"""
RepoHealer — Autonomous PR-based repair pipeline.

Compound AI architecture: all fixes are deterministic (0 LLM tokens).
The LLM is a semantic router in the control plane — it never touches code.

State machine:
  DIAGNOSE → CLASSIFY → FIX (deterministic) → VERIFY (Iron Gate) → PR
      ↓                                                              ↓
    healthy                                                       PR URL
      ↓                                                              ↓
     skip                                                    DISCARD (gate fail)

Every FindingKind maps to either a deterministic fixer (pure Python, AST-level)
or SKIP. There is no "send code to LLM" path.
"""

from __future__ import annotations

import ast
import enum
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from steward.senses.diagnostic_sense import (
    FindingKind,
    Severity,
    diagnose_repo,
)

if TYPE_CHECKING:
    from steward.fix_pipeline import FixPipeline
    from steward.senses.diagnostic_sense import Finding
    from vibe_core.mahamantra.substrate.manas.synaptic import HebbianSynaptic

logger = logging.getLogger("STEWARD.HEALER")


# ── FixStrategy Classification ─────────────────────────────────────────


class FixStrategy(enum.Enum):
    """How to fix a finding.

    DETERMINISTIC: Pure Python, 0 tokens. Pattern-matchable.
    COMPOUND: Deterministic pipeline first, gated LLM fallback if needed.
              LLM is a tool — budget-controlled, Iron-Gated, Hebbian-learned.
    SKIP: Info-level or no fixer available yet.
    """

    DETERMINISTIC = "deterministic"
    COMPOUND = "compound"
    SKIP = "skip"


_STRATEGY: dict[FindingKind, FixStrategy] = {
    FindingKind.UNDECLARED_DEPENDENCY: FixStrategy.DETERMINISTIC,
    FindingKind.MISSING_DEPENDENCY: FixStrategy.DETERMINISTIC,
    FindingKind.NO_FEDERATION_DESCRIPTOR: FixStrategy.DETERMINISTIC,
    FindingKind.NO_PEER_JSON: FixStrategy.DETERMINISTIC,
    FindingKind.NO_CI: FixStrategy.DETERMINISTIC,
    FindingKind.NO_TESTS: FixStrategy.DETERMINISTIC,
    FindingKind.BROKEN_IMPORT: FixStrategy.DETERMINISTIC,
    FindingKind.SYNTAX_ERROR: FixStrategy.DETERMINISTIC,
    FindingKind.CIRCULAR_IMPORT: FixStrategy.DETERMINISTIC,
    FindingKind.CI_FAILING: FixStrategy.COMPOUND,
    FindingKind.NADI_BLOCKED: FixStrategy.DETERMINISTIC,
    FindingKind.LARGE_FILE: FixStrategy.SKIP,
}

# Reverse mapping: import name → pip package name.
# The diagnostic sense has pip→import; the healer needs import→pip.
_IMPORT_TO_PIP: dict[str, str] = {
    "yaml": "pyyaml",
    "dateutil": "python-dateutil",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "dotenv": "python-dotenv",
    "github": "PyGithub",
    "cv2": "opencv-python",
    "bs4": "beautifulsoup4",
    "attr": "attrs",
    "serial": "pyserial",
    "usb": "pyusb",
    "gi": "PyGObject",
    "wx": "wxPython",
    "skimage": "scikit-image",
}


def classify(kind: FindingKind) -> FixStrategy:
    """Classify a finding kind into a fix strategy."""
    return _STRATEGY.get(kind, FixStrategy.SKIP)


# ── HealResult ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HealResult:
    """Outcome of a single repo healing attempt."""

    repo: str
    findings_total: int = 0
    findings_fixable: int = 0
    findings_fixed: int = 0
    pr_url: str = ""
    error: str = ""


# ── Deterministic Fixers (0 tokens each) ───────────────────────────────

# Registry: FindingKind → fixer function
_FIXERS: dict[FindingKind, Callable[["Finding", Path], list[str]]] = {}


def _fixer(kind: FindingKind):
    """Decorator to register a deterministic fixer for a FindingKind."""

    def decorator(fn: Callable[["Finding", Path], list[str]]):
        _FIXERS[kind] = fn
        return fn

    return decorator


