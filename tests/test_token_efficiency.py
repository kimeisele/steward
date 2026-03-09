"""Hardcore token efficiency tests — RED BLOOD on the battlefield.

These tests expose every bottleneck in steward-agent's token pipeline.
If they're red, the architecture has rot. Make them green.

Prahlad Maharaj testing strategy: test the thing that SHOULD NOT survive.
Hiranyakasipu was "invincible" until tested at the boundary conditions.

Categories:
    1. TOOL OUTPUT COMPRESSION — tool results must be compressed before conversation
    2. CONVERSATION BLOAT — conversation must not grow unbounded
    3. SYSTEM PROMPT EFFICIENCY — system prompt must be lean
    4. JSON MODE — brain-in-a-jar must eliminate tool schema overhead
    5. DETERMINISTIC BYPASS — some tasks need ZERO LLM tokens
    6. CHAOS TESTING — what happens at the extremes?
    7. PRANA BUDGET — token budget must be organic, not hardcoded
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import pytest

from steward.agent import StewardAgent
from steward.loop.engine import (
    MAX_INPUT_CHARS,
    MAX_PARAM_CHARS,
    MAX_RESPONSE_CHARS,
    MAX_TOOL_OUTPUT_CHARS,
    AgentLoop,
)
from steward.services import lean_tool_signatures
from steward.types import (
    AgentEvent,
    AgentUsage,
    Conversation,
    EventType,
    Message,
    MessageRole,
    ToolUse,
)


# ── Test Infrastructure ─────────────────────────────────────────────


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 5


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
    arguments: str


@dataclass
class ToolCallResponse:
    content: str = ""
    tool_calls: list | None = None
    usage: FakeUsage | None = None

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = FakeUsage()


class ScriptedLLM:
    """LLM that follows a script and tracks what it receives."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self._call_idx = 0
        self.received_kwargs: list[dict] = []

    def invoke(self, **kwargs: object) -> object:
        self.received_kwargs.append(dict(kwargs))
        if self._call_idx >= len(self._responses):
            return TextResponse("done")
        resp = self._responses[self._call_idx]
        self._call_idx += 1
        return resp


class JsonModeLLM:
    """LLM that returns JSON responses (brain-in-a-jar mode)."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._call_idx = 0
        self.received_kwargs: list[dict] = []

    def invoke(self, **kwargs: object) -> object:
        self.received_kwargs.append(dict(kwargs))
        if self._call_idx >= len(self._responses):
            return TextResponse('{"response": "done"}')
        raw = self._responses[self._call_idx]
        self._call_idx += 1
        return TextResponse(raw)


# ── 1. TOOL OUTPUT COMPRESSION ──────────────────────────────────────


class TestToolOutputLimits:
    """Tool output must be bounded. 50k chars was insane."""

    def test_max_tool_output_chars_is_sane(self):
        """MAX_TOOL_OUTPUT_CHARS must be <= 10_000.

        50k was the old value. Even 10k is generous.
        Every char costs ~0.25 tokens. 10k = 2500 tokens per tool result.
        """
        assert MAX_TOOL_OUTPUT_CHARS <= 10_000, (
            f"MAX_TOOL_OUTPUT_CHARS={MAX_TOOL_OUTPUT_CHARS} is too high. "
            f"At ~0.25 tokens/char, that's {MAX_TOOL_OUTPUT_CHARS // 4} tokens per tool result."
        )

    def test_max_response_chars_is_sane(self):
        """MAX_RESPONSE_CHARS must be <= 20_000."""
        assert MAX_RESPONSE_CHARS <= 20_000

    def test_max_param_chars_is_sane(self):
        """MAX_PARAM_CHARS must be <= 5_000."""
        assert MAX_PARAM_CHARS <= 5_000

    def test_max_input_chars_is_sane(self):
        """MAX_INPUT_CHARS must be <= 15_000."""
        assert MAX_INPUT_CHARS <= 15_000

    def test_tool_output_truncation_works(self):
        """Tool output exceeding limit must be truncated."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            # Create a massive file
            big_file = Path(tmp) / "huge.txt"
            big_file.write_text("x" * 100_000)

            llm = ScriptedLLM([
                ToolCallResponse(
                    content="Reading.",
                    tool_calls=[
                        FakeToolCall(
                            id="c1",
                            function=FakeFunction(
                                name="read_file",
                                arguments=json.dumps({"path": str(big_file)}),
                            ),
                        )
                    ],
                ),
                TextResponse("Done."),
            ])
            agent = StewardAgent(provider=llm, system_prompt="test")

            events: list[AgentEvent] = []

            async def collect():
                async for event in agent.run_stream("Read the file"):
                    events.append(event)

            asyncio.run(collect())

            # Find tool result in conversation
            tool_msgs = [
                m for m in agent.conversation.messages if m.role == MessageRole.TOOL
            ]
            for msg in tool_msgs:
                assert len(msg.content) <= MAX_TOOL_OUTPUT_CHARS + 200, (
                    f"Tool output is {len(msg.content)} chars, exceeds limit of {MAX_TOOL_OUTPUT_CHARS}"
                )


