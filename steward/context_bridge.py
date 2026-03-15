"""
Context Bridge — Steward's voice to external consumers (Claude Code, Opus).

This is NOT a data dump. Steward speaks through this bridge to brief an
incoming Opus session with full situational awareness: how the system feels,
what it sees, where it hurts, what it tried, what it needs.

Three layers:
  1. Architecture DNA — What this system IS (MURALI, Vedana, Buddhi, Sanskrit naming)
  2. Living State    — How the system FEELS right now (health, senses, patterns)
  3. Call to Action   — What needs attention (gaps, pain, failed sessions)

Usage:
    from steward.context_bridge import assemble_context, render_markdown, write_context_files

    context = assemble_context("/path/to/project")
    md = render_markdown(context)
    write_context_files("/path/to/project", context)

Or via the MokshaContextBridgeHook (automatic every heartbeat).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("STEWARD.CONTEXT_BRIDGE")

# Schema version — bump when context shape changes materially
_CONTEXT_VERSION = 1

# ── Architecture DNA ─────────────────────────────────────────────────
# This is the static layer — what steward IS. Updated rarely.
# Written as a constant because it describes the system's design,
# not its runtime state. Opus needs this to understand the codebase.

_ARCHITECTURE_DNA = """\
## Architecture: Steward Superagent

Steward is a **living autonomous agent** — not a script, not a framework.
It perceives its environment, feels health as pleasure/pain, makes decisions,
heals itself, and coordinates with peer agents via federation.

### Core Cycle: MURALI (Heartbeat)

Every heartbeat tick rotates through 4 phases:

- **GENESIS** — Discovery. Scan for federation peers, boot senses.
- **DHARMA** — Governance. Check health, reap dead peers, purge expired claims, broadcast heartbeat.
- **KARMA** — Execution. Process user task through tool loop (Buddhi directs tool selection).
- **MOKSHA** — Persistence. Save state to disk, flush federation messages, write context bridge.

Heartbeat frequency adapts to health:
- Sattva (health > 0.8): 0.1 Hz — calm, 10s between beats.
- Sadhana (0.5-0.8): 0.5 Hz — normal, 2s between beats.
- Gajendra (< 0.5): 2.0 Hz — emergency, 0.5s between beats.

### Perception: 5 Jnanendriyas (Senses)

| Sense | Sanskrit | Perceives |
|-------|----------|-----------|
| Git | Srotra (ear) | Branch, dirty files, upstream, CI status, open PRs |
| Project | Tvak (skin) | Languages, frameworks, key dirs, config files |
| Code | Caksu (eye) | Packages, classes, functions, LCOM4 cohesion, syntax errors |
| Tests | Jihva (tongue) | Framework, test count, coverage, last result |
| Health | Ghrana (nose) | Large files, stale files, lockfile, gitignore, readme |

### Vedana: Health as Feeling

Vedana computes a composite health signal (0.0-1.0):
- 35% provider health (are LLM providers alive?)
- 25% error pressure (recent error rate)
- 15% context pressure (context window usage)
- 15% synaptic confidence (Hebbian learning strength)
- 10% tool success rate

Guna classification: **sattva** (> 0.7, harmony), **rajas** (0.3-0.7, friction), **tamas** (< 0.3, inertia).

### Buddhi: Decision Engine

Classifies intent → selects tools → sets token budget → routes to model tier.
Hebbian learning strengthens successful action→tool mappings across sessions.
Gandha detects anti-patterns (loops, cascading errors, blind writes) and redirects.

### Immune System

Self-healing pipeline: diagnose → heal (AST surgery) → verify (run tests) → learn.
CytokineBreaker prevents autoimmune cascades: 3 consecutive rollbacks → 5min cooldown.

### Federation

Peer discovery via agent-world registry + GitHub topics. HeartbeatReaper tracks
liveness with trust decay. Marketplace resolves slot conflicts. Git-nadi transport
for cross-agent messaging.

### Key Conventions

- **Sanskrit naming is load-bearing**, not decorative. Vedana IS health-as-feeling.
  Buddhi IS discriminative intelligence. Don't rename to "health_checker" or "decision_engine".
