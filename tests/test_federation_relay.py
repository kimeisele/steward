"""Tests for federation_relay — GitHub API bridge for cross-repo messaging."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from steward.federation_relay import GitHubFederationRelay


class TestRelayInit:
    def test_default_config(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "test-token"}):
            relay = GitHubFederationRelay(agent_id="steward")
        assert relay._agent_id == "steward"
        assert relay.available is True

    def test_unavailable_without_token(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(GitHubFederationRelay, "_load_token", return_value=""):
                relay = GitHubFederationRelay(agent_id="test")
        assert relay.available is False

    def test_stats(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}):
            relay = GitHubFederationRelay(agent_id="test")
        stats = relay.stats()
        assert stats["available"] is True
        assert stats["pull_count"] == 0
        assert stats["push_count"] == 0
        assert stats["errors"] == 0


class TestPullFromHub:
    def test_throttled_on_quick_successive_calls(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}):
            relay = GitHubFederationRelay(agent_id="steward")

        relay._last_pull = 999999999999.0  # far future — throttle should trigger
        result = relay.pull_from_hub()
        assert result == 0

    def test_no_token_returns_zero(self):
        with patch.object(GitHubFederationRelay, "_load_token", return_value=""):
            relay = GitHubFederationRelay(agent_id="test")
        result = relay.pull_from_hub()
        assert result == 0

    def test_pull_deduplicates_messages(self, tmp_path):
        """Messages with same (source, timestamp) are not duplicated."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}):
            relay = GitHubFederationRelay(
                agent_id="steward",
                local_inbox=tmp_path / "inbox.json",
            )
        relay._last_pull = 0  # allow pull

        # Pre-populate local inbox with an existing message
        existing = [{"source": "agent-city", "timestamp": 100, "op": "heartbeat"}]
        (tmp_path / "inbox.json").write_text(json.dumps(existing))

        # Mock _get_file to return hub messages including the duplicate
        hub_messages = [
            {"source": "agent-city", "timestamp": 100, "target": "steward", "op": "heartbeat"},
            {"source": "agent-world", "timestamp": 200, "target": "steward", "op": "task"},
        ]
        with patch.object(relay, "_get_file", return_value=(hub_messages, "sha123")):
            count = relay.pull_from_hub()

        # Only the new message should be added
        assert count == 1
        inbox = json.loads((tmp_path / "inbox.json").read_text())
        assert len(inbox) == 2

    def test_pull_filters_by_target(self, tmp_path):
        """Only messages targeted at this agent (or '*') are pulled."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}):
            relay = GitHubFederationRelay(
                agent_id="steward",
                local_inbox=tmp_path / "inbox.json",
            )
        relay._last_pull = 0

        hub_messages = [
            {"source": "agent-city", "timestamp": 100, "target": "steward", "op": "task"},
            {"source": "agent-city", "timestamp": 200, "target": "other-agent", "op": "task"},
            {"source": "agent-city", "timestamp": 300, "target": "*", "op": "broadcast"},
        ]
        with patch.object(relay, "_get_file", return_value=(hub_messages, "sha123")):
            count = relay.pull_from_hub()

        assert count == 2  # steward + broadcast, not other-agent


class TestPushToHub:
    def test_no_token_returns_zero(self):
        with patch.object(GitHubFederationRelay, "_load_token", return_value=""):
            relay = GitHubFederationRelay(agent_id="test")
        assert relay.push_to_hub() == 0

    def test_throttled_returns_zero(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}):
            relay = GitHubFederationRelay(agent_id="test")
        relay._last_push = 999999999999.0
        assert relay.push_to_hub() == 0

    def test_empty_outbox_returns_zero(self, tmp_path):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}):
            relay = GitHubFederationRelay(
                agent_id="steward",
                local_outbox=tmp_path / "outbox.json",
            )
        relay._last_push = 0
        # No outbox file exists
        assert relay.push_to_hub() == 0

    def test_push_clears_outbox_on_success(self, tmp_path):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}):
            relay = GitHubFederationRelay(
                agent_id="steward",
                local_outbox=tmp_path / "outbox.json",
            )
        relay._last_push = 0

        # Create outbox with messages
        outbox = [{"source": "steward", "timestamp": 100, "op": "heartbeat"}]
        (tmp_path / "outbox.json").write_text(json.dumps(outbox))

        # Mock hub interactions
        with patch.object(relay, "_get_file", return_value=([], "sha123")):
            with patch.object(relay, "_put_file", return_value=True):
                count = relay.push_to_hub()

        assert count == 1
        # Outbox should be cleared
        remaining = json.loads((tmp_path / "outbox.json").read_text())
        assert remaining == []
