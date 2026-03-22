"""Tests for FederationGateway — Five Tattva gates for federation protocols."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from steward.federation import FederationBridge
from steward.federation_transport import NadiFederationTransport
from steward.federation_gateway import FederationGateway, _is_a2a, _is_nadi

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

    def test_processes_valid_nadi_messages(self):
        """Valid NADI messages reach the bridge through all gates."""
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gw = FederationGateway(bridge=bridge)
        transport = self._make_transport(
            [
                {"operation": "heartbeat", "source": "peer-a", "payload": {"agent_id": "peer-a"}},
                {"operation": "claim_slot", "source": "peer-b", "payload": {"slot_id": "s1", "agent_id": "peer-b"}},
            ]
        )

        processed = gw.process_inbound(transport)

        assert processed == 2
        assert bridge.ingest.call_count == 2
        assert gw.stats()["total_requests"] == 2
        assert gw.stats()["by_protocol"]["nadi"] == 2

    def test_evicted_peer_blocked_at_validate(self):
        """Evicted peer messages are rejected — NEVER reach the bridge."""
        peer = MagicMock()
        peer.status.value = "evicted"
        reaper = MagicMock()
        reaper.get_peer.return_value = peer
        bridge = MagicMock()
        gw = FederationGateway(bridge=bridge, reaper=reaper)
        transport = self._make_transport(
            [{"operation": "heartbeat", "source": "evicted-peer", "payload": {"agent_id": "evicted-peer"}}]
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

    def test_non_dict_messages_skipped(self):
        """Non-dict items in transport are silently skipped."""
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gw = FederationGateway(bridge=bridge)
        transport = self._make_transport(
            [
                "not a dict",
                42,
                None,
                {"operation": "heartbeat", "source": "valid-peer", "payload": {}},
            ]
        )

        processed = gw.process_inbound(transport)

        assert processed == 1
        assert gw.stats()["rejected_parse"] == 3  # 3 non-dicts
        assert gw.stats()["errors"] == 3

    def test_mixed_valid_and_invalid(self):
        """Mix of valid, invalid, and evicted — only valid messages pass."""
        peer = MagicMock()
        peer.status.value = "evicted"
        reaper = MagicMock()
        reaper.get_peer.side_effect = lambda aid: peer if aid == "bad-peer" else None
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gw = FederationGateway(bridge=bridge, reaper=reaper)
        transport = self._make_transport(
            [
                {"operation": "heartbeat", "source": "good-peer", "payload": {}},  # PASS: unknown peer
                {"operation": "heartbeat", "source": "bad-peer", "payload": {}},  # REJECT: evicted
                {"garbage": True},  # REJECT: unknown protocol
                {"operation": "claim_slot", "source": "good-peer", "payload": {"slot_id": "s1"}},  # PASS
            ]
        )

        processed = gw.process_inbound(transport)

        assert processed == 2
        assert bridge.ingest.call_count == 2
        assert gw.stats()["rejected_validate"] == 1
        assert gw.stats()["rejected_parse"] == 1
        assert gw.stats()["errors"] == 2

    def test_bridge_reject_is_counted_and_surfaced(self):
        bridge = MagicMock()
        bridge.ingest.side_effect = [True, False]
        gw = FederationGateway(bridge=bridge)
        transport = self._make_transport(
            [
                {"operation": "heartbeat", "source": "good-peer", "payload": {}},
                {"operation": "unknown_op", "source": "good-peer", "payload": {}},
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

        payload = {
            "agent_name": "node-a",
            "public_key": "ecdsa-pub-placeholder",
            "capabilities": ["bounty_hunter", "infrastructure"],
        }
        message = {
            "source": "node-a",
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
        assert registry["node-a"]["public_key"] == "ecdsa-pub-placeholder"
        assert registry["node-a"]["capabilities"] == ["bounty_hunter", "infrastructure"]

    def test_signals_queued_for_moksha(self):
        """All processed messages queue Hebbian signals for MOKSHA drain."""
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gw = FederationGateway(bridge=bridge)
        transport = self._make_transport(
            [
                {"operation": "heartbeat", "source": "p1", "payload": {}},
                {"operation": "heartbeat", "source": "p2", "payload": {}},
            ]
        )

        gw.process_inbound(transport)

        signals = gw._stats.drain_signals()
        assert len(signals) == 2
        assert all(proto == "nadi" and success is True for proto, success in signals)


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