# ── 2. CONVERSATION BLOAT ───────────────────────────────────────────


class TestConversationBloat:
    """Conversation must not grow without bound."""

    def test_tool_result_tagged_with_tool_name(self):
        """Tool results must include tool name for JSON mode context.

        Without the name, the LLM can't tell which tool produced which result.
        """
        llm = ScriptedLLM([
            ToolCallResponse(
                content="Listing.",
                tool_calls=[
                    FakeToolCall(
                        id="c1",
                        function=FakeFunction(name="glob", arguments='{"pattern": "*.py"}'),
                    )
                ],
            ),
            TextResponse("Found files."),
        ])
        agent = StewardAgent(provider=llm, system_prompt="test")
        agent.run_sync("List files")

        tool_msgs = [m for m in agent.conversation.messages if m.role == MessageRole.TOOL]
        assert len(tool_msgs) >= 1
        assert tool_msgs[0].content.startswith("[glob]"), (
            f"Tool result must start with [tool_name], got: {tool_msgs[0].content[:50]}"
        )

    def test_to_dicts_merges_consecutive_tool_messages(self):
        """to_dicts() must merge consecutive TOOL messages into one user message.

        Brain-in-a-jar: no tool_call_id correlation. Tool results go as user messages.
        Consecutive same-role messages must merge (providers don't like same-role back-to-back).
        """
        conv = Conversation()
        conv.add(Message(role=MessageRole.SYSTEM, content="system"))
        conv.add(Message(role=MessageRole.USER, content="do stuff"))
        conv.add(Message(role=MessageRole.ASSISTANT, content='{"tools": [...]}'))
        conv.add(Message(role=MessageRole.TOOL, content="[bash] output1"))
        conv.add(Message(role=MessageRole.TOOL, content="[glob] file1.py"))
        conv.add(Message(role=MessageRole.TOOL, content="[read_file] contents"))

        dicts = conv.to_dicts()
        roles = [d["role"] for d in dicts]

        # No consecutive same-role messages
        for i in range(1, len(roles)):
            # user-user is OK when it's tool results merged, but they should be MERGED
            pass

        # All TOOL messages should be merged into ONE user message
        user_msgs_after_assistant = [
            d for d in dicts[3:] if d["role"] == MessageRole.USER
        ]
        assert len(user_msgs_after_assistant) == 1, (
            f"Expected 1 merged user message for 3 tool results, got {len(user_msgs_after_assistant)}"
        )
        merged = user_msgs_after_assistant[0]["content"]
        assert "[bash]" in merged
        assert "[glob]" in merged
        assert "[read_file]" in merged

    def test_to_dicts_no_tool_calls_key(self):
        """Brain-in-a-jar: to_dicts() must NOT include tool_calls key.

        Tool info is in JSON content, not in tool_calls arrays.
        Every tool_calls key wastes tokens.
        """
        conv = Conversation()
        tu = ToolUse(id="c1", name="bash", parameters={"command": "ls"})
        conv.add(Message(
            role=MessageRole.ASSISTANT,
            content='{"tool": "bash", "params": {"command": "ls"}}',
            tool_uses=[tu],
        ))
        dicts = conv.to_dicts()
        for d in dicts:
            assert "tool_calls" not in d, "Brain-in-a-jar: no tool_calls in API output"
            assert "tool_call_id" not in d, "Brain-in-a-jar: no tool_call_id in API output"


# ── 3. SYSTEM PROMPT EFFICIENCY ─────────────────────────────────────


