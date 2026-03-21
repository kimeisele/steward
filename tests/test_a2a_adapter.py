"""Tests for A2A Protocol Adapter — A2A JSON-RPC ↔ NADI bridge."""

from __future__ import annotations

import json

from steward.a2a_adapter import (
    A2A_STATE_CANCELED,
    A2A_STATE_COMPLETED,
    A2A_STATE_FAILED,
    A2A_STATE_WORKING,
    A2A_TASKS_CANCEL,
    A2A_TASKS_GET,
    A2A_TASKS_SEND,
    A2AProtocolAdapter,
)


class FakeBridge:
    """Minimal FederationBridge stand-in for testing."""

    def __init__(self, accept: bool = True) -> None:
        self.ingested: list[tuple[str, dict]] = []
        self._accept = accept

    def ingest(self, operation: str, payload: dict) -> bool:
        self.ingested.append((operation, payload))
        return self._accept


# ── Agent Card ─────────────────────────────────────────────────────


def test_get_agent_card_loads_from_file(tmp_path):
    card = {"name": "TestAgent", "version": "0.1", "skills": []}
    card_path = tmp_path / "agent.json"
    card_path.write_text(json.dumps(card))

    adapter = A2AProtocolAdapter(agent_card_path=str(card_path))
    result = adapter.get_agent_card()

    assert result["name"] == "TestAgent"
    # Cached on second call
    assert adapter.get_agent_card() is result


def test_get_agent_card_fallback_on_missing():
    adapter = A2AProtocolAdapter(agent_card_path="/nonexistent/path.json")
    result = adapter.get_agent_card()

    assert result["name"] == "Steward"
    assert "skills" in result


# ── tasks/send ─────────────────────────────────────────────────────


def test_tasks_send_delegates_to_bridge():
    bridge = FakeBridge()
    adapter = A2AProtocolAdapter(bridge=bridge)

    request = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": A2A_TASKS_SEND,
        "params": {
            "id": "task-42",
            "message": {
                "role": "user",
                "parts": [
                    {"type": "text", "text": "Fix the bug in parser.py"},
                    {
                        "type": "data",
                        "data": {
                            "skill_id": "task_execution",
                            "title": "Fix parser bug",
                            "priority": 80,
                            "repo": "kimeisele/steward",
                        },
                    },
                ],
            },
            "metadata": {
                "skill_id": "task_execution",
                "source_agent": "agent-city",
            },
        },
    }

    response = adapter.handle_jsonrpc(request)

    assert response["id"] == "req-1"
    assert "result" in response
    assert response["result"]["id"] == "task-42"
    assert response["result"]["status"]["state"] == A2A_STATE_WORKING

    # Bridge received the NADI operation
    assert len(bridge.ingested) == 1
    op, payload = bridge.ingested[0]
    assert op == "delegate_task"
    assert payload["title"] == "Fix parser bug"
    assert payload["priority"] == 80
    assert payload["source_agent"] == "agent-city"


def test_tasks_send_pr_review():
    bridge = FakeBridge()
    adapter = A2AProtocolAdapter(bridge=bridge)

    request = {
        "jsonrpc": "2.0",
        "id": "req-2",
        "method": A2A_TASKS_SEND,
        "params": {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "type": "data",
                        "data": {
                            "skill_id": "pr_review",
                            "repo": "kimeisele/agent-city",
                            "pr_number": 42,
                            "author": "bot-dev",
                            "files": ["src/main.py"],
                        },
                    }
                ],
            },
            "metadata": {"skill_id": "pr_review", "source_agent": "agent-city"},
        },
    }

    response = adapter.handle_jsonrpc(request)
    assert response["result"]["status"]["state"] == A2A_STATE_WORKING

    op, payload = bridge.ingested[0]
    assert op == "pr_review_request"
    assert payload["repo"] == "kimeisele/agent-city"
    assert payload["pr_number"] == 42


def test_tasks_send_bridge_rejection():
    bridge = FakeBridge(accept=False)
    adapter = A2AProtocolAdapter(bridge=bridge)

    request = {
        "jsonrpc": "2.0",
        "id": "req-3",
        "method": A2A_TASKS_SEND,
        "params": {
            "message": {"role": "user", "parts": [{"type": "text", "text": "do stuff"}]},
            "metadata": {"skill_id": "task_execution", "source_agent": "rogue"},
        },
    }

    response = adapter.handle_jsonrpc(request)
    assert response["result"]["status"]["state"] == A2A_STATE_FAILED


def test_tasks_send_no_bridge():
    adapter = A2AProtocolAdapter(bridge=None)
    request = {
        "jsonrpc": "2.0",
        "id": "req-4",
        "method": A2A_TASKS_SEND,
        "params": {
            "message": {"role": "user", "parts": []},
            "metadata": {"skill_id": "task_execution", "source_agent": "test"},
        },
    }

    response = adapter.handle_jsonrpc(request)
    assert response["result"]["status"]["state"] == A2A_STATE_FAILED


