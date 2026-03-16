"""
annotate — Agent-facing tool for contributing validated knowledge.

Agents call this tool when they discover something important about the
codebase that future agents should know. The submission goes through
steward's neuro-symbolic validation pipeline:

  MahaCompression (dedup) → North Star (alignment) → PersistentMemory (Hebbian)

Only validated, aligned, non-duplicate knowledge gets stored.
On the next CLAUDE.md generation, validated annotations are included.

Example:
  annotate(
      text="ProviderChamber circuit breaker resets on boot",
      category="gotcha",
      file_ref="steward/provider/chamber.py:163",
  )
"""

from __future__ import annotations

import logging
from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolResult

logger = logging.getLogger("STEWARD.TOOLS.ANNOTATE")


class AnnotateTool(Tool):
    """Contribute validated knowledge to steward's briefing pipeline."""

    @property
    def name(self) -> str:
        return "annotate"

    @property
    def description(self) -> str:
        return (
            "Submit knowledge about this codebase for future agents. "
            "Goes through validation: alignment check, dedup, Hebbian tracking. "
            "Only validated knowledge appears in CLAUDE.md."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "text": {
                "type": "string",
                "required": True,
                "description": (
                    "The knowledge to contribute (max 500 chars). Be specific and actionable, not philosophical."
                ),
            },
            "category": {
                "type": "string",
                "required": True,
                "enum": ["invariant", "gotcha", "pattern", "decision", "warning"],
                "description": (
                    "invariant=must never change, gotcha=bites you if you don't know, "
                    "pattern=recurring design pattern, decision=architectural choice, "
                    "warning=active issue or fragile area"
                ),
            },
            "file_ref": {
                "type": "string",
                "required": False,
                "description": "Optional file:line reference (e.g., steward/services.py:172)",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if not parameters.get("text"):
            raise ValueError("text is required")
        if parameters.get("category") not in ("invariant", "gotcha", "pattern", "decision", "warning"):
            raise ValueError("category must be one of: invariant, gotcha, pattern, decision, warning")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        from steward.annotations import submit

        text = parameters["text"]
        category = parameters["category"]
        file_ref = parameters.get("file_ref", "")

        # Source: derive from current session context
        source = _get_source()

        result = submit(
            text=text,
            category=category,
            source=source,
            file_ref=file_ref,
        )

        if result.accepted:
            return ToolResult(
                success=True,
                output=(
                    f"Knowledge accepted (id={result.annotation_id}, "
                    f"alignment={result.alignment:.2f}). "
                    f"Will appear in next CLAUDE.md generation."
                ),
                metadata={
                    "annotation_id": result.annotation_id,
                    "alignment": result.alignment,
                },
            )
        else:
            detail = result.reason
            if result.similar_to:
                detail += f" (existing: {result.similar_to})"
            return ToolResult(
                success=False,
                error=f"Rejected: {detail}",
                metadata={
                    "annotation_id": result.annotation_id,
                    "alignment": result.alignment,
                    "similar_to": result.similar_to,
                },
            )


def _get_source() -> str:
    """Derive source identifier from the current agent context."""
    try:
        import os

        # Use session ID or agent identity if available
        session = os.environ.get("STEWARD_SESSION_ID", "")
        if session:
            return f"agent-{session[:8]}"
    except Exception:
        pass

    return f"agent-{id(object()):x}"[:16]
