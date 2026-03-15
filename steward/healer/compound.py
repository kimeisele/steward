"""Compound fixers — deterministic pipeline + gated LLM fallback."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from steward.healer.fixers import _fix_undeclared_dependency
from steward.healer.types import _FIXERS
from steward.senses.diagnostic_sense import FindingKind, Severity

if TYPE_CHECKING:
    from steward.senses.diagnostic_sense import Finding

logger = logging.getLogger("STEWARD.HEALER")

_COMPOUND_FIXERS: dict[FindingKind, Callable[["Finding", Path], list[str]]] = {}


def _compound_fixer(kind: FindingKind):
    """Register a compound fixer."""

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
    # Extract workflow name from finding detail
    wf_match = re.search(r"workflow '([^']+)'", finding.detail)
    wf_name = wf_match.group(1) if wf_match else ""

    # Step 1: Try to get the CI failure log
    log_output = ""
    try:
        r = subprocess.run(
            ["gh", "run", "list", "--workflow", wf_name, "--status", "failure", "--limit", "1", "--json", "databaseId"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(workspace),
        )
        if r.returncode == 0:
            import json as _json

            runs = _json.loads(r.stdout)
            if runs:
                run_id = str(runs[0]["databaseId"])
                r2 = subprocess.run(
                    ["gh", "run", "view", run_id, "--log-failed"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=str(workspace),
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
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(workspace),
            )
            if r.returncode == 0:
                # Check what ruff changed
                r2 = subprocess.run(
                    ["git", "diff", "--name-only"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=str(workspace),
                )
                if r2.stdout.strip():
                    changed = [f.strip() for f in r2.stdout.strip().split("\n") if f.strip()]
                    return changed
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # No deterministic fixer matched → return empty to signal LLM fallback
    return []
