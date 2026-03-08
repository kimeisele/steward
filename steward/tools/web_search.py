"""
Web Search Tool — Search the internet via Tavily API.

Gives the agent eyes on the web. Can search for documentation,
current events, technical references, error solutions, etc.

Requires: TAVILY_API_KEY environment variable.
Install: pip install tavily-python
"""

from __future__ import annotations

import logging
import os
from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolResult

logger = logging.getLogger("STEWARD.TOOL.SEARCH")

_MAX_RESULTS = 5


class WebSearchTool(Tool):
    """Search the web for information, documentation, and solutions.

    Uses Tavily API for high-quality search results optimized for AI agents.
    Returns structured results with titles, URLs, and content snippets.
    """

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for information. Use for finding documentation, "
            "error solutions, API references, current events, or any information "
            "not available in the local codebase. Returns titles, URLs, and "
            "content snippets from the top results."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "query": {
                "type": "string",
                "required": True,
                "description": "The search query",
            },
            "max_results": {
                "type": "integer",
                "required": False,
                "description": f"Maximum number of results to return (default: {_MAX_RESULTS})",
            },
            "search_depth": {
                "type": "string",
                "required": False,
                "description": "Search depth: 'basic' (fast) or 'advanced' (thorough, default: basic)",
            },
            "include_answer": {
                "type": "boolean",
                "required": False,
                "description": "Include AI-generated answer summary (default: true)",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if "query" not in parameters:
            raise ValueError("Missing required parameter: query")
        if not isinstance(parameters["query"], str):
            raise TypeError("query must be a string")
        if not parameters["query"].strip():
            raise ValueError("query must not be empty")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return ToolResult(
                success=False,
                error="TAVILY_API_KEY not set. Cannot search the web.",
            )

        query = parameters["query"]
        max_results = min(int(parameters.get("max_results", _MAX_RESULTS)), 10)
        search_depth = parameters.get("search_depth", "basic")
        include_answer = parameters.get("include_answer", True)

        try:
            from tavily import TavilyClient

            client = TavilyClient(api_key=api_key)
            response = client.search(
                query=query,
                max_results=max_results,
                search_depth=search_depth,
                include_answer=include_answer,
            )

            # Format results
            parts: list[str] = []

            # AI answer summary (if available)
            answer = response.get("answer")
            if answer:
                parts.append(f"**Summary:** {answer}\n")

            # Individual results
            results = response.get("results", [])
            for i, r in enumerate(results, 1):
                title = r.get("title", "")
                url = r.get("url", "")
                content = r.get("content", "")
                # Truncate content to 500 chars
                if len(content) > 500:
                    content = content[:500] + "..."
                parts.append(f"[{i}] {title}\n    {url}\n    {content}\n")

            if not parts:
                return ToolResult(
                    success=True,
                    output="No results found.",
                    metadata={"result_count": 0},
                )

            return ToolResult(
                success=True,
                output="\n".join(parts),
                metadata={
                    "result_count": len(results),
                    "query": query,
                    "search_depth": search_depth,
                },
            )

        except ImportError:
            return ToolResult(
                success=False,
                error="tavily-python not installed. Run: pip install tavily-python",
            )
        except Exception as e:
            logger.warning("Web search failed: %s", e)
            return ToolResult(success=False, error=f"Search failed: {e}")
