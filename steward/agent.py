"""
StewardAgent — The autonomous superagent.

This is the public API. Users create a StewardAgent, give it a task,
and it executes autonomously using the tool-use loop.

    agent = StewardAgent(provider=llm)
    result = await agent.run("Fix the failing tests in src/")

    # Or synchronous:
    result = agent.run_sync("Fix the failing tests in src/")

The agent manages its own conversation, tools, and context window.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import AsyncIterator

from vibe_core.di import ServiceRegistry
from vibe_core.mahamantra.adapters.attention import MahaAttention
from vibe_core.runtime.tool_safety_guard import ToolSafetyGuard
from vibe_core.tools.tool_protocol import Tool
from vibe_core.tools.tool_registry import ToolRegistry

from vibe_core.protocols.memory import MemoryProtocol

from steward.loop.engine import AgentLoop
from steward.services import (
    SVC_ATTENTION,
    SVC_EVENT_BUS,
    SVC_MEMORY,
    SVC_PROMPT_CONTEXT,
    SVC_SAFETY_GUARD,
    SVC_SIGNAL_BUS,
    SVC_TOOL_REGISTRY,
    boot,
)
from steward.tools.bash import BashTool
from steward.tools.edit import EditTool
from steward.tools.glob import GlobTool
from steward.tools.grep import GrepTool
from steward.tools.read_file import ReadFileTool
from steward.tools.write_file import WriteFileTool
from steward.types import AgentEvent, Conversation, LLMProvider

logger = logging.getLogger("STEWARD.AGENT")

_BASE_SYSTEM_PROMPT = """\
You are Steward, an autonomous software engineering agent.

You have access to tools for reading files, writing files, running commands,
and searching the codebase. Use them to complete the user's task.

