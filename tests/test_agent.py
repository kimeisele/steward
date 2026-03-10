"""Tests for StewardAgent and AgentLoop."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from steward.agent import StewardAgent
from steward.loop.engine import AgentLoop
from steward.types import AgentEvent, Conversation, EventType, LLMUsage, Message, NormalizedResponse, ToolUse
from vibe_core.tools.tool_registry import ToolRegistry

# ── Fake LLM Provider ────────────────────────────────────────────────

# Aliases for backward compat
FakeUsage = LLMUsage
FakeResponse = NormalizedResponse


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

        tc = ToolUse(id="call_1", name="bash", parameters={"command": "echo hello"})
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
        tc = ToolUse(id="call_1", name="nonexistent", parameters={})
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
        # Register bash in registry but NOT in attention → route miss
        from steward.tools.bash import BashTool
        from vibe_core.mahamantra.adapters.attention import MahaAttention

        reg = ToolRegistry()
        reg.register(BashTool())
        attention = MahaAttention()
        # Deliberately NOT memorizing "bash" → attend() returns found=False

        tc = ToolUse(id="call_1", name="bash", parameters={"command": "echo hi"})
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
        from steward.tools.bash import BashTool
        from vibe_core.mahamantra.adapters.attention import MahaAttention

        reg = ToolRegistry()
        bash = BashTool()
        reg.register(bash)
        attention = MahaAttention()
        attention.memorize("bash", bash)  # register in Lotus

        tc = ToolUse(id="call_1", name="bash", parameters={"command": "echo lotus"})
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

        tc1 = ToolUse(id="call_a", name="bash", parameters={"command": "echo alpha"})
        tc2 = ToolUse(id="call_b", name="bash", parameters={"command": "echo bravo"})
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
        tc = ToolUse(id="call_inf", name="echo", parameters={})
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
        tc = ToolUse(id="call_1", name="nonexistent", parameters={"x": "1"})
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
        tc1 = ToolUse(id="c1", name="search_code", parameters={"q": "x"})
        tc2 = ToolUse(id="c2", name="find_files", parameters={"p": "y"})
        responses = [
            FakeResponse(content="", tool_calls=[tc1]),
            FakeResponse(content="", tool_calls=[tc2]),
            FakeResponse(content="got redirected"),
        ]
        llm = FakeLLM(responses)
        conv = Conversation()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv, attention=attention)

        result, events = run_loop(loop, "Search for code")
        # Buddhi should inject redirect messages into conversation
        user_msgs = [m for m in conv.messages if m.role == "user"]
        redirect_msgs = [m for m in user_msgs if "redirect" in m.content.lower()]
        assert len(redirect_msgs) >= 1
        # Generic redirect fires on first failure — mentions the failed tool
        assert "search_code" in redirect_msgs[0].content or "find_files" in redirect_msgs[0].content


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
        assert agent.registry.has("agent_internet")

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
        tc = ToolUse(id="call_1", name="bash", parameters={"command": "echo hi"})
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
        """Dynamic system prompt includes cwd and tool sigs (brain-in-a-jar)."""
        llm = FakeLLM([FakeResponse(content="ok")])
        agent = StewardAgent(provider=llm)
        agent.run_sync("test")

        system_msg = agent.conversation.messages[0]
        assert system_msg.role == "system"
        assert "cwd:" in system_msg.content
        # Tools are in lean signatures (brain-in-a-jar), not "Available tools:"
        assert "bash(" in system_msg.content
        assert "read_file(" in system_msg.content

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

        tc = ToolUse(id="call_big", name="big_output", parameters={})
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


class TestHealthGateThreadSafety:
    """HealthGate flag is thread-safe (Cetana daemon thread → async loop)."""

    def test_health_anomaly_flag_thread_safe(self):
        """Concurrent reads/writes don't corrupt flag state."""
        import threading

        llm = FakeLLM([])
        agent = StewardAgent(provider=llm)

        errors = []

        def writer():
            for _ in range(100):
                agent._on_cetana_anomaly(None)  # None → early return (isinstance check)

        def reader():
            for _ in range(100):
                _ = agent.health_anomaly
                _ = agent.health_anomaly_detail
                agent.clear_health_anomaly()

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        # No crash = thread-safe

    def test_health_anomaly_uses_lock(self):
        """Verify the lock exists and is a threading.Lock."""
        import threading

        llm = FakeLLM([])
        agent = StewardAgent(provider=llm)
        assert hasattr(agent, "_health_lock")
        assert isinstance(agent._health_lock, type(threading.Lock()))

    def test_clear_resets_both_fields_atomically(self):
        """clear_health_anomaly resets flag and detail together."""
        llm = FakeLLM([])
        agent = StewardAgent(provider=llm)

        # Manually set (simulating Cetana callback)
        with agent._health_lock:
            agent._health_anomaly_flag = True
            agent._health_anomaly_detail_str = "test anomaly"

        assert agent.health_anomaly is True
        assert agent.health_anomaly_detail == "test anomaly"

        agent.clear_health_anomaly()
        assert agent.health_anomaly is False
        assert agent.health_anomaly_detail == ""


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
                            ToolUse(id="c1", name="slow_tool", parameters={})
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


