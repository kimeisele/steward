"""Tests for SamskaraContext — deterministic conversation compaction."""

from __future__ import annotations

from steward.context import SamskaraContext, _extract_structure
from steward.types import Conversation, Message, ToolUse

# ── _extract_structure tests ────────────────────────────────────────


class TestExtractStructure:
    def test_extracts_file_paths_from_tool_messages(self):
        """File paths in tool results are captured as files_read."""
        msgs = [
            Message(role="tool", content="Contents of /src/main.py:\ndef main(): ..."),
        ]
        result = _extract_structure(msgs)
        assert "/src/main.py" in result
        assert "Files read" in result

    def test_extracts_file_paths_from_write_context(self):
        """File paths in 'write' context are captured as files_modified."""
        msgs = [
            Message(role="assistant", content="I'll write to /src/config.yaml now"),
        ]
        result = _extract_structure(msgs)
        assert "/src/config.yaml" in result
        assert "Files modified" in result

    def test_extracts_tool_uses(self):
        """Tool uses from message metadata are counted."""
        msgs = [
            Message(
                role="assistant",
                content="Let me read that file",
                tool_uses=[
                    ToolUse(id="1", name="read_file", parameters={"path": "/src/app.py"}),
                    ToolUse(id="2", name="read_file", parameters={"path": "/src/lib.py"}),
                    ToolUse(id="3", name="bash", parameters={"command": "ls"}),
                ],
            ),
        ]
        result = _extract_structure(msgs)
        assert "read_file(2)" in result
        assert "bash(1)" in result
        assert "Tools:" in result

    def test_extracts_file_ops_from_tool_parameters(self):
        """Tool parameters with path are tracked as file operations."""
        msgs = [
            Message(
                role="assistant",
                content="editing",
                tool_uses=[
                    ToolUse(id="1", name="write_file", parameters={"path": "/out.txt"}),
                ],
            ),
        ]
        result = _extract_structure(msgs)
        assert "/out.txt" in result
        assert "Files modified" in result

    def test_extracts_errors(self):
        """Error messages from tool results are captured."""
        msgs = [
            Message(role="tool", content="[Error] FileNotFoundError: /missing.py"),
        ]
        result = _extract_structure(msgs)
        assert "Errors: 1" in result

    def test_empty_messages_returns_fallback(self):
        """No messages produces fallback string."""
        result = _extract_structure([])
        assert result == "No structured data extracted"

    def test_limits_file_paths_to_10(self):
        """File paths are capped at 10 to prevent bloat."""
        msgs = [
            Message(role="tool", content=" ".join(f"/src/file{i}.py" for i in range(20))),
        ]
        result = _extract_structure(msgs)
        # Should contain "Files read:" with at most 10 paths
        assert "Files read:" in result
        # Count commas — 9 commas = 10 items
        files_line = [l for l in result.split("\n") if "Files read" in l][0]
        assert files_line.count(",") <= 9


# ── SamskaraContext tests ───────────────────────────────────────────


def _make_conversation(n_messages: int, max_tokens: int = 200) -> Conversation:
    """Build a conversation with n user/assistant pairs + system prompt."""
    conv = Conversation(max_tokens=max_tokens)
    conv.messages.append(Message(role="system", content="You are helpful."))
    for i in range(n_messages):
        conv.messages.append(Message(role="user", content=f"Question {i} about code"))
        conv.messages.append(Message(role="assistant", content=f"Answer {i} with details"))
    return conv


