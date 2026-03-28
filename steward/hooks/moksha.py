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
    SVC_A2A_DISCOVERY,
    SVC_FEDERATION,
    SVC_FEDERATION_GATEWAY,
    SVC_FEDERATION_RELAY,
    SVC_FEDERATION_TRANSPORT,
    SVC_GIT_NADI_SYNC,
    SVC_MARKETPLACE,
    SVC_PR_VERDICT,
    SVC_REAPER,
    SVC_SYNAPSE_STORE,
)
from vibe_core.di import ServiceRegistry

logger = logging.getLogger("STEWARD.HOOKS.MOKSHA")


class MokshaSynapseHook(BasePhaseHook):
    """Persist Hebbian learning weights + annotation lifecycle.

    Decay: HebbianSynaptic.decay() regresses all weights toward 0.5.
    Trim:  HebbianSynaptic.trim() prunes weakest entries.
    Save:  Flush dirty weights to disk.
    """

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
                # Annotation lifecycle: decay + trim via substrate primitives
                from steward.annotations import decay_all, trim

                decay_all()
                trim(max_entries=50)

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
            reaper.save(Path(ctx.cwd) / "data" / "federation" / "peers.json")

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
            # Intercept PR verdict events before flushing — post them to GitHub
            pr_verdict_poster = ServiceRegistry.get(SVC_PR_VERDICT)
            if pr_verdict_poster is not None:
                from steward.federation import OP_PR_REVIEW_VERDICT

                for event in federation._outbound:
                    if event.operation == OP_PR_REVIEW_VERDICT:
                        pr_verdict_poster.post_from_nadi_event(event.payload)

            flushed = federation.flush_outbound(transport)
            if flushed:
                logger.info("FEDERATION: flushed %d outbound events to transport", flushed)

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

        # Drain gateway Hebbian signals → SynapseStore
        # Fire-and-forget: gateway queues signals during DHARMA, we flush here.
        gateway = ServiceRegistry.get(SVC_FEDERATION_GATEWAY)
        synapse_store = ServiceRegistry.get(SVC_SYNAPSE_STORE)
        if gateway is not None and synapse_store is not None:
            signals = gateway._stats.drain_signals()
            for protocol, success in signals:
                trigger = f"gw:{protocol}"
                if success:
                    synapse_store.increment_weight(trigger, "accept")
                else:
                    synapse_store.decrement_weight(trigger, "accept")

        # Persist A2A discovery state
        a2a_discovery = ServiceRegistry.get(SVC_A2A_DISCOVERY)
        if a2a_discovery is not None:
            a2a_discovery.save_discovered()

        # Persist A2A in-flight task state (survives reboots)
        from steward.services import SVC_A2A_ADAPTER

        a2a_adapter = ServiceRegistry.get(SVC_A2A_ADAPTER)
        if a2a_adapter is not None and hasattr(a2a_adapter, "save_tasks"):
            tasks_path = Path(ctx.cwd) / ".steward" / "a2a_tasks.json"
            saved = a2a_adapter.save_tasks(tasks_path)
            if saved:
                logger.debug("MOKSHA: persisted %d A2A tasks", saved)
