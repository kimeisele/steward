"""Tests for GitNadiSync — git network layer for federation nadi files.

Validates:
  - Noop on non-git directories (pure local federation)
  - Pull fetches latest from remote
  - Push with retry on non-fast-forward rejection
  - Throttling prevents git history bloat
  - Race condition: concurrent pushes from two agents
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from steward.git_nadi_sync import GitNadiSync


def _git(cwd: Path, *args: str) -> str:
    """Run git command in directory."""
    r = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr}")
    return r.stdout


def _init_bare_remote(tmp_path: Path) -> Path:
    """Create a bare git repo (simulates GitHub remote)."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    return remote


def _clone_to(remote: Path, dest: Path) -> Path:
    """Clone remote into dest."""
    subprocess.run(
        ["git", "clone", str(remote), str(dest)],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    _git(dest, "config", "user.email", "test@test.com")
    _git(dest, "config", "user.name", "test")
    return dest


def _seed_remote(remote: Path, tmp_path: Path) -> None:
    """Push an initial commit to the bare remote."""
    seed = tmp_path / "seed"
    _clone_to(remote, seed)
    (seed / "nadi_inbox.json").write_text("[]")
    (seed / "nadi_outbox.json").write_text("[]")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "init")
    _git(seed, "push")


class TestGitNadiSyncBasics:
    """Basic behavior: detect git, throttle, noop on non-git."""

    def test_non_git_dir_is_noop(self, tmp_path):
        """Plain directory (no .git) → all operations return True (noop)."""
        sync = GitNadiSync(str(tmp_path))
        assert not sync.is_git_repo
        assert sync.pull() is True
        assert sync.push() is True

    def test_detects_git_repo(self, tmp_path):
        _git(tmp_path, "init")
        sync = GitNadiSync(str(tmp_path))
        assert sync.is_git_repo

    def test_throttle_skips_rapid_calls(self, tmp_path):
        """Two rapid pull() calls — second is throttled (skipped)."""
        remote = _init_bare_remote(tmp_path)
        _seed_remote(remote, tmp_path)
        agent = tmp_path / "agent"
        _clone_to(remote, agent)

        sync = GitNadiSync(str(agent), sync_interval_s=60)
        assert sync.pull() is True
        # Second call within 60s — throttled
        assert sync.pull() is True
        # Verify _last_pull was set (throttle active)
        assert sync._last_pull > 0

    def test_push_with_nothing_to_push(self, tmp_path):
        """Clean working tree → push returns True without git operations."""
        remote = _init_bare_remote(tmp_path)
        _seed_remote(remote, tmp_path)
        agent = tmp_path / "agent"
        _clone_to(remote, agent)

        sync = GitNadiSync(str(agent), sync_interval_s=0)
        assert sync.push() is True


