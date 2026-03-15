"""Tests for conversation summarizer."""

from __future__ import annotations

import asyncio
from typing import Any

from tests.fakes import FakeResponse

from steward.loop.engine import AgentLoop
from steward.summarizer import Summarizer, should_summarize
from steward.types import Conversation, Message, ToolUse
from vibe_core.tools.tool_registry import ToolRegistry

# ── Specialized LLM for summarization tests ──────────────────────────


class FakeSummarizerLLM:
    """Returns a fixed summary when called."""

    def __init__(self, summary: str = "- Task: fix bugs\n- Read main.py\n- Edited 3 lines") -> None:
        self._summary = summary
        self.call_count = 0

    def invoke(self, **kwargs: Any) -> FakeResponse:
        self.call_count += 1
        # Check if this is a summarization call (contains summary prompt)
        messages = kwargs.get("messages", [])
        if messages and isinstance(messages, list):
            content = str(messages[0].get("content", ""))
            if "Summarize" in content:
                return FakeResponse(content=self._summary)
        return FakeResponse(content="ok")


# ── Tests ────────────────────────────────────────────────────────────


class TestShouldSummarize:
    def test_under_threshold(self) -> None:
        """No summarization needed when under threshold."""
        conv = Conversation(max_tokens=1000)
        conv.messages = [Message(role="user", content="short")]
        assert not should_summarize(conv, threshold=0.7)

    def test_over_threshold(self) -> None:
        """Summarization triggered when over threshold."""
        conv = Conversation(max_tokens=100)
        conv.messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="x" * 400),  # ~100 tokens > 70
        ]
        assert should_summarize(conv, threshold=0.7)


class TestSummarizer:
    def test_summarize_compacts_messages(self) -> None:
        """Summarizer replaces old messages with a summary."""
        llm = FakeSummarizerLLM()
        summarizer = Summarizer(llm)

        conv = Conversation(max_tokens=100_000)
        conv.messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Fix the bug"),
            Message(role="assistant", content="Let me read the file"),
            Message(role="tool", content="file contents here", tool_use_id="c1"),
            Message(role="assistant", content="I see the issue"),
            Message(role="user", content="What about tests?"),
            Message(role="assistant", content="Running tests now"),
        ]
        original_count = len(conv.messages)

        result = summarizer.summarize(conv, target_ratio=0.5)
        assert result is True
        assert len(conv.messages) < original_count
        assert conv.messages[0].role == "system"

        # Should have a summary message
        summary_msgs = [m for m in conv.messages if "[Summary of" in m.content]
        assert len(summary_msgs) == 1
        assert "fix bugs" in summary_msgs[0].content

    def test_summarize_preserves_system_prompt(self) -> None:
        """System prompt is never summarized away."""
        llm = FakeSummarizerLLM()
        summarizer = Summarizer(llm)

        conv = Conversation(max_tokens=100_000)
        conv.messages = [
            Message(role="system", content="Critical system prompt"),
            Message(role="user", content="Do task 1"),
            Message(role="assistant", content="Done 1"),
            Message(role="user", content="Do task 2"),
            Message(role="assistant", content="Done 2"),
        ]

        summarizer.summarize(conv)
        assert conv.messages[0].role == "system"
        assert conv.messages[0].content == "Critical system prompt"

    def test_summarize_preserves_recent_messages(self) -> None:
        """Most recent messages are kept intact."""
        llm = FakeSummarizerLLM()
        summarizer = Summarizer(llm)

        conv = Conversation(max_tokens=100_000)
        conv.messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="old task"),
            Message(role="assistant", content="old response"),
            Message(role="user", content="current task"),
            Message(role="assistant", content="current response"),
        ]

        summarizer.summarize(conv, target_ratio=0.5)

        # Most recent messages should still be there
        contents = [m.content for m in conv.messages]
        assert "current task" in contents
        assert "current response" in contents

    def test_summarize_too_few_messages(self) -> None:
        """Summarization skipped when too few messages."""
        llm = FakeSummarizerLLM()
        summarizer = Summarizer(llm)

        conv = Conversation(max_tokens=100_000)
        conv.messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="hello"),
        ]

        result = summarizer.summarize(conv)
        assert result is False
        assert llm.call_count == 0

    def test_summarize_llm_failure_returns_false(self) -> None:
        """Summarization returns False if LLM call fails."""

        class CrashLLM:
            def invoke(self, **kwargs: Any) -> Any:
                raise ConnectionError("offline")

        summarizer = Summarizer(CrashLLM())
        conv = Conversation(max_tokens=100_000)
        conv.messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="a"),
            Message(role="assistant", content="b"),
            Message(role="user", content="c"),
            Message(role="assistant", content="d"),
        ]

        result = summarizer.summarize(conv)
        assert result is False
        # Messages should be unchanged
        assert len(conv.messages) == 5

    def test_summarize_tool_uses_included_in_summary_input(self) -> None:
        """Tool calls are represented in the text sent to summarizer LLM."""
        llm = FakeSummarizerLLM()
        summarizer = Summarizer(llm)

        conv = Conversation(max_tokens=100_000)
        conv.messages = [
            Message(role="system", content="sys"),
            Message(
                role="assistant",
                content="Reading file",
                tool_uses=[ToolUse(id="c1", name="read_file", parameters={"path": "/foo.py"})],
            ),
            Message(role="tool", content="file contents", tool_use_id="c1"),
            Message(role="user", content="Next step"),
            Message(role="assistant", content="Done"),
        ]

        result = summarizer.summarize(conv, target_ratio=0.5)
        assert result is True
        # The LLM should have been called (even though we can't inspect the exact input)
        assert llm.call_count == 1


class TestSummarizerInLoop:
    def test_loop_triggers_summarization_at_threshold(self) -> None:
        """AgentLoop triggers summarization when context hits 70%."""
        llm = FakeSummarizerLLM()
        # Budget: 100 tokens. Pre-fill to ~95 tokens → 95% > 70% threshold.
        # Large enough that _trim() won't fire (95 < 100).
        conv = Conversation(max_tokens=100)
        reg = ToolRegistry()

        conv.messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="a" * 200),  # ~50 tokens
            Message(role="assistant", content="b" * 100),  # ~25 tokens
            Message(role="user", content="c" * 40),  # ~10 tokens
            Message(role="assistant", content="d" * 40),  # ~10 tokens
        ]

        loop = AgentLoop(provider=llm, registry=reg, conversation=conv)

        async def _run() -> None:
            async for _ in loop.run("new task"):
                pass

        asyncio.run(_run())

        # LLM called twice: once for summarization, once for the response
        assert llm.call_count >= 2
        # Summary message should exist in conversation
        summary_msgs = [m for m in conv.messages if "[Summary of" in m.content]
        assert len(summary_msgs) >= 1
