"""Tests for StewardAgent and AgentLoop."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from steward.agent import StewardAgent
from steward.loop.engine import AgentLoop
from steward.types import AgentEvent, Conversation, EventType, Message
from vibe_core.tools.tool_registry import ToolRegistry


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


# ── Helper: collect events from async loop ───────────────────────────


def run_loop(loop: AgentLoop, message: str) -> tuple[str, list[AgentEvent]]:
    """Run the async loop synchronously, return (final_text, all_events)."""

    async def _collect():
        events = []
        final_text = ""
        async for event in loop.run(message):
            events.append(event)
            if event.type == EventType.TEXT:
                final_text = event.content or ""
            elif event.type == EventType.ERROR:
                final_text = f"[Error: {event.content}]"
        return final_text, events

    return asyncio.run(_collect())


# ── AgentLoop Tests ──────────────────────────────────────────────────


class TestAgentLoop:
    def test_simple_text_response(self):
        """LLM returns text -> turn completes immediately."""
        llm = FakeLLM([FakeResponse(content="Hello!")])
        conv = Conversation()
        reg = ToolRegistry()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        result, events = run_loop(loop, "Hi")
        assert result == "Hello!"
        assert len(llm.calls) == 1
        assert any(e.type == EventType.DONE for e in events)

    def test_tool_use_then_text(self):
        """LLM calls a tool, then responds with text."""
        from steward.tools.bash import BashTool

        reg = ToolRegistry()
        reg.register(BashTool())

        tc = FakeToolCall(
            id="call_1",
            function=FakeFunction(name="bash", arguments={"command": "echo hello"}),
        )
        responses = [
            FakeResponse(content="", tool_calls=[tc]),
            FakeResponse(content="The command output: hello"),
        ]
        llm = FakeLLM(responses)
        conv = Conversation()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        result, events = run_loop(loop, "Run echo hello")
        assert "hello" in result.lower()
        assert len(llm.calls) == 2
        # Should have tool_call and tool_result events
        assert any(e.type == EventType.TOOL_CALL for e in events)
        assert any(e.type == EventType.TOOL_RESULT for e in events)

    def test_unknown_tool_returns_error(self):
        """Unknown tool name -> error result in conversation."""
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

        result, events = run_loop(loop, "Do something")
        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert "not found" in tool_msgs[0].content

    def test_lotus_route_miss_blocks_before_registry(self):
        """O(1) Lotus route miss blocks unknown tools before registry execution."""
        from vibe_core.mahamantra.adapters.attention import MahaAttention

        # Register bash in registry but NOT in attention → route miss
        from steward.tools.bash import BashTool

        reg = ToolRegistry()
        reg.register(BashTool())
        attention = MahaAttention()
        # Deliberately NOT memorizing "bash" → attend() returns found=False

        tc = FakeToolCall(
            id="call_1",
            function=FakeFunction(name="bash", arguments={"command": "echo hi"}),
        )
        responses = [
            FakeResponse(content="", tool_calls=[tc]),
            FakeResponse(content="Route missed"),
        ]
        llm = FakeLLM(responses)
        conv = Conversation()
        loop = AgentLoop(
            provider=llm,
            registry=reg,
            conversation=conv,
            attention=attention,
        )

        result, events = run_loop(loop, "Run bash")
        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert "O(1) route miss" in tool_msgs[0].content
        # Tool result event should show failure
        tool_results = [e for e in events if e.type == EventType.TOOL_RESULT]
        assert len(tool_results) == 1
        assert not tool_results[0].content.success

    def test_lotus_route_hit_allows_execution(self):
        """O(1) Lotus route hit allows tool execution to proceed."""
        from vibe_core.mahamantra.adapters.attention import MahaAttention
        from steward.tools.bash import BashTool

        reg = ToolRegistry()
        bash = BashTool()
        reg.register(bash)
        attention = MahaAttention()
        attention.memorize("bash", bash)  # register in Lotus

        tc = FakeToolCall(
            id="call_1",
            function=FakeFunction(name="bash", arguments={"command": "echo lotus"}),
        )
        responses = [
            FakeResponse(content="", tool_calls=[tc]),
            FakeResponse(content="It worked"),
        ]
        llm = FakeLLM(responses)
        conv = Conversation()
        loop = AgentLoop(
            provider=llm,
            registry=reg,
            conversation=conv,
            attention=attention,
        )

        result, events = run_loop(loop, "Run echo lotus")
        assert "It worked" in result
        tool_results = [e for e in events if e.type == EventType.TOOL_RESULT]
        assert len(tool_results) == 1
        assert tool_results[0].content.success
        # Verify tool output contains "lotus"
        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        assert any("lotus" in m.content for m in tool_msgs)

    def test_parallel_tool_execution(self):
        """Multiple tool calls in one LLM response execute in parallel."""
        from steward.tools.bash import BashTool

        reg = ToolRegistry()
        reg.register(BashTool())

        tc1 = FakeToolCall(
            id="call_a",
            function=FakeFunction(name="bash", arguments={"command": "echo alpha"}),
        )
        tc2 = FakeToolCall(
            id="call_b",
            function=FakeFunction(name="bash", arguments={"command": "echo bravo"}),
        )
        responses = [
            FakeResponse(content="", tool_calls=[tc1, tc2]),
            FakeResponse(content="Both done"),
        ]
        llm = FakeLLM(responses)
        conv = Conversation()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        result, events = run_loop(loop, "Run two commands")
        assert result == "Both done"

        # Both tool calls should have events
        tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
        tool_result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
        assert len(tool_call_events) == 2
        assert len(tool_result_events) == 2

        # Both results should be successful
        assert all(e.content.success for e in tool_result_events)

        # Both outputs should be in conversation
        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        assert len(tool_msgs) == 2
        outputs = {m.content.strip() for m in tool_msgs}
        assert any("alpha" in o for o in outputs)
        assert any("bravo" in o for o in outputs)

        # Usage should track 2 tool calls
        done_events = [e for e in events if e.type == EventType.DONE]
        assert done_events[0].usage.tool_calls == 2

    def test_max_rounds_exceeded(self):
        """Infinite tool loops are capped at MAX_TOOL_ROUNDS."""
        tc = FakeToolCall(
            id="call_inf",
            function=FakeFunction(name="echo", arguments={}),
        )
        responses = [FakeResponse(content="", tool_calls=[tc])] * 60
        llm = FakeLLM(responses)
        conv = Conversation()
        reg = ToolRegistry()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        result, events = run_loop(loop, "Loop forever")
        assert "Maximum tool rounds" in result or "Error" in result

    def test_llm_failure_returns_error(self):
        """LLM crash -> error message."""

        class CrashLLM:
            def invoke(self, **kwargs: Any) -> Any:
                raise ConnectionError("network down")

        conv = Conversation()
        reg = ToolRegistry()
        loop = AgentLoop(provider=CrashLLM(), registry=reg, conversation=conv)

        result, events = run_loop(loop, "Hello")
        assert "Error" in result

    def test_run_sync_convenience(self):
        """run_sync() returns the final text directly."""
        llm = FakeLLM([FakeResponse(content="sync response")])
        conv = Conversation()
        reg = ToolRegistry()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        result = loop.run_sync("Hi")
        assert result == "sync response"

    def test_blocked_tools_feed_buddhi_abort(self):
        """Repeated blocked tools trigger Buddhi abort (5 consecutive errors)."""
        from vibe_core.mahamantra.adapters.attention import MahaAttention

        reg = ToolRegistry()
        attention = MahaAttention()
        # Nothing memorized → everything is a route miss

        # 5 rounds of route misses → Buddhi should abort
        tc = FakeToolCall(
            id="call_1",
            function=FakeFunction(name="nonexistent", arguments={"x": "1"}),
        )
        # Each round: route miss, then LLM tries again with same tool
        responses = [FakeResponse(content="", tool_calls=[tc])] * 6 + [
            FakeResponse(content="gave up"),
        ]
        llm = FakeLLM(responses)
        conv = Conversation()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv, attention=attention)

        result, events = run_loop(loop, "Do something")
        # Should abort after 5 consecutive blocked-tool errors
        assert "Buddhi abort" in result or "consecutive" in result.lower()

    def test_blocked_tools_feed_buddhi_redirect(self):
        """Blocked route misses trigger Buddhi redirect with valid tool names."""
        from vibe_core.mahamantra.adapters.attention import MahaAttention

        reg = ToolRegistry()
        attention = MahaAttention()

        # 2 different fake tools → route misses → redirect
        tc1 = FakeToolCall(id="c1", function=FakeFunction(name="search_code", arguments={"q": "x"}))
        tc2 = FakeToolCall(id="c2", function=FakeFunction(name="find_files", arguments={"p": "y"}))
        responses = [
            FakeResponse(content="", tool_calls=[tc1]),
            FakeResponse(content="", tool_calls=[tc2]),
            FakeResponse(content="got redirected"),
        ]
        llm = FakeLLM(responses)
        conv = Conversation()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv, attention=attention)

        result, events = run_loop(loop, "Search for code")
        # Buddhi should inject a redirect message into conversation
        user_msgs = [m for m in conv.messages if m.role == "user"]
        redirect_msgs = [m for m in user_msgs if "redirect" in m.content.lower()]
        assert len(redirect_msgs) >= 1
        assert "Available tools" in redirect_msgs[0].content


# ── StewardAgent Tests ───────────────────────────────────────────────


class TestStewardAgent:
    def test_agent_creates_with_defaults(self):
        llm = FakeLLM([])
        agent = StewardAgent(provider=llm)
        assert agent.registry.has("bash")
        assert agent.registry.has("read_file")
        assert agent.registry.has("write_file")
        assert agent.registry.has("glob")
        assert agent.registry.has("edit_file")
        assert agent.registry.has("grep")

    def test_agent_run_sync(self):
        llm = FakeLLM([FakeResponse(content="Task complete.")])
        agent = StewardAgent(provider=llm)
        result = agent.run_sync("Do something")
        assert result == "Task complete."

    def test_agent_run_async(self):
        llm = FakeLLM([FakeResponse(content="Async result.")])
        agent = StewardAgent(provider=llm)
        result = asyncio.run(agent.run("Do something"))
        assert result == "Async result."

    def test_agent_conversation_persists(self):
        llm = FakeLLM(
            [
                FakeResponse(content="First response"),
                FakeResponse(content="Second response"),
            ]
        )
        agent = StewardAgent(provider=llm)
        agent.run_sync("First task")
        agent.chat_sync("Follow up")
        # Conversation should have: system + user + assistant + user + assistant
        assert len(agent.conversation.messages) == 5

    def test_agent_reset(self):
        llm = FakeLLM([FakeResponse(content="ok")])
        agent = StewardAgent(provider=llm)
        agent.run_sync("task")
        agent.reset()
        assert len(agent.conversation.messages) == 0

    def test_usage_tracked_in_done_event(self):
        """Done event includes token usage stats."""
        llm = FakeLLM([FakeResponse(content="Result", usage=FakeUsage(input_tokens=50, output_tokens=25))])
        agent = StewardAgent(provider=llm)

        events: list[AgentEvent] = []

        async def _collect():
            async for event in agent.run_stream("Do it"):
                events.append(event)

        asyncio.run(_collect())

        done_events = [e for e in events if e.type == EventType.DONE]
        assert len(done_events) == 1
        usage = done_events[0].usage
        assert usage is not None
        assert usage.input_tokens == 50
        assert usage.output_tokens == 25
        assert usage.total_tokens == 75
        assert usage.llm_calls == 1
        assert usage.rounds == 1

    def test_usage_accumulates_across_tool_rounds(self):
        """Usage accumulates across multiple LLM calls during tool use."""
        tc = FakeToolCall(
            id="call_1",
            function=FakeFunction(name="bash", arguments={"command": "echo hi"}),
        )
        responses = [
            FakeResponse(content="", tool_calls=[tc], usage=FakeUsage(input_tokens=100, output_tokens=30)),
            FakeResponse(content="Done", usage=FakeUsage(input_tokens=200, output_tokens=40)),
        ]
        llm = FakeLLM(responses)
        agent = StewardAgent(provider=llm)

        events: list[AgentEvent] = []

        async def _collect():
            async for event in agent.run_stream("Run something"):
                events.append(event)

        asyncio.run(_collect())

        done_events = [e for e in events if e.type == EventType.DONE]
        assert len(done_events) == 1
        usage = done_events[0].usage
        assert usage is not None
        assert usage.input_tokens == 300  # 100 + 200
        assert usage.output_tokens == 70  # 30 + 40
        assert usage.llm_calls == 2
        assert usage.tool_calls == 1
        assert usage.rounds == 2

    def test_system_prompt_includes_cwd_and_tools(self):
        """Dynamic system prompt includes working directory and tool names."""
        llm = FakeLLM([FakeResponse(content="ok")])
        agent = StewardAgent(provider=llm)
        agent.run_sync("test")

        system_msg = agent.conversation.messages[0]
        assert system_msg.role == "system"
        assert "Working directory:" in system_msg.content
        assert "Available tools:" in system_msg.content
        assert "bash" in system_msg.content
        assert "read_file" in system_msg.content

    def test_tool_output_truncated_in_conversation(self):
        """Large tool outputs are truncated to prevent context blowout."""
        from vibe_core.tools.tool_protocol import Tool, ToolResult

        class BigOutputTool(Tool):
            @property
            def name(self) -> str:
                return "big_output"

            @property
            def description(self) -> str:
                return "Returns huge output"

            @property
            def parameters_schema(self) -> dict[str, Any]:
                return {}

            def validate(self, parameters: dict[str, Any]) -> None:
                pass

            def execute(self, parameters: dict[str, Any]) -> ToolResult:
                return ToolResult(success=True, output="x" * 100_000)

        tc = FakeToolCall(
            id="call_big",
            function=FakeFunction(name="big_output", arguments={}),
        )
        responses = [
            FakeResponse(content="", tool_calls=[tc]),
            FakeResponse(content="Done processing"),
        ]
        llm = FakeLLM(responses)
        agent = StewardAgent(provider=llm, tools=[BigOutputTool()])

        agent.run_sync("Generate big output")

        # Find the tool result message
        tool_msgs = [m for m in agent.conversation.messages if m.role == "tool"]
        assert len(tool_msgs) >= 1
        # Should be truncated (50k limit + truncation notice)
        assert len(tool_msgs[0].content) < 60_000
        assert "truncated" in tool_msgs[0].content

    def test_custom_system_prompt_preserved(self):
        """Custom system prompt is used as-is, not overwritten."""
        llm = FakeLLM([FakeResponse(content="ok")])
        agent = StewardAgent(provider=llm, system_prompt="Custom prompt only")
        agent.run_sync("test")

        system_msg = agent.conversation.messages[0]
        assert system_msg.content == "Custom prompt only"
        assert "Working directory:" not in system_msg.content

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
        assert agent.registry.has("custom")


class TestLLMRetry:
    """LLM call retries on transient failure."""

    def test_retry_on_first_failure(self):
        """LLM fails once, retries, succeeds on second attempt."""
        call_count = 0

        class RetryLLM:
            def invoke(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ConnectionError("transient failure")
                return FakeResponse(content="recovered!")

        reg = ToolRegistry()
        conv = Conversation()
        loop = AgentLoop(provider=RetryLLM(), registry=reg, conversation=conv)
        result, events = run_loop(loop, "test")
        assert result == "recovered!"
        assert call_count == 2

    def test_retry_exhausted_returns_error(self):
        """LLM fails on all attempts → error event."""

        class AlwaysFailLLM:
            def invoke(self, **kwargs):
                raise ConnectionError("permanent failure")

        reg = ToolRegistry()
        conv = Conversation()
        loop = AgentLoop(provider=AlwaysFailLLM(), registry=reg, conversation=conv)
        result, events = run_loop(loop, "test")
        errors = [e for e in events if e.type == EventType.ERROR]
        assert len(errors) >= 1
        assert "no response" in str(errors[0].content).lower()


class TestToolTimeout:
    """Tool execution respects timeout."""

    def test_timeout_produces_error_result(self):
        """A tool that exceeds timeout gets a timeout error."""
        import time
        from steward.loop import engine as engine_mod
        from vibe_core.tools.tool_protocol import Tool, ToolResult

        original = engine_mod.TOOL_TIMEOUT_SECONDS
        engine_mod.TOOL_TIMEOUT_SECONDS = 0.1

        try:

            class SlowTool(Tool):
                @property
                def name(self) -> str:
                    return "slow_tool"

                @property
                def description(self) -> str:
                    return "A tool that takes too long"

                @property
                def parameters_schema(self) -> dict[str, Any]:
                    return {}

                def validate(self, parameters: dict[str, Any]) -> None:
                    pass

                def execute(self, parameters: dict[str, Any]) -> ToolResult:
                    time.sleep(5)
                    return ToolResult(success=True, output="done")

            reg = ToolRegistry()
            reg.register(SlowTool())
            llm = FakeLLM(
                [
                    FakeResponse(
                        tool_calls=[
                            FakeToolCall(
                                id="c1",
                                function=FakeFunction(name="slow_tool", arguments={}),
                            )
                        ],
                    ),
                    FakeResponse(content="Timed out."),
                ]
            )
            conv = Conversation()
            loop = AgentLoop(provider=llm, registry=reg, conversation=conv)
            _, events = run_loop(loop, "test")
            results = [e for e in events if e.type == EventType.TOOL_RESULT]
            assert len(results) == 1
            assert not results[0].content.success
            assert "timed out" in str(results[0].content.error).lower()
        finally:
            engine_mod.TOOL_TIMEOUT_SECONDS = original
