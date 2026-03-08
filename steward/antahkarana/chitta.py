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

from dataclasses import dataclass


# ── Execution Phases (derived from impressions) ──────────────────────

PHASE_ORIENT = "ORIENT"      # exploring/reading — gathering context
PHASE_EXECUTE = "EXECUTE"    # making changes — writing/editing
PHASE_VERIFY = "VERIFY"      # checking work — running tests
PHASE_COMPLETE = "COMPLETE"  # wrapping up — tests passed after writes

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
    """

    def __init__(self) -> None:
        self._impressions: list[Impression] = []
        self._round: int = 0

    def record(
        self,
        name: str,
        params_hash: int,
        success: bool,
        error: str = "",
        path: str = "",
    ) -> None:
        """Record a tool execution impression."""
        self._impressions.append(Impression(
            name=name,
            params_hash=params_hash,
            success=success,
            error=error,
            path=path,
        ))

    def advance_round(self) -> int:
        """Advance to next round, return new round number."""
        self._round += 1
        return self._round

    @property
    def impressions(self) -> list[Impression]:
        """All recorded impressions."""
        return self._impressions

    @property
    def round(self) -> int:
        """Current round number."""
        return self._round

    def recent(self, n: int) -> list[Impression]:
        """Get the last n impressions."""
        if n <= len(self._impressions):
            return self._impressions[-n:]
        return list(self._impressions)

    def clear(self) -> None:
        """Clear all impressions and reset round counter."""
        self._impressions.clear()
        self._round = 0

    @property
    def phase(self) -> str:
        """Derive current execution phase from accumulated impressions.

        ORIENT   — still reading/exploring (or regressed due to errors)
        EXECUTE  — actively writing/editing (has enough context)
        VERIFY   — wrote files, now should test (no recent writes)
        COMPLETE — wrote and verified (bash success after writes)

        Deterministic — same impressions always produce same phase.
        """
        if not self._impressions:
            return PHASE_ORIENT

        # Aggregate counts
        total_writes = sum(
            1 for i in self._impressions
            if i.name in _WRITE_NAMES and i.success
        )

        # Recent window (last 3 impressions)
        recent = self._impressions[-3:] if len(self._impressions) >= 3 else self._impressions
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
        total_reads = sum(1 for i in self._impressions if i.name in _READ_NAMES)
        if total_reads >= 2:
            return PHASE_EXECUTE

        return PHASE_ORIENT

    @property
    def files_read(self) -> list[str]:
        """Unique file paths read (from read_file impressions)."""
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
        seen: set[str] = set()
        result: list[str] = []
        for i in self._impressions:
            if i.name in _WRITE_NAMES and i.success and i.path and i.path not in seen:
                seen.add(i.path)
                result.append(i.path)
        return result

    @property
    def stats(self) -> dict[str, object]:
        """Diagnostic stats from accumulated impressions."""
        total = len(self._impressions)
        errors = sum(1 for r in self._impressions if not r.success)
        tool_counts: dict[str, int] = {}
        for r in self._impressions:
            tool_counts[r.name] = tool_counts.get(r.name, 0) + 1
        return {
            "rounds": self._round,
            "total_calls": total,
            "errors": errors,
            "error_ratio": errors / total if total else 0.0,
            "tool_distribution": tool_counts,
            "phase": self.phase,
        }
