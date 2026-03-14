"""
Marketplace — Slot Conflict Resolution for Federation Peers.

When two agents want the same work item (task, PR, issue, branch),
the marketplace decides who gets it.

Resolution strategy: **Trust-Weighted Arbitration**.
    1. Unclaimed slot → grant immediately
    2. Same agent re-claims → refresh TTL
    3. Different agent contests → higher trust score wins
    4. Equal trust → incumbent holds (first-come-first-served)
    5. Expired claims → auto-released

Claims are lightweight: slot_id + agent_id + trust + TTL.
The loser gets a typed ClaimOutcome explaining the rejection.

Integration:
    DHARMA phase: purge_expired() alongside reaper.reap()
    MOKSHA phase: persist to .steward/marketplace.json
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("STEWARD.MARKETPLACE")

DEFAULT_CLAIM_TTL_S: float = 600.0  # 10 minutes
MAX_CLAIMS: int = 512


@dataclass
class SlotClaim:
    """Active claim on a work slot."""

    slot_id: str  # e.g., "task:fix-ci", "pr:42", "branch:steward/fix/123"
    agent_id: str
    trust_at_claim: float  # trust score when claim was granted
    timestamp: float
    ttl_s: float = DEFAULT_CLAIM_TTL_S
    renewals: int = 0

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.time()) >= self.timestamp + self.ttl_s

    def to_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "agent_id": self.agent_id,
            "trust_at_claim": self.trust_at_claim,
            "timestamp": self.timestamp,
            "ttl_s": self.ttl_s,
            "renewals": self.renewals,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SlotClaim:
        return cls(
            slot_id=data["slot_id"],
            agent_id=data["agent_id"],
            trust_at_claim=data.get("trust_at_claim", 0.0),
            timestamp=data.get("timestamp", 0.0),
            ttl_s=data.get("ttl_s", DEFAULT_CLAIM_TTL_S),
            renewals=data.get("renewals", 0),
        )


@dataclass(frozen=True)
class ClaimOutcome:
    """Result of a claim attempt — returned to the requesting agent."""

    granted: bool
    slot_id: str
    agent_id: str  # the requester
    holder: str  # who holds the slot (requester if granted, incumbent if denied)
    reason: str


@dataclass
class Marketplace:
    """Slot conflict resolution via trust-weighted arbitration.

    Usage:
        market = Marketplace()
        outcome = market.claim("task:fix-ci", "agent-a", trust=0.8)
        if outcome.granted:
            # work on the task
            ...
            market.release("task:fix-ci", "agent-a")
    """

    default_ttl_s: float = DEFAULT_CLAIM_TTL_S
    _claims: dict[str, SlotClaim] = field(default_factory=dict)
    _total_grants: int = field(default=0, init=False)
    _total_contests: int = field(default=0, init=False)
    _total_evictions: int = field(default=0, init=False)

    def claim(
        self,
        slot_id: str,
        agent_id: str,
        trust: float = 0.0,
        ttl_s: float | None = None,
    ) -> ClaimOutcome:
        """Request a claim on a slot.

        Resolution:
            - Unclaimed → grant
            - Same agent → refresh TTL
            - Expired incumbent → evict and grant
            - Higher trust → evict incumbent, grant challenger
            - Equal/lower trust → deny (incumbent holds)
        """
        now = time.time()
        effective_ttl = ttl_s if ttl_s is not None else self.default_ttl_s
        existing = self._claims.get(slot_id)

        # Case 1: Unclaimed
        if existing is None:
            return self._grant(slot_id, agent_id, trust, now, effective_ttl)

        # Case 2: Same agent re-claims (refresh)
        if existing.agent_id == agent_id:
            existing.timestamp = now
            existing.ttl_s = effective_ttl
            existing.renewals += 1
            return ClaimOutcome(
                granted=True,
                slot_id=slot_id,
                agent_id=agent_id,
                holder=agent_id,
                reason="renewed",
            )

        # Case 3: Expired incumbent → evict
        if existing.is_expired(now):
            self._total_evictions += 1
            logger.info(
                "MARKET: expired claim on '%s' by '%s' — evicting",
                slot_id,
                existing.agent_id,
            )
            return self._grant(slot_id, agent_id, trust, now, effective_ttl)

        # Case 4: Contest — trust-weighted arbitration
        self._total_contests += 1

        if trust > existing.trust_at_claim:
            # Challenger wins — evict incumbent
            loser = existing.agent_id
            self._total_evictions += 1
            logger.info(
                "MARKET: '%s' (trust=%.2f) evicts '%s' (trust=%.2f) from '%s'",
                agent_id,
                trust,
                loser,
                existing.trust_at_claim,
                slot_id,
            )
            self._grant(slot_id, agent_id, trust, now, effective_ttl)
            return ClaimOutcome(
                granted=True,
                slot_id=slot_id,
                agent_id=agent_id,
                holder=agent_id,
                reason=f"trust arbitration: {trust:.2f} > {existing.trust_at_claim:.2f}",
            )

        # Incumbent holds (equal or higher trust)
        return ClaimOutcome(
            granted=False,
            slot_id=slot_id,
            agent_id=agent_id,
            holder=existing.agent_id,
            reason=f"incumbent holds: {existing.trust_at_claim:.2f} >= {trust:.2f}",
        )

    def release(self, slot_id: str, agent_id: str) -> bool:
        """Release a claim. Only the holder can release."""
        existing = self._claims.get(slot_id)
        if existing is None:
            return False
        if existing.agent_id != agent_id:
            return False
        del self._claims[slot_id]
        return True

    def get_holder(self, slot_id: str) -> str | None:
        """Get the agent holding a slot, or None if unclaimed/expired."""
        existing = self._claims.get(slot_id)
        if existing is None:
            return None
        if existing.is_expired():
            del self._claims[slot_id]
            return None
        return existing.agent_id

    def get_claim(self, slot_id: str) -> SlotClaim | None:
        """Get the full claim for a slot."""
        existing = self._claims.get(slot_id)
        if existing is None:
            return None
        if existing.is_expired():
            del self._claims[slot_id]
            return None
        return existing

    def purge_expired(self, now: float | None = None) -> int:
        """Remove all expired claims. Returns count purged."""
        now = now or time.time()
        expired = [sid for sid, claim in self._claims.items() if claim.is_expired(now)]
        for sid in expired:
            del self._claims[sid]
        if expired:
            self._total_evictions += len(expired)
            logger.info("MARKET: purged %d expired claims", len(expired))
        return len(expired)

    def list_claims(self) -> list[SlotClaim]:
        """All active (non-expired) claims."""
        now = time.time()
        return [c for c in self._claims.values() if not c.is_expired(now)]

    def claims_by_agent(self, agent_id: str) -> list[SlotClaim]:
        """All active claims held by a specific agent."""
        now = time.time()
        return [c for c in self._claims.values() if c.agent_id == agent_id and not c.is_expired(now)]

    def active_count(self) -> int:
        return len(self.list_claims())

    def stats(self) -> dict:
        active = self.list_claims()
        agents = set(c.agent_id for c in active)
        return {
            "active_claims": len(active),
            "unique_agents": len(agents),
            "total_grants": self._total_grants,
            "total_contests": self._total_contests,
            "total_evictions": self._total_evictions,
            "default_ttl_s": self.default_ttl_s,
        }

    # ── Persistence ──────────────────────────────────────────────────

    def save(self, path: Path) -> None:
        data = {
            "version": 1,
            "saved_at": time.time(),
            "total_grants": self._total_grants,
            "total_contests": self._total_contests,
            "total_evictions": self._total_evictions,
            "claims": [c.to_dict() for c in self._claims.values()],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2))
        temp.replace(path)

    def load(self, path: Path) -> int:
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return 0

        self._total_grants = data.get("total_grants", 0)
        self._total_contests = data.get("total_contests", 0)
        self._total_evictions = data.get("total_evictions", 0)

        now = time.time()
        loaded = 0
        for entry in data.get("claims", []):
            try:
                claim = SlotClaim.from_dict(entry)
                if not claim.is_expired(now):
                    self._claims[claim.slot_id] = claim
                    loaded += 1
            except (KeyError, TypeError, ValueError) as e:
                logger.debug("Skipped corrupt marketplace claim: %s", e)
        return loaded

    # ── Private ──────────────────────────────────────────────────────

    def _grant(
        self,
        slot_id: str,
        agent_id: str,
        trust: float,
        now: float,
        ttl_s: float,
    ) -> ClaimOutcome:
        self._claims[slot_id] = SlotClaim(
            slot_id=slot_id,
            agent_id=agent_id,
            trust_at_claim=trust,
            timestamp=now,
            ttl_s=ttl_s,
        )
        self._total_grants += 1

        # Capacity enforcement
        if len(self._claims) > MAX_CLAIMS:
            oldest = min(self._claims.values(), key=lambda c: c.timestamp)
            del self._claims[oldest.slot_id]

        return ClaimOutcome(
            granted=True,
            slot_id=slot_id,
            agent_id=agent_id,
            holder=agent_id,
            reason="granted",
        )
