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


_GH_CACHE: dict[str, tuple[float, str | None]] = {}
_GH_CACHE_TTL = 300.0  # 5 min cache
_GH_CALL_COUNT = 0
_GH_CALL_BUDGET = 50  # MAX 50 real API calls per session — CBR


def _gh(args: list[str], cwd: str | None = None) -> str | None:
    """Run gh CLI command with CBR budget + cache.

    Hard budget: max 50 API calls per session. After that, cache-only.
    Cache TTL: 5 minutes. Same query within TTL → no API call.
    """
    global _GH_CALL_COUNT
    cache_key = " ".join(args)
    now = time.time()

    # Cache hit → free
    if cache_key in _GH_CACHE:
        cached_time, cached_result = _GH_CACHE[cache_key]
        if (now - cached_time) < _GH_CACHE_TTL:
            return cached_result

    # Budget exhausted → return cached (even stale) or None
    if _GH_CALL_COUNT >= _GH_CALL_BUDGET:
        stale = _GH_CACHE.get(cache_key)
        if stale:
            return stale[1]
        logger.warning(
            "GH API budget exhausted (%d/%d) — dropping call: %s", _GH_CALL_COUNT, _GH_CALL_BUDGET, cache_key[:60]
        )
        return None

    try:
        r = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT,
            cwd=cwd,
        )
        _GH_CALL_COUNT += 1
        result = r.stdout if r.returncode == 0 else None
        _GH_CACHE[cache_key] = (now, result)
        return result
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
        import os
        import shutil

        # Skip if gh CLI not available (CI without GitHub token, tests, etc.)
        if shutil.which("gh") is None:
            return False
        # Skip if explicitly disabled
        if os.environ.get("STEWARD_DISABLE_DISCOVERY"):
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

        # Apply world policy compliance checks (trust penalties)
        violations = _check_policy_compliance(discovered, reaper)
        if violations:
            logger.info("GENESIS: %d policy violations detected", len(violations))

        self._last_scan = time.time()
        ctx.operations.append(f"genesis_discovery:peers={len(discovered)},new={new_count},violations={len(violations)}")


def _check_policy_compliance(
    discovered: dict[str, dict],
    reaper: object,
) -> list[str]:
    """Check discovered peers against world policies. Apply trust penalties.

    Reads policies from agent-world. For each enforceable policy,
    checks compliance and adjusts trust in the reaper.
    """
    import base64

    import yaml

    violations: list[str] = []
    owner = _get_federation_owner()

    # Load policies from agent-world
    raw = _gh(["api", f"repos/{owner}/agent-world/contents/config/world_policies.yaml", "--jq", ".content"])
    if not raw:
        return violations

    try:
        content = base64.b64decode(raw.strip()).decode("utf-8")
        data = yaml.safe_load(content)
    except Exception as e:
        logger.debug("World policies parse failed: %s", e)
        return violations

    policies = data.get("policies") or []
    trust_policies = [p for p in policies if p.get("enforcement") == "trust_penalty"]

    if not trust_policies:
        return violations

    for repo_id, info in discovered.items():
        repo_full = info.get("repo", "")
        if not repo_full:
            continue

        peer = reaper.get_peer(repo_id) if hasattr(reaper, "get_peer") else None
        if peer is None:
            continue

        for policy in trust_policies:
            policy_id = policy.get("id", "")
            penalty = float(policy.get("trust_penalty", 0))

            if policy_id == "federation_descriptor_required":
                # Check if repo has .well-known/agent-federation.json
                if info.get("source") == "org_scan_unregistered":
                    # No descriptor — apply penalty
                    old_trust = peer.trust
                    peer.trust = max(0.0, peer.trust - penalty)
                    violations.append(f"{repo_id}: no descriptor (trust {old_trust:.2f} → {peer.trust:.2f})")
                    logger.warning(
                        "Policy %s: %s lacks federation descriptor (trust -%.1f)", policy_id, repo_id, penalty
                    )

            elif policy_id == "federation_ci_required":
                # Check if repo has CI on pull_request
                ci_raw = _gh(["api", f"repos/{repo_full}/contents/.github/workflows", "--jq", ".[].name"])
                has_ci = ci_raw is not None and ci_raw.strip()
                if not has_ci:
                    old_trust = peer.trust
                    peer.trust = max(0.0, peer.trust - penalty)
                    violations.append(f"{repo_id}: no CI workflows (trust {old_trust:.2f} → {peer.trust:.2f})")
                    logger.warning("Policy %s: %s has no CI (trust -%.1f)", policy_id, repo_id, penalty)

    return violations


def _discover_from_world_registry() -> dict[str, dict]:
    """Read agent-world/config/world_registry.yaml via GitHub API.

    Parses both cities and agents sections — all federation nodes.
    Returns dict of node_id → {repo, capabilities, source}.
    """
    import base64

    import yaml

    peers: dict[str, dict] = {}

    owner = _get_federation_owner()
    raw = _gh(["api", f"repos/{owner}/agent-world/contents/config/world_registry.yaml", "--jq", ".content"])
    if not raw:
        return peers

    try:
        content = base64.b64decode(raw.strip()).decode("utf-8")
        data = yaml.safe_load(content)
    except Exception as e:
        logger.debug("World registry parse failed: %s", e)
        return peers

    if not isinstance(data, dict):
        return peers

    # Parse cities
    for city in data.get("cities") or []:
        cid = city.get("city_id", "")
        if cid:
            peers[cid] = {
                "repo": city.get("repo", ""),
                "capabilities": city.get("capabilities", []),
                "source": "world_registry_city",
            }

    # Parse agents
    for agent in data.get("agents") or []:
        aid = agent.get("agent_id", "")
        if aid and aid not in peers:  # cities take priority
            peers[aid] = {
                "repo": agent.get("repo", ""),
                "capabilities": agent.get("capabilities", []),
                "source": "world_registry_agent",
            }

    logger.debug(
        "World registry: %d nodes (%d cities, %d agents)",
        len(peers),
        len(data.get("cities") or []),
        len(data.get("agents") or []),
    )
    return peers


def _discover_from_github_topics() -> dict[str, dict]:
    """Find repos with topic 'agent-federation-node' via GitHub search."""
    peers: dict[str, dict] = {}

    raw = _gh(
        [
            "search",
            "repos",
            "--topic",
            "agent-federation-node",
            "--owner",
            f"{_get_federation_owner()}",
            "--json",
            "name,description",
        ]
    )
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
        descriptor_raw = _gh(
            [
                "api",
                f"repos/{_get_federation_owner()}/{name}/contents/.well-known/agent-federation.json",
                "--jq",
                ".content",
            ]
        )

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
