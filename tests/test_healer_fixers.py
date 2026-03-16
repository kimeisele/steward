"""Tests for deterministic healer fixers — 0 LLM tokens, pure file manipulation."""

from __future__ import annotations

import json
from dataclasses import dataclass

from steward.healer.fixers import (
    _IMPORT_TO_PIP,
    _fix_base_exception_catch,
    _fix_broken_import,
    _fix_circular_import,
    _fix_dynamic_import,
    _fix_nadi_blocked,
    _fix_no_ci,
    _fix_no_federation_descriptor,
    _fix_no_peer_json,
    _fix_no_tests,
    _fix_syntax_error,
    _fix_undeclared_dependency,
)
from steward.healer.types import _FIXERS, FixStrategy, classify
from steward.senses.diagnostic_sense import FindingKind, Severity


@dataclass(frozen=True)
class _F:
    """Minimal Finding-compatible object for tests."""

    kind: FindingKind = FindingKind.UNDECLARED_DEPENDENCY
    severity: Severity = Severity.CRITICAL
    file: str = ""
    line: int = 0
    detail: str = ""
    fix_hint: str = ""


# ── Registry & Classification ──────────────────────────────────────────


class TestFixerRegistry:
    def test_all_deterministic_kinds_have_fixers(self):
        for kind, strategy in [
            (FindingKind.UNDECLARED_DEPENDENCY, FixStrategy.DETERMINISTIC),
            (FindingKind.MISSING_DEPENDENCY, FixStrategy.DETERMINISTIC),
            (FindingKind.NO_FEDERATION_DESCRIPTOR, FixStrategy.DETERMINISTIC),
            (FindingKind.NO_PEER_JSON, FixStrategy.DETERMINISTIC),
            (FindingKind.NO_CI, FixStrategy.DETERMINISTIC),
            (FindingKind.NO_TESTS, FixStrategy.DETERMINISTIC),
            (FindingKind.BROKEN_IMPORT, FixStrategy.DETERMINISTIC),
            (FindingKind.SYNTAX_ERROR, FixStrategy.DETERMINISTIC),
            (FindingKind.CIRCULAR_IMPORT, FixStrategy.DETERMINISTIC),
            (FindingKind.NADI_BLOCKED, FixStrategy.DETERMINISTIC),
            (FindingKind.BASE_EXCEPTION_CATCH, FixStrategy.DETERMINISTIC),
            (FindingKind.DYNAMIC_IMPORT, FixStrategy.DETERMINISTIC),
        ]:
            assert classify(kind) == strategy, f"{kind} should be {strategy}"
            assert kind in _FIXERS, f"{kind} has no registered fixer"

    def test_compound_classified(self):
        assert classify(FindingKind.CI_FAILING) == FixStrategy.COMPOUND

    def test_skip_classified(self):
        assert classify(FindingKind.LARGE_FILE) == FixStrategy.SKIP

    def test_import_to_pip_mappings(self):
        assert _IMPORT_TO_PIP["yaml"] == "pyyaml"
        assert _IMPORT_TO_PIP["PIL"] == "pillow"
        assert _IMPORT_TO_PIP["sklearn"] == "scikit-learn"
        assert _IMPORT_TO_PIP["dotenv"] == "python-dotenv"


# ── _fix_undeclared_dependency ──────────────────────────────────────────


