"""
Gandha — Detection / Pattern Recognition.

PrakritiElement #9 — Protocol Layer: detect
Category: TANMATRA (Subtle Element)

In Sankhya, Gandha is the subtle element of smell — detection.
It answers: "WHAT patterns do I detect?" in the accumulated impressions.

Gandha examines Chitta's impressions and detects:
    - Stuck loops (identical calls repeated)
    - Error cascades (consecutive failures)
    - Failure redirects (known fix patterns)
    - Blind writes (writing without reading first)
    - Duplicate reads (same file read twice)
    - Tool streaks (same tool overused)
    - Error ratio (systemic failure)

All detection is STATELESS and DETERMINISTIC — zero LLM tokens.
Gandha receives impressions, returns detections.
Buddhi decides what to do with them.
"""

from __future__ import annotations

from dataclasses import dataclass

from steward.antahkarana.chitta import Impression

# Thresholds — deterministic, no magic numbers
MAX_IDENTICAL_CALLS = 3  # same tool + same params = stuck
MAX_CONSECUTIVE_ERRORS = 5  # too many errors in a row = abort
MAX_SAME_TOOL_STREAK = 8  # same tool name repeatedly = likely stuck
ERROR_RATIO_THRESHOLD = 0.7  # > 70% of calls failing = systemic issue


@dataclass(frozen=True)
class Detection:
    """A detected pattern from Gandha analysis.

    Gandha detects, Buddhi decides. The severity is a hint,
    not a command — Buddhi may override.

    Severities:
        abort    — unrecoverable, stop the loop
        redirect — known fix pattern, suggest alternative
        reflect  — inject reflection prompt
        info     — informational only
    """

    severity: str  # "abort" | "redirect" | "reflect" | "info"
    pattern: str  # name of the detected pattern
    reason: str = ""  # human-readable explanation
    suggestion: str = ""  # what to do about it


def detect_patterns(
    impressions: list[Impression],
    prior_reads: frozenset[str] = frozenset(),
) -> Detection | None:
    """Run all detection checks against impressions.

    Returns the first detected pattern (ordered by severity),
    or None if no patterns detected. Stateless — pure function.

    Args:
        impressions: Current turn's recorded tool impressions
        prior_reads: Files read in previous turns (cross-turn awareness)
    """
    # Standard checks (no cross-turn context needed)
    simple_checks = [
        _check_consecutive_errors,
        _check_identical_calls,
        _check_failure_redirect,
        _check_duplicate_read,
        _check_tool_streak,
        _check_error_ratio,
    ]

    for check in simple_checks:
        result = check(impressions)
        if result is not None:
            return result

    # Cross-turn aware checks
    result = _check_write_without_read(impressions, prior_reads)
    if result is not None:
        return result

    return None


def _check_consecutive_errors(impressions: list[Impression]) -> Detection | None:
    """Detect too many consecutive errors."""
    if len(impressions) < MAX_CONSECUTIVE_ERRORS:
        return None

    recent = impressions[-MAX_CONSECUTIVE_ERRORS:]
    if all(not r.success for r in recent):
        unique_errors = set(r.error[:80] for r in recent if r.error)
        return Detection(
            severity="abort",
            pattern="consecutive_errors",
            reason=f"{MAX_CONSECUTIVE_ERRORS} consecutive errors",
            suggestion=(
                f"Errors: {'; '.join(unique_errors) if unique_errors else 'unknown'}. "
                f"This approach is not working."
            ),
        )
    return None


def _check_identical_calls(impressions: list[Impression]) -> Detection | None:
    """Detect repeated identical tool calls (same name + same params)."""
    if len(impressions) < MAX_IDENTICAL_CALLS:
        return None

    recent = impressions[-MAX_IDENTICAL_CALLS:]
    if all(
        r.name == recent[0].name and r.params_hash == recent[0].params_hash
        for r in recent
    ):
        return Detection(
            severity="reflect",
            pattern="identical_calls",
            reason=f"Identical call repeated {MAX_IDENTICAL_CALLS}x: {recent[0].name}",
            suggestion=(
                f"Tool '{recent[0].name}' called with same parameters "
                f"{MAX_IDENTICAL_CALLS} times. Try a different approach or "
                f"different parameters."
            ),
        )
    return None


