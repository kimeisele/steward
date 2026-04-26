"""Tests for FederationGateway — Five Tattva gates for federation protocols."""

from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock

from steward.federation_crypto import NodeKeyStore, derive_node_id, sign_payload_hash
from steward.federation import FederationBridge
from steward.federation_transport import NadiFederationTransport
from steward.federation_gateway import FederationGateway, _is_a2a, _is_nadi
from steward.services import SVC_TASK_MANAGER


def _sign_outbound(msg: dict, keys: NodeKeyStore) -> dict:
    """Helper: produce a NADI message with canonical payload_hash + signature.

    Same hash convention as agent-city's FederationRelay._sign_payload —
    sha256 over sorted-keys JSON of the message minus signing fields.
    Adds a fresh timestamp so the gateway replay guard accepts it.
    """
    import time as _time

    msg = {**msg, "timestamp": msg.get("timestamp", _time.time())}
    canonical = {k: v for k, v in msg.items() if k not in ("payload_hash", "signature")}
    payload_hash = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    return {
        **canonical,
        "payload_hash": payload_hash,
        "signature": sign_payload_hash(keys.private_key, payload_hash),
    }


def _verified_mock_bridge(keys: NodeKeyStore, agent_name: str = "verified-peer") -> MagicMock:
    """Mock bridge that exposes get_verified_agent for the given identity."""
    bridge = MagicMock()
    bridge.ingest.return_value = True
    bridge.is_verified_agent.return_value = True
    bridge.get_verified_agent.return_value = {
        "node_id": keys.node_id,
        "agent_name": agent_name,
        "public_key": keys.public_key,
        "capabilities": [],
    }
    return bridge

# ── Protocol Detection ─────────────────────────────────────────────


class TestProtocolDetection:
    def test_a2a_detected(self):
        assert _is_a2a({"jsonrpc": "2.0", "method": "tasks/send", "params": {}})

    def test_a2a_rejected_no_method(self):
        assert not _is_a2a({"jsonrpc": "2.0"})

    def test_a2a_rejected_wrong_version(self):
        assert not _is_a2a({"jsonrpc": "1.0", "method": "tasks/send"})

    def test_nadi_detected(self):
        assert _is_nadi({"operation": "heartbeat", "source": "agent-city"})

    def test_nadi_rejected_no_source(self):
        assert not _is_nadi({"operation": "heartbeat"})

    def test_nadi_rejected_no_operation(self):
        assert not _is_nadi({"source": "agent-city"})

    def test_ambiguous_rejected(self):
        """Message matching no schema → unknown."""
        gw = FederationGateway()
        result = gw.handle_federation_message({"foo": "bar"})
        assert result["success"] is False
        assert result["code"] == 400
        assert "Unknown protocol" in result["error"]


# ── PARSE Gate ────────────────────────────────────────────────────


class TestParseGate:
    def test_rejects_non_dict(self):
        gw = FederationGateway()
        response = gw.handle_federation_message("not a dict")
        assert response["success"] is False
        assert response["code"] == 400

    def test_stats_count_rejected_parse(self):
        gw = FederationGateway()
        gw.handle_federation_message({"nothing": "matching"})
        gw.handle_federation_message({"also": "bad"})
        assert gw.stats()["rejected_parse"] == 2


# ── VALIDATE Gate ────────────────────────────────────────────────


class TestValidateGate:
    def test_anonymous_sender_allowed(self):
        """Empty sender passes validation (discovery/heartbeat)."""
        gw = FederationGateway(bridge=MagicMock())
        gw._bridge.ingest.return_value = True
        result = gw.handle_federation_message({"operation": "heartbeat", "source": "", "payload": {}})
        assert result["success"] is True

    def test_unknown_peer_allowed(self):
        """Peer not in reaper → allowed (first contact)."""
        reaper = MagicMock()
        reaper.get_peer.return_value = None
        gw = FederationGateway(bridge=MagicMock(), reaper=reaper)
        gw._bridge.ingest.return_value = True
        result = gw.handle_federation_message({"operation": "heartbeat", "source": "new-peer", "payload": {}})
        assert result["success"] is True

    def test_evicted_peer_rejected(self):
        """Evicted peers are rejected at VALIDATE gate."""
        peer = MagicMock()
        peer.status.value = "evicted"
        reaper = MagicMock()
        reaper.get_peer.return_value = peer
        gw = FederationGateway(bridge=MagicMock(), reaper=reaper)
        result = gw.handle_federation_message({"operation": "heartbeat", "source": "bad-peer", "payload": {}})
        assert result["success"] is False
        assert result["code"] == 403
        assert gw.stats()["rejected_validate"] == 1

    def test_alive_peer_allowed(self):
        """Alive peers pass validation."""
        peer = MagicMock()
        peer.status.value = "alive"
        reaper = MagicMock()
        reaper.get_peer.return_value = peer
        gw = FederationGateway(bridge=MagicMock(), reaper=reaper)
        gw._bridge.ingest.return_value = True
        result = gw.handle_federation_message({"operation": "heartbeat", "source": "good-peer", "payload": {}})
        assert result["success"] is True


