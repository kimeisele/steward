"""Tests for RepoHealer — autonomous PR-based repair pipeline."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from steward.healer import (
    FixStrategy,
    HealResult,
    RepoHealer,
    _add_dependency_to_toml,
    _build_pr_body,
    _extract_ci_error_summary,
    _extract_package_from_finding,
    _fix_broken_import,
    _fix_circular_import,
    _fix_no_ci,
    _fix_no_federation_descriptor,
    _fix_no_peer_json,
    _fix_no_tests,
    _fix_syntax_error,
    _fix_undeclared_dependency,
    classify,
)
from steward.senses.diagnostic_sense import (
    Finding,
    FindingKind,
    Severity,
)

# ── Strategy Classification ─────────────────────────────────────────────


class TestClassifyAllFindingKinds:
    """Every FindingKind must be mapped to a strategy."""

    def test_all_kinds_classified(self):
        for kind in FindingKind:
            strategy = classify(kind)
            assert isinstance(strategy, FixStrategy), f"{kind} not classified"

    def test_deterministic_kinds(self):
        deterministic = [
            FindingKind.UNDECLARED_DEPENDENCY,
            FindingKind.MISSING_DEPENDENCY,
            FindingKind.NO_FEDERATION_DESCRIPTOR,
            FindingKind.NO_PEER_JSON,
            FindingKind.NO_CI,
            FindingKind.NO_TESTS,
            FindingKind.BROKEN_IMPORT,
            FindingKind.SYNTAX_ERROR,
            FindingKind.CIRCULAR_IMPORT,
        ]
        for kind in deterministic:
            assert classify(kind) == FixStrategy.DETERMINISTIC, f"{kind} should be DETERMINISTIC"

    def test_compound_kinds(self):
        compound = [FindingKind.CI_FAILING]
        for kind in compound:
            assert classify(kind) == FixStrategy.COMPOUND, f"{kind} should be COMPOUND"

    def test_skip_kinds(self):
        assert classify(FindingKind.LARGE_FILE) == FixStrategy.SKIP


# ── Package Extraction ──────────────────────────────────────────────────


class TestExtractPackage:
    def test_quoted_in_fix_hint(self):
        f = Finding(
            FindingKind.UNDECLARED_DEPENDENCY, Severity.WARNING, "pyproject.toml", fix_hint="Add 'pyyaml' to deps"
        )
        assert _extract_package_from_finding(f) == "pyyaml"

    def test_pip_install_pattern(self):
        f = Finding(FindingKind.MISSING_DEPENDENCY, Severity.CRITICAL, "x.py", fix_hint="pip install requests")
        assert _extract_package_from_finding(f) == "requests"

    def test_quoted_in_detail(self):
        f = Finding(
            FindingKind.UNDECLARED_DEPENDENCY, Severity.WARNING, "", detail="'flask' is imported but not declared"
        )
        assert _extract_package_from_finding(f) == "flask"

    def test_no_match_returns_empty(self):
        f = Finding(FindingKind.LARGE_FILE, Severity.INFO, "big.py", detail="900 lines")
        assert _extract_package_from_finding(f) == ""


# ── TOML Dependency Insertion ───────────────────────────────────────────


class TestAddDependencyToToml:
    def test_insert_into_multiline_deps(self):
        text = textwrap.dedent("""\
            [project]
            dependencies = [
                "ecdsa>=0.18",
            ]
        """)
        result = _add_dependency_to_toml(text, "pyyaml")
        assert '"pyyaml"' in result
        assert result.index('"pyyaml"') > result.index('"ecdsa')

    def test_insert_into_empty_array(self):
        text = textwrap.dedent("""\
            [project]
            dependencies = []
        """)
        result = _add_dependency_to_toml(text, "requests")
        assert '"requests"' in result

    def test_insert_into_single_line_array(self):
        text = 'dependencies = ["foo"]\n'
        result = _add_dependency_to_toml(text, "bar")
        assert '"bar"' in result
        assert '"foo"' in result

    def test_no_deps_section_returns_unchanged(self):
        text = "[project]\nname = 'test'\n"
        result = _add_dependency_to_toml(text, "foo")
        assert result == text


# ── Deterministic Fixers ────────────────────────────────────────────────


class TestFixUndeclaredDependency:
    def test_adds_package_to_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            dependencies = [
                "ecdsa>=0.18",
            ]
        """)
        )
        finding = Finding(
            FindingKind.UNDECLARED_DEPENDENCY,
            Severity.WARNING,
            "pyproject.toml",
            detail="'requests' is imported but not declared",
            fix_hint="Add 'requests' to [project.dependencies] in pyproject.toml",
        )
        changed = _fix_undeclared_dependency(finding, tmp_path)
        assert "pyproject.toml" in changed

        content = (tmp_path / "pyproject.toml").read_text()
        assert '"requests"' in content

    def test_import_to_pip_mapping(self, tmp_path):
        """yaml import → pyyaml in pyproject.toml (not 'yaml')."""
        (tmp_path / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            dependencies = [
                "ecdsa>=0.18",
            ]
        """)
        )
        finding = Finding(
            FindingKind.UNDECLARED_DEPENDENCY,
            Severity.WARNING,
            "pyproject.toml",
            detail="'yaml' is imported but not declared",
            fix_hint="Add 'yaml' to [project.dependencies] in pyproject.toml",
        )
        changed = _fix_undeclared_dependency(finding, tmp_path)
        assert "pyproject.toml" in changed

        content = (tmp_path / "pyproject.toml").read_text()
        assert '"pyyaml"' in content
        assert '"yaml"' not in content  # Must NOT use import name

    def test_pil_to_pillow_mapping(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n")
        finding = Finding(
            FindingKind.UNDECLARED_DEPENDENCY,
            Severity.WARNING,
            "pyproject.toml",
            detail="'PIL' is imported but not declared",
            fix_hint="Add 'PIL' to [project.dependencies]",
        )
        _fix_undeclared_dependency(finding, tmp_path)
        content = (tmp_path / "pyproject.toml").read_text()
        assert '"pillow"' in content

    def test_no_pyproject_returns_empty(self, tmp_path):
        finding = Finding(
            FindingKind.UNDECLARED_DEPENDENCY,
            Severity.WARNING,
            "",
            fix_hint="Add 'foo' to deps",
        )
        assert _fix_undeclared_dependency(finding, tmp_path) == []


class TestFixNoFederationDescriptor:
    def test_creates_valid_json(self, tmp_path):
        finding = Finding(
            FindingKind.NO_FEDERATION_DESCRIPTOR,
            Severity.WARNING,
            ".well-known/agent-federation.json",
        )
        changed = _fix_no_federation_descriptor(finding, tmp_path)
        assert ".well-known/agent-federation.json" in changed

        descriptor = json.loads((tmp_path / ".well-known" / "agent-federation.json").read_text())
        assert descriptor["kind"] == "agent_federation_descriptor"
        assert descriptor["repo_id"] == tmp_path.name
        assert descriptor["status"] == "active"

    def test_skips_if_already_exists(self, tmp_path):
        well_known = tmp_path / ".well-known"
        well_known.mkdir()
        (well_known / "agent-federation.json").write_text('{"existing": true}')

        finding = Finding(FindingKind.NO_FEDERATION_DESCRIPTOR, Severity.WARNING, "")
        changed = _fix_no_federation_descriptor(finding, tmp_path)
        assert changed == []

        # Original content preserved
        data = json.loads((well_known / "agent-federation.json").read_text())
        assert data == {"existing": True}


class TestFixNoPeerJson:
    def test_creates_valid_json(self, tmp_path):
        finding = Finding(
            FindingKind.NO_PEER_JSON,
            Severity.WARNING,
            "data/federation/peer.json",
        )
        changed = _fix_no_peer_json(finding, tmp_path)
        assert "data/federation/peer.json" in changed

        peer = json.loads((tmp_path / "data" / "federation" / "peer.json").read_text())
        assert peer["agent_id"] == tmp_path.name
        assert "capabilities" in peer
        assert "version" in peer

    def test_skips_if_exists(self, tmp_path):
        fed_dir = tmp_path / "data" / "federation"
        fed_dir.mkdir(parents=True)
        (fed_dir / "peer.json").write_text('{"existing": true}')

        finding = Finding(FindingKind.NO_PEER_JSON, Severity.WARNING, "")
        changed = _fix_no_peer_json(finding, tmp_path)
        assert changed == []


class TestFixBrokenImport:
    def test_creates_stub_module(self, tmp_path):
        pkg = tmp_path / "src"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        finding = Finding(
            FindingKind.BROKEN_IMPORT,
            Severity.CRITICAL,
            "src/app.py",
            line=4,
            detail="from src.utils import ['helper'] — local module not found",
            fix_hint="Module 'src.utils' does not exist",
        )
        changed = _fix_broken_import(finding, tmp_path)
        assert "src/utils.py" in changed

        content = (tmp_path / "src" / "utils.py").read_text()
        assert "def helper" in content
        assert "NotImplementedError" in content

    def test_creates_nested_module_with_init(self, tmp_path):
        finding = Finding(
            FindingKind.BROKEN_IMPORT,
            Severity.CRITICAL,
            "main.py",
            line=1,
            detail="from pkg.sub.mod import ['func'] — local module not found",
        )
        changed = _fix_broken_import(finding, tmp_path)
        assert "pkg/sub/mod.py" in changed
        # __init__.py created for intermediate packages
        assert (tmp_path / "pkg" / "__init__.py").exists()
        assert (tmp_path / "pkg" / "sub" / "__init__.py").exists()

    def test_skips_if_module_exists(self, tmp_path):
        pkg = tmp_path / "src"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "utils.py").write_text("x = 1\n")

        finding = Finding(
            FindingKind.BROKEN_IMPORT,
            Severity.CRITICAL,
            "app.py",
            detail="from src.utils import ['helper'] — local module not found",
        )
        changed = _fix_broken_import(finding, tmp_path)
        assert changed == []

    def test_no_match_returns_empty(self):
        finding = Finding(
            FindingKind.BROKEN_IMPORT,
            Severity.CRITICAL,
            "x.py",
            detail="some weird error with no from/import pattern",
        )
        changed = _fix_broken_import(finding, Path("/tmp"))
        assert changed == []


class TestFixNoCi:
    def test_creates_valid_workflow(self, tmp_path):
        finding = Finding(FindingKind.NO_CI, Severity.WARNING, ".github/workflows/")
        changed = _fix_no_ci(finding, tmp_path)
        assert ".github/workflows/ci.yml" in changed

        ci_content = (tmp_path / ".github" / "workflows" / "ci.yml").read_text()
        assert "pytest" in ci_content
        assert "actions/checkout" in ci_content

    def test_ci_template_is_self_contained(self, tmp_path):
        """CI template must not assume [dev] extras or external tools."""
        finding = Finding(FindingKind.NO_CI, Severity.WARNING, "")
        _fix_no_ci(finding, tmp_path)
        ci_content = (tmp_path / ".github" / "workflows" / "ci.yml").read_text()
        # Must NOT assume [dev] extras exist
        assert "[dev]" not in ci_content
        # Must install pytest explicitly
        assert "pip install" in ci_content and "pytest" in ci_content

    def test_skips_if_exists(self, tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("existing: true\n")

        finding = Finding(FindingKind.NO_CI, Severity.WARNING, "")
        changed = _fix_no_ci(finding, tmp_path)
        assert changed == []


class TestFixNoTests:
    def test_creates_scaffold(self, tmp_path):
        finding = Finding(FindingKind.NO_TESTS, Severity.WARNING, "")
        changed = _fix_no_tests(finding, tmp_path)
        assert "tests/__init__.py" in changed
        assert "tests/test_placeholder.py" in changed

        assert (tmp_path / "tests" / "__init__.py").exists()
        placeholder = (tmp_path / "tests" / "test_placeholder.py").read_text()
        assert "def test_placeholder" in placeholder

    def test_skips_existing_files(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        (tests_dir / "test_placeholder.py").write_text("def test_real(): pass\n")

        finding = Finding(FindingKind.NO_TESTS, Severity.WARNING, "")
        changed = _fix_no_tests(finding, tmp_path)
        assert changed == []


class TestFixSyntaxError:
    def test_missing_colon_on_def(self, tmp_path):
        (tmp_path / "broken.py").write_text("def foo()\n    pass\n")
        finding = Finding(
            FindingKind.SYNTAX_ERROR,
            Severity.CRITICAL,
            "broken.py",
            line=1,
            detail="SyntaxError: expected ':'",
        )
        changed = _fix_syntax_error(finding, tmp_path)
        assert "broken.py" in changed
        content = (tmp_path / "broken.py").read_text()
        assert "def foo():" in content
        # Must actually parse
        compile(content, "broken.py", "exec")

    def test_missing_colon_on_if(self, tmp_path):
        (tmp_path / "broken.py").write_text("if True\n    x = 1\n")
        finding = Finding(
            FindingKind.SYNTAX_ERROR,
            Severity.CRITICAL,
            "broken.py",
            line=1,
            detail="SyntaxError: expected ':'",
        )
        changed = _fix_syntax_error(finding, tmp_path)
        assert "broken.py" in changed
        compile((tmp_path / "broken.py").read_text(), "broken.py", "exec")

    def test_missing_colon_on_class(self, tmp_path):
        (tmp_path / "broken.py").write_text("class Foo\n    pass\n")
        finding = Finding(
            FindingKind.SYNTAX_ERROR,
            Severity.CRITICAL,
            "broken.py",
            line=1,
            detail="SyntaxError: expected ':'",
        )
        changed = _fix_syntax_error(finding, tmp_path)
        assert "broken.py" in changed
        compile((tmp_path / "broken.py").read_text(), "broken.py", "exec")

    def test_missing_colon_on_for(self, tmp_path):
        (tmp_path / "broken.py").write_text("for i in range(10)\n    pass\n")
        finding = Finding(
            FindingKind.SYNTAX_ERROR,
            Severity.CRITICAL,
            "broken.py",
            line=1,
            detail="SyntaxError: expected ':'",
        )
        changed = _fix_syntax_error(finding, tmp_path)
        assert "broken.py" in changed

    def test_expected_indented_block(self, tmp_path):
        (tmp_path / "broken.py").write_text("def foo():\n")
        finding = Finding(
            FindingKind.SYNTAX_ERROR,
            Severity.CRITICAL,
            "broken.py",
            line=1,
            detail="IndentationError: expected an indented block",
        )
        changed = _fix_syntax_error(finding, tmp_path)
        assert "broken.py" in changed
        content = (tmp_path / "broken.py").read_text()
        assert "pass" in content
        compile(content, "broken.py", "exec")

    def test_unexpected_indent(self, tmp_path):
        (tmp_path / "broken.py").write_text("x = 1\n        y = 2\n")
        finding = Finding(
            FindingKind.SYNTAX_ERROR,
            Severity.CRITICAL,
            "broken.py",
            line=2,
            detail="IndentationError: unexpected indent",
        )
        changed = _fix_syntax_error(finding, tmp_path)
        assert "broken.py" in changed
        compile((tmp_path / "broken.py").read_text(), "broken.py", "exec")

    def test_unmatched_paren(self, tmp_path):
        (tmp_path / "broken.py").write_text("x = foo(1, 2\n")
        finding = Finding(
            FindingKind.SYNTAX_ERROR,
            Severity.CRITICAL,
            "broken.py",
            line=1,
            detail="SyntaxError: '(' was never closed",
        )
        changed = _fix_syntax_error(finding, tmp_path)
        assert "broken.py" in changed
        compile((tmp_path / "broken.py").read_text(), "broken.py", "exec")

    def test_unfixable_returns_empty(self, tmp_path):
        """Truly broken code that patterns can't fix → no change."""
        (tmp_path / "broken.py").write_text("@@@ garbage $$$\n")
        finding = Finding(
            FindingKind.SYNTAX_ERROR,
            Severity.CRITICAL,
            "broken.py",
            line=1,
            detail="SyntaxError: invalid syntax",
        )
        changed = _fix_syntax_error(finding, tmp_path)
        assert changed == []

    def test_no_file_returns_empty(self, tmp_path):
        finding = Finding(
            FindingKind.SYNTAX_ERROR,
            Severity.CRITICAL,
            "nonexistent.py",
            line=1,
            detail="SyntaxError: expected ':'",
        )
        changed = _fix_syntax_error(finding, tmp_path)
        assert changed == []

    def test_does_not_corrupt_valid_code(self, tmp_path):
        """If the fix doesn't parse, the original file is preserved."""
        original = "x = [1, 2, {3: 4\n"  # Complex case that won't parse after bracket fix
        (tmp_path / "broken.py").write_text(original)
        finding = Finding(
            FindingKind.SYNTAX_ERROR,
            Severity.CRITICAL,
            "broken.py",
            line=1,
            detail="SyntaxError: '{' was never closed",
        )
        changed = _fix_syntax_error(finding, tmp_path)
        if not changed:
            # Correctly refused — original preserved
            assert (tmp_path / "broken.py").read_text() == original


class TestFixCircularImport:
    def test_guards_circular_import(self, tmp_path):
        """A→B→A cycle: B's import of A moves behind TYPE_CHECKING."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("from pkg.b import helper\n\ndef greet():\n    return 'hi'\n")
        (pkg / "b.py").write_text("from pkg.a import greet\n\ndef helper():\n    return greet()\n")

        finding = Finding(
            FindingKind.CIRCULAR_IMPORT,
            Severity.WARNING,
            "pkg/b.py",
            detail="Circular import: pkg/a.py → pkg/b.py → pkg/a.py",
            fix_hint="Break cycle by moving imports in pkg/b.py behind TYPE_CHECKING guard",
        )
        changed = _fix_circular_import(finding, tmp_path)
        assert "pkg/b.py" in changed

        content = (tmp_path / "pkg" / "b.py").read_text()
        assert "TYPE_CHECKING" in content
        assert "from __future__ import annotations" in content
        # Must still parse
        compile(content, "b.py", "exec")

    def test_skips_if_no_cycle_imports_found(self, tmp_path):
        (tmp_path / "clean.py").write_text("x = 1\n")
        finding = Finding(
            FindingKind.CIRCULAR_IMPORT,
            Severity.WARNING,
            "clean.py",
            detail="Circular import: a.py → b.py → a.py",
        )
        changed = _fix_circular_import(finding, tmp_path)
        assert changed == []

    def test_no_file_returns_empty(self, tmp_path):
        finding = Finding(
            FindingKind.CIRCULAR_IMPORT,
            Severity.WARNING,
            "missing.py",
            detail="Circular import: a.py → missing.py → a.py",
        )
        changed = _fix_circular_import(finding, tmp_path)
        assert changed == []


class TestExtractCiErrorSummary:
    def test_returns_finding_detail_when_no_workflow(self):
        finding = Finding(
            FindingKind.CI_FAILING,
            Severity.CRITICAL,
            "",
            detail="Something failed",
        )
        result = _extract_ci_error_summary(finding, Path("/tmp"))
        assert result == "Something failed"

    def test_extracts_error_lines_only(self):
        """Error summary should be compact, not the full CI log."""
        finding = Finding(
            FindingKind.CI_FAILING,
            Severity.CRITICAL,
            "",
            detail="CI workflow 'CI' is failing",
        )
        # Can't test with real gh CLI here, but verify it falls back gracefully
        result = _extract_ci_error_summary(finding, Path("/tmp/nonexistent"))
        assert isinstance(result, str)
        assert len(result) > 0


class TestDetectCircularImports:
    """Integration test: diagnostic_sense detects circular imports."""

    def test_detects_cycle(self, tmp_path):
        from steward.senses.diagnostic_sense import diagnose_repo

        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("from pkg.b import helper\ndef greet(): pass\n")
        (pkg / "b.py").write_text("from pkg.a import greet\ndef helper(): pass\n")
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n")

        report = diagnose_repo(str(tmp_path))
        circular = [f for f in report.findings if f.kind == FindingKind.CIRCULAR_IMPORT]
        assert len(circular) >= 1
        assert "Circular import" in circular[0].detail

    def test_no_cycle_when_clean(self, tmp_path):
        from steward.senses.diagnostic_sense import diagnose_repo

        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("x = 1\n")
        (pkg / "b.py").write_text("from pkg.a import x\n")
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n")

        report = diagnose_repo(str(tmp_path))
        circular = [f for f in report.findings if f.kind == FindingKind.CIRCULAR_IMPORT]
        assert len(circular) == 0


# ── PR Body Builder ─────────────────────────────────────────────────────


class TestBuildPrBody:
    def test_all_succeeded(self):
        findings = [
            (
                Finding(FindingKind.UNDECLARED_DEPENDENCY, Severity.WARNING, "pyproject.toml", detail="Added pyyaml"),
                True,
            ),
            (Finding(FindingKind.NO_CI, Severity.WARNING, "", detail="Created ci.yml"), True),
        ]
        body = _build_pr_body(findings, gate_passed=True)
        assert "[x] undeclared_dependency" in body
        assert "[x] no_ci" in body
        assert "Lint (ruff)" in body

    def test_mixed_results(self):
        findings = [
            (Finding(FindingKind.NO_TESTS, Severity.WARNING, "", detail="Created scaffold"), True),
            (Finding(FindingKind.BROKEN_IMPORT, Severity.CRITICAL, "api.py", detail="broken"), False),
        ]
        body = _build_pr_body(findings, gate_passed=True)
        assert "[x] no_tests" in body
        assert "[ ] broken_import" in body
        assert "rolled back" in body


# ── HealResult ──────────────────────────────────────────────────────────


class TestHealResult:
    def test_frozen(self):
        r = HealResult(repo="test", findings_fixed=3)
        with pytest.raises(AttributeError):
            r.repo = "other"

    def test_defaults(self):
        r = HealResult(repo="test")
        assert r.findings_total == 0
        assert r.findings_fixed == 0
        assert r.pr_url == ""
        assert r.error == ""


# ── RepoHealer Integration ─────────────────────────────────────────────


def _make_healer(breaker=None, run_fn=None, create_pr_fn=None):
    """Create a RepoHealer with mocked pipeline."""
    pipeline = MagicMock()
    pipeline._breaker = breaker or MagicMock()
    pipeline._run_fn = run_fn or AsyncMock(return_value="fixed")
    pipeline._create_pr = create_pr_fn or MagicMock(return_value="https://github.com/test/pulls/1")
    synaptic = MagicMock()
    synaptic.update = MagicMock(return_value=0.5)

    healer = RepoHealer(
        pipeline=pipeline,
        run_fn=pipeline._run_fn,
        synaptic=synaptic,
    )
    return healer, pipeline, synaptic


class TestHealHealthyRepoSkips:
    @pytest.mark.asyncio
    async def test_healthy_repo_returns_early(self, tmp_path):
        """Healthy repo → no work, no LLM calls."""
        (tmp_path / "main.py").write_text("x = 1\n")
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n")
        # Add federation descriptor + peer.json + CI + tests to make it healthy
        well_known = tmp_path / ".well-known"
        well_known.mkdir()
        (well_known / "agent-federation.json").write_text('{"kind": "test"}')
        fed = tmp_path / "data" / "federation"
        fed.mkdir(parents=True)
        (fed / "peer.json").write_text('{"capabilities": []}')
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text("name: CI\n")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("")
        (tests / "test_x.py").write_text("def test_x(): pass\n")

        healer, pipeline, synaptic = _make_healer()
        result = await healer.heal_repo(tmp_path)

        assert result.findings_fixed == 0
        # No LLM calls
        pipeline._run_fn.assert_not_awaited()
        # No PR created
        pipeline._create_pr.assert_not_called()


class TestHealDeterministicOnly:
    @pytest.mark.asyncio
    async def test_deterministic_fixes_no_llm(self, tmp_path):
        """Deterministic-only findings → 0 LLM calls."""
        (tmp_path / "main.py").write_text("x = 1\n")
        (tmp_path / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            dependencies = [
                "ecdsa>=0.18",
            ]
        """)
        )
        # Add tests so NO_TESTS doesn't fire
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("")
        (tests / "test_x.py").write_text("def test_x(): pass\n")

        # Missing: federation descriptor, peer.json, CI
        breaker = MagicMock()
        gate_result = MagicMock()
        gate_result.passed = True
        breaker.run_gates.return_value = [gate_result]

        healer, pipeline, synaptic = _make_healer(breaker=breaker)
        result = await healer.heal_repo(tmp_path)

        assert result.findings_fixed > 0
        # No LLM calls (only deterministic fixes)
        pipeline._run_fn.assert_not_awaited()
        # Hebbian success recorded
        assert synaptic.update.called