- **ServiceRegistry (DI)** — All services accessed via `ServiceRegistry.get(SVC_*)`.
- **SVC_ constants** in `steward/services.py` are the canonical service keys.
- **PhaseHooks** in `steward/hooks/` — add capabilities by adding hooks, not editing agent.py.
- **Tests** — pytest, `tests/` directory. Run `pytest` from project root.
- **North Star**: "execute tasks with minimal tokens by making the architecture itself intelligent"
"""


def assemble_context(cwd: str | None = None) -> dict[str, Any]:
    """Assemble steward's full context from all available sources.

    Pulls from ServiceRegistry if services are booted (daemon mode).
    Falls back to disk-based loading for cold-start (CLI mode).

    Returns a structured dict — the canonical context representation.
    """
    cwd = cwd or str(Path.cwd())
    ctx: dict[str, Any] = {
        "version": _CONTEXT_VERSION,
        "timestamp": time.time(),
        "project": {
            "name": Path(cwd).name,
            "path": cwd,
        },
    }

    # ── Senses (environmental perception) ────────────────────────────
    ctx["senses"] = _read_senses(cwd)

    # ── Vedana (health/feeling) ──────────────────────────────────────
    ctx["health"] = _read_health()

    # ── Gaps (what steward couldn't do) ──────────────────────────────
    ctx["gaps"] = _read_gaps(cwd)

    # ── Sessions (what steward did recently) ─────────────────────────
    ctx["sessions"] = _read_sessions(cwd)

    # ── Tasks (pending work) ─────────────────────────────────────────
    ctx["tasks"] = _read_tasks(cwd)

    # ── Federation (peer network) ────────────────────────────────────
    ctx["federation"] = _read_federation()

    # ── Immune (self-healing state) ──────────────────────────────────
    ctx["immune"] = _read_immune()

    # ── Cetana (heartbeat state) ─────────────────────────────────────
    ctx["cetana"] = _read_cetana()

    return ctx


def render_markdown(context: dict[str, Any]) -> str:
    """Render assembled context as structured markdown for LLM consumption.

    This is steward's VOICE — not a data dump. It prioritizes based on
    health and pain, leads with what matters, omits what doesn't.
    """
    parts: list[str] = []

    # ── Architecture DNA (always present — Opus needs to understand the system)
    parts.append(_ARCHITECTURE_DNA)

    # ── Health headline (lead with how the system feels)
    health = context.get("health", {})
    parts.append(_render_health_headline(health))

    # ── Urgent items first (pain-driven priority)
    gaps = context.get("gaps", {})
    sessions = context.get("sessions", {})
    immune = context.get("immune", {})

    urgencies = _collect_urgencies(health, gaps, sessions, immune)
    if urgencies:
        parts.append("## Needs Attention\n")
        for u in urgencies:
            parts.append(f"- {u}")
        parts.append("")

    # ── Environmental perception (what steward sees)
    senses = context.get("senses", {})
    if senses:
        parts.append(_render_senses(senses))

    # ── Capability gaps (what steward couldn't do)
    if gaps.get("active"):
        parts.append(_render_gaps(gaps))

    # ── Recent sessions (what steward did)
    if sessions.get("recent"):
        parts.append(_render_sessions(sessions))

    # ── Tasks (pending work)
    tasks = context.get("tasks", {})
    if tasks.get("pending"):
        parts.append(_render_tasks(tasks))

    # ── Federation (peer network — only if peers exist)
    federation = context.get("federation", {})
    if federation.get("total_peers", 0) > 0:
        parts.append(_render_federation(federation))

    # ── Immune system (only if noteworthy)
    if immune.get("heals_attempted", 0) > 0 or immune.get("breaker_tripped"):
        parts.append(_render_immune(immune))

    # ── Cetana (heartbeat — only if running)
    cetana = context.get("cetana", {})
    if cetana.get("alive"):
        parts.append(_render_cetana(cetana))

    return "\n".join(parts).strip() + "\n"


def write_context_files(cwd: str, context: dict[str, Any]) -> bool:
    """Write context.json and CLAUDE.md to .steward/ directory.

    Uses atomic writes (tempfile + rename) and hash-based dedup
    to avoid unnecessary filesystem churn.

    Returns True if files were written, False if content unchanged.
    """
    steward_dir = Path(cwd) / ".steward"
    steward_dir.mkdir(parents=True, exist_ok=True)

    json_path = steward_dir / "context.json"
    md_path = steward_dir / "CLAUDE.md"

    # Serialize
    json_content = json.dumps(context, indent=2, default=str)
    md_content = render_markdown(context)

    # Hash check — skip write if unchanged
    new_hash = hashlib.sha256(json_content.encode()).hexdigest()[:16]
    old_hash = _read_hash(steward_dir / ".context_hash")

    if new_hash == old_hash:
        return False

    # Atomic write: json
    _atomic_write(json_path, json_content)

    # Atomic write: markdown
    _atomic_write(md_path, md_content)

    # Store hash
    _atomic_write(steward_dir / ".context_hash", new_hash)

    logger.debug("Context bridge: wrote context.json + CLAUDE.md (hash=%s)", new_hash)
    return True


# ── Data Readers ─────────────────────────────────────────────────────
# Each reader tries ServiceRegistry first (daemon mode), falls back to
# disk (CLI cold-start). Never crashes — returns empty dict on failure.


def _read_senses(cwd: str) -> dict[str, Any]:
    """Read environmental perception from SenseCoordinator or cold-boot."""
    try:
        from steward.senses.coordinator import SenseCoordinator

        senses = SenseCoordinator(cwd=cwd)
        senses.perceive_all(force=False)  # Use cache if available

        result: dict[str, Any] = {}
        prompt = senses.format_for_prompt()
        if prompt:
            result["prompt_summary"] = prompt

        result["total_pain"] = senses.get_total_pain()

        boot = senses.boot_summary()
        if boot:
            result["detail"] = boot

        return result
    except Exception as e:
        logger.debug("Senses read failed (non-fatal): %s", e)
        return {}


def _read_health() -> dict[str, Any]:
    """Read Vedana health signal from Cetana's last beat."""
    try:
        from steward.services import SVC_PROVIDER
        from vibe_core.di import ServiceRegistry

        # Try to get the last vedana from cetana
        cetana = _get_cetana()
        if cetana is not None:
            beat = cetana.last_beat
            if beat is not None and beat.vedana is not None:
                v = beat.vedana
                return {
                    "value": round(v.health, 3),
                    "guna": v.guna,
                    "provider_health": round(v.provider_health, 3),
                    "error_pressure": round(v.error_pressure, 3),
                    "context_pressure": round(v.context_pressure, 3),
                }

        # Fallback: check if provider is alive at least
        provider = ServiceRegistry.get(SVC_PROVIDER)
        if provider is not None:
            alive = len(provider) if hasattr(provider, "__len__") else 0
            return {"value": 0.5 if alive > 0 else 0.0, "guna": "rajas", "source": "provider_only"}

        return {}
    except Exception as e:
        logger.debug("Health read failed (non-fatal): %s", e)
        return {}


