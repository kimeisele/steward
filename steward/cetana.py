"""
CETANA — Life Symptoms / Autonomous Heartbeat.

BG 13.6-7 lists cetana (consciousness/life symptoms) as part of the
Ksetra (material field). It is the continuous background pulse that
keeps the agent alive and responsive without external prompting.

Cetana OBSERVES and SIGNALS via a 4-phase rotation (MURALI cycle):
  GENESIS:  Discover — run senses, scan environment
  DHARMA:   Govern   — check invariants, validate health
  KARMA:    Execute  — work on highest-priority task
  MOKSHA:   Reflect  — persist state, log stats, learn

Each beat rotates to the next phase. The agent wires behavior into
phases via the on_phase callback.

Adaptive frequency based on vedana health:
  SAMADHI:  0.1Hz (10s)  — health > 0.8 (all calm, slow steady pulse)
  SADHANA:  0.5Hz (2s)   — health > 0.5 (normal monitoring pace)
  GAJENDRA: 2.0Hz (0.5s) — health < 0.5 (emergency, rapid monitoring)

Architecture:
  - Background thread (daemon=True, dies with main process)
  - Reads vedana_source callable → VedanaSignal each beat
  - Rotates through 4 phases (GENESIS → DHARMA → KARMA → MOKSHA)
  - Adjusts frequency based on health
  - Calls on_anomaly when health drops below threshold
  - Calls on_phase for structured phase callbacks
  - Records beat history for observability
"""

from __future__ import annotations

import enum
import logging
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from steward.antahkarana.vedana import VedanaSignal


class Phase(enum.Enum):
    """4-phase MURALI heartbeat cycle (from agent-city Mayor pattern)."""

    GENESIS = 0  # Discover — run senses, scan environment
    DHARMA = 1  # Govern — check invariants, validate health
    KARMA = 2  # Execute — work on highest-priority task
    MOKSHA = 3  # Reflect — persist state, log stats, learn


logger = logging.getLogger("STEWARD.CETANA")

# ── Frequency Constants (Hz) ────────────────────────────────────────
# Named after states of spiritual practice (agent-city convention).

SAMADHI = 0.1  # Deep absorption — healthy, minimal monitoring
SADHANA = 0.5  # Active practice — normal operational pace
GAJENDRA = 2.0  # Emergency prayer — rapid response to crisis

# Health thresholds for frequency transitions
_THRESHOLD_CALM = 0.8  # Above this → SAMADHI
_THRESHOLD_ALERT = 0.5  # Above this → SADHANA, below → GAJENDRA

# Anomaly threshold — below this, on_anomaly fires
_ANOMALY_THRESHOLD = 0.3

# Maximum beat history retained
_MAX_HISTORY = 100


def _make_stopped_event() -> threading.Event:
    """Create an Event that starts in 'set' (stopped) state."""
    e = threading.Event()
    e.set()
    return e


@dataclass(frozen=True)
class CetanaBeat:
    """Single heartbeat — a snapshot of the agent's vital signs.

    Produced every tick. Lightweight, no side effects.
    """

    timestamp: float
    vedana: VedanaSignal
    frequency_hz: float
    beat_number: int
    phase: Phase = Phase.GENESIS
    anomaly: bool = False


