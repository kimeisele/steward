"""
Grep Tool — Content search via regex patterns.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolResult


class GrepTool(Tool):
    """Search file contents for a regex pattern."""

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self._cwd = Path(cwd) if cwd else Path.cwd()

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "Search file contents for a regex pattern. Returns matching lines with file path and line number."

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "pattern": {
                "type": "string",
                "required": True,
                "description": "Regex pattern to search for",
            },
            "path": {
                "type": "string",
                "required": False,
                "description": "File or directory to search (default: working directory)",
            },
            "glob": {
                "type": "string",
                "required": False,
                "description": "Glob pattern to filter files (e.g. '*.py')",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if "pattern" not in parameters:
            raise ValueError("Missing required parameter: pattern")
        try:
            re.compile(parameters["pattern"])
        except re.error as e:
            raise ValueError(f"Invalid regex: {e}")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        pattern = parameters["pattern"]
        search_path = Path(parameters.get("path", self._cwd)).expanduser()
        file_glob = parameters.get("glob", "**/*")

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolResult(success=False, error=f"Invalid regex: {e}")

        matches: list[str] = []
        max_matches = 500

        try:
            if search_path.is_file():
                files = [search_path]
            elif search_path.is_dir():
                files = sorted(search_path.glob(file_glob))
            else:
                return ToolResult(success=False, error=f"Path not found: {search_path}")

            for fpath in files:
                if not fpath.is_file():
                    continue
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except (OSError, UnicodeDecodeError):
                    continue

                for line_num, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        matches.append(f"{fpath}:{line_num}: {line.rstrip()}")
                        if len(matches) >= max_matches:
                            break
                if len(matches) >= max_matches:
                    break

            if not matches:
                return ToolResult(
                    success=True,
                    output="No matches found.",
                    metadata={"match_count": 0},
                )

            return ToolResult(
                success=True,
                output="\n".join(matches),
                metadata={"match_count": len(matches)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
