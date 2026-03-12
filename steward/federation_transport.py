"""
Federation Transport — Adapts steward-protocol's FederationNadi for the bridge.

Two transport implementations:
  - NadiFederationTransport: Uses FederationNadi from steward-protocol
    (nadi_outbox.json / nadi_inbox.json). Compatible with agent-city and
    agent-internet's filesystem federation. Works over git (push/pull = network).
  - FilesystemFederationTransport: Legacy shared-directory transport for
    backwards compatibility with STEWARD_FEDERATION_DIR.

Configure via:
  STEWARD_FEDERATION_DIR → NadiFederationTransport (preferred)
  Falls back to FilesystemFederationTransport if FederationNadi unavailable.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("STEWARD.FEDERATION.TRANSPORT")


class NadiFederationTransport:
    """Adapts steward-protocol's FederationNadi to the FederationTransport protocol.

    FederationNadi (steward-protocol) uses nadi_outbox.json / nadi_inbox.json —
    the canonical cross-repo format shared by agent-city and agent-internet.

    This adapter satisfies the FederationTransport protocol:
        read_outbox() -> list[dict]
        append_to_inbox(messages) -> int
    """

    def __init__(self, federation_dir: str) -> None:
        from vibe_core.mahamantra.federation import FederationNadi

        self._nadi = FederationNadi(federation_dir=federation_dir)

    def read_outbox(self) -> list[dict]:
        """Read messages from nadi_outbox.json (other agents' messages TO us).

        Returns list of dicts with {source, target, operation, payload, ...}.
        FederationNadi handles TTL expiry and deduplication.
        """
        messages = self._nadi.receive()
        return [msg.to_dict() for msg in messages]

    def append_to_inbox(self, messages: list[object]) -> int:
        """Write messages to nadi_inbox.json (our messages FOR other agents).

        Accepts dicts or FederationMessage-like objects. Converts to
        FederationMessage format for cross-repo compatibility.
        """
        from vibe_core.mahamantra.federation import FederationMessage

        count = 0
        for msg in messages:
            if isinstance(msg, dict):
                fm = FederationMessage.from_dict(msg)
            elif hasattr(msg, "to_dict"):
                fm = FederationMessage.from_dict(msg.to_dict())
            else:
                continue
            if self._nadi.send_message(fm):
                count += 1
        return count


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
    """Create the best available transport for the given federation directory.

    Tries NadiFederationTransport first (steward-protocol's canonical format).
    Falls back to FilesystemFederationTransport if FederationNadi unavailable.
    """
    try:
        return NadiFederationTransport(federation_dir)
    except (ImportError, Exception) as e:
        logger.info("NadiFederationTransport unavailable (%s), using filesystem fallback", e)
        return FilesystemFederationTransport(federation_dir)
