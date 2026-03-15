"""Tests for GAD-000 compliance — the operator inversion principle.

If it does not exist as protocol, it does not exist.
StewardAgent MUST be GAD-000 compliant from day 1.
"""

from __future__ import annotations

from tests.fakes import FakeLLM, FakeResponse

from steward.agent import StewardAgent
from vibe_core.mahamantra.protocols._gad import GADBase, GADProtocol


class TestGADCompliance:
    """StewardAgent MUST implement GAD-000."""

    def test_agent_is_gad_base(self):
        """StewardAgent inherits from GADBase."""
        agent = StewardAgent(provider=FakeLLM(), system_prompt="test")
        assert isinstance(agent, GADBase)

    def test_agent_is_gad_protocol(self):
        """StewardAgent satisfies GADProtocol (runtime_checkable)."""
        agent = StewardAgent(provider=FakeLLM(), system_prompt="test")
        assert isinstance(agent, GADProtocol)

    def test_discover_returns_capabilities(self):
        """discover() returns machine-readable capability description."""
        agent = StewardAgent(provider=FakeLLM(), system_prompt="test")
        info = agent.discover()

        assert info["name"] == "StewardAgent"
        assert info["type"] == "superagent"
        assert "tools" in info
        assert isinstance(info["tools"], list)
        assert len(info["tools"]) > 0  # has builtin tools
        assert info["architecture"] == "sankhya_25"
        assert info["kshetra_elements"] == 25
        # BG 13.6-7 field mapping
        assert "antahkarana" in info
        assert "manas" in info["antahkarana"]
        assert "buddhi" in info["antahkarana"]
        assert "jnanendriyas" in info
        assert "karmendriyas" in info
        assert "ksetrajna" in info
        assert "kshetra_properties" in info
        assert info["kshetra_properties"]["vedana"] is True
        assert info["kshetra_properties"]["cetana"] is True

    def test_get_state_returns_observability(self):
        """get_state() returns current agent state."""
        agent = StewardAgent(provider=FakeLLM(), system_prompt="test")
        state = agent.get_state()

        assert "conversation_messages" in state
        assert "conversation_tokens" in state
        assert "context_budget_pct" in state
        assert "tools_registered" in state
        assert "ksetrajna" in state
        assert "safety_guard_active" in state
        assert state["safety_guard_active"] is True

    def test_ksetrajna_observable(self):
        """KsetraJna meta-observer is accessible and produces stats."""
        agent = StewardAgent(provider=FakeLLM(), system_prompt="test")
        kj_stats = agent.get_state()["ksetrajna"]
        assert isinstance(kj_stats, dict)
        assert "observations" in kj_stats
        assert "digest" in kj_stats

    def test_audit_passes(self):
        """GAD-000 audit passes for StewardAgent."""
        agent = StewardAgent(provider=FakeLLM(), system_prompt="test")
        # Chant once to activate heartbeat
        agent.chant()

        audit = agent.audit()

        # The 6 criteria
        assert audit.discoverability is True
        assert audit.observability is True
        assert audit.parseability is True
        assert audit.composability is True
        assert audit.idempotency is True

        # Dharma tests
        assert audit.tapas is True  # resources constrained
        assert audit.saucam is True  # safety guard active

        # Score
        assert audit.criteria_score >= 5  # at least 5/6

    def test_tapas_fails_when_over_budget(self):
        """Tapas (austerity) fails when context exceeds budget."""
        agent = StewardAgent(
            provider=FakeLLM(),
            system_prompt="test",
            max_context_tokens=10,  # tiny budget
        )
        # Force context over budget
        from steward.types import Message

        for i in range(20):
            agent._conversation.messages.append(Message(role="user", content=f"Message {i} " * 50))
        assert agent.test_tapas() is False

    def test_is_healthy_after_chant(self):
        """Agent is healthy after chanting (heartbeat active)."""
        agent = StewardAgent(provider=FakeLLM(), system_prompt="test")
        agent.chant()
        assert agent.is_healthy() is True

    def test_state_changes_after_run(self):
        """get_state() reflects changes after running a task."""
        agent = StewardAgent(provider=FakeLLM(), system_prompt="test")

        state_before = agent.get_state()
        msg_count_before = state_before["conversation_messages"]

        agent.run_sync("Hello")

        state_after = agent.get_state()
        # Should have more messages now (user + assistant)
        assert state_after["conversation_messages"] > msg_count_before
