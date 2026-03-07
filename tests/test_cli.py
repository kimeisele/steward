"""Tests for CLI entry point."""

from __future__ import annotations

from steward.__main__ import _format_event
from steward.types import AgentEvent, ToolUse
from vibe_core.tools.tool_protocol import ToolResult


class TestCLIFormatting:
    def test_format_text_event(self, capsys):
        _format_event(AgentEvent(type="text", content="Hello world"))
        captured = capsys.readouterr()
        assert "Hello world" in captured.out

    def test_format_tool_call_event(self, capsys):
        tu = ToolUse(id="c1", name="bash", parameters={"command": "echo hi"})
        _format_event(AgentEvent(type="tool_call", tool_use=tu))
        captured = capsys.readouterr()
        assert "bash" in captured.out
        assert "echo hi" in captured.out

    def test_format_tool_result_success(self, capsys):
        result = ToolResult(success=True, output="file contents")
        _format_event(AgentEvent(type="tool_result", content=result))
        captured = capsys.readouterr()
        assert "file contents" in captured.out

    def test_format_tool_result_error(self, capsys):
        result = ToolResult(success=False, error="file not found")
        _format_event(AgentEvent(type="tool_result", content=result))
        captured = capsys.readouterr()
        assert "file not found" in captured.out

    def test_format_error_event(self, capsys):
        _format_event(AgentEvent(type="error", content="something broke"))
        captured = capsys.readouterr()
        assert "something broke" in captured.err

    def test_format_done_event(self, capsys):
        """Done event produces no output."""
        _format_event(AgentEvent(type="done"))
        captured = capsys.readouterr()
        assert captured.out == ""
