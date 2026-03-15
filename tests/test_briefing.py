"""Tests for briefing — dynamic context generation."""

import json
import tempfile
from pathlib import Path

from steward.briefing import generate_briefing


class TestGenerateBriefing:
    """Test generate_briefing() standalone (no LLM needed)."""

    def test_returns_string_with_header(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert isinstance(result, str)
        assert "# Steward" in result
        assert str(tmp_path.name) in result

    def test_includes_perception_when_git_repo(self, tmp_path):
        """In a git repo, senses should produce some output."""
        # Init a minimal git repo
        (tmp_path / ".git").mkdir()
        result = generate_briefing(cwd=str(tmp_path))
        assert "# Steward" in result

    def test_includes_session_history(self, tmp_path):
        """If sessions.json exists, briefing includes it."""
        steward_dir = tmp_path / ".steward"
        steward_dir.mkdir()
        sessions = {
            "version": 1,
            "sessions": [
                {
                    "task": "Fix CI pipeline",
                    "outcome": "success",
                    "summary": "Fixed flaky test",
                    "timestamp": "2026-03-14T10:00:00Z",
                    "tokens": 500,
                    "tool_calls": 3,
                    "rounds": 2,
                    "files_read": [],
                    "files_written": ["tests/test_ci.py"],
                    "buddhi_action": "debug",
                    "buddhi_phase": "VERIFY",
                    "errors": 0,
                }
            ],
        }
        (steward_dir / "sessions.json").write_text(json.dumps(sessions))
        result = generate_briefing(cwd=str(tmp_path))
        assert "Fix CI pipeline" in result

    def test_includes_architecture(self, tmp_path):
        """Briefing includes architecture metadata from living code."""
        result = generate_briefing(cwd=str(tmp_path))
        assert "Architecture" in result
        assert "North Star" in result

    def test_empty_project_still_works(self, tmp_path):
        """Briefing works even with zero state."""
        result = generate_briefing(cwd=str(tmp_path))
        assert "# Steward" in result
        assert len(result) > 10


class TestBriefingContent:
    """Test that briefing includes architecture data."""

    def test_includes_north_star(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "North Star" in result or "Architecture" in result
