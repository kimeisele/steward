"""Tests for project-level context loading (instructions + git)."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from steward.agent import (
    StewardAgent,
    _build_system_prompt,
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


class TestBuildSystemPromptMinimal:
    def test_prompt_is_base_plus_cwd(self) -> None:
        """System prompt is just base instruction + cwd. Nothing else."""
        prompt = _build_system_prompt(
            base="You are Steward.",
            cwd="/tmp/project",
        )
        assert "You are Steward." in prompt
        assert "cwd: /tmp/project" in prompt

    def test_no_extra_sections(self) -> None:
        """No tool list, no instructions, no environment in prompt."""
        prompt = _build_system_prompt(
            base="You are Steward.",
            cwd="/tmp/project",
        )
        assert "Project Instructions:" not in prompt
        assert "Available tools:" not in prompt
        assert "Environment:" not in prompt


class TestAgentMinimalPrompt:
    def test_agent_base_prompt_is_minimal(self) -> None:
        """Base system prompt is just base + cwd. No project instructions injected."""
        with tempfile.TemporaryDirectory() as tmp:
            steward_dir = Path(tmp) / ".steward"
            steward_dir.mkdir()
            (steward_dir / "instructions.md").write_text("Use pytest-asyncio for all async tests")

            llm = FakeLLM()
            agent = StewardAgent(provider=llm, cwd=tmp)

            # Base prompt stays minimal — no project instructions
            assert "cwd:" in agent._base_system_prompt
            assert "Use pytest-asyncio" not in agent._base_system_prompt


class TestSensePerceptionInPrompt:
    """Senses inject environmental perception into the effective system prompt."""

    def test_base_prompt_has_no_sense_data(self) -> None:
        """Base system prompt is minimal — sense data is added at runtime."""
        with tempfile.TemporaryDirectory() as tmp:
            llm = FakeLLM()
            agent = StewardAgent(provider=llm, cwd=tmp)
            assert "Environment Perception" not in agent._base_system_prompt

    def test_effective_prompt_includes_senses(self) -> None:
        """After run_sync, system message includes sense perception data."""
        llm = FakeLLM()
        agent = StewardAgent(provider=llm)
        agent.run_sync("test")
        system_msg = agent.conversation.messages[0].content
        # Effective prompt has sense data appended
        assert "cwd:" in system_msg
        # In a real cwd (git repo), sense data is present
        assert "Git:" in system_msg or "Environment Perception" in system_msg

    def test_custom_prompt_unchanged(self) -> None:
        """Custom system prompts pass through untouched."""
        with tempfile.TemporaryDirectory() as tmp:
            llm = FakeLLM()
            agent = StewardAgent(provider=llm, cwd=tmp, system_prompt="Custom prompt only")
            agent.run_sync("test")
            system_msg = agent.conversation.messages[0]
            assert system_msg.content == "Custom prompt only"
