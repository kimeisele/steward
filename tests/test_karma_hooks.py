"""Tests for KARMA phase hooks — federation callbacks, task prioritization, A2A progress."""

from __future__ import annotations

from steward.hooks.karma import (
    KarmaA2AProgressHook,
    KarmaFederationCallbackHook,
    KarmaTaskPrioritizationHook,
)
from steward.phase_hook import KARMA, PhaseContext

# ── Hook Metadata ─────────────────────────────────────────────────


def test_federation_callback_hook_metadata():
    hook = KarmaFederationCallbackHook()
    assert hook.name == "karma_federation_callback"
    assert hook.phase == KARMA
    assert hook.priority == 10


def test_task_prioritization_hook_metadata():
    hook = KarmaTaskPrioritizationHook()
    assert hook.name == "karma_task_prioritization"
    assert hook.phase == KARMA
    assert hook.priority == 20


def test_a2a_progress_hook_metadata():
    hook = KarmaA2AProgressHook()
    assert hook.name == "karma_a2a_progress"
    assert hook.phase == KARMA
    assert hook.priority == 80


# ── Federation Callback Hook ──────────────────────────────────────


def test_federation_callback_no_task_manager(tmp_path):
    """Execute should be safe with no services registered."""
    from vibe_core.di import ServiceRegistry

    ServiceRegistry.reset_all()
    hook = KarmaFederationCallbackHook()
    ctx = PhaseContext(cwd=str(tmp_path))
    hook.execute(ctx)
    assert not ctx.operations


def test_federation_callback_no_blocked_tasks(tmp_path):
    """No blocked tasks = no work."""
    from unittest.mock import MagicMock

    from steward.services import SVC_FEDERATION, SVC_TASK_MANAGER
    from vibe_core.di import ServiceRegistry

    ServiceRegistry.reset_all()

    task_mgr = MagicMock()
    task_mgr.list_tasks.return_value = []
    ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)
    ServiceRegistry.register(SVC_FEDERATION, MagicMock())

    hook = KarmaFederationCallbackHook()
    ctx = PhaseContext(cwd=str(tmp_path))
    hook.execute(ctx)
    assert not ctx.operations


# ── Task Prioritization Hook ─────────────────────────────────────


def test_task_prioritization_no_task_manager(tmp_path):
    from vibe_core.di import ServiceRegistry

    ServiceRegistry.reset_all()
    hook = KarmaTaskPrioritizationHook()
    ctx = PhaseContext(cwd=str(tmp_path))
    hook.execute(ctx)
    assert not ctx.operations


def test_task_prioritization_elevates_federation_tasks(tmp_path):
    from unittest.mock import MagicMock

    from steward.services import SVC_TASK_MANAGER
    from vibe_core.di import ServiceRegistry

    ServiceRegistry.reset_all()

    task1 = MagicMock()
    task1.title = "[HEAL_REPO] Peer foo — Kirtan escalation"
    task1.priority = 50  # below threshold — should be elevated
    task1.id = "t1"
    task2 = MagicMock()
    task2.title = "Regular task"
    task2.priority = 50
    task2.id = "t2"
    task3 = MagicMock()
    task3.title = "[POST_MERGE] Verify merge abc12345"
    task3.priority = 95  # already above threshold — no update
    task3.id = "t3"

    task_mgr = MagicMock()
    task_mgr.list_tasks.return_value = [task1, task2, task3]
    ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

    hook = KarmaTaskPrioritizationHook()
    ctx = PhaseContext(cwd=str(tmp_path))
    hook.execute(ctx)
    assert len(ctx.operations) == 1
    assert "fed_tasks=2" in ctx.operations[0]
    assert "total=3" in ctx.operations[0]
    assert "elevated=1" in ctx.operations[0]
    # task1 elevated, task3 already >=90, task2 is regular
    task_mgr.update_task.assert_called_once_with("t1", priority=90)


def test_task_prioritization_no_pending(tmp_path):
    from unittest.mock import MagicMock

    from steward.services import SVC_TASK_MANAGER
    from vibe_core.di import ServiceRegistry

    ServiceRegistry.reset_all()

    task_mgr = MagicMock()
    task_mgr.list_tasks.return_value = []
    ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

    hook = KarmaTaskPrioritizationHook()
    ctx = PhaseContext(cwd=str(tmp_path))
    hook.execute(ctx)
    assert not ctx.operations


# ── A2A Progress Hook ─────────────────────────────────────────────


def test_a2a_progress_no_services(tmp_path):
    from vibe_core.di import ServiceRegistry

    ServiceRegistry.reset_all()
    hook = KarmaA2AProgressHook()
    ctx = PhaseContext(cwd=str(tmp_path))
    hook.execute(ctx)
    assert not ctx.operations


def test_a2a_progress_completes_tasks(tmp_path):
    from unittest.mock import MagicMock

    from steward.services import SVC_A2A_ADAPTER, SVC_TASK_MANAGER
    from vibe_core.di import ServiceRegistry

    ServiceRegistry.reset_all()

    task = MagicMock()
    task.id = "task-123"

    task_mgr = MagicMock()
    task_mgr.list_tasks.return_value = [task]
    ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

    a2a = MagicMock()
    ServiceRegistry.register(SVC_A2A_ADAPTER, a2a)

    hook = KarmaA2AProgressHook()
    ctx = PhaseContext(cwd=str(tmp_path))
    hook.execute(ctx)

    a2a.complete_task.assert_called_once()
    call_args = a2a.complete_task.call_args
    assert call_args[0][0] == "task-123"


# ── Hook Registration ─────────────────────────────────────────────


def test_karma_hooks_registered():
    """All KARMA hooks should be in register_default_hooks."""
    from steward.phase_hook import PhaseHookRegistry

    registry = PhaseHookRegistry()

    # Reset ServiceRegistry to avoid boot conflicts
    from vibe_core.di import ServiceRegistry

    ServiceRegistry.reset_all()

    from steward.hooks import register_default_hooks

    register_default_hooks(registry)

    karma_hooks = registry.get_hooks(KARMA)
    names = [h.name for h in karma_hooks]
    assert "karma_federation_callback" in names
    assert "karma_task_prioritization" in names
    assert "karma_a2a_progress" in names

    # Verify priority order
    priorities = [h.priority for h in karma_hooks]
    assert priorities == sorted(priorities)
