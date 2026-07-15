"""
Briefing — read-only preview from living system state.

Three layers compose the legacy briefing preview:
  1. Static orientation from .steward/conventions.md (irreplaceable knowledge:
     cognitive pipeline, philosophy, invariants, workflow)
  2. Validated agent annotations (from steward.annotations pipeline)
  3. Dynamic state from context_bridge (health, issues, senses, federation)

The static block gives the agent a mental model of the system.
The annotations give it learned knowledge from previous agents.
The dynamic block tells it what's happening RIGHT NOW.

Generation is composable: each section is a BriefingStage in briefing_stages.py,
registered in a BriefingPipeline, dispatched by priority order.
Same pattern as PhaseHookRegistry.
"""

from __future__ import annotations

from pathlib import Path

from steward.briefing_stages import (
    BUDGET_COMPACT as BUDGET_COMPACT,  # re-export
)
from steward.briefing_stages import (
    BUDGET_FULL as BUDGET_FULL,  # re-export
)
from steward.briefing_stages import (
    BUDGET_STANDARD as BUDGET_STANDARD,  # re-export
)
from steward.briefing_stages import (
    BUDGET_UNLIMITED as BUDGET_UNLIMITED,  # re-export
)
from steward.briefing_stages import (
    _collect_critical as _collect_critical,  # re-export for backward compat
)
from steward.briefing_stages import (
    _load_orientation as _load_orientation,  # re-export for backward compat
)
from steward.briefing_stages import (
    default_pipeline,
)


class LegacyBriefingWriteDisabled(RuntimeError):
    """Raised when a caller attempts to use the retired root writer."""


def write_claude_md(cwd: str | None = None, force: bool = False) -> bool:
    """Reject legacy root writes until the canonical publisher exists."""
    del cwd, force
    raise LegacyBriefingWriteDisabled("Legacy CLAUDE.md writes are disabled; use generate_briefing() for preview only")


def generate_briefing(cwd: str | None = None, token_budget: int = BUDGET_STANDARD) -> str:
    """Generate cockpit briefing from living system state.

    Args:
        cwd: Working directory (defaults to current).
        token_budget: Token budget slider. Controls output length.
            BUDGET_COMPACT (800): identity + critical + action only
            BUDGET_STANDARD (1500): most sections, architecture compressed
            BUDGET_FULL (3000): everything expanded
            BUDGET_UNLIMITED (0): no truncation
    """
    cwd = cwd or str(Path.cwd())

    from steward.context_bridge import assemble_context, collect_architecture_metadata

    ctx = assemble_context(cwd)

    # Cold-start: merge cached context.json from last heartbeat
    if not ctx.get("federation", {}).get("peers") and not ctx.get("immune"):
        _merge_cached_context(ctx, cwd)

    arch = collect_architecture_metadata()

    pipeline = default_pipeline(token_budget=token_budget)
    return pipeline.generate(ctx, arch, cwd)


def _merge_cached_context(ctx: dict, cwd: str) -> None:
    """Fill empty sections from last heartbeat's context.json."""
    import json

    path = Path(cwd) / ".steward" / "context.json"
    if not path.exists():
        return
    try:
        cached = json.loads(path.read_text())
        for key in ("federation", "immune", "health", "cetana"):
            if not ctx.get(key) and cached.get(key):
                ctx[key] = cached[key]
    except (json.JSONDecodeError, OSError):
        pass
