"""
Sub-Agent Tool — Seed-aware task delegation via child AgentLoop.

Spawns a fresh AgentLoop with clean context to handle a sub-task.
Queries the AgentDeck (Pokedex) for a specialized profile matching
the task seed or capability. Falls back to generic spawn if no match.

Learning: reports success/failure back to AgentDeck for Hebbian weight
updates. Proven profiles get reused; weak ones get evicted.
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

    If an AgentDeck is registered (SVC_AGENT_DECK), queries it for a
    specialized profile matching the task. The profile provides:
    - Custom system prompt (specialized instructions)
    - Tool filter (only relevant tools for the task)
    - Hebbian learning (success/failure feeds back to deck)

    Falls back to generic spawn if no deck or no matching card.
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
            "Delegate a sub-task to a specialized sub-agent. "
            "The agent is selected from the AgentDeck based on task seed "
            "or required capability. Use when the current context is too "
            "large, when a task needs focused attention, or when a "
            "specialized agent profile exists for the task type."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "task": {
                "type": "string",
                "required": True,
                "description": "The task for the sub-agent to complete",
            },
            "capability": {
                "type": "string",
                "required": False,
                "description": (
                    "Required capability (e.g., 'fix_tests', 'fix_lint', "
                    "'review_code', 'explore'). Routes to a specialized agent."
                ),
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
        capability = parameters.get("capability", "")

        # Pull services from DI (booted by the time execute runs)
        provider = ServiceRegistry.get(SVC_PROVIDER)
        if provider is None:
            return ToolResult(success=False, error="No provider available for sub-agent")

        parent_registry: ToolRegistry | None = ServiceRegistry.get(SVC_TOOL_REGISTRY)

        # Query AgentDeck for specialized profile
        card = self._resolve_card(task, capability)
        card_name = card.name if card else "generic"

        # Build child ToolRegistry — filtered by card or all minus sub_agent
        child_registry = self._build_child_registry(parent_registry, card)

        # Fresh conversation (clean context — the key value of sub-agent)
        conversation = Conversation(max_tokens=SUB_AGENT_MAX_CONTEXT)

        # Fresh Buddhi (new phase machine for the sub-task)
        buddhi = Buddhi()

        # Reuse parent's governance infrastructure
        safety_guard = ServiceRegistry.get(SVC_SAFETY_GUARD)
        attention = ServiceRegistry.get(SVC_ATTENTION)
        memory = ServiceRegistry.get(SVC_MEMORY)

        # System prompt: specialized (from card) or generic
        system_prompt = self._build_system_prompt(card, child_registry)

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

            # Learn from outcome — feed back to AgentDeck
            self._learn(card, success=ok)

            if not ok:
                logger.warning("Sub-agent '%s' error: %s", card_name, result_text)
                return ToolResult(
                    success=False,
                    error=f"Sub-agent error: {result_text}",
                    metadata={"sub_agent_rounds": rounds, "agent_card": card_name},
                )
            logger.info("Sub-agent '%s' completed (rounds=%d)", card_name, rounds)
            return ToolResult(
                success=True,
                output=result_text or "[sub-agent completed with no output]",
                metadata={"sub_agent_rounds": rounds, "agent_card": card_name},
            )
        except asyncio.TimeoutError:
            self._learn(card, success=False)
            return ToolResult(
                success=False,
                error=f"Sub-agent '{card_name}' timed out after {self._timeout}s",
                metadata={"agent_card": card_name},
            )
        except Exception as e:
            self._learn(card, success=False)
            return ToolResult(
                success=False,
                error=f"Sub-agent '{card_name}' failed: {type(e).__name__}: {e}",
                metadata={"agent_card": card_name},
            )

    def _resolve_card(self, task: str, capability: str) -> object | None:
        """Query AgentDeck for a matching card. Returns None if no deck or no match."""
        from steward.services import SVC_AGENT_DECK

        deck = ServiceRegistry.get(SVC_AGENT_DECK)
        if deck is None:
            return None

        # Try capability match first (explicit routing)
        if capability:
            card = deck.match(capability=capability)
            if card is not None:
                logger.info("DECK: routed to '%s' via capability '%s'", card.name, capability)
                return card

        # Try seed match (deterministic routing)
        try:
            from vibe_core.mahamantra.adapters.compression import MahaCompression

            mc = MahaCompression()
            seed = mc.compress(task).seed
            card = deck.match(seed=seed)
            if card is not None:
                logger.info("DECK: routed to '%s' via seed %d", card.name, seed)
                return card
        except Exception:
            pass

        return None

    def _build_child_registry(self, parent_registry: ToolRegistry | None, card: object | None) -> ToolRegistry:
        """Build filtered tool registry for child agent."""
        child_registry = ToolRegistry()
        if parent_registry is None:
            return child_registry

        tool_filter = set(card.tool_filter) if card and card.tool_filter else set()

        for tool_name, tool in parent_registry.tools.items():
            if tool_name == self.name:
                continue  # prevent recursion
            if tool_filter and tool_name not in tool_filter:
                continue  # card restricts tools
            child_registry.register(tool)

        return child_registry

    def _build_system_prompt(self, card: object | None, child_registry: ToolRegistry) -> str:
        """Build system prompt — specialized from card or generic."""
        cwd_str = self._cwd or "."
        tools_list = ", ".join(child_registry.list_tools())

        if card and card.system_prompt:
            return f"{card.system_prompt}\nWorking directory: {cwd_str}\nAvailable tools: {tools_list}"

        return (
            "You are a focused sub-agent handling a specific task. "
            "Complete the task efficiently and return a clear result.\n"
            f"Working directory: {cwd_str}\n"
            f"Available tools: {tools_list}"
        )

    @staticmethod
    def _learn(card: object | None, *, success: bool) -> None:
        """Report outcome back to AgentDeck for Hebbian learning."""
        if card is None:
            return
        from steward.services import SVC_AGENT_DECK

        deck = ServiceRegistry.get(SVC_AGENT_DECK)
        if deck is None:
            return
        deck.learn(card, success=success)

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
