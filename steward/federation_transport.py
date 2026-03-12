"""
Filesystem Federation Transport — shared directory for cross-agent messaging.

Implements the FederationTransport protocol using JSON files in a shared
directory. Works immediately for local development (steward + agent-internet
on the same machine). No network, no dependencies.

Directory structure:
    {base_dir}/
        outbox/   ← we READ from here (other agents' messages TO us)
        inbox/    ← we WRITE to here (our messages FOR other agents)

Configure via STEWARD_FEDERATION_DIR environment variable.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("STEWARD.FEDERATION.TRANSPORT")


class FilesystemFederationTransport:
    """Federation transport via shared filesystem directory.

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
