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

import json
import logging
import time
from pathlib import Path

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
        self._seen: set[tuple] = set()

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
            data = json.loads(self._inbox.read_text())
            if not isinstance(data, list):
                return []
            messages = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                # Validate required nadi protocol fields
                if not all(k in item for k in ("source", "operation")):
                    logger.warning("Nadi inbox: dropping malformed message: %s", list(item.keys())[:5])
                    continue
                key = (item.get("source", ""), item.get("timestamp", 0))
                if key in self._seen:
                    continue
                self._seen.add(key)
                messages.append(item)
            return messages
        except (json.JSONDecodeError, OSError) as e:
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
                payload = msg if isinstance(msg, dict) else (msg.to_dict() if hasattr(msg, "to_dict") else None)
                if payload is None:
                    logger.warning("Nadi: dropping non-serializable message: %s", type(msg))
                    continue
                # Strict validation: required fields
                if not all(k in payload for k in ("source", "operation")):
                    logger.warning(
                        "Nadi: dropping malformed message (missing source/operation): %s", list(payload.keys())
                    )
                    continue
                existing.append(payload)

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
    if (fed_path / "nadi_inbox.json").exists() or (fed_path / "nadi_outbox.json").exists():
        return NadiFederationTransport(federation_dir)
    # Legacy format: outbox/ and inbox/ subdirectories
    return FilesystemFederationTransport(federation_dir)
