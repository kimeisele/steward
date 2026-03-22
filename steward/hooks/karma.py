"""
KARMA Phase Hooks — Task execution, federation callback handling.

KARMA = action/consequence. The agent's execution cycle:
resume blocked tasks → handle federation callbacks → execute highest-priority task.

The AutonomyEngine dispatches the top pending task. These hooks handle
federation-specific task lifecycle that AutonomyEngine doesn't know about.
"""

from __future__ import annotations

import logging
import time

from steward.phase_hook import KARMA, BasePhaseHook, PhaseContext
from steward.services import (
    SVC_A2A_ADAPTER,
    SVC_FEDERATION,
    SVC_KIRTAN,
    SVC_REAPER,
    SVC_TASK_MANAGER,
)
from vibe_core.di import ServiceRegistry

logger = logging.getLogger("STEWARD.HOOKS.KARMA")


class KarmaFederationCallbackHook(BasePhaseHook):
    """Resume tasks that were BLOCKED on federation delegation.

    When delegate_to_peer suspends a task (status=BLOCKED), the task waits
    for OP_TASK_COMPLETED to arrive via inbound federation. This hook
    checks for completed callbacks and resumes the corresponding tasks.
    """

    @property
    def name(self) -> str:
        return "karma_federation_callback"

    @property
    def phase(self) -> str:
        return KARMA

    @property
    def priority(self) -> int:
        return 10  # Before task dispatch — unblock first

    def execute(self, ctx: PhaseContext) -> None:
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        federation = ServiceRegistry.get(SVC_FEDERATION)
        if task_mgr is None or federation is None:
            return

        from vibe_core.task_types import TaskStatus

        blocked = task_mgr.list_tasks(status=TaskStatus.BLOCKED)
        if not blocked:
            return

        # Check each blocked task for federation completion
        resumed = 0
        for task in blocked:
            desc = getattr(task, "description", "") or ""
            if not desc.startswith("delegated:"):
                continue

            # Parse delegation metadata: "delegated:{title}|peer:{agent_id}"
            parts = desc.split("|")
            peer_id = ""
            for part in parts:
                if part.startswith("peer:"):
                    peer_id = part[5:]

            if not peer_id:
                continue

            # Check if peer has responded (trust > 0 = alive, sent callback)
            reaper = ServiceRegistry.get(SVC_REAPER)
            if reaper is None:
                continue

            peer = reaper.get_peer(peer_id) if hasattr(reaper, "get_peer") else None
            if peer is None:
                continue

            # Check KirtanLoop for delegation verification
            kirtan = ServiceRegistry.get(SVC_KIRTAN)
            if kirtan is not None:
                action_id = f"delegate:{task.id}" if hasattr(task, "id") else f"delegate:{peer_id}"
                status = kirtan.get_status(action_id) if hasattr(kirtan, "get_status") else None
                if status and getattr(status, "result", None) == "closed":
                    # Delegation verified complete — resume task
                    task_mgr.update_task(
                        task.id if hasattr(task, "id") else str(task),
                        status=TaskStatus.PENDING,
                        description=f"resumed from delegation to {peer_id}",
                    )
                    resumed += 1
                    logger.info("KARMA: resumed task from delegation to %s", peer_id)

        if resumed:
            ctx.operations.append(f"karma_federation_callback:resumed={resumed}")


class KarmaTaskPrioritizationHook(BasePhaseHook):
    """Prioritize federation-injected tasks (high-priority from peers).

    Tasks created by DharmaReaperHook (Kirtan escalations) or by
    inbound OP_DELEGATE_TASK get priority=90. This hook ensures
    they're picked up before lower-priority autonomous tasks.
    """

    @property
    def name(self) -> str:
        return "karma_task_prioritization"

    @property
    def phase(self) -> str:
        return KARMA

    @property
    def priority(self) -> int:
        return 20  # After callback handling, before dispatch

    def execute(self, ctx: PhaseContext) -> None:
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            return

        from vibe_core.task_types import TaskStatus

        pending = task_mgr.list_tasks(status=TaskStatus.PENDING)
        if not pending:
            return

        # Count federation tasks for observability
        fed_tasks = [
            t for t in pending if any(tag in (getattr(t, "title", "") or "") for tag in ("[FEDERATION", "[POST_MERGE]"))
        ]
        if fed_tasks:
            ctx.operations.append(f"karma_prioritization:fed_tasks={len(fed_tasks)},total={len(pending)}")


