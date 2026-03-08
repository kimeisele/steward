"""Tests for MahaAttention O(1) tool routing in Steward services."""

from __future__ import annotations

from typing import Any

from steward.services import SVC_ATTENTION, SVC_TOOL_REGISTRY, boot
from vibe_core.di import ServiceRegistry
from vibe_core.mahamantra.adapters.attention import MahaAttention
from vibe_core.tools.tool_protocol import Tool, ToolResult


class DummyTool(Tool):
    def __init__(self, tool_name: str) -> None:
        super().__init__()
        self._name = tool_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Dummy {self._name}"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {}

    def validate(self, parameters: dict[str, Any]) -> None:
        pass

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output=self._name)


class TestMahaAttentionRouting:
    def test_tools_memorized_at_boot(self):
        """boot() memorizes all tool names in MahaAttention."""
        tools = [DummyTool("alpha"), DummyTool("beta"), DummyTool("gamma")]
        boot(tools=tools)

        attention: MahaAttention = ServiceRegistry.require(SVC_ATTENTION)
        assert attention.registered_intents == 3

    def test_o1_tool_lookup(self):
        """MahaAttention resolves tool name to Tool instance in O(1)."""
        alpha = DummyTool("alpha")
        beta = DummyTool("beta")
        boot(tools=[alpha, beta])

        attention: MahaAttention = ServiceRegistry.require(SVC_ATTENTION)

        result = attention.attend("alpha")
        assert result.found
        assert result.handler is alpha
        assert result.ops_saved > 0

        result = attention.attend("beta")
        assert result.found
        assert result.handler is beta

    def test_unknown_tool_not_found(self):
        """Unknown tool name returns found=False."""
        boot(tools=[DummyTool("known")])

        attention: MahaAttention = ServiceRegistry.require(SVC_ATTENTION)
        result = attention.attend("unknown_tool_xyz")
        assert not result.found
        assert result.handler is None

    def test_registry_and_attention_consistent(self):
        """ToolRegistry and MahaAttention have the same tools."""
        tools = [DummyTool("read_file"), DummyTool("bash"), DummyTool("glob")]
        boot(tools=tools)

        from vibe_core.tools.tool_registry import ToolRegistry

        registry: ToolRegistry = ServiceRegistry.require(SVC_TOOL_REGISTRY)
        attention: MahaAttention = ServiceRegistry.require(SVC_ATTENTION)

        for name in registry.list_tools():
            result = attention.attend(name)
            assert result.found, f"Tool '{name}' not found in attention"
            assert result.handler is registry.get(name)

    def test_stats_tracking(self):
        """Attention tracks query stats."""
        boot(tools=[DummyTool("test_tool")])
        attention: MahaAttention = ServiceRegistry.require(SVC_ATTENTION)

        attention.attend("test_tool")
        attention.attend("test_tool")
        attention.attend("nonexistent")

        stats = attention.stats()
        assert stats.queries_resolved == 3
        assert stats.cache_hits == 2  # 2 hits for test_tool
