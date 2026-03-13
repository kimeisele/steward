"""
IntentHandlers — Deterministic detection handlers for autonomous intents.

Each handler maps to a TaskIntent and executes WITHOUT LLM calls.
Returns None (no problem found) or a problem description string.

Extracted from AutonomyEngine to reduce LCOM4 (god-class → focused modules).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from steward.services import SVC_FEDERATION, SVC_REAPER
from vibe_core.di import ServiceRegistry

if TYPE_CHECKING:
    from steward.senses import SenseCoordinator

logger = logging.getLogger("STEWARD.INTENT_HANDLERS")


class IntentHandlers:
    """Deterministic detection handlers — 0 LLM tokens per call.

    Each method checks a specific aspect of the system and returns
    None (healthy) or a problem description (needs attention).
    """

    def __init__(
        self,
        *,
        senses: SenseCoordinator,
        vedana_fn: Callable[[], object],
        cwd: str,
    ) -> None:
        self._senses = senses
        self._vedana_fn = vedana_fn
        self._cwd = cwd

    def dispatch(self, intent: object) -> str | None:
        """Dispatch a TaskIntent to its deterministic handler.

        Returns None if no issues found, or a problem description string.
        """
        from steward.intents import TaskIntent

        dispatch = {
            TaskIntent.HEALTH_CHECK: self.execute_health_check,
            TaskIntent.SENSE_SCAN: self.execute_sense_scan,
            TaskIntent.CI_CHECK: self.execute_ci_check,
            TaskIntent.FEDERATION_HEALTH: self.execute_federation_health,
            TaskIntent.CROSS_REPO_DIAGNOSTIC: self.execute_cross_repo_diagnostic,
            TaskIntent.HEAL_REPO: self.execute_heal_repo,
            TaskIntent.UPDATE_DEPS: self.execute_update_deps,
            TaskIntent.REMOVE_DEAD_CODE: self.execute_remove_dead_code,
        }
        handler = dispatch.get(intent)
        if handler is None:
            logger.warning("No handler for intent %s", intent)
            return None
        return handler()

    # ── Detection Handlers (0 LLM tokens) ──────────────────────────────

    def execute_health_check(self) -> str | None:
        """Deterministic health check — 0 tokens."""
        self._senses.perceive_all()
        v = self._vedana_fn()
        if v.health < 0.3:
            return (
                f"Agent health critical: health={v.health:.2f} ({v.guna}), "
                f"provider={v.provider_health:.2f}, errors={v.error_pressure:.2f}, "
                f"context={v.context_pressure:.2f}. Diagnose and fix the root cause."
            )
        return None

    def execute_sense_scan(self) -> str | None:
        """Deterministic sense scan — 0 tokens."""
        aggregate = self._senses.perceive_all()
        if aggregate.total_pain > 0.7:
            failing = [f"{j.name}={p.intensity:.2f}" for j, p in aggregate.perceptions.items() if p.quality == "tamas"]
            return f"Sense scan critical: total_pain={aggregate.total_pain:.2f}, failing={', '.join(failing)}. Investigate."
        return None

    def execute_ci_check(self) -> str | None:
        """Deterministic CI status check — 0 tokens."""
        from vibe_core.mahamantra.protocols._sense import Jnanendriya

        git_sense = self._senses.senses.get(Jnanendriya.SROTRA)
        if git_sense is None:
            return None
        try:
            perception = git_sense.perceive()
            ci_status = perception.get("ci_status") if isinstance(perception, dict) else None
            if ci_status and ci_status.get("conclusion") == "failure":
                failing = ci_status.get("name", "unknown workflow")
                return f"CI is failing: workflow '{failing}'. Check the logs and fix the failing tests."
        except Exception as e:
            logger.debug("CI check failed (non-fatal): %s", e)
        return None

    def execute_update_deps(self) -> str | None:
        """Deterministic dependency freshness check — 0 tokens."""
        import json
        import subprocess

        try:
            result = subprocess.run(
                ["pip", "list", "--outdated", "--format=json"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self._cwd,
            )
            if result.returncode != 0:
                return None

            outdated = json.loads(result.stdout)
            if not outdated:
                return None

            summaries = []
            for pkg in outdated[:5]:
                name = pkg.get("name", "?")
                current = pkg.get("version", "?")
                latest = pkg.get("latest_version", "?")
                summaries.append(f"{name} {current} → {latest}")

            return (
                f"Outdated dependencies ({len(outdated)} total): "
                f"{', '.join(summaries)}. "
                f"Update them in pyproject.toml and run tests."
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
            logger.debug("Dependency check failed (non-fatal): %s", e)
            return None

    def execute_remove_dead_code(self) -> str | None:
        """Deterministic dead code detection — 0 tokens."""
        from vibe_core.mahamantra.protocols._sense import Jnanendriya

        code_sense = self._senses.senses.get(Jnanendriya.CAKSU)
        if code_sense is None:
            return None
        try:
            perception = code_sense.perceive()

            data = getattr(perception, "data", None)
            if not isinstance(data, dict):
                return None

            low_cohesion = data.get("low_cohesion", [])
            if not isinstance(low_cohesion, list):
                return None

            bad_modules = [
                entry
                for entry in low_cohesion
                if isinstance(entry, dict) and isinstance(entry.get("lcom4"), (int, float)) and entry["lcom4"] > 4
            ]
            if not bad_modules:
                return None

            worst = sorted(bad_modules, key=lambda e: e["lcom4"], reverse=True)[:3]
            details = ", ".join(f"{e.get('class', '?')} in {e.get('file', '?')} (LCOM4={e['lcom4']})" for e in worst)
            return (
                f"Low cohesion modules: {details}. "
                f"These classes have disconnected responsibilities. "
                f"Split them into focused modules or remove unused methods."
            )
        except Exception as e:
            logger.debug("Dead code check failed (non-fatal): %s", e)
            return None

    def execute_federation_health(self) -> str | None:
        """Deterministic federation health check — 0 tokens.

        Monitors: dead peers, outbox backlog, transport errors, capability coverage.
        """
        reaper = ServiceRegistry.get(SVC_REAPER)
        federation = ServiceRegistry.get(SVC_FEDERATION)

        problems: list[str] = []

        if reaper is not None:
            dead = reaper.dead_peers()
            if dead:
                problems.append(f"{len(dead)} dead peer(s): {[p.agent_id for p in dead]}")

            # Capability coverage: check critical capabilities have alive coverage
            # Only relevant when peers exist — empty federation is not degraded
            alive = reaper.alive_peers()
            if alive:
                critical_capabilities = ("code_analysis", "task_execution", "ci_automation")
                for cap in critical_capabilities:
                    if not any(cap in getattr(p, "capabilities", ()) for p in alive):
                        problems.append(f"no alive peer with capability '{cap}'")

        if federation is not None:
            stats = federation.stats()
            if stats["outbound_pending"] > 10:
                problems.append(f"outbox backlog: {stats['outbound_pending']} unsent")
            if stats["errors"] > 0:
                problems.append(f"federation errors: {stats['errors']}")

        if problems:
            return f"Federation degraded: {'; '.join(problems)}. Check transport connectivity."
        return None

    def execute_heal_repo(self) -> str | None:
        """Deterministic heal check — 0 tokens.

        Detection only: returns problem string if degraded peers found.
        Actual healing is dispatched by AutonomyEngine._execute_heal_repo().
        """
        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is None:
            return None
        degraded = reaper.suspect_peers() + reaper.dead_peers()
        if not degraded:
            return None
        peer_ids = [p.agent_id for p in degraded[:5]]
        return f"Degraded peers requiring healing: {', '.join(peer_ids)}"

    def execute_cross_repo_diagnostic(self) -> str | None:
        """Deterministic cross-repo diagnostic — 0 tokens.

        Checks degraded peers (SUSPECT/DEAD) and runs diagnostic sense if available.
        """
        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is None:
            return None

        degraded = reaper.suspect_peers() + reaper.dead_peers()
        if not degraded:
            return None

        # Report degraded peers for diagnostic follow-up
        details = []
        for peer in degraded[:5]:  # Limit to top 5
            details.append(f"{peer.agent_id} (status={peer.status.value}, trust={peer.trust:.2f})")
        return (
            f"Degraded peers requiring diagnostic: {', '.join(details)}. "
            f"Run diagnostic sense on their repos to identify issues."
        )
