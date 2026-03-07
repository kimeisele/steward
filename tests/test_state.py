"""Tests for state persistence (Phoenix pattern)."""

import json

from steward.state import clear_state, load_conversation, save_conversation
from steward.types import Conversation, Message, ToolUse


class TestStatePersistence:
    def test_save_and_load(self, tmp_path):
        conv = Conversation(max_tokens=50_000)
        conv.messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
        ]

        save_conversation(conv, cwd=str(tmp_path))
        loaded = load_conversation(cwd=str(tmp_path))

        assert loaded is not None
        assert len(loaded.messages) == 3
        assert loaded.messages[0].role == "system"
        assert loaded.messages[1].content == "Hello"
        assert loaded.messages[2].content == "Hi there"
        assert loaded.max_tokens == 50_000

    def test_save_with_tool_uses(self, tmp_path):
        conv = Conversation()
        conv.messages = [
            Message(
                role="assistant",
                content="Let me read that.",
                tool_uses=[ToolUse(id="call_1", name="read_file", parameters={"path": "/foo.py"})],
            ),
            Message(role="tool", content="file contents here", tool_use_id="call_1"),
        ]

        save_conversation(conv, cwd=str(tmp_path))
        loaded = load_conversation(cwd=str(tmp_path))

        assert loaded is not None
        assert len(loaded.messages) == 2
        assert len(loaded.messages[0].tool_uses) == 1
        assert loaded.messages[0].tool_uses[0].name == "read_file"
        assert loaded.messages[0].tool_uses[0].parameters == {"path": "/foo.py"}
        assert loaded.messages[1].tool_use_id == "call_1"

    def test_load_no_state(self, tmp_path):
        assert load_conversation(cwd=str(tmp_path)) is None

    def test_load_corrupted_json(self, tmp_path):
        state_dir = tmp_path / ".steward"
        state_dir.mkdir()
        (state_dir / "session.json").write_text("not json {{{{")
        assert load_conversation(cwd=str(tmp_path)) is None

    def test_load_wrong_version(self, tmp_path):
        state_dir = tmp_path / ".steward"
        state_dir.mkdir()
        (state_dir / "session.json").write_text(json.dumps({"version": 999}))
        assert load_conversation(cwd=str(tmp_path)) is None

    def test_clear_state(self, tmp_path):
        conv = Conversation()
        conv.messages = [Message(role="user", content="test")]

        save_conversation(conv, cwd=str(tmp_path))
        assert load_conversation(cwd=str(tmp_path)) is not None

        clear_state(cwd=str(tmp_path))
        assert load_conversation(cwd=str(tmp_path)) is None

    def test_atomic_write_no_temp_left(self, tmp_path):
        """Atomic write should not leave .tmp files behind."""
        conv = Conversation()
        conv.messages = [Message(role="user", content="test")]

        save_conversation(conv, cwd=str(tmp_path))

        state_dir = tmp_path / ".steward"
        files = list(state_dir.iterdir())
        assert len(files) == 1
        assert files[0].name == "session.json"

    def test_roundtrip_empty_conversation(self, tmp_path):
        conv = Conversation(max_tokens=200_000)
        save_conversation(conv, cwd=str(tmp_path))
        loaded = load_conversation(cwd=str(tmp_path))

        assert loaded is not None
        assert len(loaded.messages) == 0
        assert loaded.max_tokens == 200_000

    def test_overwrite_existing_state(self, tmp_path):
        """Second save overwrites first."""
        conv1 = Conversation()
        conv1.messages = [Message(role="user", content="first")]
        save_conversation(conv1, cwd=str(tmp_path))

        conv2 = Conversation()
        conv2.messages = [Message(role="user", content="second")]
        save_conversation(conv2, cwd=str(tmp_path))

        loaded = load_conversation(cwd=str(tmp_path))
        assert loaded is not None
        assert len(loaded.messages) == 1
        assert loaded.messages[0].content == "second"