# ── EXECUTE Gate — A2A Protocol ──────────────────────────────────


class TestExecuteA2A:
    def test_a2a_routes_through_adapter(self):
        """A2A messages go through A2AProtocolAdapter.handle_jsonrpc()."""
        a2a = MagicMock()
        a2a.handle_jsonrpc.return_value = {"jsonrpc": "2.0", "id": "1", "result": {"id": "task-1"}}
        gw = FederationGateway(a2a=a2a)
        result = gw.handle_federation_message(
            {"jsonrpc": "2.0", "method": "tasks/send", "params": {"metadata": {"source_agent": ""}}, "id": "1"}
        )
        assert result["success"] is True
        assert result["protocol"] == "a2a"
        a2a.handle_jsonrpc.assert_called_once()

    def test_a2a_error_propagated(self):
        """A2A adapter errors are surfaced in result."""
        a2a = MagicMock()
        a2a.handle_jsonrpc.return_value = {"jsonrpc": "2.0", "id": "1", "error": {"code": -32601, "message": "nope"}}
        gw = FederationGateway(a2a=a2a)
        result = gw.handle_federation_message(
            {"jsonrpc": "2.0", "method": "bad/method", "params": {"metadata": {}}, "id": "1"}
        )
        assert result["success"] is False

    def test_a2a_no_adapter(self):
        """A2A message without adapter configured."""
        gw = FederationGateway()
        result = gw.handle_federation_message(
            {"jsonrpc": "2.0", "method": "tasks/send", "params": {"metadata": {}}, "id": "1"}
        )
        assert result["success"] is False
        assert "not available" in result["data"].get("error", "")


# ── EXECUTE Gate — NADI Protocol ─────────────────────────────────


class TestExecuteNADI:
    def test_nadi_routes_through_bridge(self):
        """NADI messages go through FederationBridge.ingest()."""
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gw = FederationGateway(bridge=bridge)
        result = gw.handle_federation_message(
            {"operation": "heartbeat", "source": "peer-1", "payload": {"agent_id": "peer-1"}}
        )
        assert result["success"] is True
        assert result["protocol"] == "nadi"
        bridge.ingest.assert_called_once_with("heartbeat", {"agent_id": "peer-1"})

    def test_nadi_bridge_rejects(self):
        """Bridge returns False → gateway reports failure."""
        bridge = MagicMock()
        bridge.ingest.return_value = False
        gw = FederationGateway(bridge=bridge)
        result = gw.handle_federation_message({"operation": "unknown_op", "source": "peer-1", "payload": {}})
        assert result["success"] is False
        assert result["code"] == 422
        assert "Bridge rejected operation" in result["error"]

    def test_nadi_no_bridge(self):
        """NADI message without bridge configured."""
        gw = FederationGateway()
        result = gw.handle_federation_message({"operation": "heartbeat", "source": "peer-1", "payload": {}})
        assert result["success"] is False
        assert result["code"] == 503

    def test_nadi_missing_operation(self):
        """NADI message with empty operation string."""
        bridge = MagicMock()
        gw = FederationGateway(bridge=bridge)
        result = gw.handle_federation_message({"operation": "", "source": "peer-1", "payload": {}})
        # Empty operation: _is_nadi returns True (string), but _execute_nadi rejects
        assert result["success"] is False
        assert result["code"] == 400


# ── SYNC Gate — Hebbian Learning ─────────────────────────────────


class TestSyncGate:
    def test_signals_queued_not_blocking(self):
        """Hebbian signals are queued, not processed inline."""
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gw = FederationGateway(bridge=bridge)
        gw.handle_federation_message({"operation": "heartbeat", "source": "p1", "payload": {}})
        gw.handle_federation_message({"operation": "heartbeat", "source": "p2", "payload": {}})

        stats = gw.stats()
        assert stats["total_requests"] == 2
        assert stats["pending_signals"] == 2

    def test_drain_signals(self):
        """MOKSHA hook drains pending signals."""
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gw = FederationGateway(bridge=bridge)
        gw.handle_federation_message({"operation": "heartbeat", "source": "p1", "payload": {}})

        signals = gw._stats.drain_signals()
        assert len(signals) == 1
        assert signals[0] == ("nadi", True)
        # After drain, no pending signals
        assert gw.stats()["pending_signals"] == 0


# ── GatewayProtocol Interface ────────────────────────────────────


