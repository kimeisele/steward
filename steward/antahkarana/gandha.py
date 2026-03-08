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
from enum import StrEnum

from steward.antahkarana.chitta import Impression

# Thresholds — deterministic, no magic numbers
MAX_IDENTICAL_CALLS = 3  # same tool + same params = stuck
MAX_CONSECUTIVE_ERRORS = 5  # too many errors in a row = abort
MAX_SAME_TOOL_STREAK = 8  # same tool name repeatedly = likely stuck
ERROR_RATIO_THRESHOLD = 0.7  # > 70% of calls failing = systemic issue


class VerdictAction(StrEnum):
    """Verdict/detection actions — single source of truth.

    Shared between Detection.severity and BuddhiVerdict.action.
    StrEnum so values flow directly from Gandha to Buddhi.
    """

    CONTINUE = "continue"  # proceed normally (verdict only)
    REFLECT = "reflect"  # inject reflection prompt
    REDIRECT = "redirect"  # suggest alternative approach
    ABORT = "abort"  # stop the loop (unrecoverable)
    INFO = "info"  # informational only (detection only)


@dataclass(frozen=True)
class Detection:
    """A detected pattern from Gandha analysis.

    Gandha detects, Buddhi decides. The severity is a hint,
    not a command — Buddhi may override.
    """

    severity: VerdictAction
    pattern: str  # name of the detected pattern
    reason: str = ""  # human-readable explanation
    suggestion: str = ""  # what to do about it


def detect_patterns(
    impressions: list[Impression],
    prior_reads: frozenset[str] = frozenset(),
    available_tools: frozenset[str] | None = None,
) -> Detection | None:
    """Run all detection checks against impressions.

    Returns the first detected pattern (ordered by severity),
    or None if no patterns detected. Stateless — pure function.

    Args:
        impressions: Current turn's recorded tool impressions
        prior_reads: Files read in previous turns (cross-turn awareness)
        available_tools: Currently available tool names (for route miss guidance)
    """
    # Standard checks (no cross-turn context needed)
    for check in [
        _check_consecutive_errors,
        _check_identical_calls,
        _check_duplicate_read,
        _check_tool_streak,
        _check_error_ratio,
    ]:
        result = check(impressions)
        if result is not None:
            return result

    # Failure redirect (needs available tools for guidance)
    result = _check_failure_redirect(impressions, available_tools)
    if result is not None:
        return result

    # Error recovery — match error text against known fix patterns
    result = _check_error_recovery(impressions)
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
            severity=VerdictAction.ABORT,
            pattern="consecutive_errors",
            reason=f"{MAX_CONSECUTIVE_ERRORS} consecutive errors",
            suggestion=(
                f"Errors: {'; '.join(unique_errors) if unique_errors else 'unknown'}. This approach is not working."
            ),
        )
    return None


def _check_identical_calls(impressions: list[Impression]) -> Detection | None:
    """Detect repeated identical tool calls (same name + same params)."""
    if len(impressions) < MAX_IDENTICAL_CALLS:
        return None

    recent = impressions[-MAX_IDENTICAL_CALLS:]
    if all(r.name == recent[0].name and r.params_hash == recent[0].params_hash for r in recent):
        return Detection(
            severity=VerdictAction.REFLECT,
            pattern="identical_calls",
            reason=f"Identical call repeated {MAX_IDENTICAL_CALLS}x: {recent[0].name}",
            suggestion=(
                f"Tool '{recent[0].name}' called with same parameters "
                f"{MAX_IDENTICAL_CALLS} times. Try a different approach or "
                f"different parameters."
            ),
        )
    return None


def _check_failure_redirect(
    impressions: list[Impression],
    available_tools: frozenset[str] | None = None,
) -> Detection | None:
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
        r.name == "edit_file" and not r.success and ("not found" in r.error.lower() or "no match" in r.error.lower())
        for r in recent
    ):
        return Detection(
            severity=VerdictAction.REDIRECT,
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
            severity=VerdictAction.REDIRECT,
            pattern="write_path_issue",
            reason="write_file failed 2x",
            suggestion=("Use read_file or glob to verify the target path exists and is writable, then retry."),
        )

    # Pattern: route misses (tool not found) -> suggest valid tools
    if (
        all("route miss" in r.error.lower() or "not found" in r.error.lower() for r in recent if not r.success)
        and sum(1 for r in recent if not r.success) >= 2
    ):
        tool_list = (
            ", ".join(sorted(available_tools))
            if available_tools
            else "bash, read_file, write_file, edit_file, glob, grep, sub_agent"
        )
        return Detection(
            severity=VerdictAction.REDIRECT,
            pattern="route_miss",
            reason="Repeated tool route misses — requesting non-existent tools",
            suggestion=f"Available tools: {tool_list}. Use only these tool names.",
        )

    return None


