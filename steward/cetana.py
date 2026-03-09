"""
CETANA — Life Symptoms / Autonomous Heartbeat.

BG 13.6-7 lists cetana (consciousness/life symptoms) as part of the
Ksetra (material field). It is the continuous background pulse that
keeps the agent alive and responsive without external prompting.

Cetana does NOT think or act. It OBSERVES and SIGNALS.
The agent loop does the work. Cetana is like breathing — automatic,
adaptive, and the first thing that stops when the agent dies.

Adaptive frequency based on vedana health:
  SAMADHI:  0.1Hz (10s)  — health > 0.8 (all calm, slow steady pulse)
  SADHANA:  0.5Hz (2s)   — health > 0.5 (normal monitoring pace)
  GAJENDRA: 2.0Hz (0.5s) — health < 0.5 (emergency, rapid monitoring)

Architecture:
  - Background thread (daemon=True, dies with main process)
  - Reads vedana_source callable → VedanaSignal each beat
  - Adjusts frequency based on health
  - Calls on_anomaly when health drops below threshold
  - Records beat history for observability

Does NOT:
  - Call the LLM
  - Execute tools
  - Modify conversation
  - Make decisions (that's Buddhi's job)
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from steward.antahkarana.vedana import VedanaSignal

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
    anomaly: bool = False


@dataclass
class Cetana:
    """Autonomous heartbeat — the agent's life force.

    Runs a background thread that periodically reads the agent's
    vedana (health pulse) and adjusts monitoring frequency.

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
    frequency_hz: float = SADHANA
    _stop_event: threading.Event = field(default_factory=lambda: _make_stopped_event(), init=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _total_beats: int = field(default=0, init=False)
    _history: deque[CetanaBeat] = field(default_factory=lambda: deque(maxlen=_MAX_HISTORY), init=False)
    _consecutive_anomalies: int = field(default=0, init=False)

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
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
            self._thread = None

        last_health = self._history[-1].vedana.health if self._history else 0.0
        logger.info(
            "Cetana stopped after %d beats (last health=%.2f, freq=%.1fHz)",
            self._total_beats,
            last_health,
            self.frequency_hz,
        )

    @property
    def is_alive(self) -> bool:
        """Is the heartbeat running?"""
        return not self._stop_event.is_set()

    @property
    def total_beats(self) -> int:
        return self._total_beats

    @property
    def last_beat(self) -> CetanaBeat | None:
        return self._history[-1] if self._history else None

    def stats(self) -> dict[str, object]:
        """Observability — current heartbeat state."""
        last = self.last_beat
        return {
            "alive": self.is_alive,
            "total_beats": self._total_beats,
            "frequency_hz": self.frequency_hz,
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
            sleep_time = max(0.01, (1.0 / self.frequency_hz) - elapsed)

            # Interruptible sleep — Event.wait returns immediately when set
            self._stop_event.wait(timeout=sleep_time)

    def _beat(self) -> CetanaBeat:
        """Execute one heartbeat — read vedana, detect anomalies."""
        self._total_beats += 1

        vedana = self.vedana_source()
        is_anomaly = vedana.health < _ANOMALY_THRESHOLD

        beat = CetanaBeat(
            timestamp=time.time(),
            vedana=vedana,
            frequency_hz=self.frequency_hz,
            beat_number=self._total_beats,
            anomaly=is_anomaly,
        )

        self._history.append(beat)

        if is_anomaly:
            self._consecutive_anomalies += 1
            logger.warning(
                "Cetana anomaly #%d: health=%.2f (%s) — provider=%.2f error=%.2f context=%.2f",
                self._consecutive_anomalies,
                vedana.health,
                vedana.guna,
                vedana.provider_health,
                vedana.error_pressure,
                vedana.context_pressure,
            )
            if self.on_anomaly:
                self.on_anomaly(beat)
        else:
            self._consecutive_anomalies = 0

        logger.debug(
            "Beat #%d: health=%.2f freq=%.1fHz",
            self._total_beats,
            vedana.health,
            self.frequency_hz,
        )

        return beat

    def _adapt_frequency(self, health: float) -> None:
        """Adjust heartbeat frequency based on health.

        Higher health → slower pulse (SAMADHI, relaxed monitoring).
        Lower health → faster pulse (GAJENDRA, emergency mode).
        No if/else cliffs — smooth transitions between zones.
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
