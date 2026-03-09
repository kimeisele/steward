"""Tests for core types — behavioral contracts only.

No dataclass field inspection. Tests here verify:
- Token estimation formula
- Brain-in-a-jar serialization (to_dicts role mapping)
- Context trimming behavior
"""

from steward.types import Conversation, Message, ToolUse


class TestMessageBehavior:
    def test_estimated_tokens(self):
        """Token estimation: 300 chars / 3 = 100 tokens (conservative for code/JSON)."""
        msg = Message(role="user", content="a" * 300)
        assert msg.estimated_tokens == 100


class TestConversationSerialization:
    """Brain-in-a-jar: to_dicts() converts internal messages to LLM-compatible format."""

    def test_to_dicts_basic(self):
        conv = Conversation()
        conv.add(Message(role="user", content="hi"))
        dicts = conv.to_dicts()
        assert dicts == [{"role": "user", "content": "hi"}]

    def test_to_dicts_brain_in_jar_no_tool_calls(self):
        """Assistant messages have JSON content, no tool_calls key."""
        conv = Conversation()
        tu = ToolUse(id="call_1", name="bash", parameters={"command": "ls"})
        conv.add(Message(role="assistant", content='{"tool": "bash", "params": {"command": "ls"}}', tool_uses=[tu]))
        dicts = conv.to_dicts()
        assert "tool_calls" not in dicts[0]
        assert dicts[0]["role"] == "assistant"

    def test_to_dicts_tool_becomes_user(self):
        """TOOL messages become user messages (brain-in-a-jar: no tool role)."""
        conv = Conversation()
        conv.add(Message(role="tool", content="output", tool_use_id="call_1"))
        dicts = conv.to_dicts()
        assert dicts[0]["role"] == "user"
        assert dicts[0]["content"] == "output"

    def test_to_dicts_merges_consecutive_same_role(self):
        """Consecutive TOOL messages merge into one user message."""
        conv = Conversation()
        conv.add(Message(role="assistant", content="calling tools"))
        conv.add(Message(role="tool", content="[bash] output1"))
        conv.add(Message(role="tool", content="[glob] file1.py"))
        dicts = conv.to_dicts()
        assert len(dicts) == 2  # assistant + merged user
        assert dicts[1]["role"] == "user"
        assert "[bash] output1" in dicts[1]["content"]
        assert "[glob] file1.py" in dicts[1]["content"]


class TestConversationTrimming:
    """Context window management — trim old messages, preserve system."""

    def test_trim_drops_oldest_non_system(self):
        conv = Conversation(max_tokens=200)
        conv.add(Message(role="system", content="system prompt"))
        for i in range(100):
            conv.add(Message(role="user", content=f"message {'x' * 100}"))
        assert conv.total_tokens <= 200
        assert len(conv.messages) < 100
        assert conv.messages[0].role == "system"

    def test_trim_preserves_system(self):
        conv = Conversation(max_tokens=10)
        conv.add(Message(role="system", content="important system prompt"))
        conv.add(Message(role="user", content="a" * 1000))
        assert any(m.role == "system" for m in conv.messages)
