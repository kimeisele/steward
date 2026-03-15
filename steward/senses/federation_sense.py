"""
FederationSense — Cross-repo awareness for the federation.

A Jnanendriya (knowledge sense) that reads the state of ALL
federation repos, not just steward's own. Pulls nadi outboxes,
CI status, health reports from every peer.

Without this, steward is blind beyond its own repo. With it,
steward perceives the entire federation as ONE organism.

The senses are limited (like material senses). Every new metric
we collect expands the system's consciousness.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("STEWARD.SENSE.FEDERATION")


def scan_federation_state() -> dict:
    """Build federation state from the Reaper (already populated by Genesis).

    Does NOT make its own API calls — reads what GenesisDiscoveryHook
    already collected. No duplication, no extra rate-limit consumption.
    """
    from steward.services import SVC_IMMUNE, SVC_REAPER
    from vibe_core.di import ServiceRegistry

    reaper = ServiceRegistry.get(SVC_REAPER)
    if reaper is None:
        return {"error": "no reaper", "peers": {}}

    alive = reaper.alive_peers()
    suspect = reaper.suspect_peers()
    dead = reaper.dead_peers()

    all_peers = alive + suspect + dead
    peers: dict[str, dict] = {}
    for p in all_peers:
        peers[p.agent_id] = {
            "name": p.agent_id,
            "status": p.status.value,
            "trust": p.trust,
            "capabilities": list(p.capabilities),
            "last_seen": p.last_seen,
        }

    immune = ServiceRegistry.get(SVC_IMMUNE)
    immune_stats = immune.stats() if immune else {}

    return {
        "timestamp": time.time(),
        "summary": {
            "total_peers": len(all_peers),
            "alive": len(alive),
            "suspect": len(suspect),
            "dead": len(dead),
        },
        "immune": immune_stats,
        "peers": peers,
    }
