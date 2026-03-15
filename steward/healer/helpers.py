"""Healer helper functions — package extraction, TOML editing, PR body, error summary."""

from __future__ import annotations

import ast
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steward.senses.diagnostic_sense import Finding

logger = logging.getLogger("STEWARD.HEALER")

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


