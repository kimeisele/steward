"""Tests for KsetraJna — the meta-observer (BuddyBubble foundation)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from steward.agent import StewardAgent
from steward.antahkarana.ksetrajna import BubbleSnapshot, KsetraJna, _compute_drift
from steward.antahkarana.vedana import VedanaSignal, measure_vedana
from steward.types import ToolUse

# ── Fake LLM ─────────────────────────────────────────────────────────


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class FakeResponse:
    content: str = ""
    tool_calls: list[Any] | None = None
    usage: FakeUsage | None = None

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = FakeUsage()


class FakeLLM:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self._i = 0

    def invoke(self, **kwargs: object) -> FakeResponse:
        if self._i < len(self._responses):
            r = self._responses[self._i]
            self._i += 1
            return r
        return FakeResponse(content="[done]")


# ── Helpers ──────────────────────────────────────────────────────────


def _make_vedana(health: float = 0.85) -> VedanaSignal:
    """Create a VedanaSignal with a specific health level."""
    return measure_vedana(
        provider_alive=1,
        provider_total=1,
        recent_errors=0 if health > 0.5 else 5,
        recent_calls=10,
        context_used=0.0 if health > 0.5 else 0.8,
        tool_successes=10 if health > 0.5 else 2,
        tool_total=10,
    )


def _make_ksetrajna(
    health: float = 0.85,
    phase: str = "ORIENT",
    rounds: int = 0,
    action: str = "research",
    tier: str = "STANDARD",
    pattern: str = "",
) -> KsetraJna:
    """Create a KsetraJna with fixed sources for testing."""
    return KsetraJna(
        vedana_source=lambda: _make_vedana(health),
        chitta_source=lambda: {
            "phase": phase,
            "rounds": rounds,
            "error_ratio": 0.0,
            "prior_reads": 0,
            "tool_distribution": {},
        },
        cetana_source=lambda: {
            "frequency_hz": 0.5,
            "consecutive_anomalies": 0,
        },
        buddhi_source=lambda: {"action": action, "tier": tier},
        gandha_source=lambda: pattern,
    )


# ── Unit Tests ───────────────────────────────────────────────────────


class TestBubbleSnapshot:
    def test_snapshot_frozen(self):
        """BubbleSnapshot is immutable."""
        kj = _make_ksetrajna()
        snap = kj.observe()
        try:
            snap.health = 0.0  # type: ignore[misc]
            assert False, "Should have raised"
        except AttributeError:
            pass  # Frozen dataclass

    def test_snapshot_fields(self):
        """Snapshot has all required fields."""
        kj = _make_ksetrajna(phase="EXECUTE", action="implement", tier="PRO")
        snap = kj.observe()
        assert snap.phase == "EXECUTE"
        assert snap.action == "implement"
        assert snap.tier == "PRO"
        assert snap.health > 0.0
        assert snap.guna in ("sattva", "rajas", "tamas")
        assert snap.timestamp > 0


class TestKsetraJna:
    def test_observe_produces_snapshot(self):
        kj = _make_ksetrajna()
        snap = kj.observe()
        assert isinstance(snap, BubbleSnapshot)
        assert kj.last is snap
        assert len(kj.history) == 1

    def test_history_bounded(self):
        """History is bounded to max_history."""
        kj = _make_ksetrajna()
        kj._history = kj._history.__class__(maxlen=5)
        for _ in range(10):
            kj.observe()
        assert len(kj.history) == 5

    def test_drift_no_history(self):
        """Drift is 0.0 with no observations."""
        kj = _make_ksetrajna()
        assert kj.drift() == 0.0

    def test_drift_identical_snapshots(self):
        """Identical observations produce zero drift."""
        kj = _make_ksetrajna()
        kj.observe()
        kj.observe()
        assert kj.drift() == 0.0

    def test_drift_different_snapshots(self):
        """Different observations produce non-zero drift."""
        snap_a = BubbleSnapshot(
            timestamp=1.0,
            health=0.9,
            guna="sattva",
            phase="ORIENT",
            round=1,
            error_ratio=0.0,
            files_read=0,
            files_written=0,
            action="research",
            tier="FLASH",
            heartbeat_hz=0.5,
            anomaly_count=0,
            last_pattern="",
        )
        snap_b = BubbleSnapshot(
            timestamp=2.0,
            health=0.3,
            guna="tamas",
            phase="EXECUTE",
            round=5,
            error_ratio=0.5,
            files_read=3,
            files_written=1,
            action="implement",
            tier="PRO",
            heartbeat_hz=2.0,
            anomaly_count=3,
            last_pattern="consecutive_errors",
        )
        d = _compute_drift(snap_a, snap_b)
        assert d > 0.5  # Major change

    def test_is_stuck_insufficient_history(self):
        """Not stuck when history is too short."""
        kj = _make_ksetrajna()
        kj.observe()
        kj.observe()
        assert not kj.is_stuck(window=5)

    def test_is_stuck_after_identical_observations(self):
        """Stuck when all observations are identical."""
        kj = _make_ksetrajna()
        for _ in range(6):
            kj.observe()
        assert kj.is_stuck(window=5, threshold=0.05)

    def test_not_stuck_when_progressing(self):
        """Not stuck when phase and round change each observation."""
        phases = ["ORIENT", "ORIENT", "EXECUTE", "EXECUTE", "VERIFY", "COMPLETE"]
        idx = [0]

        def varying_chitta() -> dict:
            i = min(idx[0], len(phases) - 1)
            return {"phase": phases[i], "rounds": i, "error_ratio": 0.0, "prior_reads": 0, "tool_distribution": {}}

        kj = KsetraJna(
            vedana_source=lambda: _make_vedana(0.85),
            chitta_source=varying_chitta,
            cetana_source=lambda: {"frequency_hz": 0.5, "consecutive_anomalies": 0},
            buddhi_source=lambda: {"action": "research", "tier": "STANDARD"},
            gandha_source=lambda: "",
        )
        for _ in range(6):
            idx[0] += 1
            kj.observe()
        assert not kj.is_stuck(window=5, threshold=0.05)

    def test_trend_improving(self):
        """Trend is 'improving' when health increases."""
        health_values = [0.5, 0.6, 0.7, 0.8, 0.9]
        idx = [0]

        def improving_vedana() -> VedanaSignal:
            h = health_values[min(idx[0], len(health_values) - 1)]
            idx[0] += 1
            return _make_vedana(h)

        kj = KsetraJna(
            vedana_source=improving_vedana,
            chitta_source=lambda: {
                "phase": "ORIENT",
                "rounds": 0,
                "error_ratio": 0.0,
                "prior_reads": 0,
                "tool_distribution": {},
            },
            cetana_source=lambda: {"frequency_hz": 0.5, "consecutive_anomalies": 0},
            buddhi_source=lambda: {"action": "research", "tier": "STANDARD"},
            gandha_source=lambda: "",
        )
        for _ in range(5):
            kj.observe()
        assert kj.trend() == "improving"

    def test_trend_degrading(self):
        """Trend is 'degrading' when health decreases."""
        health_values = [0.9, 0.8, 0.7, 0.6, 0.5]
        idx = [0]

        def degrading_vedana() -> VedanaSignal:
            h = health_values[min(idx[0], len(health_values) - 1)]
            idx[0] += 1
            return _make_vedana(h)

        kj = KsetraJna(
            vedana_source=degrading_vedana,
            chitta_source=lambda: {
                "phase": "ORIENT",
                "rounds": 0,
                "error_ratio": 0.0,
                "prior_reads": 0,
                "tool_distribution": {},
            },
            cetana_source=lambda: {"frequency_hz": 0.5, "consecutive_anomalies": 0},
            buddhi_source=lambda: {"action": "research", "tier": "STANDARD"},
            gandha_source=lambda: "",
        )
        for _ in range(5):
            kj.observe()
        assert kj.trend() == "degrading"

    def test_trend_stable(self):
        """Trend is 'stable' when health doesn't change."""
        kj = _make_ksetrajna(health=0.85)
        for _ in range(5):
            kj.observe()
        assert kj.trend() == "stable"

    def test_digest_format(self):
        """Digest produces peer-readable one-liner."""
        kj = _make_ksetrajna(phase="EXECUTE", action="implement")
        kj.observe()
        d = kj.digest()
        assert "EXECUTE" in d
        assert "h=" in d
        assert "hz=" in d

    def test_digest_no_observations(self):
        """Digest handles no observations gracefully."""
        kj = _make_ksetrajna()
        assert kj.digest() == "no-observation"

    def test_stats_dict(self):
        """Stats returns valid observability dict."""
        kj = _make_ksetrajna()
        kj.observe()
        s = kj.stats()
        assert "observations" in s
        assert "drift" in s
        assert "trend" in s
        assert "is_stuck" in s
        assert "digest" in s
        assert "last_snapshot" in s
        assert s["observations"] == 1


