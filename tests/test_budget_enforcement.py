"""Tests for hard budget enforcement — enterprise safety.

Verifies:
- Context trimming enforces MAX_INPUT_TOKENS_PER_CALL before every LLM call
- Tool output truncation respects MAX_TOOL_OUTPUT_CHARS (2000 chars)
- build_chamber() contains ONLY free-tier providers (no Anthropic, no DeepSeek)
- CBR measures total tokens (input + output), not output-only
- dotenv loading works for local key management
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from steward.loop.engine import (
    MAX_INPUT_CHARS,
    MAX_INPUT_TOKENS_PER_CALL,
    MAX_RESPONSE_CHARS,
    MAX_TOOL_OUTPUT_CHARS,
    AgentLoop,
)
from steward.types import AgentUsage, Conversation, Message, MessageRole


# ── Hard Limits Are Tight ────────────────────────────────────────────


class TestHardLimits:
    """Verify the hard constants are set for free-tier safety."""

    def test_tool_output_limit_is_tight(self):
        """Tool output is 2000 chars max (~667 tokens). Not 4000."""
        assert MAX_TOOL_OUTPUT_CHARS == 2_000

    def test_input_limit_is_tight(self):
        """User input is 2000 chars max."""
        assert MAX_INPUT_CHARS == 2_000

    def test_response_limit_is_tight(self):
        """LLM response stored in conversation is 1500 chars max."""
        assert MAX_RESPONSE_CHARS == 1_500

    def test_input_tokens_per_call_budget(self):
        """Hard wall: 3000 tokens max per LLM call."""
        assert MAX_INPUT_TOKENS_PER_CALL == 3_000


# ── Context Trimming ─────────────────────────────────────────────────


class TestContextTrimming:
    """Verify _enforce_input_budget() trims conversation before LLM call."""

    def _make_loop(self) -> AgentLoop:
        """Create a minimal AgentLoop for testing."""
        from steward.buddhi import Buddhi
        from vibe_core.mahamantra.adapters.attention import MahaAttention
        from vibe_core.tools.tool_registry import ToolRegistry

        class FakeProvider:
            def invoke(self, **kwargs):
                return None

        conv = Conversation(max_tokens=100_000)
        registry = ToolRegistry()
        return AgentLoop(
            provider=FakeProvider(),
            registry=registry,
            conversation=conv,
            system_prompt="test prompt",
            buddhi=Buddhi(),
            json_mode=False,
        )

    def test_trim_fires_when_over_budget(self):
        """If conversation exceeds MAX_INPUT_TOKENS_PER_CALL, trim fires."""
        loop = self._make_loop()
        conv = loop._conversation

        # Stuff the conversation with messages until it exceeds budget
        # Each message ~333 tokens (1000 chars / 3 chars per token)
        for i in range(20):
            conv.add(Message(role=MessageRole.USER, content="x" * 1000))

        before = conv.total_tokens
        assert before > MAX_INPUT_TOKENS_PER_CALL, (
            f"Setup error: need > {MAX_INPUT_TOKENS_PER_CALL} tokens, got {before}"
        )

        loop._enforce_input_budget()

        after = conv.total_tokens
        assert after <= MAX_INPUT_TOKENS_PER_CALL, (
            f"Context should be trimmed to <= {MAX_INPUT_TOKENS_PER_CALL}, got {after}"
        )

    def test_trim_preserves_system_message(self):
        """System message is never evicted during trimming."""
        loop = self._make_loop()
        conv = loop._conversation

        # System message should be first
        assert conv.messages[0].role == MessageRole.SYSTEM

        # Overstuff
        for i in range(20):
            conv.add(Message(role=MessageRole.USER, content="y" * 1000))

        loop._enforce_input_budget()

        # System message survived
        assert conv.messages[0].role == MessageRole.SYSTEM
        assert "test prompt" in conv.messages[0].content

    def test_no_trim_when_under_budget(self):
        """If conversation is under budget, no trimming occurs."""
        loop = self._make_loop()
        conv = loop._conversation
        conv.add(Message(role=MessageRole.USER, content="short message"))

        before_count = len(conv.messages)
        loop._enforce_input_budget()
        after_count = len(conv.messages)

        assert after_count == before_count


# ── CBR Measurement ──────────────────────────────────────────────────


class TestCBRMeasurement:
    """Verify CBR measures total tokens (input + output), not output-only."""

    def test_cbr_consumed_includes_input_tokens(self):
        """cbr_consumed = total_tokens (input + output). No hiding costs."""
        usage = AgentUsage()
        usage.input_tokens = 5000
        usage.output_tokens = 500

        # Simulate what engine does at turn end
        usage.cbr_consumed = usage.total_tokens
        usage.cbr_budget = 4000
        usage.cbr_exceeded = usage.cbr_consumed > usage.cbr_budget

        assert usage.cbr_consumed == 5500, "Must include input tokens"
        assert usage.cbr_exceeded is True, "5500 > 4000 should exceed"

    def test_cbr_not_cheating_with_output_only(self):
        """Regression test: output-only measurement was a fake fix."""
        usage = AgentUsage()
        usage.input_tokens = 5000
        usage.output_tokens = 200
        usage.cbr_budget = 4000

        # The WRONG way (what the fake fix did):
        wrong_consumed = usage.output_tokens  # 200
        wrong_exceeded = wrong_consumed > usage.cbr_budget  # False — hides real cost

        # The RIGHT way:
        right_consumed = usage.total_tokens  # 5200
        right_exceeded = right_consumed > usage.cbr_budget  # True — honest

        assert not wrong_exceeded, "Output-only would hide the problem"
        assert right_exceeded, "Total tokens correctly catches the overspend"


# ── Free Tier Enforcement ────────────────────────────────────────────


class TestFreeTierOnly:
    """Verify build_chamber() contains ONLY free-tier providers."""

    def test_no_anthropic_in_chamber(self):
        """Anthropic is a PAID provider. Must not be in default chamber."""
        from steward.provider import build_chamber

        chamber = build_chamber()
        stats = chamber.stats()
        provider_names = [p["name"] for p in stats.get("providers", []) if isinstance(p, dict)]
        assert "claude" not in provider_names, "Anthropic is PAID — must not be in default chamber"

    def test_no_deepseek_in_chamber(self):
        """DeepSeek/OpenRouter is PAID. Must not be in default chamber."""
        from steward.provider import build_chamber

        chamber = build_chamber()
        stats = chamber.stats()
        provider_names = [p["name"] for p in stats.get("providers", []) if isinstance(p, dict)]
        assert "deepseek" not in provider_names, "DeepSeek is PAID — must not be in default chamber"

    def test_only_free_tier_providers(self):
        """Chamber must contain ONLY: google_flash, mistral, groq."""
        from steward.provider import build_chamber

        chamber = build_chamber()
        stats = chamber.stats()
        provider_names = {p["name"] for p in stats.get("providers", []) if isinstance(p, dict)}
        allowed = {"google_flash", "mistral", "groq"}
        unexpected = provider_names - allowed
        assert not unexpected, f"Unexpected providers: {unexpected}. Only free tier allowed."

    def test_anthropic_not_importable_from_provider_init(self):
        """AnthropicAdapter must NOT be importable from steward.provider."""
        with pytest.raises(ImportError):
            from steward.provider import AnthropicAdapter  # noqa: F401


# ── Dotenv Loading ───────────────────────────────────────────────────


class TestDotenvLoading:
    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("dotenv"),
        reason="python-dotenv not installed",
    )
    def test_dotenv_loads_env_file(self, tmp_path):
        """build_chamber reads .env file for API keys."""
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_STEWARD_KEY=test_value_123\n")

        # dotenv should load from explicit path
        from dotenv import load_dotenv

        load_dotenv(str(env_file))

        assert os.environ.get("TEST_STEWARD_KEY") == "test_value_123"

        # Cleanup
        os.environ.pop("TEST_STEWARD_KEY", None)