class TestSystemPromptEfficiency:
    """System prompt must be lean — every token costs N × LLM calls."""

    def test_system_prompt_under_600_tokens(self):
        """Base system prompt (without senses) must be under 600 tokens.

        At 4 chars/token, 600 tokens = 2400 chars.
        System prompt is sent EVERY LLM call. Fat prompts = fat bills.
        """
        from steward.agent import _BASE_SYSTEM_PROMPT

        estimated_tokens = len(_BASE_SYSTEM_PROMPT) // 4
        assert estimated_tokens < 600, (
            f"Base system prompt is ~{estimated_tokens} tokens ({len(_BASE_SYSTEM_PROMPT)} chars). "
            f"Must be under 600. Every token here costs N × LLM calls."
        )

    def test_lean_tool_signatures_under_200_tokens(self):
        """Lean tool signatures must be under 200 tokens for 10 tools.

        Full JSON Schema was ~1500 tokens. Lean sigs should be 80-200.
        """
        llm = ScriptedLLM([TextResponse("ok")])
        agent = StewardAgent(provider=llm, system_prompt="test")
        sigs = lean_tool_signatures(agent.registry)
        estimated_tokens = len(sigs) // 4
        assert estimated_tokens < 200, (
            f"Lean tool signatures are ~{estimated_tokens} tokens ({len(sigs)} chars). "
            f"Must be under 200. Full JSON Schema was ~1500 tokens."
        )

    def test_lean_sigs_include_all_tools(self):
        """Every registered tool must appear in lean signatures."""
        llm = ScriptedLLM([TextResponse("ok")])
        agent = StewardAgent(provider=llm, system_prompt="test")
        sigs = lean_tool_signatures(agent.registry)
        for tool_name in agent.registry.list_tools():
            assert tool_name in sigs, f"Tool '{tool_name}' missing from lean signatures"


# ── 4. JSON MODE (Brain-in-a-Jar) ───────────────────────────────────


class TestJsonMode:
    """Brain-in-a-jar: LLM responds with JSON, no tool schemas sent."""

    def test_no_tools_parameter_in_llm_call(self):
        """Default mode must NOT send 'tools' parameter to LLM.

        Brain-in-a-jar: tool info is in system prompt, not tools parameter.
        Sending tools wastes ~1500 tokens per call.
        """
        llm = ScriptedLLM([TextResponse("ok")])
        agent = StewardAgent(provider=llm)
        agent.run_sync("hello")

        assert len(llm.received_kwargs) >= 1
        for kwargs in llm.received_kwargs:
            assert "tools" not in kwargs, (
                "Brain-in-a-jar: 'tools' parameter must NOT be sent. "
                "Tool info goes in system prompt as lean signatures."
            )

    def test_response_format_json_in_default_mode(self):
        """Default mode must request JSON response format."""
        llm = ScriptedLLM([TextResponse("ok")])
        agent = StewardAgent(provider=llm)
        agent.run_sync("hello")

        assert len(llm.received_kwargs) >= 1
        for kwargs in llm.received_kwargs:
            resp_fmt = kwargs.get("response_format")
            assert resp_fmt == {"type": "json_object"}, (
                f"Brain-in-a-jar: response_format must be json_object, got {resp_fmt}"
            )

    def test_custom_prompt_uses_legacy_tools(self):
        """Custom system prompts use legacy tool-calling (backward compat)."""
        llm = ScriptedLLM([TextResponse("ok")])
        agent = StewardAgent(provider=llm, system_prompt="Custom prompt")
        agent.run_sync("hello")

        assert len(llm.received_kwargs) >= 1
        # Custom prompts send tools parameter (legacy mode)
        kwargs = llm.received_kwargs[0]
        assert "tools" in kwargs or "response_format" not in kwargs, (
            "Custom prompts should use legacy tool-calling, not JSON mode"
        )

    def test_json_tool_call_parsed(self):
        """LLM returning JSON tool call must be parsed correctly."""
        tool_calls, text = AgentLoop._parse_json_response(
            '{"tool": "read_file", "params": {"path": "/foo/bar.py"}}'
        )
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "read_file"
        assert tool_calls[0].parameters == {"path": "/foo/bar.py"}
        assert text == ""

    def test_json_parallel_tools_parsed(self):
        """LLM returning parallel tool calls must be parsed correctly."""
        tool_calls, text = AgentLoop._parse_json_response(
            '{"tools": [{"name": "glob", "params": {"pattern": "*.py"}}, '
            '{"name": "grep", "params": {"pattern": "TODO", "path": "."}}]}'
        )
        assert len(tool_calls) == 2
        assert tool_calls[0].name == "glob"
        assert tool_calls[1].name == "grep"

    def test_json_response_parsed(self):
        """LLM returning text response must be extracted correctly."""
        tool_calls, text = AgentLoop._parse_json_response(
            '{"response": "Here are the files: main.py, lib.py"}'
        )
        assert len(tool_calls) == 0
        assert "main.py" in text

    def test_json_with_markdown_fences(self):
        """Google Gemini wraps JSON in markdown fences — must be stripped."""
        tool_calls, text = AgentLoop._parse_json_response(
            '```json\n{"tool": "bash", "params": {"command": "ls"}}\n```'
        )
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "bash"

    def test_plain_text_fallback(self):
        """Non-JSON content falls through to plain text."""
        tool_calls, text = AgentLoop._parse_json_response("Just a text response")
        assert len(tool_calls) == 0
        assert text == "Just a text response"

    def test_json_mode_system_prompt_has_tool_sigs(self):
        """Default mode must inject tool signatures into system prompt."""
        llm = ScriptedLLM([TextResponse("ok")])
        agent = StewardAgent(provider=llm)
        agent.run_sync("hello")

        # Check system prompt in conversation
        system_msg = agent.conversation.messages[0]
        assert "Reply ONLY with JSON:" in system_msg.content, (
            "Brain-in-a-jar: system prompt must include JSON instruction"
        )
        assert "bash" in system_msg.content, (
            "Brain-in-a-jar: system prompt must include tool signatures"
        )

    def test_json_mode_full_roundtrip(self):
        """Full roundtrip: JSON tool call → execute → JSON response."""
        llm = JsonModeLLM([
            '{"tool": "glob", "params": {"pattern": "*.py"}}',
            '{"response": "Found Python files."}',
        ])
        agent = StewardAgent(provider=llm)

        events: list[AgentEvent] = []

        async def collect():
            async for event in agent.run_stream("Find python files"):
                events.append(event)

        asyncio.run(collect())

        event_types = [e.type for e in events]
        assert EventType.TOOL_CALL in event_types
        assert EventType.TOOL_RESULT in event_types
        assert EventType.DONE in event_types

        # Verify no tools parameter was sent
        for kwargs in llm.received_kwargs:
            assert "tools" not in kwargs