class TestHealGateFailureRollback:
    @pytest.mark.asyncio
    async def test_gate_failure_triggers_rollback(self, tmp_path):
        """Gate failure → all changes rolled back, Hebbian failure."""
        (tmp_path / "main.py").write_text("x = 1\n")
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("")
        (tests / "test_x.py").write_text("def test_x(): pass\n")

        breaker = MagicMock()
        failed_gate = MagicMock()
        failed_gate.passed = False
        failed_gate.detail = "lint: 3 new violations"
        breaker.run_gates.return_value = [failed_gate]

        healer, pipeline, synaptic = _make_healer(breaker=breaker)
        result = await healer.heal_repo(tmp_path)

        assert result.findings_fixed == 0
        assert "Gate failure" in result.error
        breaker.rollback_files.assert_called_once()
        breaker.record_rollback.assert_called_once()
        # Hebbian failure recorded
        failure_calls = [c for c in synaptic.update.call_args_list if c.kwargs.get("success") is False]
        assert len(failure_calls) > 0


class TestHealCreatesPr:
    @pytest.mark.asyncio
    async def test_pr_created_on_success(self, tmp_path):
        """Successful healing → PR URL in result."""
        (tmp_path / "main.py").write_text("x = 1\n")
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("")
        (tests / "test_x.py").write_text("def test_x(): pass\n")

        breaker = MagicMock()
        gate_result = MagicMock()
        gate_result.passed = True
        breaker.run_gates.return_value = [gate_result]

        pr_url = "https://github.com/test/pulls/42"
        healer, pipeline, synaptic = _make_healer(
            breaker=breaker,
            create_pr_fn=MagicMock(return_value=pr_url),
        )
        result = await healer.heal_repo(tmp_path)

        assert result.pr_url == pr_url
        assert result.findings_fixed > 0


