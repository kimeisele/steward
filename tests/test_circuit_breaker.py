"""Tests for CircuitBreaker — prevent cascading failures during auto-fixes."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from steward.tools.circuit_breaker import (
    MAX_CONSECUTIVE_ROLLBACKS,
    CircuitBreaker,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Temp git repo with a test file."""
    cwd = str(tmp_path)
    subprocess.run(["git", "init"], cwd=cwd, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=cwd, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=cwd, capture_output=True)
    (tmp_path / "code.py").write_text("x = 1\n")
    (tmp_path / "test_code.py").write_text(
        "def test_x():\n    from code import x\n    assert x == 1\n"
    )
    subprocess.run(["git", "add", "."], cwd=cwd, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=cwd, capture_output=True)
    return tmp_path


@pytest.fixture
def breaker(git_repo: Path) -> CircuitBreaker:
    return CircuitBreaker(cwd=str(git_repo), test_timeout=30)


class TestGuardedFix:
    def test_fix_that_helps(self, breaker: CircuitBreaker, git_repo: Path):
        """Fix that doesn't increase failures is kept."""
        file_path = str(git_repo / "code.py")

        def fix_fn():
            Path(file_path).write_text("x = 1  # improved\n")

        # Mock test runner to show 0 failures before and after
        with patch.object(breaker, "count_failures", return_value=0):
            result = breaker.guarded_fix(file_path, fix_fn, "echo ok")
        assert result.applied
        assert not result.rolled_back
        assert "improved" in Path(file_path).read_text()

    def test_fix_that_hurts(self, breaker: CircuitBreaker, git_repo: Path):
        """Fix that increases failures is rolled back."""
        file_path = str(git_repo / "code.py")
        original = Path(file_path).read_text()

        def fix_fn():
            Path(file_path).write_text("x = BROKEN\n")

        # Baseline: 0 failures, Post: 1 failure
        call_count = [0]
        def mock_count(cmd):
            call_count[0] += 1
            return 0 if call_count[0] == 1 else 1

        with patch.object(breaker, "count_failures", side_effect=mock_count):
            result = breaker.guarded_fix(file_path, fix_fn, "pytest")
        assert result.rolled_back
        assert not result.applied
        assert result.baseline_failures == 0
        assert result.post_failures == 1
        # File should be rolled back to original
        assert Path(file_path).read_text() == original

    def test_fix_reduces_failures(self, breaker: CircuitBreaker, git_repo: Path):
        """Fix that reduces failures is kept."""
        file_path = str(git_repo / "code.py")

        def fix_fn():
            Path(file_path).write_text("x = 1  # fixed\n")

        # Baseline: 2 failures, Post: 1 failure
        call_count = [0]
        def mock_count(cmd):
            call_count[0] += 1
            return 2 if call_count[0] == 1 else 1

        with patch.object(breaker, "count_failures", side_effect=mock_count):
            result = breaker.guarded_fix(file_path, fix_fn, "pytest")
        assert result.applied
        assert result.baseline_failures == 2
        assert result.post_failures == 1

    def test_fix_fn_exception(self, breaker: CircuitBreaker, git_repo: Path):
        """Exception in fix_fn is caught gracefully."""
        with patch.object(breaker, "count_failures", return_value=0):
            result = breaker.guarded_fix(
                str(git_repo / "code.py"),
                lambda: (_ for _ in ()).throw(RuntimeError("boom")),
                "echo ok",
            )
        assert not result.applied
        assert "boom" in result.error


