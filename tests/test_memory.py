"""Tests for Memory integration in steward."""

from __future__ import annotations

from steward.agent import StewardAgent
from steward.services import SVC_MEMORY, boot
from steward.types import ToolUse
from tests.fakes import FakeLLM, FakeResponse
from vibe_core.di import ServiceRegistry
from vibe_core.protocols.memory import InMemoryMemory

# ── Tests ────────────────────────────────────────────────────────────


class TestMemoryWiring:
    def test_memory_registered_at_boot(self) -> None:
        """InMemoryMemory is registered in ServiceRegistry at boot."""
        boot()
        memory = ServiceRegistry.get(SVC_MEMORY)
        assert memory is not None
        assert isinstance(memory, InMemoryMemory)

    def test_agent_has_memory(self) -> None:
        """StewardAgent exposes memory property."""
        llm = FakeLLM([])
        agent = StewardAgent(provider=llm)
        assert agent.memory is not None

    def test_memory_remember_and_recall(self) -> None:
        """Memory stores and retrieves values."""
        llm = FakeLLM([])
        agent = StewardAgent(provider=llm)
        agent.memory.remember("test_key", "test_value", session_id="steward")
        assert agent.memory.recall("test_key", session_id="steward") == "test_value"

    def test_memory_cleared_on_reset(self) -> None:
        """Agent reset clears session memory."""
        llm = FakeLLM([FakeResponse(content="ok")])
        agent = StewardAgent(provider=llm)
        agent.memory.remember("task", "build something", session_id="steward")
        agent.reset()
        assert agent.memory.recall("task", session_id="steward") is None


class TestMemoryFileTracking:
    def test_read_file_recorded_in_memory(self) -> None:
        """read_file operations are recorded in memory."""
        import os
        import tempfile

        # Create a real temp file so read_file succeeds
        fd, path = tempfile.mkstemp(suffix=".py")
        os.write(fd, b"print('hello')")
        os.close(fd)

        try:
            tc = ToolUse(id="call_read", name="read_file", parameters={"path": path})
            responses = [
                FakeResponse(content="", tool_calls=[tc]),
                FakeResponse(content="Read the file"),
            ]
            llm = FakeLLM(responses)
            agent = StewardAgent(provider=llm)
            agent.run_sync("Read test.py")

            files_read = agent.memory.recall("files_read", session_id="steward")
            assert files_read is not None
            assert path in files_read
        finally:
            os.unlink(path)

    def test_write_file_recorded_in_memory(self) -> None:
        """write_file operations are recorded in memory."""
        import os
        import tempfile

        # Create a temp file
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.write(fd, b"original")
        os.close(fd)

        try:
            # First read the file (Iron Dome requires read before write)
            tc_read = ToolUse(id="call_read", name="read_file", parameters={"path": path})
            tc_write = ToolUse(
                id="call_write",
                name="write_file",
                parameters={
                    "path": path,
                    "content": "new content",
                },
            )
            responses = [
                FakeResponse(content="", tool_calls=[tc_read]),
                FakeResponse(content="", tool_calls=[tc_write]),
                FakeResponse(content="Wrote the file"),
            ]
            llm = FakeLLM(responses)
            agent = StewardAgent(provider=llm)
            agent.run_sync("Write the file")

            files_write = agent.memory.recall("files_write", session_id="steward")
            assert files_write is not None
            assert path in files_write
        finally:
            os.unlink(path)

    def test_memory_search_finds_file_ops(self) -> None:
        """Memory search can find file operation records."""
        llm = FakeLLM([])
        agent = StewardAgent(provider=llm)
        agent.memory.remember(
            "files_read",
            ["/foo/bar.py"],
            session_id="steward",
            tags=["file_ops"],
        )
        results = agent.memory.search("file", session_id="steward")
        assert len(results) >= 1
        assert results[0].key == "files_read"
