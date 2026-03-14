"""
GENESIS Phase Hook — Active federation peer discovery.

GENESIS = origin/creation. The agent's discovery cycle:
scan federation registry → discover peers → register heartbeats in reaper.

Discovery sources (in priority order):
1. agent-world registry (world_registry.yaml) — authoritative
2. GitHub topic scan (agent-federation-node) — open discovery
3. GitHub org scan (owner from peer.json) — fallback

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

# Cached federation identity (loaded from peer.json once)
_CACHED_OWNER: str | None = None


def _get_federation_owner() -> str:
    """Get the GitHub owner from the nadi peer descriptor (peer.json).

    This is the federation-protocol-compliant way to know who we are.
    No hardcoded strings — the peer.json IS the identity.
    """
    global _CACHED_OWNER
    if _CACHED_OWNER is not None:
        return _CACHED_OWNER

    peer_path = Path("data/federation/peer.json")
    if peer_path.exists():
        try:
            data = json.loads(peer_path.read_text())
            repo = data.get("identity", {}).get("repo", "")
            if "/" in repo:
                _CACHED_OWNER = repo.split("/")[0]
                return _CACHED_OWNER
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("peer.json parse failed: %s", e)

    # Fallback: try .well-known descriptor
    descriptor_path = Path(".well-known/agent-federation.json")
    if descriptor_path.exists():
        try:
            data = json.loads(descriptor_path.read_text())
            # repo_id doesn't have owner, but we can try gh api
            pass
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("descriptor parse failed: %s", e)

    _CACHED_OWNER = ""
    return _CACHED_OWNER


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

        # Source 3: GitHub org repos — only check repos already known
        # from authoritative sources (world registry, topics).
        # No hardcoded prefix heuristics — the registry IS the truth.
        known_names = set(discovered.keys())
        org_peers = _discover_from_org_repos(federation_members=known_names)
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
    owner = _get_federation_owner()
    raw = _gh(["api", f"repos/{owner}/agent-world/contents/config/world_registry.yaml",
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
               "--owner", f"{_get_federation_owner()}", "--json", "name,description"])
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
                "repo": f"{_get_federation_owner()}/{name}",
                "capabilities": [],
                "source": "github_topic",
            }

    logger.debug("GitHub topics: %d repos", len(peers))
    return peers


def _discover_from_org_repos(
    federation_members: set[str] | None = None,
) -> dict[str, dict]:
    """Scan org repos for federation descriptors.

    If federation_members is provided, also checks those specific repos
    even if they lack descriptors (so the healer can onboard them).
    No hardcoded prefix heuristics — the registry is the source of truth.
    """
    peers: dict[str, dict] = {}
    federation_members = federation_members or set()

    raw = _gh(["repo", "list", f"{_get_federation_owner()}", "--json", "name", "--limit", "100"])
    if not raw:
        return peers

    try:
        repos = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return peers

    _SKIP = {"steward"}  # Self

    for repo in repos:
        name = repo.get("name", "")
        if not name or name in _SKIP:
            continue

        # Check for federation descriptor
        descriptor_raw = _gh([
            "api", f"repos/{_get_federation_owner()}/{name}/contents/.well-known/agent-federation.json",
            "--jq", ".content",
        ])

        if descriptor_raw:
            try:
                import base64
                descriptor = json.loads(base64.b64decode(descriptor_raw.strip()))
                if descriptor.get("status") == "active":
                    caps = descriptor.get("capabilities", [])
                    if isinstance(caps, list):
                        peers[name] = {
                            "repo": f"{_get_federation_owner()}/{name}",
                            "capabilities": caps,
                            "source": "federation_descriptor",
                            "owner_boundary": descriptor.get("owner_boundary", ""),
                        }
                        continue
            except (json.JSONDecodeError, Exception) as e:
                logger.debug("Descriptor parse failed for %s: %s", name, e)

        # No descriptor — only register if authoritative sources say it's a member
        if name in federation_members:
            peers[name] = {
                "repo": f"{_get_federation_owner()}/{name}",
                "capabilities": [],
                "source": "org_scan_unregistered",
            }

    logger.debug("Org scan: %d repos", len(peers))
    return peers
