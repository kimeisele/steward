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
from steward.services import SVC_A2A_DISCOVERY, SVC_REAPER, SVC_TASK_MANAGER
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
            repo = data.get("repo_id", "")
            if "/" in repo:
                _CACHED_OWNER = repo.split("/")[0]
                return _CACHED_OWNER
        except (json.JSONDecodeError, OSError) as e:
            logger.debug("descriptor parse failed: %s", e)

    _CACHED_OWNER = ""
    return _CACHED_OWNER


_GH_CACHE: dict[str, tuple[float, str | None]] = {}
_GH_CACHE_TTL = 300.0  # 5 min response cache
_gh_quota = None  # CBR quota — lazy init


def _get_gh_quota():
    """CBR quota for GitHub API — same OperationalQuota as LLM provider."""
    global _gh_quota
    if _gh_quota is None:
        from vibe_core.runtime.quota_manager import OperationalQuota, QuotaLimits

        _gh_quota = OperationalQuota(
            limits=QuotaLimits(
                requests_per_minute=10,  # 10 RPM rolling window
                tokens_per_minute=999999,
                cost_per_hour_usd=999.0,
                cost_per_day_usd=999.0,
            )
        )
    return _gh_quota


def _gh(args: list[str], cwd: str | None = None) -> str | None:
    """Run gh CLI command with CBR quota (OperationalQuota) + response cache.

    Same rate-limiting system as ProviderChamber uses for LLM calls.
    10 RPM rolling window. 5-min response cache. Stale fallback when throttled.
    """
    cache_key = " ".join(args)
    now = time.time()

    if cache_key in _GH_CACHE:
        cached_time, cached_result = _GH_CACHE[cache_key]
        if (now - cached_time) < _GH_CACHE_TTL:
            return cached_result

    quota = _get_gh_quota()
    try:
        quota.check_before_request(estimated_tokens=1, operation=f"gh:{cache_key[:40]}")
    except Exception as e:
        logger.debug("gh quota check failed, using stale cache: %s", e)
        stale = _GH_CACHE.get(cache_key)
        return stale[1] if stale else None

    try:
        r = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT,
            cwd=cwd,
        )
        quota.record_request(tokens_used=1, cost_usd=0.0, operation=f"gh:{cache_key[:40]}")
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

        # Discover and resurrect peers. Two paths:
        # 1. NEW peers: register with expired lease so they trigger ALIVE→SUSPECT on first reap()
        # 2. LOADED peers (already in reaper._peers): record heartbeat to resurrect them to ALIVE
        #    This prevents false evictions while honoring the federation-first principle
        #    (inbound messages remain the primary heartbeat source).
        new_count = 0
        resurrected_count = 0

        for repo_id, info in discovered.items():
            if repo_id in self._known_repos:
                continue  # Discovered within THIS session — skip duplicate

            caps = tuple(info.get("capabilities", []))
            fingerprint = info.get("repo", repo_id)

            # Path 2: LOADED peer — resurrect to ALIVE if discovered again
            if repo_id in reaper._peers:
                reaper.record_heartbeat(
                    agent_id=repo_id,
                    source="genesis_discovery_resurrection",
                    capabilities=caps,
                    fingerprint=fingerprint,
                )
                resurrected_count += 1
                self._known_repos.add(repo_id)
                continue

            # Path 1: NEW peer — register with expired lease for controlled ALIVE→SUSPECT
            from steward.reaper import DEFAULT_LEASE_TTL_S

            source_type = info.get("source", "")
            is_world_registry = source_type in ("world_registry_agent", "world_registry_city")
            heartbeat_timestamp = time.time() - DEFAULT_LEASE_TTL_S - 1.0 if is_world_registry else time.time()

            reaper.record_heartbeat(
                agent_id=repo_id,
                timestamp=heartbeat_timestamp,
                source="genesis_discovery",
                capabilities=caps,
                fingerprint=fingerprint,
            )
            new_count += 1
            self._known_repos.add(repo_id)

        if new_count or resurrected_count:
            logger.info(
                "GENESIS: discovered %d new, resurrected %d loaded peers (%d total)",
                new_count,
                resurrected_count,
                len(discovered),
            )

        # Schedule immediate healing for unregistered peers (missing federation descriptor).
        # Don't wait for heartbeat TTL decay — heal on first discovery.
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is not None:
            from vibe_core.task_types import TaskStatus

            active_titles = {
                getattr(t, "title", "")
                for s in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)
                for t in task_mgr.list_tasks(status=s)
            }
            heal_scheduled = 0
            for repo_id, info in discovered.items():
                if info.get("source") != "org_scan_unregistered":
                    continue
                task_title = f"[HEAL_REPO] Onboard {repo_id} — missing federation descriptor"
                if task_title not in active_titles:
                    task_mgr.add_task(title=task_title, priority=70, description=info.get("repo", repo_id))
                    heal_scheduled += 1
            if heal_scheduled:
                logger.info("GENESIS: scheduled %d [HEAL_REPO] tasks for unregistered peers", heal_scheduled)

        # Apply world policy compliance checks (trust penalties)
        violations = _check_policy_compliance(discovered, reaper)
        if violations:
            logger.info("GENESIS: %d policy violations detected", len(violations))

        # Source 4: A2A Agent Card discovery (standard A2A protocol)
        # Pass known repos to avoid duplicate org API call — GenesisDiscovery
        # already scanned the org. A2A discovery reuses the repo list.
        a2a_discovery = ServiceRegistry.get(SVC_A2A_DISCOVERY)
        a2a_new = 0
        if a2a_discovery is not None:
            owner = _get_federation_owner()
            known_repos = [f"{owner}/{name}" for name in discovered.keys() if name]
            a2a_peers = a2a_discovery.scan(known_repos=known_repos)
            a2a_new = len(a2a_peers)
            if a2a_new:
                logger.info("GENESIS: A2A discovery found %d new peers", a2a_new)

        self._last_scan = time.time()
        ctx.operations.append(
            f"genesis_discovery:peers={len(discovered)},new={new_count},a2a_new={a2a_new},violations={len(violations)}"
        )


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
    """Check known federation members for descriptors.

    Only checks repos already identified by authoritative sources (world
    registry, GitHub topics). This avoids N+1 API calls scanning ALL org
    repos — with a 10 RPM quota, scanning 100 repos is impossible.

    Repos with active descriptors get full capability info.
    Known members without descriptors get registered as "unregistered"
    so the healer can onboard them.
    """
    import base64

    peers: dict[str, dict] = {}
    federation_members = federation_members or set()

    if not federation_members:
        return peers  # Nothing to check — don't waste API calls

    _SKIP = {"steward"}  # Self
    owner = _get_federation_owner()

    for name in federation_members:
        if name in _SKIP or not name:
            continue

        # Check for federation descriptor (1 API call per known member)
        descriptor_raw = _gh(
            [
                "api",
                f"repos/{owner}/{name}/contents/.well-known/agent-federation.json",
                "--jq",
                ".content",
            ]
        )

        if descriptor_raw:
            try:
                descriptor = json.loads(base64.b64decode(descriptor_raw.strip()))
                if descriptor.get("status") == "active":
                    caps = descriptor.get("capabilities", [])
                    if isinstance(caps, list):
                        peers[name] = {
                            "repo": f"{owner}/{name}",
                            "capabilities": caps,
                            "source": "federation_descriptor",
                            "owner_boundary": descriptor.get("owner_boundary", ""),
                        }
                        continue
            except Exception as e:
                logger.debug("Descriptor parse failed for %s: %s", name, e)

        # No descriptor — register as unregistered for healer onboarding
        peers[name] = {
            "repo": f"{owner}/{name}",
            "capabilities": [],
            "source": "org_scan_unregistered",
        }

    logger.debug("Org scan: %d repos (from %d known members)", len(peers), len(federation_members))
    return peers


