"""
GENESIS Phase Hook — Pokedex Sync from agent-city.

Reads agent-city's data/pokedex.json via GitHub API, converts active
agents to AgentCards, and ingests them via deck.ingest_shared_card().

Readonly now — bidirectional (OP_REQUEST_AGENT_CARD) ready for later.
"""

from __future__ import annotations

import base64
import json
import logging
import time

from steward.phase_hook import GENESIS, BasePhaseHook, PhaseContext
from steward.services import SVC_AGENT_DECK
from vibe_core.di import ServiceRegistry

logger = logging.getLogger("STEWARD.HOOKS.GENESIS_POKEDEX")

_MIN_SYNC_INTERVAL_S = 600.0  # 10 minutes
_POKEDEX_REPO = "agent-city"

# Zone → capability mapping
_ZONE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "governance": ("review_code", "code_review", "analysis"),
    "engineering": ("fix_tests", "fix_lint", "code_review"),
    "research": ("explore", "analysis", "architecture"),
    "discovery": ("explore", "codebase"),
    "operations": ("update_deps", "ci_automation"),
    "commerce": ("explore", "analysis"),
}

# Varna → supplementary capabilities
_VARNA_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "SHILPIN": ("fix_tests", "fix_lint"),  # Artisan (builder)
    "VANIJYA": ("update_deps",),  # Merchant
    "PAKSHI": ("explore", "codebase"),  # Messenger
    "RISHI": ("analysis", "architecture"),  # Sage
    "DVIJA": ("review_code", "testing"),  # Scholar
}


def _get_federation_owner() -> str:
    """Get GitHub owner from peer.json."""
    from pathlib import Path

    peer_path = Path("data/federation/peer.json")
    if peer_path.exists():
        try:
            data = json.loads(peer_path.read_text())
            repo = data.get("identity", {}).get("repo", "")
            if "/" in repo:
                return repo.split("/")[0]
        except (json.JSONDecodeError, OSError):
            pass
    return ""


def _fetch_pokedex(owner: str) -> list[dict] | None:
    """Fetch pokedex.json from agent-city via gh CLI.

    Returns list of agent entries or None on failure.
    """
    from steward.hooks.genesis import _gh

    raw = _gh([
        "api",
        f"repos/{owner}/{_POKEDEX_REPO}/contents/data/pokedex.json",
        "--jq", ".content",
    ])
    if not raw:
        return None

    try:
        content = base64.b64decode(raw.strip()).decode("utf-8")
        data = json.loads(content)
    except Exception as e:
        logger.debug("Pokedex parse failed: %s", e)
        return None

    if not isinstance(data, dict):
        return None

    agents = data.get("agents")
    if not isinstance(agents, list):
        return None

    return agents


def convert_pokedex_entry(entry: dict) -> dict | None:
    """Convert a pokedex agent entry to an AgentCard dict.

    Returns None if the entry is unusable (archived, missing data).
    """
    name = entry.get("name", "")
    if not name:
        return None

    # Filter by status — only active/discovered/citizen
    status = entry.get("status", "")
    if status in ("archived", "exiled", "frozen"):
        return None

    classification = entry.get("classification", {})
    zone = classification.get("zone", "")
    varna = classification.get("varna", "")
    guna_desc = classification.get("guna_description", "")

    # Build capabilities from zone + varna
    caps = set(_ZONE_CAPABILITIES.get(zone, ("explore",)))
    caps.update(_VARNA_CAPABILITIES.get(varna, ()))
    capabilities = sorted(caps)

    # Derive seed from signature or coord_sum
    seed_data = entry.get("seed", {})
    coord_sum = seed_data.get("coord_sum", 0)
    # Use coord_sum * diw as a unique-enough seed
    vitals = entry.get("vitals", {})
    diw = vitals.get("diw", 1)
    seed = (coord_sum * 10000 + diw) if coord_sum else hash(name) & 0x7FFFFFFF

    # Map prana vitality to initial weight (0.4-0.7 range)
    prana = vitals.get("prana", 50)
    prana_max = vitals.get("prana_max", 108)
    weight = 0.4 + 0.3 * (prana / max(prana_max, 1))

    # Build system prompt from agent's identity
    moltbook = entry.get("moltbook", {})
    description = moltbook.get("description", "")
    prompt_parts = [f"You are {name}, a specialized agent."]
    if zone:
        prompt_parts.append(f"Zone: {zone}.")
    if guna_desc:
        prompt_parts.append(f"Nature: {guna_desc}.")
    if description:
        prompt_parts.append(description)
    prompt_parts.append("Complete tasks efficiently and return clear results.")

    return {
        "seed": seed,
        "name": name,
        "capabilities": capabilities,
        "system_prompt": " ".join(prompt_parts),
        "tool_filter": [],  # all tools
        "hebbian_weight": round(weight, 4),
        "spawn_count": 0,
        "success_count": 0,
        "created_at": time.time(),
        "source": "agent-city:pokedex",
    }


class GenesisPokedexSyncHook(BasePhaseHook):
    """Sync agent profiles from agent-city's Pokedex into the local AgentDeck.

    Runs at most once per 10 minutes. Graceful degradation if agent-city
    is unavailable. Foreign cards enter via ingest_shared_card() which
    applies trust discount and preserves local proven cards.
    """

    def __init__(self) -> None:
        self._last_sync: float = 0.0

    @property
    def name(self) -> str:
        return "genesis_pokedex_sync"

    @property
    def phase(self) -> str:
        return GENESIS

    @property
    def priority(self) -> int:
        return 25  # After GenesisDiscoveryHook (20)

    def should_run(self, ctx: PhaseContext) -> bool:
        import os
        import shutil

        if shutil.which("gh") is None:
            return False
        if os.environ.get("STEWARD_DISABLE_DISCOVERY"):
            return False
        return (time.time() - self._last_sync) >= _MIN_SYNC_INTERVAL_S

    def execute(self, ctx: PhaseContext) -> None:
        deck = ServiceRegistry.get(SVC_AGENT_DECK)
        if deck is None:
            return

        owner = _get_federation_owner()
        if not owner:
            logger.debug("POKEDEX_SYNC: no federation owner — skipping")
            self._last_sync = time.time()
            return

        agents = _fetch_pokedex(owner)
        if agents is None:
            logger.debug("POKEDEX_SYNC: could not fetch pokedex — skipping")
            self._last_sync = time.time()
            return

        ingested = 0
        skipped = 0
        for entry in agents:
            card_data = convert_pokedex_entry(entry)
            if card_data is None:
                skipped += 1
                continue

            result = deck.ingest_shared_card(card_data, source="agent-city:pokedex")
            if result is not None:
                ingested += 1
            else:
                skipped += 1

        if ingested:
            logger.info(
                "POKEDEX_SYNC: ingested %d agents from agent-city (%d skipped)",
                ingested, skipped,
            )

        self._last_sync = time.time()
        ctx.operations.append(
            f"genesis_pokedex_sync:ingested={ingested},skipped={skipped},total={len(agents)}"
        )
