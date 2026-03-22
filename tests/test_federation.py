"""Tests for Federation Bridge — cross-agent message routing."""

import json
import time

from steward.federation import (
    CITY_BOTTLENECK_PREFIX,
    OP_AGENT_CLAIM,
    OP_BOTTLENECK_ESCALATION,
    OP_CITY_REPORT,
    OP_CLAIM_OUTCOME,
    OP_CLAIM_SLOT,
    OP_FEDERATION_NODE_HEALTH,
    OP_GOVERNANCE_BOUNTY,
    OP_DELEGATE_TASK,
    OP_HEARTBEAT,
    OP_RELEASE_SLOT,
    OP_TASK_COMPLETED,
    OP_TASK_FAILED,
    FederationBridge,
)
from steward.federation_transport import NadiFederationTransport
from steward.marketplace import Marketplace
from steward.reaper import HeartbeatReaper


class FakeTransport:
    """Minimal FederationTransport for testing."""

    def __init__(self, messages=None):
        self._outbox = messages or []
        self._inbox = []

    def read_outbox(self):
        return self._outbox

    def append_to_inbox(self, messages):
        self._inbox.extend(messages)
        return len(messages)

    @property
    def inbox(self):
        return self._inbox


class BrokenTransport:
    """Transport that always raises."""

    def read_outbox(self):
        raise ConnectionError("transport down")

    def append_to_inbox(self, messages):
        raise ConnectionError("transport down")


# ── Inbound: Heartbeat ──────────────────────────────────────────


class TestInboundHeartbeat:
    def test_heartbeat_routes_to_reaper(self):
        reaper = HeartbeatReaper()
        bridge = FederationBridge(reaper=reaper)
        assert bridge.ingest(
            OP_HEARTBEAT,
            {
                "agent_id": "peer-1",
                "timestamp": time.time(),
            },
        )
        assert reaper.get_peer("peer-1") is not None

    def test_heartbeat_without_agent_id_rejected(self):
        reaper = HeartbeatReaper()
        bridge = FederationBridge(reaper=reaper)
        assert not bridge.ingest(OP_HEARTBEAT, {"timestamp": time.time()})

    def test_heartbeat_without_reaper_returns_false(self):
        bridge = FederationBridge()
        assert not bridge.ingest(OP_HEARTBEAT, {"agent_id": "peer-1"})

    def test_heartbeat_with_source(self):
        reaper = HeartbeatReaper()
        bridge = FederationBridge(reaper=reaper)
        bridge.ingest(
            OP_HEARTBEAT,
            {
                "agent_id": "peer-1",
                "source": "wiki",
            },
        )
        peer = reaper.get_peer("peer-1")
        assert peer.source == "wiki"


class TestInboundNodeHealth:
    def test_node_health_upserts_peer_registry(self, tmp_path):
        bridge = FederationBridge(agent_id="steward", peer_registry_path=tmp_path / "peer_registry.json")

        assert bridge.ingest(
            OP_FEDERATION_NODE_HEALTH,
            {
                "node_id": "peer-a",
                "protocol_version": "1.0",
                "timestamp": 123.0,
                "status": "DEGRADED",
                "quarantine_metrics": {"total": 2, "by_reason": {}, "by_stage": {}},
            },
        )

        import json

        registry = json.loads((tmp_path / "peer_registry.json").read_text())
        assert registry["peer-a"]["status"] == "DEGRADED"
        assert registry["peer-a"]["protocol_version"] == "1.0"
        assert registry["peer-a"]["timestamp"] == 123.0

    def test_node_health_missing_node_id_is_rejected(self, tmp_path):
        bridge = FederationBridge(agent_id="steward", peer_registry_path=tmp_path / "peer_registry.json")

        assert not bridge.ingest(
            OP_FEDERATION_NODE_HEALTH,
            {
                "protocol_version": "1.0",
                "timestamp": 123.0,
                "status": "HEALTHY",
                "quarantine_metrics": {"total": 0, "by_reason": {}, "by_stage": {}},
            },
        )
        assert not (tmp_path / "peer_registry.json").exists()


class TestInboundAgentClaim:
    def test_agent_claim_upserts_verified_agents_registry(self, tmp_path):
        bridge = FederationBridge(agent_id="steward", verified_agents_path=tmp_path / "verified_agents.json")

        assert bridge.ingest(
            OP_AGENT_CLAIM,
            {
                "agent_name": "agent-city",
                "public_key": "ecdsa-pub-placeholder",
                "capabilities": ["bounty_hunter", "infrastructure"],
            },
        )

        registry = json.loads((tmp_path / "verified_agents.json").read_text())
        assert registry["agent-city"]["public_key"] == "ecdsa-pub-placeholder"
        assert registry["agent-city"]["capabilities"] == ["bounty_hunter", "infrastructure"]

    def test_agent_claim_requires_agent_name_and_public_key(self, tmp_path):
        bridge = FederationBridge(agent_id="steward", verified_agents_path=tmp_path / "verified_agents.json")

        assert not bridge.ingest(OP_AGENT_CLAIM, {"agent_name": "agent-city", "capabilities": ["infra"]})
        assert not (tmp_path / "verified_agents.json").exists()


