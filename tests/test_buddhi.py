"""Tests for Buddhi — Discriminative Intelligence."""

from __future__ import annotations

from steward.buddhi import Buddhi, BuddhiVerdict
from steward.types import ToolUse


def _tc(name: str = "bash", **params: object) -> ToolUse:
    """Helper to create a ToolUse."""
    return ToolUse(id=f"call_{id(params)}", name=name, parameters=params)


class TestBuddhiBasics:
    def test_single_success_continues(self):
        """Single successful tool call → continue."""
        buddhi = Buddhi()
        v = buddhi.evaluate([_tc("bash", command="ls")], [(True, "")])
        assert v.action == "continue"

    def test_single_error_continues(self):
        """Single error is not enough to trigger anything."""
        buddhi = Buddhi()
        v = buddhi.evaluate([_tc("bash", command="bad")], [(False, "not found")])
        assert v.action == "continue"

    def test_reset_clears_state(self):
        """Reset clears all history."""
        buddhi = Buddhi()
        for _ in range(3):
            buddhi.evaluate([_tc("bash", command="same")], [(False, "err")])
        buddhi.reset()
        assert buddhi.stats["total_calls"] == 0
        assert buddhi.stats["rounds"] == 0


class TestStuckLoopDetection:
    def test_identical_calls_trigger_reflect(self):
        """Same tool + same params 3x → reflect."""
        buddhi = Buddhi()
        tc = _tc("bash", command="cat /nonexistent")
        for _ in range(3):
            v = buddhi.evaluate([tc], [(False, "file not found")])
        assert v.action == "reflect"
        assert "repeated" in v.reason.lower() or "Identical" in v.reason

    def test_different_params_no_trigger(self):
        """Same tool but different params is NOT stuck."""
        buddhi = Buddhi()
        for i in range(5):
            v = buddhi.evaluate(
                [_tc("bash", command=f"ls dir{i}")],
                [(True, "")],
            )
        assert v.action == "continue"

    def test_mixed_tools_no_trigger(self):
        """Different tools don't trigger stuck detection."""
        buddhi = Buddhi()
        tools = ["bash", "read_file", "glob", "grep", "bash"]
        for name in tools:
            v = buddhi.evaluate([_tc(name, path="/test")], [(True, "")])
        assert v.action == "continue"


class TestConsecutiveErrors:
    def test_five_consecutive_errors_abort(self):
        """5 consecutive errors → abort."""
        buddhi = Buddhi()
        for i in range(5):
            v = buddhi.evaluate(
                [_tc("bash", command=f"cmd{i}")],  # different commands
                [(False, f"error {i}")],
            )
        assert v.action == "abort"
        assert "consecutive" in v.reason.lower()

    def test_errors_with_success_break_no_abort(self):
        """Errors broken by successes don't trigger abort."""
        buddhi = Buddhi()
        # Mix errors and successes with varied tools to avoid streak trigger
        tools = ["bash", "grep", "glob", "read_file", "bash", "grep", "glob", "bash"]
        results = [
            (False, "err"), (False, "err"), (False, "err"),
            (True, ""), (True, ""), (True, ""),
            (False, "err"), (False, "err"),
        ]
        for name, result in zip(tools, results):
            v = buddhi.evaluate([_tc(name, path=f"/{name}")], [result])
        assert v.action == "continue"  # not 5 consecutive, ratio 62.5%


class TestToolStreak:
    def test_same_tool_8_times_triggers_reflect(self):
        """Same tool 8x in a row (not read_file) → reflect."""
        buddhi = Buddhi()
        for i in range(8):
            v = buddhi.evaluate(
                [_tc("bash", command=f"cmd{i}")],
                [(True, "")],
            )
        assert v.action == "reflect"
        assert "bash" in v.reason

    def test_read_file_streak_allowed(self):
        """read_file streak is legitimate (exploring codebase)."""
        buddhi = Buddhi()
        for i in range(10):
            v = buddhi.evaluate(
                [_tc("read_file", path=f"/file{i}.py")],
                [(True, "")],
            )
        assert v.action == "continue"

    def test_streak_broken_by_different_tool(self):
        """A different tool in the middle resets the streak."""
        buddhi = Buddhi()
        for i in range(7):
            buddhi.evaluate([_tc("bash", command=f"cmd{i}")], [(True, "")])
        buddhi.evaluate([_tc("read_file", path="/x")], [(True, "")])
        v = buddhi.evaluate([_tc("bash", command="last")], [(True, "")])
        assert v.action == "continue"


