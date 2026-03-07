"""Tests for context window management improvements."""

from __future__ import annotations

from steward.types import Conversation, Message


class TestSmartTrimming:
    def test_trim_tool_results_first(self) -> None:
        """Tool result messages are evicted before user/assistant messages."""
        conv = Conversation(max_tokens=50)
        conv.messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="Hello"),
            Message(role="tool", content="x" * 200, tool_use_id="c1"),
            Message(role="assistant", content="Got it"),
            Message(role="user", content="Next"),
        ]
        conv._trim()

        # Tool message should be gone, user/assistant messages preserved
        roles = [m.role for m in conv.messages]
        assert "tool" not in roles
        assert "user" in roles
        assert "assistant" in roles

    def test_compaction_marker_inserted(self) -> None:
        """When messages are trimmed, a compaction marker is inserted."""
        conv = Conversation(max_tokens=30)
        conv.messages = [
            Message(role="system", content="sys"),
            Message(role="tool", content="x" * 200, tool_use_id="c1"),
            Message(role="user", content="Continue"),
        ]
        conv._trim()

        # Should have a compaction marker
        marker_msgs = [m for m in conv.messages if "trimmed" in m.content]
        assert len(marker_msgs) == 1
        assert "1 earlier messages trimmed" in marker_msgs[0].content

    def test_system_prompt_never_evicted(self) -> None:
        """System prompt is always preserved during trimming."""
        conv = Conversation(max_tokens=20)
        conv.messages = [
            Message(role="system", content="Important system prompt"),
            Message(role="user", content="x" * 100),
            Message(role="assistant", content="y" * 100),
            Message(role="user", content="z" * 100),
        ]
        conv._trim()

        assert conv.messages[0].role == "system"
        assert "Important system prompt" in conv.messages[0].content

    def test_no_trim_when_under_budget(self) -> None:
        """No trimming when total tokens are under max."""
        conv = Conversation(max_tokens=100_000)
        conv.messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
        ]
        original_count = len(conv.messages)
        conv._trim()
        assert len(conv.messages) == original_count

    def test_multiple_tool_results_trimmed(self) -> None:
        """Multiple tool results are trimmed before other messages."""
        conv = Conversation(max_tokens=10)
        conv.messages = [
            Message(role="system", content="s"),
            Message(role="user", content="q"),
            Message(role="tool", content="a" * 100, tool_use_id="c1"),
            Message(role="tool", content="b" * 100, tool_use_id="c2"),
            Message(role="assistant", content="d"),
        ]
        conv._trim()

        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        assert len(tool_msgs) == 0
        # Marker should reflect both trimmed
        marker_msgs = [m for m in conv.messages if "trimmed" in m.content]
        assert len(marker_msgs) == 1
        assert "2 earlier messages" in marker_msgs[0].content

    def test_trim_via_add(self) -> None:
        """Adding a message triggers auto-trim when over budget."""
        conv = Conversation(max_tokens=30)
        conv.messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="Hello"),
        ]
        # Add a large message that pushes over budget
        conv.add(Message(role="tool", content="x" * 200, tool_use_id="c1"))

        # Should have been trimmed
        total = conv.total_tokens
        assert total <= conv.max_tokens + 50  # some slack for marker