# ── Error Recovery Patterns ──────────────────────────────────────────
#
# Deterministic mapping: error text pattern → concrete fix suggestion.
# Gandha reads the error, suggests the fix. Zero LLM tokens.
# Patterns are checked in order — first match wins.

_ERROR_RECOVERY: list[tuple[str, str, str]] = [
    # (error_substring, pattern_name, fix_suggestion)
    (
        "modulenotfounderror",
        "missing_module",
        "Install the missing module: run `bash` with `pip install <module_name>`. "
        "Check the error for the exact module name.",
    ),
    (
        "no module named",
        "missing_module",
        "Module not installed. Use `bash` to run `pip install <module>`. "
        "If it's a local module, check the import path.",
    ),
    (
        "permissionerror",
        "permission_denied",
        "Permission denied. Check file ownership with `ls -la`. "
        "For directories, try `mkdir -p` before writing. "
        "Avoid `chmod 777` — use minimal permissions.",
    ),
    (
        "permission denied",
        "permission_denied",
        "Permission denied. Use `ls -la` to check ownership. If you need elevated access, use `sudo` cautiously.",
    ),
    (
        "filenotfounderror",
        "file_not_found",
        "File or directory not found. Use `glob` to search for the file, "
        "or `bash` with `mkdir -p` to create missing directories.",
    ),
    (
        "no such file or directory",
        "file_not_found",
        "Path does not exist. Use `glob` to find the correct path, or create the directory with `mkdir -p`.",
    ),
    (
        "syntaxerror",
        "syntax_error",
        "File has a syntax error. Use `read_file` to inspect the file, "
        "then `edit_file` to fix the syntax. Run the linter/interpreter to verify.",
    ),
    (
        "jsondecodeerror",
        "json_error",
        "Malformed JSON. Use `read_file` to see the actual content, then fix the JSON structure with `edit_file`.",
    ),
    (
        "command not found",
        "missing_command",
        "Command not installed. Use `bash` with the system package manager (brew/apt/pip) to install it.",
    ),
    (
        "connectionrefusederror",
        "connection_refused",
        "Service not running or port not open. Check if the service is up "
        "with `bash` (e.g., `lsof -i :<port>` or `docker ps`).",
    ),
    (
        "connection refused",
        "connection_refused",
        "Service not responding. Verify the service is running and the correct host:port is being used.",
    ),
    (
        "timeouterror",
        "timeout",
        "Operation timed out. Increase the timeout parameter, or check network connectivity / service health.",
    ),
    (
        "timed out",
        "timeout",
        "Request timed out. Try with a longer timeout, or verify the target is reachable.",
    ),
    (
        "importerror",
        "import_error",
        "Import failed — wrong package version or missing dependency. "
        "Run `pip show <package>` to check version, `pip install --upgrade` if needed.",
    ),
    (
        "merge conflict",
        "git_conflict",
        "Git merge conflict. Use `read_file` to see conflict markers, "
        "then `edit_file` to resolve them. Run `git add` + `git commit` after.",
    ),
    (
        "fatal: not a git repository",
        "not_git_repo",
        "Not inside a git repository. Use `bash` with `git init` or navigate to the correct directory.",
    ),
    (
        "address already in use",
        "port_in_use",
        "Port already in use. Find the process with `lsof -i :<port>` and stop it, or use a different port.",
    ),
    (
        "disk quota exceeded",
        "disk_full",
        "Disk is full. Free space with `df -h` to check, then remove unnecessary files.",
    ),
    (
        "memoryerror",
        "out_of_memory",
        "Out of memory. Reduce batch size, process data in chunks, or close other applications.",
    ),
]


def _check_error_recovery(impressions: list[Impression]) -> Detection | None:
    """Match the most recent error against known fix patterns.

    Only triggers on the latest impression if it's a failure.
    Scans error text against _ERROR_RECOVERY patterns (first match wins).
    """
    if not impressions:
        return None

    last = impressions[-1]
    if last.success or not last.error:
        return None

    error_lower = last.error.lower()
    for substring, pattern_name, suggestion in _ERROR_RECOVERY:
        if substring in error_lower:
            return Detection(
                severity=VerdictAction.REDIRECT,
                pattern=f"error_recovery:{pattern_name}",
                reason=f"Recognized error: {pattern_name} in {last.name}",
                suggestion=suggestion,
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
        if imp.name in _READ_TOOL_NAMES and imp.success and imp.path == last.path:
            return None  # File was read this turn — all good

    return Detection(
        severity=VerdictAction.REDIRECT,
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
        if imp.name == "read_file" and imp.success and imp.path == last.path:
            return Detection(
                severity=VerdictAction.REDIRECT,
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
            severity=VerdictAction.REFLECT,
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
            severity=VerdictAction.REFLECT,
            pattern="error_ratio",
            reason=f"Error ratio {ratio:.0%} exceeds threshold ({ERROR_RATIO_THRESHOLD:.0%})",
            suggestion=(f"{errors}/{total} tool calls failed. Reconsider the overall approach."),
        )
    return None
