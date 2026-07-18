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
from steward.services import SVC_FEDERATION_GATEWAY, SVC_IMMUNE, SVC_PROVIDER, SVC_REAPER
from vibe_core.di import ServiceRegistry

logger = logging.getLogger("STEWARD.HOOKS.MOKSHA_HEALTH")

_HEALTH_FILE = Path(".steward/federation_health.json")


class _ShapeDrift(Exception):
    """steward-protocol get_status() shape deviates from the pinned form (spec §5.3a)."""


def _breaker_ok(b: dict | None) -> bool:
    if b is None:
        return True  # no breaker for this provider = usable
    if "state" not in b:  # fail loud instead of silently "healthy"
        raise _ShapeDrift("breaker.get_status(): 'state' missing")
    return b["state"] != "open"  # {closed, open, half_open}; skip only on OPEN


def _quota_ok(q: dict | None) -> bool:
    if not q:
        return True
    try:  # missing expected keys -> fail loud
        return (
            q["requests"]["percent_used"] < 100
            and q["tokens"]["percent_used"] < 100
            and q["cost"]["this_hour_usd"] < q["cost"]["limit_per_hour_usd"]
        )
    except (KeyError, TypeError) as e:
        raise _ShapeDrift(f"quota.get_status() shape: {e}") from e


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
        prev = {"consecutive_collapsed_cycles": 0, "total_calls": 0, "total_failures": 0}
        try:
            _c = json.loads(_HEALTH_FILE.read_text()).get("cognition", {})
            prev["consecutive_collapsed_cycles"] = _c.get("consecutive_collapsed_cycles", 0)
            prev["total_calls"] = _c.get("total_calls", 0)
            prev["total_failures"] = _c.get("total_failures", 0)
        except (OSError, ValueError, TypeError):
            pass  # missing/torn file -> defaults

        report = _build_health_report(prev)
        payload = json.dumps(report, indent=2) + "\n"

        # Write to .steward/ (local state)
        output_dir = Path(".steward")
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            (output_dir / "federation_health.json").write_text(payload)
        except OSError as e:
            logger.warning("Failed to write health report to .steward: %s", e)

        # Write to data/federation/ (git-visible, agent-city reads this path)
        fed_dir = Path("data/federation")
        fed_dir.mkdir(parents=True, exist_ok=True)
        try:
            (fed_dir / "steward_health.json").write_text(payload)
        except OSError as e:
            logger.warning("Failed to write health report to federation dir: %s", e)

        ctx.operations.append("moksha_health_report:ok")


def _build_health_report(prev: dict | None = None) -> dict:
    """Aggregate health data from reaper + immune + gateway + cognition."""
    reaper = ServiceRegistry.get(SVC_REAPER)
    immune = ServiceRegistry.get(SVC_IMMUNE)
    gateway = ServiceRegistry.get(SVC_FEDERATION_GATEWAY)

    report: dict = {
        "timestamp": time.time(),
        "peers": {"alive": 0, "suspect": 0, "dead": 0, "total": 0},
        "immune": {},
        "gateway": {},
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

    if gateway is not None:
        report["gateway"] = gateway.stats()

    prev = prev or {"consecutive_collapsed_cycles": 0, "total_calls": 0, "total_failures": 0}
    cog = {
        "providers_alive": 0, "providers_total": 0, "providers_usable": 0,
        "total_calls": 0, "total_failures": 0, "calls_delta": 0, "fail_delta": 0,
        "hard_down": False, "degraded": False, "skip_collapse": False, "decode_error": None,
        "consecutive_collapsed_cycles": prev["consecutive_collapsed_cycles"],
    }
    provider = ServiceRegistry.get(SVC_PROVIDER)
    if provider is not None and hasattr(provider, "stats"):
        ps = provider.stats()
        providers = ps.get("providers", [])
        alive = sum(1 for p in providers if p.get("alive"))
        total = len(providers)
        tc = ps.get("total_calls", 0)
        tf = ps.get("total_failures", 0)
        # Run boundary: fresh process resets totals to 0 -> delta = current totals
        if tc >= prev["total_calls"]:
            cd = tc - prev["total_calls"]
            fd = tf - prev["total_failures"]
        else:
            cd = tc
            fd = tf
        hard_down = total > 0 and alive == 0
        degraded = cd == 0 and fd > 0  # failures but no success this cycle (§3 semantics)
        try:
            usable = sum(
                1
                for p in providers
                if p.get("alive") and _breaker_ok(p.get("breaker")) and _quota_ok(ps.get("quota"))
            )
            skip_collapse = total > 0 and usable == 0
            collapsed = hard_down or degraded or skip_collapse
            streak = prev["consecutive_collapsed_cycles"] + 1 if collapsed else 0
        except _ShapeDrift as e:  # fail loud, not silently "healthy"
            logger.warning("cognition decode drift: %s", e)
            usable = 0
            skip_collapse = False
            cog["decode_error"] = str(e)
            streak = prev["consecutive_collapsed_cycles"]  # streak frozen, not guessed
        cog.update({
            "providers_alive": alive, "providers_total": total,
            "providers_usable": usable,
            "total_calls": tc, "total_failures": tf,
            "calls_delta": cd, "fail_delta": fd,
            "hard_down": hard_down, "degraded": degraded,
            "skip_collapse": skip_collapse,
            "consecutive_collapsed_cycles": streak,
        })
    report["cognition"] = cog

    return report
