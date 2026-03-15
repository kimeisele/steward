"""Tests for PromptContext integration in steward."""

from __future__ import annotations

from steward.agent import StewardAgent
from steward.services import SVC_PROMPT_CONTEXT, boot
from tests.fakes import FakeLLM, FakeResponse
from vibe_core.di import ServiceRegistry
from vibe_core.runtime.prompt_context import PromptContext

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
    def test_system_prompt_includes_cwd(self) -> None:
        """Default system prompt includes working directory."""
        llm = FakeLLM([FakeResponse(content="ok")])
        agent = StewardAgent(provider=llm)
        agent.run_sync("test")

        system_msg = agent.conversation.messages[0]
        assert system_msg.role == "system"
        assert "cwd:" in system_msg.content

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
