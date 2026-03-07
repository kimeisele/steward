"""Tests for StewardAgent and AgentLoop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from steward.agent import StewardAgent
from steward.loop.engine import AgentLoop
from steward.tool_registry import ToolRegistry
from steward.types import Conversation, Message


# ── Fake LLM Provider ────────────────────────────────────────────────


@dataclass
class FakeToolCall:
    id: str
    function: Any


@dataclass
class FakeFunction:
    name: str
    arguments: dict[str, Any]


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class FakeResponse:
    content: str = ""
    tool_calls: list[Any] | None = None
    usage: FakeUsage | None = None

    def __post_init__(self):
        if self.usage is None:
            self.usage = FakeUsage()


class FakeLLM:
    """Fake LLM that returns pre-programmed responses in sequence."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self._call_count = 0
        self.calls: list[dict] = []

    def invoke(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        return FakeResponse(content="[no more responses]")


# ── AgentLoop Tests ──────────────────────────────────────────────────


class TestAgentLoop:
    def test_simple_text_response(self):
        """LLM returns text → turn completes immediately."""
        llm = FakeLLM([FakeResponse(content="Hello!")])
        conv = Conversation()
        reg = ToolRegistry()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        result = loop.run("Hi")
        assert result == "Hello!"
        assert len(llm.calls) == 1

    def test_tool_use_then_text(self):
        """LLM calls a tool, then responds with text."""
        from steward.tools.bash import BashTool

        reg = ToolRegistry()
        reg.register(BashTool())

        # Response 1: tool call
        tc = FakeToolCall(
            id="call_1",
            function=FakeFunction(name="bash", arguments={"command": "echo hello"}),
        )
        # Response 2: text with result
        responses = [
            FakeResponse(content="", tool_calls=[tc]),
            FakeResponse(content="The command output: hello"),
        ]
        llm = FakeLLM(responses)
        conv = Conversation()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        result = loop.run("Run echo hello")
        assert "hello" in result.lower()
        assert len(llm.calls) == 2  # tool call + follow-up

    def test_unknown_tool_returns_error(self):
        """Unknown tool name → error result in conversation."""
        tc = FakeToolCall(
            id="call_1",
            function=FakeFunction(name="nonexistent", arguments={}),
        )
        responses = [
            FakeResponse(content="", tool_calls=[tc]),
            FakeResponse(content="Tool failed, sorry"),
        ]
        llm = FakeLLM(responses)
        conv = Conversation()
        reg = ToolRegistry()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        result = loop.run("Do something")
        # Should have a tool error in conversation
        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert "Unknown tool" in tool_msgs[0].content

    def test_max_rounds_exceeded(self):
        """Infinite tool loops are capped at MAX_TOOL_ROUNDS."""
        tc = FakeToolCall(
            id="call_inf",
            function=FakeFunction(name="echo", arguments={}),
        )
        # Always return tool calls
        responses = [FakeResponse(content="", tool_calls=[tc])] * 60
        llm = FakeLLM(responses)
        conv = Conversation()
        reg = ToolRegistry()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        result = loop.run("Loop forever")
        assert "Maximum tool rounds" in result

    def test_llm_failure_returns_error(self):
        """LLM crash → error message."""

        class CrashLLM:
            def invoke(self, **kwargs: Any) -> Any:
                raise ConnectionError("network down")

        conv = Conversation()
        reg = ToolRegistry()
        loop = AgentLoop(provider=CrashLLM(), registry=reg, conversation=conv)

        result = loop.run("Hello")
        assert "Error" in result


# ── StewardAgent Tests ───────────────────────────────────────────────


class TestStewardAgent:
    def test_agent_creates_with_defaults(self):
        llm = FakeLLM([])
        agent = StewardAgent(provider=llm)
        assert "bash" in agent.registry
        assert "read_file" in agent.registry
        assert "write_file" in agent.registry
        assert "glob" in agent.registry

    def test_agent_run(self):
        llm = FakeLLM([FakeResponse(content="Task complete.")])
        agent = StewardAgent(provider=llm)
        result = agent.run("Do something")
        assert result == "Task complete."

    def test_agent_conversation_persists(self):
        llm = FakeLLM([
            FakeResponse(content="First response"),
            FakeResponse(content="Second response"),
        ])
        agent = StewardAgent(provider=llm)
        agent.run("First task")
        agent.chat("Follow up")
        # Conversation should have: system + user + assistant + user + assistant
        assert len(agent.conversation.messages) == 5

    def test_agent_reset(self):
        llm = FakeLLM([FakeResponse(content="ok")])
        agent = StewardAgent(provider=llm)
        agent.run("task")
        agent.reset()
        assert len(agent.conversation.messages) == 0

    def test_agent_custom_tools(self):
        from vibe_core.tools.tool_protocol import Tool, ToolResult

        class CustomTool(Tool):
            @property
            def name(self) -> str:
                return "custom"

            @property
            def description(self) -> str:
                return "Custom tool"

            @property
            def parameters_schema(self) -> dict[str, Any]:
                return {}

            def validate(self, parameters: dict[str, Any]) -> None:
                pass

            def execute(self, parameters: dict[str, Any]) -> ToolResult:
                return ToolResult(success=True, output="custom result")

        llm = FakeLLM([])
        agent = StewardAgent(provider=llm, tools=[CustomTool()])
        assert "custom" in agent.registry
