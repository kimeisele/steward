"""
Glob Tool — Find files by pattern.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolResult


class GlobTool(Tool):
    """Find files matching a glob pattern."""

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self._cwd = Path(cwd) if cwd else Path.cwd()

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts'). "
            "Returns matching file paths sorted by modification time."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "pattern": {
                "type": "string",
                "required": True,
                "description": "Glob pattern to match files (e.g. '**/*.py')",
            },
            "path": {
                "type": "string",
                "required": False,
                "description": "Directory to search in (default: working directory)",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if "pattern" not in parameters:
            raise ValueError("Missing required parameter: pattern")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        pattern = parameters["pattern"]
        search_dir = Path(parameters.get("path", self._cwd)).expanduser()

        if not search_dir.is_dir():
            return ToolResult(success=False, error=f"Not a directory: {search_dir}")

        try:
            matches = sorted(
                search_dir.glob(pattern),
                key=lambda p: p.stat().st_mtime if p.exists() else 0,
                reverse=True,
            )
            # Filter to files only, limit to 1000
            files = [str(p) for p in matches if p.is_file()][:1000]
            return ToolResult(
                success=True,
                output="\n".join(files) if files else "No matches found.",
                metadata={"match_count": len(files)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
