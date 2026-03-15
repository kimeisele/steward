"""Tests for Cetana — the agent's autonomous heartbeat (BG 13.6-7).

Every test verifies BEHAVIOR: does the heartbeat respond correctly
to vedana health signals? No field inspection, no dataclass noise.

Uses polling with timeout instead of fixed sleep() delays
to avoid flaky failures in CI environments.
"""

import time

from steward.antahkarana.vedana import VedanaSignal, measure_vedana
from steward.cetana import (
    GAJENDRA,
    SADHANA,
    SAMADHI,
    Cetana,
    CetanaBeat,
    Phase,
)


def _make_vedana(health: float) -> VedanaSignal:
    """Create a VedanaSignal with a specific health value.

    Uses measure_vedana with tuned inputs to hit the desired health range.
    """
    if health >= 0.9:
        return measure_vedana(
            provider_alive=5,
            provider_total=5,
            recent_errors=0,
            recent_calls=10,
            context_used=0.0,
            synaptic_weights=[0.9, 0.9, 0.9],
            tool_successes=10,
            tool_total=10,
        )
    elif health <= 0.15:
        return measure_vedana(
            provider_alive=0,
            provider_total=5,
            recent_errors=10,
            recent_calls=10,
            context_used=0.95,
            synaptic_weights=[0.1, 0.1, 0.1],
            tool_successes=0,
            tool_total=10,
        )
    else:
        # Mid-range — defaults give ~0.6-0.7
        return measure_vedana()


def _poll(condition, timeout=3.0, interval=0.05):
    """Poll until condition() is truthy or timeout expires. Returns final value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        val = condition()
        if val:
            return val
        time.sleep(interval)
    return condition()


class TestCetanaLifecycle:
    """Start, beat, stop — the basic life cycle."""

    def test_heartbeat_starts_and_stops(self):
        """Cetana can start and stop without crashing."""
        cetana = Cetana(vedana_source=lambda: _make_vedana(0.9))
        cetana.start()
        assert cetana.is_alive
        cetana.stop()
        assert not cetana.is_alive

    def test_beats_accumulate(self):
        """Running cetana produces beats over time."""
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.9),
            frequency_hz=20.0,  # Fast for testing
        )
        cetana.start()
        assert _poll(lambda: cetana.total_beats >= 2)
        cetana.stop()
        assert cetana.total_beats >= 2

    def test_last_beat_available(self):
        """After running, last_beat contains the most recent snapshot."""
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.9),
            frequency_hz=20.0,
        )
        assert cetana.last_beat is None
        cetana.start()
        _poll(lambda: cetana.last_beat is not None)
        cetana.stop()
        beat = cetana.last_beat
        assert beat is not None
        assert isinstance(beat, CetanaBeat)
        assert beat.beat_number == cetana.total_beats

    def test_double_start_is_idempotent(self):
        """Calling start() twice doesn't create a second thread."""
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.9),
            frequency_hz=20.0,
        )
        cetana.start()
        thread1 = cetana._thread
        cetana.start()  # Second call — should be no-op
        assert cetana._thread is thread1
        cetana.stop()

    def test_stop_before_start_is_safe(self):
        """Stopping a never-started cetana doesn't crash."""
        cetana = Cetana(vedana_source=lambda: _make_vedana(0.9))
        cetana.stop()  # Should not raise


class TestCetanaFrequencyAdaptation:
    """Frequency adapts to vedana health — the core adaptive behavior."""

    def test_healthy_agent_slows_down(self):
        """High health → frequency moves toward SAMADHI (slow)."""
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.9),
            frequency_hz=SADHANA,
        )
        cetana.start()
        _poll(lambda: cetana.total_beats >= 5)
        cetana.stop()
        # After several beats of healthy signal, frequency should drop
        assert cetana.frequency_hz < SADHANA

    def test_sick_agent_speeds_up(self):
        """Low health → frequency moves toward GAJENDRA (fast)."""
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.15),
            frequency_hz=SADHANA,
        )
        cetana.start()
        _poll(lambda: cetana.total_beats >= 5)
        cetana.stop()
        # After several beats of sick signal, frequency should increase
        assert cetana.frequency_hz > SADHANA

    def test_frequency_adapts_direction_to_health(self):
        """_adapt_frequency moves toward GAJENDRA on low health, SAMADHI on high."""
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.9),
            frequency_hz=SADHANA,
        )
        # Simulate several adaptation steps at low health
        for _ in range(10):
            cetana._adapt_frequency(0.1)
        freq_sick = cetana.frequency_hz

        # Reset and adapt at high health
        with cetana._lock:
            cetana.frequency_hz = SADHANA
        for _ in range(10):
            cetana._adapt_frequency(0.95)
        freq_healthy = cetana.frequency_hz

        assert freq_sick > SADHANA  # Moved toward GAJENDRA
        assert freq_healthy < SADHANA  # Moved toward SAMADHI

    def test_frequency_stays_bounded(self):
        """Frequency never exceeds GAJENDRA or drops below SAMADHI."""
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.15),
            frequency_hz=SADHANA,
        )
        cetana.start()
        _poll(lambda: cetana.total_beats >= 10)
        cetana.stop()
        # EMA smoothing means it approaches but doesn't overshoot
        assert cetana.frequency_hz <= GAJENDRA + 0.01
        assert cetana.frequency_hz >= SAMADHI - 0.01


