"""Tests for Vedana — the agent's sukham/duhkham health pulse.

Every test verifies BEHAVIOR: how does the health signal respond
to real operational conditions? No dataclass field checking.
"""

from steward.antahkarana.vedana import measure_vedana


class TestVedanaHealthyAgent:
    """Agent in good shape — sukham."""

    def test_all_providers_alive_is_sukham(self):
        """Full provider chamber + no errors = sukham."""
        v = measure_vedana(
            provider_alive=5,
            provider_total=5,
            recent_errors=0,
            recent_calls=10,
            context_used=0.2,
            tool_successes=8,
            tool_total=8,
        )
        assert v.is_sukham
        assert v.guna == "sattva"
        assert v.health > 0.8

    def test_fresh_agent_is_neutral(self):
        """Brand new agent with no history = neutral (not sukham, not duhkham)."""
        v = measure_vedana()
        assert not v.is_duhkham
        assert v.health >= 0.5


class TestVedanaSickAgent:
    """Agent in trouble — duhkham."""

    def test_all_providers_dead_is_duhkham(self):
        """No alive providers = severe duhkham."""
        v = measure_vedana(
            provider_alive=0,
            provider_total=5,
            recent_errors=5,
            recent_calls=5,
            context_used=0.9,
        )
        assert v.is_duhkham
        assert v.guna == "tamas"

    def test_cascading_errors_drops_health(self):
        """100% error rate tanks the health signal."""
        healthy = measure_vedana(recent_errors=0, recent_calls=10)
        sick = measure_vedana(recent_errors=10, recent_calls=10)
        assert sick.health < healthy.health
        assert sick.error_pressure < healthy.error_pressure

    def test_context_bloat_drops_health(self):
        """Full context window = context pain."""
        empty = measure_vedana(context_used=0.1)
        full = measure_vedana(context_used=0.95)
        assert full.health < empty.health
        assert full.context_pressure < empty.context_pressure


class TestVedanaComponentWeights:
    """Provider health dominates — it's the most critical component."""

    def test_provider_death_outweighs_good_tools(self):
        """Even with perfect tool execution, dead providers = pain."""
        v = measure_vedana(
            provider_alive=0,
            provider_total=5,
            tool_successes=100,
            tool_total=100,
        )
        # Provider death (0.35 weight × 0.0) should drag health down significantly
        assert v.health < 0.7

    def test_strong_synapses_boost_health(self):
        """Well-learned synaptic patterns = more confidence."""
        weak = measure_vedana(synaptic_weights=[0.3, 0.3, 0.3])
        strong = measure_vedana(synaptic_weights=[0.9, 0.85, 0.95])
        assert strong.health > weak.health
        assert strong.synaptic_confidence > weak.synaptic_confidence

    def test_no_synapses_is_neutral(self):
        """No synaptic data = neutral confidence (0.5), not penalty."""
        v = measure_vedana(synaptic_weights=None)
        assert v.synaptic_confidence == 0.5

    def test_weights_sum_to_one(self):
        """Component weights are a proper probability distribution."""
        from steward.antahkarana.vedana import (
            _W_CONTEXT,
            _W_ERROR,
            _W_PROVIDER,
            _W_SYNAPTIC,
            _W_TOOL,
        )

        total = _W_PROVIDER + _W_ERROR + _W_CONTEXT + _W_SYNAPTIC + _W_TOOL
        assert abs(total - 1.0) < 1e-9


class TestVedanaEdgeCases:
    """Operational edge cases the agent will hit."""

    def test_zero_calls_no_crash(self):
        """Zero calls/tools = no division by zero."""
        v = measure_vedana(
            recent_calls=0,
            tool_total=0,
            provider_total=0,
        )
        assert 0.0 <= v.health <= 1.0

    def test_context_over_100_percent_clamped(self):
        """Context > 100% (overflow) clamps to 0.0 context health."""
        v = measure_vedana(context_used=1.5)
        assert v.context_pressure == 0.0

    def test_health_always_in_range(self):
        """Health signal is always 0.0-1.0 regardless of inputs."""
        extreme = measure_vedana(
            provider_alive=100,
            provider_total=1,
            recent_errors=0,
            recent_calls=1000,
            context_used=0.0,
            synaptic_weights=[1.0, 1.0, 1.0],
            tool_successes=1000,
            tool_total=1000,
        )
        assert 0.0 <= extreme.health <= 1.0

    def test_single_provider_loss_is_rajas(self):
        """Losing 1 of 5 providers = rajas (concern, not crisis)."""
        v = measure_vedana(provider_alive=4, provider_total=5)
        assert v.guna in ("sattva", "rajas")
        assert not v.is_duhkham
