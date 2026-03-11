"""
PhaseHook — Plugin protocol for MURALI phase dispatch.

Each Cetana phase (GENESIS, DHARMA, KARMA, MOKSHA) is a thin dispatcher
that runs registered hooks in priority order. Adding a capability =
adding a hook file, not editing a monolith.

Adapted from agent-city's PhaseHook architecture (city/phase_hook.py).

Priority bands:
  0-10:  Setup & Context Validation
  11-80: Core Logic
  81-100: Cleanup & State Commit
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

logger = logging.getLogger("STEWARD.PHASE_HOOK")


# ── Phase Constants ──────────────────────────────────────────────────

GENESIS = "genesis"
DHARMA = "dharma"
KARMA = "karma"
MOKSHA = "moksha"

ALL_PHASES = frozenset({GENESIS, DHARMA, KARMA, MOKSHA})


# ── PhaseContext ─────────────────────────────────────────────────────


@dataclass
class PhaseContext:
    """Shared state for MURALI phase dispatch in steward.

    Created per-tick by the agent. Hooks read context, write results.
    Services accessed via ServiceRegistry (global DI).
    """

    cwd: str
    vedana: object | None = None
    last_interaction: float = 0.0

    # Mutable output: DHARMA hooks write, agent reads after dispatch
    health_anomaly: bool = False
    health_anomaly_detail: str = ""

    # Operation log (debugging/observability)
    operations: list[str] = field(default_factory=list)


# ── PhaseHook Protocol ───────────────────────────────────────────────


@runtime_checkable
class PhaseHook(Protocol):
    """Protocol for phase hooks across all MURALI phases.

    name:     unique identifier (logging + dedup)
    phase:    which phase this hook belongs to
    priority: execution order (0=first, 100=last)
    should_run(ctx): gate — return False to skip this tick
    execute(ctx): perform operations, mutate ctx as needed
    """

    @property
    def name(self) -> str: ...

    @property
    def phase(self) -> str: ...

    @property
    def priority(self) -> int: ...

    def should_run(self, ctx: PhaseContext) -> bool: ...

    def execute(self, ctx: PhaseContext) -> None: ...


class BasePhaseHook(ABC):
    """Base class for phase hooks with sensible defaults."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def phase(self) -> str: ...

    @property
    def priority(self) -> int:
        return 50

    def should_run(self, ctx: PhaseContext) -> bool:
        return True

    @abstractmethod
    def execute(self, ctx: PhaseContext) -> None: ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} phase={self.phase} pri={self.priority}>"


# ── PhaseHookRegistry ────────────────────────────────────────────────


class PhaseHookRegistry:
    """Registry for hooks across all phases.

    Hooks register at boot. The dispatcher for each phase calls
    registry.dispatch(phase, ctx) which runs only the hooks
    for that phase, in priority order.

    This replaces monolithic phase methods with composable,
    testable, independently deployable hook files.
    """

    __slots__ = ("_hooks",)

    def __init__(self) -> None:
        self._hooks: dict[str, list[PhaseHook]] = {
            p: [] for p in ALL_PHASES
        }

    def register(self, hook: PhaseHook) -> None:
        """Register a hook. Deduplicates by name within phase."""
        phase = hook.phase
        if phase not in self._hooks:
            logger.warning("PhaseHookRegistry: unknown phase %r, creating", phase)
            self._hooks[phase] = []

        hooks = self._hooks[phase]
        for existing in hooks:
            if existing.name == hook.name:
                logger.debug("Hook %s already registered in %s, skipping", hook.name, phase)
                return

        hooks.append(hook)
        hooks.sort(key=lambda h: h.priority)
        logger.debug(
            "Registered hook: %s (phase=%s, priority=%d)",
            hook.name, phase, hook.priority,
        )

    def unregister(self, phase: str, name: str) -> bool:
        """Remove a hook by phase and name."""
        if phase not in self._hooks:
            return False
        before = len(self._hooks[phase])
        self._hooks[phase] = [h for h in self._hooks[phase] if h.name != name]
        return len(self._hooks[phase]) < before

    def dispatch(self, phase: str, ctx: PhaseContext) -> None:
        """Execute all hooks for a phase in priority order, respecting gates."""
        hooks = self._hooks.get(phase, [])
        for hook in hooks:
            try:
                if not hook.should_run(ctx):
                    logger.debug("Hook %s skipped (gate)", hook.name)
                    continue
                hook.execute(ctx)
                ctx.operations.append(f"{hook.name}:ok")
            except Exception as e:
                logger.warning("Hook %s failed: %s", hook.name, e)
                ctx.operations.append(f"{hook.name}:error:{e}")

    def get_hooks(self, phase: str) -> list[PhaseHook]:
        """Get all hooks for a phase (sorted by priority)."""
        return list(self._hooks.get(phase, []))

    def hook_count(self, phase: str | None = None) -> int:
        """Count hooks, optionally filtered by phase."""
        if phase is not None:
            return len(self._hooks.get(phase, []))
        return sum(len(hooks) for hooks in self._hooks.values())

    def stats(self) -> dict:
        """Registry statistics."""
        return {
            phase: {
                "count": len(hooks),
                "names": [h.name for h in hooks],
            }
            for phase, hooks in self._hooks.items()
        }
