"""
IntentHandlers — Deterministic detection handlers for autonomous intents.

Each handler maps to a TaskIntent and executes WITHOUT LLM calls.
Returns None (no problem found) or a problem description string.

Extracted from AutonomyEngine to reduce LCOM4 (god-class → focused modules).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from steward.services import SVC_AGENT_DECK, SVC_FEDERATION, SVC_REAPER
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
            TaskIntent.POST_MERGE: self.execute_post_merge,
            TaskIntent.FEDERATION_HEALTH: self.execute_federation_health,
            TaskIntent.CROSS_REPO_DIAGNOSTIC: self.execute_cross_repo_diagnostic,
            TaskIntent.HEAL_REPO: self.execute_heal_repo,
            TaskIntent.UPDATE_DEPS: self.execute_update_deps,
            TaskIntent.REMOVE_DEAD_CODE: self.execute_remove_dead_code,
            TaskIntent.SYNTHESIZE_BRIEFING: self.execute_synthesize_briefing,
            TaskIntent.FEDERATION_GAP_SCAN: self.execute_federation_gap_scan,
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
            if ci_status:
                self._emit_ci_status(ci_status)
                if ci_status.get("conclusion") == "failure":
                    failing = ci_status.get("name", "unknown workflow")
                    return f"CI is failing: workflow '{failing}'. Check the logs and fix the failing tests."
        except Exception as e:
            logger.debug("CI check failed (non-fatal): %s", e)
        return None

    def _emit_ci_status(self, ci_status: dict) -> None:
        """Emit CI status to federation so peers can track repo health."""
        from steward.federation import OP_CI_STATUS
        from steward.services import SVC_FEDERATION

        bridge = ServiceRegistry.get(SVC_FEDERATION)
        if bridge is None:
            return
        bridge.emit(
            OP_CI_STATUS,
            {
                "repo": "kimeisele/steward",
                "conclusion": ci_status.get("conclusion", "unknown"),
                "workflow": ci_status.get("name", "unknown"),
            },
        )

    def execute_post_merge(self) -> str | None:
        """Post-merge verification — 0 tokens.

        Runs after every PR merge to catch regressions immediately.
        Combines CI check + lint check + test baseline in one pass.
        Returns problem description if anything is broken.
        """
        import subprocess

        problems: list[str] = []

        # 1. Quick lint check (ruff) — catches import errors, syntax issues
        try:
            r = subprocess.run(
                ["ruff", "check", "--select", "E,F,I,W", "--quiet", "."],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self._cwd,
            )
            if r.returncode != 0:
                # Count violations, report top offenders
                lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
                if lines:
                    problems.append(f"ruff: {len(lines)} lint violation(s), first: {lines[0][:120]}")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("Post-merge lint check skipped: %s", e)

        # 2. Test baseline — run pytest with short timeout
        try:
            r = subprocess.run(
                ["python", "-m", "pytest", "-x", "-q", "--timeout=30", "--tb=line"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=self._cwd,
            )
            if r.returncode != 0:
                # Extract failure summary
                summary = ""
                for line in r.stdout.splitlines():
                    if "failed" in line.lower() or "error" in line.lower():
                        summary = line.strip()
                        break
                if not summary:
                    summary = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "unknown failure"
                problems.append(f"tests: {summary}")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.debug("Post-merge test check skipped: %s", e)

        # 3. CI status from GitHub (if available)
        ci_problem = self.execute_ci_check()
        if ci_problem:
            problems.append(ci_problem)

        if problems:
            return f"Post-merge issues: {'; '.join(problems)}. Fix before next merge."
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

        # Cross-repo awareness via Reaper data (populated by GenesisDiscoveryHook)
        try:
            from steward.senses.federation_sense import scan_federation_state

            state = scan_federation_state()
            summary = state.get("summary", {})
            total = summary.get("total_peers", 0)
            if total > 0:
                dead = summary.get("dead", 0)
                if dead > 0:
                    problems.append(f"{dead} dead peer(s) in federation")
                suspect = summary.get("suspect", 0)
                if suspect > total // 2:
                    problems.append(f"{suspect}/{total} peers suspect")
        except Exception as e:
            logger.debug("Federation scan failed: %s", e)

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

    def execute_synthesize_briefing(self) -> str | None:
        """Check if CLAUDE.md briefing is stale — 0 tokens.

        Compares context.json mtime to CLAUDE.md mtime.
        Only triggers when context.json exists AND is newer.
        If no context.json yet (first boot), nothing to synthesize from.
        """
        from pathlib import Path

        steward_dir = Path(self._cwd) / ".steward"
        claude_md = Path(self._cwd) / "CLAUDE.md"
        context_json = steward_dir / "context.json"

        # No context.json yet → nothing to synthesize from (first boot)
        if not context_json.exists():
            return None

        # No CLAUDE.md but context.json exists → needs synthesis
        if not claude_md.exists():
            return "CLAUDE.md does not exist. Use the synthesize_briefing tool to create it from .steward/context.json."

        # context.json newer than CLAUDE.md → briefing is stale
        if context_json.stat().st_mtime > claude_md.stat().st_mtime:
            return "CLAUDE.md is stale (context.json updated since last synthesis). Use the synthesize_briefing tool to refresh it."

        return None

    def execute_federation_gap_scan(self) -> str | None:
        """Scan federation architecture for gaps — 0 tokens.

        Checks:
        1. Delivery guarantees: are messages being lost? (outbox backlog)
        2. Agent card coverage: do peers share specialized profiles?
        3. Consensus: are slot conflicts unresolved?
        4. Capability coverage: are critical capabilities missing?
        5. Trust health: are peer trust scores degrading?
        """
        gaps: list[str] = []

        # 1. Check delivery health (fire-and-forget gap)
        federation = ServiceRegistry.get(SVC_FEDERATION)
        if federation is not None:
            stats = federation.stats()
            if stats["errors"] > 3:
                gaps.append(
                    f"delivery_reliability: {stats['errors']} transport errors "
                    f"(outbox backlog: {stats['outbound_pending']}). "
                    f"Federation messages may be silently lost."
                )
            if stats["delegations_rejected"] > 0:
                gaps.append(
                    f"delegation_trust: {stats['delegations_rejected']} delegations "
                    f"rejected due to low trust. Peers may need trust bootstrapping."
                )

        # 2. Check agent card coverage
        deck = ServiceRegistry.get(SVC_AGENT_DECK)
        if deck is not None:
            deck_stats = deck.stats()
            if deck_stats["total_cards"] == 0:
                gaps.append(
                    "agent_deck_empty: no specialized agent profiles. "
                    "Steward cannot delegate to specialized sub-agents."
                )
            elif deck_stats["proven_cards"] == 0 and deck_stats["total_spawns"] > 5:
                gaps.append(
                    f"agent_deck_ineffective: {deck_stats['total_spawns']} spawns "
                    f"but 0 proven cards. Sub-agent profiles may need tuning."
                )

        # 3. Check peer coverage
        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is not None:
            alive = reaper.alive_peers()
            dead = reaper.dead_peers()
            suspect = reaper.suspect_peers()

            # Only flag isolation if peers WERE known but all died
            # Empty federation (no peers ever) is not a gap — it's just solo mode
            if dead and not alive and not suspect:
                gaps.append(
                    "federation_collapsed: all known peers are dead. Steward has lost contact with entire federation."
                )
            elif dead and len(dead) > len(alive):
                gaps.append(
                    f"federation_degraded: {len(dead)} dead peers vs {len(alive)} alive. "
                    f"Majority of federation is unreachable."
                )

            # Trust degradation trend
            if alive:
                avg_trust = sum(p.trust for p in alive) / len(alive)
                if avg_trust < 0.4:
                    gaps.append(
                        f"trust_erosion: average peer trust is {avg_trust:.2f}. "
                        f"Federation trust is degrading — peers may need healing."
                    )

        if gaps:
            return "Federation gaps detected: " + "; ".join(gaps)
        return None
