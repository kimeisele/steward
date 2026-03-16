"""Tests for healer helper functions — package extraction, TOML editing, PR body."""

from __future__ import annotations

from dataclasses import dataclass

from steward.healer.helpers import _add_dependency_to_toml, _build_pr_body, _extract_package_from_finding
from steward.senses.diagnostic_sense import FindingKind, Severity


@dataclass(frozen=True)
class _FakeFinding:
    kind: FindingKind = FindingKind.UNDECLARED_DEPENDENCY
    severity: Severity = Severity.CRITICAL
    file: str = ""
    line: int = 0
    detail: str = ""
    fix_hint: str = ""


# ── _extract_package_from_finding ──────────────────────────────────────


class TestExtractPackage:
    def test_quoted_in_fix_hint(self):
        f = _FakeFinding(fix_hint="Add 'pyyaml' to [project.dependencies]")
        assert _extract_package_from_finding(f) == "pyyaml"

    def test_double_quoted_in_fix_hint(self):
        f = _FakeFinding(fix_hint='Add "requests" to [project.dependencies]')
        assert _extract_package_from_finding(f) == "requests"

    def test_pip_install_in_fix_hint(self):
        f = _FakeFinding(fix_hint="pip install flask")
        assert _extract_package_from_finding(f) == "flask"

    def test_quoted_in_detail(self):
        f = _FakeFinding(fix_hint="do something", detail="'boto3' is imported but not declared")
        assert _extract_package_from_finding(f) == "boto3"

    def test_no_match_returns_empty(self):
        f = _FakeFinding(fix_hint="fix it", detail="something is wrong")
        assert _extract_package_from_finding(f) == ""

    def test_hyphenated_package(self):
        f = _FakeFinding(fix_hint="Add 'python-dateutil' to deps")
        assert _extract_package_from_finding(f) == "python-dateutil"

    def test_underscore_package(self):
        f = _FakeFinding(fix_hint="Add 'my_package' to deps")
        assert _extract_package_from_finding(f) == "my_package"


# ── _add_dependency_to_toml ──────────────────────────────────────────


class TestAddDependencyToToml:
    def test_multiline_deps(self):
        toml = (
            '[project]\nname = "foo"\n'
            'dependencies = [\n    "existing>=1.0",\n]\n'
        )
        result = _add_dependency_to_toml(toml, "newpkg")
        assert '"newpkg",' in result
        assert '"existing>=1.0",' in result

    def test_empty_array(self):
        toml = '[project]\ndependencies = []\n'
        result = _add_dependency_to_toml(toml, "flask")
        assert '"flask"' in result

    def test_single_line_with_items(self):
        toml = '[project]\ndependencies = ["foo"]\n'
        result = _add_dependency_to_toml(toml, "bar")
        assert '"bar"' in result
        assert '"foo"' in result

    def test_no_deps_section_returns_unchanged(self):
        toml = "[project]\nname = 'foo'\n"
        result = _add_dependency_to_toml(toml, "bar")
        assert result == toml

    def test_preserves_indentation(self):
        toml = '[project]\ndependencies = [\n        "big-indent",\n]\n'
        result = _add_dependency_to_toml(toml, "newpkg")
        lines = result.splitlines()
        # New dep should match existing indentation
        new_dep_line = [ln for ln in lines if "newpkg" in ln][0]
        assert new_dep_line.startswith("        ")


# ── _build_pr_body ──────────────────────────────────────────────────


class TestBuildPrBody:
    def test_all_succeeded(self):
        findings = [
            (_FakeFinding(kind=FindingKind.NO_CI, detail="No CI workflow"), True),
            (_FakeFinding(kind=FindingKind.NO_TESTS, detail="No tests dir"), True),
        ]
        body = _build_pr_body(findings, gate_passed=True)
        assert "[x] no_ci:" in body
        assert "[x] no_tests:" in body
        assert "CircuitBreaker" in body

    def test_some_rolled_back(self):
        findings = [
            (_FakeFinding(kind=FindingKind.NO_CI, detail="No CI"), True),
            (_FakeFinding(kind=FindingKind.SYNTAX_ERROR, detail="Bad syntax"), False),
        ]
        body = _build_pr_body(findings, gate_passed=False)
        assert "[x] no_ci:" in body
        assert "[ ] syntax_error:" in body
        assert "rolled back" in body
        assert "CircuitBreaker" not in body

    def test_empty_findings(self):
        body = _build_pr_body([], gate_passed=True)
        assert "Steward Autonomous Healing" in body
