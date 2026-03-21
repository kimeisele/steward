"""Tests for A2A Peer Discovery — Agent Card scanning."""

from __future__ import annotations

import json

from steward.a2a_discovery import A2APeerDiscovery, DiscoveredPeer


class FakeReaper:
    """Minimal HeartbeatReaper stand-in for testing."""

    def __init__(self) -> None:
        self.heartbeats: list[dict] = []

    def record_heartbeat(self, agent_id: str, **kwargs) -> None:
        self.heartbeats.append({"agent_id": agent_id, **kwargs})


# ── Persistence ────────────────────────────────────────────────────


def test_save_and_load_discovered(tmp_path):
    discovery = A2APeerDiscovery(known_peers_path=tmp_path / "known.json")
    discovery._discovered["test-agent"] = DiscoveredPeer(
        agent_id="test-agent",
        repo="org/test-agent",
        name="Test Agent",
        description="A test agent",
        skills=["code_analysis"],
        url="https://github.com/org/test-agent",
        card_type="a2a",
        capabilities=("code_analysis",),
    )

    save_path = tmp_path / "discovered.json"
    discovery.save_discovered(save_path)

    # Verify file was written
    data = json.loads(save_path.read_text())
    assert len(data) == 1
    assert data[0]["agent_id"] == "test-agent"
    assert data[0]["card_type"] == "a2a"

    # Load into new instance
    discovery2 = A2APeerDiscovery(known_peers_path=tmp_path / "known.json")
    count = discovery2.load_discovered(save_path)
    assert count == 1
    assert "test-agent" in discovery2._discovered


def test_load_nonexistent():
    discovery = A2APeerDiscovery()
    assert discovery.load_discovered(path=None) == 0


# ── Known Peers ────────────────────────────────────────────────────


def test_scan_known_peers_file_missing(tmp_path):
    discovery = A2APeerDiscovery(known_peers_path=tmp_path / "missing.json")
    # Should not crash
    peers = discovery._scan_known_peers()
    assert peers == []


def test_scan_known_peers_empty_list(tmp_path):
    path = tmp_path / "known_peers.json"
    path.write_text("[]")
    discovery = A2APeerDiscovery(known_peers_path=path)
    peers = discovery._scan_known_peers()
    assert peers == []


# ── Agent Card Parsing ─────────────────────────────────────────────


def test_parse_a2a_card():
    discovery = A2APeerDiscovery()
    card = {
        "name": "AgentCity",
        "description": "Multi-agent simulation",
        "url": "https://github.com/org/agent-city",
        "skills": [
            {"id": "simulation", "name": "Simulation"},
            {"id": "analysis", "name": "Analysis"},
        ],
    }

    peer = discovery._parse_agent_card("org/agent-city", card, "a2a")

    assert peer.agent_id == "agent-city"
    assert peer.repo == "org/agent-city"
    assert peer.name == "AgentCity"
    assert peer.card_type == "a2a"
    assert peer.skills == ["simulation", "analysis"]
    assert peer.capabilities == ("simulation", "analysis")


def test_parse_steward_card():
    discovery = A2APeerDiscovery()
    card = {
        "display_name": "Agent City",
        "capabilities": ["code_analysis", "task_execution"],
        "status": "active",
    }

    peer = discovery._parse_agent_card("org/agent-city", card, "steward")

    assert peer.agent_id == "agent-city"
    assert peer.card_type == "steward"
    assert peer.capabilities == ("code_analysis", "task_execution")


# ── Register Peer with Reaper ──────────────────────────────────────


def test_register_peer():
    reaper = FakeReaper()
    discovery = A2APeerDiscovery(reaper=reaper)

    peer = DiscoveredPeer(
        agent_id="test-peer",
        repo="org/test-peer",
        name="Test Peer",
        description="",
        skills=["healing"],
        url="",
        card_type="a2a",
        capabilities=("healing",),
    )

    discovery._register_peer(peer)

    assert len(reaper.heartbeats) == 1
    hb = reaper.heartbeats[0]
    assert hb["agent_id"] == "test-peer"
    assert hb["source"] == "a2a_discovery"
    assert hb["capabilities"] == ("healing",)
    assert hb["fingerprint"] == "a2a:org/test-peer"


def test_register_peer_no_reaper():
    discovery = A2APeerDiscovery(reaper=None)
    peer = DiscoveredPeer(
        agent_id="x",
        repo="org/x",
        name="X",
        description="",
        skills=[],
        url="",
        card_type="a2a",
    )
    # Should not crash
    discovery._register_peer(peer)


# ── Stats ──────────────────────────────────────────────────────────


def test_stats_empty():
    discovery = A2APeerDiscovery()
    stats = discovery.stats()

    assert stats["discovered_peers"] == 0
    assert stats["scan_count"] == 0
    assert stats["by_type"]["a2a"] == 0


def test_stats_with_peers():
    discovery = A2APeerDiscovery()
    discovery._discovered["a"] = DiscoveredPeer(
        agent_id="a", repo="", name="", description="", skills=[], url="", card_type="a2a"
    )
    discovery._discovered["b"] = DiscoveredPeer(
        agent_id="b", repo="", name="", description="", skills=[], url="", card_type="steward"
    )

    stats = discovery.stats()
    assert stats["discovered_peers"] == 2
    assert stats["by_type"]["a2a"] == 1
    assert stats["by_type"]["steward"] == 1


# ── Throttling ─────────────────────────────────────────────────────


def test_scan_throttled_without_token():
    discovery = A2APeerDiscovery()
    discovery._token = ""  # No token
    result = discovery.scan()
    assert result == []


def test_scan_throttled_by_interval():
    discovery = A2APeerDiscovery()
    discovery._token = "fake-token"
    discovery._last_scan = 999999999999.0  # Far in the future
    result = discovery.scan()
    assert result == []
