"""Tests for HeartbeatReaper — network garbage collection.

Verifies the 3-strike eviction protocol, trust degradation,
persistence, and edge cases.
"""

import json
import time

import pytest

from steward.reaper import (
    INITIAL_TRUST,
    MAX_PEERS,
    HeartbeatReaper,
    PeerRecord,
    PeerStatus,
    ReaperConsequence,
)


class TestHeartbeatRecording:
    """record_heartbeat() creates and updates peers."""

    def test_new_peer_gets_initial_trust(self):
        reaper = HeartbeatReaper()
        peer = reaper.record_heartbeat("agent-a")
        assert peer.trust == INITIAL_TRUST
        assert peer.status == PeerStatus.ALIVE
        assert peer.heartbeat_count == 1

    def test_second_heartbeat_increments_count(self):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-a", timestamp=100.0)
        peer = reaper.record_heartbeat("agent-a", timestamp=200.0)
        assert peer.heartbeat_count == 2
        assert peer.last_seen == 200.0

    def test_source_recorded(self):
        reaper = HeartbeatReaper()
        peer = reaper.record_heartbeat("agent-a", source="agent-internet")
        assert peer.source == "agent-internet"

    def test_source_updated_on_subsequent_heartbeat(self):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-a", source="nadi")
        peer = reaper.record_heartbeat("agent-a", source="agent-internet")
        assert peer.source == "agent-internet"

    def test_first_seen_set_once(self):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-a", timestamp=100.0)
        reaper.record_heartbeat("agent-a", timestamp=200.0)
        peer = reaper.get_peer("agent-a")
        assert peer.first_seen == 100.0

    def test_multiple_peers_tracked(self):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-a")
        reaper.record_heartbeat("agent-b")
        reaper.record_heartbeat("agent-c")
        assert reaper.peer_count() == 3


class TestReaping:
    """reap() detects expired leases and executes consequences."""

    def test_no_consequences_when_all_alive(self):
        reaper = HeartbeatReaper(lease_ttl_s=100)
        now = 1000.0
        reaper.record_heartbeat("agent-a", timestamp=now)
        consequences = reaper.reap(now=now + 50)  # 50s < 100s TTL
        assert consequences == []

    def test_alive_to_suspect_on_first_miss(self):
        reaper = HeartbeatReaper(lease_ttl_s=100)
        now = 1000.0
        reaper.record_heartbeat("agent-a", timestamp=now)
        consequences = reaper.reap(now=now + 150)  # 150s > 100s TTL

        assert len(consequences) == 1
        c = consequences[0]
        assert c.agent_id == "agent-a"
        assert c.action == "suspect"
        assert c.old_status == "alive"
        assert c.new_status == "suspect"
        assert c.new_trust < c.old_trust

    def test_suspect_to_dead_on_second_miss(self):
        reaper = HeartbeatReaper(lease_ttl_s=100)
        now = 1000.0
        reaper.record_heartbeat("agent-a", timestamp=now)

        # Strike 1
        reaper.reap(now=now + 150)
        # Strike 2 (still no heartbeat)
        consequences = reaper.reap(now=now + 250)

        assert len(consequences) == 1
        c = consequences[0]
        assert c.action == "dead"
        assert c.old_status == "suspect"
        assert c.new_status == "dead"

    def test_dead_to_evicted_on_third_miss(self):
        reaper = HeartbeatReaper(lease_ttl_s=100)
        now = 1000.0
        reaper.record_heartbeat("agent-a", timestamp=now)

        # 3 strikes
        reaper.reap(now=now + 150)
        reaper.reap(now=now + 250)
        consequences = reaper.reap(now=now + 350)

        assert len(consequences) == 1
        c = consequences[0]
        assert c.action == "evict"
        assert c.new_trust == 0.0
        # Evicted peer removed from registry
        assert reaper.get_peer("agent-a") is None
        assert reaper.peer_count() == 0

    def test_evicted_peer_not_reaped_again(self):
        reaper = HeartbeatReaper(lease_ttl_s=100)
        now = 1000.0
        reaper.record_heartbeat("agent-a", timestamp=now)

        # Evict
        reaper.reap(now=now + 150)
        reaper.reap(now=now + 250)
        reaper.reap(now=now + 350)

        # No more consequences
        consequences = reaper.reap(now=now + 450)
        assert consequences == []

    def test_multiple_peers_reaped_independently(self):
        reaper = HeartbeatReaper(lease_ttl_s=100)
        now = 1000.0
        reaper.record_heartbeat("agent-a", timestamp=now)
        reaper.record_heartbeat("agent-b", timestamp=now + 80)

        # At now + 150: agent-a expired, agent-b still alive (70s < 100s)
        consequences = reaper.reap(now=now + 150)
        assert len(consequences) == 1
        assert consequences[0].agent_id == "agent-a"

    def test_reap_count_increments(self):
        reaper = HeartbeatReaper()
        reaper.reap()
        reaper.reap()
        assert reaper.stats()["total_reaps"] == 2


