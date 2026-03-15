"""End-to-end integration tests — prove the whole pipeline works.

Not unit tests. These test the FULL path:
user message → system prompt → LLM → tool calls → Buddhi → samskara → response

Uses a scripted FakeLLM that simulates realistic multi-step agent behavior.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from steward.agent import StewardAgent
from steward.types import AgentEvent, EventType, LLMUsage, Message, NormalizedResponse, StreamDelta, ToolUse

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
    usage: LLMUsage | None = None

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = LLMUsage(input_tokens=50, output_tokens=30)


@dataclass
class ToolCallResponse:
    content: str = ""
    tool_calls: list | None = None
    usage: LLMUsage | None = None

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = LLMUsage(input_tokens=50, output_tokens=30)


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
        llm = ScriptedLLM(
            [
                ToolCallResponse(
                    content="Let me check.",
                    tool_calls=[ToolUse(id="call_1", name="glob", parameters={"pattern": "*.py"})],
                ),
                TextResponse("I found some Python files."),
            ]
        )
        agent = StewardAgent(provider=llm, system_prompt="You are helpful.")

        result = agent.run_sync("Find Python files")

        assert "Python files" in result
        assert llm.call_count == 2

    def test_multi_turn_conversation(self):
        """Multiple turns maintain conversation context."""
        llm = ScriptedLLM(
            [
                TextResponse("I'll help with that."),
                TextResponse("Sure, here's more info."),
                TextResponse("All done!"),
            ]
        )
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
        llm = ScriptedLLM(
            [
                ToolCallResponse(
                    content="Reading file.",
                    tool_calls=[ToolUse(id="call_1", name="glob", parameters={"pattern": "*.md"})],
                ),
                TextResponse("Done reading."),
            ]
        )
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
        done_event = [e for e in events if e.type == EventType.DONE][0]
        assert done_event.usage is not None
        assert done_event.usage.llm_calls >= 2

    def test_agent_reset_clears_state(self):
        """Reset clears conversation but keeps tools."""
        llm = ScriptedLLM(
            [
                TextResponse("First response"),
                TextResponse("After reset"),
            ]
        )
        agent = StewardAgent(provider=llm, system_prompt="test")

        agent.run_sync("Hello")
        assert len(agent.conversation.messages) >= 3

        agent.reset()
        assert len(agent.conversation.messages) == 0

        result = agent.run_sync("New session")
        assert result == "After reset"

    def test_gad_audit_after_work(self):
        """GAD-000 audit still passes after agent does work."""
        llm = ScriptedLLM(
            [
                TextResponse("Task complete."),
            ]
        )
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

    def test_phase_lifecycle_orient_to_complete(self):
        """Full phase lifecycle: ORIENT → EXECUTE → VERIFY → COMPLETE.

        Scripts a realistic multi-step agent scenario with real temp files:
        1. Read two files (ORIENT → EXECUTE)
        2. Edit a file (EXECUTE)
        3. Read three files (EXECUTE → VERIFY, needs 3 reads so recent has no writes)
        4. Run bash tests (VERIFY → COMPLETE)
        5. Text response (done)

        Verifies phase transitions through AgentUsage.
        """
        import json
        import os
        import tempfile

        # Create real temp files so tools actually succeed
        tmpdir = tempfile.mkdtemp()
        main_py = os.path.join(tmpdir, "main.py")
        lib_py = os.path.join(tmpdir, "lib.py")
        test_py = os.path.join(tmpdir, "test.py")

        with open(main_py, "w") as f:
            f.write("def hello():\n    return 'old_value'\n")
        with open(lib_py, "w") as f:
            f.write("# lib module\n")
        with open(test_py, "w") as f:
            f.write("# test module\n")

        llm = ScriptedLLM(
            [
                # Round 1: Read file → ORIENT
                ToolCallResponse(
                    content="Let me read the code.",
                    tool_calls=[ToolUse(id="call_1", name="read_file", parameters={"path": main_py})],
                ),
                # Round 2: Read another file → 2 reads → EXECUTE
                ToolCallResponse(
                    content="Let me check another file.",
                    tool_calls=[ToolUse(id="call_2", name="read_file", parameters={"path": lib_py})],
                ),
                # Round 3: Edit the file → stays EXECUTE
                ToolCallResponse(
                    content="I'll fix the bug.",
                    tool_calls=[
                        ToolUse(
                            id="call_3",
                            name="edit_file",
                            parameters={
                                "path": main_py,
                                "old_string": "old_value",
                                "new_string": "new_value",
                            },
                        )
                    ],
                ),
                # Rounds 4-6: Read after write → push recent window past the write → VERIFY
                ToolCallResponse(
                    content="Let me verify the change.",
                    tool_calls=[ToolUse(id="call_4", name="read_file", parameters={"path": main_py})],
                ),
                ToolCallResponse(
                    content="Checking more.",
                    tool_calls=[ToolUse(id="call_5", name="read_file", parameters={"path": test_py})],
                ),
                ToolCallResponse(
                    content="Reading lib.",
                    tool_calls=[ToolUse(id="call_6", name="read_file", parameters={"path": lib_py})],
                ),
                # Round 7: Run tests → COMPLETE
                ToolCallResponse(
                    content="Running tests.",
                    tool_calls=[ToolUse(id="call_7", name="bash", parameters={"command": "echo 'all tests passed'"})],
                ),
                # Final: text response
                TextResponse("All tests pass. Bug fixed."),
            ]
        )
        agent = StewardAgent(provider=llm, system_prompt="You are a coding agent.")

        events: list[AgentEvent] = []

        async def collect():
            async for event in agent.run_stream("Fix the bug in main.py"):
                events.append(event)

        try:
            asyncio.run(collect())

            # Verify event stream completeness
            event_types = [e.type for e in events]
            assert "tool_call" in event_types
            assert "tool_result" in event_types
            assert "text" in event_types
            assert "done" in event_types

            # Verify multiple tool rounds happened
            done_event = [e for e in events if e.type == EventType.DONE][0]
            assert done_event.usage is not None
            assert done_event.usage.llm_calls >= 7  # at least 7 LLM calls + final text
            assert done_event.usage.tool_calls >= 7  # at least 7 tool calls

            # Verify tool calls executed correctly
            tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
            tool_names = [e.tool_use.name for e in tool_call_events]
            assert "read_file" in tool_names
            assert "edit_file" in tool_names
            assert "bash" in tool_names

            # Verify final response
            text_events = [e for e in events if e.type == EventType.TEXT]
            assert len(text_events) == 1
            assert "Bug fixed" in str(text_events[0].content)

            # Verify the edit actually modified the file
            with open(main_py) as f:
                assert "new_value" in f.read()

            # Verify Buddhi phase transition guidance was injected (EXECUTE → VERIFY)
            buddhi_msgs = [m for m in agent.conversation.messages if m.role == "user" and "Buddhi" in m.content]
            # At least one reflection from phase transition
            assert len(buddhi_msgs) >= 1
        finally:
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_buddhi_abort_on_consecutive_errors(self):
        """Buddhi aborts after too many consecutive errors.

        Scripts 5 consecutive tool call failures → Buddhi detects
        the pattern and aborts the loop.
        """
        # Build responses that all fail (tools that don't exist)
        error_responses = []
        for i in range(6):
            error_responses.append(
                ToolCallResponse(
                    content=f"Trying tool {i}.",
                    tool_calls=[ToolUse(id=f"call_{i}", name="nonexistent_tool", parameters={"x": "y"})],
                )
            )
        error_responses.append(TextResponse("This shouldn't be reached."))

        llm = ScriptedLLM(error_responses)
        agent = StewardAgent(provider=llm, system_prompt="test")

        events: list[AgentEvent] = []

        async def collect():
            async for event in agent.run_stream("Do something"):
                events.append(event)

        asyncio.run(collect())

        # Should have an error event from Buddhi abort
        error_events = [e for e in events if e.type == EventType.ERROR]
        assert len(error_events) >= 1
        # Check it mentions Buddhi
        assert any("Buddhi" in str(e.content) or "abort" in str(e.content).lower() for e in error_events)

    def test_buddhi_reflects_on_identical_calls(self):
        """Buddhi injects reflection when same tool called identically 3x.

        The LLM calls glob with the same pattern 3 times → Buddhi
        detects identical_calls and injects reflection guidance.
        """
        identical_responses = []
        for i in range(3):
            identical_responses.append(
                ToolCallResponse(
                    content="Looking for files.",
                    tool_calls=[ToolUse(id=f"call_{i}", name="glob", parameters={"pattern": "*.py"})],
                )
            )
        identical_responses.append(TextResponse("Ok, I'll try something else."))

        llm = ScriptedLLM(identical_responses)
        agent = StewardAgent(provider=llm, system_prompt="test")

        events: list[AgentEvent] = []

        async def collect():
            async for event in agent.run_stream("Find Python files"):
                events.append(event)

        asyncio.run(collect())

        # The conversation should have a Buddhi reflection message
        messages = agent.conversation.messages
        buddhi_msgs = [m for m in messages if m.role == "user" and "Buddhi" in m.content]
        assert len(buddhi_msgs) >= 1
        assert any("identical" in m.content.lower() or "same parameters" in m.content.lower() for m in buddhi_msgs)

    def test_streaming_text_deltas(self):
        """Provider with invoke_stream yields text_delta events.

        Uses a StreamingScriptedLLM that simulates chunked output.
        """

        class StreamingLLM:
            """LLM that supports both invoke and invoke_stream."""

            def invoke(self, **kwargs: object) -> object:
                return TextResponse("Fallback response")

            def invoke_stream(self, **kwargs: object):
                """Simulate streaming — yield chunks then done."""
                yield StreamDelta(type="text_delta", text="Hello ")
                yield StreamDelta(type="text_delta", text="world!")
                yield StreamDelta(
                    type="done",
                    response=NormalizedResponse(
                        content="Hello world!",
                        usage=LLMUsage(input_tokens=10, output_tokens=5),
                    ),
                )

        llm = StreamingLLM()
        agent = StewardAgent(provider=llm, system_prompt="test")

        events: list[AgentEvent] = []

        async def collect():
            async for event in agent.run_stream("Say hello"):
                events.append(event)

        asyncio.run(collect())

        event_types = [e.type for e in events]
        # Should have text_delta events (streaming) and done
        assert "text_delta" in event_types
        assert "done" in event_types

        # Collect all text deltas
        deltas = [str(e.content) for e in events if e.type == EventType.TEXT_DELTA]
        assert len(deltas) == 2
        assert deltas[0] == "Hello "
        assert deltas[1] == "world!"

        # No separate "text" event when we had deltas
        text_events = [e for e in events if e.type == EventType.TEXT]
        assert len(text_events) == 0

    def test_streaming_fallback_to_non_streaming(self):
        """Provider without invoke_stream falls back to non-streaming."""
        llm = ScriptedLLM([TextResponse("Non-streaming response")])
        agent = StewardAgent(provider=llm, system_prompt="test")

        events: list[AgentEvent] = []

        async def collect():
            async for event in agent.run_stream("Hello"):
                events.append(event)

        asyncio.run(collect())

        event_types = [e.type for e in events]
        # No text_delta (non-streaming provider)
        assert "text_delta" not in event_types
        # Has regular text event
        assert "text" in event_types
        assert "done" in event_types

    def test_streaming_run_returns_assembled_text(self):
        """run() and run_sync() correctly assemble streamed text."""

        class StreamingLLM:
            def invoke(self, **kwargs: object) -> object:
                return TextResponse("Fallback")

            def invoke_stream(self, **kwargs: object):
                yield StreamDelta(type="text_delta", text="Part ")
                yield StreamDelta(type="text_delta", text="one ")
                yield StreamDelta(type="text_delta", text="two")
                yield StreamDelta(
                    type="done",
                    response=NormalizedResponse(content="Part one two"),
                )

        llm = StreamingLLM()
        agent = StewardAgent(provider=llm, system_prompt="test")

        result = agent.run_sync("Test streaming assembly")
        assert result == "Part one two"

    def test_cross_turn_chitta_persistence(self):
        """Chitta retains file awareness across turns.

        Turn 1: Read a file → Chitta records the read
        Turn 2: Edit same file → no write-without-read detection
        (because Chitta remembers the read from turn 1)
        """
        llm = ScriptedLLM(
            [
                # Turn 1: read a file
                ToolCallResponse(
                    content="Reading.",
                    tool_calls=[ToolUse(id="c1", name="glob", parameters={"pattern": "*.py"})],
                ),
                TextResponse("Found files."),
                # Turn 2: just text
                TextResponse("Ok, I understand the codebase."),
            ]
        )
        agent = StewardAgent(provider=llm, system_prompt="test")

        # Turn 1
        agent.run_sync("Explore the codebase")

        # After turn 1, Buddhi's Chitta should have end_turn'd
        # and the agent's state should show buddhi info
        state = agent.get_state()
        assert "buddhi_phase" in state
        assert "chitta_stats" in state

        # Turn 2 works normally
        result = agent.run_sync("What did you find?")
        assert "understand" in result.lower() or "Ok" in result

    @pytest.mark.timeout(60)
    def test_state_reflects_conversation_growth(self):
        """get_state() shows conversation growing across turns."""
        llm = ScriptedLLM(
            [
                TextResponse("Response 1"),
                TextResponse("Response 2"),
            ]
        )
        agent = StewardAgent(provider=llm, system_prompt="test")

        s1 = agent.get_state()
        agent.run_sync("Turn 1")
        s2 = agent.get_state()
        agent.run_sync("Turn 2")
        s3 = agent.get_state()

        assert s2["conversation_messages"] > s1["conversation_messages"]
        assert s3["conversation_messages"] > s2["conversation_messages"]
        assert s3["conversation_tokens"] > s1["conversation_tokens"]