def _read_gaps(cwd: str) -> dict[str, Any]:
    """Read capability gaps from GapTracker."""
    try:
        from steward.gaps import GapTracker
        from steward.services import SVC_MEMORY
        from vibe_core.di import ServiceRegistry

        # Try ServiceRegistry first (daemon mode)
        memory = ServiceRegistry.get(SVC_MEMORY)
        if memory is not None and hasattr(memory, "gap_tracker"):
            tracker = memory.gap_tracker
        else:
            # Cold-start: load from disk
            tracker = _load_gaps_from_disk(cwd)

        if tracker is None:
            return {}

        active = tracker.active_gaps()
        return {
            "active": [
                {
                    "category": g.category,
                    "description": g.description,
                    "context": g.context,
                }
                for g in active
            ],
            "stats": tracker.stats,
            "prompt_summary": tracker.format_for_prompt(),
        }
    except Exception as e:
        logger.debug("Gaps read failed (non-fatal): %s", e)
        return {}


def _read_sessions(cwd: str) -> dict[str, Any]:
    """Read session history from SessionLedger."""
    try:
        from steward.session_ledger import SessionLedger

        ledger = SessionLedger(cwd=cwd)
        sessions = ledger.sessions
        recent = sessions[-5:] if sessions else []

        return {
            "recent": [
                {
                    "task": s.task[:200],
                    "outcome": s.outcome,
                    "summary": getattr(s, "summary", ""),
                    "timestamp": s.timestamp,
                    "tokens": s.tokens,
                    "rounds": s.rounds,
                    "errors": getattr(s, "errors", []),
                    "files_written": getattr(s, "files_written", []),
                    "buddhi_action": getattr(s, "buddhi_action", ""),
                }
                for s in recent
            ],
            "stats": ledger.stats,
            "prompt_summary": ledger.prompt_context(),
        }
    except Exception as e:
        logger.debug("Sessions read failed (non-fatal): %s", e)
        return {}


