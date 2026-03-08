"""Tests for steward/services.py — boot(), integrity, tool_descriptions_for_llm()."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from vibe_core.di import ServiceRegistry
from vibe_core.tools.tool_protocol import Tool, ToolResult

from steward.services import (
    SVC_ATTENTION,
    SVC_EVENT_BUS,
    SVC_FEEDBACK,
    SVC_INTEGRITY,
    SVC_MEMORY,
    SVC_NARASIMHA,
    SVC_PROMPT_CONTEXT,
    SVC_PROVIDER,
    SVC_SAFETY_GUARD,
    SVC_SIGNAL_BUS,
    SVC_TOOL_REGISTRY,
    boot,
    tool_descriptions_for_llm,
)


class _DummyTool(Tool):
    """Minimal tool for test registration."""

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "A test tool"

    @property
    def parameters_schema(self) -> dict:
        return {
            "arg": {
                "type": "string",
                "required": True,
                "description": "A required arg",
            },
            "opt": {
                "type": "integer",
                "required": False,
                "description": "An optional arg",
            },
        }

    def validate(self, parameters: dict) -> None:
        if "arg" not in parameters:
            raise ValueError("Missing arg")

    def execute(self, parameters: dict) -> ToolResult:
        return ToolResult(success=True, output="ok")


class TestBoot:
    """Test the boot() DI wiring function."""

    def test_boot_returns_service_registry(self):
        result = boot(tools=[_DummyTool()])
        assert result is ServiceRegistry

    def test_boot_registers_tool_registry(self):
        boot(tools=[_DummyTool()])
        registry = ServiceRegistry.get(SVC_TOOL_REGISTRY)
        assert registry is not None
        assert len(registry) == 1

    def test_boot_registers_safety_guard(self):
        boot(tools=[_DummyTool()])
        guard = ServiceRegistry.get(SVC_SAFETY_GUARD)
        assert guard is not None

    def test_boot_registers_attention(self):
        boot(tools=[_DummyTool()])
        attention = ServiceRegistry.get(SVC_ATTENTION)
        assert attention is not None

    def test_boot_registers_feedback(self):
        boot(tools=[_DummyTool()])
        feedback = ServiceRegistry.get(SVC_FEEDBACK)
        assert feedback is not None

    def test_boot_registers_signal_bus(self):
        boot(tools=[_DummyTool()])
        bus = ServiceRegistry.get(SVC_SIGNAL_BUS)
        assert bus is not None

    def test_boot_registers_memory(self):
        boot(tools=[_DummyTool()])
        memory = ServiceRegistry.get(SVC_MEMORY)
        assert memory is not None

    def test_boot_registers_event_bus(self):
        boot(tools=[_DummyTool()])
        event_bus = ServiceRegistry.get(SVC_EVENT_BUS)
        assert event_bus is not None

    def test_boot_registers_narasimha(self):
        boot(tools=[_DummyTool()])
        narasimha = ServiceRegistry.get(SVC_NARASIMHA)
        assert narasimha is not None

    def test_boot_registers_prompt_context(self):
        boot(tools=[_DummyTool()])
        ctx = ServiceRegistry.get(SVC_PROMPT_CONTEXT)
        assert ctx is not None

    def test_boot_registers_integrity(self):
        boot(tools=[_DummyTool()])
        checker = ServiceRegistry.get(SVC_INTEGRITY)
        assert checker is not None

    def test_boot_with_provider(self):
        provider = MagicMock()
        provider.invoke = MagicMock()
        boot(tools=[_DummyTool()], provider=provider)
        result = ServiceRegistry.get(SVC_PROVIDER)
        assert result is provider

    def test_boot_without_provider(self):
        boot(tools=[_DummyTool()])
        # Provider not registered — get() returns None or raises
        result = ServiceRegistry.get(SVC_PROVIDER)
        assert result is None

    def test_boot_wires_feedback_to_provider(self):
        provider = MagicMock()
        provider.invoke = MagicMock()
        provider.set_feedback = MagicMock()
        boot(tools=[_DummyTool()], provider=provider)
        provider.set_feedback.assert_called_once()

    def test_boot_no_tools(self):
        """Boot with no tools should work but integrity check warns."""
        boot(tools=[])  # Should not raise


class TestIntegrity:
    """Test integrity check functions."""

    def test_integrity_passes_with_tools(self):
        boot(tools=[_DummyTool()])
        checker = ServiceRegistry.get(SVC_INTEGRITY)
        report = checker.check_all()
        assert report.passed_count >= 1

    def test_integrity_with_provider(self):
        provider = MagicMock()
        provider.invoke = MagicMock()
        boot(tools=[_DummyTool()], provider=provider)
        checker = ServiceRegistry.get(SVC_INTEGRITY)
        report = checker.check_all()
        assert report.passed_count >= 2  # tools + provider


class TestToolDescriptionsForLLM:
    """Test the OpenAI function-calling format conversion."""

    def test_single_tool_conversion(self):
        boot(tools=[_DummyTool()])
        registry = ServiceRegistry.get(SVC_TOOL_REGISTRY)
        descs = tool_descriptions_for_llm(registry)
        assert len(descs) == 1
        func = descs[0]
        assert func["type"] == "function"
        assert func["function"]["name"] == "dummy"
        params = func["function"]["parameters"]
        assert params["type"] == "object"
        assert "arg" in params["properties"]
        assert "opt" in params["properties"]
        assert "arg" in params["required"]
        assert "opt" not in params["required"]

    def test_descriptions_include_types(self):
        boot(tools=[_DummyTool()])
        registry = ServiceRegistry.get(SVC_TOOL_REGISTRY)
        descs = tool_descriptions_for_llm(registry)
        props = descs[0]["function"]["parameters"]["properties"]
        assert props["arg"]["type"] == "string"
        assert props["opt"]["type"] == "integer"

    def test_empty_registry(self):
        boot(tools=[])
        registry = ServiceRegistry.get(SVC_TOOL_REGISTRY)
        descs = tool_descriptions_for_llm(registry)
        assert descs == []
