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
    SVC_FEDERATION_RELAY,
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
    """Run HeartbeatReaper + Kirtan loop: CALL (diagnose suspect) → RESPONSE (verify next cycle).

    The Steward is not a passive monitor. When a peer becomes suspect:
    1. CALL: Run diagnostic on the peer repo immediately
    2. REPORT: Send diagnostic_report via NADI to the peer
    3. RESPONSE: Next cycle, check if peer recovered (heartbeat resumed)
    4. ESCALATE: If still suspect/dead after diagnostic, create high-priority task

    This is Call and Response — not fire-and-forget.
    """

    @property
    def name(self) -> str:
        return "dharma_reaper"

    @property
    def phase(self) -> str:
        return DHARMA

    @property
    def priority(self) -> int:
        return 30

    _DIAGNOSED_PATH = "data/federation/diagnosed_peers.json"

    def execute(self, ctx: PhaseContext) -> None:
        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is None:
            return

        # Load persisted diagnosed state (survives CI restarts)
        diagnosed = self._load_diagnosed()

        # 1. REAP — advance peer state machine
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

        # 2. CALL — diagnose suspect peers immediately (not at dead)
        for peer in reaper.suspect_peers():
            if peer.agent_id in diagnosed:
                continue
            diagnosed.add(peer.agent_id)
            self._diagnose_and_report(peer)

        # 3. ESCALATE — dead peers that didn't recover after diagnostic
        dead = reaper.dead_peers()
        if dead:
            self._escalate_dead_peers(dead)
            # Cycle complete for dead peers — clear from diagnosed so they
            # can be re-diagnosed if they come back and go suspect again.
            # Without this, diagnosed grows endlessly and the steward
            # stops diagnosing after a few weeks.
            dead_ids = {p.agent_id for p in dead}
            diagnosed -= dead_ids

        # 4. RESPONSE — clear diagnosed set for recovered peers
        alive_ids = {p.agent_id for p in reaper.alive_peers()}
        recovered = diagnosed & alive_ids
        if recovered:
            for agent_id in recovered:
                logger.info("KIRTAN RESPONSE: %s recovered — loop closed", agent_id)
            diagnosed -= recovered

        # Persist diagnosed state for next CI run
        self._save_diagnosed(diagnosed)

    def _diagnose_and_report(self, peer: object) -> None:
        """CALL: Diagnose a suspect peer and send report via NADI."""
        agent_id = peer.agent_id
        logger.info("KIRTAN CALL: diagnosing suspect peer %s", agent_id)

        # Run diagnostic — check CI, repo health, workflow status
        diagnostic = self._run_diagnostic(agent_id)

        # Send diagnostic report via federation NADI
        federation = ServiceRegistry.get(SVC_FEDERATION)
        if federation is not None:
            from steward.federation import OP_DIAGNOSTIC_REPORT

            federation.emit(
                OP_DIAGNOSTIC_REPORT,
                {
                    "target_peer": agent_id,
                    "diagnostic": diagnostic,
                    "steward_action": "suspect_investigation",
                    "trust": getattr(peer, "trust", 0.0),
                },
            )
            logger.info("KIRTAN CALL: diagnostic report sent to %s via NADI", agent_id)

    def _run_diagnostic(self, agent_id: str) -> dict:
        """Quick diagnostic on a suspect peer — what's wrong?"""
        result: dict = {"agent_id": agent_id, "checks": []}

        # Check if we can reach the peer's repo via GitHub API
        import subprocess

        try:
            r = subprocess.run(
                ["gh", "api", f"repos/kimeisele/{agent_id}", "--jq", ".pushed_at"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                result["last_push"] = r.stdout.strip()
                result["checks"].append("repo_accessible")
            else:
                result["checks"].append("repo_inaccessible")
        except Exception:
            result["checks"].append("repo_check_failed")

        # Check CI status
        try:
            r = subprocess.run(
                ["gh", "run", "list", "-R", f"kimeisele/{agent_id}",
                 "--limit", "1", "--json", "conclusion,name"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                import json
                runs = json.loads(r.stdout)
                if runs:
                    result["last_ci"] = runs[0]
                    conclusion = runs[0].get("conclusion", "unknown")
                    result["checks"].append(f"ci_{conclusion}")
        except Exception:
            result["checks"].append("ci_check_failed")

        return result

    def _escalate_dead_peers(self, dead: list) -> None:
        """ESCALATE: Dead peers → high-priority task for intervention."""
        from steward.services import SVC_TASK_MANAGER

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            return

        from vibe_core.task_types import TaskStatus

        active = task_mgr.list_tasks(status=TaskStatus.PENDING) + task_mgr.list_tasks(status=TaskStatus.IN_PROGRESS)
        active_titles = {t.title for t in active}

        for peer in dead:
            title = f"[FEDERATION_HEALTH] Peer {peer.agent_id} dead — diagnostic sent, no recovery"
            if title not in active_titles:
                task_mgr.add_task(
                    title=title,
                    priority=90,  # High — peer didn't recover after diagnostic
                    description=(
                        f"Peer {peer.agent_id} is DEAD after diagnostic was sent. "
                        f"Trust: {peer.trust:.2f}. The Kirtan CALL got no RESPONSE. "
                        f"Manual intervention may be required."
                    ),
                )
                logger.warning("KIRTAN ESCALATE: %s dead after diagnostic — task created (pri=90)", peer.agent_id)

    def _load_diagnosed(self) -> set[str]:
        """Load persisted diagnosed set from disk (survives CI restarts)."""
        import json
        from pathlib import Path

        path = Path(self._DIAGNOSED_PATH)
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text())
            return set(data) if isinstance(data, list) else set()
        except (json.JSONDecodeError, OSError):
            return set()

    def _save_diagnosed(self, diagnosed: set[str]) -> None:
        """Persist diagnosed set to disk."""
        import json
        from pathlib import Path

        path = Path(self._DIAGNOSED_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(diagnosed)))


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
        # Pull messages from hub via GitHub API relay (cross-repo delivery)
        relay = ServiceRegistry.get(SVC_FEDERATION_RELAY)
        if relay is not None:
            pulled = relay.pull_from_hub()
            if pulled:
                logger.info("FEDERATION: relay pulled %d messages from hub", pulled)

        # Git pull before reading — fetch latest messages from remote
        git_sync = ServiceRegistry.get(SVC_GIT_NADI_SYNC)
        if git_sync is not None:
            git_sync.pull()

        transport = ServiceRegistry.get(SVC_FEDERATION_TRANSPORT)
        if transport is not None:
            federation.process_inbound(transport)