# ── tasks/get ──────────────────────────────────────────────────────


def test_tasks_get():
    bridge = FakeBridge()
    adapter = A2AProtocolAdapter(bridge=bridge)

    # First, create a task
    send_req = {
        "jsonrpc": "2.0",
        "id": "s1",
        "method": A2A_TASKS_SEND,
        "params": {
            "id": "task-100",
            "message": {"role": "user", "parts": [{"type": "text", "text": "hello"}]},
            "metadata": {"skill_id": "task_execution", "source_agent": "x"},
        },
    }
    adapter.handle_jsonrpc(send_req)

    # Then query it
    get_req = {
        "jsonrpc": "2.0",
        "id": "g1",
        "method": A2A_TASKS_GET,
        "params": {"id": "task-100"},
    }
    response = adapter.handle_jsonrpc(get_req)

    assert response["result"]["id"] == "task-100"
    assert response["result"]["status"]["state"] == A2A_STATE_WORKING


def test_tasks_get_not_found():
    adapter = A2AProtocolAdapter()
    response = adapter.handle_jsonrpc({"jsonrpc": "2.0", "id": "g2", "method": A2A_TASKS_GET, "params": {"id": "nope"}})
    assert "error" in response
    assert response["error"]["code"] == -32602


# ── tasks/cancel ───────────────────────────────────────────────────


def test_tasks_cancel():
    bridge = FakeBridge()
    adapter = A2AProtocolAdapter(bridge=bridge)

    # Create task
    adapter.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": "s2",
            "method": A2A_TASKS_SEND,
            "params": {
                "id": "task-200",
                "message": {"role": "user", "parts": []},
                "metadata": {"skill_id": "task_execution", "source_agent": "x"},
            },
        }
    )

    # Cancel it
    response = adapter.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": "c1",
            "method": A2A_TASKS_CANCEL,
            "params": {"id": "task-200"},
        }
    )

    assert response["result"]["status"]["state"] == A2A_STATE_CANCELED


# ── Unknown method ─────────────────────────────────────────────────


def test_unknown_method():
    adapter = A2AProtocolAdapter()
    response = adapter.handle_jsonrpc({"jsonrpc": "2.0", "id": "u1", "method": "tasks/bogus", "params": {}})
    assert "error" in response
    assert response["error"]["code"] == -32601


# ── NADI → A2A Conversion ─────────────────────────────────────────


def test_nadi_event_to_a2a():
    adapter = A2AProtocolAdapter(agent_id="steward")

    result = adapter.nadi_event_to_a2a(
        "delegate_task",
        {
            "title": "Fix parser",
            "source_agent": "steward",
            "priority": 80,
        },
    )

    assert result["jsonrpc"] == "2.0"
    assert result["method"] == "tasks/send"
    parts = result["params"]["message"]["parts"]
    assert len(parts) == 1
    assert parts[0]["type"] == "data"
    assert parts[0]["data"]["nadi_operation"] == "delegate_task"
    assert result["params"]["metadata"]["skill_id"] == "task_execution"


def test_nadi_verdict_to_a2a():
    adapter = A2AProtocolAdapter(agent_id="steward")

    result = adapter.nadi_event_to_a2a(
        "task_completed",
        {"task_title": "Fix parser", "source_agent": "peer-1", "pr_url": "http://example.com/pr/1"},
    )

    assert result["params"]["message"]["parts"][0]["data"]["nadi_operation"] == "task_completed"


# ── Task lifecycle ─────────────────────────────────────────────────


def test_complete_and_fail_task():
    bridge = FakeBridge()
    adapter = A2AProtocolAdapter(bridge=bridge)

    adapter.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": "s3",
            "method": A2A_TASKS_SEND,
            "params": {
                "id": "task-300",
                "message": {"role": "user", "parts": []},
                "metadata": {"skill_id": "task_execution", "source_agent": "x"},
            },
        }
    )

    assert adapter.complete_task("task-300", {"pr_url": "http://example.com"})
    response = adapter.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": "g3",
            "method": A2A_TASKS_GET,
            "params": {"id": "task-300"},
        }
    )
    assert response["result"]["status"]["state"] == A2A_STATE_COMPLETED
    assert response["result"]["artifacts"][0]["parts"][0]["data"]["pr_url"] == "http://example.com"

    # Fail nonexistent task
    assert not adapter.fail_task("nope", "error")


# ── Stats ──────────────────────────────────────────────────────────


def test_stats():
    adapter = A2AProtocolAdapter(agent_id="test-agent")
    stats = adapter.stats()

    assert stats["agent_id"] == "test-agent"
    assert stats["total_tasks"] == 0
    assert stats["by_state"] == {}
