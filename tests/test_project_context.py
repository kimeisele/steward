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
            tool_names=["bash", "read_file"],
            project_instructions="Always run tests\nUse python 3.11",
        )
        assert "You are Steward." in prompt
        assert "cwd: /tmp/project" in prompt
        # Extra context NOT included — minimal prompt, every token counts
        assert "Always run tests" not in prompt

    def test_no_extra_sections(self) -> None:
        """No tool list, no instructions, no environment in prompt."""
        prompt = _build_system_prompt(
            base="You are Steward.",
            cwd="/tmp/project",
            tool_names=["bash"],
        )
        assert "Project Instructions:" not in prompt
        assert "Available tools:" not in prompt
        assert "Environment:" not in prompt


class TestAgentMinimalPrompt:
    def test_agent_prompt_is_minimal(self) -> None:
        """Agent system prompt is just base + cwd. No project instructions injected."""
        with tempfile.TemporaryDirectory() as tmp:
            steward_dir = Path(tmp) / ".steward"
            steward_dir.mkdir()
            (steward_dir / "instructions.md").write_text("Use pytest-asyncio for all async tests")

            llm = FakeLLM()
            agent = StewardAgent(provider=llm, cwd=tmp)
            agent.run_sync("test")

            system_msg = agent.conversation.messages[0]
            # Minimal prompt — no project instructions, no sense data
            assert "cwd:" in system_msg.content
            assert "Environment Perception" not in system_msg.content


class TestSensesInfrastructureOnly:
    """Senses perceive for infrastructure but do NOT inject into LLM prompt."""

    def test_prompt_has_no_sense_data(self) -> None:
        """System prompt contains zero sense data — senses are infrastructure only."""
        with tempfile.TemporaryDirectory() as tmp:
            llm = FakeLLM()
            agent = StewardAgent(provider=llm, cwd=tmp)
            assert "Environment Perception" not in agent._base_system_prompt
            assert "Environment Perception" not in agent._system_prompt

    def test_prompt_stays_minimal_across_runs(self) -> None:
        """System prompt stays minimal even after multiple runs."""
        with tempfile.TemporaryDirectory() as tmp:
            llm = FakeLLM(responses=[FakeResponse(content="ok"), FakeResponse(content="ok")])
            agent = StewardAgent(provider=llm, cwd=tmp)

            agent.run_sync("first task")
            msg1 = agent.conversation.messages[0].content

            (Path(tmp) / "test_new.py").write_text("def test_x(): pass")
            agent.run_sync("second task")
            msg2 = agent.conversation.messages[0].content

            # No sense data in prompt — ever
            assert "Environment Perception" not in msg1
            assert "Environment Perception" not in msg2
            # Prompt is stable (base + cwd only)
            assert msg1 == msg2

    def test_custom_prompt_unchanged(self) -> None:
        """Custom system prompts pass through untouched."""
        with tempfile.TemporaryDirectory() as tmp:
            llm = FakeLLM()
            agent = StewardAgent(provider=llm, cwd=tmp, system_prompt="Custom prompt only")
            agent.run_sync("test")
            system_msg = agent.conversation.messages[0]
            assert system_msg.content == "Custom prompt only"
