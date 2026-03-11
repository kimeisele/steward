"""Tests for FilesystemFederationTransport — shared directory transport."""

import json

import pytest

from steward.federation_transport import FilesystemFederationTransport


class TestFilesystemTransport:
    """Round-trip read/write via filesystem."""

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