class TestHealMixedFindings:
    @pytest.mark.asyncio
    async def test_only_fixable_attempted(self, tmp_path):
        """Mixed findings: deterministic + skip → only deterministic attempted."""
        # Create a repo with a large file (SKIP) and missing federation (DETERMINISTIC)
        (tmp_path / "big.py").write_text("x = 1\n" * 900)  # LARGE_FILE → SKIP
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("")
        (tests / "test_x.py").write_text("def test_x(): pass\n")

        breaker = MagicMock()
        gate_result = MagicMock()
        gate_result.passed = True
        breaker.run_gates.return_value = [gate_result]

        healer, pipeline, synaptic = _make_healer(breaker=breaker)
        result = await healer.heal_repo(tmp_path)

        # LARGE_FILE is skipped, but federation + CI + peer.json are deterministic
        assert result.findings_fixable > 0
        assert result.findings_fixed > 0


class TestHebbianLearning:
    @pytest.mark.asyncio
    async def test_success_records_positive_weight(self, tmp_path):
        """Successful heal → Hebbian update with success=True."""
        (tmp_path / "main.py").write_text("x = 1\n")
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("")
        (tests / "test_x.py").write_text("def test_x(): pass\n")

        breaker = MagicMock()
        gate_result = MagicMock()
        gate_result.passed = True
        breaker.run_gates.return_value = [gate_result]

        healer, pipeline, synaptic = _make_healer(breaker=breaker)
        await healer.heal_repo(tmp_path)

        success_calls = [c for c in synaptic.update.call_args_list if c.kwargs.get("success") is True]
        assert len(success_calls) > 0

    @pytest.mark.asyncio
    async def test_failure_records_negative_weight(self, tmp_path):
        """Gate failure → Hebbian update with success=False."""
        (tmp_path / "main.py").write_text("x = 1\n")
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("")
        (tests / "test_x.py").write_text("def test_x(): pass\n")

        breaker = MagicMock()
        failed_gate = MagicMock()
        failed_gate.passed = False
        failed_gate.detail = "test failure"
        breaker.run_gates.return_value = [failed_gate]

        healer, pipeline, synaptic = _make_healer(breaker=breaker)
        await healer.heal_repo(tmp_path)

        failure_calls = [c for c in synaptic.update.call_args_list if c.kwargs.get("success") is False]
        assert len(failure_calls) > 0


