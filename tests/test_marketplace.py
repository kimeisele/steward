"""Tests for Marketplace — slot conflict resolution."""

import json
import time

import pytest

from steward.marketplace import (
    DEFAULT_CLAIM_TTL_S,
    MAX_CLAIMS,
    ClaimOutcome,
    Marketplace,
    SlotClaim,
)


class TestClaimGrant:
    def test_unclaimed_slot_granted(self):
        m = Marketplace()
        out = m.claim("task:1", "agent-a", trust=0.5)
        assert out.granted
        assert out.holder == "agent-a"
        assert out.reason == "granted"

    def test_same_agent_renews(self):
        m = Marketplace()
        m.claim("task:1", "agent-a", trust=0.5)
        out = m.claim("task:1", "agent-a", trust=0.5)
        assert out.granted
        assert out.reason == "renewed"

    def test_renewal_increments_counter(self):
        m = Marketplace()
        m.claim("task:1", "agent-a", trust=0.5)
        m.claim("task:1", "agent-a", trust=0.5)
        claim = m.get_claim("task:1")
        assert claim.renewals == 1


class TestTrustArbitration:
    def test_higher_trust_wins(self):
        m = Marketplace(default_ttl_s=600)
        m.claim("task:1", "agent-a", trust=0.3)
        out = m.claim("task:1", "agent-b", trust=0.8)
        assert out.granted
        assert out.holder == "agent-b"
        assert "arbitration" in out.reason

    def test_equal_trust_incumbent_holds(self):
        m = Marketplace(default_ttl_s=600)
        m.claim("task:1", "agent-a", trust=0.5)
        out = m.claim("task:1", "agent-b", trust=0.5)
        assert not out.granted
        assert out.holder == "agent-a"
        assert "incumbent" in out.reason

    def test_lower_trust_denied(self):
        m = Marketplace(default_ttl_s=600)
        m.claim("task:1", "agent-a", trust=0.8)
        out = m.claim("task:1", "agent-b", trust=0.3)
        assert not out.granted
        assert out.holder == "agent-a"

    def test_contest_counter_increments(self):
        m = Marketplace(default_ttl_s=600)
        m.claim("task:1", "agent-a", trust=0.5)
        m.claim("task:1", "agent-b", trust=0.3)
        assert m.stats()["total_contests"] == 1


class TestExpiration:
    def test_expired_incumbent_evicted(self):
        m = Marketplace(default_ttl_s=100)
        m.claim("task:1", "agent-a", trust=0.9)

        # Simulate expiration
        m._claims["task:1"].timestamp -= 200

        out = m.claim("task:1", "agent-b", trust=0.1)
        assert out.granted
        assert out.holder == "agent-b"

    def test_get_holder_returns_none_for_expired(self):
        m = Marketplace(default_ttl_s=100)
        m.claim("task:1", "agent-a", trust=0.5)
        m._claims["task:1"].timestamp -= 200
        assert m.get_holder("task:1") is None

    def test_purge_expired(self):
        m = Marketplace(default_ttl_s=100)
        now = time.time()
        m.claim("task:1", "agent-a", trust=0.5)
        m.claim("task:2", "agent-b", trust=0.5)
        m._claims["task:1"].timestamp -= 200  # expire task:1

        purged = m.purge_expired(now=now)
        assert purged == 1
        assert m.get_holder("task:1") is None
        assert m.get_holder("task:2") == "agent-b"


class TestRelease:
    def test_holder_can_release(self):
        m = Marketplace()
        m.claim("task:1", "agent-a", trust=0.5)
        assert m.release("task:1", "agent-a")
        assert m.get_holder("task:1") is None

    def test_non_holder_cannot_release(self):
        m = Marketplace()
        m.claim("task:1", "agent-a", trust=0.5)
        assert not m.release("task:1", "agent-b")
        assert m.get_holder("task:1") == "agent-a"

    def test_release_unclaimed_returns_false(self):
        m = Marketplace()
        assert not m.release("task:999", "agent-a")