# ── Inbound: Claim Slot ─────────────────────────────────────────


class TestInboundClaim:
    def test_claim_routes_to_marketplace(self):
        market = Marketplace()
        bridge = FederationBridge(marketplace=market)
        assert bridge.ingest(
            OP_CLAIM_SLOT,
            {
                "slot_id": "task:1",
                "agent_id": "peer-1",
                "trust": 0.8,
            },
        )
        assert market.get_holder("task:1") == "peer-1"

    def test_claim_emits_outcome_event(self):
        market = Marketplace()
        bridge = FederationBridge(marketplace=market)
        bridge.ingest(
            OP_CLAIM_SLOT,
            {
                "slot_id": "task:1",
                "agent_id": "peer-1",
                "trust": 0.5,
            },
        )
        assert len(bridge._outbound) == 1
        event = bridge._outbound[0]
        assert event.operation == OP_CLAIM_OUTCOME
        assert event.payload["granted"] is True
        assert event.payload["holder"] == "peer-1"

    def test_claim_without_marketplace_returns_false(self):
        bridge = FederationBridge()
        assert not bridge.ingest(
            OP_CLAIM_SLOT,
            {
                "slot_id": "task:1",
                "agent_id": "peer-1",
            },
        )

    def test_claim_missing_slot_id_rejected(self):
        market = Marketplace()
        bridge = FederationBridge(marketplace=market)
        assert not bridge.ingest(OP_CLAIM_SLOT, {"agent_id": "peer-1"})

    def test_claim_missing_agent_id_rejected(self):
        market = Marketplace()
        bridge = FederationBridge(marketplace=market)
        assert not bridge.ingest(OP_CLAIM_SLOT, {"slot_id": "task:1"})

    def test_contested_claim_outcome(self):
        market = Marketplace(default_ttl_s=600)
        bridge = FederationBridge(marketplace=market)
        # First claim
        bridge.ingest(
            OP_CLAIM_SLOT,
            {
                "slot_id": "task:1",
                "agent_id": "peer-1",
                "trust": 0.9,
            },
        )
        # Contested claim (lower trust, should be denied)
        bridge.ingest(
            OP_CLAIM_SLOT,
            {
                "slot_id": "task:1",
                "agent_id": "peer-2",
                "trust": 0.3,
            },
        )
        assert len(bridge._outbound) == 2
        denied = bridge._outbound[1]
        assert denied.payload["granted"] is False
        assert denied.payload["holder"] == "peer-1"


# ── Inbound: Release Slot ───────────────────────────────────────


class TestInboundRelease:
    def test_release_routes_to_marketplace(self):
        market = Marketplace()
        market.claim("task:1", "peer-1", trust=0.5)
        bridge = FederationBridge(marketplace=market)
        assert bridge.ingest(
            OP_RELEASE_SLOT,
            {
                "slot_id": "task:1",
                "agent_id": "peer-1",
            },
        )
        assert market.get_holder("task:1") is None

    def test_release_without_marketplace_returns_false(self):
        bridge = FederationBridge()
        assert not bridge.ingest(
            OP_RELEASE_SLOT,
            {
                "slot_id": "task:1",
                "agent_id": "peer-1",
            },
        )

    def test_release_missing_fields_rejected(self):
        market = Marketplace()
        bridge = FederationBridge(marketplace=market)
        assert not bridge.ingest(OP_RELEASE_SLOT, {"slot_id": "task:1"})
        assert not bridge.ingest(OP_RELEASE_SLOT, {"agent_id": "peer-1"})


# ── Unknown Operations ──────────────────────────────────────────


class TestUnknownOperation:
    def test_unknown_returns_false(self):
        bridge = FederationBridge()
        assert not bridge.ingest("bogus_op", {"foo": "bar"})

    def test_inbound_count_increments_for_unknown(self):
        bridge = FederationBridge()
        bridge.ingest("bogus_op", {})
        assert bridge.stats()["inbound_processed"] == 1


# ── Transport Integration ───────────────────────────────────────


class TestProcessInbound:
    def test_reads_from_transport(self):
        reaper = HeartbeatReaper()
        market = Marketplace()
        transport = FakeTransport(
            messages=[
                {"operation": OP_HEARTBEAT, "payload": {"agent_id": "peer-1"}},
                {
                    "operation": OP_CLAIM_SLOT,
                    "payload": {
                        "slot_id": "task:1",
                        "agent_id": "peer-2",
                        "trust": 0.7,
                    },
                },
            ]
        )
        bridge = FederationBridge(reaper=reaper, marketplace=market)
        count = bridge.process_inbound(transport)
        assert count == 2
        assert reaper.get_peer("peer-1") is not None
        assert market.get_holder("task:1") == "peer-2"

    def test_skips_non_dict_messages(self):
        bridge = FederationBridge()
        transport = FakeTransport(messages=["not a dict", 42, None])
        assert bridge.process_inbound(transport) == 0

    def test_handles_transport_failure(self):
        bridge = FederationBridge()
        assert bridge.process_inbound(BrokenTransport()) == 0
        assert bridge.stats()["errors"] == 1


