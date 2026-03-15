"""Tests for DiagnosticSense — deep structural repo analysis."""

import json
import textwrap

import pytest

from steward.senses.diagnostic_sense import (
    CIStatus,
    DiagnosticReport,
    Finding,
    FindingKind,
    Severity,
    _analyze_dependencies,
    _analyze_federation,
    _analyze_imports,
    _extract_package_name,
    _parse_deps_from_toml,
    _parse_optional_deps_from_toml,
    diagnose_repo,
)

# ── Finding ──────────────────────────────────────────────────────────


class TestFinding:
    def test_finding_fields(self):
        f = Finding(
            kind=FindingKind.BROKEN_IMPORT,
            severity=Severity.CRITICAL,
            file="src/api.py",
            line=42,
            detail="from foo import bar — not found",
            fix_hint="pip install foo",
        )
        assert f.kind == FindingKind.BROKEN_IMPORT
        assert f.severity == Severity.CRITICAL
        assert f.line == 42

    def test_finding_to_dict(self):
        f = Finding(
            kind=FindingKind.SYNTAX_ERROR,
            severity=Severity.CRITICAL,
            file="broken.py",
            line=10,
            detail="SyntaxError: unexpected EOF",
        )
        d = f.to_dict()
        assert d["kind"] == "syntax_error"
        assert d["severity"] == "critical"
        assert d["file"] == "broken.py"


# ── DiagnosticReport ─────────────────────────────────────────────────


class TestDiagnosticReport:
    def test_healthy_report(self):
        report = DiagnosticReport(repo="test/repo", clone_ok=True)
        assert report.is_healthy
        assert report.critical_count == 0
        assert report.warning_count == 0

    def test_unhealthy_with_critical_finding(self):
        report = DiagnosticReport(
            repo="test/repo",
            clone_ok=True,
            findings=(Finding(FindingKind.BROKEN_IMPORT, Severity.CRITICAL, "x.py", detail="broken"),),
        )
        assert not report.is_healthy
        assert report.critical_count == 1

    def test_unhealthy_clone_failure(self):
        report = DiagnosticReport(repo="test/repo", clone_ok=False)
        assert not report.is_healthy

    def test_warning_only_is_still_healthy(self):
        report = DiagnosticReport(
            repo="test/repo",
            clone_ok=True,
            findings=(Finding(FindingKind.NO_TESTS, Severity.WARNING, "", detail="no tests"),),
        )
        assert report.is_healthy
        assert report.warning_count == 1

    def test_to_dict(self):
        report = DiagnosticReport(
            repo="test/repo",
            clone_ok=True,
            python_file_count=10,
            has_federation_descriptor=True,
            peer_capabilities=("code_analysis",),
            findings=(Finding(FindingKind.LARGE_FILE, Severity.INFO, "big.py"),),
        )
        d = report.to_dict()
        assert d["repo"] == "test/repo"
        assert d["is_healthy"] is True
        assert d["python_file_count"] == 10
        assert len(d["findings"]) == 1
        assert d["findings"][0]["kind"] == "large_file"

    def test_empty_report(self):
        report = DiagnosticReport(repo="empty")
        assert not report.is_healthy
        assert report.critical_count == 0
        assert report.findings == ()


# ── AST Import Analysis ─────────────────────────────────────────────


class TestImportAnalysis:
    def test_detects_syntax_error(self, tmp_path):
        (tmp_path / "broken.py").write_text("def f(\n")
        findings, _, _, _, _, _ = _analyze_imports(tmp_path)
        assert any(f.kind == FindingKind.SYNTAX_ERROR for f in findings)

    def test_detects_broken_internal_import(self, tmp_path):
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "real.py").write_text("x = 1")
        # Import a submodule that doesn't exist
        (tmp_path / "main.py").write_text("from mypkg.nonexistent import x\n")
        findings, _, _, _, _, _ = _analyze_imports(tmp_path)
        broken = [f for f in findings if f.kind == FindingKind.BROKEN_IMPORT]
        assert len(broken) == 1
        assert "nonexistent" in broken[0].detail

    def test_skips_relative_imports(self, tmp_path):
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .sub import x\n")
        (pkg / "sub.py").write_text("x = 1\n")
        findings, _, _, _, _, _ = _analyze_imports(tmp_path)
        # Relative imports should not produce findings
        broken = [f for f in findings if f.kind == FindingKind.BROKEN_IMPORT]
        assert len(broken) == 0

    def test_counts_python_files(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\n")
        (tmp_path / "b.py").write_text("y = 2\n")
        (tmp_path / "c.txt").write_text("not python\n")
        _, _, py_count, _, _, _ = _analyze_imports(tmp_path)
        assert py_count == 2

    def test_counts_test_files(self, tmp_path):
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "__init__.py").write_text("")
        (tests / "test_foo.py").write_text("def test_x(): pass\n")
        (tmp_path / "main.py").write_text("x = 1\n")
        _, _, _, test_count, _, _ = _analyze_imports(tmp_path)
        assert test_count == 2  # test_foo.py + __init__.py under tests/

    def test_detects_large_files(self, tmp_path):
        (tmp_path / "big.py").write_text("x = 1\n" * 900)
        findings, _, _, _, _, _ = _analyze_imports(tmp_path)
        large = [f for f in findings if f.kind == FindingKind.LARGE_FILE]
        assert len(large) == 1

    def test_skips_pycache(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "mod.py").write_text("x = 1\n")
        (tmp_path / "real.py").write_text("y = 2\n")
        _, _, py_count, _, _, _ = _analyze_imports(tmp_path)
        assert py_count == 1  # Only real.py


