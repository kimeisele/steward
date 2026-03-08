"""
Chitta — Consciousness / Impression Storage.

PrakritiElement #4 — Protocol Layer: awareness
Category: ANTAHKARANA (Internal Instrument)

In Sankhya, Chitta stores impressions (samskaras) from past actions.
It answers: "WHAT has happened?" — the accumulated experience.

Chitta tracks tool execution history as impressions,
enabling Buddhi to discriminate and Gandha to detect patterns.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Impression:
    """A recorded tool call impression (samskara).

    Each tool execution leaves an impression in Chitta.
    """

    name: str
    params_hash: int  # hash of parameters for identity
    success: bool
    error: str = ""


class Chitta:
    """Impression storage — accumulated experience.

    PrakritiElement.CITTA -> Protocol Layer: awareness

    Stores tool execution impressions for pattern analysis.
    Buddhi and Gandha query Chitta to make decisions.
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
    ) -> None:
        """Record a tool execution impression."""
        self._impressions.append(Impression(
            name=name,
            params_hash=params_hash,
            success=success,
            error=error,
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
        }
