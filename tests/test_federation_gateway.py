"""Tests for FederationGateway — Five Tattva gates for federation protocols."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

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

    def test_nadi_no_bridge(self):
        """NADI message without bridge configured."""
        gw = FederationGateway()
        result = gw.handle_federation_message({"operation": "heartbeat", "source": "peer-1", "payload": {}})
        assert result["success"] is False

    def test_nadi_missing_operation(self):
        """NADI message with empty operation string."""
        bridge = MagicMock()
        gw = FederationGateway(bridge=bridge)
        result = gw.handle_federation_message({"operation": "", "source": "peer-1", "payload": {}})
        # Empty operation: _is_nadi returns True (string), but _execute_nadi rejects
        assert result["success"] is False


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
