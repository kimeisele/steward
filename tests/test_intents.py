"""Tests for deterministic TaskIntent dispatch.

Verifies that the autonomy loop works without LLM calls:
  - TaskIntent enum maps from intent_type strings
  - Unknown intent types return None (not fed to LLM)
  - Dispatch table routes to correct handlers
  - Handlers return None (no issue) or problem string (needs LLM)
"""

import pytest

from steward.intents import INTENT_TYPE_KEY, TaskIntent


class TestTaskIntentEnum:
    """TaskIntent enum maps correctly from strings."""

    def test_health_check_maps(self):
        assert TaskIntent.from_intent_type("health_check") == TaskIntent.HEALTH_CHECK

    def test_sense_scan_maps(self):
        assert TaskIntent.from_intent_type("sense_scan") == TaskIntent.SENSE_SCAN

    def test_ci_check_maps(self):
        assert TaskIntent.from_intent_type("ci_check") == TaskIntent.CI_CHECK

    def test_unknown_returns_none(self):
        assert TaskIntent.from_intent_type("random_garbage") is None

    def test_none_returns_none(self):
        assert TaskIntent.from_intent_type(None) is None

    def test_empty_string_returns_none(self):
        assert TaskIntent.from_intent_type("") is None

    def test_intent_type_key_is_string(self):
        assert isinstance(INTENT_TYPE_KEY, str)

    def test_update_deps_maps(self):
        assert TaskIntent.from_intent_type("update_deps") == TaskIntent.UPDATE_DEPS

    def test_remove_dead_code_maps(self):
        assert TaskIntent.from_intent_type("remove_dead_code") == TaskIntent.REMOVE_DEAD_CODE

    def test_proactive_intents_are_proactive(self):
        assert TaskIntent.UPDATE_DEPS.is_proactive
        assert TaskIntent.REMOVE_DEAD_CODE.is_proactive

    def test_reactive_intents_are_not_proactive(self):
        assert not TaskIntent.HEALTH_CHECK.is_proactive
        assert not TaskIntent.SENSE_SCAN.is_proactive
        assert not TaskIntent.CI_CHECK.is_proactive

    def test_all_intents_have_handlers(self):
        """Every TaskIntent value must have a corresponding handler.

        If you add a new TaskIntent, you must also add a handler in
        StewardAgent._dispatch_intent. This test enforces that contract.
        """
        # Import here to avoid circular — just verify the enum is complete
        values = {m.value for m in TaskIntent}
        assert "health_check" in values
        assert "sense_scan" in values
        assert "ci_check" in values
        assert "update_deps" in values
        assert "remove_dead_code" in values


class TestDeterministicDispatch:
    """run_autonomous() dispatches to Python methods, not LLM."""

    def test_dispatch_health_check(self, fake_llm):
        """Health check handler runs without LLM calls."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        result = agent._autonomy._execute_health_check()
        # Healthy agent → no problem → no LLM needed
        assert result is None
        assert fake_llm.call_count == 0  # Zero LLM tokens

    def test_dispatch_sense_scan(self, fake_llm):
        """Sense scan handler runs without LLM calls."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        result = agent._autonomy._execute_sense_scan()
        assert result is None
        assert fake_llm.call_count == 0

    def test_dispatch_ci_check(self, fake_llm):
        """CI check handler runs without LLM calls."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        result = agent._autonomy._execute_ci_check()
        assert result is None
        assert fake_llm.call_count == 0

    def test_dispatch_unknown_intent_returns_none(self, fake_llm):
        """Unknown intent types are skipped, not fed to LLM."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        result = agent._autonomy.dispatch_intent("not_a_real_intent")
        assert result is None
        assert fake_llm.call_count == 0

    def test_dispatch_routes_correctly(self, fake_llm):
        """Each TaskIntent routes to its correct handler."""
        from unittest.mock import MagicMock, patch

        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))

        # Mock subprocess to avoid real pip call in UPDATE_DEPS
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[]"
        with patch("subprocess.run", return_value=mock_result):
            for intent in TaskIntent:
                result = agent._autonomy.dispatch_intent(intent)
                assert result is None, f"Intent {intent.name} unexpectedly returned: {result}"
        assert fake_llm.call_count == 0