@dataclass
class Cetana:
    """Autonomous heartbeat — the agent's life force.

    Runs a background thread that periodically reads the agent's
    vedana (health pulse) and adjusts monitoring frequency.

    Thread safety: All mutable state accessed from both the daemon thread
    and the main thread is protected by _lock. The daemon thread writes
    (_beat, _adapt_frequency), the main thread reads (stats, properties).

    Usage:
        cetana = Cetana(
            vedana_source=lambda: agent.vedana,
            on_anomaly=lambda beat: logger.warning("Health critical!"),
        )
        cetana.start()
        # ... agent runs ...
        cetana.stop()
    """

    vedana_source: Callable[[], VedanaSignal]
    on_anomaly: Callable[[CetanaBeat], None] | None = None
    on_phase: Callable[[Phase, CetanaBeat], None] | None = None
    frequency_hz: float = SADHANA
    _stop_event: threading.Event = field(default_factory=lambda: _make_stopped_event(), init=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _total_beats: int = field(default=0, init=False)
    _phase: Phase = field(default=Phase.GENESIS, init=False)
    _history: deque[CetanaBeat] = field(default_factory=lambda: deque(maxlen=_MAX_HISTORY), init=False)
    _consecutive_anomalies: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def start(self, block: bool = False) -> None:
        """Start the autonomous heartbeat."""
        if self.is_alive:
            return  # Already running — idempotent

        self._stop_event.clear()  # Clear = running
        self._install_signal_handlers()
        logger.info("Cetana starting at %.1fHz (period=%.1fs)", self.frequency_hz, 1.0 / self.frequency_hz)

        if block:
            self._loop()
        else:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop the heartbeat gracefully."""
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning("Cetana daemon thread did not stop within 5s — may be stuck")
            self._thread = None

        with self._lock:
            last_health = self._history[-1].vedana.health if self._history else 0.0
            total = self._total_beats
            freq = self.frequency_hz
        logger.info(
            "Cetana stopped after %d beats (last health=%.2f, freq=%.1fHz)",
            total,
            last_health,
            freq,
        )

    @property
    def is_alive(self) -> bool:
        """Is the heartbeat running?"""
        return not self._stop_event.is_set()

    @property
    def total_beats(self) -> int:
        with self._lock:
            return self._total_beats

    @property
    def last_beat(self) -> CetanaBeat | None:
        with self._lock:
            return self._history[-1] if self._history else None

    def stats(self) -> dict[str, object]:
        """Observability — current heartbeat state."""
        with self._lock:
            last = self._history[-1] if self._history else None
            return {
                "alive": self.is_alive,
                "total_beats": self._total_beats,
                "frequency_hz": self.frequency_hz,
                "phase": self._phase.name,
                "consecutive_anomalies": self._consecutive_anomalies,
                "last_health": last.vedana.health if last else None,
                "last_guna": last.vedana.guna if last else None,
            }

    def _loop(self) -> None:
        """Internal heartbeat loop — adaptive frequency."""
        while not self._stop_event.is_set():
            t0 = time.monotonic()

            beat = self._beat()
            self._adapt_frequency(beat.vedana.health)

            elapsed = time.monotonic() - t0
            with self._lock:
                freq = self.frequency_hz
            sleep_time = max(0.01, (1.0 / freq) - elapsed)

            # Interruptible sleep — Event.wait returns immediately when set
            self._stop_event.wait(timeout=sleep_time)

    def _beat(self) -> CetanaBeat:
        """Execute one heartbeat — read vedana, detect anomalies, rotate phase.

        Called from daemon thread. vedana_source() is called outside the lock
        (it may be slow), then state is updated atomically under _lock.

        Phase rotation: each beat advances GENESIS → DHARMA → KARMA → MOKSHA → GENESIS.
        The on_phase callback fires AFTER state update, outside the lock.
        """
        vedana = self.vedana_source()
        is_anomaly = vedana.health < _ANOMALY_THRESHOLD

        with self._lock:
            self._total_beats += 1
            current_phase = self._phase
            beat = CetanaBeat(
                timestamp=time.time(),
                vedana=vedana,
                frequency_hz=self.frequency_hz,
                beat_number=self._total_beats,
                phase=current_phase,
                anomaly=is_anomaly,
            )
            self._history.append(beat)

            if is_anomaly:
                self._consecutive_anomalies += 1
                anomaly_count = self._consecutive_anomalies
            else:
                self._consecutive_anomalies = 0
                anomaly_count = 0

            # Rotate to next phase (mod 4)
            self._phase = Phase((current_phase.value + 1) % 4)

        # Logging and callbacks outside lock (avoid holding lock during I/O)
        if is_anomaly:
            logger.warning(
                "Cetana anomaly #%d: health=%.2f (%s) — provider=%.2f error=%.2f context=%.2f",
                anomaly_count,
                vedana.health,
                vedana.guna,
                vedana.provider_health,
                vedana.error_pressure,
                vedana.context_pressure,
            )
            if self.on_anomaly:
                self.on_anomaly(beat)

        if self.on_phase:
            self.on_phase(current_phase, beat)

        logger.debug(
            "Beat #%d [%s]: health=%.2f freq=%.1fHz",
            beat.beat_number,
            current_phase.name,
            vedana.health,
            beat.frequency_hz,
        )

        return beat

    def _adapt_frequency(self, health: float) -> None:
        """Adjust heartbeat frequency based on health.

        Higher health → slower pulse (SAMADHI, relaxed monitoring).
        Lower health → faster pulse (GAJENDRA, emergency mode).
        No if/else cliffs — smooth transitions between zones.

        Called from daemon thread — frequency_hz written under _lock.
        """
        if health > _THRESHOLD_CALM:
            target = SAMADHI
        elif health > _THRESHOLD_ALERT:
            # Linear interpolation between SADHANA and SAMADHI
            t = (health - _THRESHOLD_ALERT) / (_THRESHOLD_CALM - _THRESHOLD_ALERT)
            target = SADHANA + t * (SAMADHI - SADHANA)
        else:
            # Linear interpolation between GAJENDRA and SADHANA
            t = health / _THRESHOLD_ALERT
            target = GAJENDRA + t * (SADHANA - GAJENDRA)

        # Smooth transition (exponential moving average, avoid jerky changes)
        with self._lock:
            self.frequency_hz = self.frequency_hz * 0.7 + target * 0.3

    def _install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT handlers for graceful shutdown."""
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
        except (ValueError, OSError):
            pass  # Not main thread — can't install signal handlers

    def _signal_handler(self, signum: int, frame: object) -> None:
        """Handle shutdown signals."""
        logger.info("Cetana received signal %d, stopping...", signum)
        self._stop_event.set()
