"""
MOKSHA Context Bridge Hook — Steward persists its living state to context.json.

Every heartbeat tick (MOKSHA phase), steward writes its full context to:
  - .steward/context.json  (machine-readable, full fidelity)

CLAUDE.md is NOT written here — that's synthesized by steward's own LLM
via the synthesize_briefing tool, triggered by Sankalpa missions or
on-demand tool use.

Priority 85: runs after persistence (50) and federation flush (80),
so all state is committed before the bridge reads it.

Rate-limited to one write per 5 seconds to avoid filesystem churn.
"""

from __future__ import annotations

import logging
import time

from steward.phase_hook import MOKSHA, BasePhaseHook, PhaseContext

logger = logging.getLogger("STEWARD.HOOKS.MOKSHA_BRIDGE")


class MokshaContextBridgeHook(BasePhaseHook):
    """Write steward's living context to .steward/context.json."""

    def __init__(self) -> None:
        self._last_write: float = 0.0
        self._min_interval: float = 5.0

    @property
    def name(self) -> str:
        return "moksha_context_bridge"

    @property
    def phase(self) -> str:
        return MOKSHA

    @property
    def priority(self) -> int:
        return 85

    def execute(self, ctx: PhaseContext) -> None:
        now = time.time()
        if (now - self._last_write) < self._min_interval:
            return

        try:
            from steward.context_bridge import assemble_context, write_context_json

            context = assemble_context(ctx.cwd)

            # Inject live vedana from PhaseContext if available
            if ctx.vedana is not None:
                v = ctx.vedana
                context["health"] = {
                    "value": round(v.health, 3),
                    "guna": v.guna,
                    "provider_health": round(v.provider_health, 3),
                    "error_pressure": round(v.error_pressure, 3),
                    "context_pressure": round(getattr(v, "context_pressure", 0), 3),
                }

            written = write_context_json(ctx.cwd, context)
            if written:
                ctx.operations.append("moksha_context_bridge:updated")

            self._last_write = now
        except Exception as e:
            logger.debug("Context bridge write failed (non-fatal): %s", e)