class TestTrustDegradation:
    """Trust decays on missed windows and partially recovers on comeback."""

    def test_trust_decays_on_suspect(self):
        reaper = HeartbeatReaper(lease_ttl_s=100, trust_decay=0.2)
        reaper.record_heartbeat("agent-a", timestamp=1000.0)
        reaper.reap(now=1200.0)

        peer = reaper.get_peer("agent-a")
        assert peer.trust == pytest.approx(INITIAL_TRUST - 0.2)

    def test_trust_decays_further_on_dead(self):
        reaper = HeartbeatReaper(lease_ttl_s=100, trust_decay=0.2)
        reaper.record_heartbeat("agent-a", timestamp=1000.0)
        reaper.reap(now=1200.0)
        reaper.reap(now=1400.0)

        peer = reaper.get_peer("agent-a")
        assert peer.trust == pytest.approx(INITIAL_TRUST - 0.4)

    def test_trust_floors_at_zero(self):
        reaper = HeartbeatReaper(lease_ttl_s=100, trust_decay=0.9)
        reaper.record_heartbeat("agent-a", timestamp=1000.0)
        reaper.reap(now=1200.0)  # 0.5 - 0.9 = -0.4 → clamped to 0.0

        peer = reaper.get_peer("agent-a")
        assert peer.trust == 0.0

    def test_partial_trust_recovery_on_comeback(self):
        reaper = HeartbeatReaper(lease_ttl_s=100, trust_decay=0.2)
        reaper.record_heartbeat("agent-a", timestamp=1000.0)
        reaper.reap(now=1200.0)  # SUSPECT, trust = 0.3

        # Comeback heartbeat
        peer = reaper.record_heartbeat("agent-a", timestamp=1300.0)
        assert peer.status == PeerStatus.ALIVE
        # Trust partially recovered: 0.3 + (0.2 * 0.5) = 0.4
        assert peer.trust == pytest.approx(0.4)

    def test_trust_capped_at_one(self):
        reaper = HeartbeatReaper(lease_ttl_s=100, trust_decay=0.2)
        peer = reaper.record_heartbeat("agent-a", timestamp=1000.0)
        peer.trust = 0.95
        # Comeback with high trust shouldn't exceed 1.0
        reaper.record_heartbeat("agent-a", timestamp=1100.0)
        peer = reaper.get_peer("agent-a")
        assert peer.trust <= 1.0


