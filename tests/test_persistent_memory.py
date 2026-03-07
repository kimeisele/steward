"""Tests for PersistentMemory (JSON-backed)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from steward.memory import PersistentMemory


class TestPersistentMemory:
    def test_remember_and_recall(self) -> None:
        """Basic remember/recall works."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = PersistentMemory(cwd=tmp)
            mem.remember("key1", "value1", session_id="s1")
            assert mem.recall("key1", session_id="s1") == "value1"

    def test_persistence_across_instances(self) -> None:
        """Memory survives across PersistentMemory instances."""
        with tempfile.TemporaryDirectory() as tmp:
            # Instance 1: write
            mem1 = PersistentMemory(cwd=tmp)
            mem1.remember("task", "fix bugs", session_id="steward")
            mem1.remember("files", ["/foo.py", "/bar.py"], session_id="steward")

            # Instance 2: read (new instance, same directory)
            mem2 = PersistentMemory(cwd=tmp)
            assert mem2.recall("task", session_id="steward") == "fix bugs"
            assert mem2.recall("files", session_id="steward") == ["/foo.py", "/bar.py"]

    def test_forget_persists(self) -> None:
        """Forgotten keys are removed from disk."""
        with tempfile.TemporaryDirectory() as tmp:
            mem1 = PersistentMemory(cwd=tmp)
            mem1.remember("key", "val", session_id="s1")
            mem1.forget("key", session_id="s1")

            mem2 = PersistentMemory(cwd=tmp)
            assert mem2.recall("key", session_id="s1") is None

    def test_clear_session_persists(self) -> None:
        """Cleared session data is removed from disk."""
        with tempfile.TemporaryDirectory() as tmp:
            mem1 = PersistentMemory(cwd=tmp)
            mem1.remember("a", "1", session_id="s1")
            mem1.remember("b", "2", session_id="s1")
            mem1.remember("c", "3", session_id="s2")  # different session
            count = mem1.clear_session("s1")
            assert count == 2

            mem2 = PersistentMemory(cwd=tmp)
            assert mem2.recall("a", session_id="s1") is None
            assert mem2.recall("b", session_id="s1") is None
            assert mem2.recall("c", session_id="s2") == "3"

    def test_file_created_in_steward_dir(self) -> None:
        """Memory file is created in .steward/ directory."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = PersistentMemory(cwd=tmp)
            mem.remember("x", "y")

            state_file = Path(tmp) / ".steward" / "memory.json"
            assert state_file.exists()

            data = json.loads(state_file.read_text())
            assert data["version"] == 1
            assert len(data["entries"]) >= 1

    def test_atomic_write(self) -> None:
        """No temp file left after save."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = PersistentMemory(cwd=tmp)
            mem.remember("x", "y")

            steward_dir = Path(tmp) / ".steward"
            assert not (steward_dir / "memory.tmp").exists()
            assert (steward_dir / "memory.json").exists()

    def test_corrupted_file_starts_fresh(self) -> None:
        """Corrupted JSON file results in empty memory."""
        with tempfile.TemporaryDirectory() as tmp:
            steward_dir = Path(tmp) / ".steward"
            steward_dir.mkdir()
            (steward_dir / "memory.json").write_text("not json{{{")

            mem = PersistentMemory(cwd=tmp)
            assert mem.recall("anything") is None
            # Should still work for new entries
            mem.remember("new", "data")
            assert mem.recall("new") == "data"

    def test_wrong_version_starts_fresh(self) -> None:
        """Wrong version number results in empty memory."""
        with tempfile.TemporaryDirectory() as tmp:
            steward_dir = Path(tmp) / ".steward"
            steward_dir.mkdir()
            (steward_dir / "memory.json").write_text(
                json.dumps({"version": 999, "entries": []})
            )

            mem = PersistentMemory(cwd=tmp)
            assert mem.recall("anything") is None

    def test_entity_persistence(self) -> None:
        """Entities survive across instances."""
        from vibe_core.protocols.memory import Entity

        with tempfile.TemporaryDirectory() as tmp:
            mem1 = PersistentMemory(cwd=tmp)
            mem1.remember_entities(
                [
                    Entity(type="file", id="f1", name="main.py"),
                    Entity(type="file", id="f2", name="test.py"),
                ],
                session_id="steward",
            )

            mem2 = PersistentMemory(cwd=tmp)
            resolved = mem2.resolve_reference("the second one", session_id="steward")
            assert resolved is not None
            assert resolved.name == "test.py"

    def test_search_works_after_reload(self) -> None:
        """Search finds entries after reload from disk."""
        with tempfile.TemporaryDirectory() as tmp:
            mem1 = PersistentMemory(cwd=tmp)
            mem1.remember("files_read", ["/foo.py"], session_id="s1", tags=["file_ops"])

            mem2 = PersistentMemory(cwd=tmp)
            results = mem2.search("file", session_id="s1")
            assert len(results) >= 1
            assert results[0].key == "files_read"

    def test_global_memory(self) -> None:
        """Global (no session) memory persists."""
        with tempfile.TemporaryDirectory() as tmp:
            mem1 = PersistentMemory(cwd=tmp)
            mem1.remember("global_key", "global_value")

            mem2 = PersistentMemory(cwd=tmp)
            assert mem2.recall("global_key") == "global_value"
