"""
MOKSHA Phase Hooks — Persistence, state commit, federation flush.

MOKSHA = liberation/release. The agent releases state to durable storage
and flushes outbound federation messages.
"""

from __future__ import annotations

import logging
from pathlib import Path

from steward.phase_hook import MOKSHA, BasePhaseHook, PhaseContext
from steward.services import (
    SVC_FEDERATION,
    SVC_FEDERATION_RELAY,
    SVC_FEDERATION_TRANSPORT,
    SVC_GIT_NADI_SYNC,
    SVC_MARKETPLACE,
    SVC_REAPER,
    SVC_SYNAPSE_STORE,
)
from vibe_core.di import ServiceRegistry

logger = logging.getLogger("STEWARD.HOOKS.MOKSHA")


class MokshaSynapseHook(BasePhaseHook):
    """Persist Hebbian learning weights."""

    @property
    def name(self) -> str:
        return "moksha_synapse"

    @property
    def phase(self) -> str:
        return MOKSHA

    @property
    def priority(self) -> int:
        return 20

    def execute(self, ctx: PhaseContext) -> None:
        synapse_store = ServiceRegistry.get(SVC_SYNAPSE_STORE)
        if synapse_store is not None:
            try:
                synapse_store.save()
            except Exception as e:
                logger.debug("SynapseStore save failed (non-fatal): %s", e)


class MokshaPersistenceHook(BasePhaseHook):
    """Persist reaper peer state and marketplace claims to disk."""

    @property
    def name(self) -> str:
        return "moksha_persistence"

    @property
    def phase(self) -> str:
        return MOKSHA

    @property
    def priority(self) -> int:
        return 50

    def execute(self, ctx: PhaseContext) -> None:
        steward_dir = Path(ctx.cwd) / ".steward"

        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is not None:
            reaper.save(steward_dir / "peers.json")

        marketplace = ServiceRegistry.get(SVC_MARKETPLACE)
        if marketplace is not None:
            marketplace.save(steward_dir / "marketplace.json")



class MokshaFederationHook(BasePhaseHook):
    """Flush outbound federation events via transport."""

    @property
    def name(self) -> str:
        return "moksha_federation"

    @property
    def phase(self) -> str:
        return MOKSHA

    @property
    def priority(self) -> int:
        return 80  # Cleanup band — flush after all state committed

    def execute(self, ctx: PhaseContext) -> None:
        federation = ServiceRegistry.get(SVC_FEDERATION)
        transport = ServiceRegistry.get(SVC_FEDERATION_TRANSPORT)
        if federation is not None and transport is not None:
            flushed = federation.flush_outbound(transport)
            if flushed:
                logger.debug("FEDERATION: flushed %d outbound events", flushed)

                # Push to hub via GitHub API relay (cross-repo delivery)
                relay = ServiceRegistry.get(SVC_FEDERATION_RELAY)
                if relay is not None:
                    pushed = relay.push_to_hub()
                    if pushed:
                        logger.info("FEDERATION: relay pushed %d messages to hub", pushed)

                # Git push after flushing — publish messages to remote
                git_sync = ServiceRegistry.get(SVC_GIT_NADI_SYNC)
                if git_sync is not None:
                    git_sync.push()
