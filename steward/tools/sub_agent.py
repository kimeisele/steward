"""
Sub-Agent Tool — Task delegation via child AgentLoop.

Spawns a fresh AgentLoop with clean context to handle a sub-task.
The key value: context isolation — the child gets a fresh conversation
window, preventing parent context bloat on focused sub-tasks.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from steward.buddhi import Buddhi
from steward.loop.engine import AgentLoop
from steward.services import (
    SVC_ATTENTION,
    SVC_MEMORY,
    SVC_PROVIDER,
    SVC_SAFETY_GUARD,
    SVC_TOOL_REGISTRY,
)
from steward.types import Conversation, EventType
from vibe_core.di import ServiceRegistry
from vibe_core.tools.tool_protocol import Tool, ToolResult
from vibe_core.tools.tool_registry import ToolRegistry

logger = logging.getLogger("STEWARD.TOOL.SUBAGENT")

# Sub-agent timeout (seconds) — prevents runaway child loops
SUB_AGENT_TIMEOUT = 300  # 5 minutes

# Sub-agent context window (tokens) — smaller than parent
SUB_AGENT_MAX_CONTEXT = 50_000

# Sub-agent max output tokens per LLM call
SUB_AGENT_MAX_OUTPUT = 4096


class SubAgentTool(Tool):
    """Spawn a sub-agent to handle a focused sub-task.

    Creates a fresh AgentLoop with clean context. The child agent
    inherits the parent's tools (minus sub_agent to prevent recursion)
    and governance infrastructure (safety guard, attention, memory).
    """

    def __init__(self, cwd: str | None = None, timeout: int = SUB_AGENT_TIMEOUT) -> None:
        super().__init__()
        self._cwd = cwd
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "sub_agent"

    @property
    def description(self) -> str:
        return (
            "Delegate a sub-task to a focused sub-agent with clean context. "
            "Use when the current context is too large, when a task needs "
            "focused attention, or when you want to isolate a sub-task."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "task": {
                "type": "string",
                "required": True,
                "description": "The task for the sub-agent to complete",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if "task" not in parameters:
            raise ValueError("Missing required parameter: task")
        if not isinstance(parameters["task"], str):
            raise TypeError("task must be a string")
        if not parameters["task"].strip():
            raise ValueError("task must not be empty")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        task = parameters["task"]

        # Pull services from DI (booted by the time execute runs)
        provider = ServiceRegistry.get(SVC_PROVIDER)
        if provider is None:
            return ToolResult(success=False, error="No provider available for sub-agent")

        parent_registry: ToolRegistry | None = ServiceRegistry.get(SVC_TOOL_REGISTRY)

        # Build child ToolRegistry — all parent tools minus sub_agent
        child_registry = self._build_child_registry(parent_registry)

        # Fresh conversation (clean context — the key value of sub-agent)
        conversation = Conversation(max_tokens=SUB_AGENT_MAX_CONTEXT)

        # Fresh Buddhi (new phase machine for the sub-task)
        buddhi = Buddhi()

        # Reuse parent's governance infrastructure
        safety_guard = ServiceRegistry.get(SVC_SAFETY_GUARD)
        attention = ServiceRegistry.get(SVC_ATTENTION)
        memory = ServiceRegistry.get(SVC_MEMORY)

        # Generic system prompt
        cwd_str = self._cwd or "."
        tools_list = ", ".join(child_registry.list_tools())
        system_prompt = (
            "You are a focused sub-agent handling a specific task. "
            "Complete the task efficiently and return a clear result.\n"
            f"Working directory: {cwd_str}\n"
            f"Available tools: {tools_list}"
        )

        loop = AgentLoop(
            provider=provider,
            registry=child_registry,
            conversation=conversation,
            system_prompt=system_prompt,
            max_tokens=SUB_AGENT_MAX_OUTPUT,
            safety_guard=safety_guard,
            attention=attention,
            memory=memory,
            buddhi=buddhi,
        )

        try:
            ok, result_text = asyncio.run(
                asyncio.wait_for(
                    self._run_loop(loop, task),
                    timeout=self._timeout,
                )
            )
            rounds = buddhi.stats.get("total_evaluations", 0)

            if not ok:
                logger.warning("Sub-agent error: %s", result_text)
                return ToolResult(
                    success=False,
                    error=f"Sub-agent error: {result_text}",
                    metadata={"sub_agent_rounds": rounds},
                )
            logger.info("Sub-agent completed (rounds=%d)", rounds)
            return ToolResult(
                success=True,
                output=result_text or "[sub-agent completed with no output]",
                metadata={"sub_agent_rounds": rounds},
            )
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=f"Sub-agent timed out after {self._timeout}s",
            )
        except Exception as e:
            logger.exception("Sub-agent crashed")
            return ToolResult(
                success=False,
                error=f"Sub-agent failed: {type(e).__name__}: {e}",
            )

    def _build_child_registry(self, parent_registry: ToolRegistry | None) -> ToolRegistry:
        """Build tool registry for child agent — all parent tools minus sub_agent."""
        child_registry = ToolRegistry()
        if parent_registry is None:
            return child_registry

        for tool_name, tool in parent_registry.tools.items():
            if tool_name == self.name:
                continue  # prevent recursion
            child_registry.register(tool)

        return child_registry

    @staticmethod
    async def _run_loop(loop: AgentLoop, task: str) -> tuple[bool, str]:
        """Run the child AgentLoop and collect the final text.

        Returns (success, text) — success=False if the child loop errored.
        """
        final_text = ""
        chunks: list[str] = []
        async for event in loop.run(task):
            if event.type == EventType.TEXT_DELTA:
                chunks.append(str(event.content) if event.content else "")
            elif event.type == EventType.TEXT:
                final_text = str(event.content) if event.content else ""
            elif event.type == EventType.ERROR:
                return False, str(event.content)
        text = "".join(chunks) if chunks else final_text
        return True, text