class TestFlushOutbound:
    def test_publishes_pending_events(self):
        market = Marketplace()
        bridge = FederationBridge(marketplace=market, agent_id="steward-1")
        # Generate an outbound event via claim
        bridge.ingest(
            OP_CLAIM_SLOT,
            {
                "slot_id": "task:1",
                "agent_id": "peer-1",
                "trust": 0.5,
            },
        )
        transport = FakeTransport()
        count = bridge.flush_outbound(transport)
        assert count == 1
        assert len(transport.inbox) == 1
        msg = transport.inbox[0]
        assert msg["source"] == "steward-1"
        assert msg["operation"] == OP_CLAIM_OUTCOME

    def test_clears_queue_after_flush(self):
        bridge = FederationBridge()
        bridge.emit("test_op", {"x": 1})
        transport = FakeTransport()
        bridge.flush_outbound(transport)
        assert len(bridge._outbound) == 0

    def test_no_publish_when_empty(self):
        bridge = FederationBridge()
        transport = FakeTransport()
        assert bridge.flush_outbound(transport) == 0

    def test_handles_transport_failure(self):
        bridge = FederationBridge()
        bridge.emit("test_op", {"x": 1})
        assert bridge.flush_outbound(BrokenTransport()) == 0
        assert bridge.stats()["errors"] == 1
        # Events NOT lost on failure — still in queue
        assert len(bridge._outbound) == 1

    def test_unknown_peer_is_allowed_optimistically(self, tmp_path):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("peer-z", timestamp=time.time())
        transport = NadiFederationTransport(str(tmp_path))
        bridge = FederationBridge(reaper=reaper, agent_id="steward", peer_registry_path=tmp_path / "peer_registry.json")
        bridge.emit(OP_DELEGATE_TASK, {"title": "Fix tests"})

        assert bridge.flush_outbound(transport) == 1
        outbox = json.loads((tmp_path / "nadi_outbox.json").read_text())
        assert outbox[0]["target"] == "peer-z"
        assert outbox[0]["operation"] == OP_DELEGATE_TASK

    def test_critical_peer_is_quarantined(self, tmp_path):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("peer-critical", timestamp=time.time())
        (tmp_path / "peer_registry.json").write_text(
            json.dumps(
                {
                    "peer-critical": {
                        "node_id": "peer-critical",
                        "protocol_version": "1.0",
                        "status": "CRITICAL",
                        "timestamp": 123.0,
                    }
                }
            )
        )
        transport = NadiFederationTransport(str(tmp_path))
        bridge = FederationBridge(reaper=reaper, agent_id="steward", peer_registry_path=tmp_path / "peer_registry.json")
        bridge.emit(OP_DELEGATE_TASK, {"title": "Fix tests"})

        assert bridge.flush_outbound(transport) == 0
        records = [json.loads(path.read_text()) for path in (tmp_path / "quarantine").glob("*.json") if path.name != "index.json"]
        assert len(records) == 1
        assert records[0]["stage"] == "routing_outbound"
        assert records[0]["reason"] == "circuit_breaker_peer_critical"
        assert records[0]["message"]["target"] == "peer-critical"

    def test_protocol_mismatch_peer_is_quarantined(self, tmp_path):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("peer-old", timestamp=time.time())
        (tmp_path / "peer_registry.json").write_text(
            json.dumps(
                {
                    "peer-old": {
                        "node_id": "peer-old",
                        "protocol_version": "2.1",
                        "status": "HEALTHY",
                        "timestamp": 123.0,
                    }
                }
            )
        )
        transport = NadiFederationTransport(str(tmp_path))
        bridge = FederationBridge(reaper=reaper, agent_id="steward", peer_registry_path=tmp_path / "peer_registry.json")
        bridge.emit(OP_DELEGATE_TASK, {"title": "Fix tests"})

        assert bridge.flush_outbound(transport) == 0
        records = [json.loads(path.read_text()) for path in (tmp_path / "quarantine").glob("*.json") if path.name != "index.json"]
        assert len(records) == 1
        assert records[0]["reason"] == "circuit_breaker_protocol_mismatch"
        assert records[0]["message"]["target"] == "peer-old"

    def test_node_health_bypasses_critical_peer_breaker(self, tmp_path):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("peer-critical", timestamp=time.time())
        (tmp_path / "peer_registry.json").write_text(
            json.dumps(
                {
                    "peer-critical": {
                        "node_id": "peer-critical",
                        "protocol_version": "1.0",
                        "status": "CRITICAL",
                        "timestamp": 123.0,
                    }
                }
            )
        )
        transport = NadiFederationTransport(str(tmp_path))
        bridge = FederationBridge(reaper=reaper, agent_id="steward", peer_registry_path=tmp_path / "peer_registry.json")
        bridge.emit(
            OP_FEDERATION_NODE_HEALTH,
            {
                "node_id": "steward",
                "protocol_version": "1.0",
                "timestamp": 123.0,
                "status": "HEALTHY",
                "quarantine_metrics": {"total": 0, "by_reason": {}, "by_stage": {}},
            },
        )

        assert bridge.flush_outbound(transport) == 1
        outbox = json.loads((tmp_path / "nadi_outbox.json").read_text())
        assert outbox[0]["operation"] == OP_FEDERATION_NODE_HEALTH
        assert outbox[0]["target"] == "peer-critical"