Guidelines:
- Read files before modifying them
- Run tests after making changes
- Keep changes minimal and focused
- If something fails, diagnose the root cause before retrying
- Use glob to find files, grep to search content, read_file before edit_file
"""


def _load_project_instructions(cwd: str) -> str | None:
    """Load project-specific instructions from the working directory.

    Looks for (in order):
    1. .steward/instructions.md
    2. CLAUDE.md

    Returns the file contents or None.
    """
    candidates = [
        Path(cwd) / ".steward" / "instructions.md",
        Path(cwd) / "CLAUDE.md",
    ]
    for path in candidates:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    logger.info("Loaded project instructions from %s", path)
                    return content
            except OSError as e:
                logger.warning("Failed to read %s: %s", path, e)
    return None


def _git_status_summary(cwd: str) -> str | None:
    """Get a short git status + diff summary for context.

    Returns None if not in a git repo or git is unavailable.
    """
    try:
        # Check if it's a git repo
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd, capture_output=True, check=True, timeout=5,
        )
        # Get short status
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=cwd, capture_output=True, text=True, timeout=5,
        )
        # Get diff stat
        diff = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=cwd, capture_output=True, text=True, timeout=5,
        )
        parts: list[str] = []
        if status.stdout.strip():
            # Limit to 20 lines
            lines = status.stdout.strip().split("\n")
            if len(lines) > 20:
                parts.append("\n".join(lines[:20]) + f"\n... ({len(lines) - 20} more)")
            else:
                parts.append("\n".join(lines))
        if diff.stdout.strip():
            parts.append(diff.stdout.strip())
        return "\n".join(parts) if parts else None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def _build_system_prompt(
    base: str,
    cwd: str,
    tool_names: list[str],
    dynamic_context: dict[str, str] | None = None,
    project_instructions: str | None = None,
    git_status: str | None = None,
) -> str:
    """Build system prompt with dynamic context.

    Injects working directory, tool list, project instructions,
    git status, and any PromptContext resolver values.
    """
    parts = [base.rstrip()]
    parts.append(f"\nWorking directory: {cwd}")
    parts.append(f"Available tools: {', '.join(sorted(tool_names))}")

    if dynamic_context:
        parts.append("\nEnvironment:")
        for key, value in dynamic_context.items():
            if value and not value.startswith("["):
                parts.append(f"  {key}: {value}")

    if project_instructions:
        parts.append(f"\nProject Instructions:\n{project_instructions}")

    if git_status:
        parts.append(f"\nGit Status:\n{git_status}")

    return "\n".join(parts)


class StewardAgent:
    """Autonomous agent that executes tasks using LLM + tools.

    Args:
        provider: LLM provider (anything with invoke(**kwargs) -> response)
        system_prompt: System prompt for the agent
        cwd: Working directory for tools (default: current directory)
        max_context_tokens: Maximum context window size
        max_output_tokens: Maximum tokens per LLM response
        tools: Additional Tool instances to register
    """

    def __init__(
        self,
        provider: LLMProvider,
        system_prompt: str | None = None,
        cwd: str | None = None,
        max_context_tokens: int = 100_000,
        max_output_tokens: int = 4096,
        tools: list[Tool] | None = None,
    ) -> None:
        self._provider = provider
        self._cwd = cwd or str(Path.cwd())
        self._max_output_tokens = max_output_tokens

        # Initialize conversation
        self._conversation = Conversation(max_tokens=max_context_tokens)

        # Build tool list
        builtin_tools = self._builtin_tools()
        all_tools = builtin_tools + (tools or [])

        # Boot services (wires ToolRegistry, SafetyGuard, MahaAttention, Memory, EventBus)
        boot(tools=all_tools, provider=provider, cwd=self._cwd)

        # Pull services from DI
        self._registry: ToolRegistry = ServiceRegistry.require(SVC_TOOL_REGISTRY)
        self._safety_guard: ToolSafetyGuard = ServiceRegistry.require(SVC_SAFETY_GUARD)
        self._attention: MahaAttention = ServiceRegistry.require(SVC_ATTENTION)
        self._memory: MemoryProtocol = ServiceRegistry.require(SVC_MEMORY)

        # Build system prompt (with dynamic context if not custom)
        if system_prompt is not None:
            self._system_prompt = system_prompt
        else:
            dynamic_ctx = self._resolve_dynamic_context()
            project_ctx = _load_project_instructions(self._cwd)
            git_ctx = _git_status_summary(self._cwd)
            self._system_prompt = _build_system_prompt(
                _BASE_SYSTEM_PROMPT, self._cwd, self._registry.list_tools(),
                dynamic_context=dynamic_ctx,
                project_instructions=project_ctx,
                git_status=git_ctx,
            )

        # Emit AGENT_STARTUP signal
        self._emit_startup_signal()

        logger.info(
            "StewardAgent initialized (cwd=%s, tools=%s)",
            self._cwd, self._registry.list_tools(),
        )

    async def run(self, task: str) -> str:
        """Execute a task autonomously (async).

        The agent will use tools as needed until it produces a final
        text response. Returns the agent's response.
        """
        final_text = ""
        async for event in self.run_stream(task):
            if event.type == "text":
                final_text = str(event.content) if event.content else ""
            elif event.type == "error":
                return f"[Error: {event.content}]"
        return final_text

    def run_sync(self, task: str) -> str:
        """Execute a task autonomously (sync wrapper).

        Convenience method for simple usage and testing.
        """
        return asyncio.run(self.run(task))

    async def chat(self, message: str) -> str:
        """Continue an existing conversation (async)."""
        return await self.run(message)

    def chat_sync(self, message: str) -> str:
        """Continue an existing conversation (sync wrapper)."""
        return self.run_sync(message)

    async def run_stream(self, task: str) -> AsyncIterator[AgentEvent]:
        """Execute a task and yield events as they happen.

        Emits to both SignalBus (simple) and EventBus (full Narada stream).
        Passes Memory to AgentLoop for cross-turn file tracking.
        """
        loop = AgentLoop(
            provider=self._provider,
            registry=self._registry,
            conversation=self._conversation,
            system_prompt=self._system_prompt,
            max_tokens=self._max_output_tokens,
            safety_guard=self._safety_guard,
            attention=self._attention,
            memory=self._memory,
        )
        async for event in loop.run(task):
            self._emit_signal(event)
            self._emit_event_bus(event)
            yield event

    def _emit_startup_signal(self) -> None:
        """Emit AGENT_STARTUP signal when agent is created."""
        from vibe_core.steward.bus import Signal, SignalType

        bus = ServiceRegistry.get(SVC_SIGNAL_BUS)
        if bus is None:
            return
        bus.emit(Signal(
            signal_type=SignalType.AGENT_STARTUP,
            source_agent="steward",
            payload={"tools": self._registry.list_tools(), "cwd": self._cwd},
        ))

    def _emit_signal(self, event: AgentEvent) -> None:
        """Translate AgentEvent to SignalBus signal (fire-and-forget)."""
        from vibe_core.steward.bus import Signal, SignalType

        bus = ServiceRegistry.get(SVC_SIGNAL_BUS)
        if bus is None:
            return

        if event.type == "tool_call":
            bus.emit(Signal(
                signal_type=SignalType.AGENT_STATUS_UPDATE,
                source_agent="steward",
                payload={
                    "action": "tool_call",
                    "tool": event.tool_use.name if event.tool_use else "",
                },
            ))
        elif event.type == "tool_result":
            success = False
            if event.content and hasattr(event.content, "success"):
                success = event.content.success  # type: ignore[union-attr]
            bus.emit(Signal(
                signal_type=SignalType.AGENT_STATUS_UPDATE,
                source_agent="steward",
                payload={"action": "tool_result", "success": success},
            ))
        elif event.type == "error":
            bus.emit(Signal(
                signal_type=SignalType.AGENT_ERROR,
                source_agent="steward",
                payload={"error": str(event.content)},
            ))
        elif event.type == "done":
            payload: dict[str, object] = {"action": "turn_complete"}
            if event.usage:
                payload["tokens"] = event.usage.total_tokens
                payload["tool_calls"] = event.usage.tool_calls
            bus.emit(Signal(
                signal_type=SignalType.AGENT_STATUS_UPDATE,
                source_agent="steward",
                payload=payload,
            ))

    def _emit_event_bus(self, event: AgentEvent) -> None:
        """Emit to real EventBus (Narada stream) for observability."""
        from vibe_core.mahamantra.substrate.event_types import EventType

        event_bus = ServiceRegistry.get(SVC_EVENT_BUS)
        if event_bus is None:
            return

        if event.type == "tool_call":
            event_bus.emit_sync(
                event_type=EventType.ACTION,
                agent_id="steward",
                message=f"tool_call: {event.tool_use.name}" if event.tool_use else "tool_call",
            )
        elif event.type == "tool_result":
            success = False
            if event.content and hasattr(event.content, "success"):
                success = event.content.success  # type: ignore[union-attr]
            event_bus.emit_sync(
                event_type=EventType.ACTION if success else EventType.ERROR,
                agent_id="steward",
                message=f"tool_result: {'ok' if success else 'error'}",
            )
        elif event.type == "error":
            event_bus.emit_sync(
                event_type=EventType.ERROR,
                agent_id="steward",
                message=f"error: {event.content}",
            )
        elif event.type == "text":
            event_bus.emit_sync(
                event_type=EventType.THOUGHT,
                agent_id="steward",
                message="text_response",
            )

    def _resolve_dynamic_context(self) -> dict[str, str] | None:
        """Resolve dynamic context from PromptContext (git, time, etc.)."""
        prompt_ctx = ServiceRegistry.get(SVC_PROMPT_CONTEXT)
        if prompt_ctx is None:
            return None
        try:
            return prompt_ctx.resolve(["current_branch", "system_time"])
        except Exception:
            logger.debug("PromptContext resolve failed, skipping dynamic context")
            return None

    @property
    def conversation(self) -> Conversation:
        """Access the conversation history."""
        return self._conversation

    @property
    def registry(self) -> ToolRegistry:
        """Access the tool registry."""
        return self._registry

    @property
    def memory(self) -> MemoryProtocol:
        """Access the agent memory."""
        return self._memory

    def reset(self) -> None:
        """Clear conversation history, safety guard, and session memory."""
        self._conversation = Conversation(max_tokens=self._conversation.max_tokens)
        self._safety_guard.reset_session()
        self._memory.clear_session("steward")
        logger.info("Conversation reset")

    def _builtin_tools(self) -> list[Tool]:
        """Build the default tool set."""
        return [
            BashTool(cwd=self._cwd),
            ReadFileTool(),
            WriteFileTool(),
            GlobTool(cwd=self._cwd),
            EditTool(),
            GrepTool(cwd=self._cwd),
        ]
