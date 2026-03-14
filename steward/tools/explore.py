"""
Explore Tool — Thin Tool wrapper over the MOLECULAR ExploreCapability.

The Tool interface is what the LLM sees. The Capability is what runs.
This separation keeps Tool (protocol for LLM) and Capability (protocol
for infrastructure) cleanly separated per OPUS-307.
"""

from __future__ import annotations

from typing import Any

from steward.capabilities.explore import ExploreCapability
from vibe_core.tools.tool_protocol import Tool, ToolResult


class ExploreTool(Tool):
    """Explore a codebase via AST + KnowledgeGraph + Guna classification."""

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self._cwd = cwd or "."
        self._capability = ExploreCapability()

    @property
    def name(self) -> str:
        return "explore"

    @property
    def description(self) -> str:
        return self._capability.description

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "target": {
                "type": "string",
                "required": False,
                "description": "Directory to explore (default: working directory)",
            },
            "focus": {
                "type": "string",
                "required": False,
                "description": "What to focus on (e.g. 'federation', 'healer'). Empty = full scan.",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if "target" not in parameters:
            parameters["target"] = self._cwd

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        if "target" not in parameters:
            parameters["target"] = self._cwd

        result = self._capability.execute(parameters)
        return ToolResult(
            success=result.success,
            output=str(result.output) if result.output else "",
            error=result.error or "",
            metadata=dict(result.metadata) if result.metadata else {},
        )
