"""
SROTRA — The Ear (Git Sense).

Perceives project history through git. Hears:
- Current branch and uncommitted changes
- Recent commit activity
- Stash state
- Upstream divergence

Tanmatra: SABDA (sound — git events are the project's voice)
Mahabhuta: AKASA (ether — git is the communication medium)

SB 3.26.47: "From the sky, the sense of hearing was generated..."
Git history IS the project's sound — it tells what happened.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from vibe_core.mahamantra.protocols._sense import (
    Jnanendriya,
    SensePerception,
    Tanmatra,
)

if TYPE_CHECKING:
    from steward.senses.gh import GhClient

logger = logging.getLogger("STEWARD.SENSE.GIT")


class GitSense:
    """SROTRA — perceives project history through git.

    Implements SenseProtocol. All perception is deterministic
    (subprocess calls to git, gh CLI). Zero LLM.

    Local perception: git branch, dirty files, stash, upstream.
    Remote perception (when GhClient available): CI status, open PRs.
    """

    # TTL for remote perception cache — gh CLI calls are expensive (~2s)
    _REMOTE_TTL = 60.0  # seconds

    def __init__(self, cwd: str | None = None, gh_client: GhClient | None = None) -> None:
        self._cwd = cwd or str(Path.cwd())
        self._is_git = self._check_git_repo()
        self._gh = gh_client
        self._remote_cache: dict | None = None
        self._remote_cache_time: float = 0.0

    def has_remote_perception(self) -> bool:
        """RemotePerception protocol — True when gh CLI is available."""
        return bool(self._gh and self._gh.is_available)

    @property
    def jnanendriya(self) -> Jnanendriya:
        return Jnanendriya.SROTRA

    @property
    def tanmatra(self) -> Tanmatra:
        return Tanmatra.SABDA

    @property
    def is_active(self) -> bool:
        return self._is_git

    def perceive(self) -> SensePerception:
        """Perceive git state — branch, dirty files, recent activity."""
        if not self._is_git:
            return SensePerception(
                sense=Jnanendriya.SROTRA,
                tanmatra=Tanmatra.SABDA,
                data={"is_git": False},
                intensity=0.1,
                quality="tamas",
            )

        branch = self._git("rev-parse", "--abbrev-ref", "HEAD").strip() or "unknown"
        dirty_files = self._git("status", "--porcelain", "--short") or ""
        dirty_count = len([line for line in dirty_files.strip().split("\n") if line.strip()])
        stash_output = self._git("stash", "list").strip()
        stash_count = len(stash_output.split("\n")) if stash_output else 0

        # Recent commits (last 5)
        log_output = self._git("log", "--oneline", "-5", "--no-decorate") or ""
        recent_commits = [line.strip() for line in log_output.strip().split("\n") if line.strip()]

        # Upstream status
        upstream_status = self._check_upstream()

        # Determine intensity and quality
        intensity = 0.2  # baseline: calm
        quality = "sattva"

        if dirty_count > 0:
            intensity += min(0.3, dirty_count * 0.05)
            quality = "rajas"  # active/changing
        if dirty_count > 10:
            quality = "tamas"  # too many uncommitted changes
            intensity = min(1.0, intensity + 0.3)
        if upstream_status == "diverged":
            intensity = min(1.0, intensity + 0.2)
            quality = "tamas"

        data: dict = {
            "is_git": True,
            "branch": branch,
            "dirty_count": dirty_count,
            "dirty_files": dirty_files.strip()[:500] if dirty_files else "",
            "stash_count": stash_count,
            "recent_commits": recent_commits[:5],
            "upstream": upstream_status,
            "perceives": "local",
        }

        # Remote perception (if gh available)
        remote = self._perceive_remote()
        if remote:
            data.update(remote)
            data["perceives"] = "local+remote"
            if remote.get("ci_conclusion") == "failure":
                intensity = max(intensity, 0.8)
                quality = "tamas"

        return SensePerception(
            sense=Jnanendriya.SROTRA,
            tanmatra=Tanmatra.SABDA,
            data=data,
            intensity=intensity,
            quality=quality,
        )

    def get_pain_level(self) -> float:
        """Pain = dirty working tree + diverged upstream."""
        if not self._is_git:
            return 0.0
        perception = self.perceive()
        if perception.quality == "tamas":
            return perception.intensity
        return perception.intensity * 0.3  # rajas is mild discomfort

    def _check_git_repo(self) -> bool:
        try:
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self._cwd,
                capture_output=True,
                check=True,
                timeout=5,
            )
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _git(self, *args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self._cwd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout
        except (subprocess.SubprocessError, FileNotFoundError):
            return ""

    def _perceive_remote(self) -> dict | None:
        """Perceive GitHub state via gh CLI. TTL-cached to avoid 2s+ penalty.

        gh CLI calls are the #1 boot bottleneck (~2.4s for 2 calls).
        Cache results for _REMOTE_TTL seconds — CI status doesn't change every second.
        """
        if not self._gh or not self._gh.is_available:
            return None

        # Return cached result if within TTL
        now = time.monotonic()
        if self._remote_cache is not None and (now - self._remote_cache_time) < self._REMOTE_TTL:
            return self._remote_cache

        remote: dict = {}

        # CI status: last 3 workflow runs
        runs = self._gh.call_json(
            [
                "run",
                "list",
                "--limit=3",
                "--json=status,conclusion,updatedAt,name",
            ]
        )
        if runs and isinstance(runs, list):
            remote["ci_runs"] = len(runs)
            latest = runs[0] if runs else {}
            remote["ci_status"] = latest.get("status", "unknown")
            remote["ci_conclusion"] = latest.get("conclusion", "unknown")

        # Open PRs
        prs = self._gh.call_json(
            [
                "pr",
                "list",
                "--state=open",
                "--json=number,title,headRefName",
                "--limit=10",
            ]
        )
        if prs is not None and isinstance(prs, list):
            remote["open_prs"] = len(prs)

        result = remote or None
        self._remote_cache = result
        self._remote_cache_time = now
        return result

    def _check_upstream(self) -> str:
        """Check relationship with upstream branch."""
        local = self._git("rev-parse", "HEAD").strip()
        remote = self._git("rev-parse", "@{upstream}").strip()
        if not local or not remote:
            return "no_upstream"
        if local == remote:
            return "up_to_date"
        base = self._git("merge-base", local, remote).strip()
        if base == remote:
            return "ahead"
        if base == local:
            return "behind"
        return "diverged"