# ── Stats ────────────────────────────────────────────────────────


class TestBridgeStats:
    def test_stats_track_counts(self):
        reaper = HeartbeatReaper()
        market = Marketplace()
        bridge = FederationBridge(reaper=reaper, marketplace=market)

        bridge.ingest(OP_HEARTBEAT, {"agent_id": "p1"})
        bridge.ingest(
            OP_CLAIM_SLOT,
            {
                "slot_id": "t1",
                "agent_id": "p2",
                "trust": 0.5,
            },
        )

        s = bridge.stats()
        assert s["inbound_processed"] == 2
        assert s["outbound_pending"] == 1  # claim_outcome

        transport = FakeTransport()
        bridge.flush_outbound(transport)
        s = bridge.stats()
        assert s["outbound_published"] == 1
        assert s["outbound_pending"] == 0


# ── End-to-End ───────────────────────────────────────────────────


class TestEndToEnd:
    def test_full_lifecycle(self):
        """Heartbeat → claim → contest → release — full federation cycle."""
        reaper = HeartbeatReaper()
        market = Marketplace(default_ttl_s=600)
        bridge = FederationBridge(reaper=reaper, marketplace=market)

        # Peer-1 announces itself
        bridge.ingest(OP_HEARTBEAT, {"agent_id": "peer-1"})
        assert reaper.get_peer("peer-1") is not None

        # Peer-1 claims a slot
        bridge.ingest(
            OP_CLAIM_SLOT,
            {
                "slot_id": "pr:42",
                "agent_id": "peer-1",
                "trust": 0.6,
            },
        )
        assert market.get_holder("pr:42") == "peer-1"

        # Peer-2 contests with higher trust
        bridge.ingest(
            OP_CLAIM_SLOT,
            {
                "slot_id": "pr:42",
                "agent_id": "peer-2",
                "trust": 0.9,
            },
        )
        assert market.get_holder("pr:42") == "peer-2"

        # Peer-2 releases
        bridge.ingest(
            OP_RELEASE_SLOT,
            {
                "slot_id": "pr:42",
                "agent_id": "peer-2",
            },
        )
        assert market.get_holder("pr:42") is None

        # Stats reflect all operations
        s = bridge.stats()
        assert s["inbound_processed"] == 4


# ── Federation Activation (DHARMA/MOKSHA phase integration) ──────


class TestDharmaHeartbeat:
    """DHARMA phase emits heartbeat to FederationBridge outbox."""

    def test_emit_heartbeat_queues_to_outbox(self):
        bridge = FederationBridge(agent_id="steward-test")
        bridge.emit(
            OP_HEARTBEAT,
            {
                "agent_id": "steward-test",
                "health": 0.85,
            },
        )
        assert bridge.stats()["outbound_pending"] == 1
        # Verify payload
        event = bridge._outbound[0]
        assert event.operation == OP_HEARTBEAT
        assert event.payload["health"] == 0.85

    def test_heartbeat_flushed_via_transport(self):
        bridge = FederationBridge(agent_id="steward-test")
        bridge.emit(OP_HEARTBEAT, {"agent_id": "steward-test", "health": 0.9})
        transport = FakeTransport()
        flushed = bridge.flush_outbound(transport)
        assert flushed == 1
        assert bridge.stats()["outbound_pending"] == 0
        msg = transport.inbox[0]
        assert msg["source"] == "steward-test"
        assert msg["operation"] == OP_HEARTBEAT


class TestMokshaFlush:
    """MOKSHA phase flushes outbound events via transport."""

    def test_flush_clears_outbox(self):
        bridge = FederationBridge()
        bridge.emit("test", {"x": 1})
        bridge.emit("test", {"x": 2})
        transport = FakeTransport()
        assert bridge.flush_outbound(transport) == 2
        assert bridge.stats()["outbound_pending"] == 0
        assert len(transport.inbox) == 2

    def test_no_flush_without_transport(self):
        """Without transport, outbox accumulates (local mode)."""
        bridge = FederationBridge()
        bridge.emit("test", {"x": 1})
        assert bridge.stats()["outbound_pending"] == 1

    def test_flush_uses_federation_message_format(self):
        """Flushed messages use vibe_core FederationMessage schema.

        Verifies alignment with steward-protocol's FederationMessage type
        rather than ad-hoc raw dicts (cross-repo consistency).
        """
        from vibe_core.mahamantra.federation.types import FederationMessage

        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-city")
        bridge = FederationBridge(reaper=reaper, agent_id="steward")
        bridge.emit("heartbeat", {"agent_id": "steward", "health": 0.9})
        transport = FakeTransport()
        bridge.flush_outbound(transport)

        assert len(transport.inbox) >= 1
        msg = transport.inbox[0]
        # Verify the dict has all FederationMessage fields
        parsed = FederationMessage.from_dict(msg)
        assert parsed.source == "steward"
        assert parsed.target == "agent-city"
        assert parsed.operation == "heartbeat"
        assert parsed.ttl_s == 900.0
        assert isinstance(parsed.payload, dict)


# ── Inbound: Delegate Task ─────────────────────────────────────


