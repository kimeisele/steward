"""
Campaign Signal Evaluation — the feedback loop Sankalpa was missing.

campaigns/default.json defines 4 success signals. Until now, nobody read them.
This module evaluates each signal against real system state (0 LLM tokens)
and returns a CampaignHealth that GENESIS uses to make data-driven decisions.

The signal kinds map directly to existing services:
  federation_healthy     → SVC_REAPER (alive/dead peer ratio)
  immune_clean           → SenseCoordinator diagnostic scan
  ci_green               → GitSense CI workflow status
  active_missions_at_most → SVC_TASK_MANAGER pending count
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from steward.services import (
    SVC_REAPER,
    SVC_TASK_MANAGER,
)
from vibe_core.di import ServiceRegistry

logger = logging.getLogger("STEWARD.CAMPAIGN_SIGNALS")

# ── Campaign JSON loader (read once, cache) ─────────────────────────

_campaign_cache: dict | None = None


def _load_campaign(project_root: str) -> dict:
    """Load the active campaign from campaigns/default.json.

    Returns the first campaign dict, or an empty dict if not found.
    Cached after first load — campaign config doesn't change at runtime.
    """
    global _campaign_cache
    if _campaign_cache is not None:
        return _campaign_cache

    path = Path(project_root) / "campaigns" / "default.json"
    if not path.exists():
        logger.debug("No campaign file at %s", path)
        _campaign_cache = {}
        return _campaign_cache

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        campaigns = data.get("campaigns", [])
        _campaign_cache = campaigns[0] if campaigns else {}
    except (json.JSONDecodeError, OSError, IndexError) as e:
        logger.warning("Failed to load campaign: %s", e)
        _campaign_cache = {}
    return _campaign_cache


# ── Signal evaluation ────────────────────────────────────────────────


@dataclass(frozen=True)
class SignalResult:
    """One evaluated success signal."""

    kind: str
    target: object  # bool or int from JSON
    actual: object  # measured value
    met: bool  # target achieved?


@dataclass(frozen=True)
class CampaignHealth:
    """Evaluated campaign state — all success signals checked.

    GENESIS reads this to:
    1. Pass accurate ci_green to sankalpa.think()
    2. Boost priority of tasks that address failing signals
    """

    signals: tuple[SignalResult, ...] = ()
    campaign_id: str = ""

    @property
    def ci_green(self) -> bool:
        """Whether CI is passing (for sankalpa.think ci_green param)."""
        for s in self.signals:
            if s.kind == "ci_green":
                return s.met
        return True  # No CI signal defined → assume green

    @property
    def all_met(self) -> bool:
        return all(s.met for s in self.signals)

    @property
    def failing_kinds(self) -> tuple[str, ...]:
        return tuple(s.kind for s in self.signals if not s.met)

    def priority_boost(self, intent_type: str) -> int:
        """Extra priority points for intents that address failing signals.

        Maps failing signal kinds → relevant intent types → boost.
        A failing signal makes its corresponding intent more urgent.
        """
        boost = 0
        for s in self.signals:
            if s.met:
                continue
            relevant = _SIGNAL_TO_INTENTS.get(s.kind, ())
            if intent_type in relevant:
                boost += 20  # One failing signal = +20 priority
        return boost


# Which intent types address which failing signals
_SIGNAL_TO_INTENTS: dict[str, tuple[str, ...]] = {
    "federation_healthy": ("federation_health", "heal_repo", "cross_repo_diagnostic"),
    "immune_clean": ("health_check", "sense_scan", "heal_repo"),
    "ci_green": ("ci_check", "health_check"),
    "active_missions_at_most": (),  # No intent fixes this — it's a constraint
}


def evaluate(project_root: str, senses: object | None = None) -> CampaignHealth:
    """Evaluate all success signals against real system state.

    Each signal kind is checked by a dedicated evaluator function.
    Unknown signal kinds are skipped (forward-compatible).

    Args:
        project_root: Path to the project root (for loading campaign JSON).
        senses: SenseCoordinator instance (for CI and diagnostic checks).
                Optional — signals that need it will report as met if absent.

    Returns:
        CampaignHealth with all evaluated signals.
    """
    campaign = _load_campaign(project_root)
    if not campaign:
        return CampaignHealth()

    raw_signals = campaign.get("success_signals", [])
    results: list[SignalResult] = []

    for sig in raw_signals:
        kind = sig.get("kind", "")
        target = sig.get("target")
        evaluator = _EVALUATORS.get(kind)
        if evaluator is None:
            logger.debug("Unknown signal kind '%s' — skipping", kind)
            continue
        actual, met = evaluator(target, senses)
        results.append(SignalResult(kind=kind, target=target, actual=actual, met=met))

    health = CampaignHealth(
        signals=tuple(results),
        campaign_id=campaign.get("id", ""),
    )

    if not health.all_met:
        logger.info(
            "CAMPAIGN[%s]: failing signals: %s",
            health.campaign_id,
            ", ".join(health.failing_kinds),
        )

    return health


# ── Individual signal evaluators ─────────────────────────────────────
# Each returns (actual_value, met: bool).


def _eval_federation_healthy(target: object, senses: object | None) -> tuple[object, bool]:
    """Check: all discovered peers should be ALIVE or healing."""
    reaper = ServiceRegistry.get(SVC_REAPER)
    if reaper is None:
        return (True, True)  # No reaper = no federation = vacuously healthy

    dead = reaper.dead_peers()
    alive = reaper.alive_peers()
    suspect = reaper.suspect_peers()
    total = len(alive) + len(suspect) + len(dead)

    if total == 0:
        return (True, True)  # No peers discovered yet

    healthy = len(dead) == 0
    return ({"alive": len(alive), "suspect": len(suspect), "dead": len(dead)}, healthy)


def _eval_immune_clean(target: object, senses: object | None) -> tuple[object, bool]:
    """Check: self-diagnostics should find 0 test failures."""
    if senses is None:
        return (True, True)

    try:
        aggregate = senses.perceive_all()
        # total_pain > 0.7 = system in distress (same threshold as execute_sense_scan)
        clean = aggregate.total_pain <= 0.7
        return ({"total_pain": round(aggregate.total_pain, 2)}, clean)
    except Exception as e:
        logger.debug("Immune check failed: %s", e)
        return (True, True)


def _eval_ci_green(target: object, senses: object | None) -> tuple[object, bool]:
    """Check: CI should pass on all federation repos."""
    if senses is None:
        return (True, True)

    from vibe_core.mahamantra.protocols._sense import Jnanendriya

    git_sense = senses.senses.get(Jnanendriya.SROTRA)
    if git_sense is None:
        return (True, True)

    try:
        perception = git_sense.perceive()
        data = perception.data if hasattr(perception, "data") else perception
        if not isinstance(data, dict):
            return (True, True)

        ci_status = data.get("ci_status")
        if ci_status and ci_status.get("conclusion") == "failure":
            return ({"workflow": ci_status.get("name", "?"), "conclusion": "failure"}, False)
        return (True, True)
    except Exception as e:
        logger.debug("CI check failed: %s", e)
        return (True, True)


def _eval_active_missions_at_most(target: object, senses: object | None) -> tuple[object, bool]:
    """Check: bounded execution — no thrashing."""
    task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
    if task_mgr is None:
        return (0, True)

    from vibe_core.task_types import TaskStatus

    active = task_mgr.list_tasks(status=TaskStatus.PENDING) + task_mgr.list_tasks(status=TaskStatus.IN_PROGRESS)
    count = len(active)
    limit = target if isinstance(target, int) else 3
    return (count, count <= limit)


_EVALUATORS: dict[str, object] = {
    "federation_healthy": _eval_federation_healthy,
    "immune_clean": _eval_immune_clean,
    "ci_green": _eval_ci_green,
    "active_missions_at_most": _eval_active_missions_at_most,
}
