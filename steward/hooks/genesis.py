"""
GENESIS Phase Hook — Active federation peer discovery.

GENESIS = origin/creation. The agent's discovery cycle:
scan federation registry → discover peers → register heartbeats in reaper.

Discovery sources (in priority order):
1. agent-world registry (world_registry.yaml) — authoritative
2. GitHub topic scan (agent-federation-node) — open discovery
3. GitHub org scan (kimeisele/*/.well-known/) — fallback

All sources converge to reaper.record_heartbeat() — the reaper is
source-agnostic. Discovery is deterministic (0 LLM tokens).
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

from steward.phase_hook import GENESIS, BasePhaseHook, PhaseContext
from steward.services import SVC_REAPER
from vibe_core.di import ServiceRegistry

logger = logging.getLogger("STEWARD.HOOKS.GENESIS")

# Rate limit: minimum seconds between discovery scans
_MIN_SCAN_INTERVAL_S = 600.0  # 10 minutes
_GH_TIMEOUT = 15  # seconds per gh CLI call


def _gh(args: list[str], cwd: str | None = None) -> str | None:
    """Run gh CLI command, return stdout or None on failure."""
    try:
        r = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT,
            cwd=cwd,
        )
        return r.stdout if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


class GenesisDiscoveryHook(BasePhaseHook):
    """Actively discover federation peers and register them in the reaper.

    Runs at most once per _MIN_SCAN_INTERVAL_S to respect API rate limits.
    Discovery is additive — new peers get registered, existing peers get
    refreshed. The reaper handles trust/eviction independently.
    """

    def __init__(self) -> None:
        self._last_scan: float = 0.0
        self._known_repos: set[str] = set()

    @property
    def name(self) -> str:
        return "genesis_discovery"

    @property
    def phase(self) -> str:
        return GENESIS

    @property
    def priority(self) -> int:
        return 20  # After any future context-validation hooks

    def should_run(self, ctx: PhaseContext) -> bool:
        # Don't run in test environments (no real GitHub API access)
        if "pytest" in __import__("sys").modules:
            return False
        return (time.time() - self._last_scan) >= _MIN_SCAN_INTERVAL_S

    def execute(self, ctx: PhaseContext) -> None:
        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is None:
            return

        discovered: dict[str, dict] = {}  # repo_id → {repo, capabilities, ...}

        # Source 1: agent-world registry (authoritative)
        world_peers = _discover_from_world_registry()
        discovered.update(world_peers)

        # Source 2: GitHub topic scan (open discovery)
        topic_peers = _discover_from_github_topics()
        for repo_id, info in topic_peers.items():
            if repo_id not in discovered:
                discovered[repo_id] = info

        # Source 3: GitHub org repos with federation descriptors
        org_peers = _discover_from_org_repos()
        for repo_id, info in org_peers.items():
            if repo_id not in discovered:
                discovered[repo_id] = info

        # Register only NEW peers — never refresh existing heartbeats.
        # Existing peers must send their OWN heartbeats via federation.
        # If we refresh timestamps here, the reaper can never detect
        # dead peers and the healer will never trigger.
        new_count = 0
        for repo_id, info in discovered.items():
            if repo_id in self._known_repos:
                continue  # Already known — don't touch its heartbeat

            caps = tuple(info.get("capabilities", []))
            fingerprint = info.get("repo", repo_id)
            reaper.record_heartbeat(
                agent_id=repo_id,
                timestamp=time.time(),
                source="genesis_discovery",
                capabilities=caps,
                fingerprint=fingerprint,
            )
            new_count += 1
            self._known_repos.add(repo_id)

        if new_count:
            logger.info("GENESIS: discovered %d new peers (%d total)", new_count, len(discovered))

        self._last_scan = time.time()
        ctx.operations.append(f"genesis_discovery:peers={len(discovered)},new={new_count}")


def _discover_from_world_registry() -> dict[str, dict]:
    """Read agent-world/config/world_registry.yaml via GitHub API.

    Returns dict of repo_id → {repo, capabilities, status}.
    """
    peers: dict[str, dict] = {}

    # Fetch world_registry.yaml from agent-world repo
    raw = _gh(["api", "repos/kimeisele/agent-world/contents/config/world_registry.yaml",
               "--jq", ".content"])
    if not raw:
        return peers

    try:
        import base64
        content = base64.b64decode(raw.strip()).decode("utf-8")
    except Exception:
        return peers

    # Parse YAML (simple line-based parser — no PyYAML dependency required)
    current_city: dict = {}
    in_capabilities = False

    for line in content.splitlines():
        stripped = line.strip()

        if stripped.startswith("- city_id:"):
            if current_city.get("city_id"):
                peers[current_city["city_id"]] = current_city
            current_city = {"city_id": stripped.split(":", 1)[1].strip()}
            in_capabilities = False

        elif stripped.startswith("repo:") and current_city:
            current_city["repo"] = stripped.split(":", 1)[1].strip()

        elif stripped.startswith("status:") and current_city:
            current_city["status"] = stripped.split(":", 1)[1].strip()

        elif stripped == "capabilities:":
            in_capabilities = True
            current_city.setdefault("capabilities", [])

        elif in_capabilities and stripped.startswith("- "):
            current_city.setdefault("capabilities", []).append(stripped[2:].strip())

        elif not stripped.startswith("-") and ":" in stripped:
            in_capabilities = False

    # Don't forget last city
    if current_city.get("city_id"):
        peers[current_city["city_id"]] = current_city

    logger.debug("World registry: %d cities", len(peers))
    return peers


def _discover_from_github_topics() -> dict[str, dict]:
    """Find repos with topic 'agent-federation-node' via GitHub search."""
    peers: dict[str, dict] = {}

    raw = _gh(["search", "repos", "--topic", "agent-federation-node",
               "--owner", "kimeisele", "--json", "name,description"])
    if not raw:
        return peers

    try:
        repos = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return peers

    for repo in repos:
        name = repo.get("name", "")
        if name:
            peers[name] = {
                "repo": f"kimeisele/{name}",
                "capabilities": [],
                "source": "github_topic",
            }

    logger.debug("GitHub topics: %d repos", len(peers))
    return peers


def _discover_from_org_repos() -> dict[str, dict]:
    """Scan org repos for .well-known/agent-federation.json descriptors."""
    peers: dict[str, dict] = {}

    # List all repos in the org
    raw = _gh(["repo", "list", "kimeisele", "--json", "name", "--limit", "100"])
    if not raw:
        return peers

    try:
        repos = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return peers

    for repo in repos:
        name = repo.get("name", "")
        if not name or name == "steward":  # Skip self
            continue

        # Check for federation descriptor
        descriptor_raw = _gh([
            "api", f"repos/kimeisele/{name}/contents/.well-known/agent-federation.json",
            "--jq", ".content",
        ])
        if not descriptor_raw:
            continue

        try:
            import base64
            descriptor = json.loads(base64.b64decode(descriptor_raw.strip()))
            if descriptor.get("status") == "active":
                caps = descriptor.get("capabilities", [])
                if isinstance(caps, list):
                    peers[name] = {
                        "repo": f"kimeisele/{name}",
                        "capabilities": caps,
                        "source": "federation_descriptor",
                        "owner_boundary": descriptor.get("owner_boundary", ""),
                    }
        except (json.JSONDecodeError, Exception):
            continue

    logger.debug("Org scan: %d federation repos", len(peers))
    return peers