# ── Integration Tests ────────────────────────────────────────────────


class TestKsetraJnaIntegration:
    def test_agent_has_ksetrajna(self):
        """Agent has ksetrajna property."""
        llm = FakeLLM([])
        agent = StewardAgent(provider=llm)
        assert hasattr(agent, "ksetrajna")
        assert isinstance(agent.ksetrajna, KsetraJna)

    def test_observe_after_run(self):
        """KsetraJna has observation after agent run."""
        llm = FakeLLM([FakeResponse(content="Hello!")])
        agent = StewardAgent(provider=llm)
        agent.run_sync("Hi")
        # End-of-turn observation should have been recorded
        assert agent.ksetrajna.last is not None
        assert isinstance(agent.ksetrajna.last, BubbleSnapshot)

    def test_ksetrajna_in_get_state(self):
        """get_state() includes ksetrajna stats (no heartbeat crash)."""
        llm = FakeLLM([])
        agent = StewardAgent(provider=llm)
        state = agent.get_state()
        assert "ksetrajna" in state
        assert isinstance(state["ksetrajna"], dict)
        # Old broken reference should be gone
        assert "heartbeat_state" not in state

    def test_tool_call_updates_observation(self):
        """KsetraJna captures state after tool calls."""
        tc = ToolUse(id="c1", name="bash", parameters={"command": "echo test"})
        llm = FakeLLM(
            [
                FakeResponse(content="", tool_calls=[tc]),
                FakeResponse(content="Done"),
            ]
        )
        agent = StewardAgent(provider=llm)
        agent.run_sync("Run something")
        snap = agent.ksetrajna.last
        assert snap is not None
        assert snap.round >= 0
