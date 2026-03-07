"""
Write File Tool — Write or overwrite file contents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolResult


class WriteFileTool(Tool):
    """Write content to a file, creating parent directories if needed."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file. Creates the file if it doesn't exist, "
            "overwrites if it does. Creates parent directories as needed."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "path": {
                "type": "string",
                "required": True,
                "description": "Path to the file to write",
            },
            "content": {
                "type": "string",
                "required": True,
                "description": "Content to write to the file",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if "path" not in parameters:
            raise ValueError("Missing required parameter: path")
        if "content" not in parameters:
            raise ValueError("Missing required parameter: content")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        path = Path(parameters["path"]).expanduser()
        content = parameters["content"]

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult(
                success=True,
                output=f"Wrote {len(content)} bytes to {path}",
                metadata={"bytes_written": len(content)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
