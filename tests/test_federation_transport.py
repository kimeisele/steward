"""Tests for federation transports — Nadi and filesystem.

Validates:
  - NadiFederationTransport (self-hosted: read own inbox, write own outbox)
  - FilesystemFederationTransport (legacy shared-directory)
  - create_transport() selects best available transport
  - Both satisfy FederationTransport protocol (read_outbox, append_to_inbox)
"""

import hashlib
import json

from steward.federation_crypto import verify_payload_signature
from steward.federation_transport import (
    FilesystemFederationTransport,
    NadiFederationTransport,
    create_transport,
)


class TestFilesystemTransport:
    """Round-trip read/write via filesystem (legacy)."""

    def test_append_to_inbox_creates_file(self, tmp_path):
        transport = FilesystemFederationTransport(str(tmp_path))
        count = transport.append_to_inbox([{"op": "heartbeat", "agent": "test"}])
        assert count == 1
        inbox_files = list((tmp_path / "inbox").glob("*.json"))
        assert len(inbox_files) == 1

    def test_read_outbox_empty(self, tmp_path):
        transport = FilesystemFederationTransport(str(tmp_path))
        assert transport.read_outbox() == []

    def test_read_outbox_consumes_files(self, tmp_path):
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        (outbox / "001.json").write_text(json.dumps([{"op": "heartbeat"}]))
        transport = FilesystemFederationTransport(str(tmp_path))
        messages = transport.read_outbox()
        assert len(messages) == 1
        assert messages[0]["op"] == "heartbeat"
        # File consumed
        assert list(outbox.glob("*.json")) == []

    def test_round_trip(self, tmp_path):
        """Write to inbox, then read from outbox (simulates two agents)."""
        agent_a = FilesystemFederationTransport(str(tmp_path))
        # Agent A writes to inbox
        agent_a.append_to_inbox([{"source": "a", "operation": "heartbeat"}])

        # Move file from inbox to outbox (simulates transport relay)
        inbox = tmp_path / "inbox"
        outbox = tmp_path / "outbox"
        outbox.mkdir(exist_ok=True)
        for f in inbox.glob("*.json"):
            f.rename(outbox / f.name)

        # Agent B reads from outbox
        agent_b = FilesystemFederationTransport(str(tmp_path))
        messages = agent_b.read_outbox()
        assert len(messages) == 1
        assert messages[0]["source"] == "a"

    def test_read_outbox_handles_corrupt_json(self, tmp_path):
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        (outbox / "bad.json").write_text("NOT JSON{{{")
        transport = FilesystemFederationTransport(str(tmp_path))
        messages = transport.read_outbox()
        assert messages == []

    def test_append_empty_list(self, tmp_path):
        transport = FilesystemFederationTransport(str(tmp_path))
        count = transport.append_to_inbox([])
        assert count == 0
        assert not (tmp_path / "inbox").exists()

    def test_read_outbox_single_dict(self, tmp_path):
        """Single dict (not list) in file."""
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        (outbox / "001.json").write_text(json.dumps({"op": "claim"}))
        transport = FilesystemFederationTransport(str(tmp_path))
        messages = transport.read_outbox()
        assert len(messages) == 1
        assert messages[0]["op"] == "claim"

    def test_multiple_outbox_files_sorted(self, tmp_path):
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        (outbox / "002.json").write_text(json.dumps([{"seq": 2}]))
        (outbox / "001.json").write_text(json.dumps([{"seq": 1}]))
        transport = FilesystemFederationTransport(str(tmp_path))
        messages = transport.read_outbox()
        assert messages[0]["seq"] == 1
        assert messages[1]["seq"] == 2


