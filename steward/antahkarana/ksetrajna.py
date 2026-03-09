"""
KṢETRA-JÑA — The Knower of the Field (Meta-Observer).

BG 13.1-2: "kṣetra-jñaṁ cāpi māṁ viddhi sarva-kṣetreṣu bhārata"
"Know the knower of the field in all fields, O descendant of Bharata."

The Ksetra (field) is the agent's body — its antahkarana (manas, buddhi,
chitta, gandha), its vedana (health pulse), its cetana (heartbeat).
Each component observes ONE thing. Nobody watches the WHOLE field.

KsetraJna IS that observer. It reads all components and produces
a single compressed BubbleSnapshot — the agent's complete state in
one frozen dataclass. Peers can read this. The agent can read this.
No side effects. No LLM tokens. Pure observation.

This is the BuddyBubble slot — the foundation for peer observation
in agent-city. When multi-agent coordination is wired, peers read
each other's BubbleSnapshot via SankirtanChamber resonance.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from steward.antahkarana.vedana import VedanaSignal

logger = logging.getLogger("STEWARD.KSETRAJNA")


@dataclass(frozen=True)
class BubbleSnapshot:
    """Compressed frozen snapshot of the agent's field (Ksetra).

    One observation. Immutable. Safe to share across threads/agents.
    Compatible with BrainDigest pattern from agent-city.
    """

    timestamp: float
    # Vedana — health pulse
    health: float  # 0.0 (duhkham) to 1.0 (sukham)
    guna: str  # sattva / rajas / tamas
    # Chitta — execution state
    phase: str  # ORIENT / EXECUTE / VERIFY / COMPLETE
    round: int
    error_ratio: float
    files_read: int
    files_written: int
    # Buddhi — cognitive state
    action: str  # last semantic action
    tier: str  # FLASH / STANDARD / PRO
    # Cetana — heartbeat
    heartbeat_hz: float
    anomaly_count: int
    # Gandha — pattern detection
    last_pattern: str  # pattern name or ""


# ── Drift weights ────────────────────────────────────────────────────
# How much each field contributes to the drift score between snapshots.
# Health is most critical (30%), phase change is binary and impactful (25%).

_W_HEALTH = 0.30
_W_PHASE = 0.25
_W_ERROR = 0.20
_W_ROUND = 0.15
_W_PATTERN = 0.10


def _compute_drift(a: BubbleSnapshot, b: BubbleSnapshot) -> float:
    """Compute weighted drift between two snapshots.

    Returns 0.0 (identical) to 1.0 (completely different).
    """
    d_health = abs(a.health - b.health)
    d_phase = 0.0 if a.phase == b.phase else 1.0
    d_error = abs(a.error_ratio - b.error_ratio)
    d_round = min(abs(a.round - b.round) / max(a.round, b.round, 1), 1.0)
    d_pattern = 0.0 if a.last_pattern == b.last_pattern else 1.0

    return (
        _W_HEALTH * d_health
        + _W_PHASE * d_phase
        + _W_ERROR * d_error
        + _W_ROUND * d_round
        + _W_PATTERN * d_pattern
    )


class KsetraJna:
    """Meta-observer — watches the agent's entire field.

    Takes callable sources (dependency injection). Produces frozen
    BubbleSnapshots. Detects drift, stagnation, and health trends.
    Zero LLM tokens. O(1) per observation.

    Usage:
        kj = KsetraJna(
            vedana_source=lambda: agent.vedana,
            chitta_source=lambda: agent._buddhi.stats,
            cetana_source=lambda: agent._cetana.stats(),
            buddhi_source=lambda: {"action": "research", "tier": "STANDARD"},
            gandha_source=lambda: "",
        )
        snapshot = kj.observe()
        print(kj.digest())  # "sattva EXECUTE r3 h=0.85 hz=0.5 ok"
    """

    def __init__(
        self,
        vedana_source: Callable[[], VedanaSignal],
        chitta_source: Callable[[], dict],
        cetana_source: Callable[[], dict],
        buddhi_source: Callable[[], dict],
        gandha_source: Callable[[], str],
        max_history: int = 50,
    ) -> None:
        self._vedana_source = vedana_source
        self._chitta_source = chitta_source
        self._cetana_source = cetana_source
        self._buddhi_source = buddhi_source
        self._gandha_source = gandha_source
        self._history: deque[BubbleSnapshot] = deque(maxlen=max_history)

    def observe(self) -> BubbleSnapshot:
        """Take a snapshot of the field. O(1), zero side effects."""
        vedana = self._vedana_source()
        chitta = self._chitta_source
        if callable(chitta):
            chitta = chitta()
        cetana = self._cetana_source()
        buddhi = self._buddhi_source()
        pattern = self._gandha_source()

        snapshot = BubbleSnapshot(
            timestamp=time.time(),
            health=vedana.health,
            guna=vedana.guna,
            phase=str(chitta.get("phase", "ORIENT")),
            round=int(chitta.get("rounds", 0)),
            error_ratio=float(chitta.get("error_ratio", 0.0)),
            files_read=int(chitta.get("prior_reads", 0)),
            files_written=int(chitta.get("tool_distribution", {}).get("write_file", 0))
            if isinstance(chitta.get("tool_distribution"), dict)
            else 0,
            action=str(buddhi.get("action", "")),
            tier=str(buddhi.get("tier", "STANDARD")),
            heartbeat_hz=float(cetana.get("frequency_hz", 0.0)),
            anomaly_count=int(cetana.get("consecutive_anomalies", 0)),
            last_pattern=pattern,
        )

        self._history.append(snapshot)

        logger.debug(
            "KsetraJna: %s %s r%d h=%.2f hz=%.1f %s",
            snapshot.guna,
            snapshot.phase,
            snapshot.round,
            snapshot.health,
            snapshot.heartbeat_hz,
            snapshot.last_pattern or "ok",
        )

        return snapshot

    @property
    def history(self) -> list[BubbleSnapshot]:
        """Rolling snapshot history (most recent last)."""
        return list(self._history)

    @property
    def last(self) -> BubbleSnapshot | None:
        """Most recent observation."""
        return self._history[-1] if self._history else None

    def drift(self) -> float:
        """How much has the field changed between last two snapshots?

        Returns 0.0 (identical) to 1.0 (completely different).
        Returns 0.0 if fewer than 2 snapshots.
        """
        if len(self._history) < 2:
            return 0.0
        return _compute_drift(self._history[-2], self._history[-1])

    def is_stuck(self, window: int = 5, threshold: float = 0.05) -> bool:
        """Is the agent stuck in a loop?

        True if average drift over the last `window` observations is
        below `threshold`. Needs at least `window` snapshots.
        """
        if len(self._history) < window:
            return False

        recent = list(self._history)[-window:]
        drifts = [_compute_drift(recent[i], recent[i + 1]) for i in range(len(recent) - 1)]
        avg_drift = sum(drifts) / len(drifts)
        return avg_drift < threshold

    def trend(self) -> str:
        """Health trend from last 5 snapshots.

        Returns "improving", "degrading", or "stable".
        Uses slope of health values (simple linear regression sign).
        """
        n = min(len(self._history), 5)
        if n < 2:
            return "stable"

        recent = list(self._history)[-n:]
        healths = [s.health for s in recent]

        # Simple slope: average of consecutive diffs
        diffs = [healths[i + 1] - healths[i] for i in range(len(healths) - 1)]
        avg_slope = sum(diffs) / len(diffs)

        if avg_slope > 0.02:
            return "improving"
        if avg_slope < -0.02:
            return "degrading"
        return "stable"

    def digest(self) -> str:
        """One-line compressed summary for peers.

        Format: "sattva EXECUTE r3 h=0.85 hz=0.5 ok"
        Compatible with BrainDigest.render_field_summary().
        """
        snap = self.last
        if snap is None:
            return "no-observation"
        pattern = snap.last_pattern or "ok"
        stuck = " STUCK" if self.is_stuck() else ""
        return (
            f"{snap.guna} {snap.phase} r{snap.round} "
            f"h={snap.health:.2f} hz={snap.heartbeat_hz:.1f} "
            f"{pattern}{stuck}"
        )

    def stats(self) -> dict[str, object]:
        """Observability dict for get_state()."""
        snap = self.last
        return {
            "observations": len(self._history),
            "drift": round(self.drift(), 4),
            "trend": self.trend(),
            "is_stuck": self.is_stuck(),
            "digest": self.digest(),
            "last_snapshot": {
                "health": snap.health,
                "guna": snap.guna,
                "phase": snap.phase,
                "round": snap.round,
                "error_ratio": snap.error_ratio,
                "action": snap.action,
                "tier": snap.tier,
                "heartbeat_hz": snap.heartbeat_hz,
                "anomaly_count": snap.anomaly_count,
                "last_pattern": snap.last_pattern,
            }
            if snap
            else None,
        }
