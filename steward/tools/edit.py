"""
Edit Tool — Diff-based file editing via exact string replacement.

ToolSafetyGuard enforced: the file must be read before editing.
Post-edit: .py files are syntax-checked via ast.parse(). If broken,
the edit is reverted and the syntax error is returned to the LLM.
"""

from __future__ import annotations

import ast
import re
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
                # Whitespace-normalized fallback (protocol lesson: reduces LLM retry loops)
                fallback = self._whitespace_fallback(content, old_string, new_string)
                if fallback is not None:
                    syntax_err = self._check_syntax(path, fallback, content)
                    if syntax_err:
                        return ToolResult(
                            success=False,
                            error=f"Edit would break syntax: {syntax_err}. File NOT modified.",
                        )
                    path.write_text(fallback, encoding="utf-8")
                    return ToolResult(
                        success=True,
                        output=f"Edited {path} (whitespace-normalized match)",
                        metadata={"path": str(path), "whitespace_fallback": True},
                    )
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

            syntax_err = self._check_syntax(path, new_content, content)
            if syntax_err:
                return ToolResult(
                    success=False,
                    error=f"Edit would break syntax: {syntax_err}. File NOT modified.",
                )

            path.write_text(new_content, encoding="utf-8")

            return ToolResult(
                success=True,
                output=f"Edited {path}",
                metadata={"path": str(path)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    @staticmethod
    def _check_syntax(path: Path, new_content: str, old_content: str | None = None) -> str | None:
        """Check Python syntax after edit. Returns error string or None if ok.

        Only checks .py files. Other file types pass through unchecked.
        Only rejects edits that INTRODUCE syntax errors — if the original
        content was already broken, the edit is allowed (agent may be fixing it).
        """
        if path.suffix != ".py":
            return None
        try:
            ast.parse(new_content, filename=str(path))
            return None
        except SyntaxError as e:
            # New content is broken — but was the old content also broken?
            if old_content is not None:
                try:
                    ast.parse(old_content, filename=str(path))
                except SyntaxError:
                    return None  # Original was already broken — don't block repair attempts
            return f"{e.msg} (line {e.lineno})"

    @staticmethod
    def _whitespace_fallback(content: str, old_string: str, new_string: str) -> str | None:
        """Try matching with flexible whitespace when exact match fails.

        Turns old_string into a regex where whitespace runs match any whitespace.
        Only succeeds if there's exactly one match (uniqueness preserved).

        Protocol lesson from steward-protocol file_tools: reduce expensive
        LLM retry loops when the only difference is indentation/spacing.
        """
        # Split into whitespace and non-whitespace segments
        parts = re.split(r"(\s+)", old_string)
        if not any(p.strip() for p in parts):
            return None  # All whitespace — can't match meaningfully

        pattern_parts = []
        for part in parts:
            if not part:
                continue
            if part.isspace():
                pattern_parts.append(r"\s+")
            else:
                pattern_parts.append(re.escape(part))

        pattern = "".join(pattern_parts)
        matches = list(re.finditer(pattern, content))
        if len(matches) != 1:
            return None  # No match or ambiguous — don't guess

        m = matches[0]
        return content[: m.start()] + new_string + content[m.end() :]