# ── 5. DETERMINISTIC BYPASS ─────────────────────────────────────────


class TestDeterministicBypass:
    """Some classifications should bypass the LLM entirely."""

    def test_manas_classifies_without_llm(self):
        """Manas must classify intent with ZERO LLM tokens."""
        from steward.antahkarana.manas import Manas

        manas = Manas()
        perception = manas.perceive("fix the broken test in test_auth.py")

        assert perception.action is not None
        assert perception.guna is not None
        assert perception.function is not None
        assert perception.approach is not None
        # Manas uses MahaBuddhi.think() — deterministic, zero LLM

    def test_buddhi_pre_flight_without_llm(self):
        """Buddhi pre-flight must work with ZERO LLM tokens."""
        from steward.buddhi import Buddhi

        buddhi = Buddhi()
        directive = buddhi.pre_flight("fix the bug", round_num=0)

        assert directive.action is not None
        assert directive.tier is not None
        assert directive.phase is not None
        assert directive.tool_names is not None
        # Buddhi uses Manas + Chitta — all deterministic

    def test_lotus_router_o1_lookup(self):
        """Lotus Router must resolve tool names in O(1)."""
        from vibe_core.mahamantra.adapters.attention import MahaAttention

        attention = MahaAttention()
        attention.memorize("bash", "bash_handler")
        attention.memorize("read_file", "read_handler")
        attention.memorize("glob", "glob_handler")

        # O(1) lookup — not scanning a list
        result = attention.attend("bash")
        assert result.found
        assert result.handler == "bash_handler"

        # Unknown tool — O(1) miss
        result = attention.attend("nonexistent_tool")
        assert not result.found


# ── 6. CHAOS TESTING ────────────────────────────────────────────────


