"""
Edit Tool — Diff-based file editing via exact string replacement.

ToolSafetyGuard enforced: the file must be read before editing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolResult


class EditTool(Tool):
    """Replace an exact string in a file with a new string."""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Edit a file by replacing an exact string with new content. "
            "The old_string must appear exactly once in the file. "
            "You must read the file before editing it."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "path": {
                "type": "string",
                "required": True,
                "description": "Path to the file to edit",
            },
            "old_string": {
                "type": "string",
                "required": True,
                "description": "The exact string to find and replace",
            },
            "new_string": {
                "type": "string",
                "required": True,
                "description": "The replacement string",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        for key in ("path", "old_string", "new_string"):
            if key not in parameters:
                raise ValueError(f"Missing required parameter: {key}")
        if parameters["old_string"] == parameters["new_string"]:
            raise ValueError("old_string and new_string must be different")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        path = Path(parameters["path"]).expanduser()
        old_string = parameters["old_string"]
        new_string = parameters["new_string"]

        if not path.exists():
            return ToolResult(success=False, error=f"File not found: {path}")
        if not path.is_file():
            return ToolResult(success=False, error=f"Not a file: {path}")

        try:
            content = path.read_text(encoding="utf-8")

            count = content.count(old_string)
            if count == 0:
                return ToolResult(
                    success=False,
                    error="old_string not found in file",
                )
            if count > 1:
                return ToolResult(
                    success=False,
                    error=f"old_string found {count} times (must be unique). "
                    "Provide more surrounding context to make it unique.",
                )

            new_content = content.replace(old_string, new_string, 1)
            path.write_text(new_content, encoding="utf-8")

            return ToolResult(
                success=True,
                output=f"Edited {path}",
                metadata={"path": str(path)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
