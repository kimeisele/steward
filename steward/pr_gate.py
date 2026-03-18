"""
PR Gate — Diagnostic pipeline for federation PR review requests.

Steward receives pr_review_request via NADI, runs diagnostics, sends verdict.
Zero LLM tokens — all checks are deterministic.

Checks:
  1. Blast radius: how many files changed? Which are core?
  2. Author check: is the author a federation peer?
  3. CI status: is CI passing on the PR branch?
"""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger("STEWARD.PR_GATE")

# Files that require council vote (not just steward approval).
# These are the constitutional files of agent-city.
CORE_FILES: frozenset[str] = frozenset(
    {
        "city/services.py",
        "city/immune.py",
        "city/immigration.py",
        "city/governance_layer.py",
        "city/civic_protocol.py",
        "city/constitution.md",
        "CLAUDE.md",
    }
)


def diagnose_pr(
    repo: str,
    pr_number: int,
    author: str,
    files: list[str],
    reaper: object | None = None,
) -> dict:
    """Run diagnostic pipeline on a PR.

    Returns dict with:
        blast_radius: int — number of files changed
        has_core_files: bool — any core files touched
        core_files_touched: list[str] — which core files
        author_is_peer: bool — author in federation peer registry
        author_trust: float — peer trust score (0.0 if unknown)
        ci_failing: bool — CI red on the PR
        ci_status: str — raw CI conclusion
    """
    result: dict = {
        "blast_radius": len(files),
        "has_core_files": False,
        "core_files_touched": [],
        "author_is_peer": False,
        "author_trust": 0.0,
        "ci_failing": False,
        "ci_status": "unknown",
    }

    # 1. Blast radius + core file detection
    core_touched = [f for f in files if _is_core_file(f)]
    result["core_files_touched"] = core_touched
    result["has_core_files"] = len(core_touched) > 0

    # 2. Author check — is the author a known federation peer?
    if reaper is not None and author:
        peer = None
        if hasattr(reaper, "get_peer"):
            peer = reaper.get_peer(author)
        if peer is not None:
            result["author_is_peer"] = True
            result["author_trust"] = getattr(peer, "trust", 0.0)
        else:
            # Check alive peers by agent_id prefix match
            for p in reaper.alive_peers():
                if p.agent_id == author or author in p.agent_id:
                    result["author_is_peer"] = True
                    result["author_trust"] = getattr(p, "trust", 0.0)
                    break

    # 3. CI status check via gh CLI
    ci_result = _check_ci_status(repo, pr_number)
    result["ci_status"] = ci_result
    result["ci_failing"] = ci_result in ("failure", "timed_out", "cancelled", "action_required")

    return result


def _is_core_file(filepath: str) -> bool:
    """Check if a file path matches any core file pattern."""
    # Exact match
    if filepath in CORE_FILES:
        return True
    # Match against basename (e.g., "src/city/services.py" matches "city/services.py")
    for core in CORE_FILES:
        if filepath.endswith(core):
            return True
    return False


def _check_ci_status(repo: str, pr_number: int) -> str:
    """Check CI status for a PR via gh CLI.

    Returns: "success", "failure", "pending", "unknown", etc.
    """
    try:
        r = subprocess.run(
            [
                "gh",
                "pr",
                "checks",
                str(pr_number),
                "-R",
                repo,
                "--json",
                "state",
                "--jq",
                ".[0].state",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().lower()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("CI check failed for %s#%s: %s", repo, pr_number, e)
    return "unknown"
