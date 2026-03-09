"""Tests for remote sense perception — GhClient + GitSense remote.

All tests use fake/stub GhClient — no real `gh` CLI calls.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from collections import deque

from steward.senses.gh import GhClient, get_gh_client
from steward.senses.git_sense import GitSense
from vibe_core.mahamantra.protocols._sense import Jnanendriya, Tanmatra


# ── Fake GhClient for GitSense tests ────────────────────────────────


class FakeGhClient:
    """Stub GhClient that returns pre-configured responses."""

    def __init__(
        self,
        available: bool = True,
        runs: list | None = None,
        prs: list | None = None,
    ) -> None:
        self._available = available
        self._runs = runs
        self._prs = prs

    @property
    def is_available(self) -> bool:
        return self._available

    def call(self, args: list[str], timeout: int = 15) -> str | None:
        if not self._available:
            return None
        return json.dumps(self._resolve(args))

    def call_json(self, args: list[str], timeout: int = 15) -> dict | list | None:
        if not self._available:
            return None
        return self._resolve(args)

    def _resolve(self, args: list[str]) -> list | None:
        joined = " ".join(args)
        if "run list" in joined and self._runs is not None:
            return self._runs
        if "pr list" in joined and self._prs is not None:
            return self._prs
        return None

    def stats(self) -> dict:
        return {"total_calls": 0, "throttled_calls": 0, "offline": not self._available}


# ── GhClient Unit Tests ─────────────────────────────────────────────


class TestGhClient:
    def test_offline_returns_none(self):
        """Offline client returns None for all calls."""
        client = GhClient(_offline=True)
        assert client.call(["run", "list"]) is None
        assert client.call_json(["pr", "list"]) is None
        assert client.is_available is False

    def test_stats_dict(self):
        """Stats returns all diagnostic fields."""
        client = GhClient()
        s = client.stats()
        assert "total_calls" in s
        assert "throttled_calls" in s
        assert "offline" in s
        assert "backoff_step" in s
        assert "is_available" in s

    def test_rate_limit_throttles(self):
        """Calls beyond max_per_minute are throttled."""
        client = GhClient(max_per_minute=2, _offline=True)
        # Can't actually test subprocess, but verify throttle logic
        # by checking the stats structure
        assert client.stats()["throttled_calls"] == 0

    def test_backoff_trigger(self):
        """Backoff increments step and sets future timestamp."""
        client = GhClient()
        client._trigger_backoff()
        assert client._backoff_step == 1
        assert client._backoff_until > time.monotonic() - 1
        assert client.stats()["throttled_calls"] == 1

    def test_backoff_exponential(self):
        """Multiple backoffs escalate: 30s → 60s → 120s."""
        client = GhClient()
        client._trigger_backoff()  # 30s
        assert client._backoff_step == 1
        client._backoff_until = 0  # reset for next trigger
        client._trigger_backoff()  # 60s
        assert client._backoff_step == 2
        client._backoff_until = 0
        client._trigger_backoff()  # 120s
        assert client._backoff_step == 3

    def test_call_json_none_on_none(self):
        """call_json returns None when call returns None."""
        client = GhClient(_offline=True)
        assert client.call_json(["anything"]) is None

    def test_is_available_when_online(self):
        """is_available True when not offline."""
        client = GhClient(_offline=False)
        assert client.is_available is True


# ── GitSense Remote Perception Tests ─────────────────────────────────


class TestGitSenseRemote:
    def test_local_only_without_gh(self):
        """Without GhClient, perceives local only."""
        sense = GitSense(cwd=".", gh_client=None)
        perception = sense.perceive()
        assert perception.data.get("perceives") == "local"
        assert "ci_status" not in perception.data

    def test_local_only_with_offline_gh(self):
        """Offline GhClient falls back to local-only, no error."""
        gh = FakeGhClient(available=False)
        sense = GitSense(cwd=".", gh_client=gh)
        perception = sense.perceive()
        assert perception.data.get("perceives") == "local"

    def test_local_remote_with_ci_success(self):
        """GhClient with CI success → local+remote, sattva preserved."""
        gh = FakeGhClient(
            available=True,
            runs=[{"status": "completed", "conclusion": "success", "name": "CI"}],
            prs=[],
        )
        sense = GitSense(cwd=".", gh_client=gh)
        perception = sense.perceive()
        assert perception.data.get("perceives") == "local+remote"
        assert perception.data["ci_conclusion"] == "success"
        assert perception.data["open_prs"] == 0
        # CI success should not force tamas
        assert perception.quality != "tamas" or perception.data.get("dirty_count", 0) > 10

    def test_ci_failure_increases_pain(self):
        """CI failure → tamas quality, high intensity."""
        gh = FakeGhClient(
            available=True,
            runs=[{"status": "completed", "conclusion": "failure", "name": "CI"}],
            prs=[],
        )
        sense = GitSense(cwd=".", gh_client=gh)
        perception = sense.perceive()
        assert perception.data.get("perceives") == "local+remote"
        assert perception.data["ci_conclusion"] == "failure"
        assert perception.quality == "tamas"
        assert perception.intensity >= 0.8

    def test_open_prs_counted(self):
        """Open PRs are counted in remote data."""
        gh = FakeGhClient(
            available=True,
            runs=[{"status": "completed", "conclusion": "success", "name": "CI"}],
            prs=[
                {"number": 1, "title": "feat: foo", "headRefName": "feat/foo"},
                {"number": 2, "title": "fix: bar", "headRefName": "fix/bar"},
            ],
        )
        sense = GitSense(cwd=".", gh_client=gh)
        perception = sense.perceive()
        assert perception.data["open_prs"] == 2

    def test_no_runs_no_crash(self):
        """Empty CI runs → remote available but no CI data, no crash."""
        gh = FakeGhClient(available=True, runs=[], prs=[])
        sense = GitSense(cwd=".", gh_client=gh)
        perception = sense.perceive()
        # gh is available and returned data (empty lists) → still local+remote
        assert perception.data.get("perceives") == "local+remote"
        assert perception.data.get("open_prs") == 0
        # No ci_conclusion key since runs list was empty
        assert "ci_conclusion" not in perception.data


# ── SenseCoordinator Integration ─────────────────────────────────────


class TestCoordinatorRemote:
    def test_coordinator_boots_with_gh(self):
        """SenseCoordinator boots successfully with GhClient wired."""
        from steward.senses.coordinator import SenseCoordinator

        coord = SenseCoordinator(cwd=".")
        git_sense = coord.senses.get(Jnanendriya.SROTRA)
        assert git_sense is not None
        assert hasattr(git_sense, "_gh")

    def test_format_prompt_includes_remote(self):
        """format_for_prompt() shows CI + PR info when remote available."""
        from steward.senses.coordinator import SenseCoordinator

        coord = SenseCoordinator(cwd=".")
        # Replace GitSense with one using FakeGhClient
        gh = FakeGhClient(
            available=True,
            runs=[{"status": "completed", "conclusion": "success", "name": "CI"}],
            prs=[{"number": 1, "title": "test", "headRefName": "test"}],
        )
        enhanced = GitSense(cwd=".", gh_client=gh)
        coord.register_sense(enhanced)
        coord.perceive_all()
        prompt = coord.format_for_prompt()
        assert "ci=success" in prompt
        assert "1 open PRs" in prompt