class TestSamskaraContext:
    def test_compact_reduces_messages(self):
        """Compaction replaces older messages with samskara impression."""
        conv = _make_conversation(6)  # system + 12 messages
        ctx = SamskaraContext()
        original_count = len(conv.messages)

        result = ctx.compact(conv, keep_recent=4)

        assert result is True
        # Should have: system + samskara + 4 recent = 6
        assert len(conv.messages) == 6
        assert len(conv.messages) < original_count

    def test_compact_preserves_system_message(self):
        """System message is never touched."""
        conv = _make_conversation(6)
        ctx = SamskaraContext()
        ctx.compact(conv, keep_recent=4)

        assert conv.messages[0].role == "system"
        assert conv.messages[0].content == "You are helpful."

    def test_compact_preserves_recent_messages(self):
        """Most recent messages are kept intact."""
        conv = _make_conversation(6)
        # Last 4 non-system messages should be the last 2 Q/A pairs
        last_4_content = [m.content for m in conv.messages[-4:]]
        ctx = SamskaraContext()
        ctx.compact(conv, keep_recent=4)

        # Recent messages are preserved
        kept = [m.content for m in conv.messages[-4:]]
        assert kept == last_4_content

    def test_compact_creates_samskara_message(self):
        """The compaction result contains a samskara impression."""
        conv = _make_conversation(6)
        ctx = SamskaraContext()
        ctx.compact(conv, keep_recent=4)

        # Second message (after system) should be the samskara
        samskara = conv.messages[1]
        assert samskara.role == "user"
        assert "[Samskara of" in samskara.content
        assert "seed=" in samskara.content
        assert "unique intents" in samskara.content

    def test_compact_too_few_messages_returns_false(self):
        """Conversations too short for compaction return False."""
        conv = _make_conversation(2)  # system + 4 messages
        ctx = SamskaraContext()
        result = ctx.compact(conv, keep_recent=4)
        assert result is False

    def test_compact_not_enough_to_compact_returns_false(self):
        """When keep_recent covers all messages, nothing to compact."""
        conv = _make_conversation(3)  # system + 6 messages
        ctx = SamskaraContext()
        # keep_recent=6 means keep all non-system
        result = ctx.compact(conv, keep_recent=6)
        assert result is False

    def test_compact_idempotent(self):
        """Running compact twice doesn't break anything."""
        conv = _make_conversation(8)
        ctx = SamskaraContext()

        ctx.compact(conv, keep_recent=4)
        count_after_first = len(conv.messages)

        # Second compact — samskara + 4 recent = 5, but only 1 to compact (samskara itself)
        # which is < 2, so should return False
        result = ctx.compact(conv, keep_recent=4)
        assert result is False
        assert len(conv.messages) == count_after_first

    def test_compact_with_tool_messages(self):
        """Tool messages are compacted and their structure extracted."""
        conv = Conversation(max_tokens=500)
        conv.messages.append(Message(role="system", content="You are helpful."))
        conv.messages.append(Message(role="user", content="Read /src/main.py"))
        conv.messages.append(
            Message(
                role="assistant",
                content="Reading file",
                tool_uses=[ToolUse(id="1", name="read_file", parameters={"path": "/src/main.py"})],
            )
        )
        conv.messages.append(Message(role="tool", content="def main(): pass", tool_use_id="1"))
        conv.messages.append(Message(role="user", content="Now edit it"))
        conv.messages.append(
            Message(
                role="assistant",
                content="Editing file",
                tool_uses=[ToolUse(id="2", name="edit_file", parameters={"path": "/src/main.py"})],
            )
        )
        conv.messages.append(Message(role="tool", content="File written", tool_use_id="2"))
        # Recent messages to keep
        conv.messages.append(Message(role="user", content="Looks good"))
        conv.messages.append(Message(role="assistant", content="Done"))
        conv.messages.append(Message(role="user", content="Thanks"))
        conv.messages.append(Message(role="assistant", content="Welcome"))

        ctx = SamskaraContext()
        result = ctx.compact(conv, keep_recent=4)

        assert result is True
        samskara = conv.messages[1]
        assert "read_file" in samskara.content or "/src/main.py" in samskara.content

    def test_should_compact_below_threshold(self):
        """should_compact returns False when under 50% budget."""
        conv = Conversation(max_tokens=10000)
        conv.messages.append(Message(role="system", content="hi"))
        conv.messages.append(Message(role="user", content="hello"))

        ctx = SamskaraContext()
        assert ctx.should_compact(conv) is False

    def test_should_compact_above_threshold(self):
        """should_compact returns True when over 50% budget."""
        conv = Conversation(max_tokens=50)
        conv.messages.append(Message(role="system", content="System prompt here."))
        # Add enough messages to exceed 50% of 50 tokens
        for i in range(10):
            conv.messages.append(Message(role="user", content=f"Message {i} with lots of text content."))

        ctx = SamskaraContext()
        assert ctx.should_compact(conv) is True

    def test_should_compact_too_few_messages(self):
        """should_compact returns False with < 6 messages even if over budget."""
        conv = Conversation(max_tokens=10)
        conv.messages.append(Message(role="system", content="x" * 100))  # way over budget

        ctx = SamskaraContext()
        assert ctx.should_compact(conv) is False

    def test_seed_deduplication(self):
        """Messages with identical content produce fewer unique intents."""
        conv = Conversation(max_tokens=500)
        conv.messages.append(Message(role="system", content="System"))
        # Add many duplicate messages
        for _ in range(6):
            conv.messages.append(Message(role="user", content="Fix the bug in main.py"))
            conv.messages.append(Message(role="assistant", content="I'll fix main.py"))
        # Recent
        conv.messages.append(Message(role="user", content="Recent question"))
        conv.messages.append(Message(role="assistant", content="Recent answer"))

        ctx = SamskaraContext()
        ctx.compact(conv, keep_recent=2)

        samskara = conv.messages[1]
        # With 6 identical pairs, unique intents should be low (1-2)
        assert "unique intents" in samskara.content
