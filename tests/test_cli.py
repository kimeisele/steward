"""Tests for CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from steward.__main__ import (
    _format_event,
    _format_event_json,
    _handle_broadcast_health,
    _handle_list_quarantine,
    _handle_replay_quarantine,
    _tool_display,
)
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
            input_tokens=100,
            output_tokens=50,
            llm_calls=2,
            tool_calls=3,
            rounds=2,
            buddhi_action="IMPLEMENT",
            buddhi_guna="RAJAS",
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


class TestReplayCLI:
    def test_handle_replay_quarantine_dry_run_outputs_summary(self, capsys):
        engine = MagicMock()
        engine.dry_run.return_value = {"would_accept": 5, "still_invalid": 2, "files": []}
        args = MagicMock(dry_run=True, replay_all=False, file_name="", reject_reason="", output="human", replay_limit=None)

        exit_code = _handle_replay_quarantine(args, engine=engine)

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Would accept: 5 | Still invalid: 2" in captured.out

    def test_handle_replay_quarantine_reinjects_targeted_reason(self, capsys):
        engine = MagicMock()
        engine.reinject.return_value = {"replayed": 1, "failed": 0, "files": ["abc.json"]}
        args = MagicMock(dry_run=False, replay_all=False, file_name="", reject_reason="Gateway Validate Reject", output="json", replay_limit=7)

        exit_code = _handle_replay_quarantine(args, engine=engine)

        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out.strip())
        assert payload["replayed"] == 1
        engine.reinject.assert_called_once_with(file_name="", reject_reason="Gateway Validate Reject", limit=7)

    def test_handle_list_quarantine_outputs_grouped_summary(self, capsys):
        engine = MagicMock()
        engine.analytics.return_value = {
            "total": 3,
            "by_reason": {"Gateway Validate Reject": 2, "NADI inbox JSON decode failed": 1},
            "by_stage": {"gateway_validate_reject": 2, "transport_malformed": 1},
            "files": [],
        }
        args = MagicMock(replay_all=True, file_name="", reject_reason="", output="human", export_report="")

        exit_code = _handle_list_quarantine(args, engine=engine)

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Quarantine records: 3" in captured.out
        assert "Gateway Validate Reject: 2" in captured.out
        assert "gateway_validate_reject: 2" in captured.out

    def test_handle_list_quarantine_exports_nadi_ready_report(self, tmp_path, capsys):
        engine = MagicMock()
        engine.analytics.return_value = {
            "total": 1,
            "by_reason": {"Gateway Validate Reject": 1},
            "by_stage": {"gateway_validate_reject": 1},
            "files": [],
        }
        engine.build_node_health_report.return_value = {
            "node_id": "steward-node",
            "timestamp": 123.0,
            "quarantine_metrics": {"total": 1, "by_reason": {"Gateway Validate Reject": 1}, "by_stage": {"gateway_validate_reject": 1}},
            "recommended_action": "dry_run_then_replay",
        }
        export_path = tmp_path / "node_health.json"
        args = MagicMock(replay_all=True, file_name="", reject_reason="", output="json", export_report=str(export_path))

        exit_code = _handle_list_quarantine(args, engine=engine)

        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out.strip())
        assert payload["total"] == 1
        report = json.loads(Path(export_path).read_text())
        assert report["node_id"] == "steward-node"
        assert report["quarantine_metrics"]["total"] == 1


class TestBroadcastHealthCLI:
    def test_handle_broadcast_health_writes_nadi_message_to_outbox(self, tmp_path, capsys):
        engine = MagicMock()
        engine.build_node_health_report.return_value = {
            "node_id": "steward-node",
            "protocol_version": "1.0",
            "timestamp": 123.0,
            "status": "DEGRADED",
            "quarantine_metrics": {"total": 1, "by_reason": {}, "by_stage": {}, "files": []},
            "recommended_action": "dry_run_then_replay",
        }
        transport = MagicMock()
        transport.append_to_inbox.return_value = 1
        args = MagicMock(output="json", cwd=str(tmp_path))

        exit_code = _handle_broadcast_health(args, engine=engine, transport=transport)

        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out.strip())
        assert payload["operation"] == "federation.node_health"
        appended = transport.append_to_inbox.call_args.args[0][0]
        assert appended["operation"] == "federation.node_health"
        assert appended["payload"]["status"] == "DEGRADED"
