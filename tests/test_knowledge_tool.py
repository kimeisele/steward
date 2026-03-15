"""Tests for KnowledgeGraph pull tool (query_codebase).

Verifies the pull pattern: agent queries KG on demand via tool,
instead of pushing KG context into the system prompt.
"""

import pytest

from steward.tools.knowledge import KnowledgeGraphTool
from vibe_core.di import ServiceRegistry


class TestKnowledgeGraphTool:
    """KnowledgeGraphTool — pull-based codebase understanding."""

    def test_tool_name(self):
        tool = KnowledgeGraphTool()
        assert tool.name == "query_codebase"

    def test_tool_has_description(self):
        tool = KnowledgeGraphTool()
        assert "knowledge graph" in tool.description.lower()

    def test_requires_query_parameter(self):
        tool = KnowledgeGraphTool()
        with pytest.raises(ValueError, match="query"):
            tool.validate({})

    def test_valid_parameters_pass(self):
        tool = KnowledgeGraphTool()
        tool.validate({"query": "authentication"})  # Should not raise

    def test_returns_graceful_when_kg_not_available(self):
        """When KG service is not registered, returns helpful fallback."""
        tool = KnowledgeGraphTool()
        result = tool.execute({"query": "authentication"})
        assert result.success is True
        assert "not available" in result.output

    def test_returns_results_when_kg_available(self):
        """When KG is registered and has data, returns context."""
        from steward.services import SVC_KNOWLEDGE_GRAPH, boot

        # Boot registers a _LazyKnowledgeGraph
        boot(tools=[])
        tool = KnowledgeGraphTool()
        result = tool.execute({"query": "nonexistent_concept_xyz"})
        # LazyKG scans tmp_path (empty) → no results, but doesn't crash
        assert result.success is True

    def test_tool_in_builtin_provider(self):
        """KnowledgeGraphTool is included in BuiltinToolProvider."""
        import tempfile

        from steward.tool_providers import BuiltinToolProvider

        provider = BuiltinToolProvider()
        tools = provider.provide(tempfile.mkdtemp())
        names = {t.name for t in tools}
        assert "query_codebase" in names
