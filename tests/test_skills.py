"""Tests for steward/skills.py — SkillRegistry."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from steward.skills import Skill, SkillRegistry


class TestSkillParsing:
    """Test skill file parsing."""

    def test_parse_full_skill(self):
        text = "# Deploy to PyPI\ntrigger: publish, release, pypi\n---\nSteps:\n1. Bump version\n2. Build\n3. Upload"
        skill = SkillRegistry._parse_skill(text, "/test/deploy.md")
        assert skill is not None
        assert skill.name == "Deploy to PyPI"
        assert "publish" in skill.triggers
        assert "release" in skill.triggers
        assert "pypi" in skill.triggers
        assert "Bump version" in skill.content

    def test_parse_no_separator(self):
        text = "# Quick Fix\ntrigger: fix, patch\nJust fix the thing."
        skill = SkillRegistry._parse_skill(text, "/test/fix.md")
        assert skill is not None
        assert skill.name == "Quick Fix"
        assert "Just fix the thing" in skill.content

    def test_parse_no_heading(self):
        text = "trigger: test, verify\n---\nRun pytest tests/ -x"
        skill = SkillRegistry._parse_skill(text, "/test/run-tests.md")
        assert skill is not None
        assert skill.name == "Run Tests"  # From filename

    def test_parse_empty_content(self):
        text = "# Empty\ntrigger: nothing\n---\n"
        skill = SkillRegistry._parse_skill(text, "/test/empty.md")
        assert skill is None  # No content = no skill

    def test_name_words_as_triggers(self):
        text = "# Code Review Checklist\ntrigger: review\n---\nCheck for bugs."
        skill = SkillRegistry._parse_skill(text, "/test/review.md")
        assert skill is not None
        assert "review" in skill.triggers
        assert "code" in skill.triggers
        assert "checklist" in skill.triggers

    def test_content_truncation(self):
        text = "# Big\ntrigger: big\n---\n" + "x" * 5000
        skill = SkillRegistry._parse_skill(text, "/test/big.md")
        assert skill is not None
        assert len(skill.content) <= 4100  # 4000 + truncation marker


class TestSkillRegistry:
    """Test SkillRegistry loading and matching."""

    def _make_registry(self, skill_files: dict[str, str]) -> SkillRegistry:
        """Create a SkillRegistry with temp skill files."""
        tmpdir = tempfile.mkdtemp()
        skills_dir = Path(tmpdir) / ".steward" / "skills"
        skills_dir.mkdir(parents=True)
        for name, content in skill_files.items():
            (skills_dir / name).write_text(content)
        return SkillRegistry(cwd=tmpdir)

    def test_loads_from_directory(self):
        reg = self._make_registry(
            {
                "deploy.md": "# Deploy\ntrigger: deploy, publish\n---\nDeploy steps.",
                "test.md": "# Test\ntrigger: test, verify\n---\nRun tests.",
            }
        )
        assert len(reg) == 2

    def test_empty_directory(self):
        tmpdir = tempfile.mkdtemp()
        reg = SkillRegistry(cwd=tmpdir)
        assert len(reg) == 0

    def test_match_by_trigger(self):
        reg = self._make_registry(
            {
                "deploy.md": "# Deploy\ntrigger: deploy, publish, pypi\n---\nDeploy steps.",
                "test.md": "# Test\ntrigger: test, verify, pytest\n---\nRun tests.",
            }
        )
        matches = reg.match("please deploy to pypi")
        assert len(matches) >= 1
        assert matches[0].name == "Deploy"

    def test_match_no_hit(self):
        reg = self._make_registry(
            {
                "deploy.md": "# Deploy\ntrigger: deploy, publish\n---\nDeploy steps.",
            }
        )
        matches = reg.match("fix the login bug")
        assert len(matches) == 0

    def test_match_ranking(self):
        reg = self._make_registry(
            {
                "deploy.md": "# Deploy\ntrigger: deploy, publish\n---\nDeploy.",
                "pypi.md": "# PyPI Upload\ntrigger: pypi, publish, upload\n---\nUpload to PyPI.",
            }
        )
        matches = reg.match("publish to pypi")
        assert len(matches) >= 1
        # "pypi" + "publish" should score higher for pypi.md
        assert matches[0].name == "PyPI Upload"

    def test_max_injected(self):
        files = {}
        for i in range(10):
            files[f"skill{i}.md"] = f"# Skill {i}\ntrigger: common\n---\nContent {i}."
        reg = self._make_registry(files)
        matches = reg.match("common task")
        assert len(matches) <= 3  # _MAX_INJECTED

    def test_format_for_prompt(self):
        reg = self._make_registry(
            {
                "deploy.md": "# Deploy\ntrigger: deploy\n---\nDeploy steps.",
            }
        )
        matches = reg.match("deploy")
        text = reg.format_for_prompt(matches)
        assert "## Relevant Skills" in text
        assert "Deploy" in text
        assert "Deploy steps" in text

    def test_format_empty(self):
        reg = self._make_registry({})
        assert reg.format_for_prompt([]) == ""


class TestSkillCreation:
    """Test creating skills from agent experience."""

    def test_create_skill(self):
        tmpdir = tempfile.mkdtemp()
        reg = SkillRegistry(cwd=tmpdir)
        skill = reg.create_skill(
            name="Fix Import Errors",
            triggers=["import", "ModuleNotFoundError"],
            content="Check if package is installed. If not, pip install it.",
        )
        assert skill is not None
        assert skill.name == "Fix Import Errors"
        assert len(reg) == 1

        # Verify file was written
        skills_dir = Path(tmpdir) / ".steward" / "skills"
        files = list(skills_dir.glob("*.md"))
        assert len(files) == 1

    def test_create_skill_sanitizes_filename(self):
        tmpdir = tempfile.mkdtemp()
        reg = SkillRegistry(cwd=tmpdir)
        skill = reg.create_skill(
            name="Fix: Import/Errors!!",
            triggers=["import"],
            content="Fix it.",
        )
        assert skill is not None
        # Check filename is safe
        skills_dir = Path(tmpdir) / ".steward" / "skills"
        files = list(skills_dir.glob("*.md"))
        assert len(files) == 1
        assert ":" not in files[0].name
        assert "/" not in files[0].name

    def test_created_skill_is_matchable(self):
        tmpdir = tempfile.mkdtemp()
        reg = SkillRegistry(cwd=tmpdir)
        reg.create_skill(
            name="Deploy Lambda",
            triggers=["lambda", "aws", "serverless"],
            content="Steps to deploy AWS Lambda.",
        )
        matches = reg.match("deploy to aws lambda")
        assert len(matches) == 1
        assert matches[0].name == "Deploy Lambda"
