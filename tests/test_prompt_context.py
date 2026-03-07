"""Tests for PromptContext integration in steward."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vibe_core.di import ServiceRegistry
from vibe_core.runtime.prompt_context import PromptContext

from steward.agent import StewardAgent
from steward.services import SVC_PROMPT_CONTEXT, boot


# ── Fake LLM ─────────────────────────────────────────────────────────


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class FakeResponse:
    content: str = ""
    tool_calls: list[Any] | None = None
    usage: FakeUsage | None = None

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = FakeUsage()


class FakeLLM:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self._call_count = 0
        self.calls: list[dict[str, object]] = []

    def invoke(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        return FakeResponse(content="[no more responses]")


# ── Tests ────────────────────────────────────────────────────────────


class TestPromptContextWiring:
    def test_prompt_context_registered_at_boot(self) -> None:
        """PromptContext is registered in ServiceRegistry at boot."""
        boot()
        ctx = ServiceRegistry.get(SVC_PROMPT_CONTEXT)
        assert ctx is not None
        assert isinstance(ctx, PromptContext)

    def test_prompt_context_resolves_system_time(self) -> None:
        """PromptContext can resolve system_time."""
        boot()
        ctx: PromptContext = ServiceRegistry.require(SVC_PROMPT_CONTEXT)
        result = ctx.resolve(["system_time"])
        assert "system_time" in result
        # Should be an ISO timestamp
        assert "T" in result["system_time"]

    def test_prompt_context_resolves_current_branch(self) -> None:
        """PromptContext can resolve current git branch."""
        boot()
        ctx: PromptContext = ServiceRegistry.require(SVC_PROMPT_CONTEXT)
        result = ctx.resolve(["current_branch"])
        assert "current_branch" in result
        # In this repo it should be a branch name (not an error)
        assert not result["current_branch"].startswith("[Error")


class TestDynamicSystemPrompt:
    def test_system_prompt_includes_environment(self) -> None:
        """Default system prompt includes dynamic environment context."""
        llm = FakeLLM([FakeResponse(content="ok")])
        agent = StewardAgent(provider=llm)
        agent.run_sync("test")

        system_msg = agent.conversation.messages[0]
        assert system_msg.role == "system"
        # Should have Environment section with dynamic context
        assert "Environment:" in system_msg.content
        assert "system_time:" in system_msg.content

    def test_custom_prompt_skips_dynamic_context(self) -> None:
        """Custom system prompt does not get dynamic context appended."""
        llm = FakeLLM([FakeResponse(content="ok")])
        agent = StewardAgent(provider=llm, system_prompt="My custom prompt")
        agent.run_sync("test")

        system_msg = agent.conversation.messages[0]
        assert system_msg.content == "My custom prompt"
        assert "Environment:" not in system_msg.content

    def test_prompt_context_custom_resolver(self) -> None:
        """Custom resolvers can be registered in PromptContext."""
        boot()
        ctx: PromptContext = ServiceRegistry.require(SVC_PROMPT_CONTEXT)
        ctx.register("steward_version", lambda: "0.4.0")

        result = ctx.resolve(["steward_version"])
        assert result["steward_version"] == "0.4.0"
