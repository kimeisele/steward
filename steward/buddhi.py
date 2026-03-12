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
from enum import StrEnum

from steward.antahkarana.chitta import Chitta, ExecutionPhase
from steward.antahkarana.gandha import VerdictAction, detect_patterns
from steward.antahkarana.manas import Manas
from steward.cbr import process_cbr
from steward.types import ToolUse
from vibe_core.mahamantra.protocols.compression import IntentGuna
from vibe_core.mahamantra.substrate.manas.synaptic import HebbianSynaptic
from vibe_core.runtime.semantic_actions import SemanticActionType

logger = logging.getLogger("STEWARD.BUDDHI")


# ── ToolNamespace — Shakti-derived capability domains ────────────────
#
# Vedic mapping (Shakti → Domain):
#   JNANA  (knowledge)     → OBSERVE  — read, search, discover
#   PALANA (maintenance)   → MODIFY   — write, edit, create
#   KSHATRA (enforcement)  → EXECUTE  — bash, system commands
#   UDDHARA (rescue/spawn) → DELEGATE — sub-agent, task delegation
#
# This is the composable layer: actions select NAMESPACES, not tools.
# New tools register into a namespace → automatically participate.
# Runtime-mutable: add/remove tools without code changes.


class ToolNamespace(StrEnum):
    """Semantic tool capability domains (Shakti → business English)."""

    OBSERVE = "observe"  # JNANA: read, search, discover
    MODIFY = "modify"  # PALANA: write, edit, create
    EXECUTE = "execute"  # KSHATRA: bash, system commands
    DELEGATE = "delegate"  # UDDHARA: sub-agent, task delegation


# Namespace → tool names (runtime-mutable)
_NAMESPACE_TOOLS: dict[ToolNamespace, set[str]] = {
    ToolNamespace.OBSERVE: {"read_file", "glob", "grep", "http"},
    ToolNamespace.MODIFY: {"write_file", "edit_file"},
    ToolNamespace.EXECUTE: {"bash"},
    ToolNamespace.DELEGATE: {"sub_agent"},
}

# Action → namespaces (which capability domains are needed)
_ACTION_NAMESPACES: dict[SemanticActionType, frozenset[ToolNamespace]] = {
    SemanticActionType.RESEARCH: frozenset({ToolNamespace.OBSERVE}),
    SemanticActionType.ANALYZE: frozenset({ToolNamespace.OBSERVE}),
    SemanticActionType.MONITOR: frozenset({ToolNamespace.OBSERVE}),
    SemanticActionType.REVIEW: frozenset({ToolNamespace.OBSERVE}),
    SemanticActionType.IMPLEMENT: frozenset({ToolNamespace.OBSERVE, ToolNamespace.MODIFY, ToolNamespace.EXECUTE}),
    SemanticActionType.REFACTOR: frozenset({ToolNamespace.OBSERVE, ToolNamespace.MODIFY, ToolNamespace.EXECUTE}),
    SemanticActionType.DESIGN: frozenset(
        {ToolNamespace.OBSERVE, ToolNamespace.MODIFY, ToolNamespace.EXECUTE, ToolNamespace.DELEGATE}
    ),
    SemanticActionType.PLAN: frozenset({ToolNamespace.OBSERVE, ToolNamespace.DELEGATE}),
    SemanticActionType.SYNTHESIZE: frozenset({ToolNamespace.OBSERVE, ToolNamespace.DELEGATE}),
    SemanticActionType.DEBUG: frozenset({ToolNamespace.OBSERVE, ToolNamespace.MODIFY, ToolNamespace.EXECUTE}),
    SemanticActionType.TEST: frozenset({ToolNamespace.OBSERVE, ToolNamespace.EXECUTE}),
    SemanticActionType.RESPOND: frozenset({ToolNamespace.OBSERVE, ToolNamespace.MODIFY, ToolNamespace.EXECUTE}),
}

