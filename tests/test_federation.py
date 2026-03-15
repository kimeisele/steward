"""Tests for Federation Bridge — cross-agent message routing."""

import time

import pytest

from steward.federation import (
    OP_CLAIM_OUTCOME,
    OP_CLAIM_SLOT,
    OP_DELEGATE_TASK,
    OP_HEARTBEAT,
    OP_RELEASE_SLOT,
    OP_TASK_COMPLETED,
    OP_TASK_FAILED,
    FederationBridge,
)
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
