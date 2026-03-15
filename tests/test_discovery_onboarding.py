"""Tests for Phase 1: Federation Onboarding — discovery, descriptor, heartbeat enrichment."""

import json
import time
from pathlib import Path
from unittest.mock import patch

from steward.federation import OP_HEARTBEAT, FederationBridge
from steward.hooks.dharma import DharmaFederationHook
from steward.identity import StewardIdentity
from steward.reaper import HeartbeatReaper

STEWARD_ROOT = Path(__file__).resolve().parents[1]


class TestFederationDescriptor:
    """`.well-known/agent-federation.json` is valid and matches schema."""

    def test_descriptor_exists(self):
        path = STEWARD_ROOT / ".well-known" / "agent-federation.json"
        assert path.exists(), f"Missing {path}"

    def test_descriptor_is_valid_json(self):
        path = STEWARD_ROOT / ".well-known" / "agent-federation.json"
        data = json.loads(path.read_text())
        assert isinstance(data, dict)

    def test_descriptor_has_required_fields(self):
        path = STEWARD_ROOT / ".well-known" / "agent-federation.json"
        data = json.loads(path.read_text())
        assert data["kind"] == "agent_federation_descriptor"
        assert data["version"] == 1
        assert data["repo_id"] == "steward"
        assert data["status"] == "active"
        assert "authority_feed_manifest_url" in data
        assert "projection_intents" in data
        assert "owner_boundary" in data

    def test_descriptor_display_name(self):
        path = STEWARD_ROOT / ".well-known" / "agent-federation.json"
        data = json.loads(path.read_text())
        assert "Steward" in data["display_name"]

    def test_descriptor_authority_feed_url_pattern(self):
        path = STEWARD_ROOT / ".well-known" / "agent-federation.json"
        data = json.loads(path.read_text())
        url = data["authority_feed_manifest_url"]
        assert "raw.githubusercontent.com" in url
        assert "kimeisele/steward" in url
        assert "authority-feed" in url


class TestCharterDocument:
    """docs/authority/charter.md exists and has content."""

    def test_charter_exists(self):
        path = STEWARD_ROOT / "docs" / "authority" / "charter.md"
        assert path.exists()

    def test_charter_has_content(self):
        path = STEWARD_ROOT / "docs" / "authority" / "charter.md"
        content = path.read_text()
        assert len(content) > 100
        assert "Steward" in content


class TestAuthorityFeedScript:
    """scripts/export_authority_feed.py is valid Python."""

    def test_script_exists(self):
        path = STEWARD_ROOT / "scripts" / "export_authority_feed.py"
        assert path.exists()

    def test_script_imports(self):
        path = STEWARD_ROOT / "scripts" / "export_authority_feed.py"
        code = path.read_text()
        compile(code, str(path), "exec")  # Syntax check


class TestHeartbeatEnrichment:
    """DharmaFederationHook emits enriched heartbeat payloads."""

    def test_heartbeat_includes_capabilities(self):
        reaper = HeartbeatReaper()
        bridge = FederationBridge(reaper=reaper, agent_id="steward-test")

        # Simulate what DharmaFederationHook does
        bridge.emit(
            OP_HEARTBEAT,
            {
                "agent_id": "steward-test",
                "health": 0.85,
                "timestamp": time.time(),
                "capabilities": ["code_analysis", "task_execution"],
                "repo": "kimeisele/steward",
                "version": "0.17.0",
                "fingerprint": "abc123",
            },
        )

        event = bridge._outbound[0]
        assert "capabilities" in event.payload
        assert "repo" in event.payload
        assert "version" in event.payload
        assert "fingerprint" in event.payload

    def test_enriched_heartbeat_parsed_by_bridge(self):
        reaper = HeartbeatReaper()
        bridge = FederationBridge(reaper=reaper)

        bridge.ingest(
            OP_HEARTBEAT,
            {
                "agent_id": "peer-1",
                "timestamp": time.time(),
                "capabilities": ["web_search", "wiki_sync"],
                "fingerprint": "fp123",
            },
        )

        peer = reaper.get_peer("peer-1")
        assert peer is not None
        assert "web_search" in peer.capabilities
        assert "wiki_sync" in peer.capabilities
        assert peer.fingerprint == "fp123"

    def test_dharma_hook_loads_peer_capabilities(self):
        """DharmaFederationHook reads capabilities from peer.json."""
        hook = DharmaFederationHook()
        # Force-clear cached capabilities
        hook._capabilities = None

        # Mock the peer.json read
        mock_data = json.dumps({"capabilities": ["code_analysis", "ci_automation"]})
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value=mock_data):
                caps = hook._get_capabilities()

        assert "code_analysis" in caps
        assert "ci_automation" in caps

    def test_dharma_hook_caches_capabilities(self):
        """Capabilities are loaded once, not on every heartbeat."""
        hook = DharmaFederationHook()
        hook._capabilities = ("cached_cap",)
        assert hook._get_capabilities() == ("cached_cap",)


class TestStewardIdentity:
    """StewardIdentity deterministic fingerprint."""

    def test_fingerprint_is_deterministic(self):
        fp1 = StewardIdentity.compute_fingerprint("steward", "repo", "seed123")
        fp2 = StewardIdentity.compute_fingerprint("steward", "repo", "seed123")
        assert fp1 == fp2

    def test_different_seed_different_fingerprint(self):
        fp1 = StewardIdentity.compute_fingerprint("steward", "repo", "seed1")
        fp2 = StewardIdentity.compute_fingerprint("steward", "repo", "seed2")
        assert fp1 != fp2

    def test_from_environment_uses_env_var(self):
        with patch.dict("os.environ", {"STEWARD_IDENTITY_SEED": "test_seed_42"}):
            identity = StewardIdentity.from_environment()
        assert identity.agent_id == "steward"
        assert identity.repo == "kimeisele/steward"
        assert identity.fingerprint  # non-empty
        # Verify deterministic
        expected = StewardIdentity.compute_fingerprint("steward", "kimeisele/steward", "test_seed_42")
        assert identity.fingerprint == expected

    def test_to_dict(self):
        identity = StewardIdentity(
            agent_id="test",
            repo="test/repo",
            version="1.0",
            fingerprint="abc",
        )
        d = identity.to_dict()
        assert d["agent_id"] == "test"
        assert d["fingerprint"] == "abc"
