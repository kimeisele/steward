"""
Briefing — cockpit display from living system state.

SINGLE WRITER for CLAUDE.md. All paths funnel through write_claude_md():
  - MOKSHA heartbeat (via moksha_bridge hook, rate-limited by the hook itself)
  - On-demand (synthesize_briefing tool, agent request)
  - External trigger (PR, push, federation sync)

Three layers compose the CLAUDE.md:
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

import hashlib
import logging
from pathlib import Path

from steward.briefing_stages import (
    _collect_critical as _collect_critical,  # re-export for backward compat
)
from steward.briefing_stages import (
    _load_orientation as _load_orientation,  # re-export for backward compat
)
from steward.briefing_stages import (
    default_pipeline,
)

logger = logging.getLogger("STEWARD.BRIEFING")

# ── Write Dedup ──────────────────────────────────────────────────────
# Hash-based dedup prevents writing identical content.
# Rate limiting is the caller's responsibility (MOKSHA hook has its own).
_last_hash: str = ""


def write_claude_md(cwd: str | None = None, force: bool = False) -> bool:
    """Single writer for CLAUDE.md. All triggers call this.

    Rate limiting is NOT done here — it's the caller's job (e.g., MOKSHA
    hook rate-limits at 5s). This function only deduplicates by content hash.

    Returns True if file was written, False if content unchanged.
    """
    global _last_hash

    cwd = cwd or str(Path.cwd())
    briefing = generate_briefing(cwd)

    # Hash dedup — skip write if content unchanged
    content_hash = hashlib.sha256(briefing.encode()).hexdigest()[:16]
    if content_hash == _last_hash and not force:
        return False

    claude_md = Path(cwd) / "CLAUDE.md"
    claude_md.write_text(briefing, encoding="utf-8")
    _last_hash = content_hash
    return True


def generate_briefing(cwd: str | None = None) -> str:
    """Generate cockpit briefing from living system state."""
    cwd = cwd or str(Path.cwd())

    from steward.context_bridge import assemble_context, collect_architecture_metadata

    ctx = assemble_context(cwd)

    # Cold-start: merge cached context.json from last heartbeat
    if not ctx.get("federation", {}).get("peers") and not ctx.get("immune"):
        _merge_cached_context(ctx, cwd)

    arch = collect_architecture_metadata()

    pipeline = default_pipeline()
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