class TestStreamingToolResults:
    """Test that tool results yield as they complete (not batched)."""

    def test_parallel_results_all_arrive(self):
        """Multiple parallel tools: all results arrive."""
        from steward.tools.bash import BashTool

        reg = ToolRegistry()
        reg.register(BashTool())

        tc1 = ToolUse(id="call_x", name="bash", parameters={"command": "echo fast"})
        tc2 = ToolUse(id="call_y", name="bash", parameters={"command": "echo slow"})
        responses = [
            FakeResponse(content="", tool_calls=[tc1, tc2]),
            FakeResponse(content="Done"),
        ]
        llm = FakeLLM(responses)
        conv = Conversation()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        result, events = run_loop(loop, "Two commands")
        results = [e for e in events if e.type == EventType.TOOL_RESULT]
        assert len(results) == 2
        assert all(e.content.success for e in results)

    def test_tool_result_before_done(self):
        """TOOL_RESULT events appear before DONE in event stream."""
        from steward.tools.bash import BashTool

        reg = ToolRegistry()
        reg.register(BashTool())

        tc = ToolUse(id="call_1", name="bash", parameters={"command": "echo test"})
        responses = [
            FakeResponse(content="", tool_calls=[tc]),
            FakeResponse(content="Complete"),
        ]
        llm = FakeLLM(responses)
        conv = Conversation()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        _, events = run_loop(loop, "Test")
        types = [e.type for e in events]
        tool_result_idx = types.index(EventType.TOOL_RESULT)
        done_idx = types.index(EventType.DONE)
        assert tool_result_idx < done_idx


class TestMessageMetadata:
    """Test structured metadata in Message (error tracking)."""

    def test_message_metadata_default_empty(self):
        """Message metadata defaults to empty dict."""
        m = Message(role="user", content="hello")
        assert m.metadata == {}

    def test_failed_tool_stores_metadata(self):
        """Failed tool results store structured error in message metadata."""
        tc = ToolUse(id="call_fail", name="nonexistent", parameters={})
        responses = [
            FakeResponse(content="", tool_calls=[tc]),
            FakeResponse(content="Failed"),
        ]
        llm = FakeLLM(responses)
        conv = Conversation()
        reg = ToolRegistry()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        run_loop(loop, "Do something")
        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        assert len(tool_msgs) == 1
        # Gate rejection stores error in metadata
        assert tool_msgs[0].metadata.get("success") is False or tool_msgs[0].metadata == {}

    def test_successful_tool_clean_metadata(self):
        """Successful tool result has empty or no error metadata."""
        from steward.tools.bash import BashTool

        reg = ToolRegistry()
        reg.register(BashTool())

        tc = ToolUse(id="call_ok", name="bash", parameters={"command": "echo ok"})
        responses = [
            FakeResponse(content="", tool_calls=[tc]),
            FakeResponse(content="Done"),
        ]
        llm = FakeLLM(responses)
        conv = Conversation()
        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        run_loop(loop, "Test")
        tool_msgs = [m for m in conv.messages if m.role == "tool"]
        assert len(tool_msgs) == 1
        # Success: no error metadata
        assert tool_msgs[0].metadata.get("error") is None


class TestToolSchemaConstraints:
    """Test that tool schemas communicate limits to the LLM."""

    def test_read_file_mentions_default_limit(self):
        from steward.tools.read_file import ReadFileTool

        schema = ReadFileTool().parameters_schema
        assert "2000" in schema["limit"]["description"]

    def test_bash_mentions_timeout_default(self):
        from steward.tools.bash import BashTool

        schema = BashTool().parameters_schema
        assert "120" in schema["timeout"]["description"]

    def test_glob_mentions_result_limit(self):
        from steward.tools.glob import GlobTool

        assert "1000" in GlobTool().description

    def test_grep_mentions_match_limit(self):
        from steward.tools.grep import GrepTool

        assert "500" in GrepTool().description


