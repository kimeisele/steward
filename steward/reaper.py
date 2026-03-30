"""
HeartbeatReaper — Network Garbage Collection for Federation Peers.

Tracks heartbeats from federation agents and executes hard consequences
when peers die: lease expiration, trust degradation, slot reclamation.

3-Strike Eviction Protocol:
    ALIVE   → missed 1 lease window → SUSPECT  (trust -= decay)
    SUSPECT → missed 2nd window     → DEAD     (trust -= decay, slots reclaimable)
    DEAD    → missed 3rd window     → EVICTED  (trust = 0, purged from registry)

The reaper is SOURCE-AGNOSTIC — any code can call record_heartbeat().
Integration points:
    GENESIS phase: record heartbeats from discovered peers
    DHARMA  phase: reap() and execute consequences

Persistence: JSON file at .steward/peers.json (survives across sessions).
"""

from __future__ import annotations

import enum
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("STEWARD.REAPER")

# Default lease: 15 minutes (matches cron heartbeat interval)
DEFAULT_LEASE_TTL_S: float = 900.0

# Trust decay per missed window (0.2 = 5 strikes from 1.0 to 0.0)
DEFAULT_TRUST_DECAY: float = 0.2

# Initial trust for new peers
INITIAL_TRUST: float = 0.5

# Maximum peers tracked (prevent unbounded growth)
MAX_PEERS: int = 256


class PeerStatus(enum.Enum):
    """Federation peer lifecycle state."""

    ALIVE = "alive"
    SUSPECT = "suspect"  # missed 1 lease window
    DEAD = "dead"  # missed 2+ windows
    EVICTED = "evicted"  # trust = 0, purged


# Fingerprint stability threshold: N consecutive heartbeats with same
# fingerprint → trust escalation. Change → trust reset.
FINGERPRINT_STABLE_THRESHOLD: int = 5
FINGERPRINT_TRUST_BONUS: float = 0.05  # per stable heartbeat above threshold
FINGERPRINT_RESET_TRUST: float = 0.3  # trust after fingerprint change


@dataclass
class PeerRecord:
    """Tracked federation peer."""

    agent_id: str
    last_seen: float  # epoch timestamp
    trust: float = INITIAL_TRUST
    status: PeerStatus = PeerStatus.ALIVE
    heartbeat_count: int = 0
    first_seen: float = 0.0
    source: str = ""  # where heartbeats come from (e.g., "agent-internet", "nadi")
    capabilities: tuple[str, ...] = ()  # union of all capabilities announced
    fingerprint: str = ""  # identity fingerprint for fork detection
    fingerprint_stable_count: int = 0  # consecutive heartbeats with same fingerprint

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "last_seen": self.last_seen,
            "trust": self.trust,
            "status": self.status.value,
            "heartbeat_count": self.heartbeat_count,
            "first_seen": self.first_seen,
            "source": self.source,
            "capabilities": list(self.capabilities),
            "fingerprint": self.fingerprint,
            "fingerprint_stable_count": self.fingerprint_stable_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PeerRecord:
        caps = data.get("capabilities", [])
        return cls(
            agent_id=data["agent_id"],
            last_seen=data.get("last_seen", 0.0),
            trust=data.get("trust", INITIAL_TRUST),
            status=PeerStatus(data.get("status", "alive")),
            heartbeat_count=data.get("heartbeat_count", 0),
            first_seen=data.get("first_seen", 0.0),
            source=data.get("source", ""),
            capabilities=tuple(caps) if isinstance(caps, list) else (),
            fingerprint=data.get("fingerprint", ""),
            fingerprint_stable_count=data.get("fingerprint_stable_count", 0),
        )


@dataclass(frozen=True)
class ReaperConsequence:
    """A consequence executed by the reaper."""

    agent_id: str
    action: str  # "suspect", "dead", "evict", "trust_degrade"
    detail: str
    old_status: str
    new_status: str
    old_trust: float
    new_trust: float


# ── State Machine Transition Table ──────────────────────────────────
# O(1) dispatch: PeerStatus → (next_status, action, detail, flags)
# No if/elif chains. Add a state = add a dict entry.


@dataclass(frozen=True)
class _Transition:
    next_status: PeerStatus
    action: str
    detail_fn: object  # Callable[[float, float], str]
    decay: bool = True  # Apply trust decay (vs hard zero)
    evict: bool = False  # Remove from registry


_STATE_TRANSITIONS: dict[PeerStatus, _Transition] = {
    PeerStatus.ALIVE: _Transition(
        next_status=PeerStatus.SUSPECT,
        action="suspect",
        detail_fn=lambda age, ttl: f"Lease expired ({age:.0f}s > {ttl:.0f}s TTL)",
    ),
    PeerStatus.SUSPECT: _Transition(
        next_status=PeerStatus.DEAD,
        action="dead",
        detail_fn=lambda _age, _ttl: "Second missed window — slots reclaimable",
    ),
    PeerStatus.DEAD: _Transition(
        next_status=PeerStatus.EVICTED,
        action="evict",
        detail_fn=lambda _age, _ttl: "Third strike — evicted from federation",
        decay=False,
        evict=True,
    ),
}


