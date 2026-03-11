"""Tests for Intent Actuators — GitActuator and GitHubActuator."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from steward.actuators import (
    ActuatorResult,
    GitActuator,
    GitHubActuator,
    IssueResult,
    PRResult,
)

# ── GitActuator ──────────────────────────────────────────────────────


class TestGitActuatorCurrentBranch:
    def test_returns_branch_name(self, tmp_path):
        with patch("steward.actuators._git") as mock:
            mock.return_value = subprocess.CompletedProcess([], 0, stdout="feature/x\n", stderr="")
            git = GitActuator(cwd=str(tmp_path))
            assert git.current_branch() == "feature/x"

    def test_returns_none_on_failure(self, tmp_path):
        with patch("steward.actuators._git") as mock:
            mock.return_value = subprocess.CompletedProcess([], 128, stdout="", stderr="fatal")
            git = GitActuator(cwd=str(tmp_path))
            assert git.current_branch() is None

    def test_returns_none_on_timeout(self, tmp_path):
        with patch("steward.actuators._git", side_effect=subprocess.TimeoutExpired("git", 30)):
            git = GitActuator(cwd=str(tmp_path))
            assert git.current_branch() is None


class TestGitActuatorCreateBranch:
    def test_creates_branch(self, tmp_path):
        with patch("steward.actuators._git") as mock:
            mock.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
            git = GitActuator(cwd=str(tmp_path))
            result = git.create_branch("steward/fix/123")
            assert result.success

    def test_blocks_protected_branch(self, tmp_path):
        git = GitActuator(cwd=str(tmp_path))
        result = git.create_branch("main")
        assert not result.success
        assert "protected" in result.error.lower()

    def test_blocks_master(self, tmp_path):
        git = GitActuator(cwd=str(tmp_path))
        result = git.create_branch("master")
        assert not result.success

    def test_returns_error_on_git_failure(self, tmp_path):
        with patch("steward.actuators._git") as mock:
            mock.return_value = subprocess.CompletedProcess([], 128, stdout="", stderr="already exists")
            git = GitActuator(cwd=str(tmp_path))
            result = git.create_branch("steward/fix/123")
            assert not result.success
            assert "already exists" in result.error


class TestGitActuatorCommit:
    def test_commit_succeeds(self, tmp_path):
        with patch("steward.actuators._git") as mock:
            mock.return_value = subprocess.CompletedProcess([], 0, stdout="[branch abc123]", stderr="")
            git = GitActuator(cwd=str(tmp_path))
            # Mock current_branch to return non-protected
            with patch.object(git, "current_branch", return_value="feature/x"):
                result = git.commit("fix: thing", files={"a.py", "b.py"})
                assert result.success

    def test_commit_blocked_on_main(self, tmp_path):
        git = GitActuator(cwd=str(tmp_path))
        with patch.object(git, "current_branch", return_value="main"):
            result = git.commit("fix: thing")
            assert not result.success
            assert "BLOCKED" in result.error


class TestGitActuatorPush:
    def test_push_succeeds(self, tmp_path):
        with patch("steward.actuators._git") as mock:
            mock.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="Branch pushed")
            git = GitActuator(cwd=str(tmp_path))
            result = git.push("feature/x")
            assert result.success

    def test_push_blocked_on_main(self, tmp_path):
        git = GitActuator(cwd=str(tmp_path))
        result = git.push("main")
        assert not result.success
        assert "BLOCKED" in result.error

    def test_push_blocked_on_master(self, tmp_path):
        git = GitActuator(cwd=str(tmp_path))
        result = git.push("master")
        assert not result.success


class TestGitActuatorCleanup:
    def test_cleanup_branch(self, tmp_path):
        with patch("steward.actuators._git") as mock:
            mock.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
            git = GitActuator(cwd=str(tmp_path))
            result = git.cleanup_branch("steward/fix/123")
            assert result.success


class TestGitActuatorHasChanges:
    def test_no_changes(self, tmp_path):
        with patch("steward.actuators._git") as mock:
            mock.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
            git = GitActuator(cwd=str(tmp_path))
            assert not git.has_changes()

    def test_has_changes(self, tmp_path):
        with patch("steward.actuators._git") as mock:
            mock.return_value = subprocess.CompletedProcess([], 0, stdout="M file.py\n", stderr="")
            git = GitActuator(cwd=str(tmp_path))
            assert git.has_changes()


# ── GitHubActuator ───────────────────────────────────────────────────


class TestGitHubActuatorCreatePR:
    def test_creates_pr_successfully(self):
        gh = MagicMock()
        gh.call.return_value = "https://github.com/owner/repo/pull/42\n"
        actuator = GitHubActuator(gh_client=gh)

        result = actuator.create_pr(title="fix: thing", body="description", head="feature/x")
        assert result.success
        assert result.url == "https://github.com/owner/repo/pull/42"
        assert result.number == 42

    def test_returns_error_on_failure(self):
        gh = MagicMock()
        gh.call.return_value = None
        actuator = GitHubActuator(gh_client=gh)

        result = actuator.create_pr(title="fix: thing", body="desc", head="feature/x")
        assert not result.success
        assert result.error

    def test_handles_url_without_number(self):
        gh = MagicMock()
        gh.call.return_value = "https://github.com/owner/repo/pull/abc"
        actuator = GitHubActuator(gh_client=gh)

        result = actuator.create_pr(title="fix", body="", head="b")
        assert result.success
        assert result.number == 0  # Can't parse "abc" as int


class TestGitHubActuatorOpenIssue:
    def test_opens_issue(self):
        gh = MagicMock()
        gh.call.return_value = "https://github.com/owner/repo/issues/99\n"
        actuator = GitHubActuator(gh_client=gh)

        result = actuator.open_issue(title="Bug report", body="details")
        assert result.success
        assert result.number == 99

    def test_opens_issue_with_labels(self):
        gh = MagicMock()
        gh.call.return_value = "https://github.com/owner/repo/issues/1\n"
        actuator = GitHubActuator(gh_client=gh)

        actuator.open_issue(title="Bug", body="desc", labels=["bug", "p1"])
        args = gh.call.call_args[0][0]
        assert "--label" in args
        assert "bug,p1" in args

    def test_returns_error_on_failure(self):
        gh = MagicMock()
        gh.call.return_value = None
        actuator = GitHubActuator(gh_client=gh)

        result = actuator.open_issue(title="Bug", body="desc")
        assert not result.success


class TestGitHubActuatorCloseIssue:
    def test_closes_issue(self):
        gh = MagicMock()
        gh.call.return_value = "Closed issue #42"
        actuator = GitHubActuator(gh_client=gh)

        result = actuator.close_issue(42)
        assert result.success

    def test_returns_error_on_failure(self):
        gh = MagicMock()
        gh.call.return_value = None
        actuator = GitHubActuator(gh_client=gh)

        result = actuator.close_issue(42)
        assert not result.success


class TestGitHubActuatorComment:
    def test_comment_on_issue(self):
        gh = MagicMock()
        gh.call.return_value = "https://github.com/..."
        actuator = GitHubActuator(gh_client=gh)

        result = actuator.comment_on_issue(42, "LGTM")
        assert result.success

    def test_comment_on_pr(self):
        gh = MagicMock()
        gh.call.return_value = "https://github.com/..."
        actuator = GitHubActuator(gh_client=gh)

        result = actuator.comment_on_pr(42, "Ship it")
        assert result.success


class TestGitHubActuatorListPRs:
    def test_list_open_prs(self):
        gh = MagicMock()
        gh.call_json.return_value = [
            {"number": 1, "title": "Fix bug", "headRefName": "fix/bug"},
            {"number": 2, "title": "Add feature", "headRefName": "feat/x"},
        ]
        actuator = GitHubActuator(gh_client=gh)

        prs = actuator.list_open_prs()
        assert len(prs) == 2

    def test_returns_empty_on_failure(self):
        gh = MagicMock()
        gh.call_json.return_value = None
        actuator = GitHubActuator(gh_client=gh)

        assert actuator.list_open_prs() == []


class TestGitHubActuatorListIssues:
    def test_list_open_issues(self):
        gh = MagicMock()
        gh.call_json.return_value = [
            {"number": 10, "title": "Bug"},
        ]
        actuator = GitHubActuator(gh_client=gh)

        issues = actuator.list_open_issues()
        assert len(issues) == 1

    def test_returns_empty_on_failure(self):
        gh = MagicMock()
        gh.call_json.return_value = None
        actuator = GitHubActuator(gh_client=gh)

        assert actuator.list_open_issues() == []


class TestGitHubActuatorGetPR:
    def test_get_pr(self):
        gh = MagicMock()
        gh.call_json.return_value = {"number": 1, "title": "Fix", "state": "OPEN"}
        actuator = GitHubActuator(gh_client=gh)

        pr = actuator.get_pr(1)
        assert pr["number"] == 1

    def test_returns_none_on_failure(self):
        gh = MagicMock()
        gh.call_json.return_value = None
        actuator = GitHubActuator(gh_client=gh)

        assert actuator.get_pr(1) is None


class TestGitHubActuatorMergePR:
    def test_merge_pr(self):
        gh = MagicMock()
        gh.call.return_value = "Merged PR #1"
        actuator = GitHubActuator(gh_client=gh)

        result = actuator.merge_pr(1)
        assert result.success

    def test_merge_pr_rebase(self):
        gh = MagicMock()
        gh.call.return_value = "Merged"
        actuator = GitHubActuator(gh_client=gh)

        actuator.merge_pr(1, method="rebase")
        args = gh.call.call_args[0][0]
        assert "--rebase" in args