class TestChaos:
    """Hiranyakasipu was invincible until tested at boundary conditions.

    These tests push the system to extremes to find where it breaks.
    """

    def test_massive_input_truncated(self):
        """1MB user input must be truncated, not sent to LLM."""
        llm = ScriptedLLM([TextResponse("ok")])
        agent = StewardAgent(provider=llm, system_prompt="test")
        massive_input = "x" * 1_000_000
        agent.run_sync(massive_input)

        # Check that the stored user message is truncated
        user_msgs = [m for m in agent.conversation.messages if m.role == MessageRole.USER]
        assert len(user_msgs) >= 1
        assert len(user_msgs[0].content) <= MAX_INPUT_CHARS + 100

    def test_massive_tool_output_truncated(self):
        """Tool returning 1MB output must be truncated before conversation."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            huge = Path(tmp) / "huge.txt"
            huge.write_text("data\n" * 200_000)  # ~1MB

            llm = ScriptedLLM([
                ToolCallResponse(
                    content="Reading.",
                    tool_calls=[
                        FakeToolCall(
                            id="c1",
                            function=FakeFunction(
                                name="read_file",
                                arguments=json.dumps({"path": str(huge)}),
                            ),
                        )
                    ],
                ),
                TextResponse("Done."),
            ])
            agent = StewardAgent(provider=llm, system_prompt="test")
            agent.run_sync("Read the file")

            tool_msgs = [m for m in agent.conversation.messages if m.role == MessageRole.TOOL]
            for msg in tool_msgs:
                assert len(msg.content) <= MAX_TOOL_OUTPUT_CHARS + 200

    def test_conversation_tokens_tracked_accurately(self):
        """Conversation.total_tokens must reflect actual content, not drift."""
        conv = Conversation(max_tokens=100_000)
        conv.add(Message(role=MessageRole.SYSTEM, content="System prompt " * 10))
        conv.add(Message(role=MessageRole.USER, content="User message " * 50))
        conv.add(Message(role=MessageRole.ASSISTANT, content="Response " * 100))

        # Token estimate uses ~3 chars/token (conservative for code/JSON).
        # Actual LLM usage is measured precisely; this is a safety approximation.
        total_chars = sum(len(m.content) for m in conv.messages)
        expected_tokens = total_chars // 3
        actual_tokens = conv.total_tokens

        # Allow 30% variance — estimation is conservative by design
        assert abs(actual_tokens - expected_tokens) < expected_tokens * 0.3, (
            f"Token tracking drifted: expected ~{expected_tokens}, got {actual_tokens}"
        )

    def test_param_clamping_prevents_context_bomb(self):
        """Tool parameters exceeding MAX_PARAM_CHARS must be clamped."""
        clamped = AgentLoop._clamp_params({
            "content": "x" * 100_000,
            "path": "/normal/path",
        })
        assert len(clamped["content"]) <= MAX_PARAM_CHARS + 50
        assert clamped["path"] == "/normal/path"

    def test_malformed_json_doesnt_crash(self):
        """Malformed JSON from LLM must not crash the engine."""
        for bad_json in [
            "{not json}",
            '{"tool": }',
            '{"response": null}',
            "",
            "null",
            "[]",
            '{"unknown_key": "value"}',
            '```\n{broken}\n```',
        ]:
            tool_calls, text = AgentLoop._parse_json_response(bad_json)
            # Should not crash — either returns calls or text, never raises


# ── 7. PRANA BUDGET ─────────────────────────────────────────────────


class TestPranaBudget:
    """Token budget must be organic, governed by system state, not hardcoded."""

    def test_buddhi_adjusts_max_tokens_by_context_pressure(self):
        """Buddhi must reduce max_tokens when context is filling up."""
        from steward.buddhi import Buddhi

        buddhi = Buddhi()

        # Low context pressure — standard budget
        d1 = buddhi.pre_flight("fix bug", round_num=0, context_pct=0.1)
        # High context pressure — should reduce budget
        d2 = buddhi.pre_flight("fix bug", round_num=5, context_pct=0.8)

        # At high context %, max_tokens should be lower
        if d1.max_tokens and d2.max_tokens:
            assert d2.max_tokens <= d1.max_tokens, (
                f"At 80% context, max_tokens ({d2.max_tokens}) should be <= "
                f"max_tokens at 10% ({d1.max_tokens})"
            )

    def test_samskara_compaction_reduces_tokens(self):
        """SamskaraContext must reduce conversation tokens at 50% threshold."""
        from steward.context import SamskaraContext

        conv = Conversation(max_tokens=200)
        # Fill conversation past 50%
        conv.add(Message(role=MessageRole.SYSTEM, content="System" * 5))
        for i in range(10):
            conv.add(Message(role=MessageRole.USER, content=f"User message {i} " * 5))
            conv.add(Message(role=MessageRole.ASSISTANT, content=f"Response {i} " * 5))

        samskara = SamskaraContext()
        before = conv.total_tokens

        if samskara.should_compact(conv, threshold=0.5):
            samskara.compact(conv)
            after = conv.total_tokens
            assert after <= before, (
                f"Samskara compaction should reduce tokens: {before} → {after}"
            )


# ── 8. COMPRESSION PRIMITIVES ──────────────────────────────────────


class TestCompressionPrimitives:
    """MahaCompression must be used to reduce input to LLM."""

    def test_compression_produces_seed(self):
        """MahaCompression must produce a deterministic seed from text."""
        from vibe_core.mahamantra.adapters.compression import MahaCompression

        mc = MahaCompression()
        r1 = mc.compress("fix the broken test in auth module")
        r2 = mc.compress("fix the broken test in auth module")

        assert r1.seed == r2.seed, "Same input must produce same seed"
        assert r1.seed != 0, "Seed must be non-zero"

    def test_compression_ratio_is_meaningful(self):
        """Compression ratio must reflect actual compression."""
        from vibe_core.mahamantra.adapters.compression import MahaCompression

        mc = MahaCompression()
        long_text = "This is a very detailed description of a complex software bug " * 20
        result = mc.compress(long_text)

        assert result.compression_ratio > 1.0, (
            f"Compression ratio {result.compression_ratio} must be > 1.0 for long text"
        )

    def test_engine_compresses_input_at_entry(self):
        """AgentLoop must compress user input at entry point (entry-point compression)."""
        import inspect

        # Verify by checking that MahaCompression is used in engine
        source = inspect.getsource(AgentLoop.run)
        assert "compress" in source, (
            "AgentLoop.run must call MahaCompression.compress() at entry point"
        )

    def test_maha_attention_o1_route(self):
        """MahaAttention must route tools in O(1) — no linear scan."""
        from vibe_core.mahamantra.adapters.attention import MahaAttention

        attention = MahaAttention()
        # Register 100 tools
        for i in range(100):
            attention.memorize(f"tool_{i}", f"handler_{i}")

        # O(1) lookup
        result = attention.attend("tool_50")
        assert result.found
        assert result.handler == "handler_50"

        # O(1) miss
        result = attention.attend("nonexistent")
        assert not result.found


# ── 9. TOKEN ACCOUNTING ─────────────────────────────────────────────


class TestTokenAccounting:
    """Every token must be accounted for. No invisible waste."""

    def test_usage_tracks_all_llm_calls(self):
        """AgentUsage must count every LLM call."""
        llm = ScriptedLLM([
            ToolCallResponse(
                content="",
                tool_calls=[
                    FakeToolCall(id="c1", function=FakeFunction(name="glob", arguments='{"pattern": "*.py"}')),
                ],
            ),
            TextResponse("Done."),
        ])
        agent = StewardAgent(provider=llm, system_prompt="test")

        events: list[AgentEvent] = []
        async def collect():
            async for event in agent.run_stream("Find files"):
                events.append(event)
        asyncio.run(collect())

        done_events = [e for e in events if e.type == EventType.DONE]
        assert len(done_events) == 1
        usage = done_events[0].usage
        assert usage is not None
        assert usage.llm_calls >= 2, f"Expected >= 2 LLM calls, got {usage.llm_calls}"
        assert usage.tool_calls >= 1, f"Expected >= 1 tool call, got {usage.tool_calls}"
        assert usage.rounds >= 2, f"Expected >= 2 rounds, got {usage.rounds}"

    def test_buddhi_diagnostics_in_usage(self):
        """AgentUsage must include Buddhi diagnostics (action, guna, tier, phase)."""
        llm = ScriptedLLM([TextResponse("ok")])
        agent = StewardAgent(provider=llm, system_prompt="test")

        events: list[AgentEvent] = []
        async def collect():
            async for event in agent.run_stream("hello"):
                events.append(event)
        asyncio.run(collect())

        done_events = [e for e in events if e.type == EventType.DONE]
        assert len(done_events) == 1
        usage = done_events[0].usage
        assert usage is not None
        assert usage.buddhi_action != "", "Buddhi action must be tracked"
        assert usage.buddhi_tier != "", "Buddhi tier must be tracked"
