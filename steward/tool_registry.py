"""
Tool Registry — Maps tool names to Tool instances.

Uses steward-protocol's Tool ABC, ToolCall, ToolResult directly.
No reinvention — just the registry + execution dispatch.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolCall, ToolResult

logger = logging.getLogger("STEWARD.TOOLS")


class ToolRegistry:
    """Registry of available tools, keyed by name.

    Responsibilities:
    1. Register Tool instances
    2. Look up tools by name
    3. Validate + execute ToolCalls
    4. Generate LLM-friendly tool descriptions
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Overwrites if name already exists."""
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def execute(self, name: str, parameters: dict[str, Any], call_id: str | None = None) -> ToolResult:
        """Validate and execute a tool call.

        Returns ToolResult (never raises).
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(success=False, error=f"Unknown tool: {name}")

        if call_id is None:
            call_id = f"call_{uuid.uuid4().hex[:8]}"

        try:
            tool.validate(parameters)
        except (ValueError, TypeError) as e:
            return ToolResult(success=False, error=f"Validation failed: {e}")

        try:
            return tool.execute(parameters)
        except Exception as e:
            logger.error("Tool '%s' crashed: %s", name, e, exc_info=True)
            return ToolResult(success=False, error=f"Tool execution failed: {e}")

    def to_llm_tools(self) -> list[dict[str, Any]]:
        """Generate tool descriptions for LLM system prompt.

        Returns list of tool specs in the format expected by
        most LLM APIs (OpenAI/Anthropic tool_use format).
        """
        return [
            {
                "type": "function",
                "function": tool.to_llm_description(),
            }
            for tool in self._tools.values()
        ]

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