class TestErrorRatio:
    def test_high_error_ratio_triggers_reflect(self):
        """> 70% errors overall → reflect."""
        buddhi = Buddhi()
        # 5 errors, 1 success = 83% error ratio
        for i in range(5):
            buddhi.evaluate([_tc("bash", command=f"fail{i}")], [(False, "err")])
        buddhi.evaluate([_tc("bash", command="ok")], [(True, "")])
        # Need one more to get over threshold with enough history
        v = buddhi.evaluate([_tc("bash", command="fail_again")], [(False, "err")])
        # 6/7 = 85% > 70% → but consecutive error check fires first (5 consecutive before the success)
        # After success, we have 1 more error → not 5 consecutive
        # Error ratio = 6/7 = 85.7% > 70%
        assert v.action == "reflect"

    def test_low_error_ratio_continues(self):
        """< 70% errors → continue."""
        buddhi = Buddhi()
        # 3 errors, 4 successes = 43% error ratio
        for i in range(3):
            buddhi.evaluate([_tc("bash", command=f"fail{i}")], [(False, "err")])
        for i in range(4):
            v = buddhi.evaluate([_tc("bash", command=f"ok{i}")], [(True, "")])
        assert v.action == "continue"


class TestStats:
    def test_stats_tracks_distribution(self):
        """Stats reports tool distribution."""
        buddhi = Buddhi()
        buddhi.evaluate([_tc("bash", command="ls")], [(True, "")])
        buddhi.evaluate([_tc("read_file", path="/x")], [(True, "")])
        buddhi.evaluate([_tc("bash", command="cat")], [(True, "")])

        stats = buddhi.stats
        assert stats["rounds"] == 3
        assert stats["total_calls"] == 3
        assert stats["errors"] == 0
        assert stats["tool_distribution"] == {"bash": 2, "read_file": 1}

    def test_stats_tracks_errors(self):
        """Stats reports error count and ratio."""
        buddhi = Buddhi()
        buddhi.evaluate([_tc("bash")], [(True, "")])
        buddhi.evaluate([_tc("bash")], [(False, "err")])

        stats = buddhi.stats
        assert stats["errors"] == 1
        assert stats["error_ratio"] == 0.5


class TestBuddhiInLoop:
    """Integration test: Buddhi with engine-like tool call patterns."""

    def test_realistic_exploration_session(self):
        """Simulates a real exploration: glob → read → read → edit → bash."""
        buddhi = Buddhi()
        sequence = [
            (_tc("glob", pattern="*.py"), (True, "")),
            (_tc("read_file", path="/main.py"), (True, "")),
            (_tc("read_file", path="/util.py"), (True, "")),
            (_tc("edit_file", path="/main.py", old="x", new="y"), (True, "")),
            (_tc("bash", command="pytest"), (True, "")),
        ]
        for tc, result in sequence:
            v = buddhi.evaluate([tc], [result])
            assert v.action == "continue"

    def test_stuck_agent_gets_reflected(self):
        """Agent stuck editing same file repeatedly → reflection injected."""
        buddhi = Buddhi()
        # Agent keeps trying the same edit
        tc = _tc("edit_file", path="/broken.py", old="bad", new="good")
        for _ in range(3):
            v = buddhi.evaluate([tc], [(False, "old_string not found")])
        assert v.action == "reflect"
        assert "edit_file" in v.reason

    def test_parallel_tool_calls_evaluated(self):
        """Multiple tool calls in one round all get tracked."""
        buddhi = Buddhi()
        calls = [
            _tc("read_file", path="/a.py"),
            _tc("read_file", path="/b.py"),
            _tc("read_file", path="/c.py"),
        ]
        results = [(True, ""), (True, ""), (False, "not found")]
        v = buddhi.evaluate(calls, results)
        assert v.action == "continue"
        assert buddhi.stats["total_calls"] == 3
        assert buddhi.stats["errors"] == 1
