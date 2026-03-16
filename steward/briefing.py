"""
Briefing — cockpit display from living system state.

Pure formatter of context_bridge data. Conventions derived from pyproject.toml.
Static rules loaded from .steward/conventions.md (if present).
Structured for INSTANT agent orientation: critical → rules → state → action → architecture.
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
    """Cockpit layout: identity → critical → rules → state → action → architecture."""
    parts: list[str] = []
    name = ctx.get("project", {}).get("name", "") or Path(cwd).resolve().name

    # ── 1. IDENTITY (one line — what this project IS) ──
    ns = arch.get("north_star", "")
    parts.append(f"# {name}")
    if ns:
        parts.append(f"**{ns}**")

    # ── 2. CRITICAL (what needs attention NOW — only if something is wrong) ──
    critical = _collect_critical(ctx)
    if critical:
        parts.append("\n## CRITICAL")
        for c in critical:
            parts.append(f"- {c}")

    # ── 3. RULES (how to work in this repo — derived + static) ──
    rules = _derive_conventions(cwd) + _load_static_rules(cwd)
    if rules:
        parts.append("\n## Rules")
        for r in rules:
            parts.append(f"- {r}")

    # ── 4. ENVIRONMENT (compact system state from senses) ──
    _append_environment(parts, ctx)

    # ── 5. ACTION (what to do next — issues + gaps) ──
    _append_action(parts, ctx)

    # ── 6. ARCHITECTURE (services with descriptions, phases, tools) ──
    _append_architecture(parts, arch)

    # ── 7. SESSIONS (recent work — compact) ──
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


def _derive_conventions(cwd: str) -> list[str]:
    """Derive development conventions from pyproject.toml — zero hardcoding."""
    rules: list[str] = []
    pyproject = Path(cwd) / "pyproject.toml"
    if not pyproject.is_file():
        return rules

    try:
        # Use tomllib (3.11+) or fallback to basic parsing
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        return rules

    # Linter/formatter
    ruff = data.get("tool", {}).get("ruff", {})
    if ruff:
        line_len = ruff.get("line-length", 88)
        target = ruff.get("target-version", "py311")
        rules.append(f"`ruff check` + `ruff format` before every commit (line-length={line_len}, {target})")

    # Test runner
    pytest_cfg = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    if pytest_cfg:
        testpaths = pytest_cfg.get("testpaths", ["tests"])
        timeout = pytest_cfg.get("timeout")
        asyncio = pytest_cfg.get("asyncio_mode")
        test_desc = f"`pytest {' '.join(testpaths)}`"
        if timeout:
            test_desc += f" (timeout={timeout}s"
            if asyncio:
                test_desc += f", asyncio={asyncio}"
            test_desc += ")"
        rules.append(test_desc)

    # Security scanner
    bandit = data.get("tool", {}).get("bandit", {})
    if bandit:
        rules.append("`bandit -r steward/` for security scanning")

    # Python version
    project = data.get("project", {})
    py_req = project.get("requires-python")
    if py_req:
        rules.append(f"Python {py_req}")

    return rules


def _load_static_rules(cwd: str) -> list[str]:
    """Load steward-specific invariants from .steward/conventions.md.

    These are the 'few effective spots' — critical system invariants
    that every agent must know but can't be derived from config files.
    Each non-empty, non-comment line becomes a rule.
    """
    path = Path(cwd) / ".steward" / "conventions.md"
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        return [line.lstrip("- ").strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    except OSError:
        return []


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
        # Services with their docstrings (compact: name — description)
        for svc_name in sorted(services):
            doc = services[svc_name]
            # Take first line of docstring only
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
        # Phase descriptions (compact)
        for p, desc in phases.items():
            parts.append(f"- {p}: {desc}")

    tools = arch.get("tools", [])
    if tools:
        parts.append("")
        parts.append(f"Tools ({len(tools)}):")
        for t in tools:
            desc = t.get("description", "")
            if desc:
                # First sentence only
                desc = desc.split(".")[0].strip()
            parts.append(f"- `{t['name']}`: {desc}" if desc else f"- `{t['name']}`")
