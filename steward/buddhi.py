"""
Buddhi — Discriminative Intelligence for the Agent Loop.

In the Vedic Antahkarana model, Buddhi is the discriminative faculty
that answers: "SHOULD I do this?" It's the driver of the chariot
(Katha Upanishad), not the horses (Manas/senses).

Architecture (80% deterministic / 20% LLM):

    PRE-FLIGHT (before LLM call):
        - Intent classification from user message (deterministic)
        - Tool pre-selection: only send relevant tools (token efficiency)
        - Token budget constraint: simple tasks get less budget
        - Phase awareness: early rounds need exploration tools, late rounds
          need write tools

    POST-FLIGHT (after tool execution):
        - Stuck loop detection (same tool+params repeated)
        - Error pattern recognition (repeated failures)
        - Progress tracking (files modified, tests passing)
        - Tool sequence analysis (read before write, etc.)

    LLM REFLECTION (only when stuck):
        - Triggered ONLY after deterministic checks fail to resolve

Usage:
    buddhi = Buddhi()

    # Pre-flight: which tools does the LLM need?
    directive = buddhi.pre_flight(user_message, round_num)
    tools = directive.tool_names  # send only these to LLM

    # Post-flight: how did it go?
    verdict = buddhi.evaluate(tool_calls, tool_results)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum

from steward.types import ToolUse

logger = logging.getLogger("STEWARD.BUDDHI")

# Thresholds — deterministic, no magic numbers
_MAX_IDENTICAL_CALLS = 3       # same tool + same params = stuck
_MAX_CONSECUTIVE_ERRORS = 5    # too many errors in a row = abort
_MAX_SAME_TOOL_STREAK = 8     # same tool name repeatedly = likely stuck
_ERROR_RATIO_THRESHOLD = 0.7   # > 70% of calls failing = systemic issue


# ── Intent Classification (deterministic, zero LLM) ──────────────────


class TaskIntent(StrEnum):
    """Deterministic task classification from user message.

    Each intent maps to a tool set and token budget.
    Classified by regex patterns — no LLM needed.
    """

    EXPLORE = "explore"        # read code, understand structure
    FIX = "fix"                # fix a bug, resolve an error
    CREATE = "create"          # write new code, add feature
    MODIFY = "modify"          # edit existing code, refactor
    TEST = "test"              # run tests, verify behavior
    EXPLAIN = "explain"        # explain code, answer question
    GENERAL = "general"        # unclear — send all tools


# Intent → regex patterns (first match wins, checked in order)
_INTENT_PATTERNS: list[tuple[TaskIntent, re.Pattern[str]]] = [
    (TaskIntent.TEST, re.compile(
        r"\b(run\s+(\w+\s+)?tests?|pytest|test\s+suite|check\s+(\w+\s+)?tests?|verify|unittest)\b", re.I)),
    (TaskIntent.EXPLAIN, re.compile(
        r"\b(explain|what\s+(does|is)|how\s+does|describe|show\s+me|understand)\b", re.I)),
    (TaskIntent.FIX, re.compile(
        r"\b(fix|bug|error|broken|crash|fail|issue|wrong|doesn.t\s+work|not\s+working)\b", re.I)),
    (TaskIntent.CREATE, re.compile(
        r"\b(create|add|implement|build|write|new\s+file|new\s+feature|generate)\b", re.I)),
    (TaskIntent.MODIFY, re.compile(
        r"\b(change|modify|update|refactor|rename|move|edit|replace|remove|delete)\b", re.I)),
    (TaskIntent.EXPLORE, re.compile(
        r"\b(find|search|look\s+for|where\s+is|list|grep|show\s+files|read)\b", re.I)),
]

# Intent → which tools are relevant (the rest are noise)
_INTENT_TOOLS: dict[TaskIntent, frozenset[str]] = {
    TaskIntent.EXPLORE:  frozenset({"read_file", "glob", "grep"}),
    TaskIntent.FIX:      frozenset({"read_file", "glob", "grep", "edit_file", "bash"}),
    TaskIntent.CREATE:   frozenset({"read_file", "glob", "write_file", "bash"}),
    TaskIntent.MODIFY:   frozenset({"read_file", "glob", "grep", "edit_file", "bash"}),
    TaskIntent.TEST:     frozenset({"bash", "read_file", "glob"}),
    TaskIntent.EXPLAIN:  frozenset({"read_file", "glob", "grep"}),
    TaskIntent.GENERAL:  frozenset(),  # empty = send all
}

# Intent → max_tokens constraint (simple tasks get less budget)
_INTENT_MAX_TOKENS: dict[TaskIntent, int] = {
    TaskIntent.EXPLORE:  2048,
    TaskIntent.FIX:      4096,
    TaskIntent.CREATE:   4096,
    TaskIntent.MODIFY:   4096,
    TaskIntent.TEST:     2048,
    TaskIntent.EXPLAIN:  2048,
    TaskIntent.GENERAL:  4096,
}


@dataclass(frozen=True)
class BuddhiDirective:
    """Pre-flight directive — what the LLM needs for THIS call.

    Determined deterministically from intent + round + history.
    """

    intent: TaskIntent
    tool_names: frozenset[str]    # only send these tool descriptions
    max_tokens: int               # constrain LLM output budget


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

    Two phases, both deterministic, zero LLM cost:

    PRE-FLIGHT (pre_flight):
        Classifies user intent → selects relevant tools → constrains
        token budget. Saves tokens on EVERY LLM call by not sending
        irrelevant tool descriptions.

    POST-FLIGHT (evaluate):
        Detects stuck loops, error patterns, tool streaks.
        Suggests reflection or abort.

    Phase-aware: as round number increases, tool set evolves.
    Early rounds favor exploration (read/grep/glob).
    Later rounds favor action (edit/write/bash).
    """

    def __init__(self) -> None:
        self._history: list[_ToolRecord] = []
        self._round: int = 0
        self._intent: TaskIntent = TaskIntent.GENERAL
        self._tools_used: set[str] = set()

    def pre_flight(self, user_message: str, round_num: int) -> BuddhiDirective:
        """Pre-flight gate — what does the LLM need for this call?

        Deterministic. Zero tokens. Called BEFORE every LLM call.

        Args:
            user_message: The original user request (for intent on round 0)
            round_num: Current tool-use round (0 = first LLM call)

        Returns:
            BuddhiDirective with tool_names and max_tokens
        """
        # Classify intent only on first round (user message is stable)
        if round_num == 0:
            self._intent = self._classify_intent(user_message)
            self._tools_used.clear()
            logger.info("Buddhi pre-flight: intent=%s", self._intent.value)

        base_tools = _INTENT_TOOLS[self._intent]
        max_tokens = _INTENT_MAX_TOKENS[self._intent]

        # Phase evolution: later rounds may need different tools
        if round_num > 0:
            # After exploration, the LLM may need write/edit tools
            # even if initial intent was EXPLORE or EXPLAIN
            if self._intent in (TaskIntent.EXPLORE, TaskIntent.EXPLAIN):
                # If the LLM already explored, let it act if needed
                if round_num >= 3:
                    base_tools = frozenset(base_tools | {"edit_file", "write_file", "bash"})

            # After errors, grant bash for debugging
            recent_errors = sum(1 for r in self._history[-3:] if not r.success)
            if recent_errors >= 2:
                base_tools = frozenset(base_tools | {"bash"})

        # Empty base_tools = GENERAL intent = send all tools
        if not base_tools:
            base_tools = frozenset()

        return BuddhiDirective(
            intent=self._intent,
            tool_names=base_tools,
            max_tokens=max_tokens,
        )

    @staticmethod
    def _classify_intent(message: str) -> TaskIntent:
        """Classify user intent from message text — deterministic regex.

        First matching pattern wins. Falls back to GENERAL.
        """
        for intent, pattern in _INTENT_PATTERNS:
            if pattern.search(message):
                return intent
        return TaskIntent.GENERAL

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
