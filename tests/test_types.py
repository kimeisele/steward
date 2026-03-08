"""Tests for core types: Message, Conversation, ToolUse, LLMUsage."""

from steward.types import Conversation, LLMUsage, Message, ToolUse


class TestMessage:
    def test_basic_message(self):
        msg = Message(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.tool_uses == []
        assert msg.tool_use_id is None

    def test_estimated_tokens(self):
        msg = Message(role="user", content="a" * 400)
        assert msg.estimated_tokens == 100  # 400 chars / 4

    def test_tool_use_message(self):
        tu = ToolUse(id="call_1", name="bash", parameters={"command": "ls"})
        msg = Message(role="assistant", content="", tool_uses=[tu])
        assert len(msg.tool_uses) == 1
        assert msg.tool_uses[0].name == "bash"


class TestLLMUsage:
    def test_defaults(self):
        u = LLMUsage()
        assert u.input_tokens == 0
        assert u.output_tokens == 0

    def test_explicit_values(self):
        u = LLMUsage(input_tokens=100, output_tokens=50)
        assert u.input_tokens == 100
        assert u.output_tokens == 50


class TestConversation:
    def test_add_messages(self):
        conv = Conversation()
        conv.add(Message(role="user", content="hi"))
        conv.add(Message(role="assistant", content="hello"))
        assert len(conv.messages) == 2

    def test_to_dicts(self):
        conv = Conversation()
        conv.add(Message(role="user", content="hi"))
        dicts = conv.to_dicts()
        assert dicts == [{"role": "user", "content": "hi"}]

    def test_to_dicts_with_tool_calls(self):
        conv = Conversation()
        tu = ToolUse(id="call_1", name="bash", parameters={"command": "ls"})
        conv.add(Message(role="assistant", content="", tool_uses=[tu]))
        dicts = conv.to_dicts()
        assert "tool_calls" in dicts[0]
        assert dicts[0]["tool_calls"][0]["function"]["name"] == "bash"

    def test_to_dicts_with_tool_result(self):
        conv = Conversation()
        conv.add(Message(role="tool", content="output", tool_use_id="call_1"))
        dicts = conv.to_dicts()
        assert dicts[0]["tool_call_id"] == "call_1"

    def test_trim_drops_oldest_non_system(self):
        conv = Conversation(max_tokens=50)
        conv.add(Message(role="system", content="system prompt"))
        # Add enough messages to exceed max_tokens
        for i in range(100):
            conv.add(Message(role="user", content=f"message {'x' * 100}"))
        assert conv.total_tokens <= 50
        # System message is preserved
        assert conv.messages[0].role == "system"

    def test_trim_preserves_system(self):
        conv = Conversation(max_tokens=10)
        conv.add(Message(role="system", content="important system prompt"))
        conv.add(Message(role="user", content="a" * 1000))
        # System should still be there
        assert any(m.role == "system" for m in conv.messages)