class TestQuery:
    def test_get_holder_unclaimed(self):
        m = Marketplace()
        assert m.get_holder("task:1") is None

    def test_list_claims(self):
        m = Marketplace()
        m.claim("task:1", "agent-a", trust=0.5)
        m.claim("task:2", "agent-b", trust=0.5)
        assert len(m.list_claims()) == 2

    def test_claims_by_agent(self):
        m = Marketplace()
        m.claim("task:1", "agent-a", trust=0.5)
        m.claim("task:2", "agent-a", trust=0.5)
        m.claim("task:3", "agent-b", trust=0.5)
        assert len(m.claims_by_agent("agent-a")) == 2
        assert len(m.claims_by_agent("agent-b")) == 1

    def test_active_count(self):
        m = Marketplace()
        m.claim("task:1", "agent-a", trust=0.5)
        assert m.active_count() == 1

    def test_stats(self):
        m = Marketplace()
        m.claim("task:1", "agent-a", trust=0.5)
        s = m.stats()
        assert s["active_claims"] == 1
        assert s["unique_agents"] == 1
        assert s["total_grants"] == 1


class TestPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        path = tmp_path / "marketplace.json"
        m = Marketplace()
        m.claim("task:1", "agent-a", trust=0.7)
        m.claim("task:2", "agent-b", trust=0.3)
        m.save(path)

        m2 = Marketplace()
        loaded = m2.load(path)
        assert loaded == 2
        assert m2.get_holder("task:1") == "agent-a"
        assert m2.get_holder("task:2") == "agent-b"

    def test_expired_claims_not_restored(self, tmp_path):
        path = tmp_path / "marketplace.json"
        data = {
            "version": 1,
            "claims": [
                {"slot_id": "x", "agent_id": "a", "trust_at_claim": 0.5,
                 "timestamp": 0.0, "ttl_s": 1.0},  # long expired
                {"slot_id": "y", "agent_id": "b", "trust_at_claim": 0.5,
                 "timestamp": time.time(), "ttl_s": 9999.0},
            ],
        }
        path.write_text(json.dumps(data))
        m = Marketplace()
        loaded = m.load(path)
        assert loaded == 1  # only "y"

    def test_load_missing_file(self, tmp_path):
        m = Marketplace()
        assert m.load(tmp_path / "nope.json") == 0

    def test_load_corrupt_file(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{{{invalid")
        m = Marketplace()
        assert m.load(path) == 0


class TestCapacity:
    def test_oldest_evicted_at_capacity(self):
        m = Marketplace()
        for i in range(MAX_CLAIMS):
            m.claim(f"slot:{i}", "agent-a", trust=0.5)
        assert m.active_count() == MAX_CLAIMS

        # One more triggers capacity eviction
        m.claim("slot:overflow", "agent-a", trust=0.5)
        assert m.active_count() == MAX_CLAIMS


class TestSlotClaimSerialization:
    def test_roundtrip(self):
        claim = SlotClaim(
            slot_id="task:1",
            agent_id="agent-a",
            trust_at_claim=0.75,
            timestamp=1000.0,
            ttl_s=300.0,
            renewals=2,
        )
        restored = SlotClaim.from_dict(claim.to_dict())
        assert restored.slot_id == claim.slot_id
        assert restored.agent_id == claim.agent_id
        assert restored.trust_at_claim == claim.trust_at_claim
        assert restored.renewals == claim.renewals

    def test_is_expired(self):
        claim = SlotClaim(
            slot_id="x", agent_id="a",
            trust_at_claim=0.5, timestamp=1000.0, ttl_s=100.0,
        )
        assert not claim.is_expired(now=1050.0)
        assert claim.is_expired(now=1200.0)


class TestClaimOutcome:
    def test_granted_outcome(self):
        o = ClaimOutcome(
            granted=True, slot_id="task:1",
            agent_id="agent-a", holder="agent-a", reason="granted",
        )
        assert o.granted
        assert o.agent_id == o.holder

    def test_denied_outcome(self):
        o = ClaimOutcome(
            granted=False, slot_id="task:1",
            agent_id="agent-b", holder="agent-a", reason="incumbent holds",
        )
        assert not o.granted
        assert o.agent_id != o.holder
