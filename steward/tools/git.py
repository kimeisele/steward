"""
Git Tool — Structured git operations with branch isolation.

Safety model:
    - NEVER operates on main/master directly (hard block)
    - Auto-stashes dirty state before branch switch
    - Uses GhClient for GitHub operations (PR create/list)
    - All mutations require feature branch context
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolResult

logger = logging.getLogger("STEWARD.TOOL.GIT")

# Protected branch names — NEVER allow direct commits/pushes
_PROTECTED_BRANCHES = frozenset({"main", "master", "develop", "release"})

# Valid branch name pattern
_BRANCH_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*$")


def _git(args: list[str], cwd: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run a git command. Raises on timeout."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


class GitTool(Tool):
    """Structured git operations with branch isolation safety."""

    def __init__(self, cwd: str | None = None, gh_client: object | None = None) -> None:
        super().__init__()
        self._cwd = cwd
        self._gh = gh_client  # GhClient from steward.senses.gh

    @property
    def name(self) -> str:
        return "git"

    @property
    def description(self) -> str:
        return (
            "Git operations with branch isolation. Actions: status, diff, "
            "branch_create, checkout, commit, push, pr_create, pr_list. "
            "Cannot commit or push to main/master."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "required": True,
                "description": ("Git action: status, diff, branch_create, checkout, commit, push, pr_create, pr_list"),
            },
            "branch": {
                "type": "string",
                "required": False,
                "description": "Branch name (for branch_create, checkout)",
            },
            "message": {
                "type": "string",
                "required": False,
                "description": "Commit message (for commit)",
            },
            "files": {
                "type": "string",
                "required": False,
                "description": "Space-separated file paths to stage (for commit). Omit to stage all.",
            },
            "title": {
                "type": "string",
                "required": False,
                "description": "PR title (for pr_create)",
            },
            "body": {
                "type": "string",
                "required": False,
                "description": "PR body (for pr_create)",
            },
            "base": {
                "type": "string",
                "required": False,
                "description": "Base branch for PR (default: main)",
            },
            "path": {
                "type": "string",
                "required": False,
                "description": "File path filter (for diff)",
            },
            "staged": {
                "type": "boolean",
                "required": False,
                "description": "Show staged changes only (for diff)",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if "action" not in parameters:
            raise ValueError("Missing required parameter: action")
        valid_actions = {"status", "diff", "branch_create", "checkout", "commit", "push", "pr_create", "pr_list"}
        if parameters["action"] not in valid_actions:
            raise ValueError(f"Invalid action: {parameters['action']}. Valid: {', '.join(sorted(valid_actions))}")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        action = parameters["action"]
        dispatch = {
            "status": self._status,
            "diff": self._diff,
            "branch_create": self._branch_create,
            "checkout": self._checkout,
            "commit": self._commit,
            "push": self._push,
            "pr_create": self._pr_create,
            "pr_list": self._pr_list,
        }
        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, error=f"Unknown action: {action}")
        try:
            return handler(parameters)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error=f"Git {action} timed out")
        except FileNotFoundError:
            return ToolResult(success=False, error="git not found on PATH")
        except Exception as e:
            return ToolResult(success=False, error=f"Git {action} failed: {e}")

    def _current_branch(self) -> str | None:
        """Get current branch name."""
        r = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=self._cwd)
        return r.stdout.strip() if r.returncode == 0 else None

    def _is_protected(self, branch: str | None) -> bool:
        """Check if branch is protected."""
        return branch is not None and branch in _PROTECTED_BRANCHES

    def _has_changes(self) -> bool:
        """Check if working tree has uncommitted changes."""
        r = _git(["status", "--porcelain"], cwd=self._cwd)
        return bool(r.stdout.strip())

    def _auto_stash(self) -> bool:
        """Stash dirty state. Returns True if stashed."""
        if not self._has_changes():
            return False
        r = _git(["stash", "push", "-m", "steward-auto-stash"], cwd=self._cwd)
        if r.returncode == 0:
            logger.info("Auto-stashed dirty state before branch operation")
            return True
        return False

    def _auto_unstash(self) -> None:
        """Pop stash if we stashed earlier."""
        r = _git(["stash", "list"], cwd=self._cwd)
        if r.returncode == 0 and "steward-auto-stash" in r.stdout:
            _git(["stash", "pop"], cwd=self._cwd)
            logger.info("Restored auto-stashed state")

    # ── Actions ─────────────────────────────────────────────────────

    def _status(self, params: dict[str, object]) -> ToolResult:
        """git status with branch info."""
        branch = self._current_branch()
        r = _git(["status", "--short"], cwd=self._cwd)
        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip())

        lines = r.stdout.strip()
        output = f"Branch: {branch}\n{lines}" if lines else f"Branch: {branch}\nClean working tree"
        return ToolResult(success=True, output=output, metadata={"branch": branch})

    def _diff(self, params: dict[str, object]) -> ToolResult:
        """git diff with optional path filter and staged flag."""
        args = ["diff"]
        if params.get("staged"):
            args.append("--cached")
        path = params.get("path")
        if path:
            args.extend(["--", path])

        r = _git(args, cwd=self._cwd)
        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip())

        output = r.stdout.strip() or "(no changes)"
        return ToolResult(success=True, output=output)

    def _branch_create(self, params: dict[str, object]) -> ToolResult:
        """Create and checkout a new branch."""
        branch = params.get("branch")
        if not branch:
            return ToolResult(success=False, error="Missing required parameter: branch")
        if not _BRANCH_RE.match(branch):
            return ToolResult(success=False, error=f"Invalid branch name: {branch}")

        stashed = self._auto_stash()
        r = _git(["checkout", "-b", branch], cwd=self._cwd)
        if stashed:
            self._auto_unstash()

        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip())
        return ToolResult(success=True, output=f"Created and switched to branch: {branch}")

    def _checkout(self, params: dict[str, object]) -> ToolResult:
        """Checkout existing branch with auto-stash."""
        branch = params.get("branch")
        if not branch:
            return ToolResult(success=False, error="Missing required parameter: branch")

        stashed = self._auto_stash()
        r = _git(["checkout", branch], cwd=self._cwd)
        if stashed:
            self._auto_unstash()

        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip())
        return ToolResult(success=True, output=f"Switched to branch: {branch}")

    def _commit(self, params: dict[str, object]) -> ToolResult:
        """Stage files and commit. Blocked on protected branches."""
        branch = self._current_branch()
        if self._is_protected(branch):
            return ToolResult(
                success=False,
                error=f"BLOCKED: Cannot commit directly to protected branch '{branch}'. "
                "Create a feature branch first with action=branch_create.",
            )

        message = params.get("message")
        if not message:
            return ToolResult(success=False, error="Missing required parameter: message")

        # Stage files
        files = params.get("files", "").strip()
        if files:
            for f in files.split():
                _git(["add", f], cwd=self._cwd)
        else:
            _git(["add", "-A"], cwd=self._cwd)

        # Check if there's anything to commit
        r = _git(["diff", "--cached", "--quiet"], cwd=self._cwd)
        if r.returncode == 0:
            return ToolResult(success=True, output="Nothing to commit (working tree clean)")

        # Commit
        r = _git(["commit", "-m", message], cwd=self._cwd)
        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip())

        return ToolResult(
            success=True,
            output=r.stdout.strip(),
            metadata={"branch": branch},
        )

    def _push(self, params: dict[str, object]) -> ToolResult:
        """Push current branch. Blocked on protected branches."""
        branch = self._current_branch()
        if self._is_protected(branch):
            return ToolResult(
                success=False,
                error=f"BLOCKED: Cannot push directly to protected branch '{branch}'. "
                "Work on a feature branch and create a PR.",
            )

        r = _git(["push", "-u", "origin", branch], cwd=self._cwd, timeout=60)
        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip())

        output = r.stderr.strip() or r.stdout.strip()  # git push output is on stderr
        return ToolResult(success=True, output=output, metadata={"branch": branch})

    def _pr_create(self, params: dict[str, object]) -> ToolResult:
        """Create a pull request via gh CLI."""
        if not self._gh:
            return ToolResult(success=False, error="GitHub CLI not available (no GhClient)")

        title = params.get("title")
        if not title:
            return ToolResult(success=False, error="Missing required parameter: title")

        body = params.get("body", "")
        base = params.get("base", "main")

        args = ["pr", "create", "--title", title, "--body", body, "--base", base]
        result = self._gh.call(args, timeout=30)
        if result is None:
            return ToolResult(success=False, error="Failed to create PR (gh CLI error or rate limited)")

        return ToolResult(success=True, output=result, metadata={"pr_url": result.strip()})

    def _pr_list(self, params: dict[str, object]) -> ToolResult:
        """List open pull requests via gh CLI."""
        if not self._gh:
            return ToolResult(success=False, error="GitHub CLI not available (no GhClient)")

        result = self._gh.call_json(
            ["pr", "list", "--state=open", "--json=number,title,headRefName,author", "--limit=20"]
        )
        if result is None:
            return ToolResult(success=False, error="Failed to list PRs (gh CLI error or rate limited)")

        if not result:
            return ToolResult(success=True, output="No open pull requests")

        lines = []
        for pr in result:
            num = pr.get("number", "?")
            title = pr.get("title", "")
            branch = pr.get("headRefName", "?")
            author = pr.get("author", {})
            login = author.get("login", "?") if isinstance(author, dict) else "?"
            lines.append(f"#{num} [{branch}] {title} (by {login})")

        return ToolResult(success=True, output="\n".join(lines), metadata={"count": len(result)})
