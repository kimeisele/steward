"""
MOKSHA Health Report Hook — Persist federation health state.

MOKSHA = liberation/completion. After each cycle, write the
aggregate health state to .steward/federation_health.json.
This file is git-committable and readable by any federation peer.
No API, no dashboard — just a file in the repo.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from steward.phase_hook import MOKSHA, BasePhaseHook, PhaseContext
from steward.services import SVC_IMMUNE, SVC_REAPER
from vibe_core.di import ServiceRegistry

logger = logging.getLogger("STEWARD.HOOKS.MOKSHA_HEALTH")


class MokshaHealthReportHook(BasePhaseHook):
    """Write federation health snapshot after each MURALI cycle."""

    @property
    def name(self) -> str:
        return "moksha_health_report"

    @property
    def phase(self) -> str:
        return MOKSHA

    @property
    def priority(self) -> int:
        return 40  # Before persistence (50) and federation flush (80)

    def execute(self, ctx: PhaseContext) -> None:
        report = _build_health_report()

        output_dir = Path(".steward")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "federation_health.json"

        try:
            output_path.write_text(json.dumps(report, indent=2) + "\n")
            ctx.operations.append("moksha_health_report:ok")
        except OSError as e:
            logger.warning("Failed to write health report: %s", e)


def _build_health_report() -> dict:
    """Aggregate health data from reaper + immune."""
    reaper = ServiceRegistry.get(SVC_REAPER)
    immune = ServiceRegistry.get(SVC_IMMUNE)

    report: dict = {
        "timestamp": time.time(),
        "peers": {"alive": 0, "suspect": 0, "dead": 0, "total": 0},
        "immune": {},
    }

    if reaper is not None:
        alive = reaper.alive_peers()
        suspect = reaper.suspect_peers()
        dead = reaper.dead_peers()
        report["peers"] = {
            "alive": len(alive),
            "suspect": len(suspect),
            "dead": len(dead),
            "total": len(alive) + len(suspect) + len(dead),
            "suspect_ids": [p.agent_id for p in suspect],
            "dead_ids": [p.agent_id for p in dead],
        }

    if immune is not None:
        report["immune"] = immune.stats()

    return report