class TestSuspension:
    def test_suspension_after_consecutive_rollbacks(self, breaker: CircuitBreaker, git_repo: Path):
        """Breaker suspends after MAX_CONSECUTIVE_ROLLBACKS rollbacks."""
        file_path = str(git_repo / "code.py")

        def bad_fix():
            Path(file_path).write_text("broken\n")

        call_count = [0]
        def mock_count(cmd):
            call_count[0] += 1
            return 0 if call_count[0] % 2 == 1 else 5  # always worse

        with patch.object(breaker, "count_failures", side_effect=mock_count):
            for _ in range(MAX_CONSECUTIVE_ROLLBACKS):
                result = breaker.guarded_fix(file_path, bad_fix, "pytest")
                assert result.rolled_back

        assert breaker.is_suspended
        # Next attempt should be blocked
        result = breaker.guarded_fix(file_path, bad_fix, "pytest")
        assert result.suspended
        assert "suspended" in result.error.lower()

    def test_successful_fix_resets_counter(self, breaker: CircuitBreaker, git_repo: Path):
        """A successful fix resets the consecutive rollback counter."""
        file_path = str(git_repo / "code.py")

        # 2 rollbacks (not enough to suspend)
        call_count = [0]
        def mock_count(cmd):
            call_count[0] += 1
            return 0 if call_count[0] % 2 == 1 else 5

        with patch.object(breaker, "count_failures", side_effect=mock_count):
            for _ in range(2):
                breaker.guarded_fix(file_path, lambda: Path(file_path).write_text("bad\n"), "pytest")

        assert breaker._consecutive_rollbacks == 2

        # Now a successful fix
        with patch.object(breaker, "count_failures", return_value=0):
            result = breaker.guarded_fix(file_path, lambda: None, "pytest")
        assert result.applied
        assert breaker._consecutive_rollbacks == 0


