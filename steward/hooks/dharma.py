"""
DHARMA Phase Hooks — Health monitoring, reaper, marketplace, federation.

DHARMA = duty/righteousness. The agent's duty cycle:
observe health → reap dead peers → purge expired slots → broadcast heartbeat.
"""

from __future__ import annotations

import logging
import time

from steward.hooks.genesis import _get_federation_owner
from steward.phase_hook import DHARMA, BasePhaseHook, PhaseContext
from steward.services import (
    SVC_FEDERATION,
    SVC_FEDERATION_GATEWAY,
    SVC_FEDERATION_RELAY,
    SVC_FEDERATION_TRANSPORT,
    SVC_GIT_NADI_SYNC,
    SVC_KIRTAN,
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
    """Run HeartbeatReaper + KirtanLoop for peer health verification.

    Uses the KirtanLoop primitive (not ad-hoc diagnosed_peers.json):
    1. REAP:     Advance peer state machine
    2. CALL:     Suspect peer → diagnose + register with KirtanLoop
    3. VERIFY:   KirtanLoop checks if peers recovered
    4. ESCALATE: KirtanLoop exhausted → create task + GitHub Issue payload
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

    def execute(self, ctx: PhaseContext) -> None:
        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is None:
            return
        kirtan = ServiceRegistry.get(SVC_KIRTAN)

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

        # 2. CALL — diagnose suspect peers, register with KirtanLoop
        for peer in reaper.suspect_peers():
            action_id = f"diagnose:{peer.agent_id}"
            if kirtan is not None:
                # KirtanLoop handles dedup (won't re-register existing calls)
                kirtan.call(action_id, target=peer.agent_id, expected_outcome="peer_alive")
            self._diagnose_and_report(peer)

        # 3. VERIFY — check if diagnosed peers recovered
        if kirtan is not None:
            alive_ids = {p.agent_id for p in reaper.alive_peers()}
            outcomes = {f"diagnose:{aid}": True for aid in alive_ids}
            results = kirtan.verify_all(outcomes)

            for r in results:
                if r.result == "closed":
                    logger.info("KIRTAN CLOSED: %s recovered after %d attempts", r.target, r.attempts)
                elif r.result == "escalate":
                    payload = kirtan.escalate(r.action_id)
                    self._escalate_to_task(r.target, payload)

    def _diagnose_and_report(self, peer: object) -> None:
        """CALL: Diagnose a suspect peer and send report via NADI."""
        agent_id = peer.agent_id
        logger.info("KIRTAN CALL: diagnosing suspect peer %s", agent_id)

        diagnostic = self._run_diagnostic(agent_id)

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

    def _run_diagnostic(self, agent_id: str) -> dict:
        """Quick diagnostic on a suspect peer."""
        import subprocess

        owner = _get_federation_owner()
        result: dict = {"agent_id": agent_id, "checks": []}
        try:
            r = subprocess.run(
                ["gh", "api", f"repos/{owner}/{agent_id}", "--jq", ".pushed_at"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0:
                result["last_push"] = r.stdout.strip()
                result["checks"].append("repo_accessible")
            else:
                result["checks"].append("repo_inaccessible")
        except Exception:
            result["checks"].append("repo_check_failed")

        try:
            import json as _json

            r = subprocess.run(
                ["gh", "run", "list", "-R", f"{owner}/{agent_id}", "--limit", "1", "--json", "conclusion,name"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0:
                runs = _json.loads(r.stdout)
                if runs:
                    result["last_ci"] = runs[0]
                    result["checks"].append(f"ci_{runs[0].get('conclusion', 'unknown')}")
        except Exception:
            result["checks"].append("ci_check_failed")

        return result

    def _escalate_to_task(self, target: str, payload: dict) -> None:
        """KirtanLoop exhausted → GitHub Issue + high-priority task."""
        import subprocess

        # 1. GitHub Issue (visible, trackable — not a dead MD file)
        title = f"[FEDERATION] Peer {target} unresponsive after diagnosis"
        body = (
            f"## Kirtan Escalation\n\n"
            f"Peer `{target}` was diagnosed as suspect. Diagnostic was sent via NADI. "
            f"After {payload.get('attempts', '?')} verification cycles, no recovery observed.\n\n"
            f"**Payload**: {payload}\n\n"
            f"This issue was created automatically by the steward's Kirtan loop."
        )
        try:
            r = subprocess.run(
                [
                    "gh",
                    "issue",
                    "create",
                    "--repo",
                    f"{_get_federation_owner()}/steward",
                    "--title",
                    title,
                    "--body",
                    body,
                    "--label",
                    "federation-health",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if r.returncode == 0:
                logger.warning("KIRTAN ESCALATE: %s → GitHub Issue %s", target, r.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # 2. Task in TaskManager (for the steward's own KARMA phase)
        from steward.services import SVC_TASK_MANAGER

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            return

        from vibe_core.task_types import TaskStatus

        active = task_mgr.list_tasks(status=TaskStatus.PENDING) + task_mgr.list_tasks(status=TaskStatus.IN_PROGRESS)
        task_title = f"[HEAL_REPO] Peer {target} — Kirtan escalation"
        if any(t.title == task_title for t in active):
            return

        task_mgr.add_task(title=task_title, priority=90, description=str(payload))
        logger.warning("KIRTAN ESCALATE: %s — [HEAL_REPO] task created (pri=90)", target)


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
    """Broadcast heartbeat and process inbound federation messages.

    Runs BEFORE reaper (priority 10 < 30) so inbound heartbeats are recorded
    before peer liveness is assessed. This prevents false evictions of peers
    that sent messages in the previous heartbeat cycle.
    """

    @property
    def name(self) -> str:
        return "dharma_federation"

    @property
    def phase(self) -> str:
        return DHARMA

    @property
    def priority(self) -> int:
        return 10

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

        # Record heartbeats for unique sources in pulled messages
        import json
        from pathlib import Path

        inbox_path = Path("data/federation/nadi_inbox.json")
        if inbox_path.exists():
            try:
                messages = json.loads(inbox_path.read_text())
                sources = {msg.get("source") for msg in messages if msg.get("source")}
                reaper = ServiceRegistry.get(SVC_REAPER)
                for source in sources:
                    if reaper is not None:
                        reaper.record_heartbeat(agent_id=source, source="nadi_inbox")
                if sources:
                    logger.info("FEDERATION: recorded heartbeats for %d inbox sources: %s", len(sources), ", ".join(sorted(sources)))
            except (json.JSONDecodeError, OSError):
                pass

        # Check for stale delivery receipts — messages that were pushed
        # but never implicitly confirmed by a response from the target.
        # This closes the fire-and-forget gap: agent-internet defines
        # DeliveryReceipt types; steward now implements the tracking.
        relay = ServiceRegistry.get(SVC_FEDERATION_RELAY)
        if relay is not None and hasattr(relay, "stale_receipts"):
            stale = relay.stale_receipts()
            if stale:
                targets = {r.target for r in stale}
                logger.warning(
                    "FEDERATION: %d stale delivery receipts (targets: %s) — messages may not have been consumed",
                    len(stale),
                    ", ".join(sorted(targets)),
                )
                # Register stale targets with KirtanLoop for escalation
                kirtan = ServiceRegistry.get(SVC_KIRTAN)
                if kirtan is not None:
                    for target in targets:
                        kirtan.call(
                            f"delivery:{target}",
                            target=target,
                            expected_outcome="delivery_confirmed",
                        )

        transport = ServiceRegistry.get(SVC_FEDERATION_TRANSPORT)
        if transport is not None:
            # Self-register steward's crypto node_id on first contact.
            # The transport signs outbound messages with its NodeKeyStore node_id
            # (e.g. ag_e3331b...). Without this, steward's own signed heartbeats
            # come back via the legacy outbox and get blocked by the zero-trust gate.
            node_id = getattr(transport, "node_id", None)
            pub_key = getattr(transport, "public_key", None)
            if node_id and pub_key and not federation.is_verified_agent(node_id):
                federation.ingest(
                    "federation.agent_claim",
                    {
                        "node_id": node_id,
                        "agent_name": federation.agent_id,
                        "public_key": pub_key,
                        "capabilities": list(self._get_capabilities()),
                    },
                )
                logger.info("FEDERATION: self-registered crypto identity node_id=%s", node_id)

            # Route through FederationGateway (Five Tattva Gates) if available,
            # fallback to direct bridge processing if gateway not wired.
            gateway = ServiceRegistry.get(SVC_FEDERATION_GATEWAY)
            if gateway is not None:
                processed = gateway.process_inbound(transport)
                if processed:
                    logger.info("FEDERATION: gateway processed %d inbound messages", processed)
            else:
                federation.process_inbound(transport)
