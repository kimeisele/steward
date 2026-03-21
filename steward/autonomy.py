"""
AutonomyEngine — Thin orchestrator for autonomous task execution.

Composes IntentHandlers (detection) + FixPipeline (guarded fixes) into
the autonomous loop: pick task → dispatch intent → fix if needed.

Extracted handlers and pipelines live in:
  - steward.intent_handlers (detection handlers, 0 LLM tokens)
  - steward.fix_pipeline (guarded fix, Hebbian learning, PR pipeline)
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from steward.fix_pipeline import FixPipeline, problem_fingerprint
from steward.intent_handlers import IntentHandlers
from steward.services import (
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


def _resolve_peer_repo(agent_id: str) -> Path | None:
    """Try to resolve a peer agent_id to a local repo path.

    Checks common project locations. Returns None if not found locally.
    For remote peers, use _resolve_peer_git_url() + _cross_repo_workspace().
    """
    home = Path.home()
    candidates = [
        home / "projects" / agent_id,
        home / agent_id,
        Path(agent_id),  # Might already be an absolute path
    ]
    for candidate in candidates:
        if candidate.is_dir() and (candidate / ".git").is_dir():
            return candidate
    return None


def _resolve_peer_git_url(agent_id: str, reaper: object) -> str | None:
    """Derive a cloneable Git URL for a federation peer.

    Uses the PeerRecord's fingerprint (set to 'owner/repo' by GenesisDiscoveryHook)
    to construct the GitHub clone URL.
    """
    peer = reaper.get_peer(agent_id) if hasattr(reaper, "get_peer") else None
    if peer is None:
        return None

    fingerprint = peer.fingerprint  # e.g. "kimeisele/steward-test"
    if "/" in fingerprint:
        return f"https://github.com/{fingerprint}.git"

    return None


class AutonomyEngine:
    """Autonomous task detection, dispatch, and guarded fix pipeline.

    Thin orchestrator that composes:
    - IntentHandlers: deterministic detection (0 LLM tokens)
    - FixPipeline: guarded LLM fixes + Hebbian learning + PR pipeline

    The StewardAgent delegates all autonomous work here.
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
        conversation_reset_fn: Callable[[], None] | None = None,
    ) -> None:
        self._cwd = cwd
        self._synaptic = synaptic
        self._ledger = ledger
        self._conversation_reset_fn = conversation_reset_fn
        self._senses = senses

        # Composed modules — focused, testable, low LCOM4
        self.handlers = IntentHandlers(
            senses=senses,
            vedana_fn=vedana_fn,
            cwd=cwd,
        )
        self.pipeline = FixPipeline(
            breaker=breaker,
            synaptic=synaptic,
            memory=memory,
            cwd=cwd,
            run_fn=run_fn,
            git_actuator=git_actuator,
            github_actuator=github_actuator,
        )

    # ── Public API ─────────────────────────────────────────────────────

    async def run_autonomous(self, idle_minutes: int | None = None) -> str | None:
        """One autonomous cycle: generate tasks + dispatch next.

        For programmatic/legacy use. In daemon mode, GENESIS and KARMA
        phases handle this continuously via Cetana heartbeat.
        """
        self.phase_genesis(idle_override=idle_minutes)
        return await self._dispatch_next_task()

    def run_autonomous_sync(self, idle_minutes: int | None = None) -> str | None:
        """Sync wrapper for run_autonomous."""
        return asyncio.run(self.run_autonomous(idle_minutes=idle_minutes))

    async def _dispatch_next_task(self) -> str | None:
        """Pick the next pending task and execute it deterministically.

        Core dispatch logic — used by both run_autonomous() (one-shot)
        and phase_karma() (daemon). 0 LLM tokens for detection.
        LLM only wakes if a real problem needs fixing.

        Resets conversation before each task to prevent state bloat.
        Hebbian weights persist across tasks (real memory).
        Conversation is ephemeral — each task gets a clean slate.
        """
        # Reset conversation — prevent unbounded growth in daemon mode.
        # Each task is independent. Learning persists via Hebbian weights.
        if self._conversation_reset_fn is not None:
            self._conversation_reset_fn()

        from vibe_core.task_types import TaskStatus

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            return None

        task = task_mgr.get_next_task()
        if task is None:
            return None

        logger.info("Dispatching task '%s' (id=%s)", task.title, task.id)
        task_mgr.update_task(task.id, status=TaskStatus.IN_PROGRESS)

        # Set task context for delegate_to_peer tool (suspension tracking)
        from steward.tools.delegate import set_current_task

        set_current_task(task.id, task.title)

        try:
            intent = parse_intent_from_title(task.title)

            # Special dispatch for specific intents
            if intent is not None:
                from steward.intents import TaskIntent

                if intent == TaskIntent.HEAL_REPO:
                    return await self._execute_heal_repo(task, task_mgr, TaskStatus)

                if intent == TaskIntent.BOTTLENECK_ESCALATION:
                    return await self._execute_bottleneck_escalation(task, task_mgr, TaskStatus)

            # Federated tasks from peers: [FED:source] title → isolated execution + callback
            if intent is None and task.title.startswith("[FED:"):
                return await self._execute_federated_task(task, task_mgr, TaskStatus)

            if intent is None:
                logger.warning("No typed intent in task '%s' — skipping", task.title)
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
                            auto_weight,
                            intent.name,
                            context,
                        )
                        self.pipeline.escalate_problem(problem, intent.name, auto_weight)
                        return None

                    logger.info(
                        "%s:%s found problem (confidence=%.2f), invoking LLM",
                        intent.name,
                        context,
                        auto_weight,
                    )
                    if intent.is_proactive:
                        return await self.pipeline.guarded_pr_fix(problem, intent_name=intent.name)
                    return await self.pipeline.guarded_llm_fix(problem, intent_name=intent.name)

                logger.info("Intent %s completed (no issues found)", intent.name)
                return None
            except Exception as e:
                logger.error("Task '%s' failed: %s", task.title, e)
                task_mgr.update_task(task.id, status=TaskStatus.FAILED)
                return None
        finally:
            set_current_task(None)

    # ── Intent Dispatch (delegates to IntentHandlers) ──────────────────

    def dispatch_intent(self, intent: object) -> str | None:
        """Dispatch a TaskIntent to its deterministic handler."""
        return self.handlers.dispatch(intent)

    # ── Federated Task Execution ──────────────────────────────────────

    async def _execute_federated_task(self, task: object, task_mgr: object, TaskStatus: object) -> str | None:
        """Execute a [FED:source] task with workspace isolation + callback.

        Deterministic workflow:
        1. Parse source agent and repo URL from task
        2. If repo URL: clone to isolated workspace, override pipeline cwd
        3. Run guarded_pr_fix in the workspace (gates verify in workspace)
        4. Emit OP_TASK_COMPLETED or OP_TASK_FAILED callback to federation
        5. Clean up workspace
        """
        from steward.federation import OP_TASK_COMPLETED, OP_TASK_FAILED
        from steward.services import SVC_FEDERATION

        # Parse [FED:source] prefix
        bracket_end = task.title.find("]")
        source_agent = task.title[5:bracket_end] if bracket_end > 5 else "unknown"
        problem = task.title[bracket_end + 2 :] if bracket_end > 0 else task.title

        # Extract repo URL from description
        repo_url = ""
        desc = getattr(task, "description", "") or ""
        if desc.startswith("repo:"):
            repo_url = desc[5:].strip()

        logger.info(
            "Federated task from %s: '%s' (repo=%s)",
            source_agent,
            problem,
            repo_url or "local",
        )

        result = None
        success = False
        pr_url = ""

        try:
            if repo_url:
                # Cross-repo: isolated workspace
                with self._cross_repo_workspace(repo_url, task.id) as workspace:
                    logger.info("Cross-repo workspace: %s → %s", repo_url, workspace)
                    result = await self.pipeline.guarded_pr_fix(
                        problem,
                        intent_name="DELEGATED_TASK",
                    )
            else:
                # Local task delegation (no repo URL)
                result = await self.pipeline.guarded_llm_fix(
                    problem,
                    intent_name="DELEGATED_TASK",
                )

            success = result is not None
            if result and result.startswith("Created PR:"):
                pr_url = result.split("Created PR:", 1)[1].strip()

            task_mgr.update_task(task.id, status=TaskStatus.COMPLETED)

        except Exception as e:
            logger.error("Federated task '%s' failed: %s", task.title, e)
            task_mgr.update_task(task.id, status=TaskStatus.FAILED)
            result = None

        # Emit callback to federation — close the loop
        bridge = ServiceRegistry.get(SVC_FEDERATION)
        if bridge is not None:
            if success:
                bridge.emit(
                    OP_TASK_COMPLETED,
                    {
                        "task_title": problem,
                        "source_agent": source_agent,
                        "pr_url": pr_url,
                    },
                )
            else:
                bridge.emit(
                    OP_TASK_FAILED,
                    {
                        "task_title": problem,
                        "source_agent": source_agent,
                        "error": "Pipeline failed or produced no changes",
                    },
                )

        return result

    async def _execute_bottleneck_escalation(self, task: object, task_mgr: object, TaskStatus: object) -> str | None:
        """Execute BOTTLENECK_ESCALATION: detect + fix + respond via NADI.

        Flow:
        1. Run deterministic detection (IntentHandlers.execute_bottleneck_escalation)
        2. If problem found → run fix pipeline (guarded_llm_fix)
        3. Emit OP_BOTTLENECK_RESOLUTION back to the source peer
        """
        from steward.federation import OP_BOTTLENECK_RESOLUTION
        from steward.services import SVC_FEDERATION

        # Parse source agent from task description
        desc = getattr(task, "description", "") or ""
        parts = {}
        for segment in desc.split("|"):
            if ":" in segment:
                key, _, value = segment.partition(":")
                parts[key] = value

        source_agent = parts.get("source", "unknown")

        # 1. Detect problem (0 tokens)
        problem = self.handlers.execute_bottleneck_escalation()
        self._ledger.record_autonomous("BOTTLENECK_ESCALATION", problem is not None)

        result = None
        resolution_status = "no_issue_found"

        if problem:
            # 2. Confidence gate + fix pipeline
            context = problem_fingerprint(problem)
            granular_key = f"auto:BOTTLENECK_ESCALATION:{context}" if context else "auto:BOTTLENECK_ESCALATION"
            auto_weight = self._synaptic.get_weight(granular_key, "fix")

            if auto_weight < 0.2:
                logger.warning(
                    "Hebbian confidence too low (%.2f) for bottleneck fix — escalating",
                    auto_weight,
                )
                self.pipeline.escalate_problem(problem, "BOTTLENECK_ESCALATION", auto_weight)
                resolution_status = "escalated_to_human"
            else:
                logger.info(
                    "BOTTLENECK_ESCALATION: problem found (confidence=%.2f), invoking fix pipeline",
                    auto_weight,
                )
                try:
                    result = await self.pipeline.guarded_llm_fix(problem, intent_name="BOTTLENECK_ESCALATION")
                    resolution_status = "fixed" if result else "fix_failed"
                except Exception as e:
                    logger.error("Bottleneck fix failed: %s", e)
                    resolution_status = "fix_failed"

        task_mgr.update_task(task.id, status=TaskStatus.COMPLETED)

        # 3. Emit resolution back to source peer via NADI
        bridge = ServiceRegistry.get(SVC_FEDERATION)
        if bridge is not None:
            bridge.emit(
                OP_BOTTLENECK_RESOLUTION,
                {
                    "source_agent": self.pipeline._cwd.split("/")[-1] if "/" in self.pipeline._cwd else "steward",
                    "target_agent": source_agent,
                    "resolution": resolution_status,
                    "pr_url": result if result and result.startswith("Created PR:") else "",
                    "original_task": task.title,
                },
            )
            logger.info(
                "BOTTLENECK_RESOLUTION → %s: %s",
                source_agent,
                resolution_status,
            )

        return result

    async def _execute_heal_repo(self, task: object, task_mgr: object, TaskStatus: object) -> str | None:
        """Execute HEAL_REPO: find degraded peers, heal their repos.

        1. Get degraded peers from reaper
        2. For each peer with a resolvable repo path: heal via RepoHealer
        3. Aggregate results, record Hebbian learning
        """
        from steward.healer import RepoHealer
        from steward.services import SVC_REAPER

        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is None:
            task_mgr.update_task(task.id, status=TaskStatus.COMPLETED)
            return None

        degraded = reaper.suspect_peers() + reaper.dead_peers()
        if not degraded:
            task_mgr.update_task(task.id, status=TaskStatus.COMPLETED)
            return None

        healer = RepoHealer(
            pipeline=self.pipeline,
            run_fn=self.pipeline._run_fn,
            synaptic=self._synaptic,
        )

        results = []
        for peer in degraded[:3]:
            # Try local first, then remote clone
            repo_path = _resolve_peer_repo(peer.agent_id)

            if repo_path is not None:
                # Local path — heal directly
                try:
                    result = await healer.heal_repo(repo_path)
                    results.append(result)
                    logger.info(
                        "Heal %s (local): %d/%d fixed, PR=%s",
                        peer.agent_id,
                        result.findings_fixed,
                        result.findings_fixable,
                        result.pr_url or "(none)",
                    )
                except Exception as e:
                    logger.error("Heal failed for %s: %s", peer.agent_id, e)
            else:
                # Remote peer — clone into sandbox via federation URL
                git_url = _resolve_peer_git_url(peer.agent_id, reaper)
                if git_url is None:
                    logger.debug("Cannot resolve repo for peer %s — skipping", peer.agent_id)
                    continue

                try:
                    with self._cross_repo_workspace(git_url, peer.agent_id) as workspace:
                        result = await healer.heal_repo(workspace)
                        results.append(result)
                        logger.info(
                            "Heal %s (remote): %d/%d fixed, PR=%s",
                            peer.agent_id,
                            result.findings_fixed,
                            result.findings_fixable,
                            result.pr_url or "(none)",
                        )
                except Exception as e:
                    logger.error("Heal failed for %s (remote): %s", peer.agent_id, e)

        task_mgr.update_task(task.id, status=TaskStatus.COMPLETED)
        self._ledger.record_autonomous("HEAL_REPO", bool(results))

        if results:
            summary = "; ".join(
                f"{r.repo}: {r.findings_fixed}/{r.findings_fixable} fixed" + (f" PR: {r.pr_url}" if r.pr_url else "")
                for r in results
            )
            return f"Healed repos: {summary}"
        return None

    @contextmanager
    def _cross_repo_workspace(self, repo_url: str, task_id: str):
        """Clone repo into isolated workspace, override pipeline cwd.

        Context manager that:
        1. Creates /tmp/steward-workspaces/<task_id>/
        2. git clone --depth=1 <repo_url> into it
        3. Temporarily swaps pipeline._cwd and pipeline._breaker.cwd
        4. Restores originals + deletes workspace on exit

        The pipeline, circuit breaker, and all subprocess commands
        operate in the workspace — NOT the agent's own directory.
        """
        # Create parent dir, let git clone create the actual workspace
        parent = Path(tempfile.mkdtemp(prefix="steward-ws-", dir="/tmp"))
        workspace = parent / f"{task_id[:8]}"

        # Save originals BEFORE any mutations
        original_pipeline_cwd = self.pipeline._cwd
        original_breaker_cwd = self.pipeline._breaker.cwd

        try:
            # Clone with shallow depth — minimize disk + network
            r = subprocess.run(
                ["git", "clone", "--depth=1", repo_url, str(workspace)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r.returncode != 0:
                raise RuntimeError(f"git clone failed: {r.stderr.strip()}")

            logger.info("Cloned %s → %s", repo_url, workspace)

            # Swap pipeline cwd to workspace
            self.pipeline._cwd = str(workspace)
            self.pipeline._breaker.cwd = str(workspace)

            yield workspace

        finally:
            # Restore original cwd — always, even on exception
            self.pipeline._cwd = original_pipeline_cwd
            self.pipeline._breaker.cwd = original_breaker_cwd

            # Deterministic cleanup — remove parent dir (contains workspace)
            shutil.rmtree(parent, ignore_errors=True)
            logger.info("Cleaned up workspace: %s", workspace)

    # ── Cetana Phase Handlers ──────────────────────────────────────────

    def phase_genesis(self, idle_override: int | None = None, last_interaction: float | None = None) -> None:
        """GENESIS: Discover — generate typed tasks from Sankalpa intents.

        Evaluates campaign success signals FIRST, then feeds real state
        into Sankalpa. Failing signals boost priority of relevant intents.
        """
        from steward.campaign_signals import evaluate as evaluate_campaign
        from steward.intents import TaskIntent

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

        # Evaluate campaign success signals against real system state
        campaign_health = evaluate_campaign(self._cwd, senses=self._senses)

        active = task_mgr.list_tasks(status=TaskStatus.PENDING) + task_mgr.list_tasks(status=TaskStatus.IN_PROGRESS)
        intents = sankalpa.think(
            idle_minutes=idle_minutes,
            pending_intents=len(active),
            ci_green=campaign_health.ci_green,
        )
        for intent in intents:
            typed = TaskIntent.from_intent_type(intent.intent_type)
            if typed is None:
                logger.debug("GENESIS: unknown intent_type '%s' — skipping", intent.intent_type)
                continue

            if any(t.title.startswith(f"[{typed.name}]") for t in active):
                continue

            _PRIORITY_MAP = {"critical": 90, "high": 70, "medium": 50, "low": 25}
            raw_priority = getattr(intent, "priority", "medium")
            if hasattr(raw_priority, "value"):
                priority = _PRIORITY_MAP.get(raw_priority.value, 50)
            elif isinstance(raw_priority, int):
                priority = raw_priority
            else:
                priority = _PRIORITY_MAP.get(str(raw_priority), 50)

            # Failing campaign signals boost priority of relevant intents
            priority += campaign_health.priority_boost(intent.intent_type)
            priority = min(priority, 99)  # Cap below system-level (POST_MERGE=95)

            task_mgr.add_task(
                title=f"[{typed.name}] {intent.title}",
                priority=priority,
            )

        # Merge detection: if GitSense sees main advanced, inject POST_MERGE
        self._check_merge_and_inject(task_mgr, active)

    def _check_merge_and_inject(self, task_mgr: object, active: list) -> None:
        """Detect merges via GitSense and inject POST_MERGE task + federation event."""
        from steward.federation import OP_MERGE_OCCURRED
        from steward.services import SVC_FEDERATION
        from vibe_core.mahamantra.protocols._sense import Jnanendriya

        git_sense = self._senses.senses.get(Jnanendriya.SROTRA)
        if git_sense is None:
            return
        perception = git_sense.perceive()
        if not isinstance(perception.data, dict):
            return
        if perception.data.get("merge_detected"):
            new_head = perception.data.get("merge_new_head", "unknown")

            # Emit federation event — peers learn about this merge via DHARMA
            bridge = ServiceRegistry.get(SVC_FEDERATION)
            if bridge is not None:
                bridge.emit(OP_MERGE_OCCURRED, {"new_head": new_head})

            # Inject local task (don't duplicate)
            if any(t.title.startswith("[POST_MERGE]") for t in active):
                return
            task_mgr.add_task(
                title=f"[POST_MERGE] Verify merge {new_head[:8]}",
                priority=95,
            )
            logger.info("GENESIS: merge detected (%s) — injected POST_MERGE + federation event", new_head[:8])

    def phase_karma(self) -> None:
        """KARMA: Execute — dispatch next pending task.

        Called by Cetana heartbeat every 4th beat. If no tasks pending,
        returns immediately (0 overhead). If task exists, dispatches it
        via asyncio.run() — blocks heartbeat until done (correct: agent
        is working, not sleeping).
        """
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            return
        from vibe_core.task_types import TaskStatus

        pending = task_mgr.list_tasks(status=TaskStatus.PENDING)
        if not pending:
            return  # No work — idle
        logger.info("KARMA: %d pending task(s), dispatching next", len(pending))
        try:
            asyncio.run(self._dispatch_next_task())
        except Exception as e:
            logger.error("KARMA dispatch failed: %s", e)

    @staticmethod
    def phase_moksha() -> None:
        """MOKSHA: Reflect — persist learning state."""
        synapse_store = ServiceRegistry.get(SVC_SYNAPSE_STORE)
        if synapse_store is not None:
            try:
                synapse_store.save()
            except Exception as e:
                logger.debug("SynapseStore save failed (non-fatal): %s", e)
