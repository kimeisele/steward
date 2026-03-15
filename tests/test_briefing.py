"""Tests for briefing — dynamic context generation."""

import json
import tempfile
from pathlib import Path

from steward.briefing import generate_briefing, _load_gaps_from_disk


class TestGenerateBriefing:
    """Test generate_briefing() standalone (no LLM needed)."""

    def test_returns_string_with_header(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert isinstance(result, str)
        assert "# Steward Briefing" in result
        assert str(tmp_path.name) in result

    def test_includes_perception_when_git_repo(self, tmp_path):
        """In a git repo, senses should produce some output."""
        # Init a minimal git repo
        (tmp_path / ".git").mkdir()
        result = generate_briefing(cwd=str(tmp_path))
        assert "# Steward Briefing" in result

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

    def test_includes_gaps(self, tmp_path):
        """If memory.json has gaps, briefing includes them."""
        import time

        steward_dir = tmp_path / ".steward"
        steward_dir.mkdir()
        memory = {
            "steward": {
                "gap_tracker": {
                    "value": [
                        {
                            "category": "tool",
                            "description": "Tool 'deploy' failed: connection timeout",
                            "context": "",
                            "timestamp": time.time(),
                            "resolved": False,
                            "resolution": "",
                        }
                    ]
                }
            }
        }
        (steward_dir / "memory.json").write_text(json.dumps(memory))
        result = generate_briefing(cwd=str(tmp_path))
        assert "Capability Gaps" in result
        assert "deploy" in result

    def test_includes_project_instructions(self, tmp_path):
        """If .steward/instructions.md exists, briefing includes it."""
        steward_dir = tmp_path / ".steward"
        steward_dir.mkdir()
        (steward_dir / "instructions.md").write_text("Always run tests before pushing.")
        result = generate_briefing(cwd=str(tmp_path))
        assert "Always run tests before pushing" in result

    def test_empty_project_still_works(self, tmp_path):
        """Briefing works even with zero state."""
        result = generate_briefing(cwd=str(tmp_path))
        assert "# Steward Briefing" in result
        assert len(result) > 10


class TestLoadGapsFromDisk:
    """Test gap loading from raw memory.json."""

    def test_no_file(self, tmp_path):
        gaps = _load_gaps_from_disk(str(tmp_path))
        assert len(gaps.active_gaps()) == 0

    def test_corrupt_json(self, tmp_path):
        steward_dir = tmp_path / ".steward"
        steward_dir.mkdir()
        (steward_dir / "memory.json").write_text("{invalid json")
        gaps = _load_gaps_from_disk(str(tmp_path))
        assert len(gaps.active_gaps()) == 0
