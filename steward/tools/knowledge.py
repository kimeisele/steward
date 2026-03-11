"""
Knowledge Graph Tool — pull-based codebase understanding.

The agent queries the KnowledgeGraph on demand, paying tokens only
when it actively needs codebase context. No prompt injection.

Replaces the old push pattern (_get_kg_context → system prompt)
with a tool the LLM calls when it needs structural info.
"""

from __future__ import annotations

import json
from typing import Any

from vibe_core.di import ServiceRegistry
from vibe_core.tools.tool_protocol import Tool, ToolResult


class KnowledgeGraphTool(Tool):
    """Query the codebase knowledge graph for module/class/function info."""

    @property
    def name(self) -> str:
        return "query_codebase"

    @property
    def description(self) -> str:
        return (
            "Query the codebase knowledge graph. Returns modules, classes, "
            "functions, and their relationships for a given concept. "
            "Use before editing unfamiliar code."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "query": {
                "type": "string",
                "required": True,
                "description": "Concept to search for (e.g. 'authentication', 'database', 'api routes')",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if "query" not in parameters:
            raise ValueError("Missing required parameter: query")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        from steward.services import SVC_KNOWLEDGE_GRAPH

        kg = ServiceRegistry.get(SVC_KNOWLEDGE_GRAPH)
        if kg is None:
            return ToolResult(
                success=True,
                output="Knowledge graph not available. Use grep/glob to explore the codebase.",
            )

        query = parameters["query"]
        try:
            context = kg.get_context_for_task(query)
            if not context:
                return ToolResult(
                    success=True,
                    output=f"No knowledge graph entries found for '{query}'. Use grep/glob instead.",
                )
            return ToolResult(
                success=True,
                output=json.dumps(context, indent=2, default=str),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Knowledge graph query failed: {e}")
