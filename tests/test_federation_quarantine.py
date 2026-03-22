import json
from unittest.mock import MagicMock

from steward.federation_gateway import FederationGateway
from steward.federation_quarantine import QuarantineReplayEngine
from steward.federation_transport import NadiFederationTransport


class TestQuarantineReplayEngine:
    def test_dry_run_reports_valid_and_invalid_records(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        transport.quarantine_messages(
            [{"source": "peer-1", "operation": "heartbeat", "payload": {}}],
            reason="Bridge rejected operation 'heartbeat'",
            stage="gateway_reject",
        )
        transport.quarantine_messages(
            [{"raw_text": "{broken json", "path": str(tmp_path / 'nadi_inbox.json')}],
            reason="NADI inbox JSON decode failed",
            stage="transport_read",
        )

        engine = QuarantineReplayEngine(
            transport=transport,
            gateway=FederationGateway(bridge=MagicMock()),
        )

        summary = engine.dry_run()

        assert summary["would_accept"] == 1
        assert summary["still_invalid"] == 1
        assert len(summary["files"]) == 2

    def test_reinject_by_file_processes_and_cleans_up_quarantine(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gateway = FederationGateway(bridge=bridge)
        transport.quarantine_messages(
            [{"source": "peer-1", "operation": "heartbeat", "payload": {"agent_id": "peer-1"}}],
            reason="Bridge rejected operation 'heartbeat'",
            stage="gateway_reject",
        )
        quarantine_file = [path for path in (tmp_path / "quarantine").glob("*.json") if path.name != "index.json"][0].name

        engine = QuarantineReplayEngine(transport=transport, gateway=gateway)
        summary = engine.reinject(file_name=quarantine_file)

        assert summary["replayed"] == 1
        assert summary["failed"] == 0
        assert [path for path in (tmp_path / "quarantine").glob("*.json") if path.name != "index.json"] == []
        assert json.loads((tmp_path / "quarantine" / "index.json").read_text()) == []
        assert json.loads((tmp_path / "nadi_inbox.json").read_text()) == []
        bridge.ingest.assert_called_once_with("heartbeat", {"agent_id": "peer-1"})

    def test_reinject_by_reason_only_replays_matching_records(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gateway = FederationGateway(bridge=bridge)
        transport.quarantine_messages(
            [{"source": "peer-1", "operation": "heartbeat", "payload": {}}],
            reason="Gateway Validate Reject",
            stage="gateway_reject",
        )
        transport.quarantine_messages(
            [{"source": "peer-2", "operation": "task_failed", "payload": {}}],
            reason="Bridge rejected operation 'task_failed'",
            stage="gateway_reject",
        )

        engine = QuarantineReplayEngine(transport=transport, gateway=gateway)
        summary = engine.reinject(reject_reason="Gateway Validate Reject")

        assert summary["replayed"] == 1
        remaining = [path for path in (tmp_path / "quarantine").glob("*.json") if path.name != "index.json"]
        assert len(remaining) == 1
        record = json.loads(remaining[0].read_text())
        assert record["reason"] == "Bridge rejected operation 'task_failed'"

    def test_reinject_keeps_quarantine_when_staging_fails(self, tmp_path, monkeypatch):
        transport = NadiFederationTransport(str(tmp_path))
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gateway = FederationGateway(bridge=bridge)
        transport.quarantine_messages(
            [{"source": "peer-1", "operation": "heartbeat", "payload": {}}],
            reason="Bridge rejected operation 'heartbeat'",
            stage="gateway_reject",
        )
        engine = QuarantineReplayEngine(transport=transport, gateway=gateway)

        def _boom(messages):
            raise OSError("disk full")

        monkeypatch.setattr(transport, "stage_replay_messages", _boom)
        summary = engine.reinject()

        assert summary["replayed"] == 0
        assert summary["failed"] == 1
        assert len([path for path in (tmp_path / "quarantine").glob("*.json") if path.name != "index.json"]) == 1
        bridge.ingest.assert_not_called()

    def test_analytics_groups_by_reason_and_stage(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        transport.quarantine_messages(
            [{"source": "peer-1", "operation": "heartbeat", "payload": {}}],
            reason="Gateway Validate Reject",
            stage="gateway_validate_reject",
        )
        transport.quarantine_messages(
            [{"source": "peer-2", "operation": "task_failed", "payload": {}}],
            reason="Gateway Validate Reject",
            stage="gateway_validate_reject",
        )
        transport.quarantine_messages(
            [{"raw_text": "{broken json", "path": str(tmp_path / 'nadi_inbox.json')}],
            reason="NADI inbox JSON decode failed",
            stage="transport_malformed",
        )

        engine = QuarantineReplayEngine(transport=transport, gateway=FederationGateway(bridge=MagicMock()))
        summary = engine.analytics()

        assert summary["total"] == 3
        assert summary["by_reason"]["Gateway Validate Reject"] == 2
        assert summary["by_reason"]["NADI inbox JSON decode failed"] == 1
        assert summary["by_stage"]["gateway_validate_reject"] == 2
        assert summary["by_stage"]["transport_malformed"] == 1

    def test_build_node_health_report_is_nadi_ready(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        transport.quarantine_messages(
            [{"source": "peer-1", "operation": "heartbeat", "payload": {}}],
            reason="Gateway Validate Reject",
            stage="gateway_validate_reject",
        )

        engine = QuarantineReplayEngine(
            transport=transport,
            gateway=FederationGateway(bridge=MagicMock()),
            node_id="steward-node",
        )
        report = engine.build_node_health_report()

        assert report["node_id"] == "steward-node"
        assert isinstance(report["timestamp"], float)
        assert report["quarantine_metrics"]["total"] == 1
        assert report["quarantine_metrics"]["by_reason"]["Gateway Validate Reject"] == 1
        assert "recommended_action" in report

    def test_reinject_limit_throttles_batch_replay(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        bridge = MagicMock()
        bridge.ingest.return_value = True
        gateway = FederationGateway(bridge=bridge)
        transport.quarantine_messages(
            [{"source": "peer-1", "operation": "heartbeat", "payload": {}}],
            reason="Gateway Validate Reject",
            stage="gateway_validate_reject",
        )
        transport.quarantine_messages(
            [{"source": "peer-2", "operation": "task_failed", "payload": {}}],
            reason="Gateway Validate Reject",
            stage="gateway_validate_reject",
        )

        engine = QuarantineReplayEngine(transport=transport, gateway=gateway)
        summary = engine.reinject(reject_reason="Gateway Validate Reject", limit=1)

        assert summary["replayed"] == 1
        assert len([path for path in (tmp_path / "quarantine").glob("*.json") if path.name != "index.json"]) == 1
        assert bridge.ingest.call_count == 1
