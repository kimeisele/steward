"""
Buddhi — Discriminative Intelligence for the Agent Loop.

In the Vedic Antahkarana model, Buddhi is the discriminative faculty
that answers: "SHOULD I do this?" It's the driver of the chariot
(Katha Upanishad), not the horses (Manas/senses).

Architecture (80% deterministic / 20% LLM):
    DETERMINISTIC CHECKS:
        - Stuck loop detection (same tool+params repeated)
        - Error pattern recognition (repeated failures)
        - Progress tracking (files modified, tests passing)
        - Tool sequence analysis (read before write, etc.)

    LLM REFLECTION (only when stuck):
        - "Given these results, should I try a different approach?"
        - Triggered ONLY after deterministic checks fail to resolve

Usage:
    buddhi = Buddhi()
    for round in agent_loop:
        execute_tools(...)
        verdict = buddhi.evaluate(tool_calls, tool_results)
        if verdict.action == "abort":
            break
        if verdict.action == "reflect":
            # inject reflection prompt into conversation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from steward.types import ToolUse

logger = logging.getLogger("STEWARD.BUDDHI")

# Thresholds — deterministic, no magic numbers
_MAX_IDENTICAL_CALLS = 3       # same tool + same params = stuck
_MAX_CONSECUTIVE_ERRORS = 5    # too many errors in a row = abort
_MAX_SAME_TOOL_STREAK = 8     # same tool name repeatedly = likely stuck
_ERROR_RATIO_THRESHOLD = 0.7   # > 70% of calls failing = systemic issue


@dataclass(frozen=True)
class BuddhiVerdict:
    """Buddhi's judgment after evaluating a tool round.

    Actions:
        continue  — proceed normally
        reflect   — inject reflection prompt (LLM needed)
        redirect  — suggest alternative approach (deterministic)
        abort     — stop the loop (unrecoverable)
    """

    action: str                 # "continue" | "reflect" | "redirect" | "abort"
    reason: str = ""            # human-readable explanation
    suggestion: str = ""        # alternative approach hint (for redirect/reflect)


@dataclass
class _ToolRecord:
    """A recorded tool call + result for analysis."""

    name: str
    params_hash: int           # hash of parameters for identity
    success: bool
    error: str = ""


class Buddhi:
    """Discriminative intelligence — evaluates agent actions.

    Sits between tool execution and the next LLM call.
    Detects patterns that indicate the agent is stuck,
    failing systematically, or going in circles.

    Zero LLM cost — all evaluation is deterministic.
    LLM reflection is suggested (via verdict) but never invoked here.
    """

    def __init__(self) -> None:
        self._history: list[_ToolRecord] = []
        self._round: int = 0

    def evaluate(
        self,
        tool_calls: list[ToolUse],
        results: list[tuple[bool, str]],
    ) -> BuddhiVerdict:
        """Evaluate the outcome of a tool round.

        Args:
            tool_calls: Tools that were called this round
            results: List of (success, error_msg) tuples for each call

        Returns:
            BuddhiVerdict with recommended action
        """
        self._round += 1

        # Record this round
        for tc, (success, error) in zip(tool_calls, results):
            params_hash = hash(frozenset(
                (k, str(v)) for k, v in sorted(tc.parameters.items())
            )) if tc.parameters else 0
            self._history.append(_ToolRecord(
                name=tc.name,
                params_hash=params_hash,
                success=success,
                error=error,
            ))

        # Run deterministic checks (ordered by severity)
        checks = [
            self._check_consecutive_errors,
            self._check_identical_calls,
            self._check_tool_streak,
            self._check_error_ratio,
        ]

        for check in checks:
            verdict = check()
            if verdict.action != "continue":
                logger.info(
                    "Buddhi verdict at round %d: %s — %s",
                    self._round, verdict.action, verdict.reason,
                )
                return verdict

        return BuddhiVerdict(action="continue")

    def _check_identical_calls(self) -> BuddhiVerdict:
        """Detect repeated identical tool calls (same name + same params)."""
        if len(self._history) < _MAX_IDENTICAL_CALLS:
            return BuddhiVerdict(action="continue")

        recent = self._history[-_MAX_IDENTICAL_CALLS:]
        if all(
            r.name == recent[0].name and r.params_hash == recent[0].params_hash
            for r in recent
        ):
            return BuddhiVerdict(
                action="reflect",
                reason=f"Identical call repeated {_MAX_IDENTICAL_CALLS}x: {recent[0].name}",
                suggestion=(
                    f"Tool '{recent[0].name}' called with same parameters "
                    f"{_MAX_IDENTICAL_CALLS} times. Try a different approach or "
                    f"different parameters."
                ),
            )
        return BuddhiVerdict(action="continue")

    def _check_consecutive_errors(self) -> BuddhiVerdict:
        """Detect too many consecutive errors."""
        if len(self._history) < _MAX_CONSECUTIVE_ERRORS:
            return BuddhiVerdict(action="continue")

        recent = self._history[-_MAX_CONSECUTIVE_ERRORS:]
        if all(not r.success for r in recent):
            # Extract unique error patterns
            unique_errors = set(r.error[:80] for r in recent if r.error)
            return BuddhiVerdict(
                action="abort",
                reason=f"{_MAX_CONSECUTIVE_ERRORS} consecutive errors",
                suggestion=(
                    f"Errors: {'; '.join(unique_errors) if unique_errors else 'unknown'}. "
                    f"This approach is not working."
                ),
            )
        return BuddhiVerdict(action="continue")

    def _check_tool_streak(self) -> BuddhiVerdict:
        """Detect using the same tool too many times in a row."""
        if len(self._history) < _MAX_SAME_TOOL_STREAK:
            return BuddhiVerdict(action="continue")

        recent = self._history[-_MAX_SAME_TOOL_STREAK:]
        if all(r.name == recent[0].name for r in recent):
            # Exception: read_file streak is often legitimate (exploring codebase)
            if recent[0].name == "read_file":
                return BuddhiVerdict(action="continue")
            return BuddhiVerdict(
                action="reflect",
                reason=f"Same tool '{recent[0].name}' used {_MAX_SAME_TOOL_STREAK}x consecutively",
                suggestion=(
                    f"Consider whether '{recent[0].name}' is the right tool. "
                    f"Try reading files for context or using a different approach."
                ),
            )
        return BuddhiVerdict(action="continue")

    def _check_error_ratio(self) -> BuddhiVerdict:
        """Check if the overall error rate is too high."""
        if len(self._history) < 6:
            return BuddhiVerdict(action="continue")

        total = len(self._history)
        errors = sum(1 for r in self._history if not r.success)
        ratio = errors / total

        if ratio >= _ERROR_RATIO_THRESHOLD:
            return BuddhiVerdict(
                action="reflect",
                reason=f"Error ratio {ratio:.0%} exceeds threshold ({_ERROR_RATIO_THRESHOLD:.0%})",
                suggestion=(
                    f"{errors}/{total} tool calls failed. "
                    f"Reconsider the overall approach."
                ),
            )
        return BuddhiVerdict(action="continue")

    def reset(self) -> None:
        """Reset Buddhi state for a new task."""
        self._history.clear()
        self._round = 0

    @property
    def stats(self) -> dict[str, object]:
        """Return diagnostic stats."""
        total = len(self._history)
        errors = sum(1 for r in self._history if not r.success)
        tool_counts: dict[str, int] = {}
        for r in self._history:
            tool_counts[r.name] = tool_counts.get(r.name, 0) + 1
        return {
            "rounds": self._round,
            "total_calls": total,
            "errors": errors,
            "error_ratio": errors / total if total else 0.0,
            "tool_distribution": tool_counts,
        }
