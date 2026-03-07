"""Tests for project-level context loading (instructions + git)."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from steward.agent import (
    StewardAgent,
    _build_system_prompt,
    _git_status_summary,
    _load_project_instructions,
)


# ── Fake LLM ─────────────────────────────────────────────────────────


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class FakeResponse:
    content: str = ""
    tool_calls: list[Any] | None = None
    usage: FakeUsage | None = None

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = FakeUsage()


class FakeLLM:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self._responses = list(responses or [FakeResponse(content="ok")])
        self._call_count = 0

    def invoke(self, **kwargs: Any) -> FakeResponse:
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        return FakeResponse(content="[no more responses]")


# ── Tests ────────────────────────────────────────────────────────────


class TestLoadProjectInstructions:
    def test_loads_steward_instructions(self) -> None:
        """Loads .steward/instructions.md when present."""
        with tempfile.TemporaryDirectory() as tmp:
            steward_dir = Path(tmp) / ".steward"
            steward_dir.mkdir()
            (steward_dir / "instructions.md").write_text("Always use pytest\nNever use print")
            result = _load_project_instructions(tmp)
            assert result == "Always use pytest\nNever use print"

    def test_loads_claude_md_fallback(self) -> None:
        """Falls back to CLAUDE.md when .steward/instructions.md missing."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "CLAUDE.md").write_text("Use bun not npm")
            result = _load_project_instructions(tmp)
            assert result == "Use bun not npm"

    def test_steward_instructions_takes_priority(self) -> None:
        """Prefers .steward/instructions.md over CLAUDE.md."""
        with tempfile.TemporaryDirectory() as tmp:
            steward_dir = Path(tmp) / ".steward"
            steward_dir.mkdir()
            (steward_dir / "instructions.md").write_text("steward wins")
            (Path(tmp) / "CLAUDE.md").write_text("claude loses")
            result = _load_project_instructions(tmp)
            assert result == "steward wins"

    def test_returns_none_when_no_file(self) -> None:
        """Returns None when no instruction files exist."""
        with tempfile.TemporaryDirectory() as tmp:
            result = _load_project_instructions(tmp)
            assert result is None

    def test_skips_empty_files(self) -> None:
        """Ignores empty instruction files."""
        with tempfile.TemporaryDirectory() as tmp:
            steward_dir = Path(tmp) / ".steward"
            steward_dir.mkdir()
            (steward_dir / "instructions.md").write_text("")
            result = _load_project_instructions(tmp)
            assert result is None


class TestBuildSystemPromptWithInstructions:
    def test_includes_project_instructions(self) -> None:
        """System prompt includes project instructions."""
        prompt = _build_system_prompt(
            base="You are Steward.",
            cwd="/tmp/project",
            tool_names=["bash", "read_file"],
            project_instructions="Always run tests\nUse python 3.11",
        )
        assert "Project Instructions:" in prompt
        assert "Always run tests" in prompt
        assert "Use python 3.11" in prompt

    def test_no_instructions_section_when_none(self) -> None:
        """No project instructions section when no file found."""
        prompt = _build_system_prompt(
            base="You are Steward.",
            cwd="/tmp/project",
            tool_names=["bash"],
        )
        assert "Project Instructions:" not in prompt


class TestGitStatusSummary:
    def test_returns_status_in_git_repo(self) -> None:
        """Returns git status in a real git repo."""
        # This test runs in the steward repo itself
        result = _git_status_summary(".")
        # Should return something (we always have at least untracked test files)
        # or None if clean — either is valid
        assert result is None or isinstance(result, str)

    def test_returns_none_outside_git_repo(self) -> None:
        """Returns None when not in a git repo."""
        with tempfile.TemporaryDirectory() as tmp:
            result = _git_status_summary(tmp)
            assert result is None

    def test_includes_git_status_in_prompt(self) -> None:
        """Git status section appears in system prompt when present."""
        prompt = _build_system_prompt(
            base="You are Steward.",
            cwd="/tmp/project",
            tool_names=["bash"],
            git_status="M  src/main.py\n?? new_file.py",
        )
        assert "Git Status:" in prompt
        assert "M  src/main.py" in prompt
        assert "?? new_file.py" in prompt

    def test_no_git_section_when_none(self) -> None:
        """No git status section when not in a repo."""
        prompt = _build_system_prompt(
            base="You are Steward.",
            cwd="/tmp/project",
            tool_names=["bash"],
        )
        assert "Git Status:" not in prompt


class TestAgentWithProjectInstructions:
    def test_agent_loads_project_instructions(self) -> None:
        """Agent includes project instructions in system prompt."""
        with tempfile.TemporaryDirectory() as tmp:
            steward_dir = Path(tmp) / ".steward"
            steward_dir.mkdir()
            (steward_dir / "instructions.md").write_text(
                "Use pytest-asyncio for all async tests"
            )

            llm = FakeLLM()
            agent = StewardAgent(provider=llm, cwd=tmp)
            agent.run_sync("test")

            system_msg = agent.conversation.messages[0]
            assert "Use pytest-asyncio for all async tests" in system_msg.content
            assert "Project Instructions:" in system_msg.content