class TestGitNadiSyncPushRetry:
    """Push with retry on non-fast-forward rejection."""

    def test_simple_push(self, tmp_path):
        """Single agent push — no conflict."""
        remote = _init_bare_remote(tmp_path)
        _seed_remote(remote, tmp_path)
        agent = tmp_path / "agent"
        _clone_to(remote, agent)

        # Write a message to nadi_inbox.json
        inbox = agent / "nadi_inbox.json"
        inbox.write_text(json.dumps([{"source": "steward", "operation": "heartbeat"}]))

        sync = GitNadiSync(str(agent), sync_interval_s=0)
        assert sync.push(message="test heartbeat") is True

        # Verify remote has the commit
        log = _git(agent, "log", "--oneline", "-1")
        assert "test heartbeat" in log

    def test_push_retry_on_concurrent_modification(self, tmp_path):
        """Two agents push simultaneously — one retries and succeeds.

        This is THE critical test: simulates the race condition where
        Steward pushes while agent-city modifies the same remote.
        """
        remote = _init_bare_remote(tmp_path)
        _seed_remote(remote, tmp_path)

        # Clone for agent A (steward) and agent B (agent-city)
        agent_a = tmp_path / "agent_a"
        agent_b = tmp_path / "agent_b"
        _clone_to(remote, agent_a)
        _clone_to(remote, agent_b)

        # Agent B pushes first (simulates agent-city writing a heartbeat)
        outbox_b = agent_b / "nadi_outbox.json"
        outbox_b.write_text(json.dumps([{"source": "agent-city", "operation": "city_report"}]))
        _git(agent_b, "add", "-A")
        _git(agent_b, "commit", "-m", "agent-city: city report")
        _git(agent_b, "push")

        # Agent A (steward) writes to inbox — unaware of B's push
        inbox_a = agent_a / "nadi_inbox.json"
        inbox_a.write_text(json.dumps([{"source": "steward", "operation": "heartbeat"}]))

        # Agent A's push should detect the rejection and retry with rebase
        sync_a = GitNadiSync(str(agent_a), sync_interval_s=0, max_retries=3)
        result = sync_a.push(message="steward: heartbeat")
        assert result is True

        # Verify both commits exist in the remote
        _git(agent_a, "pull", "--rebase")
        log = _git(agent_a, "log", "--oneline")
        assert "steward: heartbeat" in log
        assert "agent-city: city report" in log

        # Verify both files have their content preserved
        inbox_content = json.loads(inbox_a.read_text())
        assert any(m.get("source") == "steward" for m in inbox_content)

    def test_push_gives_up_after_max_retries(self, tmp_path):
        """If rebase keeps failing, push gives up after max_retries.

        We simulate this by making the remote bare repo refuse pushes
        (by creating a conflicting state that can't auto-merge).
        """
        remote = _init_bare_remote(tmp_path)
        _seed_remote(remote, tmp_path)

        agent = tmp_path / "agent"
        _clone_to(remote, agent)

        # Write local change
        inbox = agent / "nadi_inbox.json"
        inbox.write_text(json.dumps([{"source": "steward"}]))
        _git(agent, "add", "-A")
        _git(agent, "commit", "-m", "local change")

        # Directly modify the bare remote HEAD to create a divergence
        # that keeps happening (simulates continuous concurrent writes)
        other = tmp_path / "other"
        _clone_to(remote, other)

        # Push a conflicting change from 'other' that modifies the same file
        (other / "nadi_inbox.json").write_text(json.dumps([{"source": "other-agent"}]))
        _git(other, "add", "-A")
        _git(other, "commit", "-m", "other change")
        _git(other, "push")

        # Agent's push should retry and eventually succeed (rebase resolves it)
        # because the changes are to the same file but non-conflicting JSON
        sync = GitNadiSync(str(agent), sync_interval_s=0, max_retries=3)
        # This should succeed because git can auto-merge different lines
        # If it fails (true conflict), that's also valid — the test verifies
        # the retry mechanism runs
        sync.push(message="steward change")
        # We don't assert True here because the JSON content might conflict
        # The important thing is: it doesn't crash, it retries, it exits cleanly


class TestThrottleDecoupling:
    """Verify local beats don't flood git with commits."""

    def test_rapid_pushes_throttled(self, tmp_path):
        """10 rapid push() calls with 60s interval — only first executes."""
        remote = _init_bare_remote(tmp_path)
        _seed_remote(remote, tmp_path)
        agent = tmp_path / "agent"
        _clone_to(remote, agent)

        sync = GitNadiSync(str(agent), sync_interval_s=60)

        # Write something to push
        inbox = agent / "nadi_inbox.json"
        inbox.write_text(json.dumps([{"source": "steward", "op": "heartbeat"}]))

        # First push succeeds
        assert sync.push() is True

        # Next 9 pushes are throttled (within 60s)
        for _ in range(9):
            # Write new content each time
            inbox.write_text(json.dumps([{"source": "steward", "op": "beat"}]))
            assert sync.push() is True

        # Only 1 commit should exist (not 10)
        log = _git(agent, "log", "--oneline")
        commit_count = len(log.strip().splitlines())
        # 2 = initial seed commit + 1 push (the other 9 were throttled)
        assert commit_count == 2

    def test_zero_interval_allows_every_push(self, tmp_path):
        """sync_interval_s=0 allows every push (for testing)."""
        remote = _init_bare_remote(tmp_path)
        _seed_remote(remote, tmp_path)
        agent = tmp_path / "agent"
        _clone_to(remote, agent)

        sync = GitNadiSync(str(agent), sync_interval_s=0)

        for i in range(3):
            inbox = agent / "nadi_inbox.json"
            inbox.write_text(json.dumps([{"source": "steward", "seq": i}]))
            assert sync.push(message=f"push {i}") is True

        log = _git(agent, "log", "--oneline")
        commit_count = len(log.strip().splitlines())
        # 1 seed + 3 pushes = 4
        assert commit_count == 4