class TestCountFailures:
    def test_parses_pytest_output(self, breaker: CircuitBreaker):
        """Correctly parses 'N failed' from pytest output."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1,
                stdout="3 failed, 10 passed",
                stderr="",
            )
            count = breaker.count_failures("pytest")
        assert count == 3

    def test_all_pass(self, breaker: CircuitBreaker):
        """Returns 0 when all tests pass."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout="10 passed",
                stderr="",
            )
            count = breaker.count_failures("pytest")
        assert count == 0

    def test_timeout_returns_none(self, breaker: CircuitBreaker):
        """Timeout returns None (can't verify)."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)):
            count = breaker.count_failures("pytest")
        assert count is None


class TestChangedFiles:
    def test_clean_repo_returns_empty(self, breaker: CircuitBreaker, git_repo: Path):
        assert breaker.changed_files() == set()

    def test_modified_file_detected(self, breaker: CircuitBreaker, git_repo: Path):
        (git_repo / "code.py").write_text("x = 99\n")
        assert "code.py" in breaker.changed_files()

    def test_staged_file_detected(self, breaker: CircuitBreaker, git_repo: Path):
        (git_repo / "code.py").write_text("x = 99\n")
        subprocess.run(["git", "add", "code.py"], cwd=str(git_repo), capture_output=True)
        assert "code.py" in breaker.changed_files()

    def test_non_git_repo_returns_empty(self, tmp_path: Path):
        b = CircuitBreaker(cwd=str(tmp_path))
        # tmp_path is not a git repo — should return empty, not crash
        assert b.changed_files() == set()


class TestRollbackFiles:
    def test_rollback_single_file(self, breaker: CircuitBreaker, git_repo: Path):
        (git_repo / "code.py").write_text("broken\n")
        assert breaker.rollback_file("code.py")
        assert (git_repo / "code.py").read_text() == "x = 1\n"

    def test_rollback_multiple_files(self, breaker: CircuitBreaker, git_repo: Path):
        # Add and commit a second file
        (git_repo / "util.py").write_text("y = 2\n")
        subprocess.run(["git", "add", "."], cwd=str(git_repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "add util"], cwd=str(git_repo), capture_output=True)
        # Modify both
        (git_repo / "code.py").write_text("broken1\n")
        (git_repo / "util.py").write_text("broken2\n")
        rolled = breaker.rollback_files({"code.py", "util.py"})
        assert len(rolled) == 2
        assert (git_repo / "code.py").read_text() == "x = 1\n"
        assert (git_repo / "util.py").read_text() == "y = 2\n"


class TestRecordSuccessRollback:
    def test_record_success_resets_counter(self, breaker: CircuitBreaker):
        breaker.record_rollback()
        breaker.record_rollback()
        assert breaker._consecutive_rollbacks == 2
        breaker.record_success()
        assert breaker._consecutive_rollbacks == 0

    def test_suspension_after_max_rollbacks(self, breaker: CircuitBreaker):
        for _ in range(MAX_CONSECUTIVE_ROLLBACKS):
            breaker.record_rollback()
        assert breaker.is_suspended

    def test_success_after_suspension_not_possible(self, breaker: CircuitBreaker):
        """Once suspended, is_suspended stays True until time expires."""
        for _ in range(MAX_CONSECUTIVE_ROLLBACKS):
            breaker.record_rollback()
        assert breaker.is_suspended
        # record_success doesn't automatically unsuspend
        breaker.record_success()
        # Still suspended — the time hasn't expired
        assert breaker.is_suspended


class TestStats:
    def test_stats_dict(self, breaker: CircuitBreaker):
        stats = breaker.stats()
        assert "total_fixes" in stats
        assert "total_rollbacks" in stats
        assert "consecutive_rollbacks" in stats
        assert "is_suspended" in stats
        assert not stats["is_suspended"]

    def test_stats_after_operations(self, breaker: CircuitBreaker):
        breaker.record_success()
        breaker.record_rollback()
        s = breaker.stats()
        assert s["total_fixes"] == 1
        assert s["total_rollbacks"] == 1
        assert s["consecutive_rollbacks"] == 1


class TestGuardedLLMFix:
    """_guarded_llm_fix() — autonomous verification gate in StewardAgent."""

    def _make_agent(self, fake_llm):
        from steward.agent import StewardAgent
        from tests.conftest import track_agent
        return track_agent(StewardAgent(provider=fake_llm))

    def test_breaker_exists_on_agent(self, fake_llm):
        agent = self._make_agent(fake_llm)
        assert hasattr(agent, "_breaker")
        assert isinstance(agent._breaker, CircuitBreaker)

    def test_suspended_breaker_skips_fix(self, fake_llm):
        """When breaker is suspended, LLM is not called."""
        import asyncio
        agent = self._make_agent(fake_llm)
        for _ in range(MAX_CONSECUTIVE_ROLLBACKS):
            agent._breaker.record_rollback()
        result = asyncio.run(agent._autonomy.guarded_llm_fix("fix something"))
        assert result is None
        assert fake_llm.call_count == 0

    def test_no_baseline_runs_unguarded(self, fake_llm):
        """When tests can't establish baseline, run LLM unguarded."""
        import asyncio
        agent = self._make_agent(fake_llm)
        with patch.object(agent._breaker, "count_failures", return_value=None):
            asyncio.run(agent._autonomy.guarded_llm_fix("fix something"))
        # LLM was called (unguarded fallback)
        assert fake_llm.call_count >= 1

    def test_no_files_changed_records_success(self, fake_llm):
        """When LLM doesn't change files, record success."""
        import asyncio
        agent = self._make_agent(fake_llm)
        with patch.object(agent._breaker, "count_failures", return_value=0):
            with patch.object(agent._breaker, "changed_files", return_value=set()):
                asyncio.run(agent._autonomy.guarded_llm_fix("check something"))
        assert agent._breaker._consecutive_rollbacks == 0

    def test_worse_failures_trigger_rollback(self, fake_llm):
        """When failures increase after LLM fix, all changes are rolled back."""
        import asyncio

        from steward.tools.circuit_breaker import GateResult
        agent = self._make_agent(fake_llm)
        call_count = [0]
        def mock_count(cmd="pytest -x -q"):
            call_count[0] += 1
            return 0 if call_count[0] == 1 else 3  # baseline=0, post=3

        # Gates must pass for tests to even run
        all_pass = [GateResult(passed=True, gate="lint"), GateResult(passed=True, gate="security"), GateResult(passed=True, gate="blast_radius")]

        with patch.object(agent._breaker, "count_failures", side_effect=mock_count):
            with patch.object(agent._breaker, "changed_files", side_effect=[
                set(),  # before: clean
                {"src/foo.py", "src/bar.py"},  # after: 2 files changed
            ]):
                with patch.object(agent._breaker, "run_gates", return_value=all_pass):
                    with patch.object(agent._breaker, "rollback_files", return_value=["src/foo.py", "src/bar.py"]) as mock_rb:
                        result = asyncio.run(agent._autonomy.guarded_llm_fix("fix the bug"))
        assert result is None  # Fix rejected
        mock_rb.assert_called_once_with({"src/foo.py", "src/bar.py"})
        assert agent._breaker._consecutive_rollbacks == 1

    def test_failed_gate_triggers_rollback_before_tests(self, fake_llm):
        """When a gate fails, rollback happens WITHOUT running the test suite."""
        import asyncio

        from steward.tools.circuit_breaker import GateResult
        agent = self._make_agent(fake_llm)

        # Gates: lint fails
        gate_results = [
            GateResult(passed=False, gate="lint", detail="ruff: 3 new violations"),
            GateResult(passed=True, gate="security"),
            GateResult(passed=True, gate="blast_radius"),
        ]
        count_calls = [0]
        def mock_count(cmd="pytest -x -q"):
            count_calls[0] += 1
            return 0  # baseline always 0

        with patch.object(agent._breaker, "count_failures", side_effect=mock_count):
            with patch.object(agent._breaker, "changed_files", side_effect=[
                set(),
                {"src/foo.py"},
            ]):
                with patch.object(agent._breaker, "run_gates", return_value=gate_results):
                    with patch.object(agent._breaker, "rollback_files", return_value=["src/foo.py"]):
                        result = asyncio.run(agent._autonomy.guarded_llm_fix("fix the bug"))
        assert result is None
        # Only 1 count_failures call (baseline) — NO post-fix test run
        assert count_calls[0] == 1
        assert agent._breaker._consecutive_rollbacks == 1