# ── Dependency Analysis ──────────────────────────────────────────────


class TestDependencyAnalysis:
    def test_no_pyproject_warns(self, tmp_path):
        findings, deps = _analyze_dependencies(tmp_path, {"requests"})
        assert any(f.kind == FindingKind.MISSING_DEPENDENCY for f in findings)

    def test_undeclared_dependency(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            dependencies = [
                "ecdsa>=0.18",
            ]
        """)
        )
        findings, deps = _analyze_dependencies(tmp_path, {"ecdsa", "requests"})
        undeclared = [f for f in findings if f.kind == FindingKind.UNDECLARED_DEPENDENCY]
        assert len(undeclared) == 1
        assert "requests" in undeclared[0].detail

    def test_declared_deps_parsed(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            dependencies = [
                "ecdsa>=0.18",
                "pyyaml",
            ]
        """)
        )
        _, deps = _analyze_dependencies(tmp_path, set())
        assert "ecdsa" in deps
        assert "pyyaml" in deps


class TestParseToml:
    def test_parse_multiline_deps(self):
        text = textwrap.dedent("""\
            [project]
            dependencies = [
                "foo>=1.0",
                "bar",
            ]
        """)
        deps = _parse_deps_from_toml(text)
        assert deps == ["foo", "bar"]

    def test_parse_single_line_deps(self):
        text = 'dependencies = ["foo", "bar>=2"]'
        deps = _parse_deps_from_toml(text)
        assert deps == ["foo", "bar"]

    def test_parse_deps_with_extras_bracket(self):
        """Bracket inside quoted package name must NOT terminate array."""
        text = textwrap.dedent("""\
            [project]
            dependencies = [
                "steward-protocol[providers]",
                "rich>=13.0",
            ]
        """)
        deps = _parse_deps_from_toml(text)
        assert "steward-protocol" in deps
        assert "rich" in deps

    def test_extract_package_name(self):
        assert _extract_package_name('"ecdsa>=0.18",') == "ecdsa"
        assert _extract_package_name('"steward-protocol[city]"') == "steward-protocol"
        assert _extract_package_name("") == ""
        assert _extract_package_name('"pyyaml"') == "pyyaml"


