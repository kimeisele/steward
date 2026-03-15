"""
Briefing — cockpit display from living system state.

Pure formatter of context_bridge data. Zero hardcoded content.
Structured for INSTANT productivity: seed → critical → context → action → reference.
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
    """Cockpit layout: seed → critical → context → action → reference."""
    parts: list[str] = []
    name = ctx.get("project", {}).get("name", "") or Path(cwd).resolve().name

    # ── 1. IDENTITY (seed — the agent's compressed purpose) ──
    ns = arch.get("north_star", "")
    seed_line = ""
    if ns:
        try:
            from vibe_core.mahamantra.adapters.compression import MahaCompression

            s = MahaCompression().compress(ns)
            seed_line = f"Seed `{s.seed}` · position {s.position} · {s.compression_ratio:.0f}x compression"
        except Exception:
            pass

    parts.append(f"# {name}")
    parts.append(f"**{ns}**" if ns else "")
    if seed_line:
        parts.append(seed_line)

    # ── 2. CRITICAL (what needs attention NOW) ──
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

    if critical:
        parts.append("\n## CRITICAL")
        for c in critical:
            parts.append(f"- {c}")
    else:
        parts.append("\n*No critical issues.*")

    # ── 3. CONTEXT (compact system state) ──
    prompt = senses.get("prompt_summary", "")
    if prompt:
        parts.append(f"\n## Status\n{prompt}")

    if health:
        parts.append(f"Health: {health.get('value', '?')} ({health.get('guna', '?')})")

    if immune:
        parts.append(
            f"Immune: {immune.get('heals_attempted', 0)} attempts, "
            f"{immune.get('heals_succeeded', 0)} succeeded, "
            f"breaker {'TRIPPED' if immune.get('breaker', {}).get('tripped') else 'OK'}"
        )

    peers = fed.get("peers", [])
    if peers:
        parts.append(f"\nFederation: {len(peers)} peers")
        parts.append("| Peer | Status | Trust |")
        parts.append("|------|--------|-------|")
        for p in peers:
            parts.append(f"| {p.get('agent_id', '?')} | {p.get('status', '?')} | {p.get('trust', '?')} |")

    # ── 4. ACTION (what to do next) ──
    issues = ctx.get("issues", [])
    if issues:
        parts.append("\n## Action")
        for i in issues:
            parts.append(f"- #{i.get('number', '?')}: {i.get('title', '?')}")

    gaps = ctx.get("gaps", {})
    active_gaps = gaps.get("active", [])
    if active_gaps:
        parts.append("\nGaps:")
        for g in active_gaps[:5]:
            parts.append(f"- [{g.get('category', '?')}] {g.get('description', '?')}")

    # ── 5. REFERENCE (architecture — collapsed, for deep dives) ──
    parts.append("\n## Architecture")

    services = arch.get("services", {})
    if services:
        active = sum(1 for _ in services)
        parts.append(f"{active} services · {len(arch.get('kshetra', []))} tattvas")

        # Compact service list (one line)
        svc_names = ", ".join(f"`{n}`" for n in sorted(services)[:15])
        if len(services) > 15:
            svc_names += f" +{len(services) - 15} more"
        parts.append(f"Services: {svc_names}")

    phases = arch.get("phases", {})
    hooks = arch.get("hooks", {})
    if phases:
        phase_line = " → ".join(f"**{p}**({len(hooks.get(p, []))})" for p in phases)
        parts.append(f"MURALI: {phase_line}")

    tools = arch.get("tools", [])
    if tools:
        tool_names = ", ".join(f"`{t['name']}`" for t in tools[:10])
        if len(tools) > 10:
            tool_names += f" +{len(tools) - 10} more"
        parts.append(f"Tools: {tool_names}")

    # Sessions (compact)
    sessions = ctx.get("sessions", {})
    stats = sessions.get("stats", {})
    if stats:
        parts.append(f"\nSessions: {stats.get('total', 0)} total, success rate {stats.get('success_rate', 0):.0%}")

    return "\n".join(parts)