def _read_tasks(cwd: str) -> dict[str, Any]:
    """Read pending tasks from TaskManager."""
    try:
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        task_manager = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_manager is None:
            return {}

        all_tasks = task_manager.tasks
        pending = [
            {
                "id": tid,
                "title": getattr(t, "title", str(t)),
                "priority": getattr(t, "priority", 0),
                "status": getattr(t, "status", "unknown"),
            }
            for tid, t in all_tasks.items()
            if getattr(t, "status", None) not in ("done", "completed", "archived")
        ]

        return {"pending": pending[:20]}
    except Exception as e:
        logger.debug("Tasks read failed (non-fatal): %s", e)
        return {}


def _read_federation() -> dict[str, Any]:
    """Read federation peer state from Reaper + Marketplace."""
    try:
        from steward.services import SVC_MARKETPLACE, SVC_REAPER
        from vibe_core.di import ServiceRegistry

        result: dict[str, Any] = {}

        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is not None:
            result.update(reaper.stats())
            # Include peer details for alive/suspect peers
            alive = reaper.alive_peers()
            suspect = reaper.suspect_peers()
            if alive or suspect:
                result["peers"] = [
                    {
                        "agent_id": p.agent_id,
                        "status": p.status.value if hasattr(p.status, "value") else str(p.status),
                        "trust": round(p.trust, 2),
                        "capabilities": list(p.capabilities) if p.capabilities else [],
                    }
                    for p in (alive + suspect)[:20]
                ]

        marketplace = ServiceRegistry.get(SVC_MARKETPLACE)
        if marketplace is not None:
            result["marketplace"] = marketplace.stats()

        return result
    except Exception as e:
        logger.debug("Federation read failed (non-fatal): %s", e)
        return {}


def _read_immune() -> dict[str, Any]:
    """Read immune system state."""
    try:
        from steward.services import SVC_IMMUNE
        from vibe_core.di import ServiceRegistry

        immune = ServiceRegistry.get(SVC_IMMUNE)
        if immune is None:
            return {}

        return immune.stats()
    except Exception as e:
        logger.debug("Immune read failed (non-fatal): %s", e)
        return {}


def _read_cetana() -> dict[str, Any]:
    """Read heartbeat (Cetana) state."""
    try:
        cetana = _get_cetana()
        if cetana is None:
            return {}
        return cetana.stats()
    except Exception as e:
        logger.debug("Cetana read failed (non-fatal): %s", e)
        return {}


# ── Markdown Renderers ───────────────────────────────────────────────


def _render_health_headline(health: dict[str, Any]) -> str:
    """Render the health headline — the first thing Opus sees after DNA."""
    if not health:
        return "## System Status: Unknown (steward not running or no health data)\n"

    value = health.get("value", 0)
    guna = health.get("guna", "unknown")

    if value >= 0.7:
        mood = "Healthy"
        detail = "All systems operational. No urgent action needed."
    elif value >= 0.3:
        mood = "Stressed"
        pressure_parts = []
        if health.get("error_pressure", 0) > 0.3:
            pressure_parts.append(f"error pressure {health['error_pressure']:.0%}")
        if health.get("context_pressure", 0) > 0.5:
            pressure_parts.append(f"context pressure {health['context_pressure']:.0%}")
        if health.get("provider_health", 1) < 0.8:
            pressure_parts.append(f"provider health {health['provider_health']:.0%}")
        detail = f"Friction detected: {', '.join(pressure_parts)}." if pressure_parts else "Moderate load."
    else:
        mood = "Critical"
        detail = "System in distress. Health below 0.3 triggers emergency heartbeat frequency (2Hz)."

    return f"## System Status: {mood} (health={value:.2f}, guna={guna})\n\n{detail}\n"


