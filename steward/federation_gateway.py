"""
Federation Gateway — Unified entry point for ALL federation protocols.

Implements vibe_core's GatewayProtocol with Five Tattva Gates:
    PARSE     → Strict schema-based protocol detection (A2A, NADI, MCP)
    VALIDATE  → Verify sender identity via Reaper trust check
    EXECUTE   → Route through FederationBridge O(1) dispatch
    RESULT    → Format response in sender's protocol
    SYNC      → Fire-and-forget Hebbian learning (non-blocking)

Architecture:
    External protocols (A2A, MCP) are "dumb transport" — they get translated
    to NADI at the boundary. The intelligence lives in the substrate
    (FederationBridge, Reaper, Marketplace), not in the protocol layer.

    A2A JSON-RPC  ──┐
    NADI raw        ──┼──→ FederationGateway.receive() ──→ FederationBridge
    MCP (future)   ──┘

Wire as SVC_FEDERATION_GATEWAY in services.py.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from steward.federation import PROTECTED_OPERATIONS, PUBLIC_OPERATIONS
from steward.federation_crypto import derive_node_id, verify_payload_signature
from vibe_core.protocols.gateway import EntryType, GatewayProtocol, GatewayRequest, GatewayResponse

logger = logging.getLogger("STEWARD.FEDERATION_GATEWAY")


# ── Protocol Schemas (deterministic detection) ─────────────────────
# Each protocol has required fields. If a message matches none → reject.


def _is_a2a(msg: dict) -> bool:
    """A2A JSON-RPC 2.0: must have 'jsonrpc' and 'method' fields."""
    return msg.get("jsonrpc") == "2.0" and isinstance(msg.get("method"), str)


def _is_nadi(msg: dict) -> bool:
    """NADI federation: must have 'operation' and 'source' fields."""
    return isinstance(msg.get("operation"), str) and isinstance(msg.get("source"), str)


# Protocol tag → detector
_PROTOCOL_DETECTORS: dict[str, object] = {
    "a2a": _is_a2a,
    "nadi": _is_nadi,
}


@dataclass
class GatewayStats:
    """Observable gateway metrics."""

    total_requests: int = 0
    by_protocol: dict[str, int] = field(default_factory=dict)
    rejected_parse: int = 0
    rejected_validate: int = 0
    errors: int = 0
    last_request_time: float = 0.0
    # Fire-and-forget Hebbian signals queued for MOKSHA processing
    _pending_signals: list[tuple[str, bool]] = field(default_factory=list)

    def record(self, protocol: str, success: bool) -> None:
        self.total_requests += 1
        self.by_protocol[protocol] = self.by_protocol.get(protocol, 0) + 1
        self.last_request_time = time.time()
        # Queue Hebbian signal — processed in MOKSHA, never blocks gateway
        self._pending_signals.append((protocol, success))

    def drain_signals(self) -> list[tuple[str, bool]]:
        """Drain pending Hebbian signals (called by MOKSHA hook)."""
        signals = list(self._pending_signals)
        self._pending_signals.clear()
        return signals

    def to_dict(self) -> dict[str, object]:
        return {
            "total_requests": self.total_requests,
            "by_protocol": dict(self.by_protocol),
            "rejected_parse": self.rejected_parse,
            "rejected_validate": self.rejected_validate,
            "errors": self.errors,
            "pending_signals": len(self._pending_signals),
        }


# Replay protection — sliding timestamp window + per-source LRU of seen hashes.
# Window is generous enough to absorb clock skew and NADI relay latency, tight
# enough that an attacker cannot stockpile signed messages.
_REPLAY_WINDOW_S: float = 300.0     # ±5 minutes
_REPLAY_CACHE_PER_SOURCE: int = 256  # LRU size per source — bounds memory


class FederationGateway(GatewayProtocol):
    """Unified federation entry point — Five Tattva Gates at the boundary.

    All external federation protocols (A2A, NADI, future MCP) converge here.
    Internally, everything becomes NADI and flows through FederationBridge.

    Usage:
        gateway = FederationGateway(bridge=bridge, a2a=a2a, reaper=reaper)
        response = gateway.receive(request)  # GatewayProtocol interface
        response = gateway.handle_federation_message(raw_dict)  # Direct dict API
    """

    def __init__(
        self,
        bridge: object | None = None,
        a2a: object | None = None,
        reaper: object | None = None,
    ) -> None:
        self._bridge = bridge
        self._a2a = a2a
        self._reaper = reaper
        self._stats = GatewayStats()
        # Replay protection state — per-source LRU of payload_hash → timestamp
        self._seen: dict[str, OrderedDict[str, float]] = {}

    def _check_replay(self, msg: dict) -> tuple[bool, str, str]:
        """Sliding-window + LRU replay guard for PROTECTED NADI messages.

        Rejects when:
          - timestamp is missing or outside ±_REPLAY_WINDOW_S of now
          - (source, payload_hash) tuple has already been processed within
            the per-source LRU cache (cap _REPLAY_CACHE_PER_SOURCE)

        Returns (ok, reason, stage). Non-NADI / non-PROTECTED messages pass
        through unchanged — they are guarded by other layers.
        """
        if self._detect_protocol(msg) != "nadi":
            return True, "", ""
        operation = str(msg.get("operation", "")).strip()
        if operation not in PROTECTED_OPERATIONS:
            return True, "", ""

        source = str(msg.get("source", "")).strip()
        payload_hash = str(msg.get("payload_hash", "")).strip()
        if not source or not payload_hash:
            # Crypto stage will catch these too, but reject early so we don't
            # pollute the LRU with empty keys.
            return False, "missing_replay_fields", "replay_protection"

        ts_raw = msg.get("timestamp")
        try:
            ts = float(ts_raw)
        except (TypeError, ValueError):
            return False, "missing_timestamp", "replay_protection"
        now = time.time()
        if abs(now - ts) > _REPLAY_WINDOW_S:
            return False, "timestamp_outside_window", "replay_protection"

        cache = self._seen.setdefault(source, OrderedDict())
        if payload_hash in cache:
            return False, "replay_detected", "replay_protection"
        cache[payload_hash] = ts
        # Prune LRU
        while len(cache) > _REPLAY_CACHE_PER_SOURCE:
            cache.popitem(last=False)
        return True, "", ""

    # ── GatewayProtocol Interface ─────────────────────────────────

    def receive(self, request: GatewayRequest) -> GatewayResponse:
        """GatewayProtocol.receive() — process federation request through Five Tattva Gates."""
        import json

        command = request.get("command", "")
        entry_type = request.get("entry_type", EntryType.AGENT.value)

        # Parse command as JSON message
        try:
            msg = json.loads(command) if isinstance(command, str) else command
        except (json.JSONDecodeError, TypeError):
            self._stats.rejected_parse += 1
            return self._error_response("Invalid JSON payload", entry_type)

        if not isinstance(msg, dict):
            self._stats.rejected_parse += 1
            return self._error_response("Payload must be a JSON object", entry_type)

        result = self.handle_federation_message(msg)
        success = result.get("success", False)

        return GatewayResponse(
            success=success,
            exit_code=0 if success else 1,
            output=json.dumps(result.get("data", {}), default=str),
            error=result.get("error"),
            position=0,
            guardian="federation",
            quarter="dharma",
            guna="sattva" if success else "tamas",
            entry_type=entry_type,
            routed_via="federation_gateway",
        )

    def route(self, command: str) -> dict[str, object]:
        """GatewayProtocol.route() — detect protocol without executing."""
        import json

        try:
            msg = json.loads(command) if isinstance(command, str) else command
        except (json.JSONDecodeError, TypeError):
            return {"protocol": "unknown", "position": 0, "guardian": "federation", "quarter": "dharma"}

        if not isinstance(msg, dict):
            return {"protocol": "unknown", "position": 0, "guardian": "federation", "quarter": "dharma"}

        protocol = self._detect_protocol(msg)
        return {"protocol": protocol, "position": 0, "guardian": "federation", "quarter": "dharma"}

    # ── Direct Dict API ───────────────────────────────────────────

    def handle_federation_message(self, msg: dict) -> dict[str, object]:
        """Process a federation message through Five Tattva Gates.

        Returns:
            {"success": bool, "protocol": str, "data": dict} on success
            {"success": False, "error": str} on failure
        """
        # Type guard: must be a dict
        if not isinstance(msg, dict):
            self._stats.rejected_parse += 1
            return {"success": False, "error": "Payload must be a JSON object", "code": 400}

        # ── GATE 1: PARSE — strict protocol detection ────────────
        protocol = self._detect_protocol(msg)
        if protocol == "unknown":
            self._stats.rejected_parse += 1
            logger.debug("GATEWAY PARSE: rejected unknown protocol (keys=%s)", list(msg.keys())[:5])
            return {"success": False, "error": "Unknown protocol — no schema matched", "code": 400}

        # ── GATE 2: VALIDATE — sender trust check ────────────────
        sender = self._extract_sender(msg, protocol)
        if not self._validate_sender(sender):
            self._stats.rejected_validate += 1
            logger.warning("GATEWAY VALIDATE: rejected untrusted sender '%s'", sender)
            return {"success": False, "error": f"Sender '{sender}' not trusted", "code": 403}

        # ── GATE 3: EXECUTE — route through bridge ───────────────
        try:
            result = self._execute(msg, protocol)
        except Exception as e:
            self._stats.errors += 1
            logger.exception("GATEWAY EXECUTE: error processing %s message", protocol)
            return {"success": False, "error": f"Execution error: {e}", "code": 500}

        # ── GATE 4: RESULT — format in sender's protocol ─────────
        response_data = self._format_result(result, protocol)

        # ── GATE 5: SYNC — fire-and-forget Hebbian signal ────────
        success = result.get("success", False)
        self._stats.record(protocol, success)
        response = {"success": success, "protocol": protocol, "data": response_data}
        if not success:
            if "error" in result:
                response["error"] = result["error"]
            if "code" in result:
                response["code"] = result["code"]
        return response

    # ── Gate Implementations ──────────────────────────────────────

    def _detect_protocol(self, msg: dict) -> str:
        """PARSE gate: deterministic protocol detection via schema matching.

        Returns protocol tag ('a2a', 'nadi') or 'unknown'.
        Strict: ambiguous messages are rejected, never guessed.
        """
        for tag, detector in _PROTOCOL_DETECTORS.items():
            if detector(msg):
                return tag
        return "unknown"

    def _extract_sender(self, msg: dict, protocol: str) -> str:
        """Extract sender identity from message based on protocol."""
        if protocol == "a2a":
            params = msg.get("params", {})
            metadata = params.get("metadata", {})
            return metadata.get("source_agent", "")
        elif protocol == "nadi":
            return msg.get("source", "")
        return ""

    def _validate_sender(self, sender: str) -> bool:
        """VALIDATE gate: check sender trust via Reaper.

        Empty sender is allowed (anonymous/discovery messages).
        Known senders must have trust > 0 (not evicted).
        """
        if not sender:
            return True  # Anonymous — allowed for discovery/heartbeat

        if self._reaper is None:
            return True  # No reaper — can't validate, allow

        peer = self._reaper.get_peer(sender) if hasattr(self._reaper, "get_peer") else None
        if peer is None:
            return True  # Unknown peer — allowed (first contact)

        # Evicted peers are rejected
        status = getattr(peer, "status", None)
        if status is not None:
            status_val = status.value if hasattr(status, "value") else str(status)
            if status_val == "evicted":
                return False

        return True

    def _execute(self, msg: dict, protocol: str) -> dict[str, object]:
        """EXECUTE gate: route message through appropriate adapter → bridge."""
        if protocol == "a2a":
            return self._execute_a2a(msg)
        elif protocol == "nadi":
            return self._execute_nadi(msg)
        return {"success": False, "error": f"No executor for protocol '{protocol}'"}

    def _execute_a2a(self, msg: dict) -> dict[str, object]:
        """Route A2A JSON-RPC through A2AProtocolAdapter → FederationBridge."""
        if self._a2a is None:
            return {"success": False, "error": "A2A adapter not available"}

        response = self._a2a.handle_jsonrpc(msg)

        # A2A returns JSON-RPC response — check for error
        if "error" in response:
            return {"success": False, "response": response}
        return {"success": True, "response": response}

    def _execute_nadi(self, msg: dict) -> dict[str, object]:
        """Route raw NADI message through FederationBridge.ingest()."""
        if self._bridge is None:
            return {"success": False, "error": "Federation bridge not available", "code": 503}

        operation = msg.get("operation", "")
        payload = msg.get("payload", {})
        if isinstance(payload, dict) and operation == "federation.agent_claim":
            payload = dict(payload)
            payload["node_id"] = str(msg.get("source", "")).strip()

        if not operation:
            return {"success": False, "error": "NADI message missing 'operation' field", "code": 400}

        success = self._bridge.ingest(operation, payload)
        if not success:
            return {
                "success": False,
                "operation": operation,
                "error": f"Bridge rejected operation '{operation}'",
                "code": 422,
            }
        return {"success": True, "operation": operation}

    def _format_result(self, result: dict, protocol: str) -> dict:
        """RESULT gate: format response in sender's protocol."""
        if protocol == "a2a":
            # A2A response is already JSON-RPC formatted by the adapter
            return result.get("response", result)
        elif protocol == "nadi":
            return {
                "operation": result.get("operation", ""),
                "success": result.get("success", False),
                "source": getattr(self._bridge, "agent_id", "steward") if self._bridge is not None else "steward",
                "timestamp": time.time(),
            }
        return result

    # ── Transport Integration ────────────────────────────────────

    def _quarantine_transport_messages(
        self,
        transport: object,
        messages: list[object],
        *,
        reason: str,
        stage: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if not messages or not hasattr(transport, "quarantine_messages"):
            return
        try:
            transport.quarantine_messages(messages, reason=reason, stage=stage, metadata=metadata)
        except Exception:
            logger.exception("GATEWAY QUARANTINE: failed to quarantine rejected messages")

    def _authorize_inbound_message(self, msg: dict) -> tuple[bool, str, str]:
        protocol = self._detect_protocol(msg)
        if protocol != "nadi":
            return True, "", ""
        operation = str(msg.get("operation", "")).strip()
        if operation == "federation.agent_claim":
            payload = msg.get("payload", {})
            public_key = str(payload.get("public_key", "")).strip() if isinstance(payload, dict) else ""
            node_id = str(payload.get("node_id", "")).strip() if isinstance(payload, dict) else ""
            if not public_key or not node_id:
                return False, "identity_spoofing_attempt", "gateway_authorization"
            # Verify node_id matches derived ID from public_key (prevent tampering)
            if derive_node_id(public_key) != node_id:
                return False, "identity_spoofing_attempt", "gateway_authorization"
        if operation in PUBLIC_OPERATIONS:
            return True, "", ""
        if self._bridge is not None and hasattr(self._bridge, "is_verified_agent"):
            sender = str(msg.get("source", "")).strip()
            if sender and self._bridge.is_verified_agent(sender):
                return True, "", ""
        return False, "unauthorized_unverified_sender", "gateway_authorization"

    def _verify_inbound_signature(self, msg: dict) -> tuple[bool, str, str]:
        """Cryptographic gate for PROTECTED operations — fail-CLOSED.

        Returns (ok, reason, stage). All paths that previously returned True
        on missing infrastructure or unknown sender now reject with a
        descriptive reason. The only legitimate True returns are:
          - non-NADI protocols (handled by their own validators)
          - PUBLIC_OPERATIONS (validated in _authorize_inbound_message)
          - successful Ed25519 verification against verified_agents.json
        """
        protocol = self._detect_protocol(msg)
        if protocol != "nadi":
            return True, "", ""
        operation = str(msg.get("operation", "")).strip()
        if operation not in PROTECTED_OPERATIONS:
            return True, "", ""

        # Fail-closed: no verifier infrastructure → reject. We never accept
        # a PROTECTED message in a state where we cannot verify it.
        if self._bridge is None or not hasattr(self._bridge, "get_verified_agent"):
            return False, "verifier_unavailable", "crypto_verification"

        sender = str(msg.get("source", "")).strip()
        if not sender:
            return False, "missing_source", "crypto_verification"
        record = self._bridge.get_verified_agent(sender)

        # Fail-closed: unknown sender → reject. PROTECTED operations require a
        # registered identity. The bootstrap path is federation.agent_claim
        # (a PUBLIC operation) — that's how unknown nodes become known.
        if not isinstance(record, dict):
            return False, "unknown_sender", "crypto_verification"

        public_key = str(record.get("public_key", "")).strip()
        payload_hash = str(msg.get("payload_hash", "")).strip()
        signature = str(msg.get("signature", "")).strip()
        if not public_key or not payload_hash or not signature:
            return False, "invalid_signature", "crypto_verification"

        # Anti-spoofing invariant: verified_agents.json entries must satisfy
        # derive_node_id(public_key) == node_id (enforced on registration).
        # We re-check here so a corrupted registry can never bypass the check.
        if derive_node_id(public_key) != sender:
            return False, "registry_inconsistent", "crypto_verification"

        if not verify_payload_signature(public_key, payload_hash, signature):
            return False, "invalid_signature", "crypto_verification"
        return True, "", ""

    def process_inbound(self, transport: object) -> int:
        """Process all pending inbound messages from a FederationTransport.

        Drop-in replacement for FederationBridge.process_inbound() — same
        signature, same return type — but routes every message through the
        Five Tattva Gates before it reaches the bridge.

        Returns count of messages successfully processed (passed all gates).
        """
        try:
            messages = transport.read_outbox()
        except Exception as e:
            logger.warning("GATEWAY: read_outbox failed: %s", e)
            self._stats.errors += 1
            return 0

        processed = 0
        for msg in messages:
            if not isinstance(msg, dict):
                self._stats.rejected_parse += 1
                self._stats.errors += 1
                logger.warning("GATEWAY INBOUND: dropped non-dict message (%r)", type(msg).__name__)
                self._quarantine_transport_messages(
                    transport,
                    [msg],
                    reason="Gateway inbound payload must be a JSON object",
                    stage="gateway_parse",
                )
                continue
            verified, verify_reason, verify_stage = self._verify_inbound_signature(msg)
            if not verified:
                self._stats.errors += 1
                logger.warning(
                    "GATEWAY CRYPTO: blocked message source=%s operation=%s reason=%s",
                    msg.get("source", ""),
                    msg.get("operation", ""),
                    verify_reason,
                )
                self._quarantine_transport_messages(
                    transport,
                    [msg],
                    reason=verify_reason,
                    stage=verify_stage,
                    metadata={
                        "protocol": self._detect_protocol(msg),
                        "code": 401,
                        "source": msg.get("source", ""),
                        "operation": msg.get("operation", ""),
                    },
                )
                continue
            replay_ok, replay_reason, replay_stage = self._check_replay(msg)
            if not replay_ok:
                self._stats.errors += 1
                logger.warning(
                    "GATEWAY REPLAY: blocked message source=%s operation=%s reason=%s",
                    msg.get("source", ""),
                    msg.get("operation", ""),
                    replay_reason,
                )
                self._quarantine_transport_messages(
                    transport,
                    [msg],
                    reason=replay_reason,
                    stage=replay_stage,
                    metadata={
                        "protocol": self._detect_protocol(msg),
                        "code": 409,
                        "source": msg.get("source", ""),
                        "operation": msg.get("operation", ""),
                    },
                )
                continue
            authorized, auth_reason, auth_stage = self._authorize_inbound_message(msg)
            if not authorized:
                self._stats.errors += 1
                logger.warning(
                    "GATEWAY AUTHZ: blocked message source=%s operation=%s reason=%s",
                    msg.get("source", ""),
                    msg.get("operation", ""),
                    auth_reason,
                )
                self._quarantine_transport_messages(
                    transport,
                    [msg],
                    reason=auth_reason,
                    stage=auth_stage,
                    metadata={
                        "protocol": self._detect_protocol(msg),
                        "code": 401,
                        "source": msg.get("source", ""),
                        "operation": msg.get("operation", ""),
                    },
                )
                continue

            # Record heartbeat for peer — ANY message that passes auth proves peer is alive
            source_agent = msg.get("source")
            if source_agent:
                from steward.services import SVC_REAPER
                from vibe_core.di import ServiceRegistry

                reaper = ServiceRegistry.get(SVC_REAPER)
                if reaper is not None:
                    reaper.record_heartbeat(
                        agent_id=source_agent,
                        source="federation_gateway",
                    )

            result = self.handle_federation_message(msg)
            if result.get("success"):
                processed += 1
                continue

            self._stats.errors += 1
            error = result.get("error") or result.get("data", {}).get("error", "gateway rejected message")
            logger.warning(
                "GATEWAY INBOUND: dropped message protocol=%s source=%s operation=%s error=%s",
                result.get("protocol", "unknown"),
                msg.get("source", ""),
                msg.get("operation", ""),
                error,
            )
            self._quarantine_transport_messages(
                transport,
                [msg],
                reason=str(error),
                stage="gateway_reject",
                metadata={
                    "protocol": result.get("protocol", "unknown"),
                    "code": result.get("code", 0),
                    "source": msg.get("source", ""),
                    "operation": msg.get("operation", ""),
                },
            )
        return processed

    # ── Observability ─────────────────────────────────────────────

    def stats(self) -> dict[str, object]:
        """Gateway metrics for Buddy Bubble and DHARMA introspection."""
        return self._stats.to_dict()

    def _error_response(self, error: str, entry_type: str) -> GatewayResponse:
        return GatewayResponse(
            success=False,
            exit_code=1,
            output="",
            error=error,
            position=0,
            guardian="federation",
            quarter="dharma",
            guna="tamas",
            entry_type=entry_type,
            routed_via="federation_gateway[error]",
        )
