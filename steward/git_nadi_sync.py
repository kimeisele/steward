"""
Git Nadi Sync — Network layer for federation nadi files.

Handles git pull/push with retry on non-fast-forward rejection.
The transport layer (NadiFederationTransport) handles file I/O.
This layer handles network sync via git.

Architecture:
    NadiFederationTransport (file I/O) → GitNadiSync (git network) → Remote

Git is not a message broker. This module compensates:
  - Retry loop on push rejection (pull-rebase-push, max 3 attempts)
  - Throttle: minimum interval between git operations (default 5 min)
  - Noop when federation_dir is not a git checkout

DHARMA phase: sync.pull() — fetch latest messages from remote
MOKSHA phase: sync.push() — publish outbound messages to remote
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("STEWARD.GIT_NADI_SYNC")

# Minimum seconds between git operations (prevents git history bloat)
DEFAULT_SYNC_INTERVAL_S = 300  # 5 minutes

_FEDERATION_PATHS = (
    "nadi_inbox.json",
    "nadi_outbox.json",
    "peer.json",
    "reports",
)


class GitNadiSync:
    """Git sync for federation nadi directory.

    Only active when the federation_dir is a git checkout.
    Pure local directories (no .git) are silently skipped.
    """

    def __init__(
        self,
        federation_dir: str,
        *,
        max_retries: int = 3,
        sync_interval_s: float = DEFAULT_SYNC_INTERVAL_S,
    ) -> None:
        self._dir = Path(federation_dir)
        self._max_retries = max_retries
        self._sync_interval_s = sync_interval_s
        self._last_pull: float = 0.0
        self._last_push: float = 0.0
        self._is_git = self._detect_git()

    @property
    def is_git_repo(self) -> bool:
        return self._is_git

    def pull(self) -> bool:
        """Pull latest from remote. Throttled by sync_interval_s.

        Returns True if pull succeeded or was skipped (throttled/not git).
        Returns False on git error.
        """
        if not self._is_git:
            return True

        now = time.monotonic()
        if (now - self._last_pull) < self._sync_interval_s:
            return True  # Throttled — skip

        try:
            self._run_git("fetch", "origin", "--prune")
            # Rebase local changes on top of remote
            self._run_git("rebase", "--autostash", "origin/HEAD")
            self._last_pull = time.monotonic()
            logger.debug("GIT_NADI: pull succeeded")
            return True
        except subprocess.CalledProcessError as e:
            logger.warning("GIT_NADI: pull failed: %s", e.stderr.strip() if e.stderr else e)
            # Abort failed rebase to leave repo in clean state
            try:
                self._run_git("rebase", "--abort")
            except subprocess.CalledProcessError:
                pass
            return False

    def push(self, message: str = "steward: federation sync") -> bool:
        """Stage, commit, push with retry on non-fast-forward rejection.

        Throttled by sync_interval_s. Returns True if push succeeded,
        was skipped (throttled/nothing to push/not git), or retried successfully.
        """
        if not self._is_git:
            return True

        now = time.monotonic()
        if (now - self._last_push) < self._sync_interval_s:
            return True  # Throttled — skip

        if self._staged_paths():
            logger.warning("GIT_NADI: refusing to use a non-empty pre-existing index")
            return False

        # Check if there's anything allowed to push
        if not self._has_changes():
            self._last_push = time.monotonic()
            return True

        stageable_paths = self._stageable_paths()
        if not stageable_paths:
            self._last_push = time.monotonic()
            return True

        # Stage only positively named federation files.
        try:
            self._run_git("add", "--all", "--", *stageable_paths)
        except subprocess.CalledProcessError as e:
            logger.warning("GIT_NADI: narrow staging failed: %s", e.stderr.strip() if e.stderr else e)
            return False

        staged_paths = self._staged_paths()
        if not staged_paths:
            self._last_push = time.monotonic()
            return True  # Nothing staged
        if not self._index_is_allowed(staged_paths):
            logger.error("GIT_NADI: refusing staged paths outside federation allowlist")
            return False

        # Commit
        try:
            self._run_git("commit", "-m", message)
        except subprocess.CalledProcessError as e:
            # Nothing to commit (race between status check and commit)
            if "nothing to commit" in (e.stdout or ""):
                self._last_push = time.monotonic()
                return True
            logger.warning("GIT_NADI: commit failed: %s", e.stderr.strip() if e.stderr else e)
            return False

        # Push with retry on non-fast-forward
        for attempt in range(1, self._max_retries + 1):
            try:
                self._run_git("push")
                self._last_push = time.monotonic()
                logger.info("GIT_NADI: push succeeded (attempt %d)", attempt)
                return True
            except subprocess.CalledProcessError as e:
                stderr = e.stderr.strip() if e.stderr else ""
                if "non-fast-forward" in stderr or "fetch first" in stderr or "rejected" in stderr:
                    logger.info(
                        "GIT_NADI: push rejected (attempt %d/%d), rebasing",
                        attempt,
                        self._max_retries,
                    )
                    if not self._rebase_and_retry():
                        logger.warning("GIT_NADI: rebase failed on attempt %d", attempt)
                        return False
                    # Loop continues — next iteration will try push again
                else:
                    logger.warning("GIT_NADI: push failed (non-retryable): %s", stderr)
                    return False

        logger.error("GIT_NADI: push failed after %d retries", self._max_retries)
        return False

    # ── Private ────────────────────────────────────────────────────

    def _detect_git(self) -> bool:
        """Check if federation_dir is inside a git checkout."""
        try:
            self._run_git("rev-parse", "--git-dir")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def _has_changes(self) -> bool:
        """Check if allowlisted federation paths have modifications."""
        try:
            status = self._run_git(
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                *_FEDERATION_PATHS,
            )
            return bool(status.strip())
        except subprocess.CalledProcessError:
            return False

    def _stageable_paths(self) -> list[str]:
        """Return allowlisted paths that exist or are already tracked."""
        stageable = []
        for path in _FEDERATION_PATHS:
            if (self._dir / path).exists() or self._run_git("ls-files", "--", path).strip():
                stageable.append(path)
        return stageable

    def _staged_paths(self) -> list[str]:
        """Return repo-relative paths currently present in the index diff."""
        output = self._run_git("diff", "--cached", "--name-only", "-z")
        return [path for path in output.split("\0") if path]

    def _index_is_allowed(self, staged_paths: list[str]) -> bool:
        """Validate repo-relative index names against the federation prefix."""
        prefix = self._run_git("rev-parse", "--show-prefix").strip()
        allowed_files = {f"{prefix}{path}" for path in _FEDERATION_PATHS[:-1]}
        reports_prefix = f"{prefix}reports/"
        return all(path in allowed_files or path.startswith(reports_prefix) for path in staged_paths)

    def _rebase_and_retry(self) -> bool:
        """Pull --rebase to resolve non-fast-forward. Returns True if clean."""
        try:
            self._run_git("pull", "--rebase", "--autostash")
            return True
        except subprocess.CalledProcessError:
            # Rebase conflict — abort and give up
            try:
                self._run_git("rebase", "--abort")
            except subprocess.CalledProcessError:
                pass
            return False

    def _run_git(self, *args: str) -> str:
        """Run a git command in the federation directory."""
        r = subprocess.run(
            ["git", *args],
            cwd=str(self._dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            raise subprocess.CalledProcessError(r.returncode, ["git", *args], output=r.stdout, stderr=r.stderr)
        return r.stdout
