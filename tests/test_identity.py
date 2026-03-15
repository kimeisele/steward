"""Tests for Phase 3: StewardIdentity + trust gating + fingerprint tracking."""

from unittest.mock import patch

import pytest

from steward.federation import (
    OP_DELEGATE_TASK,
    FederationBridge,
)
from steward.identity import StewardIdentity
from steward.reaper import (
    FINGERPRINT_RESET_TRUST,
    FINGERPRINT_STABLE_THRESHOLD,
    INITIAL_TRUST,
    HeartbeatReaper,
    PeerRecord,
)
from steward.services import SVC_TASK_MANAGER
from vibe_core.di import ServiceRegistry
from vibe_core.task_management.task_manager import TaskManager


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    ServiceRegistry.reset()


class TestFingerprintDeterminism:
    """Fingerprint must be deterministic given same inputs."""

    def test_same_inputs_same_fingerprint(self):
        fp1 = StewardIdentity.compute_fingerprint("a", "b", "c")
        fp2 = StewardIdentity.compute_fingerprint("a", "b", "c")
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex

    def test_different_agent_id(self):
        fp1 = StewardIdentity.compute_fingerprint("agent-1", "repo", "seed")
        fp2 = StewardIdentity.compute_fingerprint("agent-2", "repo", "seed")
        assert fp1 != fp2

    def test_different_repo(self):
        fp1 = StewardIdentity.compute_fingerprint("agent", "repo-1", "seed")
        fp2 = StewardIdentity.compute_fingerprint("agent", "repo-2", "seed")
        assert fp1 != fp2

    def test_empty_seed_still_works(self):
        fp = StewardIdentity.compute_fingerprint("a", "b", "")
        assert len(fp) == 64

    def test_from_environment_without_seed(self):
        with patch.dict("os.environ", {}, clear=True):
            identity = StewardIdentity.from_environment()
        assert identity.fingerprint  # Still produces a fingerprint (empty seed)
        expected = StewardIdentity.compute_fingerprint("steward", "kimeisele/steward", "")
        assert identity.fingerprint == expected


class TestFingerprintChangeResetsrust:
    """Fingerprint change between heartbeats → trust reset."""

    def test_fingerprint_change_resets_trust(self):
        reaper = HeartbeatReaper()
        # First heartbeat with fingerprint A
        peer = reaper.record_heartbeat("agent-x", timestamp=100.0, fingerprint="fp_original")
        assert peer.fingerprint == "fp_original"

        # Second heartbeat with DIFFERENT fingerprint → trust reset
        peer = reaper.record_heartbeat("agent-x", timestamp=200.0, fingerprint="fp_fork")
        assert peer.fingerprint == "fp_fork"
        assert peer.trust == FINGERPRINT_RESET_TRUST
        assert peer.fingerprint_stable_count == 0

    def test_stable_fingerprint_escalates_trust(self):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-x", timestamp=100.0, fingerprint="fp_stable")

        # Send enough heartbeats to exceed threshold
        for i in range(FINGERPRINT_STABLE_THRESHOLD + 2):
            peer = reaper.record_heartbeat("agent-x", timestamp=200.0 + i, fingerprint="fp_stable")

        # Trust should have escalated above INITIAL_TRUST
        assert peer.trust > INITIAL_TRUST

    def test_fingerprint_stable_count_increments(self):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-x", timestamp=100.0, fingerprint="fp")
        peer = reaper.record_heartbeat("agent-x", timestamp=200.0, fingerprint="fp")
        assert peer.fingerprint_stable_count == 2  # initial=1, +1

    def test_no_fingerprint_no_tracking(self):
        """Heartbeats without fingerprint don't affect fingerprint tracking."""
        reaper = HeartbeatReaper()
        peer = reaper.record_heartbeat("agent-x", timestamp=100.0)
        assert peer.fingerprint == ""
        assert peer.fingerprint_stable_count == 0
        assert peer.trust == INITIAL_TRUST

    def test_trust_capped_at_one_during_escalation(self):
        reaper = HeartbeatReaper()
        peer = reaper.record_heartbeat("agent-x", timestamp=100.0, fingerprint="fp")
        peer.trust = 0.99  # Near ceiling

        # Many stable heartbeats
        for i in range(20):
            peer = reaper.record_heartbeat("agent-x", timestamp=200.0 + i, fingerprint="fp")

        assert peer.trust <= 1.0


class TestDelegationTrustGate:
    """Inbound delegations rejected below trust floor."""

    def test_delegation_rejected_below_trust_floor(self, tmp_path):
        reaper = HeartbeatReaper()
        # Register peer with low trust
        peer = reaper.record_heartbeat("untrusted-peer", timestamp=100.0)
        peer.trust = 0.1  # Below default floor of 0.3

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge(reaper=reaper, agent_id="steward")
        result = bridge.ingest(
            OP_DELEGATE_TASK,
            {
                "title": "Do evil things",
                "source_agent": "untrusted-peer",
                "priority": 50,
            },
        )
        assert result is False
        assert len(task_mgr.list_tasks()) == 0
        assert bridge._delegations_rejected == 1

    def test_delegation_accepted_above_trust_floor(self, tmp_path):
        reaper = HeartbeatReaper()
        peer = reaper.record_heartbeat("trusted-peer", timestamp=100.0)
        peer.trust = 0.8  # Above floor

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge(reaper=reaper, agent_id="steward")
        result = bridge.ingest(
            OP_DELEGATE_TASK,
            {
                "title": "Fix tests",
                "source_agent": "trusted-peer",
                "priority": 50,
            },
        )
        assert result is True
        assert len(task_mgr.list_tasks()) == 1

    def test_delegation_from_unknown_peer_accepted(self, tmp_path):
        """Unknown peers (not in reaper) are allowed — trust gate only blocks KNOWN low-trust."""
        reaper = HeartbeatReaper()
        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        bridge = FederationBridge(reaper=reaper, agent_id="steward")
        result = bridge.ingest(
            OP_DELEGATE_TASK,
            {
                "title": "Help with something",
                "source_agent": "new-peer",
                "priority": 50,
            },
        )
        assert result is True

    def test_custom_trust_floor(self, tmp_path):
        reaper = HeartbeatReaper()
        peer = reaper.record_heartbeat("mid-trust", timestamp=100.0)
        peer.trust = 0.4

        task_mgr = TaskManager(project_root=tmp_path)
        ServiceRegistry.register(SVC_TASK_MANAGER, task_mgr)

        # Higher trust floor
        bridge = FederationBridge(reaper=reaper, delegation_trust_floor=0.5)
        result = bridge.ingest(
            OP_DELEGATE_TASK,
            {
                "title": "Task",
                "source_agent": "mid-trust",
            },
        )
        assert result is False


class TestPeerRecordFingerprintSerialization:
    """Fingerprint and capabilities survive serialization roundtrip."""

    def test_roundtrip_with_fingerprint(self):
        peer = PeerRecord(
            agent_id="test",
            last_seen=1000.0,
            fingerprint="fp_abc",
            fingerprint_stable_count=7,
            capabilities=("code_analysis", "web_search"),
        )
        restored = PeerRecord.from_dict(peer.to_dict())
        assert restored.fingerprint == "fp_abc"
        assert restored.fingerprint_stable_count == 7
        assert restored.capabilities == ("code_analysis", "web_search")

    def test_from_dict_missing_fingerprint_defaults(self):
        data = {"agent_id": "test", "last_seen": 100.0}
        peer = PeerRecord.from_dict(data)
        assert peer.fingerprint == ""
        assert peer.fingerprint_stable_count == 0
        assert peer.capabilities == ()