class TestInboundDelegateTask:
    """OP_DELEGATE_TASK pushes tasks into local TaskManager queue."""

    def test_delegate_task_pushes_to_task_manager(self, tmp_path):
        """Delegated task appears in TaskManager with [FED:source] prefix."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        result = bridge.ingest(
            OP_DELEGATE_TASK,
            {
                "title": "Fix failing tests in api.py",
                "priority": 70,
                "source_agent": "agent-internet",
            },
        )
        assert result is True
        tasks = task_mgr.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "[FED:agent-internet] Fix failing tests in api.py"

    def test_delegate_task_default_source(self, tmp_path):
        """Missing source_agent defaults to 'unknown'."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        bridge.ingest(OP_DELEGATE_TASK, {"title": "Do something"})
        tasks = task_mgr.list_tasks()
        assert tasks[0].title.startswith("[FED:unknown]")

    def test_delegate_task_default_priority(self, tmp_path):
        """Missing priority defaults to 50."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        bridge.ingest(OP_DELEGATE_TASK, {"title": "Task", "source_agent": "peer"})
        tasks = task_mgr.list_tasks()
        assert tasks[0].priority == 50

    def test_delegate_task_missing_title_rejected(self, tmp_path):
        """No title → rejected."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        assert not bridge.ingest(OP_DELEGATE_TASK, {"source_agent": "peer"})
        assert len(task_mgr.list_tasks()) == 0

    def test_delegate_task_empty_title_rejected(self, tmp_path):
        """Empty title → rejected."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        assert not bridge.ingest(OP_DELEGATE_TASK, {"title": "", "source_agent": "peer"})

    def test_delegate_task_no_task_manager_returns_false(self):
        """Without TaskManager registered, delegate_task fails gracefully."""
        bridge = FederationBridge()
        assert not bridge.ingest(
            OP_DELEGATE_TASK,
            {"title": "Fix something", "source_agent": "peer"},
        )

    def test_delegate_task_stores_repo_in_description(self, tmp_path):
        """Repo URL from payload stored in task description for cross-repo dispatch."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        bridge.ingest(
            OP_DELEGATE_TASK,
            {
                "title": "Fix tests",
                "source_agent": "peer",
                "repo": "https://github.com/user/repo",
            },
        )
        tasks = task_mgr.list_tasks()
        assert tasks[0].description == "repo:https://github.com/user/repo"

    def test_delegate_task_no_repo_empty_description(self, tmp_path):
        """Without repo, description is empty."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        bridge.ingest(OP_DELEGATE_TASK, {"title": "Fix tests", "source_agent": "peer"})
        tasks = task_mgr.list_tasks()
        assert tasks[0].description == ""

    def test_delegate_task_via_transport(self, tmp_path):
        """Delegate task arrives via transport.process_inbound()."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        transport = FakeTransport(
            messages=[
                {
                    "operation": OP_DELEGATE_TASK,
                    "payload": {
                        "title": "Update wiki pages",
                        "priority": 60,
                        "source_agent": "wiki-agent",
                    },
                },
            ]
        )
        bridge = FederationBridge()
        count = bridge.process_inbound(transport)
        assert count == 1
        tasks = task_mgr.list_tasks()
        assert len(tasks) == 1
        assert "[FED:wiki-agent]" in tasks[0].title


# ── Cross-Repo Workspace Isolation ─────────────────────────────


