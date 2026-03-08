"""Tests for the Antahkarana decomposition — Manas, Chitta, Gandha."""

from steward.antahkarana.chitta import Chitta, Impression
from steward.antahkarana.gandha import (
    MAX_CONSECUTIVE_ERRORS,
    MAX_IDENTICAL_CALLS,
    MAX_SAME_TOOL_STREAK,
    Detection,
    detect_patterns,
)
from steward.antahkarana.manas import Manas, ManasPerception
from vibe_core.mahamantra.protocols.compression import IntentGuna
from vibe_core.runtime.semantic_actions import SemanticActionType


# ── Manas Tests ──────────────────────────────────────────────────────


class TestManas:
    """Test Manas perception (PrakritiElement #1 — cognition)."""

    def test_perceive_returns_perception(self):
        manas = Manas()
        p = manas.perceive("Fix the bug in main.py")
        assert isinstance(p, ManasPerception)
        assert isinstance(p.action, SemanticActionType)
        assert isinstance(p.guna, IntentGuna)

    def test_perceive_has_function_and_approach(self):
        manas = Manas()
        p = manas.perceive("Implement a new feature")
        assert isinstance(p.function, str)
        assert isinstance(p.approach, str)

    def test_perceive_is_deterministic(self):
        manas = Manas()
        p1 = manas.perceive("Read all Python files")
        p2 = manas.perceive("Read all Python files")
        assert p1.action == p2.action
        assert p1.guna == p2.guna

    def test_perceive_frozen(self):
        manas = Manas()
        p = manas.perceive("test")
        import pytest
        with pytest.raises(AttributeError):
            p.action = SemanticActionType.DEBUG  # type: ignore[misc]


# ── Chitta Tests ─────────────────────────────────────────────────────


class TestChitta:
    """Test Chitta impression storage (PrakritiElement #4 — awareness)."""

    def test_record_and_retrieve(self):
        chitta = Chitta()
        chitta.record("bash", 123, True)
        assert len(chitta.impressions) == 1
        assert chitta.impressions[0].name == "bash"
        assert chitta.impressions[0].success is True

    def test_record_error(self):
        chitta = Chitta()
        chitta.record("edit_file", 456, False, "not found")
        imp = chitta.impressions[0]
        assert not imp.success
        assert imp.error == "not found"

    def test_recent(self):
        chitta = Chitta()
        for i in range(10):
            chitta.record(f"tool_{i}", i, True)
        recent = chitta.recent(3)
        assert len(recent) == 3
        assert recent[0].name == "tool_7"
        assert recent[2].name == "tool_9"

    def test_recent_more_than_available(self):
        chitta = Chitta()
        chitta.record("bash", 1, True)
        recent = chitta.recent(10)
        assert len(recent) == 1

    def test_advance_round(self):
        chitta = Chitta()
        assert chitta.round == 0
        r = chitta.advance_round()
        assert r == 1
        assert chitta.round == 1

    def test_clear(self):
        chitta = Chitta()
        chitta.record("bash", 1, True)
        chitta.advance_round()
        chitta.clear()
        assert len(chitta.impressions) == 0
        assert chitta.round == 0

    def test_stats(self):
        chitta = Chitta()
        chitta.record("bash", 1, True)
        chitta.record("bash", 2, False, "err")
        chitta.record("read_file", 3, True)
        chitta.advance_round()
        stats = chitta.stats
        assert stats["rounds"] == 1
        assert stats["total_calls"] == 3
        assert stats["errors"] == 1
        assert stats["tool_distribution"] == {"bash": 2, "read_file": 1}

    def test_stats_empty(self):
        chitta = Chitta()
        stats = chitta.stats
        assert stats["total_calls"] == 0
        assert stats["error_ratio"] == 0.0


# ── Gandha Tests ─────────────────────────────────────────────────────