class TestCheckLint:
    """check_lint() — ruff static analysis gate."""

    def _init_repo(self, path):
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)

    def test_clean_code_passes(self, tmp_path):
        self._init_repo(tmp_path)
        f = tmp_path / "clean.py"
        f.write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_lint({"clean.py"})
        assert result.passed
        assert result.gate == "lint"

    def test_syntax_error_fails(self, tmp_path):
        self._init_repo(tmp_path)
        f = tmp_path / "bad.py"
        f.write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Now introduce a ruff error
        f.write_text("x = 1\nif True\n")  # syntax error (missing colon)
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_lint({"bad.py"})
        assert not result.passed
        assert "ruff" in result.detail

    def test_non_py_files_skipped(self, tmp_path):
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_lint({"README.md", "config.json"})
        assert result.passed

    def test_ruff_not_installed_passes(self, tmp_path):
        breaker = CircuitBreaker(cwd=str(tmp_path))
        with patch("subprocess.run", side_effect=FileNotFoundError("ruff")):
            result = breaker.check_lint({"code.py"})
        assert result.passed
        assert "not available" in result.detail

    def test_differential_ignores_preexisting_violations(self, tmp_path):
        """Pre-existing violations in HEAD don't fail the gate."""
        self._init_repo(tmp_path)
        # Commit a file WITH a ruff violation (undefined name)
        f = tmp_path / "legacy.py"
        f.write_text("x = undefined_name\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # "Modify" the file but keep the same violation count
        f.write_text("x = undefined_name  # comment\n")
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_lint({"legacy.py"})
        # Should pass — no NEW violations (same count as baseline)
        assert result.passed


class TestCheckSecurity:
    """check_security() — bandit SAST gate."""

    def _init_repo(self, path):
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)

    def test_safe_code_passes(self, tmp_path):
        self._init_repo(tmp_path)
        f = tmp_path / "safe.py"
        f.write_text("x = 1 + 2\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_security({"safe.py"})
        assert result.passed

    def test_dangerous_code_fails(self, tmp_path):
        self._init_repo(tmp_path)
        f = tmp_path / "danger.py"
        f.write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Introduce a HIGH severity security issue (B602: shell=True with user input)
        f.write_text("import subprocess\nsubprocess.call(input(), shell=True)\n")
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_security({"danger.py"})
        assert not result.passed
        assert "bandit" in result.detail

    def test_non_py_files_skipped(self, tmp_path):
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_security({"data.json"})
        assert result.passed

    def test_bandit_not_installed_passes(self, tmp_path):
        breaker = CircuitBreaker(cwd=str(tmp_path))
        with patch("subprocess.run", side_effect=FileNotFoundError("bandit")):
            result = breaker.check_security({"code.py"})
        assert result.passed
        assert "not available" in result.detail


class TestCheckBlastRadius:
    """check_blast_radius() — scope limiter."""

    def _init_repo(self, path):
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)

    def test_small_change_passes(self, tmp_path):
        self._init_repo(tmp_path)
        f = tmp_path / "small.py"
        f.write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        f.write_text("x = 2\n")
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_blast_radius({"small.py"})
        assert result.passed

    def test_too_many_files_fails(self, tmp_path):
        breaker = CircuitBreaker(cwd=str(tmp_path), max_changed_files=3)
        files = {f"file{i}.py" for i in range(5)}
        result = breaker.check_blast_radius(files)
        assert not result.passed
        assert "Too many files" in result.detail

    def test_too_many_lines_fails(self, tmp_path):
        self._init_repo(tmp_path)
        f = tmp_path / "big.py"
        f.write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Write a massive change
        f.write_text("\n".join(f"line_{i} = {i}" for i in range(600)) + "\n")
        breaker = CircuitBreaker(cwd=str(tmp_path), max_changed_lines=100)
        result = breaker.check_blast_radius({"big.py"})
        assert not result.passed
        assert "Too many lines" in result.detail

    def test_non_py_files_counted_for_file_limit(self, tmp_path):
        """File count includes ALL file types, not just .py."""
        breaker = CircuitBreaker(cwd=str(tmp_path), max_changed_files=2)
        result = breaker.check_blast_radius({"a.py", "b.md", "c.json"})
        assert not result.passed

    def test_non_py_lines_not_counted(self, tmp_path):
        """Line count only checks .py files (blast radius for code)."""
        breaker = CircuitBreaker(cwd=str(tmp_path))
        # Only non-py files — line check is skipped
        result = breaker.check_blast_radius({"data.json"})
        assert result.passed


