"""
Buddhi — Discriminative Intelligence (The Driver of the Chariot).

PrakritiElement #2 — Protocol Layer: decision
Category: ANTAHKARANA (Internal Instrument)

In the Vedic model, Buddhi is the DRIVER of the chariot (Katha Upanishad).
It doesn't perceive (that's Manas), doesn't store (that's Chitta),
doesn't detect (that's Gandha). It DISCRIMINATES and DECIDES.

Antahkarana Composition:
    Manas  (#1, cognition) — perceives user intent -> ManasPerception
    Buddhi (#2, decision)  — discriminates -> BuddhiDirective / BuddhiVerdict
    Chitta (#4, awareness) — stores impressions, derives phase
    Gandha (#9, detect)    — detects patterns -> Detection

Phase Machine (derived from Chitta):
    ORIENT   — exploring/reading (context gathering)
    EXECUTE  — making changes (writing/editing)
    VERIFY   — checking work (running tests)
    COMPLETE — task appears done (tests passed)

Buddhi reads Chitta's phase and adjusts tool selection + guidance.
No hardcoded round thresholds. The impressions determine the phase.

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

from steward.antahkarana.chitta import (
    PHASE_COMPLETE,
    PHASE_EXECUTE,
    PHASE_ORIENT,
    PHASE_VERIFY,
    Chitta,
)
from steward.antahkarana.gandha import detect_patterns
from steward.antahkarana.manas import Manas
from steward.types import ToolUse

logger = logging.getLogger("STEWARD.BUDDHI")


# ── Semantic Tool Mapping (substrate-derived) ────────────────────────

_READ_TOOLS = frozenset({"read_file", "glob", "grep"})
_WRITE_TOOLS = frozenset({"read_file", "glob", "grep", "edit_file", "write_file", "bash"})
_DEBUG_TOOLS = frozenset({"read_file", "glob", "grep", "edit_file", "bash"})
_ALL_TOOLS = frozenset()  # empty = send everything

_ACTION_TOOLS: dict[SemanticActionType, frozenset[str]] = {
    SemanticActionType.RESEARCH:   _READ_TOOLS,
    SemanticActionType.ANALYZE:    _READ_TOOLS,
    SemanticActionType.MONITOR:    _READ_TOOLS,
    SemanticActionType.REVIEW:     _READ_TOOLS,
    SemanticActionType.IMPLEMENT:  _WRITE_TOOLS,
    SemanticActionType.REFACTOR:   _WRITE_TOOLS,
    SemanticActionType.DESIGN:     _WRITE_TOOLS,
    SemanticActionType.PLAN:       _READ_TOOLS,
    SemanticActionType.SYNTHESIZE: _READ_TOOLS,
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

_GUNA_TOOLS: dict[IntentGuna, frozenset[str]] = {
    IntentGuna.SATTVA: _READ_TOOLS,
    IntentGuna.RAJAS:  _WRITE_TOOLS,
    IntentGuna.TAMAS:  _DEBUG_TOOLS,
    IntentGuna.SUDDHA: _ALL_TOOLS,
}

# ── Phase-Aware Tool Overlay ─────────────────────────────────────────
# Phase adds tools ON TOP of action-based selection.
# VERIFY ensures bash is available for tests.
# EXECUTE ensures write tools even for SATTVA actions that explored enough.

_PHASE_TOOL_OVERLAY: dict[str, frozenset[str]] = {
    PHASE_ORIENT: frozenset(),
    PHASE_EXECUTE: frozenset({"edit_file", "write_file", "bash"}),
    PHASE_VERIFY: frozenset({"bash", "read_file"}),
    PHASE_COMPLETE: frozenset(),
}

# Phase-based token budget (only applies when lower than action budget)
# VERIFY and COMPLETE tighten budget — work should be winding down.
# ORIENT and EXECUTE defer to the action's natural budget.
_PHASE_MAX_TOKENS: dict[str, int] = {
    PHASE_ORIENT: 4096,    # defer to action budget
    PHASE_EXECUTE: 4096,   # full budget for active work
    PHASE_VERIFY: 2048,    # tighten for test/check phase
    PHASE_COMPLETE: 2048,  # tighten for wrap-up
}


@dataclass(frozen=True)
class BuddhiDirective:
    """Pre-flight directive — what the LLM needs for THIS call.

    Determined deterministically from substrate cognition + Chitta phase.
    """

    action: SemanticActionType
    guna: IntentGuna
    tool_names: frozenset[str]
    max_tokens: int
    function: str = ""
    approach: str = ""
    phase: str = ""  # ORIENT | EXECUTE | VERIFY | COMPLETE


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
        Chitta — stores impressions, derives phase
        Gandha — detects patterns (stuck loops, errors)

    Phase machine (derived from Chitta):
        ORIENT -> EXECUTE -> VERIFY -> COMPLETE
        Errors regress to ORIENT.

    Buddhi reads the phase, adjusts tools, and injects guidance
    at phase transitions.
    """

    def __init__(self) -> None:
        self._manas = Manas()
        self._chitta = Chitta()
        self._prev_phase: str = PHASE_ORIENT

    def pre_flight(
        self, user_message: str, round_num: int, context_pct: float = 0.0,
    ) -> BuddhiDirective:
        """Pre-flight gate — Manas perception + Chitta phase -> tool selection.

        Round 0: Manas perceives user intent (deterministic, zero LLM).
        All rounds: Buddhi uses Chitta's phase for tool + token decisions.

        Args:
            user_message: The original user request
            round_num: Current tool-use round (0 = first LLM call)
            context_pct: Current context budget usage (0.0 to 1.0)

        Returns:
            BuddhiDirective with action, guna, tool_names, max_tokens, phase
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

        # Action-based tool selection (primary)
        base_tools = _ACTION_TOOLS.get(self._action, _ALL_TOOLS)
        max_tokens = _ACTION_MAX_TOKENS.get(self._action, 4096)

        # Guna fallback if action tools are empty
        if not base_tools:
            base_tools = _GUNA_TOOLS.get(self._guna, _ALL_TOOLS)

        # Phase-aware overlay: Chitta's phase adds tools on top
        phase = self._chitta.phase
        overlay = _PHASE_TOOL_OVERLAY.get(phase, frozenset())
        if overlay:
            base_tools = frozenset(base_tools | overlay)

        # Phase-aware token budget
        phase_max = _PHASE_MAX_TOKENS.get(phase, 4096)
        max_tokens = min(max_tokens, phase_max)

        # Context pressure: tighten budget further
        if context_pct >= 0.7:
            max_tokens = min(max_tokens, 1024)
        elif context_pct >= 0.5:
            max_tokens = min(max_tokens, 2048)

        # After errors, always grant bash for debugging
        if round_num > 0:
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
            phase=phase,
        )

    def evaluate(
        self,
        tool_calls: list[ToolUse],
        results: list[tuple[bool, str]],
    ) -> BuddhiVerdict:
        """Evaluate the outcome of a tool round.

        1. Record impressions in Chitta
        2. Gandha detects patterns
        3. Check for phase transitions -> inject guidance
        4. Buddhi makes final verdict

        Args:
            tool_calls: Tools that were called this round
            results: List of (success, error_msg) tuples

        Returns:
            BuddhiVerdict with recommended action
        """
        prev_phase = self._chitta.phase
        self._chitta.advance_round()

        # Record impressions in Chitta (with file paths for tracking)
        for tc, (success, error) in zip(tool_calls, results):
            params_hash = hash(frozenset(
                (k, str(v)) for k, v in sorted(tc.parameters.items())
            )) if tc.parameters else 0
            path = str(tc.parameters.get("path", "")) if tc.parameters else ""
            self._chitta.record(
                name=tc.name,
                params_hash=params_hash,
                success=success,
                error=error,
                path=path,
            )

        # Gandha detects patterns in Chitta's impressions (cross-turn aware)
        detection = detect_patterns(
            self._chitta.impressions,
            prior_reads=self._chitta.prior_reads,
        )
        if detection is not None:
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

        # Phase transition guidance
        curr_phase = self._chitta.phase
        if prev_phase != curr_phase:
            logger.info(
                "Buddhi phase transition: %s -> %s (round %d)",
                prev_phase, curr_phase, self._chitta.round,
            )
            guidance = _phase_guidance(prev_phase, curr_phase, self._chitta)
            if guidance:
                return BuddhiVerdict(
                    action="reflect",
                    reason=f"Phase {prev_phase}->{curr_phase}",
                    suggestion=guidance,
                )

        return BuddhiVerdict(action="continue")

    @property
    def phase(self) -> str:
        """Current phase (delegates to Chitta)."""
        return self._chitta.phase

    def reset(self) -> None:
        """Reset for a new task."""
        self._chitta.clear()
        self._prev_phase = PHASE_ORIENT

    @property
    def stats(self) -> dict[str, object]:
        """Diagnostic stats — delegates to Chitta."""
        return self._chitta.stats


def _phase_guidance(
    prev: str,
    curr: str,
    chitta: Chitta,
) -> str:
    """Generate guidance for a phase transition.

    Only injects guidance for FORWARD transitions that the LLM
    needs to know about. Error regression is Gandha's job.

    Returns guidance text or empty string (no guidance needed).
    """
    # EXECUTE -> VERIFY: nudge to run tests after modifications
    if prev == PHASE_EXECUTE and curr == PHASE_VERIFY:
        modified = chitta.files_written
        if modified:
            file_list = ", ".join(modified[:5])
            extra = f" (+{len(modified) - 5} more)" if len(modified) > 5 else ""
            return (
                f"You've modified: {file_list}{extra}. "
                f"Consider running tests to verify your changes work correctly."
            )
        return "You've made changes. Consider running tests to verify."

    return ""