class TestGandha:
    """Test Gandha pattern detection (PrakritiElement #9 — detect)."""

    def test_no_patterns_empty(self):
        assert detect_patterns([]) is None

    def test_no_patterns_short_history(self):
        imps = [Impression("bash", 1, True)]
        assert detect_patterns(imps) is None

    def test_consecutive_errors_detected(self):
        imps = [
            Impression("bash", i, False, f"error {i}")
            for i in range(MAX_CONSECUTIVE_ERRORS)
        ]
        d = detect_patterns(imps)
        assert d is not None
        assert d.severity == "abort"
        assert d.pattern == "consecutive_errors"

    def test_consecutive_errors_not_triggered_with_success(self):
        imps = [Impression("bash", i, False, "err") for i in range(4)]
        imps.append(Impression("bash", 5, True))
        assert detect_patterns(imps) is None

    def test_identical_calls_detected(self):
        imps = [
            Impression("bash", 42, True)
            for _ in range(MAX_IDENTICAL_CALLS)
        ]
        d = detect_patterns(imps)
        assert d is not None
        assert d.severity == "reflect"
        assert d.pattern == "identical_calls"

    def test_identical_calls_different_params_no_detection(self):
        imps = [Impression("bash", i, True) for i in range(MAX_IDENTICAL_CALLS)]
        assert detect_patterns(imps) is None

    def test_edit_needs_read_redirect(self):
        imps = [
            Impression("edit_file", 1, False, "old_string not found in file"),
            Impression("edit_file", 2, False, "no match found"),
        ]
        d = detect_patterns(imps)
        assert d is not None
        assert d.severity == "redirect"
        assert d.pattern == "edit_needs_read"

    def test_write_path_redirect(self):
        imps = [
            Impression("write_file", 1, False, "permission denied"),
            Impression("write_file", 2, False, "directory not found"),
        ]
        d = detect_patterns(imps)
        assert d is not None
        assert d.severity == "redirect"
        assert d.pattern == "write_path_issue"

    def test_route_miss_redirect(self):
        imps = [
            Impression("unknown_tool", 1, False, "Tool 'unknown_tool' not found (O(1) route miss)"),
            Impression("another_bad", 2, False, "Tool 'another_bad' not found (O(1) route miss)"),
        ]
        d = detect_patterns(imps)
        assert d is not None
        assert d.severity == "redirect"
        assert d.pattern == "route_miss"

    def test_tool_streak_detected(self):
        imps = [
            Impression("bash", i, True) for i in range(MAX_SAME_TOOL_STREAK)
        ]
        d = detect_patterns(imps)
        # bash with different params_hash won't trigger identical_calls
        # but WILL trigger tool_streak
        assert d is not None
        assert d.severity == "reflect"
        assert d.pattern == "tool_streak"

    def test_read_file_streak_exempt(self):
        imps = [
            Impression("read_file", i, True) for i in range(MAX_SAME_TOOL_STREAK)
        ]
        d = detect_patterns(imps)
        assert d is None  # read_file streaks are legitimate

    def test_error_ratio_detected(self):
        # 6 calls: 5 errors + 1 success = 83% error rate
        imps = [Impression("bash", i, False, "err") for i in range(5)]
        imps.append(Impression("bash", 99, True))
        d = detect_patterns(imps)
        assert d is not None
        assert d.severity == "reflect"
        assert d.pattern == "error_ratio"

    def test_error_ratio_below_threshold(self):
        # 6 calls: 3 errors + 3 success = 50% (below 70% threshold)
        imps = []
        for i in range(6):
            imps.append(Impression("bash", i, i % 2 == 0))
        d = detect_patterns(imps)
        assert d is None

    def test_detection_is_frozen(self):
        d = Detection(severity="abort", pattern="test", reason="test")
        import pytest
        with pytest.raises(AttributeError):
            d.severity = "reflect"  # type: ignore[misc]

    def test_detect_is_pure_function(self):
        """Gandha detection is stateless — same input → same output."""
        imps = [
            Impression("edit_file", 1, False, "not found"),
            Impression("edit_file", 2, False, "not found"),
        ]
        d1 = detect_patterns(imps)
        d2 = detect_patterns(imps)
        assert d1 is not None and d2 is not None
        assert d1.severity == d2.severity
        assert d1.pattern == d2.pattern