# Guna → namespaces (fallback when action tools are empty)
_GUNA_NAMESPACES: dict[IntentGuna, frozenset[ToolNamespace]] = {
    IntentGuna.SATTVA: frozenset({ToolNamespace.OBSERVE}),
    IntentGuna.RAJAS: frozenset({ToolNamespace.OBSERVE, ToolNamespace.MODIFY, ToolNamespace.EXECUTE}),
    IntentGuna.TAMAS: frozenset({ToolNamespace.OBSERVE, ToolNamespace.MODIFY, ToolNamespace.EXECUTE}),
    IntentGuna.SUDDHA: frozenset(ToolNamespace),  # all namespaces
}

# Phase → namespace overlays (add capabilities during specific phases)
_PHASE_NS_OVERLAY: dict[ExecutionPhase, frozenset[ToolNamespace]] = {
    ExecutionPhase.ORIENT: frozenset(),
    ExecutionPhase.EXECUTE: frozenset({ToolNamespace.MODIFY, ToolNamespace.EXECUTE}),
    ExecutionPhase.VERIFY: frozenset({ToolNamespace.EXECUTE, ToolNamespace.OBSERVE}),
    ExecutionPhase.COMPLETE: frozenset(),
}


def resolve_namespaces(namespaces: frozenset[ToolNamespace]) -> frozenset[str]:
    """Resolve namespace set to concrete tool names (O(N) where N=namespaces, not tools)."""
    tools: set[str] = set()
    for ns in namespaces:
        tools.update(_NAMESPACE_TOOLS.get(ns, set()))
    return frozenset(tools)


def register_tool(namespace: ToolNamespace, tool_name: str) -> None:
    """Register a tool into a namespace (runtime composition)."""
    _NAMESPACE_TOOLS[namespace].add(tool_name)


def unregister_tool(namespace: ToolNamespace, tool_name: str) -> None:
    """Remove a tool from a namespace (runtime composition)."""
    _NAMESPACE_TOOLS[namespace].discard(tool_name)


# CBR task weight per action — normalized 0.0-1.0.
# This feeds the DSP signal processor, not hardcoded token counts.
# 0.0 = trivial (just a tool call), 1.0 = heavy (edit_file + bash)
_ACTION_WEIGHT: dict[SemanticActionType, float] = {
    SemanticActionType.RESEARCH: 0.0,  # just tool calls
    SemanticActionType.ANALYZE: 0.0,  # observe only
    SemanticActionType.MONITOR: 0.0,  # observe only
    SemanticActionType.REVIEW: 0.0,  # observe only
    SemanticActionType.PLAN: 0.0,  # think, don't write
    SemanticActionType.TEST: 0.0,  # just run bash
    SemanticActionType.DESIGN: 0.5,  # plan + describe
    SemanticActionType.SYNTHESIZE: 0.5,  # aggregate
    SemanticActionType.RESPOND: 0.5,  # text response
    SemanticActionType.IMPLEMENT: 1.0,  # edit_file needs room
    SemanticActionType.REFACTOR: 1.0,  # rewrite code
    SemanticActionType.DEBUG: 1.0,  # edit + bash
}

# ── ModelTier — cost-aware LLM routing ─────────────────────────────


class ModelTier(StrEnum):
    """Cost-aware model tiers for ProviderChamber routing.

    FLASH: cheapest/fastest (Groq, Mistral) — simple reads, tests
    STANDARD: balanced (default prana ordering) — implementation, debug
    PRO: most capable (Claude, expensive) — design, synthesis
    """

    FLASH = "flash"
    STANDARD = "standard"
    PRO = "pro"


_ACTION_TIER: dict[SemanticActionType, ModelTier] = {
    SemanticActionType.RESEARCH: ModelTier.FLASH,
    SemanticActionType.ANALYZE: ModelTier.STANDARD,
    SemanticActionType.MONITOR: ModelTier.FLASH,
    SemanticActionType.REVIEW: ModelTier.STANDARD,
    SemanticActionType.IMPLEMENT: ModelTier.STANDARD,
    SemanticActionType.REFACTOR: ModelTier.STANDARD,
    SemanticActionType.DESIGN: ModelTier.PRO,
    SemanticActionType.PLAN: ModelTier.STANDARD,
    SemanticActionType.SYNTHESIZE: ModelTier.PRO,
    SemanticActionType.DEBUG: ModelTier.STANDARD,
    SemanticActionType.TEST: ModelTier.FLASH,
    SemanticActionType.RESPOND: ModelTier.STANDARD,
}


