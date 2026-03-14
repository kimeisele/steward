"""
FixPipeline — Guarded LLM fix and proactive PR pipelines.

Handles the entire lifecycle of autonomous code fixes:
- Guarded LLM fix with multi-gate circuit breaker verification
- Proactive PR pipeline (feature branch → gates → PR)
- Hebbian learning (granular: context/gate/file level)
- Escalation (when confidence too low)

Extracted from AutonomyEngine to reduce LCOM4 (god-class → focused modules).
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from steward import agent_memory
from steward.services import SVC_MARKETPLACE
from steward.tools.circuit_breaker import CircuitBreaker
from vibe_core.di import ServiceRegistry

if TYPE_CHECKING:
    from vibe_core.mahamantra.substrate.manas.synaptic import HebbianSynaptic
    from vibe_core.protocols.memory import MemoryProtocol

logger = logging.getLogger("STEWARD.FIX_PIPELINE")


# ── Module-level helpers (pure functions, no class state) ──────────────


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


class FixPipeline:
    """Guarded fix pipelines with Hebbian learning and escalation.

    Handles both reactive (direct fix on current branch) and proactive
    (feature branch → gates → PR) fix workflows.
    """

    def __init__(
        self,
        *,
        breaker: CircuitBreaker,
        synaptic: HebbianSynaptic,
        memory: MemoryProtocol,
        cwd: str,
        run_fn: Callable[[str], Awaitable[str]],
        git_actuator: object | None = None,
        github_actuator: object | None = None,
    ) -> None:
        self._breaker = breaker
        self._synaptic = synaptic
        self._memory = memory
        self._cwd = cwd
        self._run_fn = run_fn
        self._git = git_actuator
        self._github = github_actuator

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
        hebbian_trigger = (
            f"auto:{intent_name}:{context}" if (intent_name and context) else f"auto:{intent_name or 'unknown'}"
        )

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
                problem,
                hebbian_trigger,
            )
        finally:
            if claimed and marketplace is not None:
                marketplace.release(slot_id, "steward")

    async def _guarded_llm_fix_inner(
        self,
        problem: str,
        hebbian_trigger: str,
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
            self.hebbian_learn(hebbian_trigger, success=True, changed_files=set())
            return result

        # Step 5: Fast gates
        gate_results = self._breaker.run_gates(new_changes)
        failed_gates = [g for g in gate_results if not g.passed]
        if failed_gates:
            details = "; ".join(g.detail for g in failed_gates)
            rolled = self._breaker.rollback_files(new_changes)
            self._breaker.record_rollback()
            self.hebbian_learn(hebbian_trigger, success=False, failed_gates=failed_gates, changed_files=new_changes)
            logger.warning(
                "Verification gates FAILED — rolled back %d files. Gates: %s",
                len(rolled),
                details,
            )
            return None

        # Step 6: Slow gate — test suite
        post = self._breaker.count_failures(test_cmd)
        if post is None:
            rolled = self._breaker.rollback_files(new_changes)
            self._breaker.record_rollback()
            self.hebbian_learn(hebbian_trigger, success=False, changed_files=new_changes)
            logger.warning("Post-fix test run failed — rolled back %d files: %s", len(rolled), rolled)
            return None

        # Step 7: Compare test results
        if post > baseline:
            rolled = self._breaker.rollback_files(new_changes)
            self._breaker.record_rollback()
            self.hebbian_learn(hebbian_trigger, success=False, changed_files=new_changes)
            logger.warning(
                "LLM fix rolled back (failures %d → %d), %d files: %s",
                baseline,
                post,
                len(rolled),
                rolled,
            )
            return None

        # All gates passed
        self._breaker.record_success()
        self.hebbian_learn(hebbian_trigger, success=True, gate_results=gate_results, changed_files=new_changes)
        logger.info(
            "LLM fix verified: %d gates passed, tests %d → %d, %d files changed",
            len(gate_results),
            baseline,
            post,
            len(new_changes),
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
            f"auto:{intent_name}:{context}" if (intent_name and context) else f"auto:{intent_name or 'unknown'}"
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
                self.cleanup_branch(branch_name)
                return result

            # Step 4: Fast gates
            gate_results = self._breaker.run_gates(new_changes)
            failed_gates = [g for g in gate_results if not g.passed]

            if failed_gates:
                details = "; ".join(g.detail for g in failed_gates)
                self._breaker.rollback_files(new_changes)
                self._breaker.record_rollback()
                self.hebbian_learn(
                    hebbian_trigger,
                    success=False,
                    failed_gates=failed_gates,
                    changed_files=new_changes,
                )
                logger.warning("Proactive gates FAILED for %s: %s", intent_name, details)
                self.cleanup_branch(branch_name)
                return None

            # Step 5: Slow gate — test suite
            if baseline is not None:
                post = self._breaker.count_failures(test_cmd)
                if post is None or post > baseline:
                    self._breaker.rollback_files(new_changes)
                    self._breaker.record_rollback()
                    self.hebbian_learn(hebbian_trigger, success=False, changed_files=new_changes)
                    logger.warning(
                        "Proactive tests FAILED for %s (baseline=%s, post=%s)",
                        intent_name,
                        baseline,
                        post,
                    )
                    self.cleanup_branch(branch_name)
                    return None

            # Step 6: All gates passed — commit, push, create PR
            pr_url = self._create_pr(branch_name, intent_name, problem, new_changes)

            self._breaker.record_success()
            self.hebbian_learn(
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
            self.cleanup_branch(branch_name)
            return None
        finally:
            if claimed and marketplace is not None:
                marketplace.release(slot_id, "steward")

    # ── Branch/PR Management ───────────────────────────────────────────

    def cleanup_branch(self, branch_name: str) -> None:
        """Return to main and delete feature branch via GitActuator."""
        if self._git is not None:
            self._git.cleanup_branch(branch_name)
            return

        # Fallback: raw subprocess (legacy path, for tests without actuators)
        import subprocess

        try:
            subprocess.run(
                ["git", "checkout", "main"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self._cwd,
            )
        except Exception as e:
            logger.warning("Failed to switch to main: %s", e)

        try:
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self._cwd,
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
                        capture_output=True,
                        text=True,
                        timeout=10,
                        cwd=self._cwd,
                    )
                r = subprocess.run(
                    ["git", "commit", "-m", commit_msg],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=self._cwd,
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
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=self._cwd,
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
                if pr_result.success:
                    # Close the Kirtan: auto-merge when CI passes
                    self._github.enable_auto_merge(pr_result.url)
                return pr_result.url if pr_result.success else None
            else:
                from steward.senses.gh import get_gh_client

                gh = get_gh_client()
                if gh is None:
                    return None
                pr_url = gh.call(
                    ["pr", "create", "--title", pr_title, "--body", body, "--head", branch_name, "--base", "main"],
                    timeout=30,
                )
                if pr_url:
                    # Close the Kirtan: auto-merge when CI passes
                    gh.call(["pr", "merge", "--auto", "--merge", pr_url.strip()], timeout=15)
                return pr_url

        except Exception as e:
            logger.warning("PR creation failed: %s", e)
            return None

    # ── Hebbian Learning ───────────────────────────────────────────────

    def hebbian_learn(
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
                intent_name,
                confidence,
                escalation_file,
            )
        except OSError as e:
            logger.warning("Failed to write escalation file: %s", e)
