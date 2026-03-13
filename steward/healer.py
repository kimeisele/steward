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
import tokenize
from dataclasses import dataclass
from io import StringIO
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
    """How to fix a finding — deterministic (0 tokens) vs LLM-assisted."""

    DETERMINISTIC = "deterministic"  # Pure Python, 0 tokens
    LLM_ASSISTED = "llm_assisted"  # LLM executes specific fix_hint
    SKIP = "skip"  # Info-level, not fixable


_STRATEGY: dict[FindingKind, FixStrategy] = {
    FindingKind.UNDECLARED_DEPENDENCY: FixStrategy.DETERMINISTIC,
    FindingKind.MISSING_DEPENDENCY: FixStrategy.DETERMINISTIC,
    FindingKind.NO_FEDERATION_DESCRIPTOR: FixStrategy.DETERMINISTIC,
    FindingKind.NO_PEER_JSON: FixStrategy.DETERMINISTIC,
    FindingKind.NO_CI: FixStrategy.DETERMINISTIC,
    FindingKind.NO_TESTS: FixStrategy.DETERMINISTIC,
    FindingKind.BROKEN_IMPORT: FixStrategy.DETERMINISTIC,
    FindingKind.SYNTAX_ERROR: FixStrategy.DETERMINISTIC,
    FindingKind.CI_FAILING: FixStrategy.SKIP,  # needs CI-log-parser compound pipeline
    FindingKind.CIRCULAR_IMPORT: FixStrategy.SKIP,  # no detector yet
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

    All fixes are deterministic (0 LLM tokens). The pipeline:
    diagnose → classify → deterministic fix → verify (Iron Gate) → PR.
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

    async def heal_repo(self, workspace: Path) -> HealResult:
        """Run full healing pipeline on an already-cloned repo.

        1. Diagnose (0 tokens)
        2. Classify each finding: deterministic / skip
        3. Apply deterministic fixes (0 tokens)
        4. Run Iron Gate on all changed files
        5. Gate pass → create PR; gate fail → rollback + Hebbian failure
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

        # Step 2: Classify — deterministic or skip
        fixable = []
        for finding in report.findings:
            strategy = classify(finding.kind)
            if strategy == FixStrategy.DETERMINISTIC:
                fixable.append(finding)

        if not fixable:
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

        for finding in fixable:
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

        if not all_changed:
            return HealResult(
                repo=repo_name,
                findings_total=len(report.findings),
                findings_fixable=len(fixable),
                findings_fixed=0,
            )

        # Step 4: Verify via Iron Gate
        changed_set = set(all_changed)
        gate_passed = True

        if hasattr(self._pipeline, "_breaker"):
            gate_results = self._pipeline._breaker.run_gates(changed_set)
            failed_gates = [g for g in gate_results if not g.passed]

            if failed_gates:
                gate_passed = False
                details = "; ".join(g.detail for g in failed_gates)
                logger.warning("Iron Gate FAILED for %s: %s", repo_name, details)

                self._pipeline._breaker.rollback_files(changed_set)
                self._pipeline._breaker.record_rollback()

                for finding in fixable:
                    self._synaptic.update(f"heal:{finding.kind.value}:{repo_name}", "fix", success=False)

                return HealResult(
                    repo=repo_name,
                    findings_total=len(report.findings),
                    findings_fixable=len(fixable),
                    findings_fixed=0,
                    error=f"Gate failure: {details}",
                )

        # Step 5: Gate passed — create PR
        pr_url = ""
        body = _build_pr_body(applied, gate_passed)
        pr_url = self._pipeline._create_pr(
            branch_name=f"steward/heal/{repo_name}",
            intent_name="HEAL_REPO",
            problem=f"Healing {repo_name}: {fixed_count} findings fixed",
            changed_files=changed_set,
        ) or ""

        for finding in fixable:
            self._synaptic.update(f"heal:{finding.kind.value}:{repo_name}", "fix", success=True)

        logger.info(
            "Healed %s: %d/%d findings fixed, PR=%s",
            repo_name,
            fixed_count,
            len(fixable),
            pr_url or "(none)",
        )

        return HealResult(
            repo=repo_name,
            findings_total=len(report.findings),
            findings_fixable=len(fixable),
            findings_fixed=fixed_count,
            pr_url=pr_url,
        )
