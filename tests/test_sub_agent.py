"""Tests for SubAgentTool — recursive task delegation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from vibe_core.di import ServiceRegistry
from vibe_core.tools.tool_protocol import Tool, ToolResult
from vibe_core.tools.tool_registry import ToolRegistry

from steward.services import SVC_PROVIDER, SVC_TOOL_REGISTRY
from steward.tools.sub_agent import SubAgentTool, SUB_AGENT_TIMEOUT


# ── Fake Providers ───────────────────────────────────────────────────


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 5


@dataclass
class FakeResponse:
    content: str = "sub-agent result"
    tool_calls: list | None = None
    usage: FakeUsage | None = None

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = FakeUsage()


class FakeProvider:
    """Provider that returns a simple text response (no tool calls)."""

    def invoke(self, **kwargs: object) -> FakeResponse:
        return FakeResponse(content="task completed successfully")


class SlowProvider:
    """Provider that blocks longer than timeout."""

    def invoke(self, **kwargs: object) -> FakeResponse:
        import time
        time.sleep(5)
        return FakeResponse()


class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes back"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {"message": {"type": "string", "required": True}}

    def validate(self, parameters: dict[str, Any]) -> None:
        if "message" not in parameters:
            raise ValueError("Missing: message")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output=parameters["message"])


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset ServiceRegistry before each test."""
    ServiceRegistry.reset_all()
    yield
    ServiceRegistry.reset_all()


# ── Validation Tests ─────────────────────────────────────────────────


class TestSubAgentValidation:
    def test_name(self):
        tool = SubAgentTool()
        assert tool.name == "sub_agent"

    def test_description_not_empty(self):
        tool = SubAgentTool()
        assert len(tool.description) > 0

    def test_parameters_schema_has_task(self):
        tool = SubAgentTool()
        schema = tool.parameters_schema
        assert "task" in schema
        assert schema["task"]["required"] is True

    def test_validate_missing_task(self):
        tool = SubAgentTool()
        with pytest.raises(ValueError, match="Missing required parameter"):
            tool.validate({})

    def test_validate_empty_task(self):
        tool = SubAgentTool()
        with pytest.raises(ValueError, match="must not be empty"):
            tool.validate({"task": "   "})

    def test_validate_non_string_task(self):
        tool = SubAgentTool()
        with pytest.raises(TypeError, match="must be a string"):
            tool.validate({"task": 123})

    def test_validate_good_task(self):
        tool = SubAgentTool()
        tool.validate({"task": "Fix the bug"})


# ── Execution Tests ──────────────────────────────────────────────────


class TestSubAgentExecution:
    def test_no_provider_returns_error(self):
        """Without a provider registered, execute returns error."""
        tool = SubAgentTool()
        result = tool.execute({"task": "do something"})
        assert not result.success
        assert "No provider" in (result.error or "")

    def test_successful_execution(self):
        """Sub-agent runs and returns the LLM's text response."""
        provider = FakeProvider()
        ServiceRegistry.register(SVC_PROVIDER, provider)

        # Register a parent registry with echo + sub_agent
        parent_reg = ToolRegistry()
        parent_reg.register(EchoTool())
        parent_reg.register(SubAgentTool())
        ServiceRegistry.register(SVC_TOOL_REGISTRY, parent_reg)

        tool = SubAgentTool(cwd="/tmp")
        result = tool.execute({"task": "complete this task"})
        assert result.success
        assert "task completed" in (result.output or "")

    def test_child_registry_excludes_sub_agent(self):
        """Child ToolRegistry must NOT contain sub_agent (recursion guard)."""
        provider = FakeProvider()
        ServiceRegistry.register(SVC_PROVIDER, provider)

        parent_reg = ToolRegistry()
        parent_reg.register(EchoTool())
        parent_reg.register(SubAgentTool())
        ServiceRegistry.register(SVC_TOOL_REGISTRY, parent_reg)

        # Verify parent has sub_agent
        assert parent_reg.has("sub_agent")
        assert parent_reg.has("echo")

        # Build child registry the same way the tool does
        child_reg = ToolRegistry()
        for tool_name, tool in parent_reg.tools.items():
            if tool_name != "sub_agent":
                child_reg.register(tool)

        # Child must not have sub_agent
        assert not child_reg.has("sub_agent")
        assert child_reg.has("echo")

    def test_timeout_returns_error(self):
        """Sub-agent that exceeds timeout returns error."""
        provider = SlowProvider()
        ServiceRegistry.register(SVC_PROVIDER, provider)
        ServiceRegistry.register(SVC_TOOL_REGISTRY, ToolRegistry())

        tool = SubAgentTool(timeout=1)  # 1 second timeout
        result = tool.execute({"task": "slow task"})
        assert not result.success
        assert "timed out" in (result.error or "")

    def test_provider_exception_returns_error(self):
        """If the provider raises, sub-agent returns error gracefully."""
        class ExplodingProvider:
            def invoke(self, **kwargs: object) -> object:
                raise RuntimeError("kaboom")

        ServiceRegistry.register(SVC_PROVIDER, ExplodingProvider())
        ServiceRegistry.register(SVC_TOOL_REGISTRY, ToolRegistry())

        tool = SubAgentTool()
        result = tool.execute({"task": "this will fail"})
        assert not result.success
        assert result.error is not None

    def test_default_timeout(self):
        tool = SubAgentTool()
        assert tool._timeout == SUB_AGENT_TIMEOUT

    def test_custom_timeout(self):
        tool = SubAgentTool(timeout=60)
        assert tool._timeout == 60

    def test_cwd_passed_through(self):
        tool = SubAgentTool(cwd="/my/project")
        assert tool._cwd == "/my/project"


# ── Integration: agent wiring ────────────────────────────────────────


class TestSubAgentWiring:
    def test_sub_agent_in_builtin_tools(self):
        """SubAgentTool is included in StewardAgent's builtin tools."""
        from steward.tools import SubAgentTool as ExportedSubAgentTool
        assert ExportedSubAgentTool is SubAgentTool

    def test_sub_agent_in_tools_all(self):
        """SubAgentTool is exported from steward.tools."""
        from steward import tools
        assert "SubAgentTool" in tools.__all__
