"""End-to-end integration tests — prove the whole pipeline works.

Not unit tests. These test the FULL path:
user message → system prompt → LLM → tool calls → Buddhi → samskara → response

Uses a scripted FakeLLM that simulates realistic multi-step agent behavior.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from steward.agent import StewardAgent
from steward.types import AgentEvent, Message


@dataclass
class FakeUsage:
    input_tokens: int = 50
    output_tokens: int = 30


# ── Scripted LLM that returns tool calls then text ──────────────────


class ScriptedLLM:
    """LLM that follows a script: returns predefined responses in order.

    Each response is either:
    - A text response (content="...", tool_calls=None)
    - A tool call response (content="", tool_calls=[...])
    """

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self._call_idx = 0

    def invoke(self, **kwargs: object) -> object:
        if self._call_idx >= len(self._responses):
            return TextResponse("I'm done.")
        resp = self._responses[self._call_idx]
        self._call_idx += 1
        return resp

    @property
    def call_count(self) -> int:
        return self._call_idx


@dataclass
class TextResponse:
    content: str
    tool_calls: list | None = None
    usage: FakeUsage | None = None

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = FakeUsage()


@dataclass
class FakeToolCall:
    id: str
    function: object


@dataclass
class FakeFunction:
    name: str
    arguments: str  # JSON string


@dataclass
class ToolCallResponse:
    content: str = ""
    tool_calls: list | None = None
    usage: FakeUsage | None = None

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = FakeUsage()


# ── Integration Tests ───────────────────────────────────────────────


class TestEndToEnd:
    def test_simple_text_response(self):
        """User asks question → LLM responds with text → done."""
        llm = ScriptedLLM([TextResponse("Hello! How can I help?")])
        agent = StewardAgent(provider=llm, system_prompt="You are helpful.")

        result = agent.run_sync("Hi there")

        assert result == "Hello! How can I help?"
        assert llm.call_count == 1
        # Conversation should have: system + user + assistant
        assert len(agent.conversation.messages) >= 3

    def test_tool_call_then_text(self):
        """LLM calls a tool, gets result, then responds with text."""
        llm = ScriptedLLM([
            ToolCallResponse(
                content="Let me check.",
                tool_calls=[FakeToolCall(
                    id="call_1",
                    function=FakeFunction(name="glob", arguments='{"pattern": "*.py"}'),
                )],
            ),
            TextResponse("I found some Python files."),
        ])
        agent = StewardAgent(provider=llm, system_prompt="You are helpful.")

        result = agent.run_sync("Find Python files")

        assert "Python files" in result
        assert llm.call_count == 2

    def test_multi_turn_conversation(self):
        """Multiple turns maintain conversation context."""
        llm = ScriptedLLM([
            TextResponse("I'll help with that."),
            TextResponse("Sure, here's more info."),
            TextResponse("All done!"),
        ])
        agent = StewardAgent(provider=llm, system_prompt="You are helpful.")

        r1 = agent.run_sync("First question")
        r2 = agent.run_sync("Follow up")
        r3 = agent.run_sync("Final question")

        assert r1 == "I'll help with that."
        assert r2 == "Sure, here's more info."
        assert r3 == "All done!"
        # All messages should be in conversation
        assert len(agent.conversation.messages) >= 7  # system + 3×(user+assistant)

    def test_event_stream_complete(self):
        """run_stream yields all expected event types."""
        llm = ScriptedLLM([
            ToolCallResponse(
                content="Reading file.",
                tool_calls=[FakeToolCall(
                    id="call_1",
                    function=FakeFunction(name="glob", arguments='{"pattern": "*.md"}'),
                )],
            ),
            TextResponse("Done reading."),
        ])
        agent = StewardAgent(provider=llm, system_prompt="test")

        events: list[AgentEvent] = []

        async def collect():
            async for event in agent.run_stream("Read files"):
                events.append(event)

        asyncio.run(collect())

        event_types = [e.type for e in events]
        assert "tool_call" in event_types
        assert "tool_result" in event_types
        assert "text" in event_types
        assert "done" in event_types

        # Done event has usage
        done_event = [e for e in events if e.type == "done"][0]
        assert done_event.usage is not None
        assert done_event.usage.llm_calls >= 2

    def test_agent_reset_clears_state(self):
        """Reset clears conversation but keeps tools."""
        llm = ScriptedLLM([
            TextResponse("First response"),
            TextResponse("After reset"),
        ])
        agent = StewardAgent(provider=llm, system_prompt="test")

        agent.run_sync("Hello")
        assert len(agent.conversation.messages) >= 3

        agent.reset()
        assert len(agent.conversation.messages) == 0

        result = agent.run_sync("New session")
        assert result == "After reset"

    def test_gad_audit_after_work(self):
        """GAD-000 audit still passes after agent does work."""
        llm = ScriptedLLM([
            TextResponse("Task complete."),
        ])
        agent = StewardAgent(provider=llm, system_prompt="test")
        agent.chant()  # activate heartbeat

        agent.run_sync("Do something")

        audit = agent.audit()
        assert audit.discoverability is True
        assert audit.observability is True
        assert audit.criteria_score >= 5

    def test_discover_lists_all_tools(self):
        """discover() reflects the actual registered tools."""
        llm = ScriptedLLM([TextResponse("ok")])
        agent = StewardAgent(provider=llm, system_prompt="test")

        info = agent.discover()
        tools = info["tools"]

        # Should have all 6 builtin tools
        assert "bash" in tools
        assert "read_file" in tools
        assert "write_file" in tools
        assert "glob" in tools
        assert "edit_file" in tools
        assert "grep" in tools

    def test_state_reflects_conversation_growth(self):
        """get_state() shows conversation growing across turns."""
        llm = ScriptedLLM([
            TextResponse("Response 1"),
            TextResponse("Response 2"),
        ])
        agent = StewardAgent(provider=llm, system_prompt="test")

        s1 = agent.get_state()
        agent.run_sync("Turn 1")
        s2 = agent.get_state()
        agent.run_sync("Turn 2")
        s3 = agent.get_state()

        assert s2["conversation_messages"] > s1["conversation_messages"]
        assert s3["conversation_messages"] > s2["conversation_messages"]
        assert s3["conversation_tokens"] > s1["conversation_tokens"]