class TestFixUndeclaredDependency:
    def test_adds_to_multiline_deps(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\ndependencies = [\n    "existing>=1.0",\n]\n')
        f = _F(fix_hint="Add 'requests' to [project.dependencies]")
        changed = _fix_undeclared_dependency(f, tmp_path)
        assert changed == ["pyproject.toml"]
        assert '"requests",' in pyproject.read_text()

    def test_resolves_import_to_pip_name(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\ndependencies = [\n    "foo",\n]\n')
        f = _F(fix_hint="Add 'yaml' to deps")
        changed = _fix_undeclared_dependency(f, tmp_path)
        assert changed == ["pyproject.toml"]
        assert '"pyyaml",' in pyproject.read_text()

    def test_no_pyproject_returns_empty(self, tmp_path):
        f = _F(fix_hint="Add 'foo' to deps")
        assert _fix_undeclared_dependency(f, tmp_path) == []

    def test_no_package_name_returns_empty(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\ndependencies = []\n")
        f = _F(fix_hint="fix it", detail="something broken")
        assert _fix_undeclared_dependency(f, tmp_path) == []


# ── _fix_no_federation_descriptor ──────────────────────────────────────


class TestFixNoFederationDescriptor:
    def test_creates_descriptor(self, tmp_path):
        f = _F(kind=FindingKind.NO_FEDERATION_DESCRIPTOR)
        changed = _fix_no_federation_descriptor(f, tmp_path)
        assert ".well-known/agent-federation.json" in changed
        descriptor = json.loads((tmp_path / ".well-known" / "agent-federation.json").read_text())
        assert descriptor["kind"] == "agent_federation_descriptor"
        assert descriptor["repo_id"] == tmp_path.name

    def test_idempotent(self, tmp_path):
        f = _F(kind=FindingKind.NO_FEDERATION_DESCRIPTOR)
        _fix_no_federation_descriptor(f, tmp_path)
        assert _fix_no_federation_descriptor(f, tmp_path) == []


# ── _fix_no_peer_json ──────────────────────────────────────────────────


class TestFixNoPeerJson:
    def test_creates_peer_json(self, tmp_path):
        f = _F(kind=FindingKind.NO_PEER_JSON)
        changed = _fix_no_peer_json(f, tmp_path)
        assert "data/federation/peer.json" in changed
        peer = json.loads((tmp_path / "data" / "federation" / "peer.json").read_text())
        assert peer["agent_id"] == tmp_path.name

    def test_idempotent(self, tmp_path):
        f = _F(kind=FindingKind.NO_PEER_JSON)
        _fix_no_peer_json(f, tmp_path)
        assert _fix_no_peer_json(f, tmp_path) == []


# ── _fix_no_ci ──────────────────────────────────────────────────────────


class TestFixNoCi:
    def test_creates_ci_workflow(self, tmp_path):
        f = _F(kind=FindingKind.NO_CI)
        changed = _fix_no_ci(f, tmp_path)
        assert ".github/workflows/ci.yml" in changed
        content = (tmp_path / ".github" / "workflows" / "ci.yml").read_text()
        assert "pytest" in content
        assert "actions/checkout" in content

    def test_idempotent(self, tmp_path):
        f = _F(kind=FindingKind.NO_CI)
        _fix_no_ci(f, tmp_path)
        assert _fix_no_ci(f, tmp_path) == []


# ── _fix_no_tests ──────────────────────────────────────────────────────


class TestFixNoTests:
    def test_creates_test_scaffold(self, tmp_path):
        f = _F(kind=FindingKind.NO_TESTS)
        changed = _fix_no_tests(f, tmp_path)
        assert "tests/__init__.py" in changed
        assert "tests/test_placeholder.py" in changed
        assert (tmp_path / "tests" / "test_placeholder.py").exists()

    def test_idempotent(self, tmp_path):
        f = _F(kind=FindingKind.NO_TESTS)
        _fix_no_tests(f, tmp_path)
        assert _fix_no_tests(f, tmp_path) == []


# ── _fix_broken_import ──────────────────────────────────────────────────


class TestFixBrokenImport:
    def test_creates_stub_module(self, tmp_path):
        f = _F(
            kind=FindingKind.BROKEN_IMPORT,
            detail="from src.utils import ['helper'] — local module not found",
        )
        changed = _fix_broken_import(f, tmp_path)
        assert any("src/utils.py" in c for c in changed)
        stub = (tmp_path / "src" / "utils.py").read_text()
        assert "def helper" in stub
        assert "NotImplementedError" in stub

    def test_creates_init_files(self, tmp_path):
        f = _F(
            kind=FindingKind.BROKEN_IMPORT,
            detail="from deep.nested.mod import func — local module not found",
        )
        _fix_broken_import(f, tmp_path)
        assert (tmp_path / "deep" / "__init__.py").exists()
        assert (tmp_path / "deep" / "nested" / "__init__.py").exists()

    def test_existing_module_not_overwritten(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "utils.py").write_text("# existing\n")
        f = _F(
            kind=FindingKind.BROKEN_IMPORT,
            detail="from src.utils import helper — local module not found",
        )
        assert _fix_broken_import(f, tmp_path) == []

    def test_no_match_returns_empty(self, tmp_path):
        f = _F(kind=FindingKind.BROKEN_IMPORT, detail="random text")
        assert _fix_broken_import(f, tmp_path) == []


# ── _fix_syntax_error ──────────────────────────────────────────────────


class TestFixSyntaxError:
    def test_missing_colon_after_def(self, tmp_path):
        code = "def foo()\n    pass\n"
        target = tmp_path / "bad.py"
        target.write_text(code)
        f = _F(kind=FindingKind.SYNTAX_ERROR, file="bad.py", line=1, detail="expected ':'")
        changed = _fix_syntax_error(f, tmp_path)
        assert changed == ["bad.py"]
        assert "def foo():" in target.read_text()

    def test_missing_colon_after_class(self, tmp_path):
        code = "class Foo\n    pass\n"
        target = tmp_path / "bad.py"
        target.write_text(code)
        f = _F(kind=FindingKind.SYNTAX_ERROR, file="bad.py", line=1, detail="expected ':'")
        changed = _fix_syntax_error(f, tmp_path)
        assert changed == ["bad.py"]
        assert "class Foo:" in target.read_text()

    def test_expected_indented_block(self, tmp_path):
        code = "def foo():\n\nx = 1\n"
        target = tmp_path / "bad.py"
        target.write_text(code)
        f = _F(kind=FindingKind.SYNTAX_ERROR, file="bad.py", line=1, detail="expected an indented block")
        changed = _fix_syntax_error(f, tmp_path)
        assert changed == ["bad.py"]
        assert "pass" in target.read_text()

    def test_unmatched_bracket(self, tmp_path):
        code = "x = [1, 2, 3\ny = 4\n"
        target = tmp_path / "bad.py"
        target.write_text(code)
        f = _F(kind=FindingKind.SYNTAX_ERROR, file="bad.py", line=1, detail="'[' was never closed")
        changed = _fix_syntax_error(f, tmp_path)
        assert changed == ["bad.py"]
        assert "]" in target.read_text().splitlines()[0]

    def test_no_file_returns_empty(self, tmp_path):
        f = _F(kind=FindingKind.SYNTAX_ERROR, file="", line=1, detail="error")
        assert _fix_syntax_error(f, tmp_path) == []

    def test_missing_file_returns_empty(self, tmp_path):
        f = _F(kind=FindingKind.SYNTAX_ERROR, file="nonexistent.py", line=1, detail="error")
        assert _fix_syntax_error(f, tmp_path) == []

    def test_invalid_fix_not_written(self, tmp_path):
        """If the fix doesn't produce valid Python, file is not modified."""
        code = "def foo(bar baz):\n    pass\n"
        target = tmp_path / "bad.py"
        target.write_text(code)
        f = _F(kind=FindingKind.SYNTAX_ERROR, file="bad.py", line=1, detail="something weird")
        changed = _fix_syntax_error(f, tmp_path)
        # Either fixed or returned empty (didn't write garbage)
        if not changed:
            assert target.read_text() == code


# ── _fix_circular_import ──────────────────────────────────────────────


class TestFixCircularImport:
    def test_guards_offending_import(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\n")
        code = "from a import x\n\ndef use_x():\n    return x\n"
        (tmp_path / "b.py").write_text(code)
        f = _F(
            kind=FindingKind.CIRCULAR_IMPORT,
            file="b.py",
            detail="Circular import: a.py → b.py → a.py",
        )
        changed = _fix_circular_import(f, tmp_path)
        assert changed == ["b.py"]
        result = (tmp_path / "b.py").read_text()
        assert "TYPE_CHECKING" in result
        assert "from __future__ import annotations" in result

    def test_no_file_returns_empty(self, tmp_path):
        f = _F(kind=FindingKind.CIRCULAR_IMPORT, file="", detail="cycle")
        assert _fix_circular_import(f, tmp_path) == []

    def test_no_cycle_pattern_returns_empty(self, tmp_path):
        (tmp_path / "x.py").write_text("import os\n")
        f = _F(kind=FindingKind.CIRCULAR_IMPORT, file="x.py", detail="something wrong")
        assert _fix_circular_import(f, tmp_path) == []


# ── _fix_nadi_blocked ──────────────────────────────────────────────────


class TestFixNadiBlocked:
    def test_adds_gitignore_exception(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\ndata/\n__pycache__/\n")
        f = _F(kind=FindingKind.NADI_BLOCKED)
        changed = _fix_nadi_blocked(f, tmp_path)
        assert changed == [".gitignore"]
        content = gitignore.read_text()
        assert "!data/federation/" in content
        # Exception should appear after data/
        lines = content.splitlines()
        data_idx = lines.index("data/")
        exception_idx = lines.index("!data/federation/")
        assert exception_idx == data_idx + 1

    def test_already_has_exception(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("data/\n!data/federation/\n")
        f = _F(kind=FindingKind.NADI_BLOCKED)
        assert _fix_nadi_blocked(f, tmp_path) == []

    def test_no_gitignore(self, tmp_path):
        f = _F(kind=FindingKind.NADI_BLOCKED)
        assert _fix_nadi_blocked(f, tmp_path) == []

    def test_no_data_pattern(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__/\n")
        f = _F(kind=FindingKind.NADI_BLOCKED)
        assert _fix_nadi_blocked(f, tmp_path) == []


# ── _fix_base_exception_catch ─────────────────────────────────────────


class TestFixBaseExceptionCatch:
    def test_replaces_base_exception_with_exception(self, tmp_path):
        code = "try:\n    do_stuff()\nexcept BaseException:\n    pass\n"
        target = tmp_path / "bad.py"
        target.write_text(code)
        f = _F(kind=FindingKind.BASE_EXCEPTION_CATCH, file="bad.py", line=3)
        changed = _fix_base_exception_catch(f, tmp_path)
        assert changed == ["bad.py"]
        result = target.read_text()
        assert "except Exception:" in result
        assert "BaseException" not in result

    def test_leaves_handler_with_reraise(self, tmp_path):
        code = "try:\n    do_stuff()\nexcept BaseException:\n    cleanup()\n    raise\n"
        target = tmp_path / "ok.py"
        target.write_text(code)
        f = _F(kind=FindingKind.BASE_EXCEPTION_CATCH, file="ok.py", line=3)
        changed = _fix_base_exception_catch(f, tmp_path)
        assert changed == []
        assert "BaseException" in target.read_text()

    def test_with_as_clause(self, tmp_path):
        code = "try:\n    x()\nexcept BaseException as e:\n    log(e)\n"
        target = tmp_path / "bad.py"
        target.write_text(code)
        f = _F(kind=FindingKind.BASE_EXCEPTION_CATCH, file="bad.py", line=3)
        changed = _fix_base_exception_catch(f, tmp_path)
        assert changed == ["bad.py"]
        assert "except Exception as e:" in target.read_text()

    def test_no_file_returns_empty(self, tmp_path):
        f = _F(kind=FindingKind.BASE_EXCEPTION_CATCH, file="", line=1)
        assert _fix_base_exception_catch(f, tmp_path) == []

    def test_missing_file_returns_empty(self, tmp_path):
        f = _F(kind=FindingKind.BASE_EXCEPTION_CATCH, file="nope.py", line=1)
        assert _fix_base_exception_catch(f, tmp_path) == []


# ── _fix_dynamic_import ───────────────────────────────────────────────


class TestFixDynamicImport:
    def test_replaces_import_with_find_spec(self, tmp_path):
        code = 'import sys\n\nresult = __import__("foo")\n'
        target = tmp_path / "probe.py"
        target.write_text(code)
        f = _F(kind=FindingKind.DYNAMIC_IMPORT, file="probe.py", line=3)
        changed = _fix_dynamic_import(f, tmp_path)
        assert changed == ["probe.py"]
        result = target.read_text()
        assert "importlib.util.find_spec" in result
        assert "__import__" not in result
        assert "import importlib.util" in result

    def test_adds_importlib_import(self, tmp_path):
        code = '__import__("bar")\n'
        target = tmp_path / "probe.py"
        target.write_text(code)
        f = _F(kind=FindingKind.DYNAMIC_IMPORT, file="probe.py", line=1)
        changed = _fix_dynamic_import(f, tmp_path)
        assert changed == ["probe.py"]
        assert "import importlib.util" in target.read_text()

    def test_skips_if_importlib_already_imported(self, tmp_path):
        code = 'import importlib.util\n\n__import__("baz")\n'
        target = tmp_path / "probe.py"
        target.write_text(code)
        f = _F(kind=FindingKind.DYNAMIC_IMPORT, file="probe.py", line=3)
        changed = _fix_dynamic_import(f, tmp_path)
        assert changed == ["probe.py"]
        # Should not duplicate import
        assert target.read_text().count("import importlib.util") == 1

    def test_no_file_returns_empty(self, tmp_path):
        f = _F(kind=FindingKind.DYNAMIC_IMPORT, file="", line=1)
        assert _fix_dynamic_import(f, tmp_path) == []

    def test_missing_file_returns_empty(self, tmp_path):
        f = _F(kind=FindingKind.DYNAMIC_IMPORT, file="nope.py", line=1)
        assert _fix_dynamic_import(f, tmp_path) == []
