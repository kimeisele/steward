"""
Federation Transport — File I/O for steward's own data/federation/ directory.

Steward's federation dir follows the same layout as agent-city:
    data/federation/
    ├── nadi_outbox.json   ← steward WRITES (outbound, for others to read)
    ├── nadi_inbox.json    ← steward READS (inbound, from others)
    ├── peer.json          ← self-description
    ├── reports/           ← heartbeat reports
    └── directives/        ← commands from federation

IMPORTANT: This is SELF-HOSTED semantics. Steward reads its own inbox,
writes its own outbox. This matches agent-city's FederationNadi pattern.

steward-protocol's FederationNadi has REVERSED semantics (designed for
cross-agent access: read THEIR outbox, write THEIR inbox). Don't use it
for self-hosted federation — the file paths would be swapped.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from pathlib import Path

from steward.federation_crypto import NodeKeyStore, sign_payload_hash
from vibe_core.mahamantra.federation.types import FederationMessage

logger = logging.getLogger("STEWARD.FEDERATION.TRANSPORT")

NADI_BUFFER_SIZE = 144  # Max messages per file (matches steward-protocol)


class NadiFederationTransport:
    """Self-hosted federation transport for steward's own data/federation/.

    Reads from OUR inbox (nadi_inbox.json) — messages FROM other agents.
    Writes to OUR outbox (nadi_outbox.json) — messages FROM us TO others.

    Matches agent-city's own FederationNadi semantics. Agent-internet
    reads our outbox and delivers to our inbox via its relay pump.

    NOTE ON METHOD NAMES: read_outbox() and append_to_inbox() match the
    FederationTransport protocol defined in steward-protocol. The protocol
    uses CROSS-AGENT semantics (read THEIR outbox, write THEIR inbox).
    For self-hosted transport, the directions are flipped:
        read_outbox()      → reads OUR inbox  (nadi_inbox.json)
        append_to_inbox()  → writes OUR outbox (nadi_outbox.json)

    This is correct — the protocol consumer doesn't know (or care) whether
    it's talking to a self-hosted or cross-agent transport.
    """

    def __init__(self, federation_dir: str) -> None:
        self._dir = Path(federation_dir)
        self._inbox = self._dir / "nadi_inbox.json"
        self._outbox = self._dir / "nadi_outbox.json"
        self._quarantine_dir = self._dir / "quarantine"
        self._quarantine_index = self._quarantine_dir / "index.json"
        self._key_store = NodeKeyStore(self._dir / ".node_keys.json")
        self._key_store.ensure_keys()
        self.public_key = self._key_store.public_key
        self.private_key = self._key_store.private_key
        self.node_id = self._key_store.node_id
        self._seen: set[str] = set()
        self._quarantined = self._load_quarantine_index()

    def _serialize_message(self, message: object) -> object:
        if isinstance(message, (dict, list, str, int, float, bool)) or message is None:
            return message
        if hasattr(message, "to_dict"):
            return message.to_dict()
        return {"repr": repr(message), "type": type(message).__name__}

    def _fingerprint(self, message: object) -> str:
        payload = self._serialize_message(message)
        encoded = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _payload_hash(self, payload: object) -> str:
        serialized = self._serialize_message(payload)
        encoded = json.dumps(serialized, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _with_integrity_fields(self, payload: dict) -> dict:
        """Attach integrity fields (legacy path) UNLESS the message is
        already signed by an upstream layer.

        FederationBridge.flush_outbound (TICKET-007 #54) signs every
        outbound message with the canonical wire format
        (source = derive_node_id(public_key), payload_hash over the whole
        message minus sig fields, base64 ed25519 signature). If those
        three fields are populated, this transport must NOT overwrite
        them — doing so produced ghost-identity emissions for cycles.

        The legacy file-based-key path is preserved only for messages
        that arrive without signing (back-compat for any code that
        still constructs raw FederationMessage dicts and hands them to
        the transport directly).
        """
        enriched = dict(payload)
        if enriched.get("source") and enriched.get("payload_hash") and enriched.get("signature"):
            # Pre-signed by FederationBridge — only stamp a message_id if missing.
            enriched.setdefault("message_id", str(uuid.uuid4()))
            return enriched
        # Legacy path: payload-scoped hash, transport signs with file-based key
        enriched["source"] = self.node_id
        enriched["message_id"] = str(uuid.uuid4())
        enriched["payload_hash"] = self._payload_hash(enriched.get("payload", {}))
        enriched["signature"] = sign_payload_hash(self.private_key, enriched["payload_hash"])
        return enriched

    def _load_quarantine_index(self) -> set[str]:
        if not self._quarantine_index.exists():
            return set()
        try:
            raw = json.loads(self._quarantine_index.read_text())
            if isinstance(raw, list):
                return {str(item) for item in raw}
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read quarantine index: %s", self._quarantine_index)
        return set()

    def _persist_quarantine_index(self) -> None:
        self._quarantine_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._quarantine_index.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(sorted(self._quarantined), indent=2))
        tmp.replace(self._quarantine_index)

    def _load_quarantine_record(self, path: Path) -> dict | None:
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read quarantine record: %s", path)
            return None
        if not isinstance(raw, dict):
            return None
        raw["file_name"] = path.name
        raw["path"] = str(path)
        return raw

    def list_quarantine_records(self) -> list[dict]:
        if not self._quarantine_dir.exists():
            return []
        records: list[dict] = []
        for path in sorted(self._quarantine_dir.glob("*.json")):
            if path.name == "index.json":
                continue
            record = self._load_quarantine_record(path)
            if record is not None:
                records.append(record)
        return records

    def quarantine_size(self) -> int:
        return max(len(self._quarantined), len(self.list_quarantine_records()))

    def _load_inbox_messages(self) -> list[object]:
        if not self._inbox.exists():
            return []
        try:
            raw = json.loads(self._inbox.read_text())
        except (json.JSONDecodeError, OSError):
            return []
        return raw if isinstance(raw, list) else []

    def stage_replay_messages(self, messages: list[dict]) -> int:
        if not messages:
            return 0
        existing = self._load_inbox_messages()
        combined = list(existing) + [self._serialize_message(message) for message in messages]
        tmp = self._inbox.with_suffix(".json.tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(combined, indent=2, default=str))
        tmp.replace(self._inbox)
        return len(messages)

    def clear_seen_message(self, message: object) -> None:
        self._seen.discard(self._fingerprint(message))

    def remove_inbox_messages(self, messages: list[object]) -> int:
        if not messages:
            return 0
        existing = self._load_inbox_messages()
        if not existing:
            return 0
        removal = {self._fingerprint(message) for message in messages}
        kept = [item for item in existing if self._fingerprint(item) not in removal]
        tmp = self._inbox.with_suffix(".json.tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(kept, indent=2, default=str))
        tmp.replace(self._inbox)
        return len(existing) - len(kept)

    def delete_quarantine_records(self, records: list[dict]) -> int:
        deleted = 0
        for record in records:
            fingerprint = str(record.get("fingerprint", ""))
            path_str = str(record.get("path", ""))
            if path_str:
                path = Path(path_str)
                if path.exists():
                    path.unlink()
                    deleted += 1
            if fingerprint:
                self._quarantined.discard(fingerprint)
        if deleted or records:
            self._persist_quarantine_index()
        return deleted

    def quarantine_messages(
        self,
        messages: list[object],
        *,
        reason: str,
        stage: str = "gateway",
        metadata: dict[str, object] | None = None,
    ) -> int:
        if not messages:
            return 0

        self._quarantine_dir.mkdir(parents=True, exist_ok=True)
        quarantined = 0
        for message in messages:
            fingerprint = self._fingerprint(message)
            if fingerprint in self._quarantined:
                continue
            record = {
                "quarantined_at": time.time(),
                "stage": stage,
                "reason": reason,
                "metadata": metadata or {},
                "fingerprint": fingerprint,
                "message": self._serialize_message(message),
            }
            path = self._quarantine_dir / f"{time.time_ns()}_{fingerprint[:12]}.json"
            path.write_text(json.dumps(record, indent=2, default=str))
            self._quarantined.add(fingerprint)
            quarantined += 1

        if quarantined:
            self._persist_quarantine_index()
        return quarantined

    def read_outbox(self) -> list[dict]:
        """FederationTransport protocol: read_outbox().

        Self-hosted semantics: reads OUR inbox (nadi_inbox.json) because
        from the protocol consumer's perspective, our inbox IS their outbox.
        Called by FederationBridge.process_inbound() during DHARMA phase.
        Deduplicates by (source, timestamp) to prevent reprocessing.
        """
        if not self._inbox.exists():
            return []
        try:
            raw_text = self._inbox.read_text()
            data = json.loads(raw_text)
            if not isinstance(data, list):
                self.quarantine_messages(
                    [{"raw_text": raw_text, "path": str(self._inbox)}],
                    reason="NADI inbox payload must be a JSON list",
                    stage="transport_read",
                )
                return []
            messages = []
            for item in data:
                fingerprint = self._fingerprint(item)
                if fingerprint in self._quarantined or fingerprint in self._seen:
                    continue
                if not isinstance(item, dict):
                    self.quarantine_messages(
                        [item],
                        reason="NADI inbox item must be a JSON object",
                        stage="transport_parse",
                    )
                    continue
                # Normalize: some agents (e.g. agent-city) use 'type' instead of 'operation'
                if "operation" not in item and "type" in item:
                    item = dict(item)
                    item["operation"] = item["type"]

                # Validate required nadi protocol fields
                if not all(k in item for k in ("source", "operation")):
                    logger.warning("Nadi inbox: dropping malformed message: %s", list(item.keys())[:5])
                    self.quarantine_messages(
                        [item],
                        reason="NADI message missing required source/operation fields",
                        stage="transport_parse",
                    )
                    continue
                # TTL gate: silently drop expired messages so the gateway doesn't
                # waste cycles signing-checking 22-day-old hub backlog. No
                # quarantine — staleness is not malice, just delivery lag.
                ttl = item.get("ttl_s")
                ts = item.get("timestamp")
                if isinstance(ttl, (int, float)) and ttl > 0 and isinstance(ts, (int, float)):
                    if time.time() > ts + ttl:
                        self._seen.add(fingerprint)
                        continue
                expected_hash = str(item.get("payload_hash", "")).strip()
                if expected_hash:
                    actual_hash = self._payload_hash(item.get("payload", {}))
                    if actual_hash != expected_hash:
                        self.quarantine_messages(
                            [item],
                            reason="integrity_check_failed",
                            stage="transport_inbound_verify",
                        )
                        continue
                self._seen.add(fingerprint)
                messages.append(item)
            return messages
        except json.JSONDecodeError as e:
            logger.warning("Failed to read inbox: %s", e)
            try:
                raw_text = self._inbox.read_text()
            except OSError:
                raw_text = ""
            self.quarantine_messages(
                [{"raw_text": raw_text, "path": str(self._inbox)}],
                reason=f"NADI inbox JSON decode failed: {e}",
                stage="transport_read",
            )
            return []
        except OSError as e:
            logger.warning("Failed to read inbox: %s", e)
            return []

    def append_to_inbox(self, messages: list[object]) -> int:
        """FederationTransport protocol: append_to_inbox().

        Self-hosted semantics: writes OUR outbox (nadi_outbox.json) because
        from the protocol consumer's perspective, our outbox IS their inbox.
        Called by FederationBridge.flush_outbound() during MOKSHA phase.
        Atomic write (tmp → rename). Capped at NADI_BUFFER_SIZE.
        """
        if not messages:
            return 0
        try:
            existing: list[dict] = []
            if self._outbox.exists():
                try:
                    raw = json.loads(self._outbox.read_text())
                    if isinstance(raw, list):
                        existing = raw
                except json.JSONDecodeError as e:
                    logger.warning("Nadi outbox corrupt, starting fresh: %s", e)

            for msg in messages:
                if isinstance(msg, FederationMessage):
                    payload = msg.to_dict()
                elif isinstance(msg, dict):
                    payload = msg
                elif hasattr(msg, "to_dict"):
                    payload = msg.to_dict()
                else:
                    logger.warning("Nadi: dropping non-serializable message: %s", type(msg))
                    continue
                # Strict validation: required fields
                if not all(k in payload for k in ("source", "operation")):
                    logger.warning(
                        "Nadi: dropping malformed message (missing source/operation): %s", list(payload.keys())
                    )
                    continue
                existing.append(self._with_integrity_fields(payload))

            if len(existing) > NADI_BUFFER_SIZE:
                existing = existing[-NADI_BUFFER_SIZE:]

            tmp = self._outbox.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(existing, indent=2))
            tmp.replace(self._outbox)
            return len(messages)
        except OSError as e:
            logger.warning("Failed to write outbox: %s", e)
            return 0


class FilesystemFederationTransport:
    """Legacy transport via shared filesystem directory.

    Uses outbox/ and inbox/ subdirectories with separate JSON files.
    Kept for backwards compatibility with STEWARD_FEDERATION_DIR when
    NadiFederationTransport is not available.

    Satisfies the FederationTransport protocol:
        read_outbox() -> list[dict]
        append_to_inbox(messages) -> int
    """

    def __init__(self, base_dir: str) -> None:
        self._dir = Path(base_dir)
        self._outbox = self._dir / "outbox"
        self._inbox = self._dir / "inbox"

    def read_outbox(self) -> list[dict]:
        """Read and consume all messages from the outbox directory.

        Each .json file contains a list of messages or a single message.
        Consumed files are deleted after reading.
        """
        if not self._outbox.is_dir():
            return []

        messages: list[dict] = []
        for path in sorted(self._outbox.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                if isinstance(data, list):
                    messages.extend(d for d in data if isinstance(d, dict))
                elif isinstance(data, dict):
                    messages.append(data)
                path.unlink()
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read %s: %s", path, e)
        return messages

    def append_to_inbox(self, messages: list[object]) -> int:
        """Write messages to the inbox directory as a timestamped JSON file."""
        if not messages:
            return 0

        self._inbox.mkdir(parents=True, exist_ok=True)
        filename = f"{time.time_ns()}.json"
        path = self._inbox / filename

        try:
            serializable = [m if isinstance(m, dict) else {"data": str(m)} for m in messages]
            path.write_text(json.dumps(serializable, default=str))
            return len(serializable)
        except OSError as e:
            logger.warning("Failed to write %s: %s", path, e)
            return 0


def create_transport(federation_dir: str) -> object:
    """Create federation transport for the given directory.

    Uses NadiFederationTransport (self-hosted, correct inbox/outbox semantics).
    Falls back to FilesystemFederationTransport for legacy outbox/inbox subdirs.
    """
    fed_path = Path(federation_dir)
    # Self-hosted nadi format: nadi_inbox.json + nadi_outbox.json in dir root
    if (
        (fed_path / "nadi_inbox.json").exists()
        or (fed_path / "nadi_outbox.json").exists()
        or (fed_path / "quarantine").exists()
    ):
        return NadiFederationTransport(federation_dir)
    # Legacy format: outbox/ and inbox/ subdirectories
    return FilesystemFederationTransport(federation_dir)