class TestCetanaAnomalyDetection:
    """Anomaly detection — the alarm system."""

    def test_anomaly_fires_callback(self):
        """Health below threshold triggers on_anomaly callback."""
        anomalies = []
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.15),
            on_anomaly=lambda beat: anomalies.append(beat),
            frequency_hz=20.0,
        )
        cetana.start()
        _poll(lambda: len(anomalies) >= 1)
        cetana.stop()
        assert len(anomalies) >= 1
        assert all(b.anomaly for b in anomalies)

    def test_healthy_agent_no_anomalies(self):
        """Health above threshold never triggers anomaly."""
        anomalies = []
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.9),
            on_anomaly=lambda beat: anomalies.append(beat),
            frequency_hz=20.0,
        )
        cetana.start()
        _poll(lambda: cetana.total_beats >= 5)
        cetana.stop()
        assert len(anomalies) == 0

    def test_consecutive_anomalies_tracked(self):
        """Consecutive anomalies count up, reset on recovery."""
        health = [0.15]

        def dynamic_vedana():
            return _make_vedana(health[0])

        cetana = Cetana(
            vedana_source=dynamic_vedana,
            frequency_hz=20.0,
        )
        cetana.start()
        _poll(lambda: cetana.stats()["consecutive_anomalies"] >= 1)

        # Recover
        health[0] = 0.9
        _poll(lambda: cetana.stats()["consecutive_anomalies"] == 0)
        cetana.stop()
        assert cetana.stats()["consecutive_anomalies"] == 0

    def test_no_callback_means_silent_anomaly(self):
        """Anomaly without callback still marks the beat, just no callback."""
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.15),
            on_anomaly=None,
            frequency_hz=20.0,
        )
        cetana.start()
        _poll(lambda: cetana.last_beat is not None)
        cetana.stop()
        assert cetana.last_beat is not None
        assert cetana.last_beat.anomaly is True


class TestCetanaPhaseRotation:
    """4-phase MURALI cycle — GENESIS → DHARMA → KARMA → MOKSHA → repeat."""

    def test_phases_rotate_in_order(self):
        """Each beat advances to the next phase."""
        phases_seen = []
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.9),
            on_phase=lambda phase, beat: phases_seen.append(phase),
            frequency_hz=20.0,
        )
        cetana.start()
        _poll(lambda: len(phases_seen) >= 8)
        cetana.stop()
        # First 4 should be the full cycle
        assert phases_seen[:4] == [Phase.GENESIS, Phase.DHARMA, Phase.KARMA, Phase.MOKSHA]
        # Next 4 repeat
        assert phases_seen[4:8] == [Phase.GENESIS, Phase.DHARMA, Phase.KARMA, Phase.MOKSHA]

    def test_beat_carries_phase(self):
        """CetanaBeat.phase matches the phase when it was produced."""
        beats = []
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.9),
            on_phase=lambda phase, beat: beats.append(beat),
            frequency_hz=20.0,
        )
        cetana.start()
        _poll(lambda: len(beats) >= 4)
        cetana.stop()
        assert beats[0].phase == Phase.GENESIS
        assert beats[1].phase == Phase.DHARMA
        assert beats[2].phase == Phase.KARMA
        assert beats[3].phase == Phase.MOKSHA

    def test_phase_in_stats(self):
        """stats() reports current phase name."""
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.9),
            frequency_hz=20.0,
        )
        # Before start — default is GENESIS
        assert cetana.stats()["phase"] == "GENESIS"
        cetana.start()
        _poll(lambda: cetana.total_beats >= 1)
        cetana.stop()
        # After at least one beat, phase has advanced
        assert cetana.stats()["phase"] in {"GENESIS", "DHARMA", "KARMA", "MOKSHA"}

    def test_no_on_phase_callback_still_rotates(self):
        """Phase rotation works even without on_phase callback."""
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.9),
            on_phase=None,
            frequency_hz=20.0,
        )
        cetana.start()
        _poll(lambda: cetana.total_beats >= 4)
        cetana.stop()
        # After 4 beats starting from GENESIS, we're back to GENESIS
        assert cetana.stats()["phase"] == "GENESIS"


class TestCetanaObservability:
    """Stats and history — the window into the heartbeat."""

    def test_stats_before_any_beats(self):
        """Stats work even before first beat."""
        cetana = Cetana(vedana_source=lambda: _make_vedana(0.9))
        s = cetana.stats()
        assert s["alive"] is False
        assert s["total_beats"] == 0
        assert s["last_health"] is None

    def test_stats_after_beats(self):
        """Stats reflect actual heartbeat state."""
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.9),
            frequency_hz=20.0,
        )
        cetana.start()
        _poll(lambda: cetana.total_beats >= 1)
        s = cetana.stats()
        assert s["alive"] is True
        assert s["total_beats"] >= 1
        assert s["last_health"] is not None
        assert s["last_guna"] is not None
        cetana.stop()

    def test_history_bounded(self):
        """History doesn't grow unbounded — respects _MAX_HISTORY."""
        cetana = Cetana(
            vedana_source=lambda: _make_vedana(0.9),
            frequency_hz=100.0,  # Very fast to fill history
        )
        cetana.start()
        _poll(lambda: cetana.total_beats >= 110)  # Exceed history cap
        cetana.stop()
        # History is bounded by deque maxlen
        with cetana._lock:
            assert len(cetana._history) <= 100
