"""Tests for BuddyBubbleTool — system introspection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from steward.tools.buddy_bubble import ACTIONS, BuddyBubbleTool

# ── Fakes ─────────────────────────────────────────────────────────────


@dataclass
class FakePeer:
    agent_id: str = "peer-1"
    trust: float = 0.8
    heartbeat_count: int = 5
    capabilities: tuple[str, ...] = ("code_analysis",)
    fingerprint: str = "abcdef1234567890abcdef"
    last_seen: float = 1700000000.0
    status: str = "alive"


class FakeReaper:
    def stats(self):
        return {"total_peers": 2, "alive": 1, "suspect": 1, "dead": 0}

    def alive_peers(self):
        return [FakePeer()]

    def suspect_peers(self):
        return [FakePeer(agent_id="peer-2", trust=0.3, status="suspect")]

    def dead_peers(self):
        return []


class FakeMarketplace:
    def stats(self):
        return {"active_claims": 1, "unique_agents": 1}

    def list_claims(self):
        return [FakeClaim()]


@dataclass
class FakeClaim:
    slot_id: str = "task:fix-ci"
    agent_id: str = "steward"
    trust_at_claim: float = 0.9
    ttl_s: float = 600.0
    renewals: int = 0
    timestamp: float = 1700000000.0


class FakeBridge:
    agent_id = "steward"
    _outbox: list = []
    _dispatch: dict = {"heartbeat": None, "delegate_task": None}


class FakeAttention:
    def stats(self):
        @dataclass
        class AttStats:
            mechanism: str = "Lotus O(1)"
            registered_intents: int = 15
            queries_resolved: int = 42
            cache_hits: int = 38
            estimated_ops_saved: int = 570

        return AttStats()


class FakeSynapseStore:
    def get_weights(self):
        return {
            "trigger:test_fail": {"action:run_test": 0.9, "action:debug": 0.4},
            "trigger:lint_fail": {"action:autofix": 0.7},
        }


class FakeTransport:
    def stats(self):
        return {"buffer_size": 144, "pending": 3}


class FakeA2A:
    def stats(self):
        return {"active_tasks": 0, "completed": 5}


# ── Registry helper ───────────────────────────────────────────────────


def _make_registry(overrides: dict | None = None):
    """Return a get() function that returns fakes for known SVC_ keys."""
    from steward import services as svc

    defaults = {
        svc.SVC_REAPER: FakeReaper(),
        svc.SVC_MARKETPLACE: FakeMarketplace(),
        svc.SVC_FEDERATION: FakeBridge(),
        svc.SVC_ATTENTION: FakeAttention(),
        svc.SVC_SYNAPSE_STORE: FakeSynapseStore(),
        svc.SVC_FEDERATION_TRANSPORT: FakeTransport(),
        svc.SVC_A2A_ADAPTER: FakeA2A(),
        svc.SVC_PROVIDER: None,
    }
    if overrides:
        defaults.update(overrides)

    def fake_get(key, default=None):
        return defaults.get(key, default)

    return fake_get


# ── Context bridge mock data ──────────────────────────────────────────

CB_HEALTH = {"value": 0.85, "guna": "sattva", "provider_health": 0.9, "error_pressure": 0.1}
CB_FEDERATION = {"total_peers": 2, "alive": 1, "suspect": 1, "dead": 0}
CB_IMMUNE = {"heals_attempted": 3, "heals_succeeded": 2}
CB_CETANA = {"heartbeat_count": 42, "phase": "KARMA"}


# ── Tool basics ───────────────────────────────────────────────────────


def test_tool_name_and_description():
    tool = BuddyBubbleTool()
    assert tool.name == "buddy_bubble"
    assert "substrate" in tool.description.lower()


def test_tool_schema_has_action():
    tool = BuddyBubbleTool()
    schema = tool.parameters_schema
    assert "action" in schema
    assert schema["action"]["required"] is True
    assert set(schema["action"]["enum"]) == set(ACTIONS)


def test_validate_rejects_missing_action():
    tool = BuddyBubbleTool()
    with pytest.raises(ValueError, match="action is required"):
        tool.validate({})


def test_validate_rejects_unknown_action():
    tool = BuddyBubbleTool()
    with pytest.raises(ValueError, match="Unknown action"):
        tool.validate({"action": "nonexistent"})


def test_validate_accepts_all_actions():
    tool = BuddyBubbleTool()
    for action in ACTIONS:
        tool.validate({"action": action})


# ── peers ─────────────────────────────────────────────────────────────


def test_peers_returns_all_states():
    tool = BuddyBubbleTool()
    with (
        patch("steward.tools.buddy_bubble.ServiceRegistry") as mock_reg,
        patch("steward.tools.buddy_bubble._cb_federation", return_value=CB_FEDERATION),
    ):
        mock_reg.get = _make_registry()
        result = tool.execute({"action": "peers"})

    assert result.success is True
    data = json.loads(result.output)
    assert data["total_peers"] == 2
    assert len(data["alive"]) == 1
    assert data["alive"][0]["agent_id"] == "peer-1"
    assert len(data["suspect"]) == 1


def test_peers_truncates_fingerprint():
    tool = BuddyBubbleTool()
    with (
        patch("steward.tools.buddy_bubble.ServiceRegistry") as mock_reg,
        patch("steward.tools.buddy_bubble._cb_federation", return_value=CB_FEDERATION),
    ):
        mock_reg.get = _make_registry()
        result = tool.execute({"action": "peers"})

    data = json.loads(result.output)
    fp = data["alive"][0]["fingerprint"]
    assert fp.endswith("...")
    assert len(fp) == 19  # 16 + "..."


def test_peers_no_reaper():
    tool = BuddyBubbleTool()
    from steward import services as svc

    with (
        patch("steward.tools.buddy_bubble.ServiceRegistry") as mock_reg,
        patch("steward.tools.buddy_bubble._cb_federation", return_value={}),
    ):
        mock_reg.get = _make_registry({svc.SVC_REAPER: None})
        result = tool.execute({"action": "peers"})

    assert result.success is True
    data = json.loads(result.output)
    assert "error" in data


# ── signals ───────────────────────────────────────────────────────────


def test_signals_shows_a2a_and_transport():
    tool = BuddyBubbleTool()
    with patch("steward.tools.buddy_bubble.ServiceRegistry") as mock_reg:
        mock_reg.get = _make_registry()
        result = tool.execute({"action": "signals"})

    assert result.success is True
    data = json.loads(result.output)
    assert data["a2a"]["active_tasks"] == 0
    assert data["nadi_transport"]["pending"] == 3


# ── substrate ─────────────────────────────────────────────────────────


def test_substrate_shows_attention_and_synapse():
    tool = BuddyBubbleTool()
    with patch("steward.tools.buddy_bubble.ServiceRegistry") as mock_reg:
        mock_reg.get = _make_registry()
        result = tool.execute({"action": "substrate"})

    assert result.success is True
    data = json.loads(result.output)
    assert data["attention"]["mechanism"] == "Lotus O(1)"
    assert data["attention"]["registered_intents"] == 15
    assert data["synapse"]["total_triggers"] == 2
    assert data["synapse"]["total_connections"] == 3
    assert data["synapse"]["top_10"][0]["weight"] == 0.9


# ── marketplace ───────────────────────────────────────────────────────


def test_marketplace_shows_claims():
    tool = BuddyBubbleTool()
    with patch("steward.tools.buddy_bubble.ServiceRegistry") as mock_reg:
        mock_reg.get = _make_registry()
        result = tool.execute({"action": "marketplace"})

    assert result.success is True
    data = json.loads(result.output)
    assert data["active_claims"] == 1
    assert data["claims"][0]["slot_id"] == "task:fix-ci"


# ── health ────────────────────────────────────────────────────────────


def test_health_delegates_to_context_bridge():
    """Health action should delegate to context_bridge readers."""
    tool = BuddyBubbleTool()
    with (
        patch("steward.tools.buddy_bubble._cb_health", return_value=CB_HEALTH),
        patch("steward.tools.buddy_bubble._cb_cetana", return_value=CB_CETANA),
        patch("steward.tools.buddy_bubble._cb_immune", return_value=CB_IMMUNE),
    ):
        result = tool.execute({"action": "health"})

    assert result.success is True
    data = json.loads(result.output)
    # Base health from context_bridge
    assert data["value"] == 0.85
    assert data["guna"] == "sattva"
    # Enriched with cetana
    assert data["cetana"]["heartbeat_count"] == 42
    # Enriched with immune
    assert data["immune"]["heals_attempted"] == 3


def test_health_graceful_when_context_bridge_empty():
    """Health works even when context_bridge returns empty dicts."""
    tool = BuddyBubbleTool()
    with (
        patch("steward.tools.buddy_bubble._cb_health", return_value={}),
        patch("steward.tools.buddy_bubble._cb_cetana", return_value={}),
        patch("steward.tools.buddy_bubble._cb_immune", return_value={}),
    ):
        result = tool.execute({"action": "health"})

    assert result.success is True


# ── status ────────────────────────────────────────────────────────────


def test_status_includes_north_star():
    tool = BuddyBubbleTool()
    with (
        patch("steward.tools.buddy_bubble.ServiceRegistry") as mock_reg,
        patch("steward.tools.buddy_bubble._cb_health", return_value=CB_HEALTH),
        patch("steward.tools.buddy_bubble._cb_cetana", return_value={}),
        patch("steward.tools.buddy_bubble._cb_immune", return_value={}),
        patch("steward.tools.buddy_bubble._cb_federation", return_value=CB_FEDERATION),
    ):
        mock_reg.get = _make_registry()
        result = tool.execute({"action": "status"})

    assert result.success is True
    data = json.loads(result.output)
    assert "north_star" in data
    assert "services" in data
    assert "health" in data
    assert "federation" in data


# ── federation ────────────────────────────────────────────────────────


def test_federation_shows_bridge_details():
    tool = BuddyBubbleTool()
    with (
        patch("steward.tools.buddy_bubble.ServiceRegistry") as mock_reg,
        patch("steward.tools.buddy_bubble._cb_federation", return_value=CB_FEDERATION),
    ):
        mock_reg.get = _make_registry()
        result = tool.execute({"action": "federation"})

    assert result.success is True
    data = json.loads(result.output)
    assert data["bridge"]["agent_id"] == "steward"
    assert "heartbeat" in data["bridge"]["operations"]


# ── Error handling ────────────────────────────────────────────────────


def test_handler_exception_returns_failure():
    tool = BuddyBubbleTool()
    with patch("steward.tools.buddy_bubble._HANDLERS", {"status": lambda: 1 / 0}):
        result = tool.execute({"action": "status"})

    assert result.success is False
    assert "Introspection failed" in result.error


# ── Output is valid JSON ─────────────────────────────────────────────


@pytest.mark.parametrize("action", list(ACTIONS))
def test_all_actions_return_valid_json(action):
    tool = BuddyBubbleTool()
    with (
        patch("steward.tools.buddy_bubble.ServiceRegistry") as mock_reg,
        patch("steward.tools.buddy_bubble._cb_health", return_value=CB_HEALTH),
        patch("steward.tools.buddy_bubble._cb_cetana", return_value={}),
        patch("steward.tools.buddy_bubble._cb_immune", return_value={}),
        patch("steward.tools.buddy_bubble._cb_federation", return_value=CB_FEDERATION),
    ):
        mock_reg.get = _make_registry()
        result = tool.execute({"action": action})

    assert result.success is True
    parsed = json.loads(result.output)
    assert isinstance(parsed, dict)
