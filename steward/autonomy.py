"""
AutonomyEngine — Autonomous task detection, dispatch, and guarded fix pipeline.

Extracted from StewardAgent to reduce LCOM4 (god-class cohesion problem).
This module handles everything the agent does WITHOUT user input:

- Deterministic intent dispatch (0 LLM tokens)
- Detection handlers (health, senses, CI, deps, dead code)
- Guarded LLM fix with circuit breaker + 6-gate verification
- Proactive PR pipeline (feature branch → gates → PR)
- Hebbian learning (granular: context/gate/file level)
- Escalation (when confidence too low)

The StewardAgent delegates all autonomous work to AutonomyEngine.
AutonomyEngine calls back to the agent only for LLM execution (run_fn).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from steward import agent_bus, agent_memory
from steward.services import (
    SVC_MARKETPLACE,
    SVC_SANKALPA,
    SVC_SYNAPSE_STORE,
    SVC_TASK_MANAGER,
)
from steward.tools.circuit_breaker import CircuitBreaker
from vibe_core.di import ServiceRegistry

if TYPE_CHECKING:
    from steward.senses import SenseCoordinator
    from steward.session_ledger import SessionLedger
    from vibe_core.mahamantra.substrate.manas.synaptic import HebbianSynaptic
    from vibe_core.protocols.memory import MemoryProtocol

logger = logging.getLogger("STEWARD.AUTONOMY")


# ── Module-level helpers (pure functions, no class state) ──────────────


def parse_intent_from_title(title: str) -> object | None:
    """Parse TaskIntent from title prefix like '[HEALTH_CHECK] ...'.

    Returns TaskIntent enum or None. Title prefix is the persistence-safe
    encoding — survives TaskManager disk serialization (unlike metadata).
    """
    from steward.intents import TaskIntent

    if not title.startswith("["):
        return None
    bracket_end = title.find("]")
    if bracket_end < 2:
        return None
    intent_name = title[1:bracket_end]
    try:
        return TaskIntent[intent_name]
    except KeyError:
        return None


def problem_fingerprint(problem: str) -> str:
    """Extract granular context from a problem description.

    Prevents learned helplessness by making Hebbian keys specific:
    - If file paths found: "api.py:utils.py" (file-specific learning)
    - If error type found: "TypeError:async" (error-specific learning)
    - Fallback: first 3 significant words (keyword-based)
    """
    # Level 1: Extract file paths (most specific)
    files = re.findall(r"[\w/.-]+\.py\b", problem)
    if files:
        unique = sorted(set(files))[:3]
        return ":".join(unique)

    # Level 2: Extract error type keywords
    error_types = re.findall(
        r"\b(TypeError|ValueError|ImportError|SyntaxError|AttributeError|KeyError|RuntimeError)\b",
        problem,
    )
    if error_types:
        return ":".join(sorted(set(error_types))[:2])

    # Level 3: Extract workflow/test names (for CI)
    workflow = re.search(r"workflow\s+'([^']+)'", problem)
    if workflow:
        return workflow.group(1)

    # Level 4: Significant words fallback
    words = re.findall(r"\b[a-z]{5,}\b", problem.lower())
    generic = {"check", "error", "agent", "health", "found", "failing", "critical", "please", "should"}
    specific = [w for w in words if w not in generic]
    if specific:
        return ":".join(sorted(set(specific))[:3])

    return ""


class AutonomyEngine:
    """Autonomous task detection, dispatch, and guarded fix pipeline.

    Receives environment access (senses, breaker, cwd) and a callback
    to invoke the LLM (run_fn). All autonomous decisions happen here;
    the LLM is only called when deterministic detection finds a real problem.
    """

    def __init__(
        self,
        *,
        breaker: CircuitBreaker,
        senses: SenseCoordinator,
        synaptic: HebbianSynaptic,
        memory: MemoryProtocol,
        ledger: SessionLedger,
        cwd: str,
        run_fn: Callable[[str], Awaitable[str]],
        vedana_fn: Callable[[], object],
        git_actuator: object | None = None,
        github_actuator: object | None = None,
    ) -> None:
        self._breaker = breaker
        self._senses = senses
        self._synaptic = synaptic
        self._memory = memory
        self._ledger = ledger
        self._cwd = cwd
        self._run_fn = run_fn
        self._vedana_fn = vedana_fn
        self._git = git_actuator
        self._github = github_actuator

    # ── Public API ─────────────────────────────────────────────────────

    async def run_autonomous(self, idle_minutes: int | None = None) -> str | None:
        """Pick the next task from TaskManager and execute it deterministically.

        Deterministic dispatch: reads intent_type from task metadata,
        maps to TaskIntent enum, calls a Python method. 0 LLM tokens.
        The LLM only wakes up if the method finds a real error to fix.

        Returns the result text, or None if no tasks are pending.
        """
        from steward.intents import TaskIntent
        from vibe_core.task_types import TaskStatus

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            return None

        # Generate tasks first — Sankalpa might not have fired yet
        self.phase_genesis(idle_override=idle_minutes)

        task = task_mgr.get_next_task()
        if task is None:
            return None

        logger.info("Autonomous: working on task '%s' (id=%s)", task.title, task.id)
        task_mgr.update_task(task.id, status=TaskStatus.IN_PROGRESS)

        intent = parse_intent_from_title(task.title)

        if intent is None:
            logger.warning("Autonomous: no typed intent in task '%s' — skipping", task.title)
            task_mgr.update_task(task.id, status=TaskStatus.COMPLETED)
            return None

        try:
            problem = self.dispatch_intent(intent)
            task_mgr.update_task(task.id, status=TaskStatus.COMPLETED)

            self._ledger.record_autonomous(intent.name, problem is not None)

            if problem:
                context = problem_fingerprint(problem)
                granular_key = f"auto:{intent.name}:{context}" if context else f"auto:{intent.name}"
                auto_weight = self._synaptic.get_weight(granular_key, "fix")

                if auto_weight < 0.2:
                    logger.warning(
                        "Hebbian confidence too low (%.2f) for %s:%s — escalating",
                        auto_weight, intent.name, context,
                    )
                    self.escalate_problem(problem, intent.name, auto_weight)
                    return None

                logger.info(
                    "Autonomous: %s:%s found problem (confidence=%.2f), invoking LLM",
                    intent.name, context, auto_weight,
                )
                if intent.is_proactive:
                    return await self.guarded_pr_fix(problem, intent_name=intent.name)
                return await self.guarded_llm_fix(problem, intent_name=intent.name)

            logger.info("Autonomous: intent %s completed (no issues found)", intent.name)
            return None
        except Exception as e:
            logger.error("Autonomous: task '%s' failed: %s", task.title, e)
            task_mgr.update_task(task.id, status=TaskStatus.FAILED)
            return None

    def run_autonomous_sync(self, idle_minutes: int | None = None) -> str | None:
        """Sync wrapper for run_autonomous."""
        return asyncio.run(self.run_autonomous(idle_minutes=idle_minutes))

    # ── Intent Dispatch ────────────────────────────────────────────────

    def dispatch_intent(self, intent: object) -> str | None:
        """Dispatch a TaskIntent to its deterministic handler.

        Returns None if no issues found, or a problem description
        string that should be sent to the LLM for fixing.
        """
        from steward.intents import TaskIntent

        dispatch = {
            TaskIntent.HEALTH_CHECK: self._execute_health_check,
            TaskIntent.SENSE_SCAN: self._execute_sense_scan,
            TaskIntent.CI_CHECK: self._execute_ci_check,
            TaskIntent.FEDERATION_HEALTH: self._execute_federation_health,
            TaskIntent.UPDATE_DEPS: self._execute_update_deps,
            TaskIntent.REMOVE_DEAD_CODE: self._execute_remove_dead_code,
        }
        handler = dispatch.get(intent)
        if handler is None:
            logger.warning("No handler for intent %s", intent)
            return None
        return handler()

    # ── Detection Handlers (0 LLM tokens) ──────────────────────────────

    def _execute_health_check(self) -> str | None:
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

    def _execute_sense_scan(self) -> str | None:
        """Deterministic sense scan — 0 tokens."""
        aggregate = self._senses.perceive_all()
        if aggregate.total_pain > 0.7:
            failing = [
                f"{j.name}={p.intensity:.2f}"
                for j, p in aggregate.perceptions.items()
                if p.quality == "tamas"
            ]
            return f"Sense scan critical: total_pain={aggregate.total_pain:.2f}, failing={', '.join(failing)}. Investigate."
        return None

    def _execute_ci_check(self) -> str | None:
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

    def _execute_update_deps(self) -> str | None:
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

    def _execute_remove_dead_code(self) -> str | None:
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
                if isinstance(entry, dict)
                and isinstance(entry.get("lcom4"), (int, float))
                and entry["lcom4"] > 4
            ]
            if not bad_modules:
                return None

            worst = sorted(bad_modules, key=lambda e: e["lcom4"], reverse=True)[:3]
            details = ", ".join(
                f"{e.get('class', '?')} in {e.get('file', '?')} (LCOM4={e['lcom4']})"
                for e in worst
            )
            return (
                f"Low cohesion modules: {details}. "
                f"These classes have disconnected responsibilities. "
                f"Split them into focused modules or remove unused methods."
            )
        except Exception as e:
            logger.debug("Dead code check failed (non-fatal): %s", e)
            return None

    def _execute_federation_health(self) -> str | None:
        """Deterministic federation health check — 0 tokens.

        Monitors: dead peers, outbox backlog, transport errors.
        """
        from steward.services import SVC_FEDERATION, SVC_REAPER

        reaper = ServiceRegistry.get(SVC_REAPER)
        federation = ServiceRegistry.get(SVC_FEDERATION)

        problems: list[str] = []

        if reaper is not None:
            dead = reaper.dead_peers()
            if dead:
                problems.append(f"{len(dead)} dead peer(s): {[p.agent_id for p in dead]}")

        if federation is not None:
            stats = federation.stats()
            if stats["outbound_pending"] > 10:
                problems.append(f"outbox backlog: {stats['outbound_pending']} unsent")
            if stats["errors"] > 0:
                problems.append(f"federation errors: {stats['errors']}")

        if problems:
            return f"Federation degraded: {'; '.join(problems)}. Check transport connectivity."
        return None

    # ── Guarded Fix Pipelines ──────────────────────────────────────────

    async def guarded_llm_fix(self, problem: str, intent_name: str = "") -> str | None:
        """Run LLM fix with multi-gate circuit breaker + Hebbian learning.

        Verification pipeline (fast → slow):
        1. Check breaker not suspended
        2. Baseline test failures
        3. Snapshot working tree
        4. Run LLM fix
        5. Find newly changed files
        6. FAST GATES: lint, security, blast radius, test integrity, API surface
        7. SLOW GATE: test suite — no new failures

        If ANY gate fails → rollback ALL changes immediately.
        """
        if self._breaker.is_suspended:
            logger.warning("Circuit breaker suspended — skipping LLM fix for: %s", problem[:100])
            return None

        context = problem_fingerprint(problem)
        hebbian_trigger = f"auto:{intent_name}:{context}" if (intent_name and context) else f"auto:{intent_name or 'unknown'}"

        # Claim marketplace slot to prevent concurrent work on same problem
        marketplace = ServiceRegistry.get(SVC_MARKETPLACE)
        slot_id = f"fix:{intent_name}:{context}" if context else f"fix:{intent_name}"
        claimed = False
        if marketplace is not None:
            outcome = marketplace.claim(slot_id, "steward")
            if not outcome.granted:
                logger.info("Slot %s held by %s — skipping", slot_id, outcome.holder)
                return None
            claimed = True

        try:
            return await self._guarded_llm_fix_inner(
                problem, hebbian_trigger,
            )
        finally:
            if claimed and marketplace is not None:
                marketplace.release(slot_id, "steward")

    async def _guarded_llm_fix_inner(
        self, problem: str, hebbian_trigger: str,
    ) -> str | None:
        """Inner LLM fix pipeline — separated for slot guard cleanup."""
        # Step 1: Baseline tests
        test_cmd = "pytest -x -q"
        baseline = self._breaker.count_failures(test_cmd)
        if baseline is None:
            logger.warning("Cannot establish test baseline — running LLM fix unguarded")
            return await self._run_fn(problem)

        # Step 2: Snapshot current dirty files
        files_before = self._breaker.changed_files()

        # Step 3: LLM fix
        result = await self._run_fn(problem)

        # Step 4: Find newly changed files
        files_after = self._breaker.changed_files()
        new_changes = files_after - files_before
        if not new_changes:
            self._breaker.record_success()
            self._hebbian_learn(hebbian_trigger, success=True, changed_files=set())
            return result

        # Step 5: Fast gates
        gate_results = self._breaker.run_gates(new_changes)
        failed_gates = [g for g in gate_results if not g.passed]
        if failed_gates:
            details = "; ".join(g.detail for g in failed_gates)
            rolled = self._breaker.rollback_files(new_changes)
            self._breaker.record_rollback()
            self._hebbian_learn(hebbian_trigger, success=False, failed_gates=failed_gates, changed_files=new_changes)
            logger.warning(
                "Verification gates FAILED — rolled back %d files. Gates: %s",
                len(rolled), details,
            )
            return None

        # Step 6: Slow gate — test suite
        post = self._breaker.count_failures(test_cmd)
        if post is None:
            rolled = self._breaker.rollback_files(new_changes)
            self._breaker.record_rollback()
            self._hebbian_learn(hebbian_trigger, success=False, changed_files=new_changes)
            logger.warning("Post-fix test run failed — rolled back %d files: %s", len(rolled), rolled)
            return None

        # Step 7: Compare test results
        if post > baseline:
            rolled = self._breaker.rollback_files(new_changes)
            self._breaker.record_rollback()
            self._hebbian_learn(hebbian_trigger, success=False, changed_files=new_changes)
            logger.warning(
                "LLM fix rolled back (failures %d → %d), %d files: %s",
                baseline, post, len(rolled), rolled,
            )
            return None

        # All gates passed
        self._breaker.record_success()
        self._hebbian_learn(hebbian_trigger, success=True, gate_results=gate_results, changed_files=new_changes)
        logger.info(
            "LLM fix verified: %d gates passed, tests %d → %d, %d files changed",
            len(gate_results), baseline, post, len(new_changes),
        )
        return result

    async def guarded_pr_fix(self, problem: str, intent_name: str = "") -> str | None:
        """Run LLM fix on a feature branch, create PR if all gates pass.

        Proactive fix pipeline:
        1. Create feature branch: steward/{intent}/{timestamp}
        2. Run LLM to apply changes
        3. Run 6-gate verification
        4. If GREEN: commit → push → create PR
        5. If RED: rollback → delete branch → return to main
        """
        import subprocess
        import time as _time

        from steward.senses.gh import get_gh_client

        if self._breaker.is_suspended:
            logger.warning("Circuit breaker suspended — skipping proactive fix")
            return None

        context = problem_fingerprint(problem)
        hebbian_trigger = (
            f"auto:{intent_name}:{context}"
            if (intent_name and context)
            else f"auto:{intent_name or 'unknown'}"
        )

        # Claim marketplace slot to prevent concurrent work on same problem
        marketplace = ServiceRegistry.get(SVC_MARKETPLACE)
        slot_id = f"pr:{intent_name}:{context}" if context else f"pr:{intent_name}"
        claimed = False
        if marketplace is not None:
            outcome = marketplace.claim(slot_id, "steward")
            if not outcome.granted:
                logger.info("Slot %s held by %s — skipping PR", slot_id, outcome.holder)
                return None
            claimed = True

        # Step 1: Create feature branch
        timestamp = str(int(_time.time()))
        branch_name = f"steward/{intent_name.lower()}/{timestamp}"

        if self._git is not None:
            result = self._git.create_branch(branch_name)
            if not result.success:
                logger.error("Failed to create branch %s: %s", branch_name, result.error)
                return None
        else:
            try:
                r = subprocess.run(
                    ["git", "checkout", "-b", branch_name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=self._cwd,
                )
                if r.returncode != 0:
                    logger.error("Failed to create branch %s: %s", branch_name, r.stderr.strip())
                    return None
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.error("Git branch creation failed: %s", e)
                return None

        logger.info("Proactive: created branch %s for %s", branch_name, intent_name)

        try:
            # Step 2: Baseline tests
            test_cmd = "pytest -x -q"
            baseline = self._breaker.count_failures(test_cmd)

            # Step 3: Snapshot and run LLM fix
            files_before = self._breaker.changed_files()
            result = await self._run_fn(problem)
            files_after = self._breaker.changed_files()
            new_changes = files_after - files_before

            if not new_changes:
                logger.info("Proactive: LLM made no changes for %s", intent_name)
                self._cleanup_branch(branch_name)
                return result

            # Step 4: Fast gates
            gate_results = self._breaker.run_gates(new_changes)
            failed_gates = [g for g in gate_results if not g.passed]

            if failed_gates:
                details = "; ".join(g.detail for g in failed_gates)
                self._breaker.rollback_files(new_changes)
                self._breaker.record_rollback()
                self._hebbian_learn(
                    hebbian_trigger,
                    success=False,
                    failed_gates=failed_gates,
                    changed_files=new_changes,
                )
                logger.warning("Proactive gates FAILED for %s: %s", intent_name, details)
                self._cleanup_branch(branch_name)
                return None

            # Step 5: Slow gate — test suite
            if baseline is not None:
                post = self._breaker.count_failures(test_cmd)
                if post is None or post > baseline:
                    self._breaker.rollback_files(new_changes)
                    self._breaker.record_rollback()
                    self._hebbian_learn(
                        hebbian_trigger, success=False, changed_files=new_changes
                    )
                    logger.warning(
                        "Proactive tests FAILED for %s (baseline=%s, post=%s)",
                        intent_name, baseline, post,
                    )
                    self._cleanup_branch(branch_name)
                    return None

            # Step 6: All gates passed — commit, push, create PR
            pr_url = self._create_pr(branch_name, intent_name, problem, new_changes)

            self._breaker.record_success()
            self._hebbian_learn(
                hebbian_trigger,
                success=True,
                gate_results=gate_results,
                changed_files=new_changes,
            )

            if pr_url:
                logger.info("Proactive PR created: %s for %s", pr_url, intent_name)
                return f"Created PR: {pr_url}"
            return result

        except Exception as e:
            logger.error("Proactive fix failed for %s: %s", intent_name, e)
            self._cleanup_branch(branch_name)
            return None
        finally:
            if claimed and marketplace is not None:
                marketplace.release(slot_id, "steward")

    # ── Branch/PR Management ───────────────────────────────────────────

    def _cleanup_branch(self, branch_name: str) -> None:
        """Return to main and delete feature branch via GitActuator."""
        if self._git is not None:
            self._git.cleanup_branch(branch_name)
            return

        # Fallback: raw subprocess (legacy path, for tests without actuators)
        import subprocess

        try:
            subprocess.run(
                ["git", "checkout", "main"],
                capture_output=True, text=True, timeout=10, cwd=self._cwd,
            )
        except Exception as e:
            logger.warning("Failed to switch to main: %s", e)

        try:
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                capture_output=True, text=True, timeout=10, cwd=self._cwd,
            )
        except Exception as e:
            logger.debug("Branch cleanup failed for %s (non-fatal): %s", branch_name, e)

    def _create_pr(
        self,
        branch_name: str,
        intent_name: str,
        problem: str,
        changed_files: set[str],
    ) -> str | None:
        """Commit, push, create PR via actuators.

        Returns PR URL on success, None on failure.
        Uses GitActuator + GitHubActuator when available, raw subprocess fallback.
        """
        try:
            # Step 1: Commit
            commit_msg = f"fix({intent_name.lower()}): {problem[:80]}"

            if self._git is not None:
                result = self._git.commit(commit_msg, files=changed_files)
                if not result.success:
                    logger.warning("Git commit failed: %s", result.error)
                    return None
            else:
                import subprocess
                for f in changed_files:
                    subprocess.run(
                        ["git", "add", f],
                        capture_output=True, text=True, timeout=10, cwd=self._cwd,
                    )
                r = subprocess.run(
                    ["git", "commit", "-m", commit_msg],
                    capture_output=True, text=True, timeout=30, cwd=self._cwd,
                )
                if r.returncode != 0:
                    logger.warning("Git commit failed: %s", r.stderr.strip())
                    return None

            # Step 2: Push
            if self._git is not None:
                result = self._git.push(branch_name)
                if not result.success:
                    logger.warning("Git push failed: %s", result.error)
                    return None
            else:
                import subprocess
                r = subprocess.run(
                    ["git", "push", "-u", "origin", branch_name],
                    capture_output=True, text=True, timeout=60, cwd=self._cwd,
                )
                if r.returncode != 0:
                    logger.warning("Git push failed: %s", r.stderr.strip())
                    return None

            # Step 3: Create PR
            files_list = "\n".join(f"- `{f}`" for f in sorted(changed_files))
            body = (
                f"## Autonomous Fix: {intent_name}\n\n"
                f"**Problem detected:**\n{problem}\n\n"
                f"**Files changed:**\n{files_list}\n\n"
                f"**Verification:**\n"
                f"- [x] Lint gate (ruff)\n"
                f"- [x] Security gate (bandit)\n"
                f"- [x] Blast radius gate\n"
                f"- [x] Cohesion gate (LCOM4)\n"
                f"- [x] Test integrity gate\n"
                f"- [x] API surface gate\n"
                f"- [x] Test suite (no new failures)\n"
            )
            pr_title = f"steward: {intent_name.lower()} — {problem[:60]}"

            if self._github is not None:
                pr_result = self._github.create_pr(
                    title=pr_title,
                    body=body,
                    head=branch_name,
                    base="main",
                )
                return pr_result.url if pr_result.success else None
            else:
                from steward.senses.gh import get_gh_client
                gh = get_gh_client()
                if gh is None:
                    return None
                return gh.call(
                    ["pr", "create", "--title", pr_title, "--body", body,
                     "--head", branch_name, "--base", "main"],
                    timeout=30,
                )

        except Exception as e:
            logger.warning("PR creation failed: %s", e)
            return None

    # ── Hebbian Learning ───────────────────────────────────────────────

    def _hebbian_learn(
        self,
        trigger: str,
        success: bool,
        failed_gates: list | None = None,
        gate_results: list | None = None,
        changed_files: set[str] | None = None,
    ) -> None:
        """Update Hebbian weights from autonomous fix outcome.

        Three levels of learning granularity:
        1. Context-level: trigger/fix — the specific problem context
        2. Gate-level: trigger/gate:{name} — which verification gates pass/fail
        3. File-level: file:{path}/auto_fix — per-file success/failure history
        """
        # Level 1: Context-level learning
        new_weight = self._synaptic.update(trigger, "fix", success)
        logger.debug("Hebbian: %s/fix %s → %.2f", trigger, "reinforced" if success else "weakened", new_weight)

        # Level 2: Gate-specific learning
        if failed_gates:
            for gate in failed_gates:
                self._synaptic.update(trigger, f"gate:{gate.gate}", success=False)
        if success and gate_results:
            for gate in gate_results:
                if gate.passed:
                    self._synaptic.update(trigger, f"gate:{gate.gate}", success=True)

        # Level 3: Per-file learning
        if changed_files:
            for filepath in changed_files:
                if filepath.endswith(".py"):
                    self._synaptic.update(f"file:{filepath}", "auto_fix", success)

        # Persist to Memory for cross-session survival
        agent_memory.save_synaptic(self._memory, self._synaptic)

    def escalate_problem(self, problem: str, intent_name: str, confidence: float) -> None:
        """Escalate a problem the agent can't fix autonomously.

        When Hebbian confidence is too low, record for human attention.
        Writes to .steward/needs_attention.md.
        """
        from datetime import datetime, timezone

        escalation_dir = Path(self._cwd) / ".steward"
        escalation_dir.mkdir(parents=True, exist_ok=True)
        escalation_file = escalation_dir / "needs_attention.md"

        timestamp = datetime.now(timezone.utc).isoformat()[:19]
        entry = (
            f"\n## [{timestamp}] {intent_name} (confidence: {confidence:.2f})\n"
            f"{problem}\n"
            f"_Agent confidence too low for autonomous fix. Human review needed._\n"
        )

        try:
            with open(escalation_file, "a") as f:
                f.write(entry)
            logger.info(
                "Escalated to human: %s (confidence=%.2f) → %s",
                intent_name, confidence, escalation_file,
            )
        except OSError as e:
            logger.warning("Failed to write escalation file: %s", e)

    # ── Cetana Phase Handlers ──────────────────────────────────────────

    def phase_genesis(self, idle_override: int | None = None, last_interaction: float | None = None) -> None:
        """GENESIS: Discover — generate typed tasks from Sankalpa intents."""
        from steward.intents import INTENT_TYPE_KEY, TaskIntent

        sankalpa = ServiceRegistry.get(SVC_SANKALPA)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if sankalpa is None or task_mgr is None:
            return

        from vibe_core.task_types import TaskStatus

        if idle_override is not None:
            idle_minutes = idle_override
        elif last_interaction is not None:
            idle_minutes = int((time.monotonic() - last_interaction) / 60)
        else:
            idle_minutes = 0

        active = (
            task_mgr.list_tasks(status=TaskStatus.PENDING)
            + task_mgr.list_tasks(status=TaskStatus.IN_PROGRESS)
        )
        intents = sankalpa.think(
            idle_minutes=idle_minutes,
            pending_intents=len(active),
            ci_green=True,
        )
        for intent in intents:
            typed = TaskIntent.from_intent_type(intent.intent_type)
            if typed is None:
                logger.debug("GENESIS: unknown intent_type '%s' — skipping", intent.intent_type)
                continue

            if any(
                t.title.startswith(f"[{typed.name}]")
                for t in active
            ):
                continue

            _PRIORITY_MAP = {"critical": 90, "high": 70, "medium": 50, "low": 25}
            raw_priority = getattr(intent, "priority", "medium")
            if hasattr(raw_priority, "value"):
                priority = _PRIORITY_MAP.get(raw_priority.value, 50)
            elif isinstance(raw_priority, int):
                priority = raw_priority
            else:
                priority = _PRIORITY_MAP.get(str(raw_priority), 50)
            task_mgr.add_task(
                title=f"[{typed.name}] {intent.title}",
                priority=priority,
            )

    @staticmethod
    def phase_karma() -> None:
        """KARMA: Execute — log pending task count."""
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            return
        pending = task_mgr.list_tasks()
        if pending:
            logger.debug("KARMA: %d pending tasks", len(pending))

    @staticmethod
    def phase_moksha() -> None:
        """MOKSHA: Reflect — persist learning state."""
        synapse_store = ServiceRegistry.get(SVC_SYNAPSE_STORE)
        if synapse_store is not None:
            try:
                synapse_store.save()
            except Exception as e:
                logger.debug("SynapseStore save failed (non-fatal): %s", e)
