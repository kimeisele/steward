"""Tests for AnthropicAdapter format conversion."""

from __future__ import annotations

from dataclasses import dataclass

from steward.provider import AnthropicAdapter


@dataclass
class _FakeAnthropicResponse:
    """Simulates anthropic.types.Message."""
    content: list
    stop_reason: str = "end_turn"
    usage: object = None


class _FakeAnthropicClient:
    """Fake anthropic.Anthropic() that captures create() calls."""

    def __init__(self, response: _FakeAnthropicResponse) -> None:
        self._response = response
        self.last_kwargs: dict = {}

    @property
    def messages(self):
        return self

    def create(self, **kwargs: object) -> _FakeAnthropicResponse:
        self.last_kwargs = kwargs
        return self._response


class TestAnthropicAdapter:
    def test_system_prompt_separated(self):
        """System message extracted to 'system' kwarg, not in messages."""
        client = _FakeAnthropicClient(_FakeAnthropicResponse(content=[]))
        adapter = AnthropicAdapter(client)

        adapter.invoke(
            messages=[
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hello"},
            ],
            max_tokens=100,
        )

        assert client.last_kwargs["system"] == "You are helpful"
        api_msgs = client.last_kwargs["messages"]
        assert len(api_msgs) == 1
        assert api_msgs[0]["role"] == "user"

    def test_tool_calls_converted_to_content_blocks(self):
        """OpenAI-style tool_calls become Anthropic content blocks."""
        client = _FakeAnthropicClient(_FakeAnthropicResponse(content=[]))
        adapter = AnthropicAdapter(client)

        adapter.invoke(
            messages=[
                {"role": "user", "content": "Read the file"},
                {
                    "role": "assistant",
                    "content": "Let me read it.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": {"path": "/foo.py"}},
                        }
                    ],
                },
                {"role": "tool", "content": "file contents", "tool_call_id": "call_1"},
            ],
            max_tokens=100,
        )

        api_msgs = client.last_kwargs["messages"]
        # user, assistant (with tool_use blocks), user (with tool_result)
        assert len(api_msgs) == 3

        # Assistant message has content blocks
        asst = api_msgs[1]
        assert asst["role"] == "assistant"
        blocks = asst["content"]
        assert blocks[0]["type"] == "text"
        assert blocks[0]["text"] == "Let me read it."
        assert blocks[1]["type"] == "tool_use"
        assert blocks[1]["name"] == "read_file"
        assert blocks[1]["input"] == {"path": "/foo.py"}

        # Tool result is user message with tool_result block
        tool_msg = api_msgs[2]
        assert tool_msg["role"] == "user"
        assert tool_msg["content"][0]["type"] == "tool_result"
        assert tool_msg["content"][0]["tool_use_id"] == "call_1"

    def test_tools_converted_to_input_schema(self):
        """OpenAI function tools become Anthropic input_schema tools."""
        client = _FakeAnthropicClient(_FakeAnthropicResponse(content=[]))
        adapter = AnthropicAdapter(client)

        adapter.invoke(
            messages=[{"role": "user", "content": "Hi"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "bash",
                        "description": "Run a command",
                        "parameters": {
                            "type": "object",
                            "properties": {"command": {"type": "string"}},
                            "required": ["command"],
                        },
                    },
                }
            ],
            max_tokens=100,
        )

        anthropic_tools = client.last_kwargs["tools"]
        assert len(anthropic_tools) == 1
        assert anthropic_tools[0]["name"] == "bash"
        assert anthropic_tools[0]["input_schema"]["type"] == "object"
        assert "command" in anthropic_tools[0]["input_schema"]["properties"]

    def test_model_passed_through(self):
        """Model kwarg forwarded to Anthropic."""
        client = _FakeAnthropicClient(_FakeAnthropicResponse(content=[]))
        adapter = AnthropicAdapter(client)

        adapter.invoke(
            messages=[{"role": "user", "content": "Hi"}],
            model="claude-opus-4-20250514",
            max_tokens=200,
        )

        assert client.last_kwargs["model"] == "claude-opus-4-20250514"
        assert client.last_kwargs["max_tokens"] == 200
