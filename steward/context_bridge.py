"""
Context Bridge — Steward's living state for external consumers.

Two layers:
  1. assemble_context()   — Deterministic data collection (zero LLM).
     Reads senses, vedana, gaps, sessions, tasks, federation, immune, cetana.
  2. collect_architecture_metadata() — Reads architecture from LIVING CODE.
     SVC_ docstrings, kshetra mapping, phase hooks, north star — all from
     the actual codebase, not hardcoded prose.

The SYNTHESIS (CLAUDE.md) is done by steward's own LLM via the
synthesize_briefing tool. This module only collects raw material.

Usage:
    from steward.context_bridge import assemble_context, collect_architecture_metadata
    from steward.context_bridge import write_context_json

    context = assemble_context("/path/to/project")
    write_context_json("/path/to/project", context)

    # Architecture metadata (for LLM synthesis prompt):
    arch = collect_architecture_metadata()
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path

logger = logging.getLogger("STEWARD.CONTEXT_BRIDGE")

# Schema version — bump when context shape changes materially
_CONTEXT_VERSION = 1


def assemble_context(cwd: str | None = None) -> dict[str, object]:
    """Assemble steward's full context from all available sources.

    Pulls from ServiceRegistry if services are booted (daemon mode).
    Falls back to disk-based loading for cold-start (CLI mode).

    Returns a structured dict — the canonical context representation.
    """
    cwd = cwd or str(Path.cwd())
    ctx: dict[str, object] = {
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

    # ── Campaign (success signal evaluation) ─────────────────────────
    ctx["campaign"] = _read_campaign(cwd)

    # ── Cetana (heartbeat state) ─────────────────────────────────────
    ctx["cetana"] = _read_cetana()

    # ── GitHub Issues (open work tracked) ──────────────────────────
    ctx["issues"] = _read_github_issues(cwd)

    return ctx


def collect_architecture_metadata() -> dict[str, object]:
    """Read architecture description from the LIVING CODE — not hardcoded text.

    Collects:
      - SVC_ class docstrings (what each service IS)
      - Kshetra mapping (25 Sankhya elements → steward modules)
      - Phase constants + hook registry (MURALI cycle)
      - North Star text (the system's compressed purpose)

    Returns structured dict that an LLM can consume to understand
    steward's architecture. Zero hardcoded prose.
    """
    arch: dict[str, object] = {}

    # ── North Star (the system's purpose, from code) ─────────────────
    try:
        from steward.services import NORTH_STAR_TEXT

        arch["north_star"] = NORTH_STAR_TEXT
    except Exception as e:
        logger.debug("Failed to load north_star: %s", e)
        arch["north_star"] = None

    # ── SVC_ service docstrings (what each service IS) ───────────────
    try:
        import steward.services as svc_mod

        services = {}
        for name in dir(svc_mod):
            if name.startswith("SVC_"):
                cls = getattr(svc_mod, name)
                if isinstance(cls, type) and cls.__doc__:
                    services[name] = cls.__doc__.strip()
        arch["services"] = services
    except Exception as e:
        logger.debug("Failed to collect SVC_ docstrings: %s", e)
        arch["services"] = {}

    # ── Kshetra (25-tattva mapping from living code) ─────────────────
    try:
        from steward.kshetra import enumerate_kshetra

        arch["kshetra"] = enumerate_kshetra()
    except Exception as e:
        logger.debug("Failed to enumerate kshetra: %s", e)
        arch["kshetra"] = []

    # ── Phase constants (MURALI cycle) ───────────────────────────────
    try:
        from steward.phase_hook import DHARMA, GENESIS, KARMA, MOKSHA

        arch["phases"] = {
            GENESIS: "Discover — run senses, scan environment",
            DHARMA: "Govern — check invariants, validate health",
            KARMA: "Execute — work on highest-priority task",
            MOKSHA: "Reflect — persist state, log stats, learn",
        }
    except Exception as e:
        logger.debug("Failed to load phase constants: %s", e)
        arch["phases"] = {}

    # ── Registered hooks (what behavior is wired into each phase) ────
    try:
        from steward.services import SVC_PHASE_HOOKS
        from vibe_core.di import ServiceRegistry

        hook_registry = ServiceRegistry.get(SVC_PHASE_HOOKS)
        if hook_registry is not None:
            arch["hooks"] = hook_registry.stats()
        else:
            arch["hooks"] = {}
    except Exception as e:
        logger.debug("Failed to read hook registry: %s", e)
        arch["hooks"] = {}

    # ── Registered tools (what steward can DO) ───────────────────────
    try:
        from steward.services import SVC_TOOL_REGISTRY
        from vibe_core.di import ServiceRegistry

        tool_reg = ServiceRegistry.get(SVC_TOOL_REGISTRY)
        if tool_reg is not None:
            arch["tools"] = [
                {"name": d["name"], "description": d.get("description", "")} for d in tool_reg.get_tool_descriptions()
            ]
        else:
            arch["tools"] = []
    except Exception as e:
        logger.debug("Failed to read tool registry: %s", e)
        arch["tools"] = []

    return arch


def write_context_json(cwd: str, context: dict[str, object]) -> bool:
    """Write context.json to .steward/ directory.

    Uses atomic writes (tempfile + rename) and hash-based dedup
    to avoid unnecessary filesystem churn.

    CLAUDE.md is NOT written here — that's done by the synthesize_briefing
    tool using steward's own LLM intelligence.

    Returns True if file was written, False if content unchanged.
    """
    steward_dir = Path(cwd) / ".steward"
    steward_dir.mkdir(parents=True, exist_ok=True)

    json_path = steward_dir / "context.json"

    # Serialize
    json_content = json.dumps(context, indent=2, default=str)

    # Hash check — skip write if unchanged
    new_hash = hashlib.sha256(json_content.encode()).hexdigest()[:16]
    old_hash = _read_hash(steward_dir / ".context_hash")

    if new_hash == old_hash:
        return False

    # Atomic write
    _atomic_write(json_path, json_content)
    _atomic_write(steward_dir / ".context_hash", new_hash)

    logger.debug("Context bridge: wrote context.json (hash=%s)", new_hash)
    return True


# ── Data Readers ─────────────────────────────────────────────────────
# Each reader tries ServiceRegistry first (daemon mode), falls back to
# disk (CLI cold-start). Never crashes — returns empty dict on failure.


def _read_senses(cwd: str) -> dict[str, object]:
    """Read environmental perception from SenseCoordinator or cold-boot."""
    try:
        from steward.senses.coordinator import SenseCoordinator

        senses = SenseCoordinator(cwd=cwd)
        senses.perceive_all(force=False)  # Use cache if available

        result: dict[str, object] = {}
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


def _read_health() -> dict[str, object]:
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


def _read_gaps(cwd: str) -> dict[str, object]:
    """Read capability gaps from GapTracker."""
    try:
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


def _read_sessions(cwd: str) -> dict[str, object]:
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


def _read_tasks(cwd: str) -> dict[str, object]:
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


def _read_federation() -> dict[str, object]:
    """Read federation peer state from Reaper + Marketplace + Gateway."""
    try:
        from steward.services import SVC_FEDERATION_GATEWAY, SVC_MARKETPLACE, SVC_REAPER
        from vibe_core.di import ServiceRegistry

        result: dict[str, object] = {}

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

        gateway = ServiceRegistry.get(SVC_FEDERATION_GATEWAY)
        if gateway is not None and hasattr(gateway, "stats"):
            result["gateway"] = gateway.stats()

        return result
    except Exception as e:
        logger.debug("Federation read failed (non-fatal): %s", e)
        return {}


def _read_immune() -> dict[str, object]:
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


def _read_campaign(cwd: str) -> dict[str, object]:
    """Read campaign success signal evaluation."""
    try:
        from steward.campaign_signals import evaluate

        health = evaluate(cwd)
        if not health.signals:
            return {}
        return {
            "campaign_id": health.campaign_id,
            "all_met": health.all_met,
            "signals": [{"kind": s.kind, "met": s.met, "actual": s.actual} for s in health.signals],
            "failing": list(health.failing_kinds),
        }
    except Exception as e:
        logger.debug("Campaign read failed (non-fatal): %s", e)
        return {}


def _read_cetana() -> dict[str, object]:
    """Read heartbeat (Cetana) state."""
    try:
        cetana = _get_cetana()
        if cetana is None:
            return {}
        return cetana.stats()
    except Exception as e:
        logger.debug("Cetana read failed (non-fatal): %s", e)
        return {}


# ── Helpers ──────────────────────────────────────────────────────────


def _read_github_issues(cwd: str) -> list[dict]:
    """Read open GitHub issues via gh CLI (CBR-budgeted)."""
    import subprocess

    try:
        r = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--json", "number,title", "--limit", "20"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def _get_cetana() -> object | None:
    """Get Cetana instance from ServiceRegistry if available.

    Returns None when no agent is running (CLI mode, tests, hooks).
    """
    try:
        from steward.services import SVC_CETANA
        from vibe_core.di import ServiceRegistry

        return ServiceRegistry.get(SVC_CETANA)
    except (ImportError, KeyError):
        return None


def _load_gaps_from_disk(cwd: str) -> object:
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
    except Exception as e:
        logger.debug("Failed to load gaps from disk: %s", e)
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
    closed = False
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        closed = True
        os.replace(tmp_path, str(path))
    except Exception:
        if not closed:
            os.close(fd)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