class TestNadiFederationTransport:
    """NadiFederationTransport — self-hosted semantics.

    Self-hosted: read OUR inbox (nadi_inbox.json), write OUR outbox (nadi_outbox.json).
    """

    def test_init_has_paths(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        assert hasattr(transport, "_inbox")
        assert hasattr(transport, "_outbox")

    def test_init_generates_local_keypair(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))

        assert (tmp_path / ".node_keys.json").exists()
        keys = json.loads((tmp_path / ".node_keys.json").read_text())
        assert keys["public_key"] == transport.public_key
        assert keys["node_id"] == transport.node_id
        assert transport.node_id.startswith("ag_")

    def test_read_outbox_empty(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        assert transport.read_outbox() == []

    def test_append_to_inbox_writes_outbox(self, tmp_path):
        """append_to_inbox writes OUR outbox (nadi_outbox.json)."""
        transport = NadiFederationTransport(str(tmp_path))
        count = transport.append_to_inbox(
            [
                {
                    "source": "steward",
                    "target": "agent-city",
                    "operation": "heartbeat",
                    "payload": {"health": 0.9},
                }
            ]
        )
        assert count == 1
        # Self-hosted: append_to_inbox writes to nadi_outbox.json
        outbox_path = tmp_path / "nadi_outbox.json"
        assert outbox_path.exists()
        data = json.loads(outbox_path.read_text())
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["operation"] == "heartbeat"
        assert data[0]["source"] == transport.node_id
        assert isinstance(data[0]["message_id"], str)
        assert len(data[0]["payload_hash"]) == 64
        assert isinstance(data[0]["signature"], str)

    def test_append_to_inbox_signs_payload_hash(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        payload = {"health": 0.9}

        transport.append_to_inbox(
            [
                {
                    "source": "steward",
                    "target": "agent-city",
                    "operation": "heartbeat",
                    "payload": payload,
                }
            ]
        )

        data = json.loads((tmp_path / "nadi_outbox.json").read_text())
        msg = data[0]
        assert verify_payload_signature(transport.public_key, msg["payload_hash"], msg["signature"])

    def test_read_outbox_quarantines_integrity_mismatch(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        inbox_path = tmp_path / "nadi_inbox.json"
        payload = {"task_title": "fix tests"}
        inbox_path.write_text(
            json.dumps(
                [
                    {
                        "source": "agent-city",
                        "target": "steward",
                        "operation": "task_completed",
                        "payload": payload,
                        "message_id": "msg-1",
                        "payload_hash": "bad-hash",
                    }
                ]
            )
        )

        messages = transport.read_outbox()

        assert messages == []
        quarantine_files = [path for path in (tmp_path / "quarantine").glob("*.json") if path.name != "index.json"]
        assert len(quarantine_files) == 1
        record = json.loads(quarantine_files[0].read_text())
        assert record["stage"] == "transport_inbound_verify"
        assert record["reason"] == "integrity_check_failed"

    def test_round_trip_via_nadi_files(self, tmp_path):
        """Write outbound, simulate inbound, read back."""
        transport = NadiFederationTransport(str(tmp_path))

        # Write outbound (goes to nadi_outbox.json)
        transport.append_to_inbox(
            [
                {
                    "source": "steward",
                    "target": "agent-city",
                    "operation": "delegate_task",
                    "payload": {"title": "fix tests"},
                }
            ]
        )

        # Simulate another agent delivering messages to our inbox
        inbox_path = tmp_path / "nadi_inbox.json"
        payload = {"task_title": "fix tests", "pr_url": "https://github.com/test/pr/1"}
        inbox_path.write_text(
            json.dumps(
                [
                    {
                        "source": "agent-city",
                        "target": "steward",
                        "operation": "task_completed",
                        "payload": payload,
                        "message_id": "msg-1",
                        "payload_hash": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                    }
                ]
            )
        )

        # read_outbox reads from nadi_inbox.json (inbound messages)
        messages = transport.read_outbox()
        assert len(messages) == 1
        assert messages[0]["operation"] == "task_completed"
        assert messages[0]["payload"]["pr_url"] == "https://github.com/test/pr/1"

    def test_read_outbox_quarantines_malformed_items(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        inbox_path = tmp_path / "nadi_inbox.json"
        heartbeat_payload = {}
        inbox_path.write_text(
            json.dumps(
                [
                    {
                        "source": "agent-city",
                        "operation": "heartbeat",
                        "payload": heartbeat_payload,
                        "message_id": "msg-1",
                        "payload_hash": hashlib.sha256(json.dumps(heartbeat_payload, sort_keys=True).encode()).hexdigest(),
                    },
                    {"source": "agent-city", "payload": {}},
                    "not-a-dict",
                ]
            )
        )

        messages = transport.read_outbox()

        assert len(messages) == 1
        assert messages[0]["operation"] == "heartbeat"
        quarantine_files = sorted((tmp_path / "quarantine").glob("*.json"))
        assert len([path for path in quarantine_files if path.name != "index.json"]) == 2
        records = [json.loads(path.read_text()) for path in quarantine_files if path.name != "index.json"]
        reasons = {record["reason"] for record in records}
        assert "NADI message missing required source/operation fields" in reasons
        assert "NADI inbox item must be a JSON object" in reasons

    def test_read_outbox_quarantines_corrupt_json_payload(self, tmp_path):
        transport = NadiFederationTransport(str(tmp_path))
        inbox_path = tmp_path / "nadi_inbox.json"
        inbox_path.write_text("{broken json")

        messages = transport.read_outbox()

        assert messages == []
        quarantine_files = [path for path in (tmp_path / "quarantine").glob("*.json") if path.name != "index.json"]
        assert len(quarantine_files) == 1
        record = json.loads(quarantine_files[0].read_text())
        assert record["stage"] == "transport_read"
        assert "JSON decode failed" in record["reason"]

    def test_append_handles_federation_message_fields(self, tmp_path):
        """Full FederationMessage dict round-trips correctly."""
        transport = NadiFederationTransport(str(tmp_path))
        transport.append_to_inbox(
            [
                {
                    "source": "steward",
                    "target": "*",
                    "operation": "heartbeat",
                    "payload": {"agent_id": "steward", "health": 0.95},
                    "priority": 1,
                    "correlation_id": "abc123",
                    "ttl_s": 900.0,
                }
            ]
        )
        # Self-hosted: outbound goes to nadi_outbox.json
        outbox_path = tmp_path / "nadi_outbox.json"
        data = json.loads(outbox_path.read_text())
        msg = data[0]
        assert msg["priority"] == 1
        assert msg["correlation_id"] == "abc123"
        assert msg["ttl_s"] == 900.0


class TestCreateTransport:
    """create_transport() selects the best available transport."""

    def test_prefers_nadi_when_files_exist(self, tmp_path):
        (tmp_path / "nadi_outbox.json").write_text("[]")
        transport = create_transport(str(tmp_path))
        assert isinstance(transport, NadiFederationTransport)

    def test_falls_back_to_filesystem(self, tmp_path):
        transport = create_transport(str(tmp_path))
        assert isinstance(transport, FilesystemFederationTransport)

    def test_both_satisfy_protocol(self, tmp_path):
        """Both transports have read_outbox and append_to_inbox."""
        nadi = NadiFederationTransport(str(tmp_path))
        fs = FilesystemFederationTransport(str(tmp_path))
        for t in [nadi, fs]:
            assert callable(getattr(t, "read_outbox", None))
            assert callable(getattr(t, "append_to_inbox", None))
