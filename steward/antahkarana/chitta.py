"""
Chitta — Consciousness / Impression Storage.

PrakritiElement #4 — Protocol Layer: awareness
Category: ANTAHKARANA (Internal Instrument)

In Sankhya, Chitta stores impressions (samskaras) from past actions.
It answers: "WHAT has happened?" — the accumulated experience.

Chitta tracks tool execution history as impressions,
enabling Buddhi to discriminate and Gandha to detect patterns.

Phase awareness: Chitta derives the current execution phase
from its accumulated impressions. This is self-awareness —
knowing "where am I?" from "what have I done?"
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum


class ExecutionPhase(StrEnum):
    """Execution phases — derived from Chitta impressions.

    StrEnum so values work as dict keys and in string comparisons.
    """

    ORIENT = "ORIENT"  # exploring/reading — gathering context
    EXECUTE = "EXECUTE"  # making changes — writing/editing
    VERIFY = "VERIFY"  # checking work — running tests
    COMPLETE = "COMPLETE"  # wrapping up — tests passed after writes


# Legacy aliases (for backward compat)
PHASE_ORIENT = ExecutionPhase.ORIENT
PHASE_EXECUTE = ExecutionPhase.EXECUTE
PHASE_VERIFY = ExecutionPhase.VERIFY
PHASE_COMPLETE = ExecutionPhase.COMPLETE

_READ_NAMES = frozenset({"read_file", "glob", "grep"})
_WRITE_NAMES = frozenset({"edit_file", "write_file"})


@dataclass
class Impression:
    """A recorded tool call impression (samskara).

    Each tool execution leaves an impression in Chitta.
    """

    name: str
    params_hash: int  # hash of parameters for identity
    success: bool
    error: str = ""
    path: str = ""  # file path (for read/write/edit tools)


class Chitta:
    """Impression storage — accumulated experience.

    PrakritiElement.CITTA -> Protocol Layer: awareness

    Stores tool execution impressions for pattern analysis.
    Buddhi and Gandha query Chitta to make decisions.

    Phase derivation: Chitta knows its own phase from its impressions.
    ORIENT -> EXECUTE -> VERIFY -> COMPLETE
    Regression: errors pull back to ORIENT.

    Cross-turn awareness: prior_reads tracks files read in previous turns,
    enabling Gandha to detect blind writes across turn boundaries.
    """

    def __init__(self) -> None:
        self._impressions: list[Impression] = []
        self._round: int = 0
        self._prior_reads: set[str] = set()  # files read in prior turns
        self._lock = threading.Lock()  # Protects _impressions and _prior_reads

    def record(
        self,
        name: str,
        params_hash: int,
        success: bool,
        error: str = "",
        path: str = "",
    ) -> None:
        """Record a tool execution impression."""
        imp = Impression(
            name=name,
            params_hash=params_hash,
            success=success,
            error=error,
            path=path,
        )
        with self._lock:
            self._impressions.append(imp)

    def advance_round(self) -> int:
        """Advance to next round, return new round number."""
        self._round += 1
        return self._round

    @property
    def impressions(self) -> list[Impression]:
        """All recorded impressions (snapshot copy for thread safety)."""
        with self._lock:
            return list(self._impressions)

    @property
    def round(self) -> int:
        """Current round number."""
        return self._round

    def recent(self, n: int) -> list[Impression]:
        """Get the last n impressions."""
        with self._lock:
            if n <= len(self._impressions):
                return list(self._impressions[-n:])
            return list(self._impressions)

    def clear(self) -> None:
        """Clear all impressions and reset round counter.

        Also clears prior_reads — full reset for new session.
        """
        with self._lock:
            self._impressions.clear()
            self._round = 0
            self._prior_reads.clear()

    def end_turn(self) -> None:
        """End current turn — merge reads into prior, clear impressions.

        Call this between turns to retain cross-turn file awareness
        while clearing per-turn impression history.
        Round counter is NOT reset — it tracks cumulative rounds across turns.
        """
        with self._lock:
            for imp in self._impressions:
                if imp.name in _READ_NAMES and imp.success and imp.path:
                    self._prior_reads.add(imp.path)
            self._impressions.clear()
            # NOTE: _round intentionally not reset here — tracks cross-turn progress.
            # Only clear() resets round (full session reset).

    @property
    def phase(self) -> ExecutionPhase:
        """Derive current execution phase from accumulated impressions.

        ORIENT   — still reading/exploring (or regressed due to errors)
        EXECUTE  — actively writing/editing (has enough context)
        VERIFY   — wrote files, now should test (no recent writes)
        COMPLETE — wrote and verified (bash success after writes)

        Deterministic — same impressions always produce same phase.
        """
        with self._lock:
            impressions = list(self._impressions)

        if not impressions:
            return PHASE_ORIENT

        # Aggregate counts
        total_writes = sum(1 for i in impressions if i.name in _WRITE_NAMES and i.success)

        # Recent window (last 3 impressions)
        recent = impressions[-3:] if len(impressions) >= 3 else impressions
        recent_errors = sum(1 for i in recent if not i.success)
        recent_writes = sum(1 for i in recent if i.name in _WRITE_NAMES and i.success)
        recent_bash_ok = sum(1 for i in recent if i.name == "bash" and i.success)

        # Error regression: 2+ recent errors -> back to reading
        if recent_errors >= 2:
            return PHASE_ORIENT

        # Wrote files + recent successful bash -> done
        if total_writes > 0 and recent_bash_ok >= 1:
            return PHASE_COMPLETE

        # Wrote files, no recent writes -> time to verify
        if total_writes > 0 and recent_writes == 0:
            return PHASE_VERIFY

        # Actively writing
        if recent_writes > 0:
            return PHASE_EXECUTE

        # Read enough -> ready to act
        total_reads = sum(1 for i in impressions if i.name in _READ_NAMES)
        if total_reads >= 2:
            return PHASE_EXECUTE

        return PHASE_ORIENT

    @property
    def prior_reads(self) -> frozenset[str]:
        """Files read in previous turns (cross-turn awareness)."""
        with self._lock:
            return frozenset(self._prior_reads)

    def was_file_read(self, path: str) -> bool:
        """Check if a file was read in current OR prior turns."""
        with self._lock:
            if path in self._prior_reads:
                return True
            return any(i.name in _READ_NAMES and i.success and i.path == path for i in self._impressions)

    @property
    def files_read(self) -> list[str]:
        """Unique file paths read (from read_file impressions, current turn only)."""
        with self._lock:
            seen: set[str] = set()
            result: list[str] = []
            for i in self._impressions:
                if i.name in _READ_NAMES and i.success and i.path and i.path not in seen:
                    seen.add(i.path)
                    result.append(i.path)
            return result

    @property
    def files_written(self) -> list[str]:
        """Unique file paths written (from edit_file/write_file impressions)."""
        with self._lock:
            return self._files_written_unlocked()

    def to_summary(self) -> dict[str, object]:
        """Serialize cross-turn state for persistence.

        Only saves what's needed for cross-turn awareness:
        - prior_reads: all files ever read (for Gandha write-without-read)
        - files_written: files modified (for session awareness)
        - last_phase: where the session ended

        NOT saved: raw impressions (ephemeral, per-turn only).
        """
        with self._lock:
            all_reads = set(self._prior_reads)
            for imp in self._impressions:
                if imp.name in _READ_NAMES and imp.success and imp.path:
                    all_reads.add(imp.path)
            written = self._files_written_unlocked()
        return {
            "prior_reads": sorted(all_reads),
            "files_written": written,
            "last_phase": self.phase,
        }

    def _files_written_unlocked(self) -> list[str]:
        """Internal: compute files_written without acquiring lock (caller holds it)."""
        seen: set[str] = set()
        result: list[str] = []
        for i in self._impressions:
            if i.name in _WRITE_NAMES and i.success and i.path and i.path not in seen:
                seen.add(i.path)
                result.append(i.path)
        return result

    def load_summary(self, summary: dict[str, object]) -> None:
        """Restore cross-turn state from a persisted summary."""
        prior = summary.get("prior_reads", [])
        with self._lock:
            if isinstance(prior, list):
                self._prior_reads = set(prior)

    @property
    def stats(self) -> dict[str, object]:
        """Diagnostic stats from accumulated impressions."""
        with self._lock:
            total = len(self._impressions)
            errors = sum(1 for r in self._impressions if not r.success)
            tool_counts: dict[str, int] = {}
            for r in self._impressions:
                tool_counts[r.name] = tool_counts.get(r.name, 0) + 1
            n_prior = len(self._prior_reads)
        return {
            "rounds": self._round,
            "total_calls": total,
            "errors": errors,
            "error_ratio": errors / total if total else 0.0,
            "tool_distribution": tool_counts,
            "phase": self.phase,
            "prior_reads": n_prior,
        }
