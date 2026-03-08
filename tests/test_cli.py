"""Tests for CLI entry point."""

from __future__ import annotations

import json

from steward.__main__ import _format_event, _format_event_json, _tool_display
from steward.types import AgentEvent, AgentUsage, EventType, ToolUse
from vibe_core.tools.tool_protocol import ToolResult


class TestCLIFormatting:
    def test_format_text_event(self, capsys):
        _format_event(AgentEvent(type=EventType.TEXT, content="Hello world"))
        captured = capsys.readouterr()
        assert "Hello world" in captured.out

    def test_format_text_delta(self, capsys):
        _format_event(AgentEvent(type=EventType.TEXT_DELTA, content="chunk"))
        captured = capsys.readouterr()
        assert "chunk" in captured.out

    def test_format_tool_call_event(self, capsys):
        tu = ToolUse(id="c1", name="bash", parameters={"command": "echo hi"})
        _format_event(AgentEvent(type=EventType.TOOL_CALL, tool_use=tu))
        captured = capsys.readouterr()
        assert "bash" in captured.out
        assert "echo hi" in captured.out

    def test_format_tool_result_success(self, capsys):
        result = ToolResult(success=True, output="file contents")
        _format_event(AgentEvent(type=EventType.TOOL_RESULT, content=result))
        captured = capsys.readouterr()
        assert "file contents" in captured.out

    def test_format_tool_result_error(self, capsys):
        result = ToolResult(success=False, error="file not found")
        _format_event(AgentEvent(type=EventType.TOOL_RESULT, content=result))
        captured = capsys.readouterr()
        assert "file not found" in captured.out

    def test_format_error_event(self, capsys):
        _format_event(AgentEvent(type=EventType.ERROR, content="something broke"))
        captured = capsys.readouterr()
        assert "something broke" in captured.err

    def test_format_done_event(self, capsys):
        """Done event without usage produces no output."""
        _format_event(AgentEvent(type=EventType.DONE))
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_format_done_with_usage(self, capsys):
        """Done event with usage shows stats."""
        usage = AgentUsage(
            input_tokens=100, output_tokens=50,
            llm_calls=2, tool_calls=3, rounds=2,
            buddhi_action="IMPLEMENT", buddhi_guna="RAJAS",
            buddhi_phase="EXECUTE",
        )
        _format_event(AgentEvent(type=EventType.DONE, usage=usage))
        captured = capsys.readouterr()
        assert "100+50" in captured.out
        assert "IMPLEMENT" in captured.out


class TestToolDisplay:
    def test_file_path_display(self):
        assert _tool_display("read_file", {"path": "/src/main.py"}) == "/src/main.py"
        assert _tool_display("edit_file", {"path": "/a.py", "old": "x"}) == "/a.py"

    def test_bash_truncation(self):
        long_cmd = "x" * 100
        result = _tool_display("bash", {"command": long_cmd})
        assert len(result) <= 83  # 80 + "..."
        assert result.endswith("...")

    def test_glob_pattern(self):
        assert _tool_display("glob", {"pattern": "*.py"}) == "*.py"

    def test_fallback_params(self):
        result = _tool_display("unknown_tool", {"a": 1, "b": 2})
        assert "a=" in result


class TestJSONOutput:
    def test_json_text_event(self, capsys):
        _format_event_json(AgentEvent(type=EventType.TEXT, content="hello"))
        line = capsys.readouterr().out.strip()
        obj = json.loads(line)
        assert obj["type"] == "text"
        assert obj["content"] == "hello"

    def test_json_tool_call(self, capsys):
        tu = ToolUse(id="c1", name="bash", parameters={"command": "ls"})
        _format_event_json(AgentEvent(type=EventType.TOOL_CALL, tool_use=tu))
        line = capsys.readouterr().out.strip()
        obj = json.loads(line)
        assert obj["type"] == "tool_call"
        assert obj["tool"] == "bash"
        assert obj["parameters"]["command"] == "ls"

    def test_json_done_event(self, capsys):
        usage = AgentUsage(llm_calls=1, rounds=1)
        _format_event_json(AgentEvent(type=EventType.DONE, usage=usage))
        line = capsys.readouterr().out.strip()
        obj = json.loads(line)
        assert obj["type"] == "done"
        assert "usage" in obj
        assert obj["usage"]["llm_calls"] == 1

    def test_json_error_event(self, capsys):
        _format_event_json(AgentEvent(type=EventType.ERROR, content="fail"))
        line = capsys.readouterr().out.strip()
        obj = json.loads(line)
        assert obj["type"] == "error"
        assert obj["content"] == "fail"