class TestCheckTestIntegrity:
    """check_test_integrity() — prevent Goodhart test gaming."""

    def _init_repo(self, path):
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)

    def test_unchanged_tests_pass(self, tmp_path):
        """Tests with same structure before/after → pass."""
        self._init_repo(tmp_path)
        test_code = (
            "def test_add():\n    assert 1 + 1 == 2\n\n"
            "def test_sub():\n    assert 3 - 1 == 2\n"
        )
        (tmp_path / "test_math.py").write_text(test_code)
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Minor change that doesn't affect structure
        (tmp_path / "test_math.py").write_text(
            "def test_add():\n    assert 1 + 1 == 2  # verified\n\n"
            "def test_sub():\n    assert 3 - 1 == 2\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_test_integrity({"test_math.py"})
        assert result.passed

    def test_deleted_test_function_fails(self, tmp_path):
        """Removing a test function → FAIL."""
        self._init_repo(tmp_path)
        (tmp_path / "test_api.py").write_text(
            "def test_create():\n    assert True\n\n"
            "def test_delete():\n    assert True\n"
        )
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Remove one test function
        (tmp_path / "test_api.py").write_text(
            "def test_create():\n    assert True\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_test_integrity({"test_api.py"})
        assert not result.passed
        assert "test function" in result.detail.lower()

    def test_trivial_assert_true_fails(self, tmp_path):
        """Adding `assert True` where real assertions existed → FAIL."""
        self._init_repo(tmp_path)
        (tmp_path / "test_calc.py").write_text(
            "def test_divide():\n    assert 10 / 2 == 5\n    assert 6 / 3 == 2\n"
        )
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Replace real assertions with trivial ones
        (tmp_path / "test_calc.py").write_text(
            "def test_divide():\n    assert True\n    assert True\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_test_integrity({"test_calc.py"})
        assert not result.passed
        assert "trivial" in result.detail.lower()

    def test_adding_tests_passes(self, tmp_path):
        """Adding new test functions → pass (improvement)."""
        self._init_repo(tmp_path)
        (tmp_path / "test_new.py").write_text(
            "def test_one():\n    assert 1 == 1\n"
        )
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Add more tests
        (tmp_path / "test_new.py").write_text(
            "def test_one():\n    assert 1 == 1\n\n"
            "def test_two():\n    assert 2 == 2\n\n"
            "def test_three():\n    assert 3 == 3\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_test_integrity({"test_new.py"})
        assert result.passed

    def test_non_test_files_skipped(self, tmp_path):
        """Non-test files don't trigger integrity checks."""
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_test_integrity({"src/api.py", "utils.py"})
        assert result.passed

    def test_new_test_file_passes(self, tmp_path):
        """New test files (not in HEAD) → pass (no baseline)."""
        self._init_repo(tmp_path)
        (tmp_path / "dummy.txt").write_text("init\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # New test file not in HEAD
        (tmp_path / "test_brand_new.py").write_text(
            "def test_hello():\n    assert True\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_test_integrity({"test_brand_new.py"})
        assert result.passed

    def test_deleted_test_file_fails(self, tmp_path):
        """Deleting a test file entirely → FAIL."""
        self._init_repo(tmp_path)
        (tmp_path / "test_core.py").write_text(
            "def test_core():\n    assert 1 == 1\n"
        )
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Delete the test file
        (tmp_path / "test_core.py").unlink()
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_test_integrity({"test_core.py"})
        assert not result.passed
        assert "deleted" in result.detail.lower()

    def test_significant_assertion_drop_fails(self, tmp_path):
        """Losing >30% of assertions → FAIL."""
        self._init_repo(tmp_path)
        (tmp_path / "test_full.py").write_text(
            "def test_a():\n    assert 1\n    assert 2\n    assert 3\n"
            "    assert 4\n    assert 5\n    assert 6\n    assert 7\n"
            "    assert 8\n    assert 9\n    assert 10\n"
        )
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Drop to 2 assertions (80% loss)
        (tmp_path / "test_full.py").write_text(
            "def test_a():\n    assert 1\n    assert 2\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_test_integrity({"test_full.py"})
        assert not result.passed
        assert "assertions removed" in result.detail.lower()


class TestCheckCohesion:
    """check_cohesion() — 2D gate: LCOM4 × WMC prevents god-class regression."""

    def test_cohesive_class_passes(self, tmp_path):
        """Class with LCOM4=1 passes regardless of WMC."""
        (tmp_path / "clean.py").write_text(
            "class Foo:\n"
            "    def __init__(self): self.x = 1\n"
            "    def a(self): return self.x\n"
            "    def b(self): return self.x + 1\n"
            "    def c(self): return self.x * 2\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_cohesion({"clean.py"})
        assert result.passed

    def test_god_class_high_lcom4_high_wmc_fails(self, tmp_path):
        """LCOM4 > 4 AND WMC > 20 → real god-class → FAIL."""
        # 5 disconnected groups, each with branching logic → high WMC
        lines = ["class GodClass:"]
        for group, attr in [("a", "x"), ("b", "y"), ("c", "z"), ("d", "w"), ("e", "v")]:
            for i in range(1, 4):
                lines.append(
                    f"    def {group}{i}(self):\n"
                    f"        if self.{attr} > 0:\n"
                    f"            for item in self.{attr}_list:\n"
                    f"                if item and self.{attr} > 1:\n"
                    f"                    return item\n"
                    f"        return self.{attr}"
                )
        (tmp_path / "god.py").write_text("\n".join(lines))
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_cohesion({"god.py"})
        assert not result.passed
        assert "GodClass" in result.detail
        assert "LCOM4=" in result.detail
        assert "WMC=" in result.detail

    def test_router_high_lcom4_low_wmc_passes(self, tmp_path):
        """LCOM4 > 4 AND WMC ≤ 20 → router pattern → PASS (false positive avoided)."""
        # 5 disconnected groups but simple methods (CC=1 each) → low WMC
        (tmp_path / "router.py").write_text(
            "class Router:\n"
            "    def handle_a1(self): return self.x\n"
            "    def handle_a2(self): return self.x\n"
            "    def handle_a3(self): return self.x\n"
            "    def handle_b1(self): return self.y\n"
            "    def handle_b2(self): return self.y\n"
            "    def handle_b3(self): return self.y\n"
            "    def handle_c1(self): return self.z\n"
            "    def handle_c2(self): return self.z\n"
            "    def handle_c3(self): return self.z\n"
            "    def handle_d1(self): return self.w\n"
            "    def handle_d2(self): return self.w\n"
            "    def handle_d3(self): return self.w\n"
            "    def handle_e1(self): return self.v\n"
            "    def handle_e2(self): return self.v\n"
            "    def handle_e3(self): return self.v\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_cohesion({"router.py"})
        assert result.passed  # WMC=15 (all CC=1) → below threshold

    def test_test_files_skipped(self, tmp_path):
        """Test files are not checked for cohesion."""
        (tmp_path / "test_god.py").write_text(
            "class TestGod:\n"
            "    def a(self): return self.x\n"
            "    def b(self): return self.y\n"
            "    def c(self): return self.z\n"
            "    def d(self): return self.w\n"
            "    def e(self): return self.v\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_cohesion({"test_god.py"})
        assert result.passed

    def test_non_python_files_skipped(self, tmp_path):
        """Non-Python files are skipped."""
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_cohesion({"README.md"})
        assert result.passed

    def test_deleted_file_does_not_crash(self, tmp_path):
        """Deleted files don't crash the gate."""
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_cohesion({"nonexistent.py"})
        assert result.passed

    def test_syntax_error_file_does_not_crash(self, tmp_path):
        """Files with syntax errors are skipped gracefully."""
        (tmp_path / "broken.py").write_text("class Broken(\n  def")
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_cohesion({"broken.py"})
        assert result.passed

    def test_small_class_passes(self, tmp_path):
        """Classes with < 3 methods always pass (trivially cohesive)."""
        (tmp_path / "tiny.py").write_text(
            "class Tiny:\n"
            "    def a(self): return self.x\n"
            "    def b(self): return self.y\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_cohesion({"tiny.py"})
        assert result.passed


class TestCheckApiSurface:
    """check_api_surface() — prevent deletion of public interfaces."""

    def _init_repo(self, path):
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True)

    def test_unchanged_api_passes(self, tmp_path):
        """No change to public surface → pass."""
        self._init_repo(tmp_path)
        (tmp_path / "api.py").write_text(
            "__all__ = ['create_user', 'delete_user']\n\n"
            "def create_user():\n    pass\n\n"
            "def delete_user():\n    pass\n"
        )
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Add internal change only
        (tmp_path / "api.py").write_text(
            "__all__ = ['create_user', 'delete_user']\n\n"
            "def create_user():\n    return True  # improved\n\n"
            "def delete_user():\n    pass\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_api_surface({"api.py"})
        assert result.passed

    def test_removed_all_export_fails(self, tmp_path):
        """Removing an entry from __all__ → FAIL."""
        self._init_repo(tmp_path)
        (tmp_path / "api.py").write_text(
            "__all__ = ['create_user', 'delete_user']\n\n"
            "def create_user():\n    pass\n\n"
            "def delete_user():\n    pass\n"
        )
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Remove delete_user from __all__
        (tmp_path / "api.py").write_text(
            "__all__ = ['create_user']\n\n"
            "def create_user():\n    pass\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_api_surface({"api.py"})
        assert not result.passed
        assert "delete_user" in result.detail

    def test_removed_decorated_endpoint_fails(self, tmp_path):
        """Removing a @route decorated function → FAIL."""
        self._init_repo(tmp_path)
        (tmp_path / "views.py").write_text(
            "from flask import Flask\n"
            "app = Flask(__name__)\n\n"
            "@app.route('/users')\n"
            "def list_users():\n    return []\n\n"
            "@app.route('/health')\n"
            "def health():\n    return 'ok'\n"
        )
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Remove the health endpoint
        (tmp_path / "views.py").write_text(
            "from flask import Flask\n"
            "app = Flask(__name__)\n\n"
            "@app.route('/users')\n"
            "def list_users():\n    return []\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_api_surface({"views.py"})
        assert not result.passed
        assert "health" in result.detail

    def test_removed_multiple_public_functions_fails(self, tmp_path):
        """Removing 2+ public functions → FAIL."""
        self._init_repo(tmp_path)
        (tmp_path / "utils.py").write_text(
            "def parse_json():\n    pass\n\n"
            "def format_date():\n    pass\n\n"
            "def validate_email():\n    pass\n"
        )
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Remove 2 public functions
        (tmp_path / "utils.py").write_text(
            "def parse_json():\n    pass\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_api_surface({"utils.py"})
        assert not result.passed
        assert "public names removed" in result.detail

    def test_removing_single_public_function_passes(self, tmp_path):
        """Removing 1 public function → pass (normal refactoring)."""
        self._init_repo(tmp_path)
        (tmp_path / "utils.py").write_text(
            "def parse_json():\n    pass\n\n"
            "def old_helper():\n    pass\n"
        )
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Remove 1 function — allowed (refactoring)
        (tmp_path / "utils.py").write_text(
            "def parse_json():\n    pass\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_api_surface({"utils.py"})
        assert result.passed

    def test_adding_public_functions_passes(self, tmp_path):
        """Adding new public API → pass (improvement)."""
        self._init_repo(tmp_path)
        (tmp_path / "api.py").write_text(
            "def get_users():\n    pass\n"
        )
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "api.py").write_text(
            "def get_users():\n    pass\n\n"
            "def create_user():\n    pass\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_api_surface({"api.py"})
        assert result.passed

    def test_test_files_skipped(self, tmp_path):
        """Test files don't trigger API surface checks."""
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_api_surface({"test_api.py", "tests/test_utils.py"})
        assert result.passed

    def test_deleted_source_file_with_public_api_fails(self, tmp_path):
        """Deleting a source file that had public API → FAIL."""
        self._init_repo(tmp_path)
        (tmp_path / "module.py").write_text(
            "__all__ = ['important_func']\n\n"
            "def important_func():\n    return 42\n"
        )
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "module.py").unlink()
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_api_surface({"module.py"})
        assert not result.passed
        assert "deleted" in result.detail.lower()

    def test_new_file_passes(self, tmp_path):
        """New files (not in HEAD) → pass (no baseline)."""
        self._init_repo(tmp_path)
        (tmp_path / "dummy.txt").write_text("init\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "new_module.py").write_text(
            "def new_function():\n    pass\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_api_surface({"new_module.py"})
        assert result.passed

    def test_private_function_removal_passes(self, tmp_path):
        """Removing private functions (_prefixed) → pass."""
        self._init_repo(tmp_path)
        (tmp_path / "internal.py").write_text(
            "def _helper():\n    pass\n\n"
            "def _internal():\n    pass\n\n"
            "def public_api():\n    pass\n"
        )
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Remove private functions — that's fine
        (tmp_path / "internal.py").write_text(
            "def public_api():\n    pass\n"
        )
        breaker = CircuitBreaker(cwd=str(tmp_path))
        result = breaker.check_api_surface({"internal.py"})
        assert result.passed


class TestRunGates:
    """run_gates() — orchestrator."""

    def test_all_pass(self, tmp_path):
        breaker = CircuitBreaker(cwd=str(tmp_path))
        results = breaker.run_gates({"README.md"})
        assert len(results) == 6
        assert all(r.passed for r in results)

    def test_returns_all_results_even_on_failure(self, tmp_path):
        """All gates run even if earlier ones fail (collect all violations)."""
        breaker = CircuitBreaker(cwd=str(tmp_path), max_changed_files=0)
        results = breaker.run_gates({"a.py"})
        # blast_radius should fail (max=0), others may pass/fail
        blast = [r for r in results if r.gate == "blast_radius"]
        assert len(blast) == 1
        assert not blast[0].passed

    def test_all_six_gates_present(self, tmp_path):
        """All 6 gate types are represented in results."""
        breaker = CircuitBreaker(cwd=str(tmp_path))
        results = breaker.run_gates({"code.py"})
        gate_names = {r.gate for r in results}
        assert "lint" in gate_names
        assert "security" in gate_names
        assert "blast_radius" in gate_names
        assert "cohesion" in gate_names
        assert "test_integrity" in gate_names
        assert "api_surface" in gate_names
