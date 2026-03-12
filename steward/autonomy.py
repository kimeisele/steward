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
import time
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
    ) -> None:
        self._synaptic = synaptic
        self._ledger = ledger

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
        """
        from vibe_core.task_types import TaskStatus

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            return None

        task = task_mgr.get_next_task()
        if task is None:
            return None

        logger.info("Dispatching task '%s' (id=%s)", task.title, task.id)
        task_mgr.update_task(task.id, status=TaskStatus.IN_PROGRESS)

        intent = parse_intent_from_title(task.title)

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
                        auto_weight, intent.name, context,
                    )
                    self.pipeline.escalate_problem(problem, intent.name, auto_weight)
                    return None

                logger.info(
                    "%s:%s found problem (confidence=%.2f), invoking LLM",
                    intent.name, context, auto_weight,
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

    # ── Intent Dispatch (delegates to IntentHandlers) ──────────────────

    def dispatch_intent(self, intent: object) -> str | None:
        """Dispatch a TaskIntent to its deterministic handler."""
        return self.handlers.dispatch(intent)

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
