"""Tests for ToolSafetyGuard (Iron Dome) integration in AgentLoop."""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vibe_core.runtime.tool_safety_guard import ToolSafetyGuard
from vibe_core.tools.tool_protocol import Tool, ToolResult
from vibe_core.tools.tool_registry import ToolRegistry

from steward.loop.engine import AgentLoop
from steward.tools.edit import EditTool
from steward.tools.read_file import ReadFileTool
from steward.tools.write_file import WriteFileTool
from steward.types import Conversation


# ── Fake LLM ─────────────────────────────────────────────────────────


@dataclass
class FakeToolCall:
    id: str
    function: object


@dataclass
class FakeFunction:
    name: str
    arguments: dict[str, str]


@dataclass
class FakeResponse:
    content: str = ""
    tool_calls: list[object] | None = None


class FakeLLM:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self._i = 0

    def invoke(self, **kwargs: object) -> FakeResponse:
        if self._i < len(self._responses):
            r = self._responses[self._i]
            self._i += 1
            return r
        return FakeResponse(content="done")


def _run(loop: AgentLoop, msg: str) -> tuple[str, list[object]]:
    async def _collect() -> tuple[str, list[object]]:
        events = []
        text = ""
        async for ev in loop.run(msg):
            events.append(ev)
            if ev.type == "text":
                text = str(ev.content) if ev.content else ""
            elif ev.type == "error":
                text = str(ev.content)
        return text, events

    return asyncio.run(_collect())


# ── Tests ────────────────────────────────────────────────────────────


class TestSafetyGuard:
    def test_blind_edit_blocked(self):
        """Editing a file without reading it first is blocked."""
        guard = ToolSafetyGuard(enable_strict_mode=True)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("hello world")
            path = f.name

        reg = ToolRegistry()
        reg.register(EditTool())

        tc = FakeToolCall(
            id="call_edit",
            function=FakeFunction(
                name="edit_file",
                arguments={"path": path, "old_string": "hello", "new_string": "goodbye"},
            ),
        )
        llm = FakeLLM([
            FakeResponse(content="", tool_calls=[tc]),
            FakeResponse(content="edit failed"),
        ])
        conv = Conversation()
        loop = AgentLoop(
            provider=llm, registry=reg, conversation=conv, safety_guard=guard,
        )

        _run(loop, "edit the file")

        # Check that the tool result in conversation contains the block message
        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert "BLOCKED" in tool_msgs[0].content or "without reading" in tool_msgs[0].content

        # File should be unchanged
        assert Path(path).read_text() == "hello world"
        Path(path).unlink()

    def test_read_then_edit_allowed(self):
        """Reading a file first, then editing it, is allowed."""
        guard = ToolSafetyGuard(enable_strict_mode=True)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("hello world")
            path = f.name

        reg = ToolRegistry()
        reg.register(ReadFileTool())
        reg.register(EditTool())

        # Step 1: read
        tc_read = FakeToolCall(
            id="call_read",
            function=FakeFunction(name="read_file", arguments={"path": path}),
        )
        # Step 2: edit
        tc_edit = FakeToolCall(
            id="call_edit",
            function=FakeFunction(
                name="edit_file",
                arguments={"path": path, "old_string": "hello", "new_string": "goodbye"},
            ),
        )
        llm = FakeLLM([
            FakeResponse(content="", tool_calls=[tc_read]),
            FakeResponse(content="", tool_calls=[tc_edit]),
            FakeResponse(content="done"),
        ])
        conv = Conversation()
        loop = AgentLoop(
            provider=llm, registry=reg, conversation=conv, safety_guard=guard,
        )

        result, _ = _run(loop, "read then edit")
        assert result == "done"

        # File should be changed
        assert Path(path).read_text() == "goodbye world"
        Path(path).unlink()

    def test_write_without_read_blocked(self):
        """Writing to an existing file without reading is blocked."""
        guard = ToolSafetyGuard(enable_strict_mode=True)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("original")
            path = f.name

        reg = ToolRegistry()
        reg.register(WriteFileTool())

        tc = FakeToolCall(
            id="call_write",
            function=FakeFunction(
                name="write_file",
                arguments={"path": path, "content": "overwritten"},
            ),
        )
        llm = FakeLLM([
            FakeResponse(content="", tool_calls=[tc]),
            FakeResponse(content="blocked"),
        ])
        conv = Conversation()
        loop = AgentLoop(
            provider=llm, registry=reg, conversation=conv, safety_guard=guard,
        )

        _run(loop, "write file")

        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        assert any("BLOCKED" in m.content or "without reading" in m.content for m in tool_msgs)

        # File unchanged
        assert Path(path).read_text() == "original"
        Path(path).unlink()

    def test_guard_records_reads(self):
        """Safety guard tracks which files have been read."""
        guard = ToolSafetyGuard()
        guard.record_file_read("/tmp/test.py")
        assert guard._was_file_read("/tmp/test.py")
        assert not guard._was_file_read("/tmp/other.py")

    def test_guard_session_reset(self):
        """Resetting the session clears read/write records."""
        guard = ToolSafetyGuard()
        guard.record_file_read("/tmp/test.py")
        guard.reset_session()
        assert not guard._was_file_read("/tmp/test.py")