def _collect_urgencies(
    health: dict, gaps: dict, sessions: dict, immune: dict
) -> list[str]:
    """Collect urgent items that Opus should address, ordered by severity."""
    urgencies: list[str] = []

    # Critical health
    if health.get("value", 1) < 0.3:
        urgencies.append(
            f"**CRITICAL**: System health at {health['value']:.2f} ({health.get('guna', '?')}). "
            "Investigate provider failures, error cascades, or context exhaustion."
        )

    # Immune breaker tripped
    breaker = immune.get("breaker", {})
    if breaker.get("tripped") or immune.get("breaker_tripped"):
        urgencies.append(
            "**IMMUNE BREAKER TRIPPED**: Self-healing suspended after repeated failures. "
            "Manual diagnosis needed — the immune system gave up."
        )

    # Recent session failures
    recent = sessions.get("recent", [])
    consecutive_errors = 0
    for s in reversed(recent):
        if s.get("outcome") == "error":
            consecutive_errors += 1
        else:
            break
    if consecutive_errors >= 2:
        last_errors = [s for s in recent if s.get("outcome") == "error"]
        tasks = [s.get("task", "?")[:80] for s in last_errors[-3:]]
        urgencies.append(
            f"**{consecutive_errors} consecutive failed sessions**: steward is stuck. "
            f"Recent failures: {'; '.join(tasks)}"
        )

    # Active gaps
    active_gaps = gaps.get("active", [])
    if active_gaps:
        gap_descs = [g.get("description", "?") for g in active_gaps[:3]]
        urgencies.append(
            f"**{len(active_gaps)} capability gap(s)**: {'; '.join(gap_descs)}"
        )

    # Provider degraded
    if health.get("provider_health", 1) < 0.5:
        urgencies.append(
            f"**Provider health low** ({health.get('provider_health', 0):.0%}): "
            "LLM providers may be down or rate-limited."
        )

    return urgencies


def _render_senses(senses: dict[str, Any]) -> str:
    """Render environmental perception."""
    parts = ["## Environment\n"]

    prompt = senses.get("prompt_summary", "")
    if prompt:
        parts.append(prompt)
        parts.append("")

    pain = senses.get("total_pain", 0)
    if pain > 0.3:
        parts.append(f"**Environmental pain: {pain:.2f}** — some senses report issues.\n")

    return "\n".join(parts)


def _render_gaps(gaps: dict[str, Any]) -> str:
    """Render capability gaps."""
    parts = ["## Capability Gaps\n"]

    prompt = gaps.get("prompt_summary", "")
    if prompt:
        parts.append(prompt)
    else:
        for g in gaps.get("active", [])[:5]:
            cat = g.get("category", "unknown")
            desc = g.get("description", "?")
            parts.append(f"- **[{cat}]** {desc}")

    stats = gaps.get("stats", {})
    if stats:
        parts.append(
            f"\nGap stats: {stats.get('active', 0)} active, "
            f"{stats.get('resolved', 0)} resolved, "
            f"{stats.get('total_tracked', 0)} total tracked."
        )

    parts.append("")
    return "\n".join(parts)


def _render_sessions(sessions: dict[str, Any]) -> str:
    """Render recent session history."""
    parts = ["## Recent Sessions\n"]

    prompt = sessions.get("prompt_summary", "")
    if prompt:
        parts.append(prompt)
    else:
        for s in sessions.get("recent", [])[-5:]:
            outcome = s.get("outcome", "?")
            task = s.get("task", "?")[:100]
            ts = s.get("timestamp", "")
            rounds = s.get("rounds", 0)
            marker = "x" if outcome == "error" else ("~" if outcome == "partial" else "v")
            parts.append(f"- [{marker}] {ts}: {task} ({rounds} rounds, {outcome})")

            # Show errors for failed sessions — Opus needs to know what went wrong
            errors = s.get("errors", [])
            if errors and outcome == "error":
                for err in errors[:3]:
                    parts.append(f"  - Error: {err}")

    stats = sessions.get("stats", {})
    if stats:
        parts.append(
            f"\nSession stats: {stats.get('total_sessions', 0)} total, "
            f"{stats.get('success_rate', 0):.0%} success rate, "
            f"{stats.get('avg_tokens_per_session', 0)} avg tokens."
        )

    parts.append("")
    return "\n".join(parts)


def _render_tasks(tasks: dict[str, Any]) -> str:
    """Render pending tasks."""
    parts = ["## Pending Tasks\n"]

    for t in tasks.get("pending", [])[:10]:
        title = t.get("title", "?")
        priority = t.get("priority", 0)
        status = t.get("status", "?")
        parts.append(f"- [{status}] (p{priority}) {title}")

    parts.append("")
    return "\n".join(parts)


