"""
Federation Bridge — Routes cross-agent messages to local services.

Steward's Reaper and Marketplace are local in-process services. The
federation bridge connects them to the outside world:

    INBOUND:  FederationMessage → route by operation → Reaper/Marketplace
    OUTBOUND: local events → FederationMessage → any transport

The bridge is transport-agnostic. Any transport implementing the
FederationTransport protocol (agent-internet's FilesystemTransport,
wiki sync, HTTP, MCP) can plug in. No hardcoded repos.

Integration:
    DHARMA phase: bridge.process_inbound(transport)
    MOKSHA phase: bridge.flush_outbound(transport)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

logger = logging.getLogger("STEWARD.FEDERATION")

# ── Protocols ──────────────────────────────────────────────────────

# These protocols define what the bridge needs. Any transport or
# service that matches can plug in — no imports required.


@runtime_checkable
class FederationTransport(Protocol):
    """Transport layer for federation messages.

    Matches agent-internet's FederationTransport interface.
    Implementations: FilesystemFederationTransport, wiki sync, HTTP.
    """

    def read_outbox(self) -> list[dict]: ...
    def append_to_inbox(self, messages: list[object]) -> int: ...


@runtime_checkable
class ReaperLike(Protocol):
    """Anything that accepts heartbeats and reaps dead peers."""

    def record_heartbeat(
        self,
        agent_id: str,
        timestamp: float | None = None,
        source: str = "",
    ) -> None: ...

    def reap(self, now: float | None = None) -> list: ...


@runtime_checkable
class MarketplaceLike(Protocol):
    """Anything that handles slot claims."""

    def claim(
        self,
        slot_id: str,
        agent_id: str,
        trust: float = 0.0,
        ttl_s: float | None = None,
    ) -> object: ...

    def release(self, slot_id: str, agent_id: str) -> bool: ...


# ── Wire Format ───────────────────────────────────────────────────

# Operations the bridge understands. Aligned with steward-protocol's
# FederationMessage.operation field.

OP_HEARTBEAT = "heartbeat"
OP_CLAIM_SLOT = "claim_slot"
OP_RELEASE_SLOT = "release_slot"
OP_EVICTION = "eviction"
OP_CLAIM_OUTCOME = "claim_outcome"
OP_DELEGATE_TASK = "delegate_task"
OP_TASK_COMPLETED = "task_completed"
OP_TASK_FAILED = "task_failed"
OP_DIAGNOSTIC_REQUEST = "diagnostic_request"
OP_DIAGNOSTIC_REPORT = "diagnostic_report"
OP_MERGE_OCCURRED = "merge_occurred"

# Minimum trust level to accept inbound delegations
DEFAULT_DELEGATION_TRUST_FLOOR: float = 0.3


@dataclass(frozen=True)
class BridgeEvent:
    """Outbound event produced by local services for federation broadcast."""

    operation: str
    agent_id: str
    payload: dict
    timestamp: float


# ── Bridge ────────────────────────────────────────────────────────


@dataclass
class FederationBridge:
    """Routes federation messages to local Reaper + Marketplace.

    Usage:
        bridge = FederationBridge(reaper=reaper, marketplace=marketplace)

        # DHARMA phase — consume inbound messages
        bridge.process_inbound(transport)

        # MOKSHA phase — publish outbound events
        bridge.flush_outbound(transport)

    The bridge is stateless except for the outbound queue. It doesn't
    care where messages come from — any FederationTransport works.
    """

    reaper: ReaperLike | None = None
    marketplace: MarketplaceLike | None = None
    agent_id: str = "steward"  # our identity in federation messages
    delegation_trust_floor: float = DEFAULT_DELEGATION_TRUST_FLOOR

    _outbound: list[BridgeEvent] = field(default_factory=list)
    _inbound_count: int = field(default=0, init=False)
    _outbound_count: int = field(default=0, init=False)
    _errors: int = field(default=0, init=False)
    _delegations_rejected: int = field(default=0, init=False)
    _op_dispatch: dict = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._op_dispatch = {
            OP_HEARTBEAT: self._handle_heartbeat,
            OP_CLAIM_SLOT: self._handle_claim,
            OP_RELEASE_SLOT: self._handle_release,
            OP_DELEGATE_TASK: self._handle_delegate_task,
            OP_TASK_COMPLETED: self._handle_task_callback,
            OP_TASK_FAILED: self._handle_task_callback,
        }

    def ingest(self, operation: str, payload: dict) -> bool:
        """Route inbound message via O(1) dispatch table."""
        self._inbound_count += 1
        handler = self._op_dispatch.get(operation)
        if handler is None:
            logger.debug("BRIDGE: unknown operation '%s'", operation)
            return False
        return handler(payload)

    def process_inbound(self, transport: FederationTransport) -> int:
        """Read all pending messages from transport and route them.

        Returns count of messages processed.
        """
        try:
            messages = transport.read_outbox()
        except Exception as e:
            logger.warning("BRIDGE: read_outbox failed: %s", e)
            self._errors += 1
            return 0

        processed = 0
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            op = msg.get("operation", "")
            payload = msg.get("payload", {})
            if self.ingest(op, payload):
                processed += 1
        return processed

    def flush_outbound(self, transport: FederationTransport) -> int:
        """Publish all pending outbound events via transport.

        Returns count of messages published.
        """
        if not self._outbound:
            return 0

        # Get known peer IDs for targeted delivery (not broadcast *)
        peer_ids = []
        if self.reaper is not None:
            for p in self.reaper.alive_peers() + self.reaper.suspect_peers():
                if p.agent_id != self.agent_id:
                    peer_ids.append(p.agent_id)

        messages = []
        for event in self._outbound:
            targets = peer_ids if peer_ids else ["*"]
            for target in targets:
                messages.append(
                    {
                        "source": self.agent_id,
                        "target": target,
                        "operation": event.operation,
                        "payload": event.payload,
                        "timestamp": event.timestamp,
                        "priority": 1,
                        "correlation_id": "",
                        "ttl_s": 900.0,
                    }
                )

        try:
            count = transport.append_to_inbox(messages)
            self._outbound_count += len(self._outbound)
            self._outbound.clear()
            return count if isinstance(count, int) else len(messages)
        except Exception as e:
            logger.warning("BRIDGE: append_to_inbox failed: %s", e)
            self._errors += 1
            return 0

    # Max outbound events queued before oldest are dropped.
    # Matches NADI_BUFFER_SIZE from federation_transport.py.
    _MAX_OUTBOUND = 144

    def emit(self, operation: str, payload: dict) -> None:
        """Queue an outbound event for federation broadcast."""
        self._outbound.append(
            BridgeEvent(
                operation=operation,
                agent_id=self.agent_id,
                payload=payload,
                timestamp=time.time(),
            )
        )
        # Cap queue — drop oldest if over limit
        if len(self._outbound) > self._MAX_OUTBOUND:
            self._outbound = self._outbound[-self._MAX_OUTBOUND :]

    def stats(self) -> dict:
        return {
            "inbound_processed": self._inbound_count,
            "outbound_published": self._outbound_count,
            "outbound_pending": len(self._outbound),
            "errors": self._errors,
            "delegations_rejected": self._delegations_rejected,
        }

    # ── Private Handlers ──────────────────────────────────────────

    def _handle_heartbeat(self, payload: dict) -> bool:
        if self.reaper is None:
            return False
        agent_id = payload.get("agent_id")
        if not agent_id:
            return False
        ts = payload.get("timestamp")
        source = payload.get("source", "federation")
        capabilities = payload.get("capabilities")
        fingerprint = payload.get("fingerprint", "")
        caps = tuple(capabilities) if isinstance(capabilities, list) else ()
        self.reaper.record_heartbeat(
            agent_id,
            timestamp=ts,
            source=source,
            capabilities=caps,
            fingerprint=fingerprint,
        )
        return True

    def _handle_claim(self, payload: dict) -> bool:
        if self.marketplace is None:
            return False
        slot_id = payload.get("slot_id")
        agent_id = payload.get("agent_id")
        if not slot_id or not agent_id:
            return False
        trust = payload.get("trust", 0.0)
        outcome = self.marketplace.claim(slot_id, agent_id, trust=trust)
        # Emit outcome for federation peers to observe
        self.emit(
            OP_CLAIM_OUTCOME,
            {
                "slot_id": slot_id,
                "agent_id": agent_id,
                "granted": getattr(outcome, "granted", False),
                "holder": getattr(outcome, "holder", ""),
                "reason": getattr(outcome, "reason", ""),
            },
        )
        return True

    def _handle_release(self, payload: dict) -> bool:
        if self.marketplace is None:
            return False
        slot_id = payload.get("slot_id")
        agent_id = payload.get("agent_id")
        if not slot_id or not agent_id:
            return False
        self.marketplace.release(slot_id, agent_id)
        return True

    def _handle_delegate_task(self, payload: dict) -> bool:
        """Inbound task delegation from a peer agent.

        Trust-gated: rejects delegations from peers below trust floor.
        Pushes the task into the local TaskManager queue. KARMA phase
        will pick it up and dispatch it like any other autonomous task.

        Payload:
            title: str — task title (should include [INTENT] prefix)
            priority: int — 0-100
            source_agent: str — who delegated
            repo: str — target repo URL (optional, for cross-repo work)
        """
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            logger.warning("BRIDGE: delegate_task but no TaskManager registered")
            return False

        title = payload.get("title")
        if not title:
            return False

        source = payload.get("source_agent", "unknown")
        priority = payload.get("priority", 50)
        repo = payload.get("repo", "")

        # Trust gate: reject delegations from untrusted peers
        if self.reaper is not None and source != "unknown":
            peer = self.reaper.get_peer(source) if hasattr(self.reaper, "get_peer") else None
            if peer is not None and peer.trust < self.delegation_trust_floor:
                self._delegations_rejected += 1
                logger.warning(
                    "BRIDGE: delegation REJECTED from %s (trust=%.2f < floor=%.2f): '%s'",
                    source,
                    peer.trust,
                    self.delegation_trust_floor,
                    title,
                )
                return False

        # Prefix with source for traceability
        full_title = f"[FED:{source}] {title}"
        description = f"repo:{repo}" if repo else ""
        task_mgr.add_task(title=full_title, priority=priority, description=description)
        logger.info(
            "BRIDGE: delegated task from %s → '%s' (priority=%d)",
            source,
            title,
            priority,
        )
        return True

    def _handle_task_callback(self, payload: dict) -> bool:
        """Inbound task completion/failure callback from a peer.

        When we delegated a task to a peer, this is their response.
        Wakes up BLOCKED tasks in TaskManager that match the callback.

        Payload:
            task_title: str — the original task title we delegated
            source_agent: str — who completed it (should match target_agent)
            pr_url: str — PR link if applicable (task_completed only)
            error: str — error message (task_failed only)
        """
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            return False

        task_title = payload.get("task_title", "")
        source_agent = payload.get("source_agent", "unknown")
        pr_url = payload.get("pr_url", "")
        error = payload.get("error", "")

        if not task_title:
            return False

        from vibe_core.task_types import TaskStatus

        # Find BLOCKED tasks that match this callback
        blocked = task_mgr.list_tasks(status=TaskStatus.BLOCKED)
        matched = None
        for task in blocked:
            desc = getattr(task, "description", "") or ""
            # Match by delegated task title stored in description
            if f"delegated:{task_title}" in desc:
                matched = task
                break

        if matched is None:
            logger.debug(
                "BRIDGE: callback for '%s' from %s — no matching BLOCKED task",
                task_title,
                source_agent,
            )
            return False

        # Resume the task: BLOCKED → PENDING with result context
        result_context = f"peer_result:{pr_url}" if pr_url else f"peer_error:{error}" if error else "peer_result:done"
        task_mgr.update_task(
            matched.id,
            status=TaskStatus.PENDING,
            description=result_context,
        )
        logger.info(
            "BRIDGE: callback from %s resumed task '%s' (result=%s)",
            source_agent,
            matched.title,
            result_context[:80],
        )
        return True
