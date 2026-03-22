"""
A2A Peer Discovery — Find federation peers via Agent Cards.

Scans GitHub repos for /.well-known/agent.json (A2A standard) and
/.well-known/agent-federation.json (Steward custom). Discovered peers
are registered with the HeartbeatReaper as ALIVE with initial trust.

Discovery sources:
    1. Configured peer list (data/federation/known_peers.json)
    2. GitHub org scan (all repos in kimeisele/ with agent cards)
    3. Inbound heartbeats (existing Reaper mechanism)

Integration:
    GENESIS phase: discovery.scan() — discover new peers
    DHARMA phase: reaper manages peer lifecycle (existing)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("STEWARD.A2A.DISCOVERY")

GITHUB_API = "https://api.github.com"
DEFAULT_ORG = "kimeisele"
DISCOVERY_INTERVAL_S = 300  # 5 minutes between scans
INITIAL_PEER_TRUST = 0.5  # New peers start with moderate trust


@dataclass
class DiscoveredPeer:
    """A peer found via A2A Agent Card discovery."""

    agent_id: str
    repo: str
    name: str
    description: str
    skills: list[str]
    url: str
    card_type: str  # "a2a" or "steward"
    discovered_at: float = field(default_factory=time.time)
    capabilities: tuple[str, ...] = ()
    node_role: str = ""
    layer: str = ""


class A2APeerDiscovery:
    """Discover federation peers by scanning for A2A Agent Cards on GitHub.

    Usage:
        discovery = A2APeerDiscovery(reaper=reaper)
        new_peers = discovery.scan()  # Returns list of newly discovered peers
    """

    def __init__(
        self,
        reaper: object | None = None,
        org: str = DEFAULT_ORG,
        known_peers_path: str | Path | None = None,
    ) -> None:
        self._reaper = reaper
        self._org = org
        self._known_peers_path = (
            Path(known_peers_path) if known_peers_path else Path("data/federation/known_peers.json")
        )
        self._token = self._load_token()
        self._last_scan: float = 0.0
        self._discovered: dict[str, DiscoveredPeer] = {}
        self._scan_count: int = 0
        self._errors: int = 0

    @property
    def available(self) -> bool:
        return bool(self._token)

    def _load_token(self) -> str:
        token = os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")
        if not token:
            token_file = Path.home() / ".config" / "gh_token"
            if token_file.exists():
                token = token_file.read_text().strip()
        return token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"token {self._token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "steward-a2a-discovery/1.0",
        }

    # ── Main Scan ──────────────────────────────────────────────────

    def scan(self, known_repos: list[str] | None = None) -> list[DiscoveredPeer]:
        """Scan for new federation peers. Returns newly discovered peers.

        Throttled to DISCOVERY_INTERVAL_S between scans.

        Args:
            known_repos: Optional pre-fetched repo list from GenesisDiscoveryHook.
                When provided, skips the expensive org API call and only checks
                these repos for agent cards. This prevents duplicate API calls
                since GenesisDiscovery already scanned the org.
        """
        if not self._token:
            return []

        now = time.monotonic()
        if (now - self._last_scan) < DISCOVERY_INTERVAL_S:
            return []

        self._last_scan = now
        self._scan_count += 1
        new_peers: list[DiscoveredPeer] = []

        # 1. Scan configured known peers
        for peer in self._scan_known_peers():
            if peer.agent_id not in self._discovered:
                self._discovered[peer.agent_id] = peer
                new_peers.append(peer)

        # 2. Scan for agent cards — use pre-fetched repo list if available
        #    (avoids duplicate org API call when GenesisDiscovery already scanned)
        if known_repos is not None:
            for repo in known_repos:
                if not repo or repo == f"{self._org}/steward":
                    continue
                peer = self._fetch_agent_card(repo)
                if peer is not None and peer.agent_id not in self._discovered:
                    self._discovered[peer.agent_id] = peer
                    new_peers.append(peer)
        else:
            for peer in self._scan_org_repos():
                if peer.agent_id not in self._discovered:
                    self._discovered[peer.agent_id] = peer
                    new_peers.append(peer)

        # 3. Register new peers with Reaper
        for peer in new_peers:
            self._register_peer(peer)

        if new_peers:
            logger.info(
                "A2A DISCOVERY: found %d new peers (total known: %d)",
                len(new_peers),
                len(self._discovered),
            )

        return new_peers

    # ── Known Peers (configured list) ──────────────────────────────

    def _scan_known_peers(self) -> list[DiscoveredPeer]:
        """Read data/federation/known_peers.json and check each for agent cards."""
        if not self._known_peers_path.exists():
            return []

        try:
            data = json.loads(self._known_peers_path.read_text())
            repos = data if isinstance(data, list) else data.get("peers", [])
        except (json.JSONDecodeError, OSError):
            return []

        peers: list[DiscoveredPeer] = []
        for entry in repos:
            repo = entry if isinstance(entry, str) else entry.get("repo", "")
            if not repo:
                continue
            peer = self._fetch_agent_card(repo)
            if peer is not None:
                peers.append(peer)

        return peers

    # ── Org Scan ───────────────────────────────────────────────────

    def _scan_org_repos(self) -> list[DiscoveredPeer]:
        """Scan all repos in the org for /.well-known/agent.json."""
        import urllib.request

        url = f"{GITHUB_API}/orgs/{self._org}/repos?per_page=100&sort=pushed"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                repos = json.loads(resp.read())
        except Exception as e:
            logger.debug("Org scan failed: %s", e)
            self._errors += 1
            return []

        peers: list[DiscoveredPeer] = []
        for repo_data in repos:
            full_name = repo_data.get("full_name", "")
            if not full_name or full_name == f"{self._org}/steward":
                continue  # Skip self

            peer = self._fetch_agent_card(full_name)
            if peer is not None:
                peers.append(peer)

        return peers

    # ── Fetch Agent Card ───────────────────────────────────────────

    def _fetch_agent_card(self, repo: str) -> DiscoveredPeer | None:
        """Try to fetch A2A agent card, then Steward federation card."""
        import base64
        import urllib.request

        # Try A2A standard first
        for path, card_type in [
            (".well-known/agent.json", "a2a"),
            (".well-known/agent-federation.json", "steward"),
        ]:
            url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
            req = urllib.request.Request(url, headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                    content = json.loads(base64.b64decode(data["content"]).decode())
                    return self._parse_agent_card(repo, content, card_type)
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                continue

        return None

    def _parse_agent_card(self, repo: str, card: dict, card_type: str) -> DiscoveredPeer:
        """Parse an agent card (A2A or Steward format) into DiscoveredPeer."""
        agent_id = repo.split("/")[-1] if "/" in repo else repo
        if card_type == "a2a":
            skills = [s.get("id", "") for s in card.get("skills", [])]
            federation = card.get("federation", {})
            return DiscoveredPeer(
                agent_id=agent_id,
                repo=repo,
                name=card.get("name", agent_id),
                description=card.get("description", ""),
                skills=skills,
                url=card.get("url", f"https://github.com/{repo}"),
                card_type="a2a",
                capabilities=tuple(skills),
                node_role=str(federation.get("node_role", card.get("role", ""))),
                layer=str(card.get("layer", federation.get("node_topic", ""))),
            )
        else:
            # Steward format
            capabilities = card.get("capabilities", [])
            return DiscoveredPeer(
                agent_id=agent_id,
                repo=repo,
                name=card.get("display_name", agent_id),
                description=f"Steward peer: {', '.join(capabilities[:3])}",
                skills=capabilities,
                url=f"https://github.com/{repo}",
                card_type="steward",
                capabilities=tuple(capabilities),
                node_role=str(card.get("role", "")),
                layer=str(card.get("layer", "")),
            )

    def _is_liveness_monitored(self, peer: DiscoveredPeer) -> bool:
        role = (peer.node_role or "").strip().lower()
        layer = (peer.layer or "").strip().lower()
        if role == "city_runtime":
            return True
        if role in {"hub", "internet", "operator", "template", "agent_template_relay"}:
            return False
        if layer in {"internet", "agent-federation-template"}:
            return False
        return False

    # ── Register with Reaper ───────────────────────────────────────

    def _register_peer(self, peer: DiscoveredPeer) -> None:
        """Register a discovered peer with the HeartbeatReaper."""
        if self._reaper is None:
            return

        if not self._is_liveness_monitored(peer):
            logger.info(
                "A2A DISCOVERY: skipped liveness registration for %s (role=%s layer=%s)",
                peer.agent_id,
                peer.node_role or "?",
                peer.layer or "?",
            )
            return

        try:
            self._reaper.record_heartbeat(
                peer.agent_id,
                timestamp=time.time(),
                source="a2a_discovery",
                capabilities=peer.capabilities,
                fingerprint=f"{peer.card_type}:{peer.repo}",
            )
            logger.info(
                "A2A DISCOVERY: registered peer %s (%s, %d skills)",
                peer.agent_id,
                peer.card_type,
                len(peer.skills),
            )
        except Exception as e:
            logger.warning("A2A DISCOVERY: failed to register %s: %s", peer.agent_id, e)
            self._errors += 1

    # ── Persistence ────────────────────────────────────────────────

    def save_discovered(self, path: Path | None = None) -> None:
        """Save discovered peers to JSON for cross-session persistence."""
        save_path = path or self._known_peers_path.parent / "discovered_peers.json"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "agent_id": p.agent_id,
                "repo": p.repo,
                "name": p.name,
                "card_type": p.card_type,
                "skills": p.skills,
                "discovered_at": p.discovered_at,
            }
            for p in self._discovered.values()
        ]
        tmp = save_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(save_path)

    def load_discovered(self, path: Path | None = None) -> int:
        """Load previously discovered peers. Returns count loaded."""
        load_path = path or self._known_peers_path.parent / "discovered_peers.json"
        if not load_path.exists():
            return 0
        try:
            data = json.loads(load_path.read_text())
            for entry in data:
                agent_id = entry.get("agent_id", "")
                if agent_id and agent_id not in self._discovered:
                    self._discovered[agent_id] = DiscoveredPeer(
                        agent_id=agent_id,
                        repo=entry.get("repo", ""),
                        name=entry.get("name", agent_id),
                        description="",
                        skills=entry.get("skills", []),
                        url=f"https://github.com/{entry.get('repo', '')}",
                        card_type=entry.get("card_type", "unknown"),
                        discovered_at=entry.get("discovered_at", 0),
                        capabilities=tuple(entry.get("skills", [])),
                    )
            return len(data)
        except (json.JSONDecodeError, OSError):
            return 0

    # ── Stats ──────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "available": self.available,
            "discovered_peers": len(self._discovered),
            "scan_count": self._scan_count,
            "errors": self._errors,
            "last_scan": self._last_scan,
            "by_type": {
                "a2a": sum(1 for p in self._discovered.values() if p.card_type == "a2a"),
                "steward": sum(1 for p in self._discovered.values() if p.card_type == "steward"),
            },
        }
