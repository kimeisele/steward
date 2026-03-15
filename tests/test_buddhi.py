"""Tests for Buddhi — Discriminative Intelligence.

Uses REAL substrate primitives:
- SemanticActionType from steward-protocol
- IntentGuna from MahaCompression
- MahaBuddhi for cognitive classification
"""

from __future__ import annotations

from steward.buddhi import Buddhi, BuddhiDirective, BuddhiVerdict, ModelTier
from steward.types import ToolUse
from vibe_core.mahamantra.protocols.compression import IntentGuna
from vibe_core.mahamantra.substrate.manas.synaptic import HebbianSynaptic
from vibe_core.runtime.semantic_actions import SemanticActionType


def _tc(name: str = "bash", **params: object) -> ToolUse:
    """Helper to create a ToolUse."""
    return ToolUse(id=f"call_{id(params)}", name=name, parameters=params)


class TestBuddhiBasics:
    def test_single_success_continues(self):
        """Single successful tool call → continue."""
        buddhi = Buddhi()
        v = buddhi.evaluate([_tc("bash", command="ls")], [(True, "")])
        assert v.action == "continue"

    def test_single_error_redirects(self):
        """Single error triggers redirect — infrastructure forces retry."""
        buddhi = Buddhi()
        v = buddhi.evaluate([_tc("bash", command="bad")], [(False, "not found")])
        assert v.action == "redirect"
        assert "bash" in v.reason
        assert "alternative" in v.suggestion.lower()

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
            (False, "err"),
            (False, "err"),
            (False, "err"),
            (True, ""),
            (True, ""),
            (True, ""),
            (False, "err"),
            (False, "err"),
        ]
        for name, result in zip(tools, results):
            v = buddhi.evaluate([_tc(name, path=f"/{name}")], [result])
        # Last call failed → redirect (infrastructure forces retry).
        # Key invariant: NOT abort (only 2 consecutive at end, not 5).
        assert v.action == "redirect"
        assert v.action != "abort"


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
        v = buddhi.evaluate([_tc("bash", command="fail_again")], [(False, "err")])
        assert v.action == "reflect"

    def test_low_error_ratio_continues(self):
        """< 70% errors → continue."""
        buddhi = Buddhi()
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


class TestPreFlightSubstrate:
    """Pre-flight uses real substrate primitives."""

    def test_pre_flight_returns_directive(self):
        """pre_flight returns a BuddhiDirective with substrate types."""
        buddhi = Buddhi()
        d = buddhi.pre_flight("fix the authentication bug", 0)
        assert isinstance(d, BuddhiDirective)
        assert isinstance(d.action, SemanticActionType)
        assert isinstance(d.guna, IntentGuna)
        assert isinstance(d.tool_names, frozenset)
        assert d.max_tokens > 0

    def test_pre_flight_has_cognitive_frame(self):
        """Directive includes MahaBuddhi cognitive frame."""
        buddhi = Buddhi()
        d = buddhi.pre_flight("implement a new router", 0)
        # function and approach come from MahaBuddhi.think() (lowercase from VM)
        assert d.function != ""  # carrier/deliverer/enhancer/creator/maintainer/destroyer
        assert d.approach != ""  # genesis/dharma/karma/moksha

    def test_pre_flight_tool_selection_not_empty(self):
        """Pre-flight selects at least some tools for real messages."""
        buddhi = Buddhi()
        d = buddhi.pre_flight("read the main.py file and explain it", 0)
        assert len(d.tool_names) > 0

    def test_pre_flight_token_budget(self):
        """Token budget is tick-aligned and never below floor."""
        from steward.cbr import CBR_FLOOR, CBR_TICK

        buddhi = Buddhi()
        d = buddhi.pre_flight("some task", 0)
        assert d.max_tokens % CBR_TICK == 0  # tick-aligned
        assert d.max_tokens >= CBR_FLOOR  # never below floor

    def test_pre_flight_stable_across_rounds(self):
        """Action type classified once on round 0, stable after."""
        buddhi = Buddhi()
        d0 = buddhi.pre_flight("fix the bug", 0)
        d1 = buddhi.pre_flight("whatever", 1)
        assert d0.action == d1.action  # not reclassified


