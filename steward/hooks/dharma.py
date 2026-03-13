"""
DHARMA Phase Hooks — Health monitoring, reaper, marketplace, federation.

DHARMA = duty/righteousness. The agent's duty cycle:
observe health → reap dead peers → purge expired slots → broadcast heartbeat.
"""

from __future__ import annotations

import logging
import time

from steward.phase_hook import DHARMA, BasePhaseHook, PhaseContext
from steward.services import (
    SVC_FEDERATION,
    SVC_FEDERATION_TRANSPORT,
    SVC_GIT_NADI_SYNC,
    SVC_MARKETPLACE,
    SVC_REAPER,
)
from vibe_core.di import ServiceRegistry

logger = logging.getLogger("STEWARD.HOOKS.DHARMA")


class DharmaHealthHook(BasePhaseHook):
    """Monitor vedana health — set anomaly flag when critical."""

    @property
    def name(self) -> str:
        return "dharma_health"

    @property
    def phase(self) -> str:
        return DHARMA

    @property
    def priority(self) -> int:
        return 10  # Setup band — health check first

    def execute(self, ctx: PhaseContext) -> None:
        v = ctx.vedana
        if v is None:
            return
        if v.health < 0.3:
            ctx.health_anomaly = True
            ctx.health_anomaly_detail = (
                f"DHARMA: health={v.health:.2f} ({v.guna}), "
                f"errors={v.error_pressure:.2f}, context={v.context_pressure:.2f}"
            )
            logger.warning("DHARMA: health critical (%.2f %s)", v.health, v.guna)


class DharmaReaperHook(BasePhaseHook):
    """Run HeartbeatReaper to detect and manage dead peers."""

    @property
    def name(self) -> str:
        return "dharma_reaper"

    @property
    def phase(self) -> str:
        return DHARMA

    @property
    def priority(self) -> int:
        return 30

    def execute(self, ctx: PhaseContext) -> None:
        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is None:
            return
        consequences = reaper.reap()
        for c in consequences:
            logger.warning(
                "REAPER[%s]: %s → %s (trust %.2f→%.2f)",
                c.agent_id,
                c.old_status,
                c.new_status,
                c.old_trust,
                c.new_trust,
            )


class DharmaMarketplaceHook(BasePhaseHook):
    """Purge expired marketplace claims."""

    @property
    def name(self) -> str:
        return "dharma_marketplace"

    @property
    def phase(self) -> str:
        return DHARMA

    @property
    def priority(self) -> int:
        return 40

    def execute(self, ctx: PhaseContext) -> None:
        marketplace = ServiceRegistry.get(SVC_MARKETPLACE)
        if marketplace is None:
            return
        purged = marketplace.purge_expired()
        if purged:
            logger.info("MARKET: purged %d expired claims", purged)


class DharmaFederationHook(BasePhaseHook):
    """Broadcast heartbeat and process inbound federation messages."""

    @property
    def name(self) -> str:
        return "dharma_federation"

    @property
    def phase(self) -> str:
        return DHARMA

    @property
    def priority(self) -> int:
        return 50

    _capabilities: tuple[str, ...] | None = None
    _identity: object | None = None

    def _get_capabilities(self) -> tuple[str, ...]:
        """Load capabilities from peer.json once, cache for session."""
        if self._capabilities is not None:
            return self._capabilities
        import json
        from pathlib import Path

        peer_path = Path("data/federation/peer.json")
        if peer_path.exists():
            try:
                data = json.loads(peer_path.read_text())
                self._capabilities = tuple(data.get("capabilities", []))
            except (json.JSONDecodeError, OSError):
                self._capabilities = ()
        else:
            self._capabilities = ()
        return self._capabilities

    def _get_identity(self) -> object:
        """Load identity once, cache for session."""
        if self._identity is not None:
            return self._identity
        from steward.identity import StewardIdentity

        self._identity = StewardIdentity.from_environment()
        return self._identity

    def execute(self, ctx: PhaseContext) -> None:
        federation = ServiceRegistry.get(SVC_FEDERATION)
        if federation is None:
            return
        from steward.federation import OP_HEARTBEAT

        v = ctx.vedana
        identity = self._get_identity()
        federation.emit(
            OP_HEARTBEAT,
            {
                "agent_id": federation.agent_id,
                "health": v.health if v is not None else 0.0,
                "timestamp": time.time(),
                "capabilities": list(self._get_capabilities()),
                "repo": identity.repo,
                "version": identity.version,
                "fingerprint": identity.fingerprint,
            },
        )
        # Git pull before reading — fetch latest messages from remote
        git_sync = ServiceRegistry.get(SVC_GIT_NADI_SYNC)
        if git_sync is not None:
            git_sync.pull()

        transport = ServiceRegistry.get(SVC_FEDERATION_TRANSPORT)
        if transport is not None:
            federation.process_inbound(transport)