@dataclass
class HeartbeatReaper:
    """Network garbage collector — tracks federation peer liveness.

    Source-agnostic: call record_heartbeat() from any discovery mechanism.
    Call reap() periodically to detect expired leases and execute consequences.

    Usage:
        reaper = HeartbeatReaper(lease_ttl_s=900)
        reaper.record_heartbeat("agent-city-mayor")
        # ... 15 minutes pass ...
        consequences = reaper.reap()
        for c in consequences:
            logger.warning("Reaper: %s → %s (%s)", c.agent_id, c.new_status, c.action)
    """

    lease_ttl_s: float = DEFAULT_LEASE_TTL_S
    trust_decay: float = DEFAULT_TRUST_DECAY
    _peers: dict[str, PeerRecord] = field(default_factory=dict)
    _total_reaps: int = field(default=0, init=False)
    _total_evictions: int = field(default=0, init=False)

    def record_heartbeat(
        self,
        agent_id: str,
        timestamp: float | None = None,
        source: str = "",
        capabilities: tuple[str, ...] | list[str] | None = None,
        fingerprint: str = "",
    ) -> PeerRecord:
        """Record a heartbeat from a federation peer.

        Creates new peer record if first contact.
        Refreshes lease and restores to ALIVE if previously SUSPECT/DEAD.
        Trust is NOT restored on heartbeat — it must be earned back gradually.
        Capabilities are merged (union) on each heartbeat.
        Fingerprint change resets trust (fork/impersonation detection).
        """
        now = timestamp if timestamp is not None else time.time()
        caps = tuple(capabilities) if capabilities else ()

        if agent_id in self._peers:
            peer = self._peers[agent_id]
            peer.last_seen = now
            peer.heartbeat_count += 1
            if source:
                peer.source = source

            # Merge capabilities (union, not replace)
            if caps:
                existing = set(peer.capabilities)
                existing.update(caps)
                peer.capabilities = tuple(sorted(existing))

            # Fingerprint tracking — fork detection
            if fingerprint:
                if peer.fingerprint and peer.fingerprint != fingerprint:
                    # Fingerprint changed! Possible fork/impersonation
                    old_trust = peer.trust
                    peer.trust = FINGERPRINT_RESET_TRUST
                    peer.fingerprint_stable_count = 0
                    logger.warning(
                        "REAPER: peer '%s' fingerprint CHANGED (trust %.2f→%.2f) — possible fork",
                        agent_id,
                        old_trust,
                        peer.trust,
                    )
                else:
                    peer.fingerprint_stable_count += 1
                    # Trust escalation for stable fingerprint
                    if peer.fingerprint_stable_count >= FINGERPRINT_STABLE_THRESHOLD:
                        peer.trust = min(1.0, peer.trust + FINGERPRINT_TRUST_BONUS)
                peer.fingerprint = fingerprint

            # Resurrect: SUSPECT/DEAD/EVICTED → ALIVE (but trust stays degraded)
            if peer.status in (PeerStatus.SUSPECT, PeerStatus.DEAD, PeerStatus.EVICTED):
                old = peer.status.value
                peer.status = PeerStatus.ALIVE
                # EVICTED peers reset to 0.50; others get incremental recovery
                if old == "evicted":
                    peer.trust = 0.50
                else:
                    # Small trust recovery on comeback (slower than decay)
                    peer.trust = min(1.0, peer.trust + self.trust_decay * 0.5)
                logger.info(
                    "REAPER: peer '%s' resurrected (%s → ALIVE, trust=%.2f)",
                    agent_id,
                    old,
                    peer.trust,
                )
        else:
            peer = PeerRecord(
                agent_id=agent_id,
                last_seen=now,
                trust=INITIAL_TRUST,
                status=PeerStatus.ALIVE,
                heartbeat_count=1,
                first_seen=now,
                source=source,
                capabilities=tuple(sorted(caps)) if caps else (),
                fingerprint=fingerprint,
                fingerprint_stable_count=1 if fingerprint else 0,
            )
            self._peers[agent_id] = peer
            logger.info("REAPER: new peer '%s' registered (trust=%.2f)", agent_id, INITIAL_TRUST)

            # Evict oldest if at capacity
            if len(self._peers) > MAX_PEERS:
                self._evict_oldest()

        return peer

    def reap(self, now: float | None = None) -> list[ReaperConsequence]:
        """Scan all peers and execute consequences for expired leases.

        Returns list of consequences (data, not side-effects).
        Caller decides what to do with them.
        """
        now = now or time.time()
        consequences: list[ReaperConsequence] = []
        to_evict: list[str] = []

        for agent_id, peer in self._peers.items():
            if peer.status == PeerStatus.EVICTED:
                continue

            age = now - peer.last_seen
            if age <= self.lease_ttl_s:
                continue  # Still within lease — healthy

            transition = _STATE_TRANSITIONS.get(peer.status)
            if transition is None:
                continue

            old_status = peer.status.value
            old_trust = peer.trust

            peer.status = transition.next_status
            peer.trust = max(0.0, peer.trust - self.trust_decay) if transition.decay else peer.trust  # preserve trust on eviction — CI statelessness ≠ defect
            detail = transition.detail_fn(age, self.lease_ttl_s)

            if transition.evict:
                to_evict.append(agent_id)
                self._total_evictions += 1

            consequences.append(
                ReaperConsequence(
                    agent_id=agent_id,
                    action=transition.action,
                    detail=detail,
                    old_status=old_status,
                    new_status=peer.status.value,
                    old_trust=old_trust,
                    new_trust=peer.trust,
                )
            )

        # Keep evicted peers in registry for persistence across runs.
        # They are marked EVICTED but remain recoverable if they heartbeat again.
        # Deleting them prevents load() from recovering trust scores next session.

        self._total_reaps += 1

        if consequences:
            logger.warning(
                "REAPER: %d consequences (%d suspect, %d dead, %d evicted)",
                len(consequences),
                sum(1 for c in consequences if c.action == "suspect"),
                sum(1 for c in consequences if c.action == "dead"),
                sum(1 for c in consequences if c.action == "evict"),
            )

        return consequences

    def get_peer(self, agent_id: str) -> PeerRecord | None:
        """Get a specific peer's record."""
        return self._peers.get(agent_id)

    def alive_peers(self) -> list[PeerRecord]:
        """Get all peers with ALIVE status."""
        return [p for p in self._peers.values() if p.status == PeerStatus.ALIVE]

    def suspect_peers(self) -> list[PeerRecord]:
        """Get all peers with SUSPECT status."""
        return [p for p in self._peers.values() if p.status == PeerStatus.SUSPECT]

    def dead_peers(self) -> list[PeerRecord]:
        """Get all peers with DEAD status."""
        return [p for p in self._peers.values() if p.status == PeerStatus.DEAD]

    def peer_count(self) -> int:
        """Total tracked peers (excluding evicted)."""
        return len(self._peers)

    def stats(self) -> dict:
        """Observability — reaper state."""
        by_status: dict[str, int] = {}
        total_trust = 0.0
        for peer in self._peers.values():
            by_status[peer.status.value] = by_status.get(peer.status.value, 0) + 1
            total_trust += peer.trust

        return {
            "total_peers": len(self._peers),
            "by_status": by_status,
            "avg_trust": total_trust / len(self._peers) if self._peers else 0.0,
            "total_reaps": self._total_reaps,
            "total_evictions": self._total_evictions,
            "lease_ttl_s": self.lease_ttl_s,
            "trust_decay": self.trust_decay,
        }

    # ── Persistence ──────────────────────────────────────────────────

    def save(self, path: Path) -> None:
        """Persist peer registry to JSON file."""
        data = {
            "version": 1,
            "saved_at": time.time(),
            "lease_ttl_s": self.lease_ttl_s,
            "trust_decay": self.trust_decay,
            "total_reaps": self._total_reaps,
            "total_evictions": self._total_evictions,
            "peers": [p.to_dict() for p in self._peers.values()],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2))
        temp.replace(path)
        logger.debug("REAPER: saved %d peers to %s", len(self._peers), path)

    def load(self, path: Path) -> int:
        """Restore peer registry from JSON file.

        Returns number of peers loaded. Silently handles missing/corrupt files.
        """
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("REAPER: failed to load %s: %s", path, e)
            return 0

        peers = data.get("peers", [])
        loaded = 0
        for entry in peers:
            try:
                peer = PeerRecord.from_dict(entry)
                # Load all peers including EVICTED — they may heartbeat again next run
                self._peers[peer.agent_id] = peer
                loaded += 1
            except (KeyError, TypeError, ValueError) as e:
                logger.debug("REAPER: skipped corrupt peer entry: %s", e)

        self._total_reaps = data.get("total_reaps", 0)
        self._total_evictions = data.get("total_evictions", 0)

        logger.info("REAPER: loaded %d peers from %s", loaded, path)
        return loaded

    # ── Private ──────────────────────────────────────────────────────

    def _evict_oldest(self) -> None:
        """Evict the oldest peer when at capacity."""
        if not self._peers:
            return
        oldest = min(self._peers.values(), key=lambda p: p.last_seen)
        del self._peers[oldest.agent_id]
        logger.info("REAPER: capacity eviction — removed '%s' (oldest)", oldest.agent_id)
