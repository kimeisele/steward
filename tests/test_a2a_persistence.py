"""Tests for A2A task state persistence (save/load across reboots)."""

from __future__ import annotations

import json

import pytest

from steward.a2a_adapter import (
    A2A_STATE_COMPLETED,
    A2A_STATE_FAILED,
    A2A_STATE_WORKING,
    A2AProtocolAdapter,
    A2ATask,
)


def _make_adapter() -> A2AProtocolAdapter:
    return A2AProtocolAdapter(agent_id="test-agent")


def _seed_tasks(adapter: A2AProtocolAdapter) -> None:
    """Add test tasks directly to the adapter's internal state."""
    adapter._tasks["task-1"] = A2ATask(
        id="task-1",
        state=A2A_STATE_WORKING,
        skill_id="task_execution",
        source_agent="peer-a",
        created_at=1000.0,
        payload={"title": "Build feature X"},
    )
    adapter._tasks["task-2"] = A2ATask(
        id="task-2",
        state=A2A_STATE_COMPLETED,
        skill_id="pr_review",
        source_agent="peer-b",
        created_at=2000.0,
        payload={"repo": "kimeisele/foo"},
        result={"verdict": "approved"},
    )


# ── save_tasks ────────────────────────────────────────────────────


def test_save_tasks_creates_file(tmp_path):
    adapter = _make_adapter()
    _seed_tasks(adapter)

    path = tmp_path / "a2a_tasks.json"
    saved = adapter.save_tasks(path)

    assert saved == 2
    assert path.exists()
    data = json.loads(path.read_text())
    assert len(data) == 2
    ids = {d["id"] for d in data}
    assert ids == {"task-1", "task-2"}


def test_save_tasks_empty(tmp_path):
    adapter = _make_adapter()
    path = tmp_path / "a2a_tasks.json"
    saved = adapter.save_tasks(path)

    assert saved == 0
    assert not path.exists()


def test_save_tasks_creates_parent_dirs(tmp_path):
    adapter = _make_adapter()
    _seed_tasks(adapter)

    path = tmp_path / "nested" / "deep" / "a2a_tasks.json"
    saved = adapter.save_tasks(path)

    assert saved == 2
    assert path.exists()


# ── load_tasks ────────────────────────────────────────────────────


def test_load_tasks_restores(tmp_path):
    # Save first
    adapter1 = _make_adapter()
    _seed_tasks(adapter1)
    path = tmp_path / "a2a_tasks.json"
    adapter1.save_tasks(path)

    # Load into fresh adapter
    adapter2 = _make_adapter()
    loaded = adapter2.load_tasks(path)

    assert loaded == 2
    assert "task-1" in adapter2._tasks
    assert "task-2" in adapter2._tasks
    assert adapter2._tasks["task-1"].state == A2A_STATE_WORKING
    assert adapter2._tasks["task-2"].result == {"verdict": "approved"}


def test_load_tasks_missing_file(tmp_path):
    adapter = _make_adapter()
    loaded = adapter.load_tasks(tmp_path / "nonexistent.json")
    assert loaded == 0


def test_load_tasks_corrupt_json(tmp_path):
    path = tmp_path / "a2a_tasks.json"
    path.write_text("{not valid json")
    adapter = _make_adapter()
    loaded = adapter.load_tasks(path)
    assert loaded == 0


def test_load_tasks_deduplicates(tmp_path):
    adapter = _make_adapter()
    _seed_tasks(adapter)
    path = tmp_path / "a2a_tasks.json"
    adapter.save_tasks(path)

    # Load again — should not duplicate
    loaded = adapter.load_tasks(path)
    assert loaded == 0  # All already present


def test_roundtrip_preserves_data(tmp_path):
    adapter1 = _make_adapter()
    _seed_tasks(adapter1)
    path = tmp_path / "a2a_tasks.json"
    adapter1.save_tasks(path)

    adapter2 = _make_adapter()
    adapter2.load_tasks(path)

    for task_id in ("task-1", "task-2"):
        orig = adapter1._tasks[task_id]
        restored = adapter2._tasks[task_id]
        assert orig.id == restored.id
        assert orig.state == restored.state
        assert orig.skill_id == restored.skill_id
        assert orig.source_agent == restored.source_agent
        assert orig.created_at == restored.created_at
        assert orig.payload == restored.payload
        assert orig.result == restored.result
