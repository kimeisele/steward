"""
Buddy Bubble — System Introspection Tool.

Lets a CLI operator enter Steward's substrate to inspect, debug, and browse
the entire system state. Pure substrate read — zero LLM tokens.

ARCHITECTURE: Delegates to context_bridge for overlapping reads (health,
federation basics, immune, cetana). Adds unique substrate-level introspection
that context_bridge doesn't cover: Hebbian weights, Lotus routing, signal
queues, deep federation internals.

Actions:
  status     — Full system: all services, federation, health
  peers      — Reaper state: alive/suspect/dead, trust, capabilities
  signals    — Active A2A tasks, pending NADI messages
  substrate  — Lotus routing stats, Hebbian weights, cache, Antaranga slots
  health     — Vedana snapshot, cognitive pipeline state
  marketplace— Active claims, contests, expirations
  federation — Full federation: gateway stats, bridge, transport, relay

Security: This tool exposes FULL internal state. CLI-only — API endpoints
must NEVER pass raw Buddy Bubble output to HTTP responses.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from vibe_core.di import ServiceRegistry
from vibe_core.tools.tool_protocol import Tool, ToolResult

logger = logging.getLogger("STEWARD.TOOL.BUDDY_BUBBLE")

# Valid actions for the tool
ACTIONS = (
    "status",
    "peers",
    "signals",
    "substrate",
    "health",
    "marketplace",
    "federation",
)


class BuddyBubbleTool(Tool):
    """Enter Steward's substrate to inspect live system state.

    Pure substrate read — zero LLM tokens. Returns structured JSON
    for the CLI operator to browse, debug, and understand the system.
    """

    @property
    def name(self) -> str:
        return "buddy_bubble"

    @property
    def description(self) -> str:
        return (
            "Introspect Steward's live substrate. Actions: status (full overview), "
            "peers (reaper state), signals (A2A/NADI queues), substrate (Lotus routing, "
            "Hebbian weights, Antaranga slots), health (Vedana), marketplace (slot claims), "
            "federation (bridge/transport/relay). Zero LLM tokens — pure substrate read."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "required": True,
                "enum": list(ACTIONS),
                "description": ("What to inspect: status, peers, signals, substrate, health, marketplace, federation"),
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        action = parameters.get("action")
        if not action:
            raise ValueError("action is required")
        if action not in ACTIONS:
            raise ValueError(f"Unknown action '{action}'. Valid: {', '.join(ACTIONS)}")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        action = parameters["action"]
        handler = _HANDLERS.get(action)
        if handler is None:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        try:
            data = handler()
            return ToolResult(success=True, output=_format(data), metadata=data)
        except Exception as e:
            logger.exception("Buddy Bubble '%s' failed", action)
            return ToolResult(success=False, error=f"Introspection failed: {e}")


# ── Context Bridge Delegation ────────────────────────────────────────
# context_bridge already reads: health, federation, immune, cetana.
# We delegate those reads instead of reimplementing them.


def _cb_health() -> dict[str, object]:
    """Delegate to context_bridge._read_health()."""
    try:
        from steward.context_bridge import _read_health

        return _read_health()
    except Exception:
        return {}


def _cb_federation() -> dict[str, object]:
    """Delegate to context_bridge._read_federation()."""
    try:
        from steward.context_bridge import _read_federation

        return _read_federation()
    except Exception:
        return {}


def _cb_immune() -> dict[str, object]:
    """Delegate to context_bridge._read_immune()."""
    try:
        from steward.context_bridge import _read_immune

        return _read_immune()
    except Exception:
        return {}


def _cb_cetana() -> dict[str, object]:
    """Delegate to context_bridge._read_cetana()."""
    try:
        from steward.context_bridge import _read_cetana

        return _read_cetana()
    except Exception:
        return {}


# ── Action Handlers ──────────────────────────────────────────────────


def _status() -> dict[str, object]:
    """Full system overview — services, federation, health in one shot."""
    from steward.services import NORTH_STAR_TEXT

    result: dict[str, object] = {
        "north_star": NORTH_STAR_TEXT,
        "timestamp": time.time(),
    }

    # Services inventory
    result["services"] = _collect_services()

    # Health — delegated to context_bridge + enriched
    result["health"] = _health()

    # Federation summary — peers with full detail
    result["federation"] = _peers()

    # Marketplace summary
    marketplace = _marketplace()
    if marketplace:
        result["marketplace"] = marketplace

    return result


def _peers() -> dict[str, object]:
    """Reaper peer state: alive/suspect/dead with full details.

    Extends context_bridge._read_federation() with dead peers and
    per-peer detail (heartbeat_count, fingerprint, last_seen) that
    context_bridge omits.
    """
    from steward.services import SVC_REAPER

    reaper = ServiceRegistry.get(SVC_REAPER)
    if reaper is None:
        return {"error": "Reaper not booted"}

    # Start with context_bridge's federation base (stats + alive/suspect summary)
    result: dict[str, object] = _cb_federation()

    # Override with DEEP peer detail (all 3 states incl. dead — context_bridge skips dead)
    for label, getter in (
        ("alive", reaper.alive_peers),
        ("suspect", reaper.suspect_peers),
        ("dead", reaper.dead_peers),
    ):
        peers = getter()
        if peers:
            result[label] = [
                {
                    "agent_id": p.agent_id,
                    "trust": round(p.trust, 3),
                    "heartbeat_count": p.heartbeat_count,
                    "capabilities": list(p.capabilities) if p.capabilities else [],
                    "fingerprint": p.fingerprint[:16] + "..." if len(p.fingerprint) > 16 else p.fingerprint,
                    "last_seen": p.last_seen,
                }
                for p in peers
            ]

    return result


def _signals() -> dict[str, object]:
    """Active A2A tasks and pending NADI messages.

    UNIQUE to Buddy Bubble — context_bridge has no signal queue introspection.
    """
    from steward.services import SVC_A2A_ADAPTER, SVC_FEDERATION, SVC_FEDERATION_TRANSPORT

    result: dict[str, object] = {}

    # A2A adapter state
    a2a = ServiceRegistry.get(SVC_A2A_ADAPTER)
    if a2a is not None and hasattr(a2a, "stats"):
        result["a2a"] = a2a.stats()

    # NADI transport state
    transport = ServiceRegistry.get(SVC_FEDERATION_TRANSPORT)
    if transport is not None and hasattr(transport, "stats"):
        result["nadi_transport"] = transport.stats()

    # Federation bridge outbox
    bridge = ServiceRegistry.get(SVC_FEDERATION)
    if bridge is not None:
        outbox = getattr(bridge, "_outbox", [])
        result["nadi_outbox_size"] = len(outbox)
        if outbox:
            result["nadi_outbox_preview"] = [
                {"op": ev.get("op", "?"), "target": ev.get("target_agent", "?")} for ev in outbox[:5]
            ]

    return result


def _substrate() -> dict[str, object]:
    """Lotus routing, Hebbian weights, Antaranga slots, cache stats.

    UNIQUE to Buddy Bubble — context_bridge has zero substrate introspection.
    """
    from steward.services import SVC_ANTARANGA, SVC_ATTENTION, SVC_CACHE, SVC_SIKSASTAKAM, SVC_SYNAPSE_STORE

    result: dict[str, object] = {}

    # MahaAttention (O(1) Lotus routing)
    attention = ServiceRegistry.get(SVC_ATTENTION)
    if attention is not None and hasattr(attention, "stats"):
        stats = attention.stats()
        result["attention"] = {
            "mechanism": getattr(stats, "mechanism", "unknown"),
            "registered_intents": getattr(stats, "registered_intents", 0),
            "queries_resolved": getattr(stats, "queries_resolved", 0),
            "cache_hits": getattr(stats, "cache_hits", 0),
            "estimated_ops_saved": getattr(stats, "estimated_ops_saved", 0),
        }

    # SynapseStore (Hebbian weights)
    synapse = ServiceRegistry.get(SVC_SYNAPSE_STORE)
    if synapse is not None and hasattr(synapse, "get_weights"):
        weights = synapse.get_weights()
        total = sum(len(v) for v in weights.values())
        flat: list[tuple[str, str, float]] = []
        for trigger, actions in weights.items():
            for action, w in actions.items():
                flat.append((trigger, action, w))
        flat.sort(key=lambda x: x[2], reverse=True)
        result["synapse"] = {
            "total_triggers": len(weights),
            "total_connections": total,
            "top_10": [{"trigger": t, "action": a, "weight": round(w, 4)} for t, a, w in flat[:10]],
            "bottom_5": [{"trigger": t, "action": a, "weight": round(w, 4)} for t, a, w in flat[-5:]] if flat else [],
        }

    # AntarangaRegistry (512-slot contiguous RAM)
    antaranga = ServiceRegistry.get(SVC_ANTARANGA)
    if antaranga is not None:
        active = antaranga.active_count() if hasattr(antaranga, "active_count") else "?"
        total_prana = antaranga.total_prana() if hasattr(antaranga, "total_prana") else "?"
        result["antaranga"] = {
            "active_slots": active,
            "total_prana": total_prana,
            "max_slots": 512,
        }

    # Siksastakam (7-beat cache lifecycle)
    siks = ServiceRegistry.get(SVC_SIKSASTAKAM)
    if siks is not None and hasattr(siks, "stats"):
        result["siksastakam"] = siks.stats()

    # Ephemeral cache
    cache = ServiceRegistry.get(SVC_CACHE)
    if cache is not None and hasattr(cache, "stats"):
        result["cache"] = cache.stats()

    return result


def _health() -> dict[str, object]:
    """Health: delegated to context_bridge + enriched with immune and cetana.

    context_bridge._read_health() provides vedana + provider basics.
    We add immune stats and cetana stats which context_bridge reads
    in separate functions.
    """
    # Base health from context_bridge (vedana, provider)
    result: dict[str, object] = _cb_health()

    # Enrich with cetana stats
    cetana_data = _cb_cetana()
    if cetana_data:
        result["cetana"] = cetana_data

    # Enrich with immune system
    immune_data = _cb_immune()
    if immune_data:
        result["immune"] = immune_data

    return result


def _marketplace() -> dict[str, object]:
    """Active marketplace claims, contests, expirations.

    Extends context_bridge with per-claim detail (TTL, renewals)
    that context_bridge omits.
    """
    from steward.services import SVC_MARKETPLACE

    marketplace = ServiceRegistry.get(SVC_MARKETPLACE)
    if marketplace is None:
        return {"error": "Marketplace not booted"}

    result: dict[str, object] = marketplace.stats()

    claims = marketplace.list_claims()
    if claims:
        result["claims"] = [
            {
                "slot_id": c.slot_id,
                "agent_id": c.agent_id,
                "trust_at_claim": round(c.trust_at_claim, 3),
                "ttl_s": c.ttl_s,
                "renewals": c.renewals,
            }
            for c in claims[:20]
        ]

    return result


def _federation() -> dict[str, object]:
    """Full federation: bridge, transport, relay, A2A, discovery.

    UNIQUE depth — context_bridge only reads Reaper+Marketplace stats.
    This reads all 6 federation services + deep bridge internals.
    """
    from steward.services import (
        SVC_A2A_ADAPTER,
        SVC_A2A_DISCOVERY,
        SVC_FEDERATION,
        SVC_FEDERATION_RELAY,
        SVC_FEDERATION_TRANSPORT,
        SVC_GIT_NADI_SYNC,
    )

    result: dict[str, object] = {}

    # Bridge
    bridge = ServiceRegistry.get(SVC_FEDERATION)
    if bridge is not None:
        result["bridge"] = {
            "agent_id": getattr(bridge, "agent_id", "?"),
            "outbox_size": len(getattr(bridge, "_outbox", [])),
            "operations": list(getattr(bridge, "_dispatch", {}).keys()) if hasattr(bridge, "_dispatch") else [],
        }

    # Transport
    transport = ServiceRegistry.get(SVC_FEDERATION_TRANSPORT)
    if transport is not None and hasattr(transport, "stats"):
        result["transport"] = transport.stats()

    # Relay
    relay = ServiceRegistry.get(SVC_FEDERATION_RELAY)
    if relay is not None and hasattr(relay, "stats"):
        result["relay"] = relay.stats()

    # Git NADI sync
    git_sync = ServiceRegistry.get(SVC_GIT_NADI_SYNC)
    if git_sync is not None and hasattr(git_sync, "stats"):
        result["git_nadi_sync"] = git_sync.stats()

    # A2A adapter
    a2a = ServiceRegistry.get(SVC_A2A_ADAPTER)
    if a2a is not None and hasattr(a2a, "stats"):
        result["a2a_adapter"] = a2a.stats()

    # A2A discovery
    discovery = ServiceRegistry.get(SVC_A2A_DISCOVERY)
    if discovery is not None and hasattr(discovery, "stats"):
        result["a2a_discovery"] = discovery.stats()

    # Peers — deep detail via _peers()
    result["peers"] = _peers()

    return result


# ── Helpers ──────────────────────────────────────────────────────────


def _collect_services() -> dict[str, str]:
    """List all registered SVC_ services and their boot status."""
    try:
        import steward.services as svc_mod

        services: dict[str, str] = {}
        for name in sorted(dir(svc_mod)):
            if not name.startswith("SVC_"):
                continue
            cls = getattr(svc_mod, name)
            if not isinstance(cls, type):
                continue
            instance = ServiceRegistry.get(cls)
            if instance is not None:
                services[name] = type(instance).__name__
            else:
                services[name] = "(not booted)"
        return services
    except Exception as e:
        return {"error": str(e)}


def _format(data: dict[str, object]) -> str:
    """Format introspection data as readable text for the CLI operator."""
    import json

    return json.dumps(data, indent=2, default=str)


# ── Dispatch ─────────────────────────────────────────────────────────
_HANDLERS: dict[str, object] = {
    "status": _status,
    "peers": _peers,
    "signals": _signals,
    "substrate": _substrate,
    "health": _health,
    "marketplace": _marketplace,
    "federation": _federation,
}