class TestResurrection:
    """Peers can come back from SUSPECT/DEAD with a heartbeat."""

    def test_suspect_resurrected_to_alive(self):
        reaper = HeartbeatReaper(lease_ttl_s=100)
        reaper.record_heartbeat("agent-a", timestamp=1000.0)
        reaper.reap(now=1200.0)  # SUSPECT
        reaper.record_heartbeat("agent-a", timestamp=1300.0)

        peer = reaper.get_peer("agent-a")
        assert peer.status == PeerStatus.ALIVE

    def test_dead_resurrected_to_alive(self):
        reaper = HeartbeatReaper(lease_ttl_s=100)
        reaper.record_heartbeat("agent-a", timestamp=1000.0)
        reaper.reap(now=1200.0)  # SUSPECT
        reaper.reap(now=1400.0)  # DEAD
        reaper.record_heartbeat("agent-a", timestamp=1500.0)

        peer = reaper.get_peer("agent-a")
        assert peer.status == PeerStatus.ALIVE

    def test_evicted_can_rejoin_as_new_peer(self):
        reaper = HeartbeatReaper(lease_ttl_s=100)
        reaper.record_heartbeat("agent-a", timestamp=1000.0)
        reaper.reap(now=1200.0)
        reaper.reap(now=1400.0)
        reaper.reap(now=1600.0)  # EVICTED, removed

        # Re-register as new peer
        peer = reaper.record_heartbeat("agent-a", timestamp=2000.0)
        assert peer.status == PeerStatus.ALIVE
        assert peer.trust == INITIAL_TRUST  # Fresh start
        assert peer.heartbeat_count == 1


class TestPersistence:
    """save/load roundtrip preserves state."""

    def test_save_load_roundtrip(self, tmp_path):
        path = tmp_path / ".steward" / "peers.json"
        reaper = HeartbeatReaper(lease_ttl_s=300)
        reaper.record_heartbeat("agent-a", timestamp=1000.0, source="nadi")
        reaper.record_heartbeat("agent-b", timestamp=2000.0, source="api")
        reaper.reap(now=3000.0)  # Reap to increment counter

        reaper.save(path)
        assert path.exists()

        reaper2 = HeartbeatReaper(lease_ttl_s=300)
        loaded = reaper2.load(path)
        assert loaded == 2
        assert reaper2.get_peer("agent-a") is not None
        assert reaper2.get_peer("agent-b") is not None
        assert reaper2.stats()["total_reaps"] == 1

    def test_evicted_peers_not_restored(self, tmp_path):
        path = tmp_path / "peers.json"
        reaper = HeartbeatReaper(lease_ttl_s=100)
        reaper.record_heartbeat("agent-a", timestamp=1000.0)
        reaper.reap(now=1200.0)
        reaper.reap(now=1400.0)
        reaper.reap(now=1600.0)  # EVICTED

        # Manually save a record with evicted status to verify load skips it
        data = {
            "version": 1,
            "saved_at": time.time(),
            "peers": [
                {"agent_id": "ghost", "status": "evicted", "trust": 0.0, "last_seen": 0},
                {"agent_id": "alive-one", "status": "alive", "trust": 0.5, "last_seen": 1000},
            ],
        }
        path.write_text(json.dumps(data))

        reaper2 = HeartbeatReaper()
        loaded = reaper2.load(path)
        assert loaded == 1  # Only alive-one
        assert reaper2.get_peer("ghost") is None
        assert reaper2.get_peer("alive-one") is not None

    def test_load_missing_file_returns_zero(self, tmp_path):
        reaper = HeartbeatReaper()
        loaded = reaper.load(tmp_path / "nonexistent.json")
        assert loaded == 0

    def test_load_corrupt_file_returns_zero(self, tmp_path):
        path = tmp_path / "peers.json"
        path.write_text("not valid json{{{")

        reaper = HeartbeatReaper()
        loaded = reaper.load(path)
        assert loaded == 0

    def test_load_corrupt_entry_skipped(self, tmp_path):
        path = tmp_path / "peers.json"
        data = {
            "version": 1,
            "peers": [
                {"agent_id": "good", "status": "alive", "trust": 0.5, "last_seen": 1000},
                {"broken": True},  # Missing agent_id
            ],
        }
        path.write_text(json.dumps(data))

        reaper = HeartbeatReaper()
        loaded = reaper.load(path)
        assert loaded == 1


