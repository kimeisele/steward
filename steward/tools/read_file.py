"""
Read File Tool — Read contents of a file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolResult


class ReadFileTool(Tool):
    """Read file contents with optional line range."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a file. Can optionally read a specific line range with offset and limit parameters."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "path": {
                "type": "string",
                "required": True,
                "description": "Absolute or relative path to the file",
            },
            "offset": {
                "type": "integer",
                "required": False,
                "description": "Line number to start reading from (1-based)",
            },
            "limit": {
                "type": "integer",
                "required": False,
                "description": "Maximum number of lines to read",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if "path" not in parameters:
            raise ValueError("Missing required parameter: path")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        path = Path(parameters["path"]).expanduser()
        offset = parameters.get("offset", 1)
        limit = parameters.get("limit", 2000)

        if not path.exists():
            return ToolResult(success=False, error=f"File not found: {path}")
        if not path.is_file():
            return ToolResult(success=False, error=f"Not a file: {path}")

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()

            # Apply offset (1-based) and limit
            start = max(0, offset - 1)
            end = start + limit
            selected = lines[start:end]

            # Format with line numbers
            numbered = []
            for i, line in enumerate(selected, start=start + 1):
                # Truncate long lines
                if len(line) > 2000:
                    line = line[:2000] + "... [truncated]"
                numbered.append(f"{i:6d}\t{line}")

            return ToolResult(
                success=True,
                output="\n".join(numbered),
                metadata={"total_lines": len(lines), "returned_lines": len(selected)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
