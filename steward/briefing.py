"""
Briefing — cockpit display from living system state.

Two layers compose the CLAUDE.md:
  1. Static orientation from .steward/conventions.md (architecture, invariants, workflow)
  2. Dynamic state from context_bridge (health, issues, senses, federation)

The static block gives the agent a mental model of the system.
The dynamic block tells it what's happening RIGHT NOW.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("STEWARD.BRIEFING")


def generate_briefing(cwd: str | None = None) -> str:
    """Generate cockpit briefing from living system state."""
    cwd = cwd or str(Path.cwd())

    from steward.context_bridge import assemble_context, collect_architecture_metadata

    ctx = assemble_context(cwd)

    # Cold-start: merge cached context.json from last heartbeat
    if not ctx.get("federation", {}).get("peers") and not ctx.get("immune"):
        _merge_cached_context(ctx, cwd)

    arch = collect_architecture_metadata()
    return _format(ctx, arch, cwd)


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


def _format(ctx: dict, arch: dict, cwd: str = ".") -> str:
    """Cockpit layout: identity → orientation → critical → state → action → architecture."""
    parts: list[str] = []
    name = ctx.get("project", {}).get("name", "") or Path(cwd).resolve().name

    # ── 1. IDENTITY ──
    ns = arch.get("north_star", "")
    parts.append(f"# {name}")
    if ns:
        parts.append(f"**{ns}**")

    # ── 2. ORIENTATION (static block — the agent's mental model) ──
    orientation = _load_orientation(cwd)
    if orientation:
        parts.append(f"\n{orientation}")

    # ── 3. CRITICAL (only if something is actually wrong) ──
    critical = _collect_critical(ctx)
    if critical:
        parts.append("\n## CRITICAL")
        for c in critical:
            parts.append(f"- {c}")

    # ── 4. ENVIRONMENT (dynamic — what senses perceive right now) ──
    _append_environment(parts, ctx)

    # ── 5. ACTION (issues + gaps) ──
    _append_action(parts, ctx)

    # ── 6. ARCHITECTURE (dynamic — services, phases, tools from living code) ──
    _append_architecture(parts, arch)

    # ── 7. SESSIONS (compact) ──
    sessions = ctx.get("sessions", {})
    stats = sessions.get("stats", {})
    if stats and stats.get("total", 0) > 0:
        parts.append(f"\nSessions: {stats.get('total', 0)} total, success rate {stats.get('success_rate', 0):.0%}")

    return "\n".join(parts)


# ── Section Builders ──────────────────────────────────────────────────


def _collect_critical(ctx: dict) -> list[str]:
    """Collect critical alerts from system state."""
    critical: list[str] = []

    health = ctx.get("health", {})
    h_val = health.get("value", 1.0)
    if isinstance(h_val, (int, float)) and h_val < 0.5:
        critical.append(f"Health CRITICAL: {h_val} ({health.get('guna', '?')})")

    immune = ctx.get("immune", {})
    if immune.get("breaker", {}).get("tripped"):
        critical.append("Immune breaker TRIPPED — healing suspended")
    if immune.get("heals_rolled_back", 0) > 0:
        critical.append(f"{immune['heals_rolled_back']} heals rolled back")

    fed = ctx.get("federation", {})
    dead = fed.get("dead", 0) if isinstance(fed.get("dead"), int) else len(fed.get("dead_ids", []))
    if dead:
        critical.append(f"{dead} DEAD peers in federation")

    senses = ctx.get("senses", {})
    pain = senses.get("total_pain", 0)
    if isinstance(pain, (int, float)) and pain > 0.7:
        critical.append(f"High pain: {pain:.2f}")

    return critical


def _load_orientation(cwd: str) -> str:
    """Load the static orientation block from .steward/conventions.md.

    This is included verbatim — it contains the architectural mental model,
    key directories, invariants, and workflow that an agent needs to orient.
    """
    path = Path(cwd) / ".steward" / "conventions.md"
    if not path.is_file():
        return ""
    try:
        content = path.read_text(encoding="utf-8").strip()
        # Strip leading comment lines (file-level comments, not content)
        lines = content.splitlines()
        # Skip lines that are file-level comments (before first non-comment content)
        start = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                # Found first content line, but check if previous line was a heading
                # (headings start with # followed by space)
                start = i
                # Include the heading above if it exists
                if i > 0 and lines[i - 1].strip().startswith("# "):
                    start = i - 1
                break
            if stripped.startswith("## "):
                # This is a section heading, include from here
                start = i
                break
        return "\n".join(lines[start:]).strip()
    except OSError:
        return ""


def _append_environment(parts: list[str], ctx: dict) -> None:
    """Append environment perception — senses, health, immune, federation."""
    senses = ctx.get("senses", {})
    prompt = senses.get("prompt_summary", "")

    # Senses produce their own "## Environment Perception" header
    if prompt:
        parts.append(f"\n{prompt.strip()}")
    else:
        parts.append("\n## Environment")

    health = ctx.get("health", {})
    if health:
        parts.append(f"Health: {health.get('value', '?')} ({health.get('guna', '?')})")

    immune = ctx.get("immune", {})
    if immune:
        parts.append(
            f"Immune: {immune.get('heals_attempted', 0)} attempts, "
            f"{immune.get('heals_succeeded', 0)} succeeded, "
            f"breaker {'TRIPPED' if immune.get('breaker', {}).get('tripped') else 'OK'}"
        )

    fed = ctx.get("federation", {})
    peers = fed.get("peers", [])
    if peers:
        parts.append(f"\nFederation: {len(peers)} peers")
        parts.append("| Peer | Status | Trust |")
        parts.append("|------|--------|-------|")
        for p in peers:
            parts.append(f"| {p.get('agent_id', '?')} | {p.get('status', '?')} | {p.get('trust', '?')} |")


def _append_action(parts: list[str], ctx: dict) -> None:
    """Append action items — issues and gaps."""
    issues = ctx.get("issues", [])
    gaps = ctx.get("gaps", {})
    active_gaps = gaps.get("active", [])

    if not issues and not active_gaps:
        return

    parts.append("\n## Action")

    if issues:
        for i in issues:
            num = i.get("number", "?")
            title = i.get("title", "?")
            labels = i.get("labels", [])
            label_str = ""
            if labels:
                label_str = " " + " ".join(f"[{lb}]" for lb in labels[:3])
            parts.append(f"- #{num}: {title}{label_str}")

    if active_gaps:
        parts.append("")
        parts.append("Gaps:")
        for g in active_gaps[:5]:
            parts.append(f"- [{g.get('category', '?')}] {g.get('description', '?')}")


def _append_architecture(parts: list[str], arch: dict) -> None:
    """Append architecture — services with docstrings, phases, tools."""
    parts.append("\n## Architecture")

    services = arch.get("services", {})
    if services:
        parts.append(f"{len(services)} services · {len(arch.get('kshetra', []))} tattvas")
        parts.append("")
        for svc_name in sorted(services):
            doc = services[svc_name]
            first_line = doc.split("\n")[0].strip().rstrip(".")
            parts.append(f"- `{svc_name}`: {first_line}")

    phases = arch.get("phases", {})
    hooks = arch.get("hooks", {})
    if phases:
        parts.append("")
        phase_parts = []
        for p, desc in phases.items():
            hook_info = hooks.get(p, {})
            if isinstance(hook_info, dict):
                count = hook_info.get("count", 0)
            else:
                count = len(hook_info) if isinstance(hook_info, list) else 0
            phase_parts.append(f"**{p}**({count}h)")
        parts.append(f"MURALI: {' → '.join(phase_parts)}")
        for p, desc in phases.items():
            parts.append(f"- {p}: {desc}")

    tools = arch.get("tools", [])
    if tools:
        parts.append("")
        parts.append(f"Tools ({len(tools)}):")
        for t in tools:
            desc = t.get("description", "")
            if desc:
                desc = desc.split(".")[0].strip()
            parts.append(f"- `{t['name']}`: {desc}" if desc else f"- `{t['name']}`")