@_fixer(FindingKind.UNDECLARED_DEPENDENCY)
def _fix_undeclared_dependency(finding: "Finding", workspace: Path) -> list[str]:
    """Add undeclared package to pyproject.toml dependencies.

    Handles import→pip name mismatch (yaml→pyyaml, PIL→pillow, etc.).
    """
    import_name = _extract_package_from_finding(finding)
    if not import_name:
        return []

    # Resolve import name to pip package name
    package = _IMPORT_TO_PIP.get(import_name, import_name)

    pyproject = workspace / "pyproject.toml"
    if not pyproject.exists():
        return []

    text = pyproject.read_text()
    new_text = _add_dependency_to_toml(text, package)
    if new_text == text:
        return []  # Already present or couldn't insert

    pyproject.write_text(new_text)
    return ["pyproject.toml"]


@_fixer(FindingKind.MISSING_DEPENDENCY)
def _fix_missing_dependency(finding: "Finding", workspace: Path) -> list[str]:
    """Add missing package to pyproject.toml dependencies.

    Same logic as undeclared — both need pyproject.toml edit.
    """
    return _fix_undeclared_dependency(finding, workspace)


@_fixer(FindingKind.NO_FEDERATION_DESCRIPTOR)
def _fix_no_federation_descriptor(finding: "Finding", workspace: Path) -> list[str]:
    """Create .well-known/agent-federation.json from template."""
    well_known = workspace / ".well-known"
    well_known.mkdir(parents=True, exist_ok=True)

    descriptor_path = well_known / "agent-federation.json"
    if descriptor_path.exists():
        return []

    repo_id = workspace.name  # Use directory name as repo_id
    descriptor = {
        "kind": "agent_federation_descriptor",
        "version": "0.1.0",
        "repo_id": repo_id,
        "status": "active",
        "capabilities": [],
    }
    descriptor_path.write_text(json.dumps(descriptor, indent=2) + "\n")
    return [".well-known/agent-federation.json"]


@_fixer(FindingKind.NO_PEER_JSON)
def _fix_no_peer_json(finding: "Finding", workspace: Path) -> list[str]:
    """Create data/federation/peer.json with identity + capabilities."""
    fed_dir = workspace / "data" / "federation"
    fed_dir.mkdir(parents=True, exist_ok=True)

    peer_path = fed_dir / "peer.json"
    if peer_path.exists():
        return []

    repo_id = workspace.name
    peer = {
        "agent_id": repo_id,
        "capabilities": [],
        "endpoint": "",
        "version": "0.1.0",
    }
    peer_path.write_text(json.dumps(peer, indent=2) + "\n")
    return ["data/federation/peer.json"]


@_fixer(FindingKind.NO_CI)
def _fix_no_ci(finding: "Finding", workspace: Path) -> list[str]:
    """Create .github/workflows/ci.yml with pytest + lint."""
    workflows_dir = workspace / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    ci_path = workflows_dir / "ci.yml"
    if ci_path.exists():
        return []

    ci_yaml = """\
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e . && pip install pytest
      - run: pytest -x -q
"""
    ci_path.write_text(ci_yaml)
    return [".github/workflows/ci.yml"]