class TestCrossRepoWorkspace:
    """Deterministic workspace isolation for cross-repo federation tasks."""

    def test_workspace_clones_and_cleans_up(self, fake_llm, tmp_path):
        """_cross_repo_workspace clones repo, then deletes on exit."""
        import os
        import subprocess

        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))

        # Create a local git repo to clone from
        source_repo = tmp_path / "source-repo"
        source_repo.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        subprocess.run(["git", "init", str(source_repo)], capture_output=True, env=env)
        subprocess.run(
            ["git", "-C", str(source_repo), "config", "commit.gpgsign", "false"], capture_output=True, env=env
        )
        (source_repo / "README.md").write_text("test repo")
        subprocess.run(["git", "-C", str(source_repo), "add", "."], capture_output=True, env=env)
        subprocess.run(["git", "-C", str(source_repo), "commit", "-m", "init"], capture_output=True, env=env)

        workspace_path = None
        original_cwd = agent._autonomy.pipeline._cwd

        with agent._autonomy._cross_repo_workspace(str(source_repo), "test-task-123") as ws:
            workspace_path = ws
            # Workspace exists and has cloned content
            assert ws.exists()
            assert (ws / "README.md").exists()
            assert (ws / "README.md").read_text() == "test repo"
            # Pipeline cwd swapped to workspace
            assert agent._autonomy.pipeline._cwd == str(ws)
            assert agent._autonomy.pipeline._breaker.cwd == str(ws)

        # After exit: workspace deleted, cwd restored
        assert not workspace_path.exists()
        assert agent._autonomy.pipeline._cwd == original_cwd

    def test_workspace_restores_cwd_on_error(self, fake_llm):
        """Pipeline cwd restored even if workspace code throws."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        original_cwd = agent._autonomy.pipeline._cwd

        # Non-existent repo — clone will fail
        try:
            with agent._autonomy._cross_repo_workspace("/nonexistent/repo.git", "fail-task"):
                pass
        except RuntimeError:
            pass  # Expected

        # cwd must be restored
        assert agent._autonomy.pipeline._cwd == original_cwd


# ── Callback Events ────────────────────────────────────────────


class TestCallbackEvents:
    """OP_TASK_COMPLETED and OP_TASK_FAILED close the federation loop."""

    def test_callback_emitted_on_local_federated_task(self, fake_llm):
        """Local [FED:*] task (no repo) emits callback to bridge outbox."""
        import asyncio

        from steward.agent import StewardAgent
        from steward.services import SVC_FEDERATION, SVC_TASK_MANAGER
        from tests.conftest import track_agent
        from vibe_core.di import ServiceRegistry

        agent = track_agent(StewardAgent(provider=fake_llm))
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        bridge = ServiceRegistry.get(SVC_FEDERATION)

        task_mgr.add_task(
            title="[FED:agent-internet] Fix failing tests",
            priority=70,
        )

        asyncio.run(agent.run_autonomous())

        # Bridge should have a callback event
        assert bridge is not None
        callbacks = [e for e in bridge._outbound if e.operation in (OP_TASK_COMPLETED, OP_TASK_FAILED)]
        assert len(callbacks) >= 1
        cb = callbacks[-1]
        assert cb.payload["source_agent"] == "agent-internet"
        assert cb.payload["task_title"] == "Fix failing tests"

    def test_federated_task_derives_repo_url_from_target_repo_metadata(self, fake_llm, tmp_path, monkeypatch):
        import asyncio

        from steward.agent import StewardAgent
        from steward.services import SVC_TASK_MANAGER
        from tests.conftest import track_agent
        from vibe_core.di import ServiceRegistry

        agent = track_agent(StewardAgent(provider=fake_llm))
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)

        task_mgr.add_task(
            title="[FED:agent-city] Fix bottleneck: ruff_clean",
            priority=70,
            description="target_repo:kimeisele/agent-city\ndedup_key:kimeisele/agent-city#ruff_clean",
        )

        seen: dict[str, str] = {}

        class _Workspace:
            def __init__(self, path):
                self._path = path

            def __enter__(self):
                return self._path

            def __exit__(self, exc_type, exc, tb):
                return False

        def fake_workspace(repo_url, task_id):
            seen["repo_url"] = repo_url
            seen["task_id"] = task_id
            return _Workspace(tmp_path / "fed-ws")

        async def fake_guarded_pr_fix(problem, intent_name=""):
            seen["problem"] = problem
            seen["intent_name"] = intent_name
            return "Created PR: https://example.com/pr/1"

        monkeypatch.setattr(agent._autonomy, "_cross_repo_workspace", fake_workspace)
        monkeypatch.setattr(agent._autonomy.pipeline, "guarded_pr_fix", fake_guarded_pr_fix)

        asyncio.run(agent.run_autonomous())

        assert seen["repo_url"] == "https://github.com/kimeisele/agent-city.git"
        assert seen["problem"] == "Fix bottleneck: ruff_clean"
        assert seen["intent_name"] == "DELEGATED_TASK"

    def test_callback_contains_task_completed_on_success(self, fake_llm):
        """Successful federated task emits OP_TASK_COMPLETED."""
        import asyncio

        from steward.agent import StewardAgent
        from steward.services import SVC_FEDERATION, SVC_TASK_MANAGER
        from tests.conftest import track_agent
        from vibe_core.di import ServiceRegistry

        agent = track_agent(StewardAgent(provider=fake_llm))
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        bridge = ServiceRegistry.get(SVC_FEDERATION)

        task_mgr.add_task(
            title="[FED:peer-1] Check health",
            priority=50,
        )

        asyncio.run(agent.run_autonomous())

        assert bridge is not None
        callbacks = [e for e in bridge._outbound if e.operation in (OP_TASK_COMPLETED, OP_TASK_FAILED)]
        assert len(callbacks) >= 1


# ── Inbound: City Report (agent-city) ──────────────────────────


class TestInboundCityReport:
    """OP_CITY_REPORT from agent-city creates bottleneck tasks.

    Verified payload format from kimeisele/agent-city:
    - city/hooks/moksha/outbound.py FederationReportHook
    - city/missions.py create_brain_mission (verb="bottleneck")
    - city/hooks/moksha/mission_lifecycle.py _collect_terminal_missions
    """

    @staticmethod
    def _city_report_payload(mission_results=None, heartbeat=42):
        """Build a city_report payload matching agent-city's verified format."""
        return {
            "heartbeat": heartbeat,
            "population": 5,
            "alive": 3,
            "chain_valid": True,
            "pr_results": [],
            "mission_results": mission_results or [],
            "active_campaigns": [],
            "source_agent": "agent-city",
        }

    def test_city_report_creates_bottleneck_task(self, tmp_path):
        """Bottleneck mission in city_report → [FED:agent-city] task."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        payload = self._city_report_payload(
            mission_results=[
                {
                    "id": "brain_bottleneck_ruff_clean_42",
                    "name": "Brain bottleneck: ruff_clean",
                    "status": "completed",
                    "owner": "mayor",
                },
            ]
        )
        assert bridge.ingest(OP_CITY_REPORT, payload)

        tasks = task_mgr.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "[FED:agent-city] Fix bottleneck: ruff_clean"
        assert tasks[0].priority == 70
        assert "brain_bottleneck_ruff_clean_42" in tasks[0].description

    def test_city_report_ignores_non_bottleneck_missions(self, tmp_path):
        """Non-bottleneck missions (escalation, health, etc.) are ignored."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        payload = self._city_report_payload(
            mission_results=[
                {
                    "id": "brain_escalation_auth_fix_42",
                    "name": "Brain escalation: auth_fix",
                    "status": "completed",
                    "owner": "mayor",
                },
                {
                    "id": "issue_123_42",
                    "name": "Fix #123: broken import",
                    "status": "completed",
                    "owner": "agent-alpha",
                },
            ]
        )
        assert bridge.ingest(OP_CITY_REPORT, payload)
        assert len(task_mgr.list_tasks()) == 0

    def test_city_report_dedup_skips_active_bottleneck(self, tmp_path):
        """Duplicate bottleneck target not created if already active."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        missions = [
            {
                "id": "brain_bottleneck_tests_pass_42",
                "name": "Brain bottleneck: tests_pass",
                "status": "completed",
                "owner": "mayor",
            },
        ]
        # First report creates task
        bridge.ingest(OP_CITY_REPORT, self._city_report_payload(mission_results=missions, heartbeat=42))
        assert len(task_mgr.list_tasks()) == 1

        # Second report with same target — dedup
        bridge.ingest(OP_CITY_REPORT, self._city_report_payload(mission_results=missions, heartbeat=43))
        assert len(task_mgr.list_tasks()) == 1

    def test_city_report_dedup_uses_issue_key_not_title_poetry(self, tmp_path):
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        bridge.ingest(
            OP_CITY_REPORT,
            self._city_report_payload(
                mission_results=[
                    {
                        "id": "brain_bottleneck_ruff_clean_42",
                        "name": "Brain bottleneck: ruff_clean contract",
                        "status": "completed",
                        "owner": "mayor",
                        "issue_key": "kimeisele/agent-city#ruff_clean",
                        "target_repo": "kimeisele/agent-city",
                        "contract_name": "ruff_clean",
                    },
                ],
                heartbeat=42,
            ),
        )
        bridge.ingest(
            OP_CITY_REPORT,
            self._city_report_payload(
                mission_results=[
                    {
                        "id": "brain_bottleneck_ruff_clean_43",
                        "name": "Brain bottleneck: poetry about lint storms",
                        "status": "completed",
                        "owner": "mayor",
                        "issue_key": "kimeisele/agent-city#ruff_clean",
                        "target_repo": "kimeisele/agent-city",
                        "contract_name": "ruff_clean",
                    },
                ],
                heartbeat=43,
            ),
        )

        tasks = task_mgr.list_tasks()
        assert len(tasks) == 1
        assert "dedup_key:kimeisele/agent-city#ruff_clean" in tasks[0].description
        assert "target_repo:kimeisele/agent-city" in tasks[0].description


class TestInboundGovernanceBounty:
    def test_governance_bounty_dedup_uses_violation_id(self, tmp_path):
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        payload = {
            "target": "fix:federation_ci_required:agent-internet",
            "severity": "high",
            "reward": 108,
            "description": "CI required policy violated",
            "issuer": "legislator",
            "violation_id": "gov:ci_required:agent-internet:42",
            "policy_name": "federation_ci_required",
            "target_repo": "kimeisele/agent-internet",
        }
        assert bridge.ingest(OP_GOVERNANCE_BOUNTY, payload)
        payload_2 = {
            "target": "fix:totally different prose that should not matter",
            "severity": "high",
            "reward": 108,
            "description": "duplicate emission",
            "issuer": "legislator",
            "violation_id": "gov:ci_required:agent-internet:42",
            "policy_name": "different_but_ignored_when_violation_id_present",
            "target_repo": "kimeisele/another-repo",
        }
        assert bridge.ingest(OP_GOVERNANCE_BOUNTY, payload_2)

        tasks = task_mgr.list_tasks()
        assert len(tasks) == 1
        assert "dedup_key:gov:ci_required:agent-internet:42" in tasks[0].description
        assert "violation_id:gov:ci_required:agent-internet:42" in tasks[0].description

    def test_governance_bounty_dedup_falls_back_to_target_repo_and_policy(self, tmp_path):
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        payload = {
            "target": "fix:federation_ci_required:agent-internet",
            "severity": "medium",
            "reward": 54,
            "description": "first emission",
            "issuer": "legislator",
            "policy_name": "federation_ci_required",
            "target_repo": "kimeisele/agent-internet",
        }
        assert bridge.ingest(OP_GOVERNANCE_BOUNTY, payload)
        payload_2 = {
            "target": "violation:federation ci required:agent-internet",
            "severity": "medium",
            "reward": 54,
            "description": "duplicate emission",
            "issuer": "legislator",
            "policy_name": "federation_ci_required",
            "target_repo": "kimeisele/agent-internet",
        }
        assert bridge.ingest(OP_GOVERNANCE_BOUNTY, payload_2)

        tasks = task_mgr.list_tasks()
        assert len(tasks) == 1
        assert "dedup_key:kimeisele/agent-internet:federation_ci_required" in tasks[0].description
        assert "policy_name:federation_ci_required" in tasks[0].description
        assert "target_repo:kimeisele/agent-internet" in tasks[0].description


class TestInboundCityReportMore(TestInboundCityReport):
    def test_city_report_records_heartbeat(self):
        """city_report acts as a liveness signal for the reaper."""
        reaper = HeartbeatReaper()
        bridge = FederationBridge(reaper=reaper)
        payload = self._city_report_payload()
        bridge.ingest(OP_CITY_REPORT, payload)

        peer = reaper.get_peer("agent-city")
        assert peer is not None
        assert peer.source == "city_report"

    def test_city_report_empty_missions_accepted(self):
        """city_report with no missions is valid (just heartbeat)."""
        bridge = FederationBridge()
        assert bridge.ingest(OP_CITY_REPORT, self._city_report_payload())

    def test_city_report_via_transport_injects_source(self, tmp_path):
        """process_inbound injects source_agent from message envelope."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        transport = FakeTransport(
            messages=[
                {
                    "source": "agent-city",
                    "target": "steward",
                    "operation": OP_CITY_REPORT,
                    "payload": {
                        "heartbeat": 99,
                        "population": 2,
                        "alive": 1,
                        "chain_valid": True,
                        "pr_results": [],
                        "mission_results": [
                            {
                                "id": "brain_bottleneck_lint_99",
                                "name": "Brain bottleneck: lint",
                                "status": "completed",
                                "owner": "mayor",
                            },
                        ],
                        "active_campaigns": [],
                    },
                    "priority": 2,
                    "timestamp": time.time(),
                    "ttl_s": 7200.0,
                },
            ]
        )
        bridge = FederationBridge()
        count = bridge.process_inbound(transport)
        assert count == 1

        tasks = task_mgr.list_tasks()
        assert len(tasks) == 1
        assert "[FED:agent-city]" in tasks[0].title
        assert "lint" in tasks[0].title

    def test_city_report_multiple_bottlenecks(self, tmp_path):
        """Multiple bottleneck missions in one report create multiple tasks."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        payload = self._city_report_payload(
            mission_results=[
                {
                    "id": "brain_bottleneck_ruff_clean_42",
                    "name": "Brain bottleneck: ruff_clean",
                    "status": "completed",
                    "owner": "mayor",
                },
                {
                    "id": "brain_bottleneck_tests_pass_42",
                    "name": "Brain bottleneck: tests_pass",
                    "status": "completed",
                    "owner": "mayor",
                },
            ]
        )
        bridge.ingest(OP_CITY_REPORT, payload)
        tasks = task_mgr.list_tasks()
        assert len(tasks) == 2
        titles = {t.title for t in tasks}
        assert "[FED:agent-city] Fix bottleneck: ruff_clean" in titles
        assert "[FED:agent-city] Fix bottleneck: tests_pass" in titles

    def test_city_report_no_task_manager_still_accepted(self):
        """Without TaskManager, city_report is accepted (heartbeat still works)."""
        reaper = HeartbeatReaper()
        bridge = FederationBridge(reaper=reaper)
        payload = self._city_report_payload(
            mission_results=[
                {
                    "id": "brain_bottleneck_x_1",
                    "name": "Brain bottleneck: x",
                    "status": "completed",
                    "owner": "mayor",
                },
            ]
        )
        assert bridge.ingest(OP_CITY_REPORT, payload)
        # Heartbeat still recorded
        assert reaper.get_peer("agent-city") is not None

    def test_bottleneck_prefix_constant_matches_agent_city(self):
        """Verify constant matches agent-city's create_brain_mission format."""
        # From city/missions.py: name=f"Brain {verb}: {target[:50]}"
        # with verb="bottleneck"
        assert CITY_BOTTLENECK_PREFIX == "Brain bottleneck: "


class TestInboundBottleneckEscalation:
    def test_bottleneck_escalation_dedup_uses_deterministic_key(self, tmp_path):
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_management.task_manager import TaskManager

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge()
        payload = {
            "target": "ruff contract broken",
            "source": "brain_health",
            "evidence": "first",
            "heartbeat": 10,
            "issue_key": "kimeisele/agent-city#ruff_clean",
            "target_repo": "kimeisele/agent-city",
            "contract_name": "ruff_clean",
        }
        assert bridge.ingest(OP_BOTTLENECK_ESCALATION, payload)
        payload_2 = {
            "target": "completely different poetic wording",
            "source": "brain_critique",
            "evidence": "second",
            "heartbeat": 11,
            "issue_key": "kimeisele/agent-city#ruff_clean",
            "target_repo": "kimeisele/agent-city",
            "contract_name": "ruff_clean",
        }
        assert bridge.ingest(OP_BOTTLENECK_ESCALATION, payload_2)

        tasks = task_mgr.list_tasks()
        assert len(tasks) == 1
        assert "dedup_key:kimeisele/agent-city#ruff_clean" in tasks[0].description
        assert "target_repo:kimeisele/agent-city" in tasks[0].description