class TestPreFlightPhaseEvolution:
    """Tool set evolves based on Chitta phase (not round counter)."""

    def test_orient_stays_read_only(self):
        """ORIENT phase keeps read-only tools for SATTVA actions."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.RESEARCH
        buddhi._guna = IntentGuna.SATTVA
        buddhi._function = "VISHNU"
        buddhi._approach = "MOKSHA"

        d = buddhi.pre_flight("observe", 1)
        assert "edit_file" not in d.tool_names
        assert d.phase == "ORIENT"

    def test_execute_phase_unlocks_writes(self):
        """After 2+ reads, phase evolves to EXECUTE, write tools added."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.RESEARCH
        buddhi._guna = IntentGuna.SATTVA
        buddhi._function = "VISHNU"
        buddhi._approach = "MOKSHA"

        # Simulate 2 successful reads → Chitta phase becomes EXECUTE
        buddhi.evaluate([_tc("read_file", path="/a.py")], [(True, "")])
        buddhi.evaluate([_tc("glob", pattern="*.py")], [(True, "")])

        d = buddhi.pre_flight("observe", 2)
        assert "edit_file" in d.tool_names
        assert d.phase == "EXECUTE"

    def test_errors_add_bash(self):
        """After 2+ recent errors, bash is added for debugging."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.RESEARCH
        buddhi._guna = IntentGuna.SATTVA
        buddhi._function = "VISHNU"
        buddhi._approach = "MOKSHA"

        buddhi.evaluate([_tc("read_file", path="/a")], [(False, "err")])
        buddhi.evaluate([_tc("grep", pattern="x")], [(False, "err")])
        d = buddhi.pre_flight("observe", 2)
        assert "bash" in d.tool_names


class TestPreFlightTokenSavings:
    """Verify that pre-flight saves tokens with substrate routing."""

    def test_read_action_sends_fewer_tools(self):
        """RESEARCH/ANALYZE sends OBSERVE tools (read_file, glob, grep, http)."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.RESEARCH
        buddhi._guna = IntentGuna.SATTVA
        buddhi._function = "VISHNU"
        buddhi._approach = "MOKSHA"

        d = buddhi.pre_flight("research", 1)
        assert len(d.tool_names) == 5  # OBSERVE: read_file, glob, grep, http, think
        assert "http" in d.tool_names

    def test_test_action_sends_fewer_tools(self):
        """TEST sends OBSERVE + EXECUTE = 6 tools (read_file, glob, grep, http, think, bash)."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.TEST
        buddhi._guna = IntentGuna.TAMAS
        buddhi._function = "SHIVA"
        buddhi._approach = "KARMA"

        d = buddhi.pre_flight("test", 1)
        assert len(d.tool_names) == 6
        assert "bash" in d.tool_names
        assert "grep" in d.tool_names


class TestContextAwareTokenBudget:
    """Token budget adapts to context window pressure."""

    def test_low_context_gets_dsp_budget(self):
        """Low context → DSP: weight(1.0) × phase_mod(0.5) = 0.5, no compression."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.IMPLEMENT
        buddhi._guna = IntentGuna.RAJAS
        buddhi._function = "BRAHMA"
        buddhi._approach = "GENESIS"

        d = buddhi.pre_flight("implement", 1, context_pct=0.3)
        # IMPLEMENT(1.0) × ORIENT(0.5) = 0.5 gain, no compression → 768
        assert d.max_tokens == 768

    def test_moderate_context_compresses_budget(self):
        """60-80% context → DSP compressor logarithmically reduces gain."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.IMPLEMENT
        buddhi._guna = IntentGuna.RAJAS
        buddhi._function = "BRAHMA"
        buddhi._approach = "GENESIS"

        d_low = buddhi.pre_flight("implement", 1, context_pct=0.3)
        d_mod = buddhi.pre_flight("implement", 1, context_pct=0.65)
        # Compressed budget < uncompressed, both above floor
        assert d_mod.max_tokens < d_low.max_tokens
        assert d_mod.max_tokens >= 512  # never below floor

    def test_high_context_compressed_mode(self):
        """Over 80% context → DSP compressor heavily attenuates. Never below floor."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.IMPLEMENT
        buddhi._guna = IntentGuna.RAJAS
        buddhi._function = "BRAHMA"
        buddhi._approach = "GENESIS"

        d_mod = buddhi.pre_flight("implement", 1, context_pct=0.65)
        d_high = buddhi.pre_flight("implement", 1, context_pct=0.85)
        # Higher pressure → lower budget, still above floor
        assert d_high.max_tokens <= d_mod.max_tokens
        assert d_high.max_tokens >= 512

    def test_research_stays_at_floor(self):
        """RESEARCH weight=0.0 → gain=0.0 → floor (512) regardless of pressure."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.RESEARCH
        buddhi._guna = IntentGuna.SATTVA
        buddhi._function = "VISHNU"
        buddhi._approach = "MOKSHA"

        d50 = buddhi.pre_flight("research", 1, context_pct=0.65)
        assert d50.max_tokens == 512  # floor — weight=0.0 means floor always

        d80 = buddhi.pre_flight("research", 1, context_pct=0.85)
        assert d80.max_tokens == 512  # floor — can't go below


class TestSeedConfidenceDSP:
    """Seed confidence feeds into DSP cache gate via Hebbian synaptic."""

    def test_high_confidence_reduces_budget(self):
        """Seed with high Hebbian confidence → DSP cache gate attenuates."""
        synaptic = HebbianSynaptic()
        buddhi = Buddhi(synaptic=synaptic)
        buddhi._action = SemanticActionType.IMPLEMENT
        buddhi._guna = IntentGuna.RAJAS
        buddhi._function = "BRAHMA"
        buddhi._approach = "GENESIS"

        seed = 12345
        # Drive confidence above 0.7 (5+ successes from 0.5 baseline)
        for _ in range(6):
            synaptic.update(f"seed:{seed}", "cache", True)
        assert buddhi.seed_confidence(seed) > 0.7

        d_no_seed = buddhi.pre_flight("implement", 1, context_pct=0.0, seed=0)
        d_with_seed = buddhi.pre_flight("implement", 1, context_pct=0.0, seed=seed)
        assert d_with_seed.max_tokens < d_no_seed.max_tokens

    def test_low_confidence_no_effect(self):
        """Seed with default confidence (0.5) → negligible DSP effect."""
        synaptic = HebbianSynaptic()
        buddhi = Buddhi(synaptic=synaptic)
        buddhi._action = SemanticActionType.IMPLEMENT
        buddhi._guna = IntentGuna.RAJAS
        buddhi._function = "BRAHMA"
        buddhi._approach = "GENESIS"

        # Default weight is 0.5 → cache gate: gain *= (1 - 0.5 * 0.5) = 0.75
        # vs seed=0: gain *= (1 - 0.0 * 0.5) = 1.0
        # Both produce different gains but the difference is from the continuous gate
        d_no_seed = buddhi.pre_flight("implement", 1, context_pct=0.0, seed=0)
        d_unknown = buddhi.pre_flight("implement", 1, context_pct=0.0, seed=99999)
        # Unknown seed gets default 0.5 confidence → some attenuation
        assert d_unknown.max_tokens <= d_no_seed.max_tokens

    def test_no_synaptic_zero_confidence(self):
        """Without HebbianSynaptic, seed confidence is always 0.0."""
        buddhi = Buddhi()  # no synaptic
        assert buddhi.seed_confidence(12345) == 0.0


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
        # 1 failure in batch → redirect (infrastructure forces retry)
        assert v.action == "redirect"
        assert buddhi.stats["total_calls"] == 3
        assert buddhi.stats["errors"] == 1


class TestFailureRedirect:
    """Redirect patterns — deterministic fix suggestions for known failure modes."""

    def test_edit_file_not_found_redirects_to_read(self):
        """edit_file failing 2x with 'not found' → redirect to read_file."""
        buddhi = Buddhi()
        tc1 = _tc("edit_file", path="/a.py", old="foo", new="bar")
        tc2 = _tc("edit_file", path="/a.py", old="baz", new="qux")
        buddhi.evaluate([tc1], [(False, "old_string not found")])
        v = buddhi.evaluate([tc2], [(False, "no match in file")])
        assert v.action == "redirect"
        assert "read_file" in v.suggestion

    def test_edit_file_success_no_redirect(self):
        """edit_file succeeding after read → no redirect."""
        buddhi = Buddhi()
        # Read the file first (Gandha expects reads before writes)
        buddhi.evaluate([_tc("read_file", path="/a.py")], [(True, "")])
        tc = _tc("edit_file", path="/a.py", old="foo", new="bar")
        buddhi.evaluate([tc], [(True, "")])
        v = buddhi.evaluate([tc], [(True, "")])
        assert v.action == "continue"

    def test_write_file_fails_redirects_to_read(self):
        """write_file failing 2x → redirect to verify path."""
        buddhi = Buddhi()
        tc1 = _tc("write_file", path="/bad/path.py", content="x")
        tc2 = _tc("write_file", path="/bad/path2.py", content="y")
        buddhi.evaluate([tc1], [(False, "permission denied")])
        v = buddhi.evaluate([tc2], [(False, "no such directory")])
        assert v.action == "redirect"
        assert "glob" in v.suggestion or "read_file" in v.suggestion

    def test_route_misses_redirect_to_valid_tools(self):
        """Repeated route misses → redirect with available tool names."""
        buddhi = Buddhi()
        tc1 = _tc("search_code", query="foo")
        tc2 = _tc("find_files", pattern="*.py")
        buddhi.evaluate([tc1], [(False, "Tool 'search_code' not found (O(1) route miss)")])
        v = buddhi.evaluate([tc2], [(False, "Tool 'find_files' not found (O(1) route miss)")])
        assert v.action == "redirect"
        assert "Available tools" in v.suggestion

    def test_single_failure_redirects(self):
        """Single failure triggers generic redirect — infrastructure forces retry."""
        buddhi = Buddhi()
        tc = _tc("edit_file", path="/a.py", old="foo", new="bar")
        v = buddhi.evaluate([tc], [(False, "old_string not found")])
        assert v.action == "redirect"
        assert "edit_file" in v.reason

    def test_redirect_before_identical_check(self):
        """Redirect fires before identical-call reflect (lower severity)."""
        buddhi = Buddhi()
        # Same edit_file call 3x with 'not found' — redirect at 2, not reflect at 3
        tc = _tc("edit_file", path="/a.py", old="foo", new="bar")
        buddhi.evaluate([tc], [(False, "old_string not found")])
        v = buddhi.evaluate([tc], [(False, "old_string not found")])
        # Redirect fires at 2 (before identical-call reflect which needs 3)
        assert v.action == "redirect"

    def test_blocked_tools_tracked_in_stats(self):
        """Blocked tools (route miss) are tracked in stats like normal tools."""
        buddhi = Buddhi()
        tc = _tc("nonexistent_tool", query="x")
        buddhi.evaluate([tc], [(False, "route miss")])
        assert buddhi.stats["total_calls"] == 1
        assert buddhi.stats["errors"] == 1
        assert buddhi.stats["tool_distribution"] == {"nonexistent_tool": 1}


class TestModelTier:
    """Tests for ModelTier routing in BuddhiDirective."""

    def test_action_tier_mapping_flash(self):
        """RESEARCH, MONITOR, TEST → FLASH tier."""
        from steward.buddhi import _ACTION_TIER

        assert _ACTION_TIER[SemanticActionType.RESEARCH] == ModelTier.FLASH
        assert _ACTION_TIER[SemanticActionType.MONITOR] == ModelTier.FLASH
        assert _ACTION_TIER[SemanticActionType.TEST] == ModelTier.FLASH

    def test_action_tier_mapping_standard(self):
        """IMPLEMENT, DEBUG, REFACTOR → STANDARD tier."""
        from steward.buddhi import _ACTION_TIER

        assert _ACTION_TIER[SemanticActionType.IMPLEMENT] == ModelTier.STANDARD
        assert _ACTION_TIER[SemanticActionType.DEBUG] == ModelTier.STANDARD
        assert _ACTION_TIER[SemanticActionType.REFACTOR] == ModelTier.STANDARD

    def test_action_tier_mapping_pro(self):
        """DESIGN, SYNTHESIZE → PRO tier."""
        from steward.buddhi import _ACTION_TIER

        assert _ACTION_TIER[SemanticActionType.DESIGN] == ModelTier.PRO
        assert _ACTION_TIER[SemanticActionType.SYNTHESIZE] == ModelTier.PRO

    def test_tier_demotes_under_context_pressure(self):
        """At 70%+ context, tier demotes to FLASH regardless of action."""
        buddhi = Buddhi()
        directive = buddhi.pre_flight("do something complex", 0, context_pct=0.75)
        assert directive.tier == ModelTier.FLASH

    def test_tier_in_directive(self):
        """BuddhiDirective includes tier field."""
        buddhi = Buddhi()
        directive = buddhi.pre_flight("list all files", 0)
        assert isinstance(directive.tier, ModelTier)
        assert directive.tier.value in ("flash", "standard", "pro")

    def test_all_actions_have_tier(self):
        """Every SemanticActionType has a tier mapping."""
        from steward.buddhi import _ACTION_TIER

        for action in SemanticActionType:
            assert action in _ACTION_TIER, f"{action} missing from _ACTION_TIER"


class TestHebbianTierEscalation:
    """Tests for Hebbian learning — real HebbianSynaptic from steward-protocol."""

    def test_no_synaptic_keeps_default_tier(self):
        """Without HebbianSynaptic, tiers stay at action defaults."""
        buddhi = Buddhi()  # no synaptic
        directive = buddhi.pre_flight("fix the broken test", 0)
        # Tier matches action default (whatever Manas classifies)
        from steward.buddhi import _ACTION_TIER

        assert directive.tier == _ACTION_TIER[directive.action]

    def test_flash_escalates_to_standard_on_low_weight(self):
        """FLASH tier escalates to STANDARD when synaptic weight < 0.4."""
        synaptic = HebbianSynaptic()
        buddhi = Buddhi(synaptic=synaptic)
        # Force a FLASH-tier action directly
        buddhi._action = SemanticActionType.RESEARCH
        buddhi._guna = IntentGuna.SATTVA
        buddhi._function = "carrier"
        buddhi._approach = "moksha"

        d0 = buddhi.pre_flight("research something", 1)
        assert d0.tier == ModelTier.FLASH

        # Drive weight down with failures (0.5 → 0.45 → 0.405 → 0.3645)
        for _ in range(3):
            synaptic.update("research", "execute", False)
        assert synaptic.get_weight("research", "execute") < 0.4

        directive = buddhi.pre_flight("research something", 1)
        assert directive.tier == ModelTier.STANDARD  # escalated

    def test_standard_escalates_to_pro_on_very_low_weight(self):
        """STANDARD tier escalates to PRO when synaptic weight < 0.25."""
        synaptic = HebbianSynaptic()
        buddhi = Buddhi(synaptic=synaptic)
        # Force a STANDARD-tier action
        buddhi._action = SemanticActionType.IMPLEMENT
        buddhi._guna = IntentGuna.RAJAS
        buddhi._function = "carrier"
        buddhi._approach = "genesis"

        d0 = buddhi.pre_flight("implement something", 1)
        assert d0.tier == ModelTier.STANDARD

        # Drive weight well below 0.25 with many failures
        for _ in range(8):
            synaptic.update("implement", "execute", False)
        assert synaptic.get_weight("implement", "execute") < 0.25

        directive = buddhi.pre_flight("implement something", 1)
        assert directive.tier == ModelTier.PRO  # escalated

    def test_high_weight_keeps_default(self):
        """Strong synaptic weight does not escalate tier."""
        synaptic = HebbianSynaptic()
        buddhi = Buddhi(synaptic=synaptic)
        # Force a STANDARD-tier action
        buddhi._action = SemanticActionType.IMPLEMENT
        buddhi._guna = IntentGuna.RAJAS
        buddhi._function = "carrier"
        buddhi._approach = "genesis"

        # Successes strengthen the weight (0.5 → 0.55 → 0.595 → ...)
        for _ in range(3):
            synaptic.update("implement", "execute", True)
        assert synaptic.get_weight("implement", "execute") > 0.5

        directive = buddhi.pre_flight("implement something", 1)
        assert directive.tier == ModelTier.STANDARD  # stays at default

    def test_context_pressure_overrides_escalation(self):
        """Context pressure (>70%) demotes to FLASH even after escalation."""
        synaptic = HebbianSynaptic()
        buddhi = Buddhi(synaptic=synaptic)
        buddhi._action = SemanticActionType.IMPLEMENT
        buddhi._guna = IntentGuna.RAJAS
        buddhi._function = "carrier"
        buddhi._approach = "genesis"

        for _ in range(8):
            synaptic.update("implement", "execute", False)

        directive = buddhi.pre_flight("implement something", 1, context_pct=0.75)
        assert directive.tier == ModelTier.FLASH  # context pressure wins

    def test_record_outcome_updates_weight(self):
        """record_outcome() delegates to HebbianSynaptic.update()."""
        synaptic = HebbianSynaptic()
        buddhi = Buddhi(synaptic=synaptic)
        buddhi.pre_flight("fix the broken test", 0)
        action = buddhi._action.value

        # Record success → weight should increase from 0.5
        buddhi.record_outcome(True)
        assert synaptic.get_weight(action, "execute") > 0.5

        # Record failure → weight should decrease
        buddhi.record_outcome(False)
        w = synaptic.get_weight(action, "execute")
        assert 0.45 < w < 0.55  # near default after 1 success + 1 failure

    def test_weight_recovers_after_improvement(self):
        """Successes after failures recover the weight — tier de-escalates."""
        synaptic = HebbianSynaptic()
        buddhi = Buddhi(synaptic=synaptic)
        buddhi._action = SemanticActionType.IMPLEMENT
        buddhi._guna = IntentGuna.RAJAS
        buddhi._function = "carrier"
        buddhi._approach = "genesis"

        # Drive down
        for _ in range(5):
            synaptic.update("implement", "execute", False)
        assert synaptic.get_weight("implement", "execute") < 0.4

        # Recover
        for _ in range(10):
            synaptic.update("implement", "execute", True)
        assert synaptic.get_weight("implement", "execute") > 0.5

        directive = buddhi.pre_flight("implement something", 1)
        assert directive.tier == ModelTier.STANDARD  # recovered, no escalation


class TestToolNamespace:
    """Tests for ToolNamespace — semantic capability domains."""

    def test_namespace_enum_values(self):
        """All 4 namespaces exist with correct values."""
        from steward.buddhi import ToolNamespace

        assert ToolNamespace.OBSERVE == "observe"
        assert ToolNamespace.MODIFY == "modify"
        assert ToolNamespace.EXECUTE == "execute"
        assert ToolNamespace.DELEGATE == "delegate"

    def test_resolve_single_namespace(self):
        """Resolve a single namespace to tool names."""
        from steward.buddhi import ToolNamespace, resolve_namespaces

        tools = resolve_namespaces(frozenset({ToolNamespace.OBSERVE}))
        assert tools == frozenset({"read_file", "glob", "grep", "http", "think"})

    def test_resolve_multiple_namespaces(self):
        """Resolve combined namespaces — union of all tools."""
        from steward.buddhi import ToolNamespace, resolve_namespaces

        tools = resolve_namespaces(frozenset({ToolNamespace.OBSERVE, ToolNamespace.EXECUTE}))
        assert tools == frozenset({"read_file", "glob", "grep", "http", "think", "bash"})

    def test_resolve_all_namespaces(self):
        """Resolving all namespaces gives all 9 tools."""
        from steward.buddhi import ToolNamespace, resolve_namespaces

        tools = resolve_namespaces(frozenset(ToolNamespace))
        assert "read_file" in tools
        assert "bash" in tools
        assert "http" in tools
        assert "think" in tools
        assert "sub_agent" in tools
        assert len(tools) == 9

    def test_sub_agent_in_delegate_namespace(self):
        """sub_agent is in the DELEGATE namespace."""
        from steward.buddhi import _NAMESPACE_TOOLS, ToolNamespace

        assert "sub_agent" in _NAMESPACE_TOOLS[ToolNamespace.DELEGATE]

    def test_design_action_includes_sub_agent(self):
        """DESIGN action includes DELEGATE namespace → sub_agent visible."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.DESIGN
        buddhi._guna = IntentGuna.RAJAS
        buddhi._function = "BRAHMA"
        buddhi._approach = "GENESIS"

        d = buddhi.pre_flight("design the architecture", 1)
        assert "sub_agent" in d.tool_names

    def test_plan_action_includes_sub_agent(self):
        """PLAN action includes DELEGATE namespace → sub_agent visible."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.PLAN
        buddhi._guna = IntentGuna.SATTVA
        buddhi._function = "VISHNU"
        buddhi._approach = "DHARMA"

        d = buddhi.pre_flight("plan the approach", 1)
        assert "sub_agent" in d.tool_names

    def test_synthesize_action_includes_sub_agent(self):
        """SYNTHESIZE action includes DELEGATE namespace → sub_agent visible."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.SYNTHESIZE
        buddhi._guna = IntentGuna.SATTVA
        buddhi._function = "VISHNU"
        buddhi._approach = "MOKSHA"

        d = buddhi.pre_flight("synthesize findings", 1)
        assert "sub_agent" in d.tool_names

    def test_research_excludes_sub_agent(self):
        """RESEARCH action uses only OBSERVE → no sub_agent."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.RESEARCH
        buddhi._guna = IntentGuna.SATTVA
        buddhi._function = "VISHNU"
        buddhi._approach = "MOKSHA"

        d = buddhi.pre_flight("research the topic", 1)
        assert "sub_agent" not in d.tool_names

    def test_register_tool_runtime(self):
        """Register a new tool into a namespace at runtime."""
        from steward.buddhi import ToolNamespace, register_tool, resolve_namespaces, unregister_tool

        register_tool(ToolNamespace.OBSERVE, "semantic_search")
        try:
            tools = resolve_namespaces(frozenset({ToolNamespace.OBSERVE}))
            assert "semantic_search" in tools
        finally:
            unregister_tool(ToolNamespace.OBSERVE, "semantic_search")

    def test_unregister_tool_runtime(self):
        """Remove a tool from a namespace at runtime."""
        from steward.buddhi import ToolNamespace, register_tool, resolve_namespaces, unregister_tool

        register_tool(ToolNamespace.EXECUTE, "docker_run")
        unregister_tool(ToolNamespace.EXECUTE, "docker_run")
        tools = resolve_namespaces(frozenset({ToolNamespace.EXECUTE}))
        assert "docker_run" not in tools

    def test_all_actions_have_namespaces(self):
        """Every SemanticActionType has namespace mappings."""
        from steward.buddhi import _ACTION_NAMESPACES, resolve_namespaces

        for action in SemanticActionType:
            ns = _ACTION_NAMESPACES.get(action, frozenset())
            assert len(ns) > 0, f"{action} has no namespace mapping"
            tools = resolve_namespaces(ns)
            assert len(tools) > 0, f"{action} resolves to no tools"

    def test_implement_has_full_toolset(self):
        """IMPLEMENT action has OBSERVE + MODIFY + EXECUTE (no DELEGATE)."""
        from steward.buddhi import _ACTION_NAMESPACES, ToolNamespace

        ns = _ACTION_NAMESPACES[SemanticActionType.IMPLEMENT]
        assert ToolNamespace.OBSERVE in ns
        assert ToolNamespace.MODIFY in ns
        assert ToolNamespace.EXECUTE in ns
        assert ToolNamespace.DELEGATE not in ns