class TestGatewayProtocolInterface:
    def test_receive_nadi(self):
        """receive() accepts GatewayRequest with JSON command."""
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gw = FederationGateway(bridge=bridge)
        request = {
            "entry_type": "agent",
            "command": json.dumps({"operation": "heartbeat", "source": "p1", "payload": {}}),
            "args": [],
            "context": {},
        }
        response = gw.receive(request)
        assert response["success"] is True
        assert response["routed_via"] == "federation_gateway"
        assert response["guardian"] == "federation"

    def test_receive_invalid_json(self):
        """receive() rejects non-JSON command."""
        gw = FederationGateway()
        request = {"entry_type": "agent", "command": "not json {{{", "args": [], "context": {}}
        response = gw.receive(request)
        assert response["success"] is False
        assert "Invalid JSON" in response["error"]

    def test_route_detects_protocol(self):
        """route() returns protocol without executing."""
        gw = FederationGateway()
        result = gw.route(json.dumps({"jsonrpc": "2.0", "method": "tasks/send"}))
        assert result["protocol"] == "a2a"

        result = gw.route(json.dumps({"operation": "heartbeat", "source": "p1"}))
        assert result["protocol"] == "nadi"

        result = gw.route(json.dumps({"foo": "bar"}))
        assert result["protocol"] == "unknown"


# ── Stats ────────────────────────────────────────────────────────


# ── process_inbound (Transport Integration) ──────────────────────


