"""
DHARMA Immune Hook — Self-healing during the duty cycle.

Runs StewardImmune.run_self_diagnostics() to find and fix
code pathogens in the agent's own codebase. The immune system
tests itself, discovers failures, matches them to known
pathogens, and applies CST/AST surgical fixes.

Buddhi evaluates every finding — no blind except-pass.
"""

from __future__ import annotations

import logging

from steward.phase_hook import DHARMA, BasePhaseHook, PhaseContext
from steward.services import SVC_IMMUNE
from vibe_core.di import ServiceRegistry

logger = logging.getLogger("STEWARD.HOOKS.DHARMA_IMMUNE")


class DharmaImmuneHook(BasePhaseHook):
    """Run immune self-diagnostics during DHARMA phase."""

    @property
    def name(self) -> str:
        return "dharma_immune"

    @property
    def phase(self) -> str:
        return DHARMA

    @property
    def priority(self) -> int:
        return 60  # After federation (50), before cleanup

    def should_run(self, ctx: PhaseContext) -> bool:
        # Only run if immune system is available
        immune = ServiceRegistry.get(SVC_IMMUNE)
        return immune is not None and immune.available

    def execute(self, ctx: PhaseContext) -> None:
        immune = ServiceRegistry.get(SVC_IMMUNE)
        if immune is None:
            return

        results = immune.run_self_diagnostics()

        healed = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        if healed:
            logger.info(
                "DHARMA IMMUNE: %d pathogens healed (%d failed)",
                len(healed), len(failed),
            )
            for r in healed:
                logger.info("  ✓ %s: %s", r.rule_id, r.message)

        if failed:
            for r in failed:
                logger.warning("  ✗ %s: %s", r.rule_id, r.message)

        ctx.operations.append(
            f"dharma_immune:healed={len(healed)},failed={len(failed)}"
        )
