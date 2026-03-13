"""
Delegate-to-Peer Tool — Outbound task delegation to federation peers.

Karmendriya (action organ) for federation command. Buddhi (the cognitive
pipeline) decides WHEN to delegate; the LLM (provider) is just the
execution substrate. This tool is the mechanism Buddhi uses to act.

1. Queries the Reaper for alive peers sorted by trust
2. Optionally filters by required capability
3. Emits OP_DELEGATE_TASK to the FederationBridge outbox
4. Marks the current task as BLOCKED (waiting for peer)

The agent does NOT block or poll. KARMA phase resumes the task when
OP_TASK_COMPLETED arrives via inbound federation.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from steward.federation import OP_DELEGATE_TASK
from steward.services import SVC_FEDERATION, SVC_REAPER
from vibe_core.di import ServiceRegistry
from vibe_core.tools.tool_protocol import Tool, ToolResult

logger = logging.getLogger("STEWARD.TOOL.DELEGATE")

# Current task context — set by AutonomyEngine before LLM dispatch,
# read by the tool to mark the task as BLOCKED on delegation.
_current_task_id: str | None = None
_current_task_title: str | None = None


def set_current_task(task_id: str | None, task_title: str | None = None) -> None:
    """Set the current task context for delegation tracking."""
    global _current_task_id, _current_task_title
    _current_task_id = task_id
    _current_task_title = task_title


class DelegateToPeerTool(Tool):
    """Delegate a task to the best available federation peer.

    Selects the highest-trust alive peer (optionally filtered by capability)
    and emits an OP_DELEGATE_TASK event. The current task is suspended —
    the agent returns to idle and resumes when the peer responds.
    """

    @property
    def name(self) -> str:
        return "delegate_to_peer"

    @property
    def description(self) -> str:
        return (
            "Delegate a task to a federation peer. Selects the highest-trust "
            "alive peer with the required capability. The task is suspended "
            "until the peer responds. Use when a task requires capabilities "
            "you don't have (web search, wiki sync, etc.) or when you want "
            "to parallelize work across multiple agents."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "title": {
                "type": "string",
                "required": True,
                "description": "Task title describing what the peer should do",
            },
            "capability": {
                "type": "string",
                "required": False,
                "description": "Required capability (e.g., 'web_search', 'wiki_sync'). "
                "If omitted, delegates to highest-trust peer.",
            },
            "priority": {
                "type": "integer",
                "required": False,
                "description": "Task priority 0-100 (default: 50)",
            },
            "repo": {
                "type": "string",
                "required": False,
                "description": "Target repository URL for cross-repo work",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if not parameters.get("title"):
            raise ValueError("title is required")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        title = parameters["title"]
        capability = parameters.get("capability", "")
        priority = parameters.get("priority", 50)
        repo = parameters.get("repo", "")

        # 1. Find the best peer
        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is None:
            return ToolResult(success=False, error="No Reaper registered — federation not active")

        peers = reaper.alive_peers()
        if not peers:
            return ToolResult(success=False, error="No alive peers in federation")

        # Filter by capability if requested
        if capability:
            peers = [p for p in peers if capability in getattr(p, "capabilities", ())]
            if not peers:
                return ToolResult(
                    success=False,
                    error=f"No peers with capability '{capability}'",
                )

        # Select highest-trust peer
        best = max(peers, key=lambda p: p.trust)

        # 2. Emit delegation event
        bridge = ServiceRegistry.get(SVC_FEDERATION)
        if bridge is None:
            return ToolResult(success=False, error="No FederationBridge registered")

        bridge.emit(
            OP_DELEGATE_TASK,
            {
                "title": title,
                "priority": priority,
                "source_agent": bridge.agent_id,
                "target_agent": best.agent_id,
                "repo": repo,
                "delegated_at": time.time(),
            },
        )

        logger.info(
            "Delegated to %s (trust=%.2f): '%s' (priority=%d)",
            best.agent_id,
            best.trust,
            title,
            priority,
        )

        # Suspend current task if we know it — mark BLOCKED so KARMA skips it.
        # The task resumes when OP_TASK_COMPLETED arrives via federation.
        from steward.services import SVC_TASK_MANAGER

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is not None and _current_task_id:
            from vibe_core.task_types import TaskStatus

            task_mgr.update_task(
                _current_task_id,
                status=TaskStatus.BLOCKED,
                description=f"delegated:{title}|peer:{best.agent_id}",
            )
            logger.info(
                "Task %s suspended (BLOCKED) — waiting for %s",
                _current_task_id,
                best.agent_id,
            )

        return ToolResult(
            success=True,
            output=f"Delegated to {best.agent_id} (trust={best.trust:.2f}): {title}. Task suspended — will resume on peer callback.",
            metadata={
                "peer_id": best.agent_id,
                "peer_trust": best.trust,
                "title": title,
                "priority": priority,
                "task_suspended": True,
            },
        )
