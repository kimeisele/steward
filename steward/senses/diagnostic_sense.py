"""
DiagnosticSense — Deep structural repo analysis for cross-repo diagnostics.

A Jnanendriya (knowledge sense) that deterministically analyzes a target
repo at the AST level. 0 LLM tokens — pure infrastructure observation.

Produces ATOMIC findings — each one typed, actionable, with a fix hint
that a cheap LLM (or pure Python) can execute without reasoning.

Analysis layers:
  1. Structure   — files, packages, test infrastructure, CI
  2. Imports     — AST-level broken import detection (handles relative imports)
  3. Dependencies — pyproject.toml declared vs actually imported
  4. Federation  — .well-known descriptor, peer.json, capabilities
  5. CI          — workflow status via gh CLI (optional, network-dependent)

Each layer produces Finding objects. Findings have severity + fix_hint.
"""

from __future__ import annotations

import ast
import enum
import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("STEWARD.SENSE.DIAGNOSTIC")

_MAX_FILES = 500


class Severity(enum.Enum):
    """Finding severity — drives priority of fix."""

    CRITICAL = "critical"  # Blocks execution (broken imports, missing deps)
    WARNING = "warning"  # Degraded (no CI, no tests, no federation)
    INFO = "info"  # Observable (large files, low cohesion)


class FindingKind(enum.Enum):
    """What category of problem was found."""

    BROKEN_IMPORT = "broken_import"
    MISSING_DEPENDENCY = "missing_dependency"
    UNDECLARED_DEPENDENCY = "undeclared_dependency"
    SYNTAX_ERROR = "syntax_error"
    NO_TESTS = "no_tests"
    NO_CI = "no_ci"
    CI_FAILING = "ci_failing"
    NO_FEDERATION_DESCRIPTOR = "no_federation_descriptor"
    NO_PEER_JSON = "no_peer_json"
    LARGE_FILE = "large_file"
    CIRCULAR_IMPORT = "circular_import"
    NADI_BLOCKED = "nadi_blocked"


@dataclass(frozen=True)
class Finding:
    """Single atomic diagnostic finding — typed, actionable, fixable.

    Each finding is self-contained: a cheap LLM or pure Python can
    execute fix_hint without understanding the broader codebase.
    """

    kind: FindingKind
    severity: Severity
    file: str  # relative path (or "" for repo-level)
    line: int = 0  # 0 = file-level
    detail: str = ""  # human-readable explanation
    fix_hint: str = ""  # atomic fix instruction (machine-executable)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "severity": self.severity.value,
            "file": self.file,
            "line": self.line,
            "detail": self.detail,
            "fix_hint": self.fix_hint,
        }


@dataclass(frozen=True)
class CIStatus:
    """CI workflow status from gh run list."""

    workflow: str
    conclusion: str  # success, failure, cancelled, ""
    status: str  # completed, in_progress, queued


@dataclass(frozen=True)
class DiagnosticReport:
    """Structured diagnostic output — atomic findings, no prose."""

    repo: str
    clone_ok: bool = False
    findings: tuple[Finding, ...] = ()
    # Structure
    python_file_count: int = 0
    test_file_count: int = 0
    total_lines: int = 0
    packages: tuple[str, ...] = ()
    # Dependencies
    declared_deps: tuple[str, ...] = ()
    imported_third_party: tuple[str, ...] = ()
    # Federation
    has_federation_descriptor: bool = False
    federation_descriptor: dict = field(default_factory=dict)
    has_peer_json: bool = False
    peer_capabilities: tuple[str, ...] = ()
    # CI
    ci_statuses: tuple[CIStatus, ...] = ()
    ci_error: str = ""
    # Errors during analysis
    errors: tuple[str, ...] = ()

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.WARNING)

    @property
    def is_healthy(self) -> bool:
        """Healthy = cloned OK + zero critical findings."""
        return self.clone_ok and self.critical_count == 0

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "clone_ok": self.clone_ok,
            "is_healthy": self.is_healthy,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "findings": [f.to_dict() for f in self.findings],
            "python_file_count": self.python_file_count,
            "test_file_count": self.test_file_count,
            "total_lines": self.total_lines,
            "packages": list(self.packages),
            "declared_deps": list(self.declared_deps),
            "imported_third_party": list(self.imported_third_party),
            "has_federation_descriptor": self.has_federation_descriptor,
            "has_peer_json": self.has_peer_json,
            "peer_capabilities": list(self.peer_capabilities),
            "ci_statuses": [
                {"workflow": ci.workflow, "conclusion": ci.conclusion, "status": ci.status} for ci in self.ci_statuses
            ],
            "ci_error": self.ci_error,
            "errors": list(self.errors),
        }


# ── Analysis Functions (pure, no side effects) ────────────────────────


def _skip_path(parts: tuple[str, ...]) -> bool:
    """Skip hidden dirs, caches, venvs."""
    return any(p.startswith(".") or p == "__pycache__" or p in ("venv", ".venv", "node_modules", ".tox") for p in parts)


def _analyze_imports(
    repo_path: Path,
) -> tuple[
    list[Finding],  # findings
    set[str],  # all third-party top-level modules imported
    int,  # python file count
    int,  # test file count
    int,  # total lines
    list[str],  # packages
]:
    """AST-level import analysis. Detects broken imports, syntax errors.

    Correctly handles relative imports (level > 0). Only flags absolute
    imports where the top-level module cannot be found in:
      - Python stdlib
      - The repo's own packages
      - Installed site-packages
    """
    import sys

    stdlib_modules = getattr(sys, "stdlib_module_names", set())

    findings: list[Finding] = []
    third_party: set[str] = set()
    py_file_count = 0
    test_file_count = 0
    total_lines = 0
    packages: list[str] = []

    # Discover repo-local packages (dirs with __init__.py)
    local_packages: set[str] = set()
    for init in repo_path.rglob("__init__.py"):
        rel = init.parent.relative_to(repo_path)
        parts = rel.parts
        if _skip_path(parts):
            continue
        if parts:
            local_packages.add(parts[0])
            packages.append(str(rel))

    py_files = sorted(repo_path.rglob("*.py"))[:_MAX_FILES]

    for f in py_files:
        rel = f.relative_to(repo_path)
        parts = rel.parts
        if _skip_path(parts):
            continue

        py_file_count += 1
        rel_str = str(rel)

        if "test" in rel_str.lower():
            test_file_count += 1

        try:
            source = f.read_text(encoding="utf-8", errors="replace")
            total_lines += source.count("\n") + 1
            tree = ast.parse(source, filename=rel_str)
        except SyntaxError as e:
            findings.append(
                Finding(
                    kind=FindingKind.SYNTAX_ERROR,
                    severity=Severity.CRITICAL,
                    file=rel_str,
                    line=getattr(e, "lineno", 0) or 0,
                    detail=f"SyntaxError: {e.msg}" if hasattr(e, "msg") else str(e),
                    fix_hint=f"Fix syntax error in {rel_str}",
                )
            )
            continue
        except (OSError, UnicodeDecodeError):
            continue

        # Walk AST for imports
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    # Relative import — valid within the package, skip
                    continue
                if not node.module:
                    continue
                top = node.module.split(".")[0]
                names = [a.name for a in (node.names or [])]

                # Classify
                if top in stdlib_modules or top == "__future__":
                    continue
                if top in local_packages:
                    # Local package — check if the specific submodule/name exists
                    _check_local_import(repo_path, node.module, names, rel_str, node.lineno, findings)
                    continue

                # Third-party
                third_party.add(top)
                # Check if actually importable — use find_spec to avoid executing
                # arbitrary code in third-party __init__.py modules
                import importlib.util

                spec = importlib.util.find_spec(node.module)
                if spec is None:
                    # Try just the top-level package
                    top_spec = importlib.util.find_spec(top)
                    if top_spec is not None:
                        # Top-level exists but submodule doesn't
                        findings.append(
                            Finding(
                                kind=FindingKind.BROKEN_IMPORT,
                                severity=Severity.CRITICAL,
                                file=rel_str,
                                line=node.lineno,
                                detail=f"from {node.module} import {names} — submodule not found",
                                fix_hint=f"Check if '{node.module}' was renamed or moved in latest version of '{top}'",
                            )
                        )
                    else:
                        findings.append(
                            Finding(
                                kind=FindingKind.MISSING_DEPENDENCY,
                                severity=Severity.CRITICAL,
                                file=rel_str,
                                line=node.lineno,
                                detail=f"from {node.module} import {names} — package '{top}' not installed",
                                fix_hint=f"pip install {top}",
                            )
                        )

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in stdlib_modules or top in local_packages:
                        continue
                    third_party.add(top)

        # Large file check
        line_count = source.count("\n") + 1
        if line_count > 800:
            findings.append(
                Finding(
                    kind=FindingKind.LARGE_FILE,
                    severity=Severity.INFO,
                    file=rel_str,
                    detail=f"{line_count} lines — consider splitting",
                    fix_hint=f"Split {rel_str} into focused modules (LCOM4 analysis recommended)",
                )
            )

    return findings, third_party, py_file_count, test_file_count, total_lines, packages[:50]


