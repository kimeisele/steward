"""
Buddhi — Discriminative Intelligence for the Agent Loop.

In the Vedic Antahkarana model, Buddhi is the discriminative faculty
that answers: "SHOULD I do this?" It's the driver of the chariot
(Katha Upanishad), not the horses (Manas/senses).

Architecture (80% deterministic / 20% LLM):

    PRE-FLIGHT (before LLM call):
        - MahaBuddhi.think() → cognitive frame (mode/function/approach)
        - SemanticActionType from substrate → intent taxonomy
        - Guna-based tool pre-selection (SATTVA=read, RAJAS=act, TAMAS=debug)
        - Phase awareness: early rounds → exploration, late rounds → action

    POST-FLIGHT (after tool execution):
        - Stuck loop detection (same tool+params repeated)
        - Error pattern recognition (repeated failures)
        - Tool sequence analysis (read before write, etc.)

    LLM REFLECTION (only when stuck):
        - Triggered ONLY after deterministic checks fail to resolve

Uses REAL substrate primitives:
    - SemanticActionType (not hardcoded enums)
    - MahaBuddhi.think() (Lotus VM + MahaComposition, zero LLM)
    - MahaCompression.decode_samskara_intent() (guna from seed)
    - IntentGuna (SATTVA/RAJAS/TAMAS/SUDDHA)

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
from dataclasses import dataclass, field

from vibe_core.mahamantra.adapters.compression import MahaCompression
from vibe_core.mahamantra.protocols.compression import IntentGuna
from vibe_core.mahamantra.substrate.buddhi import MahaBuddhi, get_buddhi
from vibe_core.runtime.semantic_actions import SemanticActionType

from steward.types import ToolUse

logger = logging.getLogger("STEWARD.BUDDHI")

# Thresholds — deterministic, no magic numbers
_MAX_IDENTICAL_CALLS = 3       # same tool + same params = stuck
_MAX_CONSECUTIVE_ERRORS = 5    # too many errors in a row = abort
_MAX_SAME_TOOL_STREAK = 8     # same tool name repeatedly = likely stuck
_ERROR_RATIO_THRESHOLD = 0.7   # > 70% of calls failing = systemic issue


# ── Semantic Tool Mapping (substrate-derived) ────────────────────────
#
# SemanticActionType → which tools are relevant.
# The taxonomy comes from steward-protocol, the tool mapping is
# steward-specific (steward knows its own tools).
#
# Guna overlay:
#   SATTVA → read-only tools (safe, observational)
#   RAJAS  → all tools (active, creative)
#   TAMAS  → debug tools (fix, heal, respond)
#

_READ_TOOLS = frozenset({"read_file", "glob", "grep"})
_WRITE_TOOLS = frozenset({"read_file", "glob", "grep", "edit_file", "write_file", "bash"})
_DEBUG_TOOLS = frozenset({"read_file", "glob", "grep", "edit_file", "bash"})
_ALL_TOOLS = frozenset()  # empty = send everything

# SemanticActionType → tool set
_ACTION_TOOLS: dict[SemanticActionType, frozenset[str]] = {
    # SATTVA-aligned: observation
    SemanticActionType.RESEARCH:   _READ_TOOLS,
    SemanticActionType.ANALYZE:    _READ_TOOLS,
    SemanticActionType.MONITOR:    _READ_TOOLS,
    SemanticActionType.REVIEW:     _READ_TOOLS,
    # RAJAS-aligned: action
    SemanticActionType.IMPLEMENT:  _WRITE_TOOLS,
    SemanticActionType.REFACTOR:   _WRITE_TOOLS,
    SemanticActionType.DESIGN:     _WRITE_TOOLS,
    SemanticActionType.PLAN:       _READ_TOOLS,
    SemanticActionType.SYNTHESIZE: _READ_TOOLS,
    # TAMAS-aligned: fix/respond
    SemanticActionType.DEBUG:      _DEBUG_TOOLS,
    SemanticActionType.TEST:       frozenset({"bash", "read_file", "glob"}),
    SemanticActionType.RESPOND:    _DEBUG_TOOLS,
}

# SemanticActionType → max_tokens
_ACTION_MAX_TOKENS: dict[SemanticActionType, int] = {
    SemanticActionType.RESEARCH:   2048,
    SemanticActionType.ANALYZE:    2048,
    SemanticActionType.MONITOR:    2048,
    SemanticActionType.REVIEW:     2048,
    SemanticActionType.IMPLEMENT:  4096,
    SemanticActionType.REFACTOR:   4096,
    SemanticActionType.DESIGN:     4096,
    SemanticActionType.PLAN:       2048,
    SemanticActionType.SYNTHESIZE: 2048,
    SemanticActionType.DEBUG:      4096,
    SemanticActionType.TEST:       2048,
    SemanticActionType.RESPOND:    4096,
}

# Guna → fallback tool set (when action type is ambiguous)
_GUNA_TOOLS: dict[IntentGuna, frozenset[str]] = {
    IntentGuna.SATTVA: _READ_TOOLS,
    IntentGuna.RAJAS:  _WRITE_TOOLS,
    IntentGuna.TAMAS:  _DEBUG_TOOLS,
    IntentGuna.SUDDHA: _ALL_TOOLS,  # transcendental = no restriction
}

# Trinity function → SemanticActionType affinity
# BRAHMA = creation, VISHNU = maintenance, SHIVA = transformation
_FUNCTION_AFFINITY: dict[str, SemanticActionType] = {
    "BRAHMA": SemanticActionType.IMPLEMENT,
    "VISHNU": SemanticActionType.MONITOR,
    "SHIVA": SemanticActionType.REFACTOR,
}

# Approach → SemanticActionType affinity
# GENESIS = build, DHARMA = maintain, KARMA = fix, MOKSHA = transcend
_APPROACH_AFFINITY: dict[str, SemanticActionType] = {
    "GENESIS": SemanticActionType.IMPLEMENT,
    "DHARMA": SemanticActionType.REVIEW,
    "KARMA": SemanticActionType.DEBUG,
    "MOKSHA": SemanticActionType.RESEARCH,
}


@dataclass(frozen=True)
class BuddhiDirective:
    """Pre-flight directive — what the LLM needs for THIS call.

    Determined deterministically from substrate cognition.
    """

    action: SemanticActionType     # from substrate taxonomy
    guna: IntentGuna               # from MahaCompression seed
    tool_names: frozenset[str]     # only send these tool descriptions
    max_tokens: int                # constrain LLM output budget
    function: str = ""             # BRAHMA/VISHNU/SHIVA (from MahaBuddhi)
    approach: str = ""             # GENESIS/DHARMA/KARMA/MOKSHA


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

    Uses REAL substrate primitives for cognition:
    - MahaBuddhi.think() for cognitive frame (zero LLM, Lotus VM)
    - MahaCompression.decode_samskara_intent() for guna classification
    - SemanticActionType for intent taxonomy

    PRE-FLIGHT (pre_flight):
        Substrate cognition → tool selection → token budget.

    POST-FLIGHT (evaluate):
        Stuck loop detection, error patterns, tool streaks.
    """

    def __init__(self) -> None:
        self._history: list[_ToolRecord] = []
        self._round: int = 0
        self._action: SemanticActionType = SemanticActionType.IMPLEMENT
        self._guna: IntentGuna = IntentGuna.RAJAS
        self._function: str = ""
        self._approach: str = ""
        self._compression = MahaCompression()
        self._maha_buddhi = get_buddhi()

    def pre_flight(self, user_message: str, round_num: int) -> BuddhiDirective:
        """Pre-flight gate — substrate cognition → tool selection.

        Uses MahaBuddhi.think() + MahaCompression for classification.
        Deterministic. Zero LLM tokens.

        Args:
            user_message: The original user request (for intent on round 0)
            round_num: Current tool-use round (0 = first LLM call)

        Returns:
            BuddhiDirective with action type, guna, tool_names, max_tokens
        """
        # Classify intent only on first round (user message is stable)
        if round_num == 0:
            self._classify(user_message)
            logger.info(
                "Buddhi pre-flight: action=%s guna=%s function=%s approach=%s",
                self._action.value, self._guna.value,
                self._function, self._approach,
            )

        # Tool selection: action type → tool set
        base_tools = _ACTION_TOOLS.get(self._action, _ALL_TOOLS)
        max_tokens = _ACTION_MAX_TOKENS.get(self._action, 4096)

        # Guna overlay: if action tools are empty, use guna fallback
        if not base_tools:
            base_tools = _GUNA_TOOLS.get(self._guna, _ALL_TOOLS)

        # Phase evolution: later rounds may need different tools
        if round_num > 0:
            # After exploration, the LLM may need write/edit tools
            if self._action in (
                SemanticActionType.RESEARCH, SemanticActionType.ANALYZE,
                SemanticActionType.MONITOR, SemanticActionType.REVIEW,
            ):
                if round_num >= 3:
                    base_tools = frozenset(base_tools | {"edit_file", "write_file", "bash"})

            # After errors, grant bash for debugging
            recent_errors = sum(1 for r in self._history[-3:] if not r.success)
            if recent_errors >= 2:
                base_tools = frozenset(base_tools | {"bash"})

        return BuddhiDirective(
            action=self._action,
            guna=self._guna,
            tool_names=base_tools,
            max_tokens=max_tokens,
            function=self._function,
            approach=self._approach,
        )

    def _classify(self, message: str) -> None:
        """Classify user intent using substrate primitives.

        1. MahaCompression → seed → IntentGuna (SATTVA/RAJAS/TAMAS)
        2. MahaBuddhi.think() → cognitive frame (function/approach)
        3. Map cognitive frame → SemanticActionType
        """
        # Step 1: Compression → guna
        cr = self._compression.compress(message)
        self._guna = self._compression.decode_samskara_intent(cr.seed).guna

        # Step 2: MahaBuddhi → cognitive frame
        cognition = self._maha_buddhi.think(message)
        self._function = cognition.function
        self._approach = cognition.approach

        # Step 3: Map to SemanticActionType
        # Priority: approach affinity > function affinity > guna default
        action = _APPROACH_AFFINITY.get(cognition.approach)
        if action is None:
            action = _FUNCTION_AFFINITY.get(cognition.function)
        if action is None:
            # Guna fallback
            guna_defaults = {
                IntentGuna.SATTVA: SemanticActionType.RESEARCH,
                IntentGuna.RAJAS: SemanticActionType.IMPLEMENT,
                IntentGuna.TAMAS: SemanticActionType.DEBUG,
                IntentGuna.SUDDHA: SemanticActionType.IMPLEMENT,
            }
            action = guna_defaults.get(self._guna, SemanticActionType.IMPLEMENT)
        self._action = action

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
