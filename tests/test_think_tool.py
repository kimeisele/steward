"""Tests for ThinkTool — neuro-symbolic reasoning bridge."""

from __future__ import annotations

from steward.tools.think import ThinkTool, _build_symbolic_feedback


class TestThinkToolBasic:
    """ThinkTool without Antahkarana wiring — graceful fallback."""

    def test_tool_properties(self):
        tool = ThinkTool()
        assert tool.name == "think"
        assert "hypothesis" in tool.parameters_schema
        assert "action" in tool.parameters_schema

    def test_validate_requires_hypothesis(self):
        tool = ThinkTool()
        try:
            tool.validate({})
            assert False, "Should have raised"
        except ValueError:
            pass

    def test_validate_rejects_empty(self):
        tool = ThinkTool()
        try:
            tool.validate({"hypothesis": "   "})
            assert False, "Should have raised"
        except ValueError:
            pass

    def test_execute_without_antahkarana(self):
        """Without wiring, returns basic acknowledgment."""
        tool = ThinkTool()
        result = tool.execute({"hypothesis": "The CI is failing due to missing deps"})
        assert result.success
        assert "Think" in result.output
        assert "Proceed" in result.output

    def test_execute_with_action(self):
        tool = ThinkTool()
        result = tool.execute({
            "hypothesis": "Need to fix imports",
            "action": "edit context_bridge.py",
        })
        assert result.success
        assert "Think" in result.output


class TestSymbolicFeedback:
    """Test the symbolic feedback builder."""

    def test_empty_sources(self):
        feedback = _build_symbolic_feedback(
            hypothesis="test",
            planned_action="",
            chitta=None,
            gandha=None,
            vedana_source=None,
            ksetrajna=None,
            maha_buddhi=None,
        )
        assert "guidance" in feedback
        assert "Proceed" in feedback["guidance"]

    def test_with_mock_chitta(self):
        """Chitta provides phase and memory info."""

        class MockChitta:
            impressions = []
            phase = "EXECUTE"

        feedback = _build_symbolic_feedback(
            hypothesis="test",
            planned_action="edit file.py",
            chitta=MockChitta(),
            gandha=None,
            vedana_source=None,
            ksetrajna=None,
            maha_buddhi=None,
        )
        assert feedback["phase"] == "EXECUTE"
        assert "memory" in feedback


class TestThinkToolInAgent:
    """Integration: ThinkTool in agent tool registry."""

    def test_think_in_builtin_tools(self):
        from steward.tool_providers import BuiltinToolProvider

        provider = BuiltinToolProvider()
        tools = provider.provide(cwd="/tmp")
        names = [t.name for t in tools]
        assert "think" in names

    def test_think_registered_in_observe_namespace(self):
        from steward.buddhi import ToolNamespace, _NAMESPACE_TOOLS

        assert "think" in _NAMESPACE_TOOLS[ToolNamespace.OBSERVE]