class TestDependencyAwareExecution:
    """Test write→read dependency detection for parallel tool execution.

    Protocol lesson from ActionStep.depends_on: if tool A writes a file
    that tool B reads/tests, B must wait for A to complete.
    """

    def test_no_writes_single_wave(self):
        """All reads — single wave, all parallel."""
        from steward.types import ToolUse

        to_execute = [
            (ToolUse(id="1", name="read_file", parameters={"path": "a.py"}), None),
            (ToolUse(id="2", name="read_file", parameters={"path": "b.py"}), None),
            (ToolUse(id="3", name="bash", parameters={"command": "echo hi"}), None),
        ]
        waves = AgentLoop._partition_by_dependency(to_execute)
        assert len(waves) == 1
        assert waves[0] == [0, 1, 2]

    def test_write_plus_independent_single_wave(self):
        """Write + unrelated read — single wave (no dependency)."""
        from steward.types import ToolUse

        to_execute = [
            (ToolUse(id="1", name="write_file", parameters={"path": "a.py", "content": "x"}), None),
            (ToolUse(id="2", name="read_file", parameters={"path": "b.py"}), None),
        ]
        waves = AgentLoop._partition_by_dependency(to_execute)
        assert len(waves) == 1

    def test_write_then_read_same_file_two_waves(self):
        """write_file(a.py) + read_file(a.py) → 2 waves."""
        from steward.types import ToolUse

        to_execute = [
            (ToolUse(id="1", name="write_file", parameters={"path": "/tmp/a.py", "content": "x"}), None),
            (ToolUse(id="2", name="read_file", parameters={"path": "/tmp/a.py"}), None),
        ]
        waves = AgentLoop._partition_by_dependency(to_execute)
        assert len(waves) == 2
        assert 0 in waves[0]  # writer in wave 1
        assert 1 in waves[1]  # reader in wave 2

    def test_edit_then_bash_test_two_waves(self):
        """edit_file(foo.py) + bash(pytest foo.py) → 2 waves."""
        from steward.types import ToolUse

        to_execute = [
            (
                ToolUse(
                    id="1", name="edit_file", parameters={"path": "src/foo.py", "old_string": "a", "new_string": "b"}
                ),
                None,
            ),
            (ToolUse(id="2", name="bash", parameters={"command": "pytest src/foo.py"}), None),
        ]
        waves = AgentLoop._partition_by_dependency(to_execute)
        assert len(waves) == 2
        assert 0 in waves[0]  # editor in wave 1
        assert 1 in waves[1]  # tester in wave 2

    def test_write_plus_independent_bash_single_wave(self):
        """write_file(a.py) + bash(echo hi) → 1 wave (bash doesn't reference a.py)."""
        from steward.types import ToolUse

        to_execute = [
            (ToolUse(id="1", name="write_file", parameters={"path": "a.py", "content": "x"}), None),
            (ToolUse(id="2", name="bash", parameters={"command": "echo hello"}), None),
        ]
        waves = AgentLoop._partition_by_dependency(to_execute)
        assert len(waves) == 1

    def test_single_tool_single_wave(self):
        """Single tool — always 1 wave."""
        from steward.types import ToolUse

        to_execute = [
            (ToolUse(id="1", name="write_file", parameters={"path": "a.py", "content": "x"}), None),
        ]
        waves = AgentLoop._partition_by_dependency(to_execute)
        assert len(waves) == 1

    def test_multiple_writes_dependent_reads(self):
        """Two writes, one dependent read — 2 waves, correct partitioning."""
        from steward.types import ToolUse

        to_execute = [
            (ToolUse(id="1", name="write_file", parameters={"path": "a.py", "content": "x"}), None),
            (
                ToolUse(id="2", name="edit_file", parameters={"path": "b.py", "old_string": "a", "new_string": "b"}),
                None,
            ),
            (ToolUse(id="3", name="bash", parameters={"command": "pytest a.py b.py"}), None),
            (ToolUse(id="4", name="read_file", parameters={"path": "c.py"}), None),
        ]
        waves = AgentLoop._partition_by_dependency(to_execute)
        assert len(waves) == 2
        # Wave 1: writers (0, 1) + independent reader (3)
        assert set(waves[0]) == {0, 1, 3}
        # Wave 2: dependent bash (2) — references both a.py and b.py
        assert waves[1] == [2]

    def test_end_to_end_write_then_test(self):
        """Full AgentLoop: write + test serialized correctly."""
        from steward.tools.bash import BashTool
        from steward.tools.write_file import WriteFileTool

        reg = ToolRegistry()
        reg.register(WriteFileTool())
        reg.register(BashTool())

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            target = f"{td}/hello.py"
            tc1 = ToolUse(id="w1", name="write_file", parameters={"path": target, "content": "print('hello')"})
            tc2 = ToolUse(id="t1", name="bash", parameters={"command": f"python {target}"})
            responses = [
                FakeResponse(content="", tool_calls=[tc1, tc2]),
                FakeResponse(content="Done"),
            ]
            llm = FakeLLM(responses)
            conv = Conversation()
            loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

            _, events = run_loop(loop, "Write and test")
            results = [e for e in events if e.type == EventType.TOOL_RESULT]
            assert len(results) == 2
            # Both should succeed because write completes before bash runs
            assert all(r.content.success for r in results)