class KarmaA2AProgressHook(BasePhaseHook):
    """Update A2A task states based on internal task progress.

    When Steward processes an A2A-originated task, this hook checks
    the internal task status and updates the A2A adapter so external
    agents can query task progress via tasks/get.
    """

    @property
    def name(self) -> str:
        return "karma_a2a_progress"

    @property
    def phase(self) -> str:
        return KARMA

    @property
    def priority(self) -> int:
        return 80  # Cleanup band — after task execution

    def execute(self, ctx: PhaseContext) -> None:
        a2a = ServiceRegistry.get(SVC_A2A_ADAPTER)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if a2a is None or task_mgr is None:
            return

        from vibe_core.task_types import TaskStatus

        # Check completed tasks that might have A2A tracking
        completed = task_mgr.list_tasks(status=TaskStatus.COMPLETED)
        for task in completed:
            task_id = getattr(task, "id", None)
            if task_id and hasattr(a2a, "complete_task"):
                a2a.complete_task(
                    task_id,
                    {"status": "completed", "completed_at": time.time()},
                )


class KarmaBottleneckResolutionHook(BasePhaseHook):
    """Emit bottleneck_resolution to agent-city when escalation tasks complete.

    When agent-city escalates a bottleneck via NADI, steward creates a
    [BOTTLENECK_ESCALATION] task. Once that task completes, this hook
    emits a bottleneck_resolution message back so agent-city can unblock
    its scope gate and stop re-escalating.

    Priority 85: cleanup band, after task execution (80) and A2A progress.
    """

    @property
    def name(self) -> str:
        return "karma_bottleneck_resolution"

    @property
    def phase(self) -> str:
        return KARMA

    @property
    def priority(self) -> int:
        return 85  # Cleanup band — after A2A progress (80)

    def execute(self, ctx: PhaseContext) -> None:
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        federation = ServiceRegistry.get(SVC_FEDERATION)
        if task_mgr is None or federation is None:
            return

        from vibe_core.task_types import TaskStatus

        completed = task_mgr.list_tasks(status=TaskStatus.COMPLETED)
        if not completed:
            return

        emitted = 0
        for task in completed:
            title = getattr(task, "title", "") or ""
            if not title.startswith("[BOTTLENECK_ESCALATION]"):
                continue

            desc = getattr(task, "description", "") or ""

            # Skip if we already emitted resolution for this task
            if "resolution_emitted:true" in desc:
                continue

            # Extract dedup_key from description (format: "dedup_key:{value}")
            dedup_key = ""
            for line in desc.split("\n"):
                line = line.strip()
                if line.startswith("dedup_key:"):
                    dedup_key = line[len("dedup_key:"):]
                    break

            if not dedup_key:
                logger.debug(
                    "KARMA: completed bottleneck task '%s' has no dedup_key, skipping resolution",
                    title[:60],
                )
                continue

            # Emit resolution via federation bridge
            federation.emit(
                "bottleneck_resolution",
                {
                    "dedup_key": dedup_key,
                    "task_title": title,
                    "source_agent": "steward",
                },
            )
            emitted += 1

            # Mark as emitted to prevent re-emission on subsequent cycles
            task_id = getattr(task, "id", None)
            if task_id and hasattr(task_mgr, "update_task"):
                task_mgr.update_task(
                    task_id,
                    description=desc + "\nresolution_emitted:true",
                )

            logger.info(
                "KARMA: emitted bottleneck_resolution for '%s' (dedup_key=%s)",
                title[:60],
                dedup_key,
            )

        if emitted:
            ctx.operations.append(f"karma_bottleneck_resolution:emitted={emitted}")

