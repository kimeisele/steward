"""
GapTracker — Agent self-awareness of capability gaps.

Tracks what the agent tried but couldn't do. Gaps are recorded when:
- A tool returns an error (tool_gap)
- A skill is needed but doesn't exist (skill_gap)
- A provider capability is missing (provider_gap)

Gaps persist in memory and are surfaced in the system prompt so the
agent can act on them — install a package, create a skill, or route
to a different provider.

This is what makes steward ALIVE — it knows what it doesn't know.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("STEWARD.GAPS")

_MAX_GAPS = 20  # Max gaps to track (FIFO)
_GAP_EXPIRY_HOURS = 72  # Gaps expire after 3 days


@dataclass
class Gap:
    """A detected capability gap."""

    category: str  # "tool", "skill", "provider", "knowledge"
    description: str  # What was attempted
    context: str  # What triggered it
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False
    resolution: str = ""


@dataclass
class GapTracker:
    """Tracks capability gaps the agent encounters.

    Gaps are recorded, deduplicated, and surfaced in the system prompt
    so the agent (and its operator) know what's missing.
    """

    _gaps: list[Gap] = field(default_factory=list)

    def record(self, category: str, description: str, context: str = "") -> None:
        """Record a new capability gap.

        Deduplicates by description — same gap isn't recorded twice.
        """
        # Deduplicate
        for gap in self._gaps:
            if gap.description == description and not gap.resolved:
                return  # Already tracked

        gap = Gap(category=category, description=description, context=context)
        self._gaps.append(gap)
        logger.info("Gap detected [%s]: %s", category, description)

        # Evict old gaps (FIFO)
        self._prune()

    def record_tool_failure(self, tool_name: str, error: str, parameters: dict | None = None) -> None:
        """Record a gap from a tool failure."""
        # Filter noise — not every tool error is a gap
        if any(skip in error.lower() for skip in ["not found", "no such file", "permission"]):
            return  # User error, not a capability gap

        desc = f"Tool '{tool_name}' failed: {error[:200]}"
        ctx = f"parameters: {parameters}" if parameters else ""
        self.record("tool", desc, ctx)

    def record_missing_skill(self, task_description: str) -> None:
        """Record a gap when no skill matches a task."""
        desc = f"No skill found for: {task_description[:200]}"
        self.record("skill", desc)

    def record_provider_gap(self, capability: str, details: str = "") -> None:
        """Record a gap in provider capabilities."""
        desc = f"Provider capability missing: {capability}"
        self.record("provider", desc, details)

    def resolve(self, description: str, resolution: str = "") -> bool:
        """Mark a gap as resolved."""
        for gap in self._gaps:
            if gap.description == description and not gap.resolved:
                gap.resolved = True
                gap.resolution = resolution
                logger.info("Gap resolved: %s", description[:100])
                return True
        return False

    def active_gaps(self) -> list[Gap]:
        """Get all unresolved, non-expired gaps."""
        now = time.time()
        cutoff = now - (_GAP_EXPIRY_HOURS * 3600)
        return [g for g in self._gaps if not g.resolved and g.timestamp > cutoff]

    def format_for_prompt(self) -> str:
        """Format active gaps for injection into system prompt."""
        active = self.active_gaps()
        if not active:
            return ""

        parts = ["\n## Known Capability Gaps"]
        for gap in active[:5]:  # Top 5 only
            parts.append(f"- [{gap.category}] {gap.description}")

        parts.append(
            "\nConsider addressing these gaps by installing packages, "
            "creating skills, or finding alternative approaches."
        )
        return "\n".join(parts)

    def to_dict(self) -> list[dict]:
        """Serialize gaps for persistence."""
        return [
            {
                "category": g.category,
                "description": g.description,
                "context": g.context,
                "timestamp": g.timestamp,
                "resolved": g.resolved,
                "resolution": g.resolution,
            }
            for g in self._gaps
        ]

    def load_from_dict(self, data: list[dict]) -> None:
        """Restore gaps from persisted data."""
        self._gaps = [
            Gap(
                category=d.get("category", "unknown"),
                description=d.get("description", ""),
                context=d.get("context", ""),
                timestamp=d.get("timestamp", 0),
                resolved=d.get("resolved", False),
                resolution=d.get("resolution", ""),
            )
            for d in data
        ]
        self._prune()

    def _prune(self) -> None:
        """Remove expired and excess gaps."""
        now = time.time()
        cutoff = now - (_GAP_EXPIRY_HOURS * 3600)

        # Remove expired
        self._gaps = [g for g in self._gaps if g.timestamp > cutoff or not g.resolved]

        # FIFO eviction
        if len(self._gaps) > _MAX_GAPS:
            self._gaps = self._gaps[-_MAX_GAPS:]

    @property
    def stats(self) -> dict:
        """Gap tracker statistics."""
        active = self.active_gaps()
        categories = {}
        for g in active:
            categories[g.category] = categories.get(g.category, 0) + 1
        return {
            "total_tracked": len(self._gaps),
            "active": len(active),
            "resolved": sum(1 for g in self._gaps if g.resolved),
            "by_category": categories,
        }

    def __len__(self) -> int:
        return len(self.active_gaps())
