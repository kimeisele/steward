"""Tests for federation_relay — GitHub API bridge for cross-repo messaging."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

from steward.federation_relay import DeliveryReceipt, GitHubFederationRelay


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

        # Mock _get_file: first call = outbox, second call = inbox (empty)
        hub_messages = [
            {"source": "agent-city", "timestamp": 100, "target": "steward", "op": "heartbeat"},
            {"source": "agent-world", "timestamp": 200, "target": "steward", "op": "task"},
        ]
        with patch.object(relay, "_get_file", side_effect=[(hub_messages, "sha123"), ([], "sha456")]):
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
        # first call = outbox (has messages), second call = inbox (empty)
        with patch.object(relay, "_get_file", side_effect=[(hub_messages, "sha123"), ([], "sha456")]):
            count = relay.pull_from_hub()

        assert count == 2  # steward + broadcast, not other-agent

    def test_pull_reads_both_outbox_and_inbox(self, tmp_path):
        """Messages from hub inbox (agent-city convention) are also pulled."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}):
            relay = GitHubFederationRelay(
                agent_id="steward",
                local_inbox=tmp_path / "inbox.json",
            )
        relay._last_pull = 0

        outbox_msgs = [
            {"source": "agent-world", "timestamp": 100, "target": "steward", "operation": "heartbeat"},
        ]
        inbox_msgs = [
            {"source": "agent-city", "timestamp": 200, "target": "steward-protocol", "operation": "pr_review_request"},
        ]
        with patch.object(relay, "_get_file", side_effect=[(outbox_msgs, "sha1"), (inbox_msgs, "sha2")]):
            count = relay.pull_from_hub()

        # Both messages pulled: one from outbox (exact match), one from inbox (substring match)
        assert count == 2
        inbox = json.loads((tmp_path / "inbox.json").read_text())
        assert len(inbox) == 2
        ops = {m["operation"] for m in inbox}
        assert "heartbeat" in ops
        assert "pr_review_request" in ops


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


# ── Delivery Receipt Tracking ──────────────────────────────────────


class TestDeliveryReceipt:
    def test_receipt_creation(self):
        receipt = DeliveryReceipt(
            batch_id="batch-1",
            target="agent-city",
            message_ids=["msg-1", "msg-2"],
            pushed_at=time.time(),
        )
        assert receipt.target == "agent-city"
        assert receipt.confirmed is False
        assert len(receipt.message_ids) == 2

    def test_receipt_to_dict(self):
        receipt = DeliveryReceipt(
            batch_id="b1",
            target="peer",
            message_ids=["m1"],
            pushed_at=100.0,
        )
        d = receipt.to_dict()
        assert d["batch_id"] == "b1"
        assert d["confirmed"] is False

    def test_push_creates_receipts(self, tmp_path):
        """Pushing messages creates delivery receipts for tracking."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}):
            relay = GitHubFederationRelay(
                agent_id="steward",
                local_outbox=tmp_path / "outbox.json",
            )
        relay._last_push = 0

        # Create outbox with targeted messages (not broadcast)
        outbox = [
            {"source": "steward", "target": "agent-city", "timestamp": 100, "id": "msg-1", "operation": "heartbeat"},
            {"source": "steward", "target": "agent-city", "timestamp": 101, "id": "msg-2", "operation": "heartbeat"},
        ]
        (tmp_path / "outbox.json").write_text(json.dumps(outbox))

        with patch.object(relay, "_get_file", return_value=([], "sha123")):
            with patch.object(relay, "_put_file", return_value=True):
                relay.push_to_hub()

        # Should have created a receipt for agent-city
        assert len(relay._pending_receipts) == 1
        receipt = relay._pending_receipts[0]
        assert receipt.target == "agent-city"
        assert receipt.message_ids == ["msg-1", "msg-2"]
        assert receipt.confirmed is False

    def test_pull_confirms_receipts(self, tmp_path):
        """Receiving a response from a peer confirms delivery receipts."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}):
            relay = GitHubFederationRelay(
                agent_id="steward",
                local_inbox=tmp_path / "inbox.json",
            )
        relay._last_pull = 0

        # Add a pending receipt for agent-city
        receipt = DeliveryReceipt(
            batch_id="b1",
            target="agent-city",
            message_ids=["m1"],
            pushed_at=time.time(),
        )
        relay._pending_receipts.append(receipt)

        # Pull a response from agent-city (implicit ack)
        response = [
            {"source": "agent-city", "target": "steward", "timestamp": 200, "operation": "heartbeat"},
        ]
        with patch.object(relay, "_get_file", side_effect=[(response, "sha1"), ([], "sha2")]):
            relay.pull_from_hub()

        # Receipt should now be confirmed
        assert receipt.confirmed is True

    def test_stale_receipts(self):
        """Receipts older than RECEIPT_TTL_S without confirmation are stale."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}):
            relay = GitHubFederationRelay(agent_id="steward")

        old_receipt = DeliveryReceipt(
            batch_id="old",
            target="dead-peer",
            message_ids=["m1"],
            pushed_at=time.time() - relay.RECEIPT_TTL_S - 1,  # expired
        )
        fresh_receipt = DeliveryReceipt(
            batch_id="fresh",
            target="alive-peer",
            message_ids=["m2"],
            pushed_at=time.time(),  # still fresh
        )
        relay._pending_receipts = [old_receipt, fresh_receipt]

        stale = relay.stale_receipts()
        assert len(stale) == 1
        assert stale[0].target == "dead-peer"

        pending = relay.pending_receipts()
        assert len(pending) == 1
        assert pending[0].target == "alive-peer"

    def test_stats_include_receipts(self):
        """Stats expose receipt tracking metrics."""
        with patch.dict("os.environ", {"GITHUB_TOKEN": "tok"}):
            relay = GitHubFederationRelay(agent_id="steward")

        relay._pending_receipts = [
            DeliveryReceipt("b1", "dead-peer", ["m1"], time.time() - 7200),
        ]

        stats = relay.stats()
        assert stats["stale_receipts"] == 1
        assert "dead-peer" in stats["stale_targets"]
