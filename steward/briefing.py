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
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

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
    """Cockpit layout optimized for AI agent consumption.

    Layout order (highest priority first):
      1. IDENTITY    — who you are, what drives you
      2. CRITICAL    — stop and read these FIRST (only if issues exist)
      3. ORIENTATION — static mental model (conventions.md)
      4. STATUS      — compact health/immune/federation state
      5. ACTION      — what to do next (issues + gaps)
      6. KNOWLEDGE   — validated annotations from prior agents
      7. ENVIRONMENT — senses perception (git, code, tests, health)
      8. TOOLBOX     — available tools with descriptions
      9. ARCHITECTURE — services, phases, substrate (reference)
    """
    parts: list[str] = []
    name = ctx.get("project", {}).get("name", "") or Path(cwd).resolve().name

    # ── 1. IDENTITY ──
    ns = arch.get("north_star", "")
    parts.append(f"# {name}")
    if ns:
        parts.append(f"**{ns}**")

    seed_info = _get_seed_info()
    if seed_info:
        parts.append(seed_info)

    # ── 2. CRITICAL (only if something is actually wrong) ──
    critical = _collect_critical(ctx)
    if critical:
        parts.append("\n## Critical")
        for c in critical:
            parts.append(f"- {c}")
    else:
        parts.append("\n*No critical issues.*")

    # ── 3. ORIENTATION (static — the agent's irreplaceable mental model) ──
    orientation = _load_orientation(cwd)
    if orientation:
        parts.append(f"\n{orientation}")

    # ── 4. STATUS (compact one-liner per subsystem) ──
    _append_status(parts, ctx)

    # ── 5. ACTION (what to do next — issues + gaps) ──
    _append_action(parts, ctx)

    # ── 6. AGENT KNOWLEDGE (validated annotations from pipeline) ──
    knowledge = _collect_annotations()
    if knowledge:
        parts.append("\n## Agent Knowledge")
        parts.append(knowledge)

    # ── 7. ENVIRONMENT (dynamic — what senses perceive right now) ──
    _append_environment(parts, ctx)

    # ── 8. TOOLBOX (what tools are available) ──
    _append_toolbox(parts, arch)

    # ── 9. ARCHITECTURE (reference — services, phases, substrate) ──
    _append_architecture(parts, arch)

    # ── Sessions (compact footer) ──
    sessions = ctx.get("sessions", {})
    stats = sessions.get("stats", {})
    if stats and stats.get("total", 0) > 0:
        parts.append(f"\nSessions: {stats.get('total', 0)} total, success rate {stats.get('success_rate', 0):.0%}")

    return "\n".join(parts)


# ── Section Builders ──────────────────────────────────────────────────


def _get_seed_info() -> str:
    """Get MahaMantra seed + position for identity line."""
    try:
        from vibe_core.mahamantra import mahamantra

        vm = mahamantra("steward")
        seed = vm.get("seed", "")
        position = vm.get("position", "")
        compression = vm.get("compression_ratio", "")
        parts = []
        if seed:
            parts.append(f"Seed `{seed}`")
        if position:
            parts.append(f"position {position}")
        if compression:
            parts.append(f"{compression}x compression")
        return " · ".join(parts) if parts else ""
    except Exception:
        return ""


