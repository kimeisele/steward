"""
Intent Actuators — The muscles that execute real actions.

Programmatic APIs for the autonomy engine to interact with the world:
- GitActuator:    local git operations (branch, commit, push)
- GitHubActuator: remote GitHub operations (PR, issue, comment)

These are NOT LLM tools (GitTool serves that role). These are called
directly by AutonomyEngine to turn intents into physical actions.

Safety:
    - Protected branches (main/master) are hard-blocked
    - All operations return typed Result objects (never raise)
    - Rate limiting via GhClient
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("STEWARD.ACTUATORS")

_PROTECTED = frozenset({"main", "master", "develop", "release"})


def _git(args: list[str], cwd: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


# ── Result Types ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ActuatorResult:
    """Base result for all actuator operations."""

    success: bool
    output: str = ""
    error: str = ""


@dataclass(frozen=True)
class PRResult:
    """Result of a PR creation."""

    success: bool
    url: str = ""
    number: int = 0
    error: str = ""


@dataclass(frozen=True)
class IssueResult:
    """Result of an issue creation."""

    success: bool
    url: str = ""
    number: int = 0
    error: str = ""


# ── Git Actuator (local) ─────────────────────────────────────────────


class GitActuator:
    """Structured local git operations for the autonomy engine.

    All methods return ActuatorResult — never raise exceptions.
    Protected branches are hard-blocked for mutations.
    """

    def __init__(self, cwd: str) -> None:
        self._cwd = cwd

    def current_branch(self) -> str | None:
        try:
            r = _git(["rev-parse", "--abbrev-ref", "HEAD"], self._cwd)
            return r.stdout.strip() if r.returncode == 0 else None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def has_changes(self) -> bool:
        try:
            r = _git(["status", "--porcelain"], self._cwd)
            return bool(r.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def create_branch(self, name: str) -> ActuatorResult:
        if name in _PROTECTED:
            return ActuatorResult(success=False, error=f"Cannot create protected branch: {name}")
        try:
            r = _git(["checkout", "-b", name], self._cwd)
            if r.returncode != 0:
                return ActuatorResult(success=False, error=r.stderr.strip())
            return ActuatorResult(success=True, output=f"Created branch: {name}")
        except subprocess.TimeoutExpired:
            return ActuatorResult(success=False, error="git checkout -b timed out")
        except FileNotFoundError:
            return ActuatorResult(success=False, error="git not found")

    def checkout(self, branch: str) -> ActuatorResult:
        try:
            r = _git(["checkout", branch], self._cwd)
            if r.returncode != 0:
                return ActuatorResult(success=False, error=r.stderr.strip())
            return ActuatorResult(success=True, output=f"Switched to: {branch}")
        except subprocess.TimeoutExpired:
            return ActuatorResult(success=False, error="git checkout timed out")
        except FileNotFoundError:
            return ActuatorResult(success=False, error="git not found")

    def commit(self, message: str, files: set[str] | None = None) -> ActuatorResult:
        """Stage files and commit. Blocked on protected branches."""
        branch = self.current_branch()
        if branch in _PROTECTED:
            return ActuatorResult(
                success=False,
                error=f"BLOCKED: cannot commit to protected branch '{branch}'",
            )
        try:
            if files:
                for f in files:
                    _git(["add", f], self._cwd)
            else:
                _git(["add", "-A"], self._cwd)

            r = _git(["commit", "-m", message], self._cwd)
            if r.returncode != 0:
                return ActuatorResult(success=False, error=r.stderr.strip())
            return ActuatorResult(success=True, output=r.stdout.strip())
        except subprocess.TimeoutExpired:
            return ActuatorResult(success=False, error="git commit timed out")
        except FileNotFoundError:
            return ActuatorResult(success=False, error="git not found")

    def push(self, branch: str | None = None) -> ActuatorResult:
        """Push to origin. Blocked on protected branches."""
        target = branch or self.current_branch()
        if target in _PROTECTED:
            return ActuatorResult(
                success=False,
                error=f"BLOCKED: cannot push to protected branch '{target}'",
            )
        try:
            r = _git(["push", "-u", "origin", target], self._cwd, timeout=60)
            if r.returncode != 0:
                return ActuatorResult(success=False, error=r.stderr.strip())
            return ActuatorResult(success=True, output=r.stderr.strip() or r.stdout.strip())
        except subprocess.TimeoutExpired:
            return ActuatorResult(success=False, error="git push timed out")
        except FileNotFoundError:
            return ActuatorResult(success=False, error="git not found")

    def cleanup_branch(self, branch_name: str, return_to: str = "main") -> ActuatorResult:
        """Return to base branch and delete feature branch."""
        try:
            _git(["checkout", return_to], self._cwd)
        except Exception as e:
            logger.warning("Branch cleanup: checkout %s failed: %s", return_to, e)
        try:
            r = _git(["branch", "-D", branch_name], self._cwd)
            if r.returncode != 0:
                return ActuatorResult(success=False, error=r.stderr.strip())
            return ActuatorResult(success=True, output=f"Deleted branch: {branch_name}")
        except Exception as e:
            return ActuatorResult(success=False, error=str(e))


# ── GitHub Actuator (remote) ─────────────────────────────────────────


class GitHubActuator:
    """Structured GitHub operations via gh CLI.

    All methods return typed result objects — never raise exceptions.
    Requires a GhClient instance for rate-limited CLI access.
    """

    def __init__(self, gh_client: object) -> None:
        self._gh = gh_client

    def create_pr(
        self,
        *,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> PRResult:
        """Create a pull request. Returns PRResult with URL."""
        result = self._gh.call(
            ["pr", "create", "--title", title, "--body", body, "--head", head, "--base", base],
            timeout=30,
        )
        if result is None:
            return PRResult(success=False, error="gh pr create failed (rate limit or CLI error)")

        url = result.strip()
        # Extract PR number from URL (e.g., .../pull/42)
        number = 0
        if "/pull/" in url:
            try:
                number = int(url.rstrip("/").rsplit("/", 1)[-1])
            except ValueError:
                pass

        return PRResult(success=True, url=url, number=number)

    def open_issue(
        self,
        *,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> IssueResult:
        """Open a GitHub issue. Returns IssueResult with URL."""
        args = ["issue", "create", "--title", title, "--body", body]
        if labels:
            args.extend(["--label", ",".join(labels)])

        result = self._gh.call(args, timeout=30)
        if result is None:
            return IssueResult(success=False, error="gh issue create failed")

        url = result.strip()
        number = 0
        if "/issues/" in url:
            try:
                number = int(url.rstrip("/").rsplit("/", 1)[-1])
            except ValueError:
                pass

        return IssueResult(success=True, url=url, number=number)

    def close_issue(self, issue_number: int) -> ActuatorResult:
        """Close a GitHub issue."""
        result = self._gh.call(
            ["issue", "close", str(issue_number)],
            timeout=15,
        )
        if result is None:
            return ActuatorResult(success=False, error=f"gh issue close {issue_number} failed")
        return ActuatorResult(success=True, output=result.strip())

    def comment_on_issue(self, issue_number: int, body: str) -> ActuatorResult:
        """Add a comment to an issue or PR."""
        result = self._gh.call(
            ["issue", "comment", str(issue_number), "--body", body],
            timeout=15,
        )
        if result is None:
            return ActuatorResult(success=False, error=f"gh issue comment {issue_number} failed")
        return ActuatorResult(success=True, output=result.strip())

    def comment_on_pr(self, pr_number: int, body: str) -> ActuatorResult:
        """Add a review comment to a PR."""
        result = self._gh.call(
            ["pr", "comment", str(pr_number), "--body", body],
            timeout=15,
        )
        if result is None:
            return ActuatorResult(success=False, error=f"gh pr comment {pr_number} failed")
        return ActuatorResult(success=True, output=result.strip())

    def list_open_prs(self, limit: int = 20) -> list[dict]:
        """List open PRs. Returns list of dicts or empty on failure."""
        result = self._gh.call_json(
            ["pr", "list", "--state=open", "--json=number,title,headRefName,author,url", f"--limit={limit}"],
        )
        if result is None or not isinstance(result, list):
            return []
        return result

    def list_open_issues(self, limit: int = 20) -> list[dict]:
        """List open issues. Returns list of dicts or empty on failure."""
        result = self._gh.call_json(
            ["issue", "list", "--state=open", "--json=number,title,labels,url", f"--limit={limit}"],
        )
        if result is None or not isinstance(result, list):
            return []
        return result

    def get_pr(self, pr_number: int) -> dict | None:
        """Get PR details. Returns dict or None."""
        result = self._gh.call_json(
            ["pr", "view", str(pr_number), "--json=number,title,state,headRefName,body,url"],
        )
        if result is None or not isinstance(result, dict):
            return None
        return result

    def merge_pr(self, pr_number: int, method: str = "squash") -> ActuatorResult:
        """Merge a PR. Method: merge, squash, rebase."""
        result = self._gh.call(
            ["pr", "merge", str(pr_number), f"--{method}", "--delete-branch"],
            timeout=30,
        )
        if result is None:
            return ActuatorResult(success=False, error=f"gh pr merge {pr_number} failed")
        return ActuatorResult(success=True, output=result.strip())

    def enable_auto_merge(self, pr_url: str) -> ActuatorResult:
        """Enable GitHub auto-merge on a PR.

        Uses `gh pr merge --auto` — GitHub merges automatically when
        all required status checks pass. Requires branch protection
        rules to be configured on the repo.
        """
        result = self._gh.call(
            ["pr", "merge", "--auto", "--merge", pr_url.strip()],
            timeout=15,
        )
        if result is None:
            return ActuatorResult(
                success=False,
                error=f"gh pr merge --auto failed for {pr_url}",
            )
        return ActuatorResult(success=True, output=result.strip())
