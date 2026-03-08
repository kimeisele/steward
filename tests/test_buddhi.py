"""Tests for Buddhi — Discriminative Intelligence.

Uses REAL substrate primitives:
- SemanticActionType from steward-protocol
- IntentGuna from MahaCompression
- MahaBuddhi for cognitive classification
"""

from __future__ import annotations

from vibe_core.mahamantra.protocols.compression import IntentGuna
from vibe_core.runtime.semantic_actions import SemanticActionType

from steward.buddhi import Buddhi, BuddhiDirective, BuddhiVerdict, ModelTier
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
        # function and approach come from MahaBuddhi.think()
        assert d.function != ""  # BRAHMA/VISHNU/SHIVA
        assert d.approach != ""  # GENESIS/DHARMA/KARMA/MOKSHA

    def test_pre_flight_tool_selection_not_empty(self):
        """Pre-flight selects at least some tools for real messages."""
        buddhi = Buddhi()
        d = buddhi.pre_flight("read the main.py file and explain it", 0)
        assert len(d.tool_names) > 0

    def test_pre_flight_token_budget(self):
        """Token budget is set from action type."""
        buddhi = Buddhi()
        d = buddhi.pre_flight("some task", 0)
        assert d.max_tokens in (2048, 4096)

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
        """RESEARCH/ANALYZE sends 3 tools, not 6."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.RESEARCH
        buddhi._guna = IntentGuna.SATTVA
        buddhi._function = "VISHNU"
        buddhi._approach = "MOKSHA"

        d = buddhi.pre_flight("research", 1)
        assert len(d.tool_names) == 3

    def test_test_action_sends_fewer_tools(self):
        """TEST sends OBSERVE + EXECUTE = 4 tools (read_file, glob, grep, bash)."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.TEST
        buddhi._guna = IntentGuna.TAMAS
        buddhi._function = "SHIVA"
        buddhi._approach = "KARMA"

        d = buddhi.pre_flight("test", 1)
        assert len(d.tool_names) == 4
        assert "bash" in d.tool_names
        assert "grep" in d.tool_names


class TestContextAwareTokenBudget:
    """Token budget adapts to context window pressure."""

    def test_low_context_gets_full_budget(self):
        """Under 50% context → full token budget."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.IMPLEMENT
        buddhi._guna = IntentGuna.RAJAS
        buddhi._function = "BRAHMA"
        buddhi._approach = "GENESIS"

        d = buddhi.pre_flight("implement", 1, context_pct=0.3)
        assert d.max_tokens == 4096

    def test_half_context_constrains_budget(self):
        """50-70% context → max 2048 tokens."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.IMPLEMENT
        buddhi._guna = IntentGuna.RAJAS
        buddhi._function = "BRAHMA"
        buddhi._approach = "GENESIS"

        d = buddhi.pre_flight("implement", 1, context_pct=0.55)
        assert d.max_tokens == 2048

    def test_high_context_further_constrains(self):
        """Over 70% context → max 1024 tokens."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.IMPLEMENT
        buddhi._guna = IntentGuna.RAJAS
        buddhi._function = "BRAHMA"
        buddhi._approach = "GENESIS"

        d = buddhi.pre_flight("implement", 1, context_pct=0.75)
        assert d.max_tokens == 1024

    def test_research_already_under_cap(self):
        """RESEARCH has 2048 base — at 50% stays 2048, at 70% drops to 1024."""
        buddhi = Buddhi()
        buddhi._action = SemanticActionType.RESEARCH
        buddhi._guna = IntentGuna.SATTVA
        buddhi._function = "VISHNU"
        buddhi._approach = "MOKSHA"

        d50 = buddhi.pre_flight("research", 1, context_pct=0.55)
        assert d50.max_tokens == 2048  # already at cap

        d70 = buddhi.pre_flight("research", 1, context_pct=0.75)
        assert d70.max_tokens == 1024  # further constrained


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
        buddhi.evaluate(
            [_tc("read_file", path="/a.py")], [(True, "")]
        )
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

    def test_single_failure_no_redirect(self):
        """Single failure is not enough for redirect."""
        buddhi = Buddhi()
        tc = _tc("edit_file", path="/a.py", old="foo", new="bar")
        v = buddhi.evaluate([tc], [(False, "old_string not found")])
        assert v.action == "continue"

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
        assert tools == frozenset({"read_file", "glob", "grep"})

    def test_resolve_multiple_namespaces(self):
        """Resolve combined namespaces — union of all tools."""
        from steward.buddhi import ToolNamespace, resolve_namespaces
        tools = resolve_namespaces(frozenset({ToolNamespace.OBSERVE, ToolNamespace.EXECUTE}))
        assert tools == frozenset({"read_file", "glob", "grep", "bash"})

    def test_resolve_all_namespaces(self):
        """Resolving all namespaces gives all 7 tools."""
        from steward.buddhi import ToolNamespace, resolve_namespaces
        tools = resolve_namespaces(frozenset(ToolNamespace))
        assert "read_file" in tools
        assert "bash" in tools
        assert "sub_agent" in tools
        assert len(tools) == 7

    def test_sub_agent_in_delegate_namespace(self):
        """sub_agent is in the DELEGATE namespace."""
        from steward.buddhi import ToolNamespace, _NAMESPACE_TOOLS
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
        from steward.buddhi import ToolNamespace, register_tool, unregister_tool, resolve_namespaces

        register_tool(ToolNamespace.OBSERVE, "semantic_search")
        try:
            tools = resolve_namespaces(frozenset({ToolNamespace.OBSERVE}))
            assert "semantic_search" in tools
        finally:
            unregister_tool(ToolNamespace.OBSERVE, "semantic_search")

    def test_unregister_tool_runtime(self):
        """Remove a tool from a namespace at runtime."""
        from steward.buddhi import ToolNamespace, register_tool, unregister_tool, resolve_namespaces

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
        from steward.buddhi import ToolNamespace, _ACTION_NAMESPACES
        ns = _ACTION_NAMESPACES[SemanticActionType.IMPLEMENT]
        assert ToolNamespace.OBSERVE in ns
        assert ToolNamespace.MODIFY in ns
        assert ToolNamespace.EXECUTE in ns
        assert ToolNamespace.DELEGATE not in ns