def _load_orientation(cwd: str) -> str:
    """Load the static orientation block from .steward/conventions.md.

    This is included verbatim — it contains the architectural mental model,
    key directories, invariants, and workflow that an agent needs to orient.
    This knowledge CANNOT be auto-derived from code.
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


def _collect_annotations() -> str:
    """Collect validated annotations from the knowledge pipeline."""
    try:
        from steward.annotations import format_for_briefing

        return format_for_briefing()
    except Exception:
        return ""


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


def _append_environment(parts: list[str], ctx: dict) -> None:
    """Append environment perception from senses + federation peer table."""
    senses = ctx.get("senses", {})
    prompt = senses.get("prompt_summary", "")

    # Senses produce their own "## Environment Perception" header
    if prompt:
        parts.append(f"\n{prompt.strip()}")
    else:
        parts.append("\n## Environment Perception")

    # Federation peer table (detailed view, separate from Status one-liner)
    fed = ctx.get("federation", {})
    peers = fed.get("peers", [])
    if peers:
        parts.append(f"\nFederation peers: {len(peers)}")
        parts.append("| Peer | Status | Trust | Capabilities |")
        parts.append("|------|--------|-------|--------------|")
        for p in peers:
            caps = ", ".join(p.get("capabilities", [])[:3]) or "—"
            parts.append(f"| {p.get('agent_id', '?')} | {p.get('status', '?')} | {p.get('trust', '?')} | {caps} |")


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


def _append_status(parts: list[str], ctx: dict) -> None:
    """Compact status dashboard — one line per subsystem."""
    status_lines: list[str] = []

    health = ctx.get("health", {})
    if health:
        h_val = health.get("value", "?")
        guna = health.get("guna", "?")
        status_lines.append(f"Health: {h_val} ({guna})")

    immune = ctx.get("immune", {})
    if immune:
        breaker = "TRIPPED" if immune.get("breaker", {}).get("tripped") else "OK"
        attempted = immune.get("heals_attempted", 0)
        succeeded = immune.get("heals_succeeded", 0)
        status_lines.append(f"Immune: {succeeded}/{attempted} heals, breaker {breaker}")

    fed = ctx.get("federation", {})
    peers = fed.get("peers", [])
    if peers:
        alive = sum(1 for p in peers if p.get("status") == "alive")
        suspect = sum(1 for p in peers if p.get("status") == "suspect")
        dead = sum(1 for p in peers if p.get("status") in ("dead", "evicted"))
        status_lines.append(f"Federation: {len(peers)} peers ({alive} alive, {suspect} suspect, {dead} dead)")

    if status_lines:
        parts.append("\n## Status")
        for line in status_lines:
            parts.append(line)


def _append_toolbox(parts: list[str], arch: dict) -> None:
    """Append available tools — what the agent can actually DO."""
    tools = arch.get("tools", [])
    if not tools:
        return

    parts.append("\n## Toolbox")
    for t in tools:
        name = t.get("name", "?")
        desc = t.get("description", "")
        if desc:
            # First sentence only for compact display
            first_sentence = desc.split(".")[0].strip()
            parts.append(f"- `{name}` — {first_sentence}")
        else:
            parts.append(f"- `{name}`")


def _append_architecture(parts: list[str], arch: dict) -> None:
    """Append architecture reference — services grouped, phases, substrate."""
    parts.append("\n## Architecture")

    services = arch.get("services", {})
    kshetra = arch.get("kshetra", [])
    if services:
        parts.append(f"{len(services)} services · {len(kshetra)} tattvas")

        # Group services by function for faster scanning
        groups = _group_services(sorted(services.keys()))
        for group_name, svc_list in groups.items():
            parts.append(f"{group_name}: {', '.join(f'`{s}`' for s in svc_list)}")

    phases = arch.get("phases", {})
    hooks = arch.get("hooks", {})
    if phases:
        phase_parts = []
        for p, desc in phases.items():
            hook_info = hooks.get(p, {})
            if isinstance(hook_info, dict):
                count = hook_info.get("count", 0)
            else:
                count = len(hook_info) if isinstance(hook_info, list) else 0
            phase_parts.append(f"**{p}**({count})")
        parts.append(f"MURALI: {' → '.join(phase_parts)}")


def _group_services(svc_names: list[str]) -> dict[str, list[str]]:
    """Group services by functional area for compact display."""
    groups: dict[str, list[str]] = {
        "Cognitive": [],
        "Memory": [],
        "Safety": [],
        "Federation": [],
        "Healing": [],
        "Other": [],
    }

    cognitive = {"SVC_ATTENTION", "SVC_MAHA_LLM", "SVC_COMPRESSION", "SVC_ANTARANGA", "SVC_VENU", "SVC_SIKSASTAKAM"}
    memory = {"SVC_MEMORY", "SVC_SYNAPSE_STORE", "SVC_CACHE", "SVC_KNOWLEDGE_GRAPH", "SVC_TASK_MANAGER"}
    safety = {"SVC_SAFETY_GUARD", "SVC_NARASIMHA", "SVC_INTEGRITY", "SVC_DIAMOND"}
    federation = {
        "SVC_FEDERATION",
        "SVC_FEDERATION_TRANSPORT",
        "SVC_FEDERATION_RELAY",
        "SVC_GIT_NADI_SYNC",
        "SVC_REAPER",
        "SVC_MARKETPLACE",
    }
    healing = {"SVC_IMMUNE", "SVC_FEEDBACK", "SVC_OUROBOROS"}

    for name in svc_names:
        if name in cognitive:
            groups["Cognitive"].append(name)
        elif name in memory:
            groups["Memory"].append(name)
        elif name in safety:
            groups["Safety"].append(name)
        elif name in federation:
            groups["Federation"].append(name)
        elif name in healing:
            groups["Healing"].append(name)
        else:
            groups["Other"].append(name)

    # Remove empty groups
    return {k: v for k, v in groups.items() if v}
