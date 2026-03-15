"""Tests for DelegateToPeerTool — outbound federation delegation.

Validates:
  - Tool selects highest-trust alive peer from Reaper
  - Emits OP_DELEGATE_TASK to FederationBridge outbox
  - Marks current task as BLOCKED with delegation info
  - Fails gracefully when no Reaper, no peers, no bridge
  - Callback resume: OP_TASK_COMPLETED wakes BLOCKED task
  - Full cycle: delegate → BLOCKED → callback → PENDING
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from steward.federation import (
    OP_DELEGATE_TASK,
    OP_TASK_COMPLETED,
    OP_TASK_FAILED,
    FederationBridge,
)
from steward.services import SVC_FEDERATION, SVC_REAPER, SVC_TASK_MANAGER
from steward.tools.delegate import DelegateToPeerTool, set_current_task
from vibe_core.di import ServiceRegistry
from vibe_core.task_management.task_manager import TaskManager
from vibe_core.task_types import TaskStatus


@dataclass
class FakePeer:
    agent_id: str
    trust: float


class FakeReaper:
    def __init__(self, peers: list[FakePeer] | None = None):
        self._peers = peers or []

    def alive_peers(self) -> list[FakePeer]:
        return self._peers

    def record_heartbeat(self, agent_id, timestamp=None, source=""):
        pass

    def reap(self, now=None):
        return []


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset DI and task context before each test."""
    set_current_task(None)
    yield
    ServiceRegistry.reset()
    set_current_task(None)


