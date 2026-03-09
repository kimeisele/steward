"""
VEDANA — The Agent's Own Pleasure/Pain Signal.

Sukham (pleasure) and Duhkham (pain) are listed in BG 13.6-7 as
part of the Ksetra (field) — they are MATERIAL phenomena, not
spiritual. This means they CAN and MUST be programmed.

Vedana is the single health pulse of the agent. It reads from all
internal sources and produces one 0.0-1.0 signal:
  1.0 = sukham (everything working, synapses strong, providers alive)
  0.0 = duhkham (all providers dead, errors cascading, context blown)

Sources (each contributes a weighted component):
  - Provider health: alive/total ratio + circuit breaker state
  - Error pressure: recent error rate from Buddhi
  - Context pressure: how full is the context window
  - Synaptic confidence: average weight of learned patterns
  - Tool success rate: recent tool execution outcomes

This is NOT a sense (Jnanendriya) — senses perceive the EXTERNAL world.
Vedana perceives the INTERNAL state of the agent itself.

Prerequisite for:
  - Cetana (heartbeat frequency adapts to health)
  - BuddyBubble (peers read each other's vedana)
  - Iccha/Dvesha (desire/aversion responds to pleasure/pain)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("STEWARD.VEDANA")


@dataclass(frozen=True)
class VedanaSignal:
    """Single health pulse — the agent's sukham/duhkham reading.

    health: 0.0 (duhkham/pain) to 1.0 (sukham/pleasure)
    components: breakdown of what contributed to the signal
    """

    health: float
    provider_health: float
    error_pressure: float
    context_pressure: float
    synaptic_confidence: float
    tool_success_rate: float

    @property
    def is_sukham(self) -> bool:
        """Agent is in a pleasurable/healthy state (> 0.7)."""
        return self.health > 0.7

    @property
    def is_duhkham(self) -> bool:
        """Agent is in a painful/unhealthy state (< 0.3)."""
        return self.health < 0.3

    @property
    def guna(self) -> str:
        """Derive guna from health — same scale as sense perceptions."""
        if self.health > 0.7:
            return "sattva"
        if self.health > 0.3:
            return "rajas"
        return "tamas"


# ── Component weights ────────────────────────────────────────────────
# These are NOT arbitrary — they reflect operational criticality.
# Provider health is most critical (no provider = agent is dead).
# Error pressure is second (cascading errors = agent is confused).
# Others modulate but don't kill.

_W_PROVIDER = 0.35
_W_ERROR = 0.25
_W_CONTEXT = 0.15
_W_SYNAPTIC = 0.15
_W_TOOL = 0.10

# Sanity check: weights sum to 1.0
assert abs(_W_PROVIDER + _W_ERROR + _W_CONTEXT + _W_SYNAPTIC + _W_TOOL - 1.0) < 1e-9


def measure_vedana(
    *,
    provider_alive: int = 1,
    provider_total: int = 1,
    recent_errors: int = 0,
    recent_calls: int = 1,
    context_used: float = 0.0,
    synaptic_weights: list[float] | None = None,
    tool_successes: int = 1,
    tool_total: int = 1,
) -> VedanaSignal:
    """Measure the agent's current vedana (health pulse).

    All inputs are raw counts/ratios — this function normalizes them
    into 0.0-1.0 component scores and produces the weighted health signal.

    Args:
        provider_alive: number of alive LLM providers
        provider_total: total number of configured providers
        recent_errors: errors in the current turn
        recent_calls: total calls in the current turn
        context_used: context window usage ratio (0.0-1.0)
        synaptic_weights: list of Hebbian weight values (0.0-1.0 each)
        tool_successes: successful tool executions this turn
        tool_total: total tool executions this turn
    """
    # Provider health: alive ratio (0 alive = 0.0 health, all alive = 1.0)
    p_health = provider_alive / max(provider_total, 1)

    # Error pressure: inverted error rate (no errors = 1.0, all errors = 0.0)
    e_health = 1.0 - (recent_errors / max(recent_calls, 1))

    # Context pressure: inverted (empty = 1.0, full = 0.0)
    c_health = 1.0 - min(context_used, 1.0)

    # Synaptic confidence: average weight (0.5 = neutral, > 0.5 = learned)
    if synaptic_weights:
        s_health = sum(synaptic_weights) / len(synaptic_weights)
    else:
        s_health = 0.5  # No synapses = neutral (not bad, not good)

    # Tool success rate
    t_health = tool_successes / max(tool_total, 1)

    # Weighted composite
    health = (
        _W_PROVIDER * p_health
        + _W_ERROR * e_health
        + _W_CONTEXT * c_health
        + _W_SYNAPTIC * s_health
        + _W_TOOL * t_health
    )

    # Clamp to [0.0, 1.0]
    health = max(0.0, min(1.0, health))

    signal = VedanaSignal(
        health=health,
        provider_health=p_health,
        error_pressure=e_health,
        context_pressure=c_health,
        synaptic_confidence=s_health,
        tool_success_rate=t_health,
    )

    logger.debug(
        "Vedana: %.2f (%s) — provider=%.2f error=%.2f context=%.2f synapse=%.2f tool=%.2f",
        signal.health,
        signal.guna,
        p_health,
        e_health,
        c_health,
        s_health,
        t_health,
    )

    return signal