class TestProcessInbound:
    """Integration: transport → gateway → bridge, with all five gates active."""

    def _make_transport(self, messages: list[dict]) -> MagicMock:
        transport = MagicMock()
        transport.read_outbox.return_value = messages
        return transport

    def test_processes_valid_nadi_messages(self, tmp_path):
        """Valid signed NADI messages from verified peers reach the bridge."""
        keys_a = NodeKeyStore(tmp_path / "a" / ".node_keys.json")
        keys_a.ensure_keys()
        keys_b = NodeKeyStore(tmp_path / "b" / ".node_keys.json")
        keys_b.ensure_keys()
        bridge = MagicMock()
        bridge.ingest.return_value = True
        bridge.is_verified_agent.return_value = True
        bridge.get_verified_agent.side_effect = lambda nid: (
            {"node_id": keys_a.node_id, "public_key": keys_a.public_key} if nid == keys_a.node_id
            else {"node_id": keys_b.node_id, "public_key": keys_b.public_key} if nid == keys_b.node_id
            else None
        )
        gw = FederationGateway(bridge=bridge)
        transport = self._make_transport(
            [
                _sign_outbound({"operation": "heartbeat", "source": keys_a.node_id, "payload": {"agent_id": "a"}}, keys_a),
                _sign_outbound({"operation": "claim_slot", "source": keys_b.node_id, "payload": {"slot_id": "s1", "agent_id": "b"}}, keys_b),
            ]
        )

        processed = gw.process_inbound(transport)

        assert processed == 2
        assert bridge.ingest.call_count == 2
        assert gw.stats()["total_requests"] == 2
        assert gw.stats()["by_protocol"]["nadi"] == 2

    def test_evicted_peer_blocked_at_validate(self, tmp_path):
        """Evicted peer messages are rejected at VALIDATE — even when sig is valid."""
        evicted_keys = NodeKeyStore(tmp_path / "evicted" / ".node_keys.json")
        evicted_keys.ensure_keys()
        peer = MagicMock()
        peer.status.value = "evicted"
        reaper = MagicMock()
        reaper.get_peer.return_value = peer
        bridge = _verified_mock_bridge(evicted_keys, agent_name="evicted-peer")
        gw = FederationGateway(bridge=bridge, reaper=reaper)
        transport = self._make_transport(
            [_sign_outbound(
                {"operation": "heartbeat", "source": evicted_keys.node_id, "payload": {"agent_id": "evicted-peer"}},
                evicted_keys,
            )]
        )

        processed = gw.process_inbound(transport)

        assert processed == 0
        bridge.ingest.assert_not_called()  # CRITICAL: evicted peer NEVER reaches bridge
        assert gw.stats()["rejected_validate"] == 1

    def test_unknown_protocol_rejected(self):
        """Messages with unrecognized schema are rejected at PARSE."""
        bridge = MagicMock()
        gw = FederationGateway(bridge=bridge)
        transport = self._make_transport([{"garbage": "data"}, {"also": "garbage"}])

        processed = gw.process_inbound(transport)

        assert processed == 0
        bridge.ingest.assert_not_called()
        assert gw.stats()["rejected_parse"] == 2
        assert gw.stats()["errors"] == 2

    def test_non_dict_messages_skipped(self, tmp_path):
        """Non-dict items in transport are silently skipped."""
        keys = NodeKeyStore(tmp_path / "v" / ".node_keys.json")
        keys.ensure_keys()
        bridge = _verified_mock_bridge(keys)
        gw = FederationGateway(bridge=bridge)
        transport = self._make_transport(
            [
                "not a dict",
                42,
                None,
                _sign_outbound({"operation": "heartbeat", "source": keys.node_id, "payload": {}}, keys),
            ]
        )

        processed = gw.process_inbound(transport)

        assert processed == 1
        assert gw.stats()["rejected_parse"] == 3  # 3 non-dicts
        assert gw.stats()["errors"] == 3

    def test_mixed_valid_and_invalid(self, tmp_path):
        """Mix of valid, invalid, and evicted — only valid messages pass."""
        good_keys = NodeKeyStore(tmp_path / "good" / ".node_keys.json")
        good_keys.ensure_keys()
        bad_keys = NodeKeyStore(tmp_path / "bad" / ".node_keys.json")
        bad_keys.ensure_keys()
        peer = MagicMock()
        peer.status.value = "evicted"
        reaper = MagicMock()
        reaper.get_peer.side_effect = lambda aid: peer if aid == bad_keys.node_id else None
        bridge = MagicMock()
        bridge.ingest.return_value = True
        bridge.is_verified_agent.return_value = True
        bridge.get_verified_agent.side_effect = lambda nid: (
            {"node_id": good_keys.node_id, "public_key": good_keys.public_key} if nid == good_keys.node_id
            else {"node_id": bad_keys.node_id, "public_key": bad_keys.public_key} if nid == bad_keys.node_id
            else None
        )
        gw = FederationGateway(bridge=bridge, reaper=reaper)
        transport = self._make_transport(
            [
                _sign_outbound({"operation": "heartbeat", "source": good_keys.node_id, "payload": {}}, good_keys),
                _sign_outbound({"operation": "heartbeat", "source": bad_keys.node_id, "payload": {}}, bad_keys),  # REJECT: evicted
                {"garbage": True},  # REJECT: unknown protocol
                _sign_outbound({"operation": "claim_slot", "source": good_keys.node_id, "payload": {"slot_id": "s1"}}, good_keys),
            ]
        )

        processed = gw.process_inbound(transport)

        assert processed == 2
        assert bridge.ingest.call_count == 2
        assert gw.stats()["rejected_validate"] == 1
        assert gw.stats()["rejected_parse"] == 1
        assert gw.stats()["errors"] == 2

    def test_bridge_reject_is_counted_and_surfaced(self, tmp_path):
        keys = NodeKeyStore(tmp_path / "g" / ".node_keys.json")
        keys.ensure_keys()
        bridge = _verified_mock_bridge(keys)
        bridge.ingest.side_effect = [True, False]
        gw = FederationGateway(bridge=bridge)
        transport = self._make_transport(
            [
                _sign_outbound({"operation": "heartbeat", "source": keys.node_id, "payload": {}}, keys),
                _sign_outbound({"operation": "unknown_op", "source": keys.node_id, "payload": {}}, keys),
            ]
        )

        processed = gw.process_inbound(transport)

        assert processed == 1
        assert gw.stats()["errors"] == 1

    def test_unknown_protocol_message_is_quarantined(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        (tmp_path / "nadi_inbox.json").write_text(
            json.dumps(
                [
                    {"source": "peer-1", "operation": 7, "payload": {}},
                ]
            )
        )
        gw = FederationGateway(bridge=MagicMock())

        processed = gw.process_inbound(transport)

        assert processed == 0
        quarantine_files = [path for path in (tmp_path / "quarantine").glob("*.json") if path.name != "index.json"]
        assert len(quarantine_files) == 1
        record = json.loads(quarantine_files[0].read_text())
        assert record["stage"] == "gateway_reject"
        assert record["metadata"]["code"] == 400

    def test_bridge_reject_message_is_quarantined(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        (tmp_path / "nadi_inbox.json").write_text(
            json.dumps(
                [
                    {"source": "peer-1", "operation": "unknown_op", "payload": {}},
                ]
            )
        )
        bridge = MagicMock()
        bridge.ingest.return_value = False
        bridge.is_verified_agent.return_value = True
        gw = FederationGateway(bridge=bridge)

        processed = gw.process_inbound(transport)

        assert processed == 0
        quarantine_files = [path for path in (tmp_path / "quarantine").glob("*.json") if path.name != "index.json"]
        assert len(quarantine_files) == 1
        record = json.loads(quarantine_files[0].read_text())
        assert record["stage"] == "gateway_reject"
        assert record["metadata"]["code"] == 422
        assert "Bridge rejected operation 'unknown_op'" == record["reason"]

    def test_transport_read_failure(self):
        """Transport read error is caught and counted."""
        gw = FederationGateway(bridge=MagicMock())
        transport = MagicMock()
        transport.read_outbox.side_effect = OSError("disk full")

        processed = gw.process_inbound(transport)

        assert processed == 0
        assert gw.stats()["errors"] == 1

    def test_unverified_sender_protected_operation_is_quarantined(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        payload = {"target": "fix:federation_ci_required:agent-internet", "severity": "high", "reward": 108, "description": "Fix CI"}
        (tmp_path / "nadi_inbox.json").write_text(
            json.dumps(
                [
                    {
                        "source": "node-x",
                        "target": "steward",
                        "operation": "governance_bounty",
                        "payload": payload,
                        "message_id": "gov-1",
                        "payload_hash": __import__("hashlib").sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                    }
                ]
            )
        )
        bridge = FederationBridge(agent_id="steward", verified_agents_path=tmp_path / "verified_agents.json")
        gw = FederationGateway(bridge=bridge)

        processed = gw.process_inbound(transport)

        assert processed == 0
        quarantine_files = [path for path in (tmp_path / "quarantine").glob("*.json") if path.name != "index.json"]
        assert len(quarantine_files) == 1
        record = json.loads(quarantine_files[0].read_text())
        # Fail-closed: unknown sender on a PROTECTED op is now blocked at the
        # crypto gate (before authz) — verifier has no public_key to check
        # the signature against, so we must reject.
        assert record["stage"] == "crypto_verification"
        assert record["reason"] == "unknown_sender"

    def test_unverified_sender_public_operation_is_allowed(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        node_x_keys = NodeKeyStore(tmp_path / "node-x" / ".node_keys.json")
        node_x_keys.ensure_keys()
        # Claim payloads MUST carry node_id — the gateway's authz check needs
        # both public_key and node_id to enforce derive_node_id(public_key)
        # == node_id. agent-city's _send_federation_claim already includes it.
        payload = {
            "agent_name": "node-x",
            "node_id": node_x_keys.node_id,
            "public_key": node_x_keys.public_key,
            "capabilities": ["infra"],
        }
        (tmp_path / "nadi_inbox.json").write_text(
            json.dumps(
                [
                    {
                        "source": node_x_keys.node_id,
                        "target": "steward",
                        "operation": "federation.agent_claim",
                        "payload": payload,
                        "message_id": "claim-1",
                        "payload_hash": __import__("hashlib").sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                    }
                ]
            )
        )
        bridge = FederationBridge(agent_id="steward", verified_agents_path=tmp_path / "verified_agents.json")
        gw = FederationGateway(bridge=bridge)

        processed = gw.process_inbound(transport)

        assert processed == 1
        registry = json.loads((tmp_path / "verified_agents.json").read_text())
        assert registry[node_x_keys.node_id]["public_key"] == node_x_keys.public_key

    def test_immigration_flow_blocks_then_claims_then_allows(self, tmp_path):
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        transport = NadiFederationTransport(str(tmp_path))
        node_x_keys = NodeKeyStore(tmp_path / "node-x" / ".node_keys.json")
        node_x_keys.ensure_keys()
        bridge = FederationBridge(agent_id="steward", verified_agents_path=tmp_path / "verified_agents.json")
        gw = FederationGateway(bridge=bridge)
        gov_payload = {"target": "fix:federation_ci_required:agent-internet", "severity": "high", "reward": 108, "description": "Fix CI"}
        claim_payload = {
            "agent_name": "node-x",
            "node_id": node_x_keys.node_id,
            "public_key": node_x_keys.public_key,
            "capabilities": ["bounty_hunter"],
        }

        (tmp_path / "nadi_inbox.json").write_text(
            json.dumps(
                [
                    {
                        "source": node_x_keys.node_id,
                        "target": "steward",
                        "operation": "governance_bounty",
                        "payload": gov_payload,
                        "message_id": "gov-a",
                        "payload_hash": __import__("hashlib").sha256(json.dumps(gov_payload, sort_keys=True).encode()).hexdigest(),
                    }
                ]
            )
        )
        assert gw.process_inbound(transport) == 0

        (tmp_path / "nadi_inbox.json").write_text(
            json.dumps(
                [
                    {
                        "source": node_x_keys.node_id,
                        "target": "steward",
                        "operation": "federation.agent_claim",
                        "payload": claim_payload,
                        "message_id": "claim-b",
                        "payload_hash": __import__("hashlib").sha256(json.dumps(claim_payload, sort_keys=True).encode()).hexdigest(),
                    }
                ]
            )
        )
        assert gw.process_inbound(transport) == 1

        (tmp_path / "nadi_inbox.json").write_text(
            json.dumps(
                [
                    {
                        "source": node_x_keys.node_id,
                        "target": "steward",
                        "operation": "governance_bounty",
                        "payload": gov_payload,
                        "message_id": "gov-c",
                        "timestamp": __import__("time").time(),
                        "payload_hash": __import__("hashlib").sha256(json.dumps(gov_payload, sort_keys=True).encode()).hexdigest(),
                        "signature": sign_payload_hash(node_x_keys.private_key, __import__("hashlib").sha256(json.dumps(gov_payload, sort_keys=True).encode()).hexdigest()),
                    }
                ]
            )
        )
        assert gw.process_inbound(transport) == 1
        assert len(task_mgr.list_tasks()) == 1

    def test_verified_sender_invalid_signature_is_quarantined(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        node_x_keys = NodeKeyStore(tmp_path / "node-x" / ".node_keys.json")
        node_x_keys.ensure_keys()
        # Registry MUST be keyed by derive_node_id(public_key); the gateway's
        # registry-consistency check would otherwise reject before the sig
        # verification runs. (This is the new anti-spoofing invariant.)
        (tmp_path / "verified_agents.json").write_text(
            json.dumps(
                {
                    node_x_keys.node_id: {
                        "node_id": node_x_keys.node_id,
                        "agent_name": "node-x",
                        "public_key": node_x_keys.public_key,
                        "capabilities": ["bounty_hunter"],
                    }
                }
            )
        )
        gov_payload = {"target": "fix:federation_ci_required:agent-internet", "severity": "high", "reward": 108, "description": "Fix CI"}
        (tmp_path / "nadi_inbox.json").write_text(
            json.dumps(
                [
                    {
                        "source": node_x_keys.node_id,
                        "target": "steward",
                        "operation": "governance_bounty",
                        "payload": gov_payload,
                        "message_id": "gov-bad",
                        "payload_hash": __import__("hashlib").sha256(json.dumps(gov_payload, sort_keys=True).encode()).hexdigest(),
                        "signature": "deadbeef",
                    }
                ]
            )
        )
        bridge = FederationBridge(agent_id="steward", verified_agents_path=tmp_path / "verified_agents.json")
        gw = FederationGateway(bridge=bridge)

        assert gw.process_inbound(transport) == 0
        quarantine_files = [path for path in (tmp_path / "quarantine").glob("*.json") if path.name != "index.json"]
        assert len(quarantine_files) == 1
        record = json.loads(quarantine_files[0].read_text())
        assert record["stage"] == "crypto_verification"
        assert record["reason"] == "invalid_signature"

    def test_node_health_broadcast_round_trip_updates_peer_registry(self, tmp_path):
        node_a = tmp_path / "node-a"
        node_b = tmp_path / "node-b"
        node_a.mkdir()
        node_b.mkdir()

        transport_a = NadiFederationTransport(str(node_a))
        transport_b = NadiFederationTransport(str(node_b))
        bridge_b = FederationBridge(agent_id="node-b", peer_registry_path=node_b / "peer_registry.json")
        gw_b = FederationGateway(bridge=bridge_b)

        message = {
            "source": "node-a",
            "target": "*",
            "operation": "federation.node_health",
            "payload": {
                "node_id": "node-a",
                "protocol_version": "1.0",
                "timestamp": 123.0,
                "status": "DEGRADED",
                "quarantine_metrics": {"total": 1, "by_reason": {}, "by_stage": {}},
            },
        }
        assert transport_a.append_to_inbox([message]) == 1
        outbox_messages = json.loads((node_a / "nadi_outbox.json").read_text())
        (node_b / "nadi_inbox.json").write_text(json.dumps(outbox_messages))

        processed = gw_b.process_inbound(transport_b)

        assert processed == 1
        registry = json.loads((node_b / "peer_registry.json").read_text())
        assert registry["node-a"]["status"] == "DEGRADED"
        assert registry["node-a"]["protocol_version"] == "1.0"

    def test_agent_claim_round_trip_updates_verified_agents_registry(self, tmp_path):
        node_b = tmp_path / "node-b"
        node_b.mkdir()

        transport_b = NadiFederationTransport(str(node_b))
        bridge_b = FederationBridge(agent_id="node-b", verified_agents_path=node_b / "verified_agents.json")
        gw_b = FederationGateway(bridge=bridge_b)
        node_a_keys = NodeKeyStore(tmp_path / "node-a" / ".node_keys.json")
        node_a_keys.ensure_keys()

        payload = {
            "agent_name": "node-a",
            "node_id": node_a_keys.node_id,
            "public_key": node_a_keys.public_key,
            "capabilities": ["bounty_hunter", "infrastructure"],
        }
        message = {
            "source": node_a_keys.node_id,
            "target": "node-b",
            "operation": "federation.agent_claim",
            "payload": payload,
            "message_id": "claim-1",
            "payload_hash": __import__("hashlib").sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        }
        (node_b / "nadi_inbox.json").write_text(json.dumps([message]))

        processed = gw_b.process_inbound(transport_b)

        assert processed == 1
        registry = json.loads((node_b / "verified_agents.json").read_text())
        assert registry[node_a_keys.node_id]["public_key"] == node_a_keys.public_key
        # Capabilities are normalised (set + sort) by the handler now
        assert sorted(registry[node_a_keys.node_id]["capabilities"]) == ["bounty_hunter", "infrastructure"]

    def test_spoofed_agent_claim_is_quarantined_for_identity_spoofing(self, tmp_path):
        node_b = tmp_path / "node-b"
        node_b.mkdir()

        transport_b = NadiFederationTransport(str(node_b))
        bridge_b = FederationBridge(agent_id="node-b", verified_agents_path=node_b / "verified_agents.json")
        gw_b = FederationGateway(bridge=bridge_b)
        attacker_keys = NodeKeyStore(tmp_path / "attacker" / ".node_keys.json")
        attacker_keys.ensure_keys()
        payload = {
            "agent_name": "World_Government_Main_Node",
            "public_key": attacker_keys.public_key,
            "capabilities": ["governance"],
        }
        message = {
            "source": "ag_world_gov",
            "target": "node-b",
            "operation": "federation.agent_claim",
            "payload": payload,
            "message_id": "claim-spoof",
            "payload_hash": __import__("hashlib").sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            "signature": sign_payload_hash(attacker_keys.private_key, __import__("hashlib").sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()),
        }
        (node_b / "nadi_inbox.json").write_text(json.dumps([message]))

        assert gw_b.process_inbound(transport_b) == 0
        quarantine_files = [path for path in (node_b / "quarantine").glob("*.json") if path.name != "index.json"]
        assert len(quarantine_files) == 1
        record = json.loads(quarantine_files[0].read_text())
        assert record["stage"] == "gateway_authorization"
        assert record["reason"] == "identity_spoofing_attempt"

    def test_signals_queued_for_moksha(self, tmp_path):
        """All processed messages queue Hebbian signals for MOKSHA drain."""
        keys_p1 = NodeKeyStore(tmp_path / "p1" / ".node_keys.json")
        keys_p1.ensure_keys()
        keys_p2 = NodeKeyStore(tmp_path / "p2" / ".node_keys.json")
        keys_p2.ensure_keys()
        bridge = MagicMock()
        bridge.ingest.return_value = True
        bridge.is_verified_agent.return_value = True
        bridge.get_verified_agent.side_effect = lambda nid: (
            {"node_id": keys_p1.node_id, "public_key": keys_p1.public_key} if nid == keys_p1.node_id
            else {"node_id": keys_p2.node_id, "public_key": keys_p2.public_key} if nid == keys_p2.node_id
            else None
        )
        gw = FederationGateway(bridge=bridge)
        transport = self._make_transport(
            [
                _sign_outbound({"operation": "heartbeat", "source": keys_p1.node_id, "payload": {}}, keys_p1),
                _sign_outbound({"operation": "heartbeat", "source": keys_p2.node_id, "payload": {}}, keys_p2),
            ]
        )

        gw.process_inbound(transport)

        signals = gw._stats.drain_signals()
        assert len(signals) == 2
        assert all(proto == "nadi" and success is True for proto, success in signals)


# ── Replay protection ────────────────────────────────────────────


class TestReplayProtection:
    """Replay guard: timestamp window + per-source LRU of payload_hash."""

    def _make_transport(self, messages: list[dict]) -> MagicMock:
        transport = MagicMock()
        transport.read_outbox.return_value = messages
        return transport

    def test_replay_of_identical_signed_message_is_blocked(self, tmp_path):
        keys = NodeKeyStore(tmp_path / "k" / ".node_keys.json")
        keys.ensure_keys()
        bridge = _verified_mock_bridge(keys)
        gw = FederationGateway(bridge=bridge)
        msg = _sign_outbound({"operation": "heartbeat", "source": keys.node_id, "payload": {"a": 1}}, keys)
        transport = self._make_transport([msg, msg])  # exact same bytes twice

        processed = gw.process_inbound(transport)

        assert processed == 1  # first accepted, second blocked
        assert bridge.ingest.call_count == 1

    def test_message_with_stale_timestamp_is_blocked(self, tmp_path):
        keys = NodeKeyStore(tmp_path / "k" / ".node_keys.json")
        keys.ensure_keys()
        bridge = _verified_mock_bridge(keys)
        gw = FederationGateway(bridge=bridge)
        # Timestamp 1 hour in the past — outside the ±5min window
        stale = _sign_outbound(
            {"operation": "heartbeat", "source": keys.node_id, "payload": {}, "timestamp": time.time() - 3600},
            keys,
        )
        processed = gw.process_inbound(self._make_transport([stale]))

        assert processed == 0
        bridge.ingest.assert_not_called()

    def test_message_without_timestamp_is_blocked(self, tmp_path):
        keys = NodeKeyStore(tmp_path / "k" / ".node_keys.json")
        keys.ensure_keys()
        bridge = _verified_mock_bridge(keys)
        gw = FederationGateway(bridge=bridge)
        # Build a message and strip timestamp post-sign — simulate a sender
        # that doesn't include one
        msg = _sign_outbound({"operation": "heartbeat", "source": keys.node_id, "payload": {}}, keys)
        del msg["timestamp"]
        # Re-sign without timestamp
        import hashlib as _h
        canonical = {k: v for k, v in msg.items() if k not in ("payload_hash", "signature")}
        msg["payload_hash"] = _h.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
        msg["signature"] = sign_payload_hash(keys.private_key, msg["payload_hash"])

        processed = gw.process_inbound(self._make_transport([msg]))

        assert processed == 0
        bridge.ingest.assert_not_called()

    def test_public_operation_skips_replay_guard(self, tmp_path):
        """federation.agent_claim is PUBLIC — replay guard does not apply."""
        keys = NodeKeyStore(tmp_path / "k" / ".node_keys.json")
        keys.ensure_keys()
        bridge = _verified_mock_bridge(keys)
        gw = FederationGateway(bridge=bridge)
        # No timestamp, no signature — agent_claim is bootstrap and not subject
        # to replay protection (it's idempotent at the handler level)
        claim = {
            "operation": "federation.agent_claim",
            "source": keys.node_id,
            "payload": {
                "agent_name": "k", "node_id": keys.node_id,
                "public_key": keys.public_key, "capabilities": [],
            },
        }
        # Send twice: second should still be accepted at the gateway level
        # (the handler dedupes by node_id + content hash internally)
        transport = self._make_transport([claim, claim])
        processed = gw.process_inbound(transport)
        assert processed == 2


import time  # noqa: E402  — used only by replay tests above


# ── Stats ────────────────────────────────────────────────────────


class TestStats:
    def test_stats_tracks_protocols(self):
        bridge = MagicMock()
        bridge.ingest.return_value = True
        a2a = MagicMock()
        a2a.handle_jsonrpc.return_value = {"jsonrpc": "2.0", "id": "1", "result": {}}
        gw = FederationGateway(bridge=bridge, a2a=a2a)

        gw.handle_federation_message({"operation": "heartbeat", "source": "p1", "payload": {}})
        gw.handle_federation_message({"jsonrpc": "2.0", "method": "tasks/get", "params": {"metadata": {}}, "id": "1"})
        gw.handle_federation_message({"bad": "message"})

        stats = gw.stats()
        assert stats["total_requests"] == 2  # Only successful protocol detections are counted
        assert stats["by_protocol"]["nadi"] == 1
        assert stats["by_protocol"]["a2a"] == 1
        assert stats["rejected_parse"] == 1


# ── Integration: MOKSHA Hebbian Drain → SynapseStore ─────────────


class TestMokshaHebbianDrainIntegration:
    """End-to-end: gateway processes messages → MOKSHA drains signals → SynapseStore weights."""

    def test_success_signals_increment_weight(self):
        """Successful gateway processing → SynapseStore.increment_weight('gw:nadi', 'accept')."""
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gw = FederationGateway(bridge=bridge)

        # Simulate DHARMA: gateway processes 2 successful NADI messages
        gw.handle_federation_message({"operation": "heartbeat", "source": "p1", "payload": {}})
        gw.handle_federation_message({"operation": "heartbeat", "source": "p2", "payload": {}})

        # Simulate MOKSHA: drain signals and apply to mock SynapseStore
        synapse_store = MagicMock()
        signals = gw._stats.drain_signals()
        for protocol, success in signals:
            trigger = f"gw:{protocol}"
            if success:
                synapse_store.increment_weight(trigger, "accept")
            else:
                synapse_store.decrement_weight(trigger, "accept")

        assert synapse_store.increment_weight.call_count == 2
        synapse_store.increment_weight.assert_any_call("gw:nadi", "accept")
        synapse_store.decrement_weight.assert_not_called()

    def test_failure_signals_decrement_weight(self):
        """Failed gateway processing → SynapseStore.decrement_weight('gw:nadi', 'accept')."""
        bridge = MagicMock()
        bridge.ingest.return_value = False  # Bridge rejects
        gw = FederationGateway(bridge=bridge)

        # Message passes PARSE and VALIDATE but fails at EXECUTE (bridge rejects)
        gw.handle_federation_message({"operation": "heartbeat", "source": "p1", "payload": {}})

        synapse_store = MagicMock()
        signals = gw._stats.drain_signals()
        for protocol, success in signals:
            trigger = f"gw:{protocol}"
            if success:
                synapse_store.increment_weight(trigger, "accept")
            else:
                synapse_store.decrement_weight(trigger, "accept")

        assert synapse_store.decrement_weight.call_count == 1
        synapse_store.decrement_weight.assert_called_with("gw:nadi", "accept")
        synapse_store.increment_weight.assert_not_called()

    def test_mixed_signals_both_paths(self):
        """Mix of success and failure → correct increment/decrement calls."""
        bridge = MagicMock()
        bridge.ingest.side_effect = [True, False, True]
        gw = FederationGateway(bridge=bridge)

        gw.handle_federation_message({"operation": "heartbeat", "source": "p1", "payload": {}})
        gw.handle_federation_message({"operation": "unknown_op", "source": "p2", "payload": {}})
        gw.handle_federation_message({"operation": "heartbeat", "source": "p3", "payload": {}})

        synapse_store = MagicMock()
        signals = gw._stats.drain_signals()
        for protocol, success in signals:
            trigger = f"gw:{protocol}"
            if success:
                synapse_store.increment_weight(trigger, "accept")
            else:
                synapse_store.decrement_weight(trigger, "accept")

        assert synapse_store.increment_weight.call_count == 2
        assert synapse_store.decrement_weight.call_count == 1

    def test_drain_is_idempotent(self):
        """Second drain returns empty — no double-counting."""
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gw = FederationGateway(bridge=bridge)

        gw.handle_federation_message({"operation": "heartbeat", "source": "p1", "payload": {}})

        first = gw._stats.drain_signals()
        second = gw._stats.drain_signals()

        assert len(first) == 1
        assert len(second) == 0  # Drained — nothing left
