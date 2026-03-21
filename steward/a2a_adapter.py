"""
A2A Protocol Adapter — Bridge between Google's Agent2Agent protocol and NADI.

Translates A2A JSON-RPC 2.0 messages into NADI federation operations and vice
versa.  This lets any A2A-compatible agent (150+ organizations) communicate
with Steward's federation without knowing NADI internals.

A2A spec: https://a2a-protocol.org/latest/
NADI spec: Steward federation_transport.py / federation.py

Architecture:
    A2A JSON-RPC  →  A2AAdapter.handle_request()  →  FederationBridge.ingest()
    FederationBridge.emit()  →  A2AAdapter.to_a2a_message()  →  A2A JSON-RPC

The adapter is stateless — all state lives in FederationBridge + Reaper.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("STEWARD.A2A")

# ── A2A JSON-RPC Method Constants ──────────────────────────────────

A2A_TASKS_SEND = "tasks/send"
A2A_TASKS_GET = "tasks/get"
A2A_TASKS_CANCEL = "tasks/cancel"

# A2A task states
A2A_STATE_SUBMITTED = "submitted"
A2A_STATE_WORKING = "working"
A2A_STATE_INPUT_REQUIRED = "input-required"
A2A_STATE_COMPLETED = "completed"
A2A_STATE_FAILED = "failed"
A2A_STATE_CANCELED = "canceled"

# NADI operation → A2A skill mapping
NADI_TO_A2A_SKILL: dict[str, str] = {
    "delegate_task": "task_execution",
    "pr_review_request": "pr_review",
    "diagnostic_request": "cross_repo_diagnostic",
    "heartbeat": "heartbeat",
}

A2A_SKILL_TO_NADI: dict[str, str] = {
    "task_execution": "delegate_task",
    "pr_review": "pr_review_request",
    "cross_repo_diagnostic": "diagnostic_request",
    "code_analysis": "diagnostic_request",
    "ci_automation": "diagnostic_request",
    "healing": "delegate_task",
}


@dataclass
class A2ATask:
    """In-flight A2A task tracked by the adapter."""

    id: str
    state: str
    skill_id: str
    source_agent: str
    created_at: float
    payload: dict = field(default_factory=dict)
    result: dict | None = None


class A2AProtocolAdapter:
    """Translates A2A JSON-RPC 2.0 ↔ NADI federation operations.

    Usage:
        adapter = A2AProtocolAdapter(bridge=federation_bridge)

        # Handle inbound A2A request
        response = adapter.handle_jsonrpc(request_dict)

        # Convert outbound NADI event to A2A notification
        a2a_msg = adapter.nadi_event_to_a2a(operation, payload)
    """

    def __init__(
        self,
        bridge: object | None = None,
        agent_id: str = "steward",
        agent_card_path: str | None = None,
    ) -> None:
        self._bridge = bridge
        self._agent_id = agent_id
        self._tasks: dict[str, A2ATask] = {}
        self._card_path = agent_card_path or str(Path(__file__).parent.parent / ".well-known" / "agent.json")
        self._agent_card: dict | None = None

    # ── Agent Card ─────────────────────────────────────────────────

    def get_agent_card(self) -> dict:
        """Return the A2A Agent Card (cached after first load)."""
        if self._agent_card is not None:
            return self._agent_card
        try:
            self._agent_card = json.loads(Path(self._card_path).read_text())
        except (OSError, json.JSONDecodeError):
            self._agent_card = {
                "name": "Steward",
                "description": "Autonomous superagent",
                "url": f"https://github.com/kimeisele/{self._agent_id}",
                "version": "1.0.0",
                "skills": [],
            }
        return self._agent_card

    # ── JSON-RPC 2.0 Dispatch ──────────────────────────────────────

    def handle_jsonrpc(self, request: dict) -> dict:
        """Handle an A2A JSON-RPC 2.0 request, return response dict.

        Supports:
            tasks/send    — create a new task (maps to NADI delegate_task etc.)
            tasks/get     — query task status
            tasks/cancel  — cancel a running task
        """
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id", str(uuid.uuid4()))

        dispatch = {
            A2A_TASKS_SEND: self._handle_tasks_send,
            A2A_TASKS_GET: self._handle_tasks_get,
            A2A_TASKS_CANCEL: self._handle_tasks_cancel,
        }

        handler = dispatch.get(method)
        if handler is None:
            return self._error_response(req_id, -32601, f"Method not found: {method}")

        try:
            result = handler(params)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except ValueError as e:
            return self._error_response(req_id, -32602, str(e))
        except Exception as e:
            logger.warning("A2A handler error: %s", e)
            return self._error_response(req_id, -32603, f"Internal error: {e}")

    def _handle_tasks_send(self, params: dict) -> dict:
        """A2A tasks/send → create task, route to NADI bridge."""
        task_id = params.get("id") or str(uuid.uuid4())
        message = params.get("message", {})
        parts = message.get("parts", [])

        # Extract skill from metadata or first text part
        metadata = params.get("metadata", {})
        skill_id = metadata.get("skill_id", "")
        source_agent = metadata.get("source_agent", "unknown")

        # Extract text content from parts
        text_content = ""
        data_content: dict = {}
        for part in parts:
            if part.get("type") == "text":
                text_content = part.get("text", "")
            elif part.get("type") == "data":
                data_content = part.get("data", {})

        # If no explicit skill, try to infer from content
        if not skill_id and data_content:
            skill_id = data_content.get("skill_id", "task_execution")

        # Map A2A skill → NADI operation
        nadi_op = A2A_SKILL_TO_NADI.get(skill_id, "delegate_task")

        # Build NADI payload from A2A message
        nadi_payload = self._a2a_to_nadi_payload(nadi_op, text_content, data_content, source_agent)

        # Track the task
        task = A2ATask(
            id=task_id,
            state=A2A_STATE_SUBMITTED,
            skill_id=skill_id,
            source_agent=source_agent,
            created_at=time.time(),
            payload=nadi_payload,
        )
        self._tasks[task_id] = task

        # Route through NADI bridge
        if self._bridge is not None:
            success = self._bridge.ingest(nadi_op, nadi_payload)
            task.state = A2A_STATE_WORKING if success else A2A_STATE_FAILED
            if not success:
                task.result = {"error": "Bridge rejected the operation"}
        else:
            task.state = A2A_STATE_FAILED
            task.result = {"error": "No federation bridge available"}

        return self._task_to_a2a(task)

    def _handle_tasks_get(self, params: dict) -> dict:
        """A2A tasks/get → query task status."""
        task_id = params.get("id", "")
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        return self._task_to_a2a(task)

    def _handle_tasks_cancel(self, params: dict) -> dict:
        """A2A tasks/cancel → cancel a tracked task."""
        task_id = params.get("id", "")
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        task.state = A2A_STATE_CANCELED
        return self._task_to_a2a(task)

    # ── NADI → A2A Conversion ──────────────────────────────────────

    def nadi_event_to_a2a(self, operation: str, payload: dict) -> dict:
        """Convert an outbound NADI event to A2A JSON-RPC notification.

        Used by MokshaFederationHook to emit A2A-formatted messages
        alongside NADI messages for A2A-compatible peers.
        """
        skill_id = NADI_TO_A2A_SKILL.get(operation, operation)

        # Map NADI operation to A2A task state
        if operation in ("delegate_task", "pr_review_request", "diagnostic_request"):
            task_state = A2A_STATE_SUBMITTED
        elif operation == "task_failed":
            task_state = A2A_STATE_FAILED
        else:
            task_state = A2A_STATE_COMPLETED

        task_id = payload.get("correlation_id") or str(uuid.uuid4())

        return {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "params": {
                "id": task_id,
                "status": {"state": task_state},
                "message": {
                    "role": "agent",
                    "parts": [
                        {
                            "type": "data",
                            "data": {
                                "nadi_operation": operation,
                                "skill_id": skill_id,
                                "source_agent": payload.get("source_agent", self._agent_id),
                                **{k: v for k, v in payload.items() if k != "source_agent"},
                            },
                        }
                    ],
                },
                "metadata": {
                    "skill_id": skill_id,
                    "source_agent": self._agent_id,
                    "nadi_operation": operation,
                },
            },
        }

    def complete_task(self, task_id: str, result: dict) -> bool:
        """Mark an A2A task as completed with result (called by NADI callback)."""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.state = A2A_STATE_COMPLETED
        task.result = result
        return True

    def fail_task(self, task_id: str, error: str) -> bool:
        """Mark an A2A task as failed (called by NADI callback)."""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.state = A2A_STATE_FAILED
        task.result = {"error": error}
        return True

    # ── Stats ──────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Observability: task counts by state."""
        by_state: dict[str, int] = {}
        for task in self._tasks.values():
            by_state[task.state] = by_state.get(task.state, 0) + 1
        return {
            "total_tasks": len(self._tasks),
            "by_state": by_state,
            "agent_id": self._agent_id,
        }

    # ── Private Helpers ────────────────────────────────────────────

    def _a2a_to_nadi_payload(
        self,
        nadi_op: str,
        text_content: str,
        data_content: dict,
        source_agent: str,
    ) -> dict:
        """Convert A2A message parts into NADI operation payload."""
        if nadi_op == "delegate_task":
            return {
                "title": data_content.get("title", text_content or "A2A delegated task"),
                "priority": data_content.get("priority", 50),
                "source_agent": source_agent,
                "repo": data_content.get("repo", ""),
            }
        elif nadi_op == "pr_review_request":
            return {
                "repo": data_content.get("repo", ""),
                "pr_number": data_content.get("pr_number"),
                "author": data_content.get("author", ""),
                "files": data_content.get("files", []),
                "description": text_content or data_content.get("description", ""),
                "source_agent": source_agent,
            }
        elif nadi_op == "diagnostic_request":
            return {
                "target_peer": data_content.get("target_peer", source_agent),
                "source_agent": source_agent,
            }
        else:
            return {
                "source_agent": source_agent,
                "text": text_content,
                **data_content,
            }

    def _task_to_a2a(self, task: A2ATask) -> dict:
        """Convert internal task to A2A task response format."""
        artifacts = []
        if task.result:
            artifacts.append(
                {
                    "parts": [{"type": "data", "data": task.result}],
                }
            )

        return {
            "id": task.id,
            "status": {"state": task.state},
            "artifacts": artifacts,
            "metadata": {
                "skill_id": task.skill_id,
                "source_agent": task.source_agent,
                "created_at": task.created_at,
            },
        }

    @staticmethod
    def _error_response(req_id: str, code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }
