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

    def test_write_without_read_detected(self):
        """Writing a file without reading it first is a redirect."""
        imps = [
            Impression("glob", 1, True),
            Impression("edit_file", 2, True, path="/src/main.py"),
        ]
        d = detect_patterns(imps)
        assert d is not None
        assert d.severity == "redirect"
        assert d.pattern == "write_without_read"
        assert "main.py" in d.suggestion

    def test_write_after_read_ok(self):
        """Writing a file after reading it is fine."""
        imps = [
            Impression("read_file", 1, True, path="/src/main.py"),
            Impression("edit_file", 2, True, path="/src/main.py"),
        ]
        assert detect_patterns(imps) is None

    def test_write_without_read_only_on_last(self):
        """Only the most recent impression triggers write-without-read."""
        imps = [
            Impression("edit_file", 1, True, path="/src/a.py"),  # blind write
            Impression("read_file", 2, True, path="/src/b.py"),  # different file
        ]
        # Last impression is a read, not a write — no detection
        assert detect_patterns(imps) is None

    def test_write_without_read_new_file_ok(self):
        """write_file to a new file (no path) is not flagged."""
        imps = [
            Impression("write_file", 1, True),  # no path
        ]
        assert detect_patterns(imps) is None

    def test_write_without_read_failed_write_ok(self):
        """Failed writes are not flagged (they didn't actually write)."""
        imps = [
            Impression("edit_file", 1, False, "permission denied", path="/src/main.py"),
        ]
        assert detect_patterns(imps) is None

    def test_duplicate_read_detected(self):
        """Reading the same file twice is a redirect."""
        imps = [
            Impression("read_file", 1, True, path="/src/main.py"),
            Impression("glob", 2, True),
            Impression("read_file", 3, True, path="/src/main.py"),
        ]
        d = detect_patterns(imps)
        assert d is not None
        assert d.severity == "redirect"
        assert d.pattern == "duplicate_read"
        assert "main.py" in d.suggestion

    def test_duplicate_read_different_files_ok(self):
        """Reading different files is fine."""
        imps = [
            Impression("read_file", 1, True, path="/src/a.py"),
            Impression("read_file", 2, True, path="/src/b.py"),
        ]
        assert detect_patterns(imps) is None

    def test_duplicate_read_failed_first_ok(self):
        """Re-reading after a failed read is fine."""
        imps = [
            Impression("read_file", 1, False, "not found", path="/src/main.py"),
            Impression("read_file", 2, True, path="/src/main.py"),
        ]
        assert detect_patterns(imps) is None

    def test_duplicate_read_no_path_ignored(self):
        """Reads without paths are not duplicate-checked."""
        imps = [
            Impression("read_file", 1, True),
            Impression("read_file", 2, True),
        ]
        assert detect_patterns(imps) is None

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


# ── Phase Machine Tests (Chitta self-awareness) ─────────────────────


from steward.antahkarana.chitta import (
    PHASE_COMPLETE,
    PHASE_EXECUTE,
    PHASE_ORIENT,
    PHASE_VERIFY,
)


class TestChittaPhase:
    """Test Chitta phase derivation from impressions."""

    def test_empty_is_orient(self):
        chitta = Chitta()
        assert chitta.phase == PHASE_ORIENT

    def test_single_read_is_orient(self):
        chitta = Chitta()
        chitta.record("read_file", 1, True)
        assert chitta.phase == PHASE_ORIENT

    def test_two_reads_becomes_execute(self):
        chitta = Chitta()
        chitta.record("read_file", 1, True)
        chitta.record("glob", 2, True)
        assert chitta.phase == PHASE_EXECUTE

    def test_three_reads_stays_execute(self):
        chitta = Chitta()
        chitta.record("read_file", 1, True)
        chitta.record("grep", 2, True)
        chitta.record("read_file", 3, True)
        assert chitta.phase == PHASE_EXECUTE

    def test_write_is_execute(self):
        chitta = Chitta()
        chitta.record("edit_file", 1, True)
        assert chitta.phase == PHASE_EXECUTE

    def test_write_then_read_is_verify(self):
        """After writes, if no recent writes → VERIFY."""
        chitta = Chitta()
        chitta.record("read_file", 1, True)
        chitta.record("edit_file", 2, True)
        chitta.record("read_file", 3, True)
        chitta.record("read_file", 4, True)
        chitta.record("read_file", 5, True)
        # recent 3: [read, read, read] — no recent writes, but total writes > 0
        assert chitta.phase == PHASE_VERIFY

    def test_write_then_bash_ok_is_complete(self):
        """After writes + successful bash → COMPLETE."""
        chitta = Chitta()
        chitta.record("read_file", 1, True)
        chitta.record("edit_file", 2, True)
        chitta.record("bash", 3, True)  # test pass
        assert chitta.phase == PHASE_COMPLETE

    def test_errors_regress_to_orient(self):
        """2+ recent errors → back to ORIENT."""
        chitta = Chitta()
        chitta.record("read_file", 1, True)
        chitta.record("read_file", 2, True)
        # Now in EXECUTE phase
        assert chitta.phase == PHASE_EXECUTE
        chitta.record("edit_file", 3, False, "err")
        chitta.record("edit_file", 4, False, "err")
        # 2 recent errors → ORIENT
        assert chitta.phase == PHASE_ORIENT

    def test_bash_without_writes_stays_orient(self):
        """Bash without prior writes doesn't trigger COMPLETE."""
        chitta = Chitta()
        chitta.record("bash", 1, True)
        # No writes, so phase based on reads (0) → ORIENT
        assert chitta.phase == PHASE_ORIENT

    def test_phase_in_stats(self):
        chitta = Chitta()
        chitta.record("read_file", 1, True)
        assert chitta.stats["phase"] == PHASE_ORIENT

    def test_clear_resets_phase(self):
        chitta = Chitta()
        chitta.record("read_file", 1, True)
        chitta.record("glob", 2, True)
        assert chitta.phase == PHASE_EXECUTE
        chitta.clear()
        assert chitta.phase == PHASE_ORIENT

    def test_files_read_tracked(self):
        chitta = Chitta()
        chitta.record("read_file", 1, True, path="/src/main.py")
        chitta.record("read_file", 2, True, path="/src/lib.py")
        chitta.record("read_file", 3, False, "err", path="/bad.py")  # failed, excluded
        assert chitta.files_read == ["/src/main.py", "/src/lib.py"]

    def test_files_written_tracked(self):
        chitta = Chitta()
        chitta.record("edit_file", 1, True, path="/src/main.py")
        chitta.record("write_file", 2, True, path="/src/new.py")
        chitta.record("edit_file", 3, True, path="/src/main.py")  # duplicate, deduped
        assert chitta.files_written == ["/src/main.py", "/src/new.py"]

    def test_files_no_path_excluded(self):
        chitta = Chitta()
        chitta.record("read_file", 1, True)  # no path
        chitta.record("bash", 2, True)  # not a read tool
        assert chitta.files_read == []
        assert chitta.files_written == []


class TestChittaCrossTurn:
    """Test cross-turn Chitta persistence (prior_reads, end_turn, serialization)."""

    def test_end_turn_merges_reads(self):
        """end_turn() moves current reads into prior_reads."""
        chitta = Chitta()
        chitta.record("read_file", 1, True, path="/src/main.py")
        chitta.record("read_file", 2, True, path="/src/lib.py")
        chitta.record("edit_file", 3, True, path="/src/main.py")

        chitta.end_turn()

        assert chitta.prior_reads == frozenset({"/src/main.py", "/src/lib.py"})
        assert len(chitta.impressions) == 0  # impressions cleared
        assert chitta.round == 0  # round reset

    def test_prior_reads_accumulate_across_turns(self):
        """Prior reads accumulate across multiple turns."""
        chitta = Chitta()
        chitta.record("read_file", 1, True, path="/a.py")
        chitta.end_turn()

        chitta.record("read_file", 2, True, path="/b.py")
        chitta.end_turn()

        assert chitta.prior_reads == frozenset({"/a.py", "/b.py"})

    def test_was_file_read_current_turn(self):
        """was_file_read checks current turn impressions."""
        chitta = Chitta()
        chitta.record("read_file", 1, True, path="/src/main.py")
        assert chitta.was_file_read("/src/main.py") is True
        assert chitta.was_file_read("/src/other.py") is False

    def test_was_file_read_prior_turn(self):
        """was_file_read checks prior turns too."""
        chitta = Chitta()
        chitta.record("read_file", 1, True, path="/src/main.py")
        chitta.end_turn()

        # New turn — no current impressions, but prior_reads has it
        assert chitta.was_file_read("/src/main.py") is True

    def test_clear_resets_prior_reads(self):
        """Full clear resets prior_reads too."""
        chitta = Chitta()
        chitta.record("read_file", 1, True, path="/src/main.py")
        chitta.end_turn()
        assert len(chitta.prior_reads) == 1

        chitta.clear()
        assert len(chitta.prior_reads) == 0

    def test_to_summary_serialization(self):
        """to_summary() produces a serializable dict."""
        chitta = Chitta()
        chitta.record("read_file", 1, True, path="/a.py")
        chitta.record("edit_file", 2, True, path="/a.py")

        summary = chitta.to_summary()
        assert "/a.py" in summary["prior_reads"]
        assert "/a.py" in summary["files_written"]
        assert summary["last_phase"] in ("ORIENT", "EXECUTE", "VERIFY", "COMPLETE")

    def test_load_summary_restores_prior_reads(self):
        """load_summary() restores prior_reads from a dict."""
        chitta = Chitta()
        chitta.load_summary({
            "prior_reads": ["/a.py", "/b.py"],
            "files_written": ["/a.py"],
            "last_phase": "VERIFY",
        })
        assert chitta.prior_reads == frozenset({"/a.py", "/b.py"})
        assert chitta.was_file_read("/a.py") is True

    def test_roundtrip_serialization(self):
        """to_summary → load_summary preserves data."""
        c1 = Chitta()
        c1.record("read_file", 1, True, path="/x.py")
        c1.record("read_file", 2, True, path="/y.py")
        c1.end_turn()
        summary = c1.to_summary()

        c2 = Chitta()
        c2.load_summary(summary)
        assert c2.prior_reads == c1.prior_reads
        assert c2.was_file_read("/x.py") is True

    def test_stats_includes_prior_reads_count(self):
        """Stats show how many prior reads are tracked."""
        chitta = Chitta()
        chitta.record("read_file", 1, True, path="/a.py")
        chitta.end_turn()
        assert chitta.stats["prior_reads"] == 1


class TestGandhaAvailableTools:
    """Test Gandha route_miss with dynamic available_tools parameter."""

    def test_route_miss_uses_available_tools(self):
        """Route miss suggestion includes dynamically-provided tool names."""
        imps = [
            Impression("bad_tool", 1, False, "Tool 'bad_tool' not found (O(1) route miss)"),
            Impression("worse_tool", 2, False, "Tool 'worse_tool' not found (O(1) route miss)"),
        ]
        tools = frozenset({"bash", "read_file", "sub_agent"})
        d = detect_patterns(imps, available_tools=tools)
        assert d is not None
        assert d.pattern == "route_miss"
        assert "bash" in d.suggestion
        assert "read_file" in d.suggestion
        assert "sub_agent" in d.suggestion

    def test_route_miss_without_tools_uses_default(self):
        """Route miss without available_tools uses hardcoded default list."""
        imps = [
            Impression("bad", 1, False, "Tool 'bad' not found"),
            Impression("worse", 2, False, "Tool 'worse' not found"),
        ]
        d = detect_patterns(imps)
        assert d is not None
        assert "sub_agent" in d.suggestion  # default includes sub_agent now

    def test_other_patterns_unaffected_by_available_tools(self):
        """Non-route-miss patterns work the same regardless of available_tools."""
        imps = [
            Impression("bash", i, False, f"err {i}")
            for i in range(MAX_CONSECUTIVE_ERRORS)
        ]
        d = detect_patterns(imps, available_tools=frozenset({"bash", "read_file"}))
        assert d is not None
        assert d.pattern == "consecutive_errors"  # not affected by available_tools


class TestGandhaCrossTurn:
    """Test Gandha cross-turn awareness (write-without-read with prior_reads)."""

    def test_write_ok_if_read_in_prior_turn(self):
        """Writing a file that was read in a prior turn is safe."""
        imps = [
            Impression("edit_file", 1, True, path="/src/main.py"),
        ]
        prior = frozenset({"/src/main.py"})
        d = detect_patterns(imps, prior_reads=prior)
        assert d is None  # No detection — file was read in prior turn

    def test_write_flagged_if_never_read(self):
        """Writing a file never read (current or prior) is detected."""
        imps = [
            Impression("edit_file", 1, True, path="/src/main.py"),
        ]
        prior = frozenset({"/src/other.py"})  # different file
        d = detect_patterns(imps, prior_reads=prior)
        assert d is not None
        assert d.pattern == "write_without_read"


class TestBuddhiPhaseGuidance:
    """Test that Buddhi injects guidance at phase transitions."""

    def test_execute_to_verify_injects_guidance(self):
        """Transitioning EXECUTE → VERIFY nudges LLM to run tests."""
        from steward.buddhi import Buddhi
        from steward.types import ToolUse

        buddhi = Buddhi()

        # Read → ORIENT
        buddhi.evaluate(
            [ToolUse(id="1", name="read_file", parameters={"path": "/a.py"})],
            [(True, "")],
        )
        # Read → ORIENT (still < 2 reads after the first one... wait, we had a read)
        buddhi.evaluate(
            [ToolUse(id="2", name="read_file", parameters={"path": "/b.py"})],
            [(True, "")],
        )
        # Now EXECUTE (2 reads)
        # Write → stays EXECUTE
        buddhi.evaluate(
            [ToolUse(id="3", name="edit_file", parameters={"path": "/a.py", "old": "x", "new": "y"})],
            [(True, "")],
        )
        # Read (no recent write) → should transition to VERIFY
        v = buddhi.evaluate(
            [ToolUse(id="4", name="read_file", parameters={"path": "/c.py"})],
            [(True, "")],
        )
        # But we need to check: recent 3 = [read, edit, read]
        # recent_writes = 0 (only the read from id=4 counts as recent write? No, edit is a write)
        # Hmm, let me think: impressions are [read, read, edit, read]
        # recent 3 = [read, edit, read] — recent_writes: edit_file IS in _WRITE_NAMES, and it succeeded
        # So recent_writes = 1 → still EXECUTE
        # We need more reads after the write to get to VERIFY
        v2 = buddhi.evaluate(
            [ToolUse(id="5", name="read_file", parameters={"path": "/d.py"})],
            [(True, "")],
        )
        v3 = buddhi.evaluate(
            [ToolUse(id="6", name="read_file", parameters={"path": "/e.py"})],
            [(True, "")],
        )
        # Now recent 3 = [read, read, read], no recent writes, total_writes=1 → VERIFY
        # Phase transition: EXECUTE → VERIFY → reflect guidance
        assert v3.action == "reflect"
        assert "modified" in v3.suggestion.lower()

    def test_phase_appears_in_directive(self):
        """BuddhiDirective includes the current phase."""
        from steward.buddhi import Buddhi

        buddhi = Buddhi()
        d = buddhi.pre_flight("test something", 0)
        assert d.phase in ("ORIENT", "EXECUTE", "VERIFY", "COMPLETE")