class TestDelegateToPeerTool:
    """DelegateToPeerTool selects best peer and emits delegation event."""

    def test_name(self):
        tool = DelegateToPeerTool()
        assert tool.name == "delegate_to_peer"

    def test_validate_requires_title(self):
        tool = DelegateToPeerTool()
        with pytest.raises(ValueError):
            tool.validate({})
        with pytest.raises(ValueError):
            tool.validate({"title": ""})

    def test_no_reaper_returns_error(self):
        tool = DelegateToPeerTool()
        result = tool.execute({"title": "fix tests"})
        assert not result.success
        assert "Reaper" in result.error

    def test_no_alive_peers_returns_error(self):
        tool = DelegateToPeerTool()
        ServiceRegistry.register(SVC_REAPER, FakeReaper(peers=[]))
        result = tool.execute({"title": "fix tests"})
        assert not result.success
        assert "No alive peers" in result.error

    def test_no_bridge_returns_error(self):
        tool = DelegateToPeerTool()
        ServiceRegistry.register(SVC_REAPER, FakeReaper(peers=[FakePeer("peer-1", 0.8)]))
        result = tool.execute({"title": "fix tests"})
        assert not result.success
        assert "FederationBridge" in result.error

    def test_selects_highest_trust_peer(self):
        tool = DelegateToPeerTool()
        peers = [
            FakePeer("low-trust", 0.3),
            FakePeer("high-trust", 0.9),
            FakePeer("mid-trust", 0.6),
        ]
        ServiceRegistry.register(SVC_REAPER, FakeReaper(peers=peers))
        bridge = FederationBridge(agent_id="steward")
        ServiceRegistry.register(SVC_FEDERATION, bridge)

        result = tool.execute({"title": "fix tests"})
        assert result.success
        assert "high-trust" in result.output
        assert result.metadata["peer_id"] == "high-trust"
        assert result.metadata["peer_trust"] == 0.9

    def test_emits_delegate_task_event(self):
        tool = DelegateToPeerTool()
        ServiceRegistry.register(SVC_REAPER, FakeReaper(peers=[FakePeer("peer-1", 0.8)]))
        bridge = FederationBridge(agent_id="steward")
        ServiceRegistry.register(SVC_FEDERATION, bridge)

        tool.execute({"title": "fix tests", "priority": 70, "repo": "https://github.com/test/repo"})

        assert len(bridge._outbound) == 1
        event = bridge._outbound[0]
        assert event.operation == OP_DELEGATE_TASK
        assert event.payload["title"] == "fix tests"
        assert event.payload["priority"] == 70
        assert event.payload["source_agent"] == "steward"
        assert event.payload["target_agent"] == "peer-1"
        assert event.payload["repo"] == "https://github.com/test/repo"

    def test_suspends_current_task_as_blocked(self, tmp_path):
        tool = DelegateToPeerTool()
        ServiceRegistry.register(SVC_REAPER, FakeReaper(peers=[FakePeer("peer-1", 0.8)]))
        bridge = FederationBridge(agent_id="steward")
        ServiceRegistry.register(SVC_FEDERATION, bridge)

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        task_mgr.add_task(title="[HEALTH_CHECK] Run health", priority=50)
        tasks = task_mgr.list_tasks(status=TaskStatus.PENDING)
        task_id = tasks[0].id

        # Set current task context (autonomy engine does this before LLM dispatch)
        set_current_task(task_id, "[HEALTH_CHECK] Run health")

        result = tool.execute({"title": "fix tests in peer repo"})
        assert result.success
        assert result.metadata["task_suspended"]

        # Task should now be BLOCKED
        blocked = task_mgr.list_tasks(status=TaskStatus.BLOCKED)
        assert len(blocked) == 1
        assert blocked[0].id == task_id
        desc = getattr(blocked[0], "description", "")
        assert "delegated:fix tests in peer repo" in desc
        assert "peer:peer-1" in desc

    def test_no_suspension_without_task_context(self, tmp_path):
        """Without set_current_task(), tool delegates but doesn't suspend."""
        tool = DelegateToPeerTool()
        ServiceRegistry.register(SVC_REAPER, FakeReaper(peers=[FakePeer("peer-1", 0.8)]))
        bridge = FederationBridge(agent_id="steward")
        ServiceRegistry.register(SVC_FEDERATION, bridge)

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        task_mgr.add_task(title="[HEALTH_CHECK] Run health", priority=50)

        # No set_current_task() call
        result = tool.execute({"title": "fix tests"})
        assert result.success

        # Task should NOT be blocked
        blocked = task_mgr.list_tasks(status=TaskStatus.BLOCKED)
        assert len(blocked) == 0

    def test_default_priority_and_repo(self):
        tool = DelegateToPeerTool()
        ServiceRegistry.register(SVC_REAPER, FakeReaper(peers=[FakePeer("peer-1", 0.8)]))
        bridge = FederationBridge(agent_id="steward")
        ServiceRegistry.register(SVC_FEDERATION, bridge)

        tool.execute({"title": "simple task"})

        event = bridge._outbound[0]
        assert event.payload["priority"] == 50
        assert event.payload["repo"] == ""


