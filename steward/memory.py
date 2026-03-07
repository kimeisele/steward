"""
Persistent Memory — JSON-backed MemoryProtocol implementation.

Extends InMemoryMemory with file persistence using the Phoenix pattern
(atomic write via temp + rename). Memory survives across sessions.

    memory = PersistentMemory(cwd="/path/to/project")
    memory.remember("key", "value", session_id="steward")
    # Persisted to .steward/memory.json

    # Next session:
    memory = PersistentMemory(cwd="/path/to/project")
    value = memory.recall("key", session_id="steward")  # "value"
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from vibe_core.protocols.memory import (
    Entity,
    InMemoryMemory,
    MemoryEntry,
    MemoryStats,
)

logger = logging.getLogger("STEWARD.MEMORY")

_STATE_VERSION = 1


class PersistentMemory(InMemoryMemory):
    """JSON-backed persistent memory.

    Inherits all InMemoryMemory behavior. Adds:
    - Load from .steward/memory.json on init
    - Save after every remember/forget/clear operation
    - Phoenix pattern: atomic write (temp + rename)
    """

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self._cwd = Path(cwd) if cwd else Path.cwd()
        self._state_dir = self._cwd / ".steward"
        self._state_file = self._state_dir / "memory.json"
        self._load()

    def remember(
        self,
        key: str,
        value: object,
        session_id: str | None = None,
        ttl_seconds: int | None = None,
        tags: list[str] | None = None,
    ) -> None:
        super().remember(key, value, session_id, ttl_seconds, tags)
        self._save()

    def forget(
        self,
        key: str,
        session_id: str | None = None,
    ) -> bool:
        result = super().forget(key, session_id)
        if result:
            self._save()
        return result

    def clear_session(self, session_id: str) -> int:
        count = super().clear_session(session_id)
        if count > 0:
            self._save()
        return count

    def remember_entities(
        self,
        entities: List[Entity],
        session_id: str,
    ) -> None:
        super().remember_entities(entities, session_id)
        self._save()

    def clear_expired(self) -> int:
        count = super().clear_expired()
        if count > 0:
            self._save()
        return count

    def _save(self) -> None:
        """Persist memory to JSON using Phoenix pattern."""
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)

            # Serialize entries (skip expired)
            entries: list[dict[str, object]] = []
            for (sid, key), entry in self._store.items():
                if entry.is_expired:
                    continue
                entries.append({
                    "session_id": sid,
                    "key": key,
                    "value": entry.value,
                    "created_at": entry.created_at.isoformat(),
                    "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
                    "tags": entry.tags,
                })

            # Serialize entities
            entity_data: dict[str, list[dict[str, object]]] = {}
            for sid, entity_list in self._entities.items():
                entity_data[sid] = [
                    {
                        "type": e.type,
                        "id": e.id,
                        "name": e.name,
                        "position": e.position,
                        "metadata": e.metadata,
                    }
                    for e in entity_list
                ]

            data = {
                "version": _STATE_VERSION,
                "entries": entries,
                "entities": entity_data,
            }

            # Atomic write
            temp = self._state_file.with_suffix(".tmp")
            temp.write_text(json.dumps(data, indent=2, default=str))
            temp.replace(self._state_file)

        except Exception as e:
            logger.warning("Memory save failed: %s", e)

    def _load(self) -> None:
        """Load memory from JSON."""
        if not self._state_file.exists():
            return

        try:
            raw = json.loads(self._state_file.read_text())
            if raw.get("version") != _STATE_VERSION:
                logger.warning("Memory version mismatch, starting fresh")
                return

            # Restore entries
            for entry_data in raw.get("entries", []):
                sid = entry_data.get("session_id", "__global__")
                key = entry_data.get("key", "")
                created_at = datetime.fromisoformat(entry_data["created_at"])
                expires_at = (
                    datetime.fromisoformat(entry_data["expires_at"])
                    if entry_data.get("expires_at")
                    else None
                )

                entry = MemoryEntry(
                    key=key,
                    value=entry_data.get("value"),
                    created_at=created_at,
                    expires_at=expires_at,
                    session_id=sid if sid != "__global__" else None,
                    tags=entry_data.get("tags", []),
                )

                # Skip expired entries
                if entry.is_expired:
                    continue

                self._store[(sid, key)] = entry

            # Restore entities
            for sid, entity_list in raw.get("entities", {}).items():
                self._entities[sid] = [
                    Entity(
                        type=e.get("type", ""),
                        id=e.get("id", ""),
                        name=e.get("name", ""),
                        position=e.get("position", 0),
                        metadata=e.get("metadata", {}),
                    )
                    for e in entity_list
                ]

            logger.info(
                "Memory loaded (%d entries, %d entity sets)",
                len(self._store),
                len(self._entities),
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Memory load failed (%s), starting fresh", e)