class TestQueryMethods:
    """Filtering and stats work correctly."""

    def test_alive_peers_filter(self):
        reaper = HeartbeatReaper(lease_ttl_s=100)
        reaper.record_heartbeat("alive", timestamp=1000.0)
        reaper.record_heartbeat("doomed", timestamp=500.0)
        reaper.reap(now=1050.0)  # doomed → suspect

        alive = reaper.alive_peers()
        assert len(alive) == 1
        assert alive[0].agent_id == "alive"

    def test_suspect_peers_filter(self):
        reaper = HeartbeatReaper(lease_ttl_s=100)
        reaper.record_heartbeat("agent-a", timestamp=500.0)
        reaper.reap(now=1000.0)

        suspect = reaper.suspect_peers()
        assert len(suspect) == 1

    def test_dead_peers_filter(self):
        reaper = HeartbeatReaper(lease_ttl_s=100)
        reaper.record_heartbeat("agent-a", timestamp=500.0)
        reaper.reap(now=1000.0)
        reaper.reap(now=1200.0)

        dead = reaper.dead_peers()
        assert len(dead) == 1

    def test_get_unknown_peer_returns_none(self):
        reaper = HeartbeatReaper()
        assert reaper.get_peer("nonexistent") is None

    def test_stats_include_all_fields(self):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-a")
        stats = reaper.stats()

        assert "total_peers" in stats
        assert "by_status" in stats
        assert "avg_trust" in stats
        assert "total_reaps" in stats
        assert "total_evictions" in stats
        assert "lease_ttl_s" in stats

    def test_stats_avg_trust(self):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-a")
        reaper.record_heartbeat("agent-b")
        stats = reaper.stats()
        assert stats["avg_trust"] == pytest.approx(INITIAL_TRUST)

    def test_empty_reaper_stats(self):
        reaper = HeartbeatReaper()
        stats = reaper.stats()
        assert stats["total_peers"] == 0
        assert stats["avg_trust"] == 0.0


class TestCapacityEviction:
    """MAX_PEERS capacity limit enforced."""

    def test_oldest_evicted_at_capacity(self):
        reaper = HeartbeatReaper()
        # Fill to MAX_PEERS
        for i in range(MAX_PEERS):
            reaper.record_heartbeat(f"agent-{i}", timestamp=float(i))

        assert reaper.peer_count() == MAX_PEERS

        # One more triggers eviction of oldest (agent-0)
        reaper.record_heartbeat("agent-overflow", timestamp=float(MAX_PEERS + 1))
        assert reaper.peer_count() == MAX_PEERS
        assert reaper.get_peer("agent-0") is None
        assert reaper.get_peer("agent-overflow") is not None


class TestPeerRecordSerialization:
    """PeerRecord to_dict/from_dict roundtrip."""

    def test_roundtrip(self):
        peer = PeerRecord(
            agent_id="test",
            last_seen=1000.0,
            trust=0.75,
            status=PeerStatus.SUSPECT,
            heartbeat_count=5,
            first_seen=500.0,
            source="nadi",
        )
        restored = PeerRecord.from_dict(peer.to_dict())
        assert restored.agent_id == peer.agent_id
        assert restored.trust == peer.trust
        assert restored.status == peer.status
        assert restored.heartbeat_count == peer.heartbeat_count
        assert restored.source == peer.source


class TestReaperConsequence:
    """ReaperConsequence is a clean data object."""

    def test_consequence_fields(self):
        c = ReaperConsequence(
            agent_id="test",
            action="suspect",
            detail="lease expired",
            old_status="alive",
            new_status="suspect",
            old_trust=0.5,
            new_trust=0.3,
        )
        assert c.agent_id == "test"
        assert c.action == "suspect"
        assert c.old_trust > c.new_trust