class TestCallbackResume:
    """OP_TASK_COMPLETED / OP_TASK_FAILED resumes BLOCKED tasks."""

    def _setup_blocked_task(self, tmp_path, task_title="fix tests"):
        """Create a BLOCKED task that was delegated."""
        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        task_mgr.add_task(title="[HEALTH_CHECK] Run health", priority=50)
        tasks = task_mgr.list_tasks(status=TaskStatus.PENDING)
        task_id = tasks[0].id

        # Simulate delegation: mark BLOCKED with delegation info
        task_mgr.update_task(
            task_id,
            status=TaskStatus.BLOCKED,
            description=f"delegated:{task_title}|peer:agent-internet",
        )

        bridge = FederationBridge(agent_id="steward")
        ServiceRegistry.register(SVC_FEDERATION, bridge)
        return task_mgr, bridge, task_id

    def test_task_completed_resumes_blocked_task(self, tmp_path):
        task_mgr, bridge, task_id = self._setup_blocked_task(tmp_path)

        ok = bridge.ingest(
            OP_TASK_COMPLETED,
            {
                "task_title": "fix tests",
                "source_agent": "agent-internet",
                "pr_url": "https://github.com/test/repo/pull/42",
            },
        )
        assert ok

        # Task should be PENDING again
        pending = task_mgr.list_tasks(status=TaskStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].id == task_id
        desc = getattr(pending[0], "description", "")
        assert "peer_result:https://github.com/test/repo/pull/42" in desc

    def test_task_failed_resumes_blocked_task(self, tmp_path):
        task_mgr, bridge, task_id = self._setup_blocked_task(tmp_path)

        ok = bridge.ingest(
            OP_TASK_FAILED,
            {
                "task_title": "fix tests",
                "source_agent": "agent-internet",
                "error": "Pipeline failed",
            },
        )
        assert ok

        pending = task_mgr.list_tasks(status=TaskStatus.PENDING)
        assert len(pending) == 1
        desc = getattr(pending[0], "description", "")
        assert "peer_error:Pipeline failed" in desc

    def test_callback_no_matching_blocked_task(self, tmp_path):
        task_mgr, bridge, _ = self._setup_blocked_task(tmp_path, task_title="fix tests")

        # Callback for a different task title
        ok = bridge.ingest(
            OP_TASK_COMPLETED,
            {
                "task_title": "unrelated task",
                "source_agent": "peer-1",
            },
        )
        assert not ok

        # Original task still BLOCKED
        blocked = task_mgr.list_tasks(status=TaskStatus.BLOCKED)
        assert len(blocked) == 1

    def test_callback_without_task_manager(self):
        bridge = FederationBridge(agent_id="steward")
        ok = bridge.ingest(
            OP_TASK_COMPLETED,
            {
                "task_title": "fix tests",
                "source_agent": "peer-1",
            },
        )
        assert not ok

    def test_callback_empty_title(self, tmp_path):
        task_mgr, bridge, _ = self._setup_blocked_task(tmp_path)
        ok = bridge.ingest(
            OP_TASK_COMPLETED,
            {
                "task_title": "",
                "source_agent": "peer-1",
            },
        )
        assert not ok


class TestFullDelegationCycle:
    """End-to-end: delegate → BLOCKED → callback → PENDING."""

    def test_delegate_then_callback_resumes(self, tmp_path):
        # Setup infrastructure
        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)
        ServiceRegistry.register(SVC_REAPER, FakeReaper(peers=[FakePeer("agent-internet", 0.85)]))
        bridge = FederationBridge(agent_id="steward")
        ServiceRegistry.register(SVC_FEDERATION, bridge)

        # 1. Create a task
        task_mgr.add_task(title="[CI_CHECK] Run CI", priority=50)
        tasks = task_mgr.list_tasks(status=TaskStatus.PENDING)
        task_id = tasks[0].id

        # 2. Simulate autonomy engine setting task context
        set_current_task(task_id, "[CI_CHECK] Run CI")

        # 3. LLM calls delegate_to_peer
        tool = DelegateToPeerTool()
        result = tool.execute(
            {"title": "fix failing CI in agent-internet", "repo": "https://github.com/test/agent-internet"}
        )
        assert result.success

        # 4. Task is BLOCKED, delegation event in outbox
        blocked = task_mgr.list_tasks(status=TaskStatus.BLOCKED)
        assert len(blocked) == 1
        assert blocked[0].id == task_id

        assert len(bridge._outbound) == 1
        assert bridge._outbound[0].operation == OP_DELEGATE_TASK
        assert bridge._outbound[0].payload["target_agent"] == "agent-internet"

        # 5. Peer completes the task — inbound callback
        ok = bridge.ingest(
            OP_TASK_COMPLETED,
            {
                "task_title": "fix failing CI in agent-internet",
                "source_agent": "agent-internet",
                "pr_url": "https://github.com/test/agent-internet/pull/7",
            },
        )
        assert ok

        # 6. Task is PENDING again with peer result
        pending = task_mgr.list_tasks(status=TaskStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].id == task_id
        desc = getattr(pending[0], "description", "")
        assert "peer_result:" in desc
        assert "pull/7" in desc

        # No more BLOCKED tasks
        blocked = task_mgr.list_tasks(status=TaskStatus.BLOCKED)
        assert len(blocked) == 0