class TestParseOptionalDeps:
    def test_parse_optional_deps(self):
        text = textwrap.dedent("""\
            [project]
            dependencies = ["ecdsa>=0.18"]

            [project.optional-dependencies]
            kernel = ["steward-protocol[city]"]
            dev = [
                "pytest>=7.0",
                "ruff>=0.1.0",
            ]
        """)
        deps = _parse_optional_deps_from_toml(text)
        assert "steward-protocol" in deps
        assert "pytest" in deps
        assert "ruff" in deps

    def test_empty_optional_deps(self):
        text = textwrap.dedent("""\
            [project]
            dependencies = ["ecdsa"]
        """)
        deps = _parse_optional_deps_from_toml(text)
        assert deps == []

    def test_optional_deps_not_flagged_as_undeclared(self, tmp_path):
        """Optional deps should be treated as declared — no false positives."""
        (tmp_path / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            dependencies = ["ecdsa>=0.18"]

            [project.optional-dependencies]
            dev = ["pytest>=7.0"]
            kernel = ["steward-protocol[city]"]
        """)
        )
        findings, deps = _analyze_dependencies(tmp_path, {"ecdsa", "pytest", "steward", "vibe_core"})
        undeclared = [f for f in findings if f.kind == FindingKind.UNDECLARED_DEPENDENCY]
        # pytest is in dev, steward/vibe_core come from steward-protocol
        assert len(undeclared) == 0, f"False positives: {[f.detail for f in undeclared]}"


# ── Federation Analysis ──────────────────────────────────────────────


class TestFederationAnalysis:
    def test_missing_descriptor(self, tmp_path):
        findings, has_desc, _, has_peer, _ = _analyze_federation(tmp_path)
        assert not has_desc
        assert any(f.kind == FindingKind.NO_FEDERATION_DESCRIPTOR for f in findings)

    def test_has_descriptor(self, tmp_path):
        well_known = tmp_path / ".well-known"
        well_known.mkdir()
        (well_known / "agent-federation.json").write_text(
            json.dumps(
                {
                    "kind": "agent_federation_descriptor",
                    "repo_id": "test",
                }
            )
        )
        findings, has_desc, descriptor, _, _ = _analyze_federation(tmp_path)
        assert has_desc
        assert descriptor["repo_id"] == "test"
        assert not any(f.kind == FindingKind.NO_FEDERATION_DESCRIPTOR for f in findings)

    def test_missing_peer_json(self, tmp_path):
        findings, _, _, has_peer, _ = _analyze_federation(tmp_path)
        assert not has_peer
        assert any(f.kind == FindingKind.NO_PEER_JSON for f in findings)

    def test_has_peer_json_with_capabilities(self, tmp_path):
        fed = tmp_path / "data" / "federation"
        fed.mkdir(parents=True)
        (fed / "peer.json").write_text(
            json.dumps(
                {
                    "capabilities": ["code_analysis", "ci_automation"],
                }
            )
        )
        findings, _, _, has_peer, caps = _analyze_federation(tmp_path)
        assert has_peer
        assert "code_analysis" in caps
        assert "ci_automation" in caps


# ── Full Diagnostic ──────────────────────────────────────────────────


class TestDiagnoseRepo:
    def test_nonexistent_repo_returns_clone_failure(self):
        report = diagnose_repo("/nonexistent/path/to/repo.git", timeout=10)
        assert not report.clone_ok
        assert not report.is_healthy
        assert len(report.errors) > 0

    def test_local_repo_no_clone(self, tmp_path):
        """Local path = direct analysis, no git clone."""
        (tmp_path / "main.py").write_text("x = 1\n")
        report = diagnose_repo(str(tmp_path))
        assert report.clone_ok
        assert report.python_file_count == 1

    def test_local_repo_findings(self, tmp_path):
        """Full diagnostic on a minimal repo with known issues."""
        (tmp_path / "main.py").write_text("from nonexistent_pkg import thing\n")
        (tmp_path / "pyproject.toml").write_text(
            textwrap.dedent("""\
            [project]
            dependencies = []
        """)
        )
        report = diagnose_repo(str(tmp_path))
        assert report.clone_ok
        # Should find the broken import
        assert report.critical_count >= 1
        assert not report.is_healthy
        # Should find missing federation
        assert not report.has_federation_descriptor
        assert not report.has_peer_json


# ── CIStatus ─────────────────────────────────────────────────────────


class TestCIStatus:
    def test_ci_status_fields(self):
        ci = CIStatus(workflow="CI", conclusion="success", status="completed")
        assert ci.workflow == "CI"

    def test_ci_status_frozen(self):
        ci = CIStatus("CI", "success", "completed")
        with pytest.raises(AttributeError):
            ci.conclusion = "failure"


# ── Cross-Repo Diagnostic Intent ────────────────────────────────────


class TestCrossRepoDiagnosticIntent:
    def test_intent_exists(self):
        from steward.intents import TaskIntent

        assert TaskIntent.CROSS_REPO_DIAGNOSTIC.value == "cross_repo_diagnostic"

    def test_handler_returns_none_without_reaper(self):
        from steward.intent_handlers import IntentHandlers

        class FakeSenses:
            senses = {}

            def perceive_all(self):
                pass

        handlers = IntentHandlers(senses=FakeSenses(), vedana_fn=lambda: None, cwd="/tmp")
        result = handlers.execute_cross_repo_diagnostic()
        assert result is None

    def test_handler_returns_none_when_no_degraded_peers(self):
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
        result = handlers.execute_cross_repo_diagnostic()
        assert result is None

    def test_handler_reports_degraded_peers(self):
        from steward.intent_handlers import IntentHandlers
        from steward.reaper import HeartbeatReaper
        from steward.services import SVC_REAPER
        from vibe_core.di import ServiceRegistry

        reaper = HeartbeatReaper(lease_ttl_s=100)
        reaper.record_heartbeat("dying-peer", timestamp=500.0)
        reaper.reap(now=1000.0)
        ServiceRegistry.register(SVC_REAPER, reaper)

        class FakeSenses:
            senses = {}

            def perceive_all(self):
                pass

        handlers = IntentHandlers(senses=FakeSenses(), vedana_fn=lambda: None, cwd="/tmp")
        result = handlers.execute_cross_repo_diagnostic()
        assert result is not None
        assert "dying-peer" in result
        assert "suspect" in result
