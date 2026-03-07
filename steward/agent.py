"""
StewardAgent — The autonomous superagent.

This is the public API. Users create a StewardAgent, give it a task,
and it executes autonomously using the tool-use loop.

    agent = StewardAgent(provider=llm)
    response = agent.run("Fix the failing tests in src/")

The agent manages its own conversation, tools, and context window.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from steward.loop.engine import AgentLoop, LLMProvider
from steward.tool_registry import ToolRegistry
from steward.tools.bash import BashTool
from steward.tools.glob import GlobTool
from steward.tools.read_file import ReadFileTool
from steward.tools.write_file import WriteFileTool
from steward.types import Conversation

logger = logging.getLogger("STEWARD.AGENT")

DEFAULT_SYSTEM_PROMPT = """\
You are Steward, an autonomous software engineering agent.

You have access to tools for reading files, writing files, running commands,
and searching the codebase. Use them to complete the user's task.

Guidelines:
- Read files before modifying them
- Run tests after making changes
- Keep changes minimal and focused
- If something fails, diagnose the root cause before retrying
"""


class StewardAgent:
    """Autonomous agent that executes tasks using LLM + tools.

    Args:
        provider: LLM provider (anything with invoke(**kwargs) → response)
        system_prompt: System prompt for the agent
        cwd: Working directory for tools (default: current directory)
        max_context_tokens: Maximum context window size
        max_output_tokens: Maximum tokens per LLM response
        tools: Additional Tool instances to register
    """

    def __init__(
        self,
        provider: LLMProvider,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        cwd: str | None = None,
        max_context_tokens: int = 100_000,
        max_output_tokens: int = 4096,
        tools: list[Any] | None = None,
    ) -> None:
        self._provider = provider
        self._system_prompt = system_prompt
        self._cwd = cwd or str(Path.cwd())
        self._max_output_tokens = max_output_tokens

        # Initialize conversation
        self._conversation = Conversation(max_tokens=max_context_tokens)

        # Initialize tool registry with built-in tools
        self._registry = ToolRegistry()
        self._register_builtin_tools()

        # Register any additional tools
        if tools:
            for tool in tools:
                self._registry.register(tool)

        logger.info(
            "StewardAgent initialized (cwd=%s, tools=%s)",
            self._cwd, self._registry.tool_names,
        )

    def run(self, task: str) -> str:
        """Execute a task autonomously.

        The agent will use tools as needed until it produces a final
        text response. Returns the agent's response.
        """
        loop = AgentLoop(
            provider=self._provider,
            registry=self._registry,
            conversation=self._conversation,
            system_prompt=self._system_prompt,
            max_tokens=self._max_output_tokens,
        )
        return loop.run(task)

    def chat(self, message: str) -> str:
        """Continue an existing conversation.

        Same as run() but semantically indicates multi-turn usage.
        """
        return self.run(message)

    @property
    def conversation(self) -> Conversation:
        """Access the conversation history."""
        return self._conversation

    @property
    def registry(self) -> ToolRegistry:
        """Access the tool registry."""
        return self._registry

    def reset(self) -> None:
        """Clear conversation history (keeps system prompt)."""
        self._conversation = Conversation(max_tokens=self._conversation.max_tokens)
        logger.info("Conversation reset")

    def _register_builtin_tools(self) -> None:
        """Register the default tool set."""
        self._registry.register(BashTool(cwd=self._cwd))
        self._registry.register(ReadFileTool())
        self._registry.register(WriteFileTool())
        self._registry.register(GlobTool(cwd=self._cwd))
