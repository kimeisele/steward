"""Tests for Sruti — listen-first instruction synthesis."""

import tempfile
from pathlib import Path

import pytest

from steward.sruti import Sruti


@pytest.fixture
def empty_project(tmp_path):
    """A project with no instructions and minimal structure."""
    (tmp_path / "README.md").write_text("# TestProject\nA test project for Sruti.\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-project"\nversion = "0.1.0"\n')
    return tmp_path


@pytest.fixture
def project_with_instructions(tmp_path):
    """A project with existing human-written instructions."""
    (tmp_path / ".steward").mkdir()
    (tmp_path / ".steward" / "instructions.md").write_text(
        "Always use type hints.\nRun ruff before committing.\nThe architecture follows Sankhya-25.\n"
    )
    (tmp_path / "README.md").write_text("# MyAgent\nAn agent project.\n")
    return tmp_path


class TestSrutiHearing:
    """Test the listening phase — Sruti must hear before speaking."""

    def test_hear_existing_returns_content(self, project_with_instructions):
        sruti = Sruti(cwd=str(project_with_instructions))
        existing = sruti.hear_existing()
        assert existing is not None
        assert "type hints" in existing
        assert "ruff" in existing

    def test_hear_existing_returns_none_when_empty(self, empty_project):
        sruti = Sruti(cwd=str(empty_project))
        assert sruti.hear_existing() is None

    def test_hear_existing_prefers_steward_instructions(self, tmp_path):
        """instructions.md takes priority over CLAUDE.md."""
        (tmp_path / ".steward").mkdir()
        (tmp_path / ".steward" / "instructions.md").write_text("steward voice")
        (tmp_path / "CLAUDE.md").write_text("claude voice")
        sruti = Sruti(cwd=str(tmp_path))
        assert sruti.hear_existing() == "steward voice"

    def test_hear_existing_falls_back_to_claude_md(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("claude voice")
        sruti = Sruti(cwd=str(tmp_path))
        assert sruti.hear_existing() == "claude voice"

    def test_hear_project_identity_reads_readme(self, empty_project):
        sruti = Sruti(cwd=str(empty_project))
        identity = sruti.hear_project_identity()
        assert "readme" in identity
        assert "TestProject" in identity["readme"]

    def test_hear_project_identity_reads_skills(self, tmp_path):
        (tmp_path / ".steward" / "skills").mkdir(parents=True)
        (tmp_path / ".steward" / "skills" / "deploy.md").write_text("Deploy instructions")
        sruti = Sruti(cwd=str(tmp_path))
        identity = sruti.hear_project_identity()
        assert "skills" in identity
        assert "Deploy instructions" in identity["skills"]


class TestSrutiSynthesis:
    """Test the speaking phase — output must integrate what was heard."""

    def test_blank_canvas_produces_content(self, empty_project):
        sruti = Sruti(cwd=str(empty_project))
        result = sruti.synthesize()
        assert result
        assert "TestProject" in result
        assert "pytest" in result  # should include test commands

    def test_existing_content_preserved(self, project_with_instructions):
        sruti = Sruti(cwd=str(project_with_instructions))
        result = sruti.synthesize()
        # Human voice must survive
        assert "type hints" in result
        assert "Sankhya-25" in result

    def test_no_duplicate_when_already_mentioned(self, project_with_instructions):
        """If existing instructions mention ruff, don't add a Linting section."""
        sruti = Sruti(cwd=str(project_with_instructions))
        result = sruti.synthesize()
        assert "## Linting" not in result  # ruff already mentioned

    def test_adds_missing_info(self, tmp_path):
        """If existing instructions don't mention testing, add it."""
        (tmp_path / ".steward").mkdir()
        (tmp_path / ".steward" / "instructions.md").write_text("Use type hints everywhere.\n")
        (tmp_path / "README.md").write_text("# Proj\n")
        sruti = Sruti(cwd=str(tmp_path))
        result = sruti.synthesize()
        assert "## Testing" in result  # testing was missing, should be added

    def test_project_name_from_readme(self, empty_project):
        sruti = Sruti(cwd=str(empty_project))
        result = sruti.synthesize()
        assert result.startswith("# TestProject")

    def test_project_name_fallback_to_dirname(self, tmp_path):
        sruti = Sruti(cwd=str(tmp_path))
        result = sruti.synthesize()
        # Should use directory name as fallback
        assert result.startswith("#")


class TestSrutiWrite:
    """Test the write phase — output goes to correct path."""

    def test_write_creates_file(self, empty_project):
        sruti = Sruti(cwd=str(empty_project))
        path = sruti.write()
        assert path.exists()
        assert path.name == "instructions.md"
        assert path.parent.name == ".steward"
        content = path.read_text()
        assert "TestProject" in content

    def test_write_custom_path(self, empty_project):
        sruti = Sruti(cwd=str(empty_project))
        target = empty_project / "CLAUDE.md"
        path = sruti.write(str(target))
        assert path == target
        assert path.exists()

    def test_write_preserves_existing_on_rewrite(self, project_with_instructions):
        """Writing again should still contain the original human content."""
        sruti = Sruti(cwd=str(project_with_instructions))
        path = sruti.write()
        content = path.read_text()
        assert "type hints" in content
        assert "Sankhya-25" in content


class TestSrutiAcintya:
    """Test the acintya principle — simultaneously one and different.

    The output should be neither purely "old" nor purely "new" —
    it should be an organic integration of both.
    """

    def test_human_and_system_voices_coexist(self, tmp_path):
        """Both voices present, no mechanical separation."""
        (tmp_path / ".steward").mkdir()
        (tmp_path / ".steward" / "instructions.md").write_text(
            "The LLM is the 25th sense, NOT the CEO.\nCheck Hebbian weights before fixing bugs.\n"
        )
        (tmp_path / "README.md").write_text("# Agent\nAn autonomous agent.\n")

        sruti = Sruti(cwd=str(tmp_path))
        result = sruti.synthesize()

        # Human voice
        assert "25th sense" in result
        assert "Hebbian weights" in result

        # System voice (added because not in existing)
        assert "pytest" in result  # testing not mentioned → added

        # No mechanical markers
        assert "<!-- authority" not in result
        assert "HUMAN SECTION" not in result
        assert "SYSTEM SECTION" not in result

    def test_idempotent_synthesis(self, tmp_path):
        """Running Sruti twice should produce the same output.

        Because it always listens first — hearing the same input
        produces the same speech.
        """
        (tmp_path / "README.md").write_text("# Stable\nA stable project.\n")
        sruti = Sruti(cwd=str(tmp_path))
        first = sruti.synthesize()
        second = sruti.synthesize()
        assert first == second

    def test_write_then_read_is_stable(self, tmp_path):
        """Write → read → write again should converge, not diverge.

        This is the key acintya test: the system doesn't fight itself.
        After writing, re-reading and re-writing should not keep adding
        new sections indefinitely.
        """
        (tmp_path / "README.md").write_text("# Converge\nShould converge.\n")
        (tmp_path / ".steward").mkdir(exist_ok=True)

        sruti = Sruti(cwd=str(tmp_path))

        # First write
        sruti.write()
        first_content = (tmp_path / ".steward" / "instructions.md").read_text()

        # Second write (now there ARE existing instructions)
        sruti2 = Sruti(cwd=str(tmp_path))
        sruti2.write()
        second_content = (tmp_path / ".steward" / "instructions.md").read_text()

        # Should converge — not grow indefinitely
        # Allow some difference (perception data may change) but not explosion
        ratio = len(second_content) / max(len(first_content), 1)
        assert ratio < 1.5, f"Content grew {ratio:.1f}x on rewrite — diverging instead of converging"
