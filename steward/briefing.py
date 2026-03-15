"""
Briefing — format context_bridge data as markdown for CLAUDE.md.

This is a PURE FORMATTER. All data comes from:
- context_bridge.assemble_context() (senses, health, federation, immune, issues)
- context_bridge.collect_architecture_metadata() (services, hooks, kshetra)

Zero hardcoded content. If the system changes, the briefing changes.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("STEWARD.BRIEFING")


def generate_briefing(cwd: str | None = None) -> str:
    """Generate CLAUDE.md content from living system state.

    Pure formatter — delegates ALL data collection to context_bridge.
    """
    cwd = cwd or str(Path.cwd())

    from steward.context_bridge import assemble_context, collect_architecture_metadata

    ctx = assemble_context(cwd)

    # Cold-start fallback: if services aren't booted, read last heartbeat's context.json
    if not ctx.get("federation", {}).get("peers") and not ctx.get("immune"):
        context_json = Path(cwd) / ".steward" / "context.json"
        if context_json.exists():
            try:
                import json

                cached = json.loads(context_json.read_text())
                # Merge cached data for sections that are empty
                for key in ("federation", "immune", "health", "cetana"):
                    if not ctx.get(key) and cached.get(key):
                        ctx[key] = cached[key]
            except (json.JSONDecodeError, OSError):
                pass

    arch = collect_architecture_metadata()

    return _format(ctx, arch, cwd)


def _format(ctx: dict, arch: dict, cwd: str = ".") -> str:
    """Format context + architecture as cockpit markdown."""
    parts: list[str] = []

    # Header
    project = ctx.get("project", {})
    name = project.get("name", "") or Path(cwd).resolve().name
    parts.append(f"# Steward — {name}")

    # Senses
    senses = ctx.get("senses", {})
    prompt = senses.get("prompt_summary", "")
    if prompt:
        parts.append(f"\n## Status\n{prompt}")

    # Health
    health = ctx.get("health", {})
    if health:
        parts.append(f"\nHealth: {health.get('value', '?')} ({health.get('guna', '?')})")

    # Federation
    fed = ctx.get("federation", {})
    peers = fed.get("peers", [])
    if peers:
        parts.append("\n## Federation")
        parts.append("| Peer | Status | Trust |")
        parts.append("|------|--------|-------|")
        for p in peers:
            parts.append(f"| {p.get('agent_id', '?')} | {p.get('status', '?')} | {p.get('trust', '?')} |")
    else:
        total = fed.get("total_peers", 0)
        reaps = fed.get("total_reaps", 0)
        parts.append(f"\n## Federation\nPeers: {total}, Reaps: {reaps}")

    # Immune
    immune = ctx.get("immune", {})
    if immune:
        parts.append(
            f"\nImmune: {immune.get('heals_attempted', 0)} attempts, "
            f"{immune.get('heals_succeeded', 0)} succeeded, "
            f"breaker={'TRIPPED' if immune.get('breaker', {}).get('tripped') else 'OK'}"
        )

    # Issues
    issues = ctx.get("issues", [])
    if issues:
        parts.append("\n## Open Issues")
        for i in issues:
            parts.append(f"- #{i.get('number', '?')}: {i.get('title', '?')}")

    # Sessions
    sessions = ctx.get("sessions", {})
    recent = sessions.get("recent", [])
    if recent:
        parts.append("\n## Recent Sessions")
        for s in recent[-3:]:
            parts.append(f"- [{s.get('outcome', '?')}] {s.get('task', '?')[:80]}")

    # Architecture (from living code)
    parts.append("\n## Architecture")

    ns = arch.get("north_star")
    if ns:
        # Compute seed for alignment — every decision should be checked against this
        try:
            from vibe_core.mahamantra.adapters.compression import MahaCompression

            seed_result = MahaCompression().compress(ns)
            parts.append(
                f"North Star: {ns}\n"
                f"Seed: `{seed_result.seed}` (position {seed_result.position}) — "
                f"align every task against this seed via XOR Hamming distance"
            )
        except Exception:
            parts.append(f"North Star: {ns}")

    services = arch.get("services", {})
    if services:
        parts.append(f"\n### Services ({len(services)})")
        parts.append("| Service | Description |")
        parts.append("|---------|-------------|")
        for svc_name, doc in sorted(services.items()):
            clean_doc = " ".join(doc.split())[:80]  # collapse newlines
            parts.append(f"| `{svc_name}` | {clean_doc} |")

    phases = arch.get("phases", {})
    hooks = arch.get("hooks", {})
    if phases:
        parts.append("\n### MURALI Phases")
        for phase, desc in phases.items():
            hook_list = hooks.get(phase, [])
            hook_names = ", ".join(h["name"] for h in hook_list) if hook_list else "—"
            parts.append(f"- **{phase}**: {desc} → [{hook_names}]")

    tools = arch.get("tools", [])
    if tools:
        parts.append(f"\n### Tools ({len(tools)})")
        for t in tools:
            parts.append(f"- `{t['name']}`: {t.get('description', '')[:60]}")

    kshetra = arch.get("kshetra", [])
    if kshetra:
        parts.append(f"\n### Kshetra ({len(kshetra)} tattvas)")
        parts.append("| # | Element | Category | Role |")
        parts.append("|---|---------|----------|------|")
        for k in kshetra:
            parts.append(f"| {k['number']} | {k['element']} | {k['category']} | {k['role']} |")

    # Gaps
    gaps = ctx.get("gaps", {})
    active_gaps = gaps.get("active", [])
    if active_gaps:
        parts.append("\n## Gaps")
        for g in active_gaps[:5]:
            parts.append(f"- [{g.get('category', '?')}] {g.get('description', '?')}")

    return "\n".join(parts)
