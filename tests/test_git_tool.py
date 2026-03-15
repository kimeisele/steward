"""Tests for GitTool — structured git operations with branch isolation."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from steward.tools.git import _PROTECTED_BRANCHES, GitTool


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo with an initial commit."""
    cwd = str(tmp_path)
    subprocess.run(["git", "init"], cwd=cwd, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=cwd, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=cwd, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=cwd, capture_output=True)
    # Create initial file and commit on main
    (tmp_path / "hello.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=cwd, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=cwd, capture_output=True)
    return tmp_path


@pytest.fixture
def tool(git_repo: Path) -> GitTool:
    """GitTool wired to the temp repo."""
    return GitTool(cwd=str(git_repo))


class TestGitStatus:
    def test_clean_repo(self, tool: GitTool):
        result = tool.execute({"action": "status"})
        assert result.success
        assert "Clean working tree" in result.output
        assert "Branch:" in result.output

    def test_dirty_repo(self, tool: GitTool, git_repo: Path):
        (git_repo / "new.txt").write_text("dirty")
        result = tool.execute({"action": "status"})
        assert result.success
        assert "new.txt" in result.output


class TestGitDiff:
    def test_no_changes(self, tool: GitTool):
        result = tool.execute({"action": "diff"})
        assert result.success
        assert "(no changes)" in result.output

    def test_with_changes(self, tool: GitTool, git_repo: Path):
        (git_repo / "hello.py").write_text("print('goodbye')\n")
        result = tool.execute({"action": "diff"})
        assert result.success
        assert "goodbye" in result.output

    def test_staged_diff(self, tool: GitTool, git_repo: Path):
        (git_repo / "hello.py").write_text("print('staged')\n")
        subprocess.run(["git", "add", "hello.py"], cwd=str(git_repo), capture_output=True)
        result = tool.execute({"action": "diff", "staged": True})
        assert result.success
        assert "staged" in result.output


class TestBranchCreate:
    def test_create_branch(self, tool: GitTool):
        result = tool.execute({"action": "branch_create", "branch": "feature/test"})
        assert result.success
        assert "feature/test" in result.output

    def test_invalid_branch_name(self, tool: GitTool):
        result = tool.execute({"action": "branch_create", "branch": "bad name with spaces"})
        assert not result.success
        assert "Invalid branch name" in result.error

    def test_missing_branch_name(self, tool: GitTool):
        result = tool.execute({"action": "branch_create"})
        assert not result.success
        assert "Missing" in result.error

    def test_auto_stash_on_create(self, tool: GitTool, git_repo: Path):
        """Dirty state is stashed before branch creation."""
        (git_repo / "dirty.txt").write_text("uncommitted work")
        subprocess.run(["git", "add", "dirty.txt"], cwd=str(git_repo), capture_output=True)
        result = tool.execute({"action": "branch_create", "branch": "feature/stash-test"})
        assert result.success
        # Dirty file should be restored
        assert (git_repo / "dirty.txt").exists()


class TestCheckout:
    def test_checkout_existing(self, tool: GitTool, git_repo: Path):
        # Create branch first
        subprocess.run(["git", "branch", "feature/x"], cwd=str(git_repo), capture_output=True)
        result = tool.execute({"action": "checkout", "branch": "feature/x"})
        assert result.success
        assert "feature/x" in result.output

    def test_checkout_missing(self, tool: GitTool):
        result = tool.execute({"action": "checkout"})
        assert not result.success

    def test_checkout_nonexistent(self, tool: GitTool):
        result = tool.execute({"action": "checkout", "branch": "nonexistent"})
        assert not result.success


class TestCommit:
    def test_commit_on_feature_branch(self, tool: GitTool, git_repo: Path):
        # Switch to feature branch
        subprocess.run(["git", "checkout", "-b", "feature/work"], cwd=str(git_repo), capture_output=True)
        (git_repo / "new_file.py").write_text("x = 1\n")
        result = tool.execute({"action": "commit", "message": "add new file"})
        assert result.success

    def test_commit_blocked_on_main(self, tool: GitTool, git_repo: Path):
        """CRITICAL: commits to main are BLOCKED."""
        (git_repo / "new_file.py").write_text("x = 1\n")
        result = tool.execute({"action": "commit", "message": "sneaky commit"})
        assert not result.success
        assert "BLOCKED" in result.error
        assert "protected" in result.error.lower()

    def test_commit_blocked_on_master(self, tool: GitTool, git_repo: Path):
        """Protected branch check for 'master' too."""
        subprocess.run(["git", "checkout", "-b", "master"], cwd=str(git_repo), capture_output=True)
        (git_repo / "file.py").write_text("y = 2\n")
        result = tool.execute({"action": "commit", "message": "bad"})
        assert not result.success
        assert "BLOCKED" in result.error

    def test_commit_specific_files(self, tool: GitTool, git_repo: Path):
        subprocess.run(["git", "checkout", "-b", "feature/specific"], cwd=str(git_repo), capture_output=True)
        (git_repo / "a.py").write_text("a = 1\n")
        (git_repo / "b.py").write_text("b = 2\n")
        result = tool.execute({"action": "commit", "message": "only a", "files": "a.py"})
        assert result.success
        # b.py should NOT be committed
        r = subprocess.run(["git", "status", "--porcelain"], cwd=str(git_repo), capture_output=True, text=True)
        assert "b.py" in r.stdout

    def test_commit_missing_message(self, tool: GitTool, git_repo: Path):
        subprocess.run(["git", "checkout", "-b", "feature/no-msg"], cwd=str(git_repo), capture_output=True)
        result = tool.execute({"action": "commit"})
        assert not result.success
        assert "message" in result.error.lower()

    def test_nothing_to_commit(self, tool: GitTool, git_repo: Path):
        subprocess.run(["git", "checkout", "-b", "feature/clean"], cwd=str(git_repo), capture_output=True)
        result = tool.execute({"action": "commit", "message": "empty"})
        assert result.success
        assert "Nothing to commit" in result.output


class TestPush:
    def test_push_blocked_on_main(self, tool: GitTool):
        result = tool.execute({"action": "push"})
        assert not result.success
        assert "BLOCKED" in result.error


class TestPrCreate:
    def test_no_gh_client(self, tool: GitTool):
        """PR creation fails gracefully without gh client."""
        result = tool.execute({"action": "pr_create", "title": "test PR"})
        assert not result.success
        assert "not available" in result.error.lower()

    def test_missing_title(self):
        """PR creation requires title."""
        from unittest.mock import MagicMock

        gh = MagicMock()
        tool = GitTool(gh_client=gh)
        result = tool.execute({"action": "pr_create"})
        assert not result.success
        assert "title" in result.error.lower()


class TestPrList:
    def test_no_gh_client(self, tool: GitTool):
        result = tool.execute({"action": "pr_list"})
        assert not result.success
        assert "not available" in result.error.lower()


class TestValidation:
    def test_missing_action(self, tool: GitTool):
        with pytest.raises(ValueError, match="action"):
            tool.validate({})

    def test_invalid_action(self, tool: GitTool):
        with pytest.raises(ValueError, match="Invalid action"):
            tool.validate({"action": "destroy"})

    def test_valid_actions(self, tool: GitTool):
        for action in ["status", "diff", "branch_create", "checkout", "commit", "push", "pr_create", "pr_list"]:
            tool.validate({"action": action})  # Should not raise


class TestProtectedBranches:
    def test_all_protected(self):
        assert "main" in _PROTECTED_BRANCHES
        assert "master" in _PROTECTED_BRANCHES
        assert "develop" in _PROTECTED_BRANCHES
        assert "release" in _PROTECTED_BRANCHES
        assert "feature/x" not in _PROTECTED_BRANCHES