def _check_failure_redirect(impressions: list[Impression]) -> Detection | None:
    """Redirect to a better tool when failure patterns are recognizable.

    Deterministic pattern matching — common failure modes have known fixes:
    - edit_file failing with "not found" -> read_file first
    - write_file failing -> read_file the target path first
    - Repeated route misses -> suggest available tools
    """
    if len(impressions) < 2:
        return None

    recent = impressions[-2:]

    # Pattern: edit_file failed twice -> need to read the file first
    if all(
        r.name == "edit_file"
        and not r.success
        and ("not found" in r.error.lower() or "no match" in r.error.lower())
        for r in recent
    ):
        return Detection(
            severity="redirect",
            pattern="edit_needs_read",
            reason="edit_file failed 2x — old_string not found in file",
            suggestion=(
                "Use read_file to see the current file contents, "
                "then retry edit_file with the exact string from the file."
            ),
        )

    # Pattern: write_file failed twice -> likely path or permission issue
    if all(r.name == "write_file" and not r.success for r in recent):
        return Detection(
            severity="redirect",
            pattern="write_path_issue",
            reason="write_file failed 2x",
            suggestion=(
                "Use read_file or glob to verify the target path exists "
                "and is writable, then retry."
            ),
        )

    # Pattern: route misses (tool not found) -> suggest valid tools
    if (
        all(
            "route miss" in r.error.lower() or "not found" in r.error.lower()
            for r in recent
            if not r.success
        )
        and sum(1 for r in recent if not r.success) >= 2
    ):
        return Detection(
            severity="redirect",
            pattern="route_miss",
            reason="Repeated tool route misses — requesting non-existent tools",
            suggestion=(
                "Available tools: bash, read_file, write_file, edit_file, "
                "glob, grep. Use only these tool names."
            ),
        )

    return None


_WRITE_TOOL_NAMES = frozenset({"edit_file", "write_file"})
_READ_TOOL_NAMES = frozenset({"read_file"})


def _check_write_without_read(
    impressions: list[Impression],
    prior_reads: frozenset[str] = frozenset(),
) -> Detection | None:
    """Detect writing/editing a file that was never read — blind write.

    Only triggers if the MOST RECENT impression is a successful write/edit
    to a file that was never read in this turn OR in prior turns.

    Cross-turn aware: if you read a file last turn and edit it this turn,
    Gandha knows it's safe.

    ToolSafetyGuard (Iron Dome) blocks at the tool level.
    Gandha detects the PATTERN and gives better guidance.
    """
    if not impressions:
        return None

    last = impressions[-1]
    if last.name not in _WRITE_TOOL_NAMES or not last.success or not last.path:
        return None

    # Check prior turns first (cross-turn awareness)
    if last.path in prior_reads:
        return None  # Read in a previous turn — safe

    # Check current turn
    for imp in impressions[:-1]:
        if (
            imp.name in _READ_TOOL_NAMES
            and imp.success
            and imp.path == last.path
        ):
            return None  # File was read this turn — all good

    return Detection(
        severity="redirect",
        pattern="write_without_read",
        reason=f"Blind write to '{last.path}' — file was never read first",
        suggestion=(
            f"You wrote to '{last.path}' without reading it first. "
            f"Use read_file to understand the current contents before "
            f"making changes. This prevents incorrect edits."
        ),
    )


def _check_duplicate_read(impressions: list[Impression]) -> Detection | None:
    """Detect reading the same file twice — wasted tokens.

    Only triggers if the MOST RECENT impression is a duplicate read.
    The file was already read successfully earlier in this turn.
    """
    if len(impressions) < 2:
        return None

    last = impressions[-1]
    if last.name != "read_file" or not last.success or not last.path:
        return None

    # Check if this path was already read successfully earlier
    for imp in impressions[:-1]:
        if (
            imp.name == "read_file"
            and imp.success
            and imp.path == last.path
        ):
            return Detection(
                severity="redirect",
                pattern="duplicate_read",
                reason=f"File already read: {last.path}",
                suggestion=(
                    f"You already read '{last.path}' earlier in this turn. "
                    f"Use the content from your earlier read instead of re-reading."
                ),
            )

    return None


def _check_tool_streak(impressions: list[Impression]) -> Detection | None:
    """Detect using the same tool too many times in a row."""
    if len(impressions) < MAX_SAME_TOOL_STREAK:
        return None

    recent = impressions[-MAX_SAME_TOOL_STREAK:]
    if all(r.name == recent[0].name for r in recent):
        # Exception: read_file streak is often legitimate (exploring codebase)
        if recent[0].name == "read_file":
            return None
        return Detection(
            severity="reflect",
            pattern="tool_streak",
            reason=f"Same tool '{recent[0].name}' used {MAX_SAME_TOOL_STREAK}x consecutively",
            suggestion=(
                f"Consider whether '{recent[0].name}' is the right tool. "
                f"Try reading files for context or using a different approach."
            ),
        )
    return None


def _check_error_ratio(impressions: list[Impression]) -> Detection | None:
    """Check if the overall error rate is too high."""
    if len(impressions) < 6:
        return None

    total = len(impressions)
    errors = sum(1 for r in impressions if not r.success)
    ratio = errors / total

    if ratio >= ERROR_RATIO_THRESHOLD:
        return Detection(
            severity="reflect",
            pattern="error_ratio",
            reason=f"Error ratio {ratio:.0%} exceeds threshold ({ERROR_RATIO_THRESHOLD:.0%})",
            suggestion=(
                f"{errors}/{total} tool calls failed. "
                f"Reconsider the overall approach."
            ),
        )
    return None