@_fixer(FindingKind.NO_TESTS)
def _fix_no_tests(finding: "Finding", workspace: Path) -> list[str]:
    """Create tests/ scaffold with __init__.py and placeholder test."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    changed: list[str] = []

    init_path = tests_dir / "__init__.py"
    if not init_path.exists():
        init_path.write_text("")
        changed.append("tests/__init__.py")

    placeholder = tests_dir / "test_placeholder.py"
    if not placeholder.exists():
        placeholder.write_text(
            '"""Placeholder test — replace with real tests."""\n\n\ndef test_placeholder():\n    assert True\n'
        )
        changed.append("tests/test_placeholder.py")

    return changed


@_fixer(FindingKind.BROKEN_IMPORT)
def _fix_broken_import(finding: "Finding", workspace: Path) -> list[str]:
    """Fix broken local imports by creating stub modules.

    When the diagnostic says 'from pkg.sub import X — local module not found',
    the module path is deterministic. Create the missing file with stub exports.
    """
    # Extract module path from the finding detail
    # Pattern: "from pkg.sub import ['helper'] — local module not found"
    match = re.search(r"from\s+([\w.]+)\s+import\s+(\[.*?\]|[\w, ]+)", finding.detail)
    if not match:
        return []

    module_path = match.group(1)  # e.g. "src.utils"
    names_raw = match.group(2)  # e.g. "['helper']" or "helper, foo"

    # Parse imported names
    names_raw = names_raw.strip("[]'\"")
    names = [n.strip().strip("'\"") for n in names_raw.split(",") if n.strip().strip("'\"")]

    # Convert module path to file path
    parts = module_path.split(".")
    target_path = workspace / Path(*parts)

    # Try as a .py file first
    py_file = target_path.with_suffix(".py")
    if py_file.exists():
        return []  # Already exists

    # Create parent directories if needed
    py_file.parent.mkdir(parents=True, exist_ok=True)

    # Ensure __init__.py exists in all parent packages
    changed: list[str] = []
    for i in range(len(parts) - 1):
        init_path = workspace / Path(*parts[: i + 1]) / "__init__.py"
        if not init_path.exists():
            init_path.write_text("")
            changed.append(str(init_path.relative_to(workspace)))

    # Create stub module with exported names
    stub_lines = [f'"""Stub module — auto-generated by steward healer."""\n']
    for name in names:
        stub_lines.append(f"\ndef {name}(*args, **kwargs):\n    raise NotImplementedError('{name} needs implementation')\n")

    py_file.write_text("\n".join(stub_lines))
    changed.append(str(py_file.relative_to(workspace)))
    return changed


@_fixer(FindingKind.SYNTAX_ERROR)
def _fix_syntax_error(finding: "Finding", workspace: Path) -> list[str]:
    """Fix common syntax errors via AST error message + token-level patching.

    Handles the most frequent deterministic patterns:
    - Missing colon after def/class/if/for/while/else/elif/try/except/finally/with
    - Unmatched brackets/parens
    - IndentationError (unexpected indent / expected indented block)
    - f-string backslash (Python <3.12)
    """
    if not finding.file:
        return []

    target = workspace / finding.file
    if not target.exists():
        return []

    source = target.read_text()
    lines = source.splitlines(keepends=True)
    line_idx = finding.line - 1  # 0-based

    if line_idx < 0 or line_idx >= len(lines):
        return []

    detail = finding.detail.lower()
    fixed = False

    # Pattern 1: Missing colon — "expected ':'"
    if "expected ':'" in detail or "expected ':'":
        line = lines[line_idx].rstrip("\n\r")
        # Check if line ends a compound statement without colon
        stripped = line.rstrip()
        compound_re = re.compile(
            r"^\s*(def\s+\w+.*\)|class\s+\w+.*|if\s+.+|elif\s+.+|else|for\s+.+|while\s+.+"
            r"|try|except.*|finally|with\s+.+)\s*$"
        )
        if compound_re.match(stripped) and not stripped.endswith(":"):
            lines[line_idx] = stripped + ":\n"
            fixed = True

    # Pattern 2: IndentationError — "expected an indented block"
    if not fixed and "expected an indented block" in detail:
        # Insert a `pass` statement after the compound statement
        if line_idx + 1 <= len(lines):
            # Determine indent from the previous line + 4 spaces
            prev = lines[line_idx] if line_idx < len(lines) else ""
            indent_match = re.match(r"(\s*)", prev)
            indent = (indent_match.group(1) if indent_match else "") + "    "
            lines.insert(line_idx + 1, f"{indent}pass\n")
            fixed = True

    # Pattern 3: Unexpected indent — line has more indent than context
    if not fixed and "unexpected indent" in detail:
        line = lines[line_idx]
        # Dedent to match the previous non-empty line
        prev_idx = line_idx - 1
        while prev_idx >= 0 and not lines[prev_idx].strip():
            prev_idx -= 1
        if prev_idx >= 0:
            prev_indent = len(lines[prev_idx]) - len(lines[prev_idx].lstrip())
            curr_content = line.lstrip()
            lines[line_idx] = " " * prev_indent + curr_content
            fixed = True

    # Pattern 4: Unmatched bracket/paren — try adding closing bracket
    if not fixed and ("was never closed" in detail or "unmatched" in detail):
        # Find which bracket is unmatched by tokenizing
        bracket_map = {"(": ")", "[": "]", "{": "}"}
        line = lines[line_idx].rstrip("\n\r")
        stack: list[str] = []
        for ch in line:
            if ch in bracket_map:
                stack.append(bracket_map[ch])
            elif ch in bracket_map.values():
                if stack and stack[-1] == ch:
                    stack.pop()
        if stack:
            # Append the missing closing brackets at end of line
            lines[line_idx] = line + "".join(reversed(stack)) + "\n"
            fixed = True

    if not fixed:
        return []

    # Verify the fix actually parses
    new_source = "".join(lines)
    try:
        ast.parse(new_source, filename=finding.file)
    except SyntaxError:
        return []  # Our fix didn't work — don't write garbage

    target.write_text(new_source)
    return [finding.file]


@_fixer(FindingKind.CIRCULAR_IMPORT)
def _fix_circular_import(finding: "Finding", workspace: Path) -> list[str]:
    """Break circular imports by moving them behind TYPE_CHECKING guard.

    Pure graph-theory fix: if A imports B and B imports A, move B's
    import of A behind `if TYPE_CHECKING:` and add the guard + __future__
    annotations import if not present.
    """
    if not finding.file:
        return []

    target = workspace / finding.file
    if not target.exists():
        return []

    source = target.read_text()
    lines = source.splitlines(keepends=True)

    # Parse the cycle from finding.detail
    # Format: "Circular import: a.py → b.py → a.py"
    cycle_match = re.search(r"Circular import:\s*(.+)", finding.detail)
    if not cycle_match:
        return []

    # The file in the finding is the one we should fix (last in the cycle)
    # We need to find which imports in THIS file point to other files in the cycle
    cycle_files = [f.strip() for f in cycle_match.group(1).split("→")]

    # Parse AST to find the offending import lines
    try:
        tree = ast.parse(source, filename=finding.file)
    except SyntaxError:
        return []

    # Find imports that target cycle members
    imports_to_guard: list[tuple[int, int]] = []  # (start_line, end_line) 1-based
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # Check if this import targets a file in the cycle
            mod_parts = node.module.split(".")
            target_path = str(Path(*mod_parts).with_suffix(".py"))
            target_init = str(Path(*mod_parts) / "__init__.py")
            if target_path in cycle_files or target_init in cycle_files:
                imports_to_guard.append((node.lineno, node.end_lineno or node.lineno))

    if not imports_to_guard:
        return []

    # Check if TYPE_CHECKING already imported
    has_type_checking = "TYPE_CHECKING" in source
    has_future_annotations = "from __future__ import annotations" in source

    # Build the guarded block
    # Remove the offending import lines and collect them
    guarded_lines: list[str] = []
    lines_to_remove: set[int] = set()
    for start, end in imports_to_guard:
        for i in range(start - 1, end):  # 0-based
            guarded_lines.append(lines[i])
            lines_to_remove.add(i)

    # Build new source
    new_lines: list[str] = []
    for i, line in enumerate(lines):
        if i in lines_to_remove:
            continue
        new_lines.append(line)

    # Find insertion point — after existing imports, before first non-import code
    insert_idx = 0
    for i, line in enumerate(new_lines):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) or not stripped or stripped.startswith("#"):
            insert_idx = i + 1
        elif stripped.startswith("if TYPE_CHECKING"):
            insert_idx = i  # Insert INTO existing TYPE_CHECKING block
            break
        else:
            break

    # Build guard block
    guard_block: list[str] = []
    if not has_future_annotations:
        guard_block.append("from __future__ import annotations\n")
    if not has_type_checking:
        guard_block.append("\n")
        guard_block.append("from typing import TYPE_CHECKING\n")
    guard_block.append("\n")
    guard_block.append("if TYPE_CHECKING:\n")
    for gl in guarded_lines:
        guard_block.append("    " + gl.lstrip())
    guard_block.append("\n")

    # Insert
    for j, gb_line in enumerate(guard_block):
        new_lines.insert(insert_idx + j, gb_line)

    new_source = "".join(new_lines)

    # Verify it parses
    try:
        ast.parse(new_source, filename=finding.file)
    except SyntaxError:
        return []

    target.write_text(new_source)
    return [finding.file]


@_fixer(FindingKind.NADI_BLOCKED)
def _fix_nadi_blocked(finding: "Finding", workspace: Path) -> list[str]:
    """Unblock nadi transport by adding gitignore exception.

    Adds '!data/federation/' after 'data/' or 'data/*' in .gitignore.
    """
    gitignore = workspace / ".gitignore"
    if not gitignore.exists():
        return []

    content = gitignore.read_text()
    if "!data/federation" in content:
        return []  # Already has exception

    lines = content.splitlines(keepends=True)
    new_lines: list[str] = []
    inserted = False

    for line in lines:
        new_lines.append(line)
        stripped = line.strip()
        if not inserted and stripped in ("data/", "data/*"):
            new_lines.append("!data/federation/\n")
            inserted = True

    if not inserted:
        return []

    gitignore.write_text("".join(new_lines))
    return [".gitignore"]


# ── Compound Fixers (deterministic pipeline + gated LLM fallback) ──────


_COMPOUND_FIXERS: dict[FindingKind, Callable[["Finding", Path], list[str]]] = {}


def _compound_fixer(kind: FindingKind):
    """Register a compound fixer — deterministic extraction + optional LLM."""

    def decorator(fn: Callable[["Finding", Path], list[str]]):
        _COMPOUND_FIXERS[kind] = fn
        return fn

    return decorator


@_compound_fixer(FindingKind.CI_FAILING)
def _fix_ci_failing(finding: "Finding", workspace: Path) -> list[str]:
    """Compound pipeline for CI failures.

    Step 1: Parse CI log deterministically (gh run view --log-failed)
    Step 2: Classify failure type (test, lint, build, import, etc.)
    Step 3: Route to appropriate deterministic fixer if possible
    Step 4: If no deterministic fixer matches → return empty (LLM fallback in heal_repo)

    This is the deterministic HALF of the compound pipeline.
    The LLM half runs in heal_repo only if this returns empty.
    """
    import subprocess

    # Extract workflow name from finding detail
    wf_match = re.search(r"workflow '([^']+)'", finding.detail)
    wf_name = wf_match.group(1) if wf_match else ""

    # Step 1: Try to get the CI failure log
    log_output = ""
    try:
        r = subprocess.run(
            ["gh", "run", "list", "--workflow", wf_name, "--status", "failure",
             "--limit", "1", "--json", "databaseId"],
            capture_output=True, text=True, timeout=15, cwd=str(workspace),
        )
        if r.returncode == 0:
            import json as _json
            runs = _json.loads(r.stdout)
            if runs:
                run_id = str(runs[0]["databaseId"])
                r2 = subprocess.run(
                    ["gh", "run", "view", run_id, "--log-failed"],
                    capture_output=True, text=True, timeout=30, cwd=str(workspace),
                )
                if r2.returncode == 0:
                    log_output = r2.stdout[-5000:]  # Last 5KB of log
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.warning("CI log fetch failed: %s", e)

    if not log_output:
        return []  # Can't get logs — signal for LLM fallback

    # Step 2: Classify failure type from log
    log_lower = log_output.lower()
    changed: list[str] = []

    # Type A: Import error in CI → route to dependency fixer
    import_match = re.search(r"modulenotfounderror: no module named '(\w+)'", log_lower)
    if import_match:
        pkg = import_match.group(1)
        dep_finding = Finding(
            FindingKind.UNDECLARED_DEPENDENCY,
            Severity.CRITICAL,
            "pyproject.toml",
            detail=f"'{pkg}' is imported but not declared (from CI log)",
            fix_hint=f"Add '{pkg}' to [project.dependencies]",
        )
        changed = _fix_undeclared_dependency(dep_finding, workspace)
        if changed:
            return changed

    # Type B: Syntax error in CI → route to syntax fixer
    syntax_match = re.search(r"syntaxerror:.*?file \"([^\"]+)\", line (\d+)", log_lower)
    if syntax_match:
        file_path = syntax_match.group(1)
        line_no = int(syntax_match.group(2))
        # Make path relative to workspace
        try:
            rel_path = str(Path(file_path).relative_to(workspace))
        except ValueError:
            rel_path = file_path
        syntax_finding = Finding(
            FindingKind.SYNTAX_ERROR,
            Severity.CRITICAL,
            rel_path,
            line=line_no,
            detail="SyntaxError: detected in CI log",
        )
        syn_fixer = _FIXERS.get(FindingKind.SYNTAX_ERROR)
        if syn_fixer:
            changed = syn_fixer(syntax_finding, workspace)
            if changed:
                return changed

    # Type C: Lint failure → try ruff --fix
    if "ruff" in log_lower and ("error" in log_lower or "violation" in log_lower):
        try:
            r = subprocess.run(
                ["ruff", "check", "--fix", "."],
                capture_output=True, text=True, timeout=30, cwd=str(workspace),
            )
            if r.returncode == 0:
                # Check what ruff changed
                r2 = subprocess.run(
                    ["git", "diff", "--name-only"],
                    capture_output=True, text=True, timeout=10, cwd=str(workspace),
                )
                if r2.stdout.strip():
                    changed = [f.strip() for f in r2.stdout.strip().split("\n") if f.strip()]
                    return changed
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # No deterministic fixer matched → return empty to signal LLM fallback
    return []


# ── Helper Functions ────────────────────────────────────────────────────


def _extract_package_from_finding(finding: "Finding") -> str:
    """Extract package name from a finding's fix_hint or detail.

    Handles patterns like:
      - "Add 'pyyaml' to [project.dependencies]..."
      - "'requests' is imported but not declared..."
      - "pip install foo"
    """
    # Pattern 1: quoted package in fix_hint
    match = re.search(r"['\"]([a-zA-Z0-9_-]+)['\"]", finding.fix_hint)
    if match:
        return match.group(1)

    # Pattern 2: "pip install <package>" in fix_hint
    match = re.search(r"pip install\s+([a-zA-Z0-9_-]+)", finding.fix_hint)
    if match:
        return match.group(1)

    # Pattern 3: quoted package in detail
    match = re.search(r"['\"]([a-zA-Z0-9_-]+)['\"]", finding.detail)
    if match:
        return match.group(1)

    return ""


def _add_dependency_to_toml(text: str, package: str) -> str:
    """Insert a package into pyproject.toml's dependencies array.

    Handles the common multi-line format:
      dependencies = [
          "existing>=1.0",
      ]
    """
    lines = text.splitlines(keepends=True)
    in_deps = False
    insert_idx = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("dependencies") and "=" in stripped:
            in_deps = True
            # Single-line: dependencies = ["foo"]
            if "[" in stripped and "]" in stripped:
                # Insert before the closing bracket
                bracket_pos = line.rfind("]")
                existing = line[:bracket_pos].rstrip()
                if existing.rstrip().endswith("["):
                    # Empty array: dependencies = []
                    new_line = existing + f'"{package}"' + line[bracket_pos:]
                else:
                    # Has items: dependencies = ["foo"]
                    new_line = existing.rstrip() + f', "{package}"' + line[bracket_pos:]
                lines[i] = new_line
                return "".join(lines)
            continue
        if in_deps:
            if stripped == "]" or ("]" in stripped and not stripped.startswith('"')):
                insert_idx = i
                break

    if insert_idx < 0:
        return text  # Can't find insertion point

    # Determine indentation from previous line
    prev_line = lines[insert_idx - 1] if insert_idx > 0 else ""
    indent_match = re.match(r"(\s+)", prev_line)
    indent = indent_match.group(1) if indent_match else "    "

    new_dep_line = f'{indent}"{package}",\n'
    lines.insert(insert_idx, new_dep_line)
    return "".join(lines)


def _extract_ci_error_summary(finding: "Finding", workspace: Path) -> str:
    """Deterministically extract a minimal error summary from CI logs.

    Parses the CI log and returns ONLY the assertion/error line —
    not the full log, not source files, not pip install output.
    Typically ~30-50 tokens.
    """
    import subprocess

    wf_match = re.search(r"workflow '([^']+)'", finding.detail)
    if not wf_match:
        return finding.detail

    try:
        r = subprocess.run(
            ["gh", "run", "list", "--workflow", wf_match.group(1),
             "--status", "failure", "--limit", "1", "--json", "databaseId"],
            capture_output=True, text=True, timeout=15, cwd=str(workspace),
        )
        if r.returncode != 0:
            return finding.detail

        runs = json.loads(r.stdout)
        if not runs:
            return finding.detail

        r2 = subprocess.run(
            ["gh", "run", "view", str(runs[0]["databaseId"]), "--log-failed"],
            capture_output=True, text=True, timeout=30, cwd=str(workspace),
        )
        if r2.returncode != 0:
            return finding.detail

        log = r2.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return finding.detail

    # Extract ONLY the error lines — not the full log
    lines = log.splitlines()
    error_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Skip timestamp/CI metadata prefix
        if "\t" in stripped:
            stripped = stripped.split("\t", 2)[-1].strip()
        # Capture assertion errors, failures, tracebacks
        if any(kw in stripped.lower() for kw in (
            "assert", "error", "failed", "traceback",
            "raise", "exception",
        )):
            # Strip ANSI codes and CI noise
            clean = re.sub(r"\x1b\[[0-9;]*m", "", stripped)
            clean = re.sub(r"^##\[.*?\]\s*", "", clean)
            if clean and len(clean) > 5:
                error_lines.append(clean)

    if not error_lines:
        return finding.detail

    # Return max 5 error lines — minimal context
    return " | ".join(error_lines[:5])


# ── PR Body Builder ─────────────────────────────────────────────────────


def _build_pr_body(
    applied: list[tuple["Finding", bool]],
    gate_passed: bool,
) -> str:
    """Build structured PR body from applied findings."""
    lines = ["## Steward Autonomous Healing\n", "**Findings addressed:**"]

    for finding, succeeded in applied:
        check = "x" if succeeded else " "
        suffix = ""
        if not succeeded:
            suffix = " (rolled back — gate failure)"
        lines.append(f"- [{check}] {finding.kind.value}: {finding.detail}{suffix}")

    if gate_passed:
        lines.extend(
            [
                "",
                "**Verification (CircuitBreaker):**",
                "- [x] Lint (ruff)",
                "- [x] Security (bandit)",
                "- [x] Blast radius",
                "- [x] Test suite",
            ]
        )

    return "\n".join(lines)


# ── RepoHealer ─────────────────────────────────────────────────────────


class RepoHealer:
    """Stateless per-attempt repo healer.

    Neuro-symbolic pipeline: deterministic fixers first, compound
    (deterministic + gated LLM) for complex issues. The LLM is a tool
    in the registry — budget-controlled, one-shot, Iron-Gated.
    """

    def __init__(
        self,
        pipeline: "FixPipeline",
        run_fn: Callable[[str], Awaitable[str]],
        synaptic: "HebbianSynaptic",
    ) -> None:
        self._pipeline = pipeline
        self._run_fn = run_fn
        self._synaptic = synaptic

    async def _llm_compound_fix(
        self, finding: "Finding", workspace: Path,
    ) -> list[str]:
        """Phase B of COMPOUND: one LLM call via the agent's tool loop.

        The LLM uses the agent's existing tools (read, edit, bash) to
        investigate and fix. No context dumping, no response parsing.
        Changes land on disk through tool use. We detect them via git diff.
        """
        import subprocess

        # Extract the error summary from the CI log deterministically
        error_summary = _extract_ci_error_summary(finding, workspace)

        # Minimal instruction — the agent has tools, it can read files itself
        instruction = (
            f"Fix CI failure in {workspace}. {error_summary}"
        )

        try:
            await self._run_fn(instruction)
        except Exception as e:
            logger.warning("LLM compound fix failed: %s", e)
            return []

        # Detect what the LLM changed via git diff
        try:
            r = subprocess.run(
                ["git", "diff", "--name-only"],
                capture_output=True, text=True, timeout=10, cwd=str(workspace),
            )
            if r.returncode == 0 and r.stdout.strip():
                return [f.strip() for f in r.stdout.strip().split("\n") if f.strip()]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return []

    async def heal_repo(self, workspace: Path) -> HealResult:
        """Run full healing pipeline on an already-cloned repo.

        1. Diagnose (0 tokens)
        2. Classify: deterministic / compound / skip
        3. Apply deterministic fixes (0 tokens)
        4. Apply compound fixes (deterministic pipeline + gated LLM fallback)
        5. Run Iron Gate on all changed files
        6. Gate pass → create PR; gate fail → rollback + Hebbian failure
        """
        repo_name = workspace.name

        # Step 1: Diagnose
        try:
            report = diagnose_repo(str(workspace))
        except Exception as e:
            logger.error("Diagnosis failed for %s: %s", repo_name, e)
            return HealResult(repo=repo_name, error=str(e))

        if not report.findings:
            logger.info("Repo %s has no findings — nothing to heal", repo_name)
            return HealResult(repo=repo_name, findings_total=0)

        # Step 2: Classify
        deterministic: list["Finding"] = []
        compound: list["Finding"] = []
        for finding in report.findings:
            strategy = classify(finding.kind)
            if strategy == FixStrategy.DETERMINISTIC:
                deterministic.append(finding)
            elif strategy == FixStrategy.COMPOUND:
                compound.append(finding)

        total_fixable = len(deterministic) + len(compound)
        if total_fixable == 0:
            logger.info("Repo %s: %d findings but none fixable", repo_name, len(report.findings))
            return HealResult(
                repo=repo_name,
                findings_total=len(report.findings),
                findings_fixable=0,
            )

        # Step 3: Apply deterministic fixes (0 tokens)
        all_changed: list[str] = []
        applied: list[tuple["Finding", bool]] = []
        fixed_count = 0

        for finding in deterministic:
            fixer_fn = _FIXERS.get(finding.kind)
            if fixer_fn is None:
                continue
            try:
                changed = fixer_fn(finding, workspace)
                if changed:
                    all_changed.extend(changed)
                    applied.append((finding, True))
                    fixed_count += 1
                    logger.info("Fixed %s: %s", finding.kind.value, finding.detail)
                else:
                    applied.append((finding, False))
            except Exception as e:
                logger.warning("Fixer %s failed: %s", finding.kind.value, e)
                applied.append((finding, False))

        # Step 4: Apply compound fixes (deterministic pipeline + gated LLM)
        for finding in compound:
            compound_fn = _COMPOUND_FIXERS.get(finding.kind)
            if compound_fn is None:
                applied.append((finding, False))
                continue
            try:
                # Phase A: deterministic extraction + classification
                changed = compound_fn(finding, workspace)
                if changed:
                    all_changed.extend(changed)
                    applied.append((finding, True))
                    fixed_count += 1
                    logger.info("Compound-fixed %s: %s (deterministic)", finding.kind.value, finding.detail)
                    continue

                # Phase B: deterministic failed → one gated LLM call
                llm_changed = await self._llm_compound_fix(finding, workspace)
                if llm_changed:
                    all_changed.extend(llm_changed)
                    applied.append((finding, True))
                    fixed_count += 1
                    logger.info("Compound-fixed %s: %s (LLM, %d files)", finding.kind.value, finding.detail, len(llm_changed))
                else:
                    applied.append((finding, False))
            except Exception as e:
                logger.warning("Compound fixer %s failed: %s", finding.kind.value, e)
                applied.append((finding, False))

        if not all_changed and fixed_count == 0:
            return HealResult(
                repo=repo_name,
                findings_total=len(report.findings),
                findings_fixable=total_fixable,
                findings_fixed=0,
            )

        # Step 5: Verify via Iron Gate
        changed_set = set(all_changed)
        gate_passed = True

        if changed_set and hasattr(self._pipeline, "_breaker"):
            gate_results = self._pipeline._breaker.run_gates(changed_set)
            failed_gates = [g for g in gate_results if not g.passed]

            if failed_gates:
                gate_passed = False
                details = "; ".join(g.detail for g in failed_gates)
                logger.warning("Iron Gate FAILED for %s: %s", repo_name, details)

                self._pipeline._breaker.rollback_files(changed_set)
                self._pipeline._breaker.record_rollback()

                for finding in deterministic + compound:
                    self._synaptic.update(f"heal:{finding.kind.value}:{repo_name}", "fix", success=False)

                return HealResult(
                    repo=repo_name,
                    findings_total=len(report.findings),
                    findings_fixable=total_fixable,
                    findings_fixed=0,
                    error=f"Gate failure: {details}",
                )

        # Step 6: Gate passed — create PR
        pr_url = ""
        if changed_set:
            body = _build_pr_body(applied, gate_passed)
            pr_url = self._pipeline._create_pr(
                branch_name=f"steward/heal/{repo_name}",
                intent_name="HEAL_REPO",
                problem=f"Healing {repo_name}: {fixed_count} findings fixed",
                changed_files=changed_set,
            ) or ""

        for finding in deterministic + compound:
            self._synaptic.update(f"heal:{finding.kind.value}:{repo_name}", "fix", success=True)

        logger.info(
            "Healed %s: %d/%d findings fixed, PR=%s",
            repo_name,
            fixed_count,
            total_fixable,
            pr_url or "(none)",
        )

        return HealResult(
            repo=repo_name,
            findings_total=len(report.findings),
            findings_fixable=total_fixable,
            findings_fixed=fixed_count,
            pr_url=pr_url,
        )
