"""
Buddhi — Discriminative Intelligence (The Driver of the Chariot).

PrakritiElement #2 — Protocol Layer: decision
Category: ANTAHKARANA (Internal Instrument)

In the Vedic model, Buddhi is the DRIVER of the chariot (Katha Upanishad).
It doesn't perceive (that's Manas), doesn't store (that's Chitta),
doesn't detect (that's Gandha). It DISCRIMINATES and DECIDES.

Antahkarana Composition:
    Manas  (#1, cognition) — perceives user intent → ManasPerception
    Buddhi (#2, decision)  — discriminates → BuddhiDirective / BuddhiVerdict
    Chitta (#4, awareness) — stores impressions → history
    Gandha (#9, detect)    — detects patterns → Detection

Buddhi is thin. It:
    1. Asks Manas to perceive (pre_flight, round 0)
    2. Records impressions in Chitta (evaluate)
    3. Asks Gandha to detect patterns (evaluate)
    4. Makes the final verdict (continue/reflect/redirect/abort)

80% deterministic / 20% LLM. LLM reflection only when stuck.

Usage:
    buddhi = Buddhi()
    directive = buddhi.pre_flight(user_message, round_num)
    verdict = buddhi.evaluate(tool_calls, tool_results)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from vibe_core.mahamantra.protocols.compression import IntentGuna
from vibe_core.runtime.semantic_actions import SemanticActionType

from steward.antahkarana.chitta import Chitta
from steward.antahkarana.gandha import Detection, detect_patterns
from steward.antahkarana.manas import Manas
from steward.types import ToolUse

logger = logging.getLogger("STEWARD.BUDDHI")


# ── Semantic Tool Mapping (substrate-derived) ────────────────────────
#
# SemanticActionType → which tools are relevant.
# Guna overlay: SATTVA=read, RAJAS=act, TAMAS=debug

_READ_TOOLS = frozenset({"read_file", "glob", "grep"})
_WRITE_TOOLS = frozenset({"read_file", "glob", "grep", "edit_file", "write_file", "bash"})
_DEBUG_TOOLS = frozenset({"read_file", "glob", "grep", "edit_file", "bash"})
_ALL_TOOLS = frozenset()  # empty = send everything

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
    IntentGuna.SUDDHA: _ALL_TOOLS,
}


@dataclass(frozen=True)
class BuddhiDirective:
    """Pre-flight directive — what the LLM needs for THIS call.

    Determined deterministically from substrate cognition.
    """

    action: SemanticActionType
    guna: IntentGuna
    tool_names: frozenset[str]
    max_tokens: int
    function: str = ""
    approach: str = ""


@dataclass(frozen=True)
class BuddhiVerdict:
    """Buddhi's judgment after evaluating a tool round.

    Actions:
        continue  — proceed normally
        reflect   — inject reflection prompt (LLM needed)
        redirect  — suggest alternative approach (deterministic)
        abort     — stop the loop (unrecoverable)
    """

    action: str  # "continue" | "reflect" | "redirect" | "abort"
    reason: str = ""
    suggestion: str = ""


class Buddhi:
    """Discriminative intelligence — the Driver of the Chariot.

    Composes the Antahkarana elements:
        Manas  — perceives intent (classification)
        Chitta — stores impressions (history)
        Gandha — detects patterns (stuck loops, errors)

    Buddhi itself only DISCRIMINATES and DECIDES.
    """

    def __init__(self) -> None:
        self._manas = Manas()
        self._chitta = Chitta()

    def pre_flight(
        self, user_message: str, round_num: int, context_pct: float = 0.0,
    ) -> BuddhiDirective:
        """Pre-flight gate — Manas perception → Buddhi decision.

        Round 0: Manas perceives user intent (deterministic, zero LLM).
        All rounds: Buddhi discriminates tool selection + token budget.

        Args:
            user_message: The original user request
            round_num: Current tool-use round (0 = first LLM call)
            context_pct: Current context budget usage (0.0 to 1.0)

        Returns:
            BuddhiDirective with action, guna, tool_names, max_tokens
        """
        # Round 0: Manas perceives (classify intent once)
        if round_num == 0:
            perception = self._manas.perceive(user_message)
            self._action = perception.action
            self._guna = perception.guna
            self._function = perception.function
            self._approach = perception.approach
            logger.info(
                "Buddhi pre-flight: action=%s guna=%s function=%s approach=%s",
                self._action.value, self._guna.value,
                self._function, self._approach,
            )

        # Buddhi discriminates: action → tool set, token budget
        base_tools = _ACTION_TOOLS.get(self._action, _ALL_TOOLS)
        max_tokens = _ACTION_MAX_TOKENS.get(self._action, 4096)

        # Context-aware token budget: constrain at pressure thresholds
        if context_pct >= 0.7:
            max_tokens = min(max_tokens, 1024)
        elif context_pct >= 0.5:
            max_tokens = min(max_tokens, 2048)

        # Guna overlay: if action tools are empty, use guna fallback
        if not base_tools:
            base_tools = _GUNA_TOOLS.get(self._guna, _ALL_TOOLS)

        # Phase evolution: later rounds may need different tools
        if round_num > 0:
            if self._action in (
                SemanticActionType.RESEARCH, SemanticActionType.ANALYZE,
                SemanticActionType.MONITOR, SemanticActionType.REVIEW,
            ):
                if round_num >= 3:
                    base_tools = frozenset(base_tools | {"edit_file", "write_file", "bash"})

            # After errors, grant bash for debugging
            recent_errors = sum(
                1 for r in self._chitta.recent(3) if not r.success
            )
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

    def evaluate(
        self,
        tool_calls: list[ToolUse],
        results: list[tuple[bool, str]],
    ) -> BuddhiVerdict:
        """Evaluate the outcome of a tool round.

        1. Record impressions in Chitta
        2. Gandha detects patterns
        3. Buddhi translates detection → verdict

        Args:
            tool_calls: Tools that were called this round
            results: List of (success, error_msg) tuples

        Returns:
            BuddhiVerdict with recommended action
        """
        self._chitta.advance_round()

        # Record impressions in Chitta
        for tc, (success, error) in zip(tool_calls, results):
            params_hash = hash(frozenset(
                (k, str(v)) for k, v in sorted(tc.parameters.items())
            )) if tc.parameters else 0
            self._chitta.record(
                name=tc.name,
                params_hash=params_hash,
                success=success,
                error=error,
            )

        # Gandha detects patterns in Chitta's impressions
        detection = detect_patterns(self._chitta.impressions)
        if detection is None:
            return BuddhiVerdict(action="continue")

        # Buddhi translates detection → verdict
        verdict = BuddhiVerdict(
            action=detection.severity,
            reason=detection.reason,
            suggestion=detection.suggestion,
        )
        logger.info(
            "Buddhi verdict at round %d: %s — %s",
            self._chitta.round, verdict.action, verdict.reason,
        )
        return verdict

    def reset(self) -> None:
        """Reset for a new task."""
        self._chitta.clear()

    @property
    def stats(self) -> dict[str, object]:
        """Diagnostic stats — delegates to Chitta."""
        return self._chitta.stats