class GenesisProvisioningHook(BasePhaseHook):
    """Auto-provision NODE_PRIVATE_KEY secret for newly discovered federation nodes.

    Steward-as-Provisioner pattern:
    1. Discover new nodes via GenesisDiscoveryHook (runs first, priority 20)
    2. For each node WITHOUT NODE_PRIVATE_KEY: generate Ed25519 keypair
    3. Encrypt private key via GitHub sealed box + POST to secrets API
    4. Register public key in verified_agents.json
    5. Idempotent: skip if secret already exists
    6. Owner-whitelist: only provision repos owned by FEDERATION_OWNER

    Priority 40: runs after GenesisDiscoveryHook (20) in same GENESIS phase.
    """

    @property
    def name(self) -> str:
        return "genesis_provisioning"

    @property
    def phase(self) -> str:
        return GENESIS

    @property
    def priority(self) -> int:
        return 40

    def execute(self, ctx: PhaseContext) -> None:
        logger.info("PROVISIONER: execute() called")
        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is None:
            logger.warning("PROVISIONER: reaper service not available, skipping")
            return

        owner = _get_federation_owner()
        if not owner:
            logger.warning("PROVISIONER: no federation owner configured, skipping")
            return
        logger.info("PROVISIONER: owner=%s, checking peers...", owner)

        # Provision all peers under owner/ that lack NODE_PRIVATE_KEY
        # Skip crypto IDs (ag_xxxx) — those are transport signatures not repos
        all_peers = (list(reaper.alive_peers()) +
                     list(reaper.suspect_peers()) +
                     list(reaper.dead_peers()))
        seen = set()
        for peer in all_peers:
            agent_id = str(getattr(peer, "agent_id", ""))
            if not agent_id or agent_id.startswith("ag_") or agent_id in seen:
                continue
            seen.add(agent_id)
            repo = f"{owner}/{agent_id}"
            self._provision_if_needed(repo, agent_id)

    def _provision_if_needed(self, repo: str, agent_id: str) -> None:
        """Check if NODE_PRIVATE_KEY exists; if not, generate and set it."""
        import subprocess as _sp
        import json as _json
        import hashlib as _hashlib

        # 1. Idempotency check: does secret already exist?
        check = _sp.run(
            ["gh", "api", f"repos/{repo}/actions/secrets",
             "--jq", '.secrets[] | select(.name=="NODE_PRIVATE_KEY") | .name'],
            capture_output=True, text=True, timeout=10
        )
        if "NODE_PRIVATE_KEY" in check.stdout:
            logger.debug("PROVISIONER: %s already has NODE_PRIVATE_KEY", repo)
            return

        logger.info("PROVISIONER: provisioning NODE_PRIVATE_KEY for %s", repo)

        # 2. Generate Ed25519 keypair
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

            priv = Ed25519PrivateKey.generate()
            pub = priv.public_key()
            priv_hex = priv.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            ).hex()
            pub_hex = pub.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            ).hex()
            node_id = "ag_" + _hashlib.sha256(pub_hex.encode()).hexdigest()[:16]
        except Exception as exc:
            logger.error("PROVISIONER: key generation failed for %s: %s", repo, exc)
            return

        secret_value = _json.dumps({
            "private_key": priv_hex,
            "public_key": pub_hex,
            "node_id": node_id,
        })

        # 3. Fetch repo public key for GitHub sealed box encryption
        try:
            pk_result = _sp.run(
                ["gh", "api", f"repos/{repo}/actions/secrets/public-key",
                 "--jq", "{key_id: .key_id, key: .key}"],
                capture_output=True, text=True, timeout=10
            )
            if pk_result.returncode != 0:
                logger.warning("PROVISIONER: cannot access %s secrets API", repo)
                return
            pk_data = _json.loads(pk_result.stdout)
        except Exception as exc:
            logger.error("PROVISIONER: public key fetch failed for %s: %s", repo, exc)
            return

        # 4. Encrypt with PyNaCl sealed box
        try:
            import base64 as _b64
            from nacl.public import PublicKey, SealedBox

            repo_pub_key = PublicKey(_b64.b64decode(pk_data["key"]))
            box = SealedBox(repo_pub_key)
            encrypted = _b64.b64encode(box.encrypt(secret_value.encode())).decode()
        except Exception as exc:
            logger.error("PROVISIONER: encryption failed for %s: %s", repo, exc)
            return

        # 5. Set secret via GitHub API
        try:
            api_input = _json.dumps({
                "encrypted_value": encrypted,
                "key_id": pk_data['key_id']
            })
            set_result = _sp.run(
                ["gh", "api", "-X", "PUT",
                 f"repos/{repo}/actions/secrets/NODE_PRIVATE_KEY",
                 "--input", "-"],
                input=api_input,
                capture_output=True, text=True, timeout=15
            )
            if set_result.returncode == 0:
                logger.info("PROVISIONER: ✅ NODE_PRIVATE_KEY set for %s (node_id=%s)", repo, node_id)
            else:
                logger.error("PROVISIONER: secret set failed for %s: %s", repo, set_result.stderr[:200])
                return
        except Exception as exc:
            logger.error("PROVISIONER: secret PUT failed for %s: %s", repo, exc)
            return

        logger.info("PROVISIONER: %s provisioned successfully with node_id=%s", repo, node_id)