def _check_local_import(
    repo_path: Path,
    module: str,
    names: list[str],
    from_file: str,
    lineno: int,
    findings: list[Finding],
) -> None:
    """Check if a local (intra-repo) import actually resolves to a file."""
    parts = module.split(".")
    # Try to find the module file
    possible = repo_path / Path(*parts)
    if (possible.with_suffix(".py")).exists():
        return  # File exists
    if (possible / "__init__.py").exists():
        return  # Package exists

    # The import target doesn't exist as a file — broken internal reference
    findings.append(
        Finding(
            kind=FindingKind.BROKEN_IMPORT,
            severity=Severity.CRITICAL,
            file=from_file,
            line=lineno,
            detail=f"from {module} import {names} — local module not found",
            fix_hint=f"Module '{module}' does not exist at {possible}.py or {possible}/__init__.py",
        )
    )


def _detect_circular_imports(repo_path: Path) -> list[Finding]:
    """Build import graph from AST and detect cycles via DFS.

    Only considers intra-repo (local package) imports — third-party
    and stdlib are excluded. Reports the shortest cycle found per file.
    """
    # Discover local packages
    local_packages: set[str] = set()
    for init in repo_path.rglob("__init__.py"):
        rel = init.parent.relative_to(repo_path)
        parts = rel.parts
        if _skip_path(parts):
            continue
        if parts:
            local_packages.add(parts[0])

    # Build adjacency list: file → set of local files it imports
    graph: dict[str, set[str]] = {}
    py_files = sorted(repo_path.rglob("*.py"))[:_MAX_FILES]

    for f in py_files:
        rel = f.relative_to(repo_path)
        parts = rel.parts
        if _skip_path(parts):
            continue
        rel_str = str(rel)
        graph.setdefault(rel_str, set())

        try:
            source = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=rel_str)
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue

        # Collect imports that are inside TYPE_CHECKING guards (skip those)
        type_checking_ranges: list[tuple[int, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                # Detect `if TYPE_CHECKING:` pattern
                test = node.test
                if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                    end_line = max((getattr(n, "end_lineno", 0) or getattr(n, "lineno", 0)) for n in ast.walk(node))
                    type_checking_ranges.append((node.lineno, end_line))
                elif isinstance(test, ast.Attribute) and getattr(test, "attr", "") == "TYPE_CHECKING":
                    end_line = max((getattr(n, "end_lineno", 0) or getattr(n, "lineno", 0)) for n in ast.walk(node))
                    type_checking_ranges.append((node.lineno, end_line))

        # Also collect function/method bodies (deferred imports don't cause cycles)
        deferred_ranges: list[tuple[int, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = max((getattr(n, "end_lineno", 0) or getattr(n, "lineno", 0)) for n in ast.walk(node))
                deferred_ranges.append((node.lineno, end_line))

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                # Skip imports inside TYPE_CHECKING blocks
                if any(start <= node.lineno <= end for start, end in type_checking_ranges):
                    continue
                # Skip imports inside function bodies (deferred — don't cause load-time cycles)
                if any(start <= node.lineno <= end for start, end in deferred_ranges):
                    continue
                top = node.module.split(".")[0]
                if top not in local_packages:
                    continue
                # Resolve module path to file path
                mod_parts = node.module.split(".")
                target = repo_path / Path(*mod_parts)
                if target.with_suffix(".py").exists():
                    target_str = str(target.with_suffix(".py").relative_to(repo_path))
                elif (target / "__init__.py").exists():
                    target_str = str((target / "__init__.py").relative_to(repo_path))
                else:
                    continue
                graph[rel_str].add(target_str)

    # DFS cycle detection
    findings: list[Finding] = []
    reported_cycles: set[frozenset[str]] = set()

    def _dfs(node: str, path: list[str], visited: set[str]) -> None:
        if node in visited:
            # Found cycle — extract it
            if node in path:
                cycle_start = path.index(node)
                cycle = path[cycle_start:]
                cycle_key = frozenset(cycle)
                if cycle_key not in reported_cycles:
                    reported_cycles.add(cycle_key)
                    cycle_str = " → ".join(cycle + [node])
                    findings.append(
                        Finding(
                            kind=FindingKind.CIRCULAR_IMPORT,
                            severity=Severity.WARNING,
                            file=node,
                            detail=f"Circular import: {cycle_str}",
                            fix_hint=f"Break cycle by moving imports in {node} behind TYPE_CHECKING guard",
                        )
                    )
            return
        visited.add(node)
        path.append(node)
        for neighbor in graph.get(node, set()):
            _dfs(neighbor, path, visited)
        path.pop()

    visited: set[str] = set()
    for node in graph:
        if node not in visited:
            _dfs(node, [], visited)

    return findings


def _analyze_dependencies(repo_path: Path, imported: set[str]) -> tuple[list[Finding], list[str]]:
    """Compare pyproject.toml declared deps vs actual imports."""
    findings: list[Finding] = []

    pyproject = repo_path / "pyproject.toml"
    if not pyproject.exists():
        findings.append(
            Finding(
                kind=FindingKind.MISSING_DEPENDENCY,
                severity=Severity.WARNING,
                file="",
                detail="No pyproject.toml found",
                fix_hint="Create pyproject.toml with project dependencies",
            )
        )
        return findings, []

    # Parse dependencies from pyproject.toml (basic TOML parsing without tomllib)
    declared: list[str] = []
    try:
        text = pyproject.read_text()
        declared = _parse_deps_from_toml(text)
        # Also include optional-dependencies (dev, test, kernel, etc.)
        optional = _parse_optional_deps_from_toml(text)
        declared = declared + optional
    except Exception as e:
        logger.warning("Failed to parse dependencies from pyproject.toml: %s", e)

    # Normalize: pip package names use - but import names use _
    declared_normalized = {d.lower().replace("-", "_").split("[")[0] for d in declared}

    # Check for undeclared third-party imports
    # Common mapping: package name != import name
    _KNOWN_MAPPINGS = {
        "pyyaml": "yaml",
        "python_dateutil": "dateutil",
        "pillow": "PIL",
        "scikit_learn": "sklearn",
        "python_dotenv": "dotenv",
        "pygithub": "github",
        "google_generativeai": "google",
        "tavily_python": "tavily",
        "python_telegram_bot": "telegram",
        "steward_protocol": ("steward", "vibe_core", "pydantic", "openai", "google", "yaml"),
    }
    declared_import_names = set()
    for d in declared_normalized:
        declared_import_names.add(d)
        if d in _KNOWN_MAPPINGS:
            mapping = _KNOWN_MAPPINGS[d]
            if isinstance(mapping, tuple):
                for m in mapping:
                    declared_import_names.add(m.lower())
            else:
                declared_import_names.add(mapping.lower())

    for imp in sorted(imported):
        if imp.lower() not in declared_import_names:
            findings.append(
                Finding(
                    kind=FindingKind.UNDECLARED_DEPENDENCY,
                    severity=Severity.WARNING,
                    file="pyproject.toml",
                    detail=f"'{imp}' is imported but not declared in dependencies",
                    fix_hint=f"Add '{imp}' to [project.dependencies] in pyproject.toml",
                )
            )

    return findings, declared


def _is_real_bracket_close(line: str) -> bool:
    """Check if ] in line is the real array close, not inside a quoted string."""
    # Strip the line and check: if it's just ']' or starts with ']', it's a real close
    stripped = line.strip()
    if stripped == "]":
        return True
    # Count quotes before first ]: if even, it's real; if odd, it's inside string
    idx = stripped.find("]")
    if idx < 0:
        return False
    quote_count = stripped[:idx].count('"')
    return quote_count % 2 == 0


def _parse_deps_from_toml(text: str) -> list[str]:
    """Extract dependency names from pyproject.toml without tomllib.

    Handles the common pattern:
    [project]
    dependencies = [
        "package>=1.0",
        "other-package",
    ]
    """
    deps: list[str] = []
    in_deps = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("dependencies") and "=" in stripped:
            in_deps = True
            # Handle single-line: dependencies = ["foo"]
            if "[" in stripped:
                rest = stripped.split("[", 1)[1]
                if _is_real_bracket_close(rest):
                    items = rest.split("]")[0]
                    for item in items.split(","):
                        name = _extract_package_name(item)
                        if name:
                            deps.append(name)
                    in_deps = False
            continue
        if in_deps:
            if _is_real_bracket_close(stripped):
                # Last item before closing bracket
                before = stripped.split("]")[0]
                name = _extract_package_name(before)
                if name:
                    deps.append(name)
                in_deps = False
            else:
                name = _extract_package_name(stripped)
                if name:
                    deps.append(name)
    return deps


def _parse_optional_deps_from_toml(text: str) -> list[str]:
    """Extract dependency names from [project.optional-dependencies] sections."""
    deps: list[str] = []
    in_optional = False
    in_array = False
    for line in text.splitlines():
        stripped = line.strip()
        # Detect [project.optional-dependencies] section headers like: key = [...]
        if in_optional and stripped.startswith("[") and not stripped.startswith('"'):
            # New section header — stop parsing optional deps
            in_optional = False
            in_array = False
            if stripped.startswith("[project.optional-dependencies]"):
                in_optional = True
            continue
        if stripped == "[project.optional-dependencies]":
            in_optional = True
            continue
        if not in_optional:
            continue
        # Inside optional-dependencies section
        if "=" in stripped and not in_array:
            # e.g. dev = ["pytest>=7.0", ...]
            if "[" in stripped:
                rest = stripped.split("[", 1)[1]
                if _is_real_bracket_close(rest):
                    # Single line: dev = ["pytest>=7.0", "ruff"]
                    items = rest.split("]")[0]
                    for item in items.split(","):
                        name = _extract_package_name(item)
                        if name:
                            deps.append(name)
                else:
                    # Multi-line start
                    in_array = True
                    # Parse items after [
                    for item in rest.split(","):
                        name = _extract_package_name(item)
                        if name:
                            deps.append(name)
        elif in_array:
            if _is_real_bracket_close(stripped):
                before = stripped.split("]")[0]
                name = _extract_package_name(before)
                if name:
                    deps.append(name)
                in_array = False
            else:
                name = _extract_package_name(stripped)
                if name:
                    deps.append(name)
    return deps


def _extract_package_name(item: str) -> str:
    """Extract package name from a dependency string like '"ecdsa>=0.18"'."""
    item = item.strip().strip(",").strip('"').strip("'").strip()
    if not item:
        return ""
    # Split on version specifiers
    for sep in (">=", "<=", "==", "!=", ">", "<", "~=", "[", ";"):
        item = item.split(sep)[0]
    return item.strip()


def _analyze_federation(repo_path: Path) -> tuple[list[Finding], bool, dict, bool, tuple[str, ...]]:
    """Check federation readiness."""
    findings: list[Finding] = []

    descriptor_path = repo_path / ".well-known" / "agent-federation.json"
    has_descriptor = descriptor_path.exists()
    descriptor: dict = {}
    if has_descriptor:
        try:
            descriptor = json.loads(descriptor_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("Federation descriptor parse failed: %s", e)
    else:
        findings.append(
            Finding(
                kind=FindingKind.NO_FEDERATION_DESCRIPTOR,
                severity=Severity.WARNING,
                file=".well-known/agent-federation.json",
                detail="No federation descriptor — repo is invisible to the network",
                fix_hint="Create .well-known/agent-federation.json with kind, version, repo_id, status fields",
            )
        )

    peer_path = repo_path / "data" / "federation" / "peer.json"
    has_peer = peer_path.exists()
    peer_caps: tuple[str, ...] = ()
    if has_peer:
        try:
            peer_data = json.loads(peer_path.read_text())
            peer_caps = tuple(peer_data.get("capabilities", []))
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("peer.json parse failed: %s", e)
    else:
        findings.append(
            Finding(
                kind=FindingKind.NO_PEER_JSON,
                severity=Severity.WARNING,
                file="data/federation/peer.json",
                detail="No peer.json — capabilities unknown to federation",
                fix_hint="Create data/federation/peer.json with identity, capabilities, endpoint fields",
            )
        )

    # Check if nadi transport files are blocked by gitignore
    gitignore_path = repo_path / ".gitignore"
    if gitignore_path.exists() and has_peer:
        try:
            gitignore = gitignore_path.read_text()
            # data/ or data/* without !data/federation/ exception blocks nadi
            if ("data/" in gitignore or "data/*" in gitignore) and "!data/federation" not in gitignore:
                findings.append(
                    Finding(
                        kind=FindingKind.NADI_BLOCKED,
                        severity=Severity.WARNING,
                        file=".gitignore",
                        detail="Nadi transport blocked by .gitignore — federation messages cannot flow",
                        fix_hint="Add '!data/federation/' exception to .gitignore after 'data/' or 'data/*'",
                    )
                )
        except OSError:
            pass

    return findings, has_descriptor, descriptor, has_peer, peer_caps


def _analyze_ci(repo_path: Path) -> tuple[list[Finding], tuple[CIStatus, ...], str]:
    """Check CI status via gh CLI and workflow files."""
    findings: list[Finding] = []
    ci_statuses: list[CIStatus] = []
    ci_error = ""

    # Check for workflow files
    workflows_dir = repo_path / ".github" / "workflows"
    if not workflows_dir.exists() or not any(workflows_dir.glob("*.yml")):
        findings.append(
            Finding(
                kind=FindingKind.NO_CI,
                severity=Severity.WARNING,
                file=".github/workflows/",
                detail="No GitHub Actions workflows found",
                fix_hint="Add .github/workflows/ci.yml with pytest and lint steps",
            )
        )

    # Try gh run list (may fail without network/auth — that's fine)
    try:
        result = subprocess.run(
            ["gh", "run", "list", "--limit=5", "--json=name,conclusion,status"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(repo_path),
        )
        if result.returncode == 0 and result.stdout.strip():
            runs = json.loads(result.stdout)
            seen_workflows: set[str] = set()
            for run in runs:
                wf_name = run.get("name", "")
                ci_statuses.append(
                    CIStatus(
                        workflow=wf_name,
                        conclusion=run.get("conclusion", ""),
                        status=run.get("status", ""),
                    )
                )
                # Only flag the MOST RECENT run of each workflow
                if wf_name not in seen_workflows:
                    seen_workflows.add(wf_name)
                    if run.get("conclusion") == "failure":
                        findings.append(
                            Finding(
                                kind=FindingKind.CI_FAILING,
                                severity=Severity.CRITICAL,
                                file="",
                                detail=f"CI workflow '{wf_name}' is failing",
                                fix_hint="Run 'gh run view' to see failure details, then fix the failing tests/lint",
                            )
                        )
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        ci_error = str(e)[:200]

    return findings, tuple(ci_statuses), ci_error


def _analyze_test_infrastructure(repo_path: Path, test_file_count: int) -> list[Finding]:
    """Check test infrastructure health."""
    findings: list[Finding] = []

    if test_file_count == 0:
        findings.append(
            Finding(
                kind=FindingKind.NO_TESTS,
                severity=Severity.WARNING,
                file="",
                detail="No test files found",
                fix_hint="Create tests/ directory with test_*.py files",
            )
        )

    return findings


# ── Main Diagnostic Entry Point ──────────────────────────────────────


def diagnose_repo(repo_url: str, *, timeout: int = 60) -> DiagnosticReport:
    """Run deep structural diagnostic on a target repo. 0 LLM tokens.

    Accepts local path or git URL. Shallow-clones if remote.
    Returns DiagnosticReport with atomic Finding objects.
    """
    errors: list[str] = []
    clone_dir = None
    should_cleanup = False

    try:
        repo_path = Path(repo_url)
        if repo_path.is_dir():
            # Local path — analyze directly, no clone needed
            clone_ok = True
        else:
            # Remote — shallow clone
            clone_dir = Path(tempfile.mkdtemp(prefix="steward_diag_"))
            should_cleanup = True
            try:
                subprocess.run(
                    ["git", "clone", "--depth=1", "--single-branch", repo_url, str(clone_dir / "repo")],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=True,
                )
                repo_path = clone_dir / "repo"
                clone_ok = True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                errors.append(f"clone failed: {e}")
                return DiagnosticReport(repo=repo_url, clone_ok=False, errors=tuple(errors))

        # Layer 1+2: Structure + Import analysis (AST-level, no subprocess)
        import_findings, third_party, py_count, test_count, total_lines, packages = _analyze_imports(repo_path)

        # Layer 3: Dependency analysis
        dep_findings, declared_deps = _analyze_dependencies(repo_path, third_party)

        # Layer 4: Federation analysis
        fed_findings, has_descriptor, descriptor, has_peer, peer_caps = _analyze_federation(repo_path)

        # Layer 5: CI analysis
        ci_findings, ci_statuses, ci_error = _analyze_ci(repo_path)

        # Layer 6: Test infrastructure
        test_findings = _analyze_test_infrastructure(repo_path, test_count)

        # Layer 7: Circular import detection (import graph DFS)
        circular_findings = _detect_circular_imports(repo_path)

        # Combine all findings, sort by severity
        all_findings = import_findings + dep_findings + fed_findings + ci_findings + test_findings + circular_findings
        severity_order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
        all_findings.sort(key=lambda f: severity_order.get(f.severity, 9))

        return DiagnosticReport(
            repo=repo_url,
            clone_ok=clone_ok,
            findings=tuple(all_findings),
            python_file_count=py_count,
            test_file_count=test_count,
            total_lines=total_lines,
            packages=tuple(packages),
            declared_deps=tuple(declared_deps),
            imported_third_party=tuple(sorted(third_party)),
            has_federation_descriptor=has_descriptor,
            federation_descriptor=descriptor,
            has_peer_json=has_peer,
            peer_capabilities=peer_caps,
            ci_statuses=ci_statuses,
            ci_error=ci_error,
            errors=tuple(errors),
        )

    except Exception as e:
        errors.append(f"unexpected: {e}")
        return DiagnosticReport(repo=repo_url, errors=tuple(errors))

    finally:
        if should_cleanup and clone_dir and clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)