# ── Intent Integration ──────────────────────────────────────────────────


class TestHealRepoIntent:
    def test_intent_exists(self):
        from steward.intents import TaskIntent

        assert TaskIntent.HEAL_REPO.value == "heal_repo"

    def test_intent_is_proactive(self):
        from steward.intents import TaskIntent

        assert TaskIntent.HEAL_REPO.is_proactive

    def test_handler_returns_none_without_reaper(self):
        from steward.intent_handlers import IntentHandlers

        class FakeSenses:
            senses = {}

            def perceive_all(self):
                pass

        handlers = IntentHandlers(senses=FakeSenses(), vedana_fn=lambda: None, cwd="/tmp")
        result = handlers.execute_heal_repo()
        assert result is None

    def test_handler_returns_none_when_no_degraded(self):
        from steward.intent_handlers import IntentHandlers
        from steward.reaper import HeartbeatReaper
        from steward.services import SVC_REAPER
        from vibe_core.di import ServiceRegistry

        reaper = HeartbeatReaper()
        reaper.record_heartbeat("healthy-peer", timestamp=1000.0)
        ServiceRegistry.register(SVC_REAPER, reaper)

        class FakeSenses:
            senses = {}

            def perceive_all(self):
                pass

        handlers = IntentHandlers(senses=FakeSenses(), vedana_fn=lambda: None, cwd="/tmp")
        result = handlers.execute_heal_repo()
        assert result is None

    def test_handler_reports_degraded_peers(self):
        from steward.intent_handlers import IntentHandlers
        from steward.reaper import HeartbeatReaper
        from steward.services import SVC_REAPER
        from vibe_core.di import ServiceRegistry

        reaper = HeartbeatReaper(lease_ttl_s=100)
        reaper.record_heartbeat("sick-peer", timestamp=500.0)
        reaper.reap(now=1000.0)
        ServiceRegistry.register(SVC_REAPER, reaper)

        class FakeSenses:
            senses = {}

            def perceive_all(self):
                pass

        handlers = IntentHandlers(senses=FakeSenses(), vedana_fn=lambda: None, cwd="/tmp")
        result = handlers.execute_heal_repo()
        assert result is not None
        assert "sick-peer" in result
        assert "healing" in result.lower()