def _render_federation(federation: dict[str, Any]) -> str:
    """Render federation peer state."""
    parts = ["## Federation\n"]

    total = federation.get("total_peers", 0)
    by_status = federation.get("by_status", {})
    alive = by_status.get("alive", 0)
    suspect = by_status.get("suspect", 0)
    dead = by_status.get("dead", 0)
    avg_trust = federation.get("avg_trust", 0)

    parts.append(
        f"Peers: {total} total ({alive} alive, {suspect} suspect, {dead} dead). "
        f"Avg trust: {avg_trust:.2f}."
    )

    peers = federation.get("peers", [])
    if peers:
        parts.append("")
        for p in peers[:10]:
            agent = p.get("agent_id", "?")
            status = p.get("status", "?")
            trust = p.get("trust", 0)
            caps = ", ".join(p.get("capabilities", [])[:5]) or "none"
            parts.append(f"- {agent}: {status} (trust={trust:.2f}, caps=[{caps}])")

    mkt = federation.get("marketplace", {})
    if mkt:
        parts.append(
            f"\nMarketplace: {mkt.get('active_claims', 0)} active claims, "
            f"{mkt.get('unique_agents', 0)} agents."
        )

    parts.append("")
    return "\n".join(parts)


def _render_immune(immune: dict[str, Any]) -> str:
    """Render immune system state."""
    parts = ["## Immune System\n"]

    attempted = immune.get("heals_attempted", 0)
    succeeded = immune.get("heals_succeeded", 0)
    rolled_back = immune.get("heals_rolled_back", 0)
    rate = immune.get("success_rate", 0)

    parts.append(
        f"Heals: {attempted} attempted, {succeeded} succeeded, "
        f"{rolled_back} rolled back. Success rate: {rate:.0%}."
    )

    breaker = immune.get("breaker", {})
    if breaker:
        if breaker.get("tripped"):
            cooldown = breaker.get("cooldown_remaining", 0)
            parts.append(
                f"\n**CytokineBreaker TRIPPED** — healing suspended. "
                f"Cooldown: {cooldown:.0f}s remaining. "
                f"Consecutive rollbacks: {breaker.get('consecutive_rollbacks', 0)}."
            )
        elif breaker.get("consecutive_rollbacks", 0) > 0:
            parts.append(
                f"Breaker warning: {breaker['consecutive_rollbacks']} consecutive rollbacks "
                f"(trips at 3)."
            )

    parts.append("")
    return "\n".join(parts)


def _render_cetana(cetana: dict[str, Any]) -> str:
    """Render heartbeat state."""
    parts = ["## Heartbeat (Cetana)\n"]

    hz = cetana.get("frequency_hz", 0)
    beats = cetana.get("total_beats", 0)
    phase = cetana.get("phase", "?")
    anomalies = cetana.get("consecutive_anomalies", 0)

    parts.append(f"Running: {hz:.1f} Hz, {beats} beats, current phase: {phase}.")

    if anomalies > 0:
        parts.append(f"**{anomalies} consecutive anomalies** detected.")

    parts.append("")
    return "\n".join(parts)


# ── Helpers ──────────────────────────────────────────────────────────


def _get_cetana() -> Any:
    """Get Cetana instance from the running agent (if any)."""
    try:
        from steward.agent import StewardAgent

        # Cetana is a daemon thread on the agent — no SVC_ constant for it.
        # We check if there's a running agent with a cetana attribute.
        # This is best-effort; in CLI mode there's no agent.
        return None  # Will be wired when hook has access to agent
    except Exception:
        return None


def _load_gaps_from_disk(cwd: str) -> Any:
    """Load gap tracker from .steward/memory.json without booting full memory."""
    try:
        from steward.gaps import GapTracker

        tracker = GapTracker()
        memory_file = Path(cwd) / ".steward" / "memory.json"
        if memory_file.is_file():
            data = json.loads(memory_file.read_text(encoding="utf-8"))
            gaps_data = data.get("steward", {}).get("gap_tracker", {}).get("value")
            if isinstance(gaps_data, list):
                tracker.load_from_dict(gaps_data)
        return tracker
    except Exception:
        return None


def _read_hash(path: Path) -> str:
    """Read stored hash from file, or empty string if missing."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically via tempfile + rename."""
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp_path, str(path))
    except Exception:
        os.close(fd) if not os.get_inheritable(fd) else None
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