# Phase modulation — multiplier on task_weight before DSP processing.
# The phase attenuates the input signal, not the output budget.
# EXECUTE = unity gain (1.0), everything else reduces the signal.
_PHASE_MODULATION: dict[ExecutionPhase, float] = {
    ExecutionPhase.ORIENT: 0.5,  # exploring — half amplitude
    ExecutionPhase.EXECUTE: 1.0,  # implementing — full amplitude
    ExecutionPhase.VERIFY: 0.5,  # testing — half amplitude
    ExecutionPhase.COMPLETE: 0.5,  # summarizing — half amplitude
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
    tier: ModelTier = ModelTier.STANDARD
    function: str = ""
    approach: str = ""
    phase: ExecutionPhase | str = ""  # defaults to "" before Chitta derives it


@dataclass(frozen=True)
class BuddhiVerdict:
    """Buddhi's judgment after evaluating a tool round.

    Actions:
        continue  — proceed normally
        reflect   — inject reflection prompt (LLM needed)
        redirect  — suggest alternative approach (deterministic)
        abort     — stop the loop (unrecoverable)
    """

    action: VerdictAction
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

    def __init__(self, synaptic: HebbianSynaptic | None = None) -> None:
        self._manas = Manas()
        self._chitta = Chitta()
        self._prev_phase = ExecutionPhase.ORIENT
        self._synaptic = synaptic  # Real Hebbian learning from steward-protocol
        # Initialized by pre_flight() round 0 — safe defaults until then
        self._action: SemanticActionType = SemanticActionType.RESPOND
        self._guna: IntentGuna = IntentGuna.RAJAS
        self._function: str = ""
        self._approach: str = ""
        self._last_tier: ModelTier = ModelTier.STANDARD
        self._last_pattern: str = ""

    def record_outcome(self, success: bool) -> None:
        """Record task outcome via Hebbian synaptic update.

        Uses real HebbianSynaptic from steward-protocol:
        Success: w += 0.1 * (1 - w)  → asymptotic to 1.0
        Failure: w -= 0.1 * w        → asymptotic to 0.0
        """
        if self._synaptic is None:
            return
        self._synaptic.update(self._action.value, "execute", success)

    def record_seed(self, seed: int, success: bool) -> None:
        """Record seed-level outcome for input-specific learning.

        Tracks per-input-pattern confidence. Higher weight = more cacheable.
        Uses HebbianSynaptic: success strengthens, failure weakens.
        """
        if self._synaptic is None:
            return
        self._synaptic.update(f"seed:{seed}", "cache", success)

    def seed_confidence(self, seed: int) -> float:
        """Get confidence for a specific input seed (0.0 to 1.0)."""
        if self._synaptic is None:
            return 0.0
        return self._synaptic.get_weight(f"seed:{seed}", "cache")

    @property
    def synaptic(self) -> HebbianSynaptic | None:
        """Access synaptic learning (for persistence by agent)."""
        return self._synaptic

    def pre_flight(
        self,
        user_message: str,
        round_num: int,
        context_pct: float = 0.0,
        seed: int = 0,
    ) -> BuddhiDirective:
        """Pre-flight gate — Manas perception + Chitta phase -> tool selection.

        Round 0: Manas perceives user intent (deterministic, zero LLM).
        All rounds: Buddhi uses Chitta's phase for tool + token decisions.

        Args:
            user_message: The original user request
            round_num: Current tool-use round (0 = first LLM call)
            context_pct: Current context budget usage (0.0 to 1.0)
            seed: Input seed for Hebbian cache confidence lookup

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
                self._action.value,
                self._guna.value,
                self._function,
                self._approach,
            )

        # Action-based namespace selection (primary)
        action_ns = _ACTION_NAMESPACES.get(self._action, frozenset())
        base_tools = resolve_namespaces(action_ns)

        # Guna fallback if no namespaces for action
        if not base_tools:
            guna_ns = _GUNA_NAMESPACES.get(self._guna, frozenset(ToolNamespace))
            base_tools = resolve_namespaces(guna_ns)

        # Phase-aware overlay: Chitta's phase adds namespace capabilities
        phase = self._chitta.phase
        phase_ns = _PHASE_NS_OVERLAY.get(phase, frozenset())
        if phase_ns:
            base_tools = frozenset(base_tools | resolve_namespaces(phase_ns))

        # ── DSP Signal Chain ────────────────────────────────────────
        # Task weight (action) × phase modulation → effective weight
        # Cache confidence from Hebbian synaptic (per-seed learning).
        # Then process_cbr() handles compression + limiting + quantization.
        # No if/else thresholds. The math handles everything.
        task_weight = _ACTION_WEIGHT.get(self._action, 0.5)
        phase_mod = _PHASE_MODULATION.get(phase, 0.5)
        effective_weight = task_weight * phase_mod
        cache_conf = self.seed_confidence(seed) if seed else 0.0

        # VBR: Antaranga wave density — complexity signal from standing wave.
        # Many active slots = agent used many distinct tools = complex task.
        # Research: "TALE framework — ~70% token reduction via complexity-based allocation."
        from steward.services import SVC_ANTARANGA
        from vibe_core.di import ServiceRegistry

        antaranga = ServiceRegistry.get(SVC_ANTARANGA)
        wave_density = antaranga.active_count() / 512.0 if antaranga else 0.0

        cbr_out = process_cbr(
            context_pressure=context_pct,
            task_weight=effective_weight,
            cache_confidence=cache_conf,
            wave_density=wave_density,
        )
        max_tokens = cbr_out.budget

        # After errors, always grant bash for debugging
        if round_num > 0:
            recent_errors = sum(1 for r in self._chitta.recent(3) if not r.success)
            if recent_errors >= 2:
                base_tools = frozenset(base_tools | {"bash"})

        # ModelTier: action-derived, session-history-adjusted, phase-adjusted
        tier = _ACTION_TIER.get(self._action, ModelTier.STANDARD)

        # Hebbian escalation: synaptic weight < threshold → escalate tier
        # HebbianSynaptic from steward-protocol: default 0.5, success→1.0, failure→0.0
        if self._synaptic is not None:
            confidence = self._synaptic.get_weight(self._action.value, "execute")
            if confidence < 0.4:
                if tier == ModelTier.FLASH:
                    tier = ModelTier.STANDARD
                    logger.info("Tier escalated FLASH→STANDARD (synapse %.2f for %s)", confidence, self._action.value)
                elif tier == ModelTier.STANDARD and confidence < 0.25:
                    tier = ModelTier.PRO
                    logger.info("Tier escalated STANDARD→PRO (synapse %.2f for %s)", confidence, self._action.value)

        # PRO tasks demote to STANDARD in VERIFY/COMPLETE (work is done)
        if tier == ModelTier.PRO and phase in (ExecutionPhase.VERIFY, ExecutionPhase.COMPLETE):
            tier = ModelTier.STANDARD
        # Under context pressure, demote to save tokens
        if context_pct >= 0.7:
            tier = ModelTier.FLASH

        self._last_tier = tier

        return BuddhiDirective(
            action=self._action,
            guna=self._guna,
            tool_names=base_tools,
            max_tokens=max_tokens,
            tier=tier,
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
            params_hash = hash(frozenset((k, str(v)) for k, v in sorted(tc.parameters.items()))) if tc.parameters else 0
            path = str(tc.parameters.get("path", "")) if tc.parameters else ""
            self._chitta.record(
                name=tc.name,
                params_hash=params_hash,
                success=success,
                error=error,
                path=path,
            )

        # Gandha detects patterns in Chitta's impressions (cross-turn aware)
        all_tools = resolve_namespaces(frozenset(ToolNamespace))
        detection = detect_patterns(
            self._chitta.impressions,
            prior_reads=self._chitta.prior_reads,
            available_tools=all_tools,
        )
        self._last_pattern = detection.pattern if detection else ""
        if detection is not None:
            verdict = BuddhiVerdict(
                action=detection.severity,
                reason=detection.reason,
                suggestion=detection.suggestion,
            )
            logger.info(
                "Buddhi verdict at round %d: %s — %s",
                self._chitta.round,
                verdict.action,
                verdict.reason,
            )
            return verdict

        # Tool failure redirect — force LLM to try alternatives
        # The LLM is a pattern matcher. Without this, it sees "error" and says "sorry".
        # Infrastructure decides: any failed tool = redirect, not give up.
        failed = [(tc, err) for tc, (ok, err) in zip(tool_calls, results) if not ok]
        if failed:
            tc, err = failed[0]
            short_err = err[:150] if err else "unknown error"
            return BuddhiVerdict(
                action=VerdictAction.REDIRECT,
                reason=f"{tc.name} failed",
                suggestion=f"Tool '{tc.name}' returned error: {short_err}. Try an alternative approach.",
            )

        # Phase transition guidance
        curr_phase = self._chitta.phase
        if prev_phase != curr_phase:
            logger.info(
                "Buddhi phase transition: %s -> %s (round %d)",
                prev_phase,
                curr_phase,
                self._chitta.round,
            )
            guidance = _phase_guidance(prev_phase, curr_phase, self._chitta)
            if guidance:
                return BuddhiVerdict(
                    action=VerdictAction.REFLECT,
                    reason=f"Phase {prev_phase}->{curr_phase}",
                    suggestion=guidance,
                )

        return BuddhiVerdict(action=VerdictAction.CONTINUE)

    @property
    def phase(self) -> str:
        """Current phase (delegates to Chitta)."""
        return self._chitta.phase

    def reset(self) -> None:
        """Reset for a new task."""
        self._chitta.clear()
        self._prev_phase = ExecutionPhase.ORIENT

    @property
    def stats(self) -> dict[str, object]:
        """Diagnostic stats — delegates to Chitta."""
        return self._chitta.stats

    @property
    def last_action(self) -> str:
        """Last semantic action (for KsetraJna observation)."""
        return self._action.value

    @property
    def last_tier(self) -> str:
        """Last model tier (for KsetraJna observation)."""
        return self._last_tier.value

    @property
    def last_pattern(self) -> str:
        """Last gandha pattern name (for KsetraJna observation)."""
        return self._last_pattern

    def end_turn(self) -> None:
        """End current turn — delegates to Chitta for cross-turn merge."""
        self._chitta.end_turn()

    def synaptic_weights(self) -> list[float] | None:
        """Get synaptic weight values (for vedana health calculation).

        Returns None if no synaptic learning is configured.
        Public API — avoids _synaptic._weights encapsulation violation.
        """
        if self._synaptic is None:
            return None
        snapshot = self._synaptic.snapshot()
        return list(snapshot.values()) if snapshot else None

    def chitta_summary(self) -> dict[str, object]:
        """Serialize Chitta's cross-turn state for persistence."""
        return self._chitta.to_summary()

    def load_chitta_summary(self, summary: dict[str, object]) -> None:
        """Restore Chitta's cross-turn state from a persisted summary."""
        self._chitta.load_summary(summary)

    @property
    def chitta_prior_reads_count(self) -> int:
        """Number of prior reads (for logging)."""
        return len(self._chitta.prior_reads)

    @property
    def chitta_files_read(self) -> list[str]:
        """Files read this turn (for session ledger)."""
        return self._chitta.files_read

    @property
    def chitta_files_written(self) -> list[str]:
        """Files written this turn (for session ledger)."""
        return self._chitta.files_written


def _phase_guidance(
    prev: ExecutionPhase,
    curr: ExecutionPhase,
    chitta: Chitta,
) -> str:
    """Generate guidance for a phase transition.

    Only injects guidance for FORWARD transitions that the LLM
    needs to know about. Error regression is Gandha's job.

    Returns guidance text or empty string (no guidance needed).
    """
    # EXECUTE -> VERIFY: nudge to run tests after modifications
    if prev == ExecutionPhase.EXECUTE and curr == ExecutionPhase.VERIFY:
        modified = chitta.files_written
        if modified:
            file_list = ", ".join(modified[:5])
            extra = f" (+{len(modified) - 5} more)" if len(modified) > 5 else ""
            return f"You've modified: {file_list}{extra}. Consider running tests to verify your changes work correctly."
        return "You've made changes. Consider running tests to verify."

    return ""
