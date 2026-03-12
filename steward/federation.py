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

    _outbound: list[BridgeEvent] = field(default_factory=list)
    _inbound_count: int = field(default=0, init=False)
    _outbound_count: int = field(default=0, init=False)
    _errors: int = field(default=0, init=False)
    _op_dispatch: dict = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._op_dispatch = {
            OP_HEARTBEAT: self._handle_heartbeat,
            OP_CLAIM_SLOT: self._handle_claim,
            OP_RELEASE_SLOT: self._handle_release,
            OP_DELEGATE_TASK: self._handle_delegate_task,
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

        messages = []
        for event in self._outbound:
            messages.append(
                {
                    "source": self.agent_id,
                    "target": "*",  # broadcast
                    "operation": event.operation,
                    "payload": event.payload,
                    "timestamp": event.timestamp,
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

    def stats(self) -> dict:
        return {
            "inbound_processed": self._inbound_count,
            "outbound_published": self._outbound_count,
            "outbound_pending": len(self._outbound),
            "errors": self._errors,
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
        self.reaper.record_heartbeat(agent_id, timestamp=ts, source=source)
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
