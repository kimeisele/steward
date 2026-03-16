"""Tests for briefing_stages — foveated rendering pipeline for CLAUDE.md."""

from steward.briefing_stages import (
    BUDGET_COMPACT,
    BUDGET_STANDARD,
    ActionStage,
    ArchitectureStage,
    BriefingPipeline,
    CriticalStage,
    EnvironmentStage,
    FederationInsightStage,
    GapAwarenessStage,
    IdentityStage,
    OrientationStage,
    SessionsStage,
    StatusStage,
    ToolboxStage,
    _estimate_tokens,
    compute_focus,
    default_pipeline,
)


class TestBriefingPipeline:
    def test_stages_sorted_by_priority(self):
        pipeline = default_pipeline()
        stages = pipeline.get_stages()
        priorities = [s.priority for s in stages]
        assert priorities == sorted(priorities)

    def test_default_pipeline_has_all_stages(self):
        pipeline = default_pipeline()
        assert pipeline.stage_count() == 12

    def test_dedup_by_name(self):
        pipeline = BriefingPipeline()
        pipeline.register(IdentityStage())
        pipeline.register(IdentityStage())
        assert pipeline.stage_count() == 1

    def test_generate_returns_string(self):
        pipeline = default_pipeline()
        result = pipeline.generate({}, {}, "/tmp")
        assert isinstance(result, str)
        assert "#" in result

    def test_stage_gate_skips(self):
        pipeline = BriefingPipeline()
        pipeline.register(StatusStage())
        result = pipeline.generate({}, {}, "/tmp")
        assert "## Status" not in result

    def test_stage_gate_runs(self):
        pipeline = BriefingPipeline()
        pipeline.register(StatusStage())
        ctx = {"health": {"value": 0.9, "guna": "sattva"}}
        result = pipeline.generate(ctx, {}, "/tmp")
        assert "## Status" in result
        assert "Health: 0.9" in result


class TestComputeFocus:
    """Focus signal computation from substrate signals."""

    def test_default_focus(self):
        focus = compute_focus({})
        assert 0.0 < focus.orientation <= 1.0
        assert focus.driver == "rajas"  # default guna

    def test_high_pain_boosts_all(self):
        ctx = {"senses": {"total_pain": 0.8}, "health": {"guna": "tamas"}}
        focus = compute_focus(ctx)
        assert focus.orientation >= 0.8
        assert focus.action >= 0.9
        assert "pain" in focus.driver

    def test_sattva_compresses_noise_not_signal(self):
        """Sattva compresses noise stages (toolbox, sessions) but not signal (orientation, architecture)."""
        ctx = {"senses": {"total_pain": 0.1}, "health": {"guna": "sattva"}}
        focus = compute_focus(ctx)
        # Signal stages stay high even in sattva
        assert focus.orientation >= 0.7
        assert focus.architecture >= 0.7
        # Noise stages compress
        assert focus.toolbox <= 0.3
        assert focus.sessions <= 0.3
        assert "sattva" in focus.driver

    def test_context_pressure_compresses(self):
        ctx = {"health": {"context_pressure": 0.8}}
        focus_low = compute_focus(ctx)
        focus_normal = compute_focus({})
        assert focus_low.orientation < focus_normal.orientation

    def test_gaps_boost_gap_awareness(self):
        ctx = {"gaps": {"active": [{"category": "tool", "description": "x"}] * 5}}
        focus = compute_focus(ctx)
        assert focus.gap_awareness > 0.5
        assert "gaps=5" in focus.driver

    def test_sense_pain_boosts_environment(self):
        ctx = {"senses": {"detail": {"srotra": {"pain": 0.6, "active": True}}}}
        focus = compute_focus(ctx)
        assert focus.environment >= 0.6
        assert "git_pain" in focus.driver

    def test_all_weights_clamped(self):
        focus = compute_focus({"health": {"context_pressure": 0.99}})
        for attr in ("orientation", "status", "action", "knowledge", "environment",
                      "gap_awareness", "federation_insight", "toolbox", "architecture", "sessions"):
            val = getattr(focus, attr)
            assert 0.1 <= val <= 1.0, f"{attr}={val} out of [0.1, 1.0]"


class TestIdentityStage:
    def test_includes_project_name(self):
        stage = IdentityStage()
        parts: list[str] = []
        ctx = {"project": {"name": "myproject"}}
        stage.enrich(parts, ctx, {}, "/tmp", 1.0)
        assert any("myproject" in p for p in parts)

    def test_includes_north_star(self):
        stage = IdentityStage()
        parts: list[str] = []
        arch = {"north_star": "execute tasks with minimal tokens"}
        stage.enrich(parts, {}, arch, "/tmp", 1.0)
        assert any("execute tasks" in p for p in parts)


class TestCriticalStage:
    def test_no_critical_shows_healthy(self):
        stage = CriticalStage()
        parts: list[str] = []
        stage.enrich(parts, {}, {}, "/tmp", 1.0)
        assert any("No critical" in p for p in parts)

    def test_low_health_shows_critical(self):
        stage = CriticalStage()
        parts: list[str] = []
        ctx = {"health": {"value": 0.3, "guna": "tamas"}, "immune": {}, "federation": {}, "senses": {}}
        stage.enrich(parts, ctx, {}, "/tmp", 1.0)
        assert any("CRITICAL" in p for p in parts)


class TestOrientationStage:
    def test_full_focus_includes_all(self, tmp_path):
        steward_dir = tmp_path / ".steward"
        steward_dir.mkdir()
        (steward_dir / "conventions.md").write_text(
            "## Identity\nYou are Steward.\n\n## Pipeline\nManas → Buddhi\n"
        )
        stage = OrientationStage()
        parts: list[str] = []
        stage.enrich(parts, {}, {}, str(tmp_path), 1.0)
        text = "\n".join(parts)
        assert "You are Steward" in text
        assert "Manas" in text

    def test_low_focus_only_headers(self, tmp_path):
        steward_dir = tmp_path / ".steward"
        steward_dir.mkdir()
        (steward_dir / "conventions.md").write_text(
            "## Identity\nYou are Steward.\n\n## Pipeline\nManas → Buddhi\n"
        )
        stage = OrientationStage()
        parts: list[str] = []
        stage.enrich(parts, {}, {}, str(tmp_path), 0.1)
        text = "\n".join(parts)
        assert "## Identity" in text
        assert "## Pipeline" in text
        assert "You are Steward" not in text


class TestActionStage:
    def test_skips_when_no_issues(self):
        stage = ActionStage()
        assert not stage.should_run({}, {})

    def test_shows_issues(self):
        stage = ActionStage()
        parts: list[str] = []
        ctx = {"issues": [{"number": 42, "title": "Fix bug"}]}
        stage.enrich(parts, ctx, {}, "/tmp", 1.0)
        assert any("#42" in p for p in parts)


class TestGapAwarenessStage:
    def test_skips_when_no_gaps(self):
        stage = GapAwarenessStage()
        assert not stage.should_run({}, {})

    def test_full_focus_shows_context(self):
        stage = GapAwarenessStage()
        parts: list[str] = []
        ctx = {
            "gaps": {
                "active": [{"category": "tool", "description": "missing linter", "context": "bandit check"}],
                "stats": {"total_tracked": 5, "resolved": 3},
            }
        }
        stage.enrich(parts, ctx, {}, "/tmp", 1.0)
        text = "\n".join(parts)
        assert "missing linter" in text
        assert "bandit check" in text  # Context shown at high focus

    def test_low_focus_count_only(self):
        stage = GapAwarenessStage()
        parts: list[str] = []
        ctx = {"gaps": {"active": [{"category": "tool", "description": "x"}] * 3, "stats": {}}}
        stage.enrich(parts, ctx, {}, "/tmp", 0.1)
        text = "\n".join(parts)
        assert "3 active gaps" in text
        assert "x" not in text.replace("3 active gaps", "")


class TestFederationInsightStage:
    def test_reads_inbox(self, tmp_path):
        import json

        fed_dir = tmp_path / "data" / "federation"
        fed_dir.mkdir(parents=True)
        inbox = [
            {
                "operation": "research_result",
                "agent_id": "peer-alpha",
                "payload": {"summary": "Found scaling bottleneck in federation"},
            }
        ]
        (fed_dir / "nadi_inbox.json").write_text(json.dumps(inbox))

        stage = FederationInsightStage()
        parts: list[str] = []
        stage.enrich(parts, {}, {}, str(tmp_path), 1.0)
        assert any("peer-alpha" in p for p in parts)

    def test_empty_inbox_produces_nothing(self, tmp_path):
        import json

        fed_dir = tmp_path / "data" / "federation"
        fed_dir.mkdir(parents=True)
        (fed_dir / "nadi_inbox.json").write_text(json.dumps([]))

        stage = FederationInsightStage()
        parts: list[str] = []
        stage.enrich(parts, {}, {}, str(tmp_path), 1.0)
        assert len(parts) == 0


class TestToolboxStage:
    def test_skips_when_no_tools(self):
        stage = ToolboxStage()
        assert not stage.should_run({}, {})

    def test_full_focus_shows_descriptions(self):
        stage = ToolboxStage()
        parts: list[str] = []
        arch = {"tools": [{"name": "synthesize_briefing", "description": "Generate briefing."}]}
        stage.enrich(parts, {}, arch, "/tmp", 1.0)
        assert any("Generate briefing" in p for p in parts)

    def test_low_focus_count_only(self):
        stage = ToolboxStage()
        parts: list[str] = []
        arch = {"tools": [{"name": "a"}, {"name": "b"}]}
        stage.enrich(parts, {}, arch, "/tmp", 0.1)
        text = "\n".join(parts)
        assert "2 tools available" in text


class TestArchitectureStage:
    def test_shows_services(self):
        stage = ArchitectureStage()
        parts: list[str] = []
        arch = {
            "services": {"SVC_ATTENTION": "Attention", "SVC_CACHE": "Cache"},
            "kshetra": ["a", "b"],
            "phases": {"genesis": "boot"},
            "hooks": {},
        }
        stage.enrich(parts, {}, arch, "/tmp", 1.0)
        assert any("2 services" in p for p in parts)
        assert any("MURALI" in p for p in parts)

    def test_compressed_shows_group_counts(self):
        stage = ArchitectureStage()
        parts: list[str] = []
        arch = {
            "services": {"SVC_ATTENTION": "a", "SVC_CACHE": "b"},
            "kshetra": [],
            "phases": {"genesis": "boot"},
            "hooks": {},
        }
        stage.enrich(parts, {}, arch, "/tmp", 0.5)
        text = "\n".join(parts)
        assert "Services:" in text  # Compressed group summary


class TestSessionsStage:
    def test_skips_when_no_sessions(self):
        stage = SessionsStage()
        assert not stage.should_run({}, {})

    def test_shows_stats(self):
        stage = SessionsStage()
        parts: list[str] = []
        ctx = {"sessions": {"stats": {"total": 10, "success_rate": 0.8}}}
        stage.enrich(parts, ctx, {}, "/tmp", 1.0)
        assert any("10 total" in p for p in parts)


class TestTokenBudget:
    def test_estimate_tokens(self):
        assert _estimate_tokens("hello world") == max(1, len("hello world") // 4)
        assert _estimate_tokens("") == 1

    def test_budget_default_is_standard(self):
        pipeline = default_pipeline()
        assert pipeline.token_budget == BUDGET_STANDARD

    def test_compact_smaller_than_standard(self):
        compact = default_pipeline(token_budget=BUDGET_COMPACT)
        standard = default_pipeline(token_budget=BUDGET_STANDARD)
        ctx = {
            "health": {"value": 0.9, "guna": "sattva"},
            "sessions": {"stats": {"total": 5, "success_rate": 0.8}},
        }
        arch = {
            "services": {"SVC_A": "a", "SVC_B": "b"},
            "kshetra": ["x"],
            "phases": {"genesis": "boot"},
            "hooks": {},
        }
        compact_out = compact.generate(ctx, arch, "/tmp")
        standard_out = standard.generate(ctx, arch, "/tmp")
        assert len(compact_out) <= len(standard_out)

    def test_fixed_stages_never_compressible(self):
        assert not IdentityStage().compressible
        assert not CriticalStage().compressible
        assert not ActionStage().compressible

    def test_compressible_stages_default_true(self):
        assert OrientationStage().compressible
        assert EnvironmentStage().compressible
        assert ArchitectureStage().compressible
        assert SessionsStage().compressible

    def test_metadata_footer_present(self):
        pipeline = default_pipeline()
        result = pipeline.generate({}, {}, "/tmp")
        assert "<!-- briefing v" in result
        assert "tokens" in result
        assert "focus:" in result

    def test_very_tight_budget_still_has_identity(self):
        pipeline = default_pipeline(token_budget=100)
        result = pipeline.generate({}, {}, "/tmp")
        assert "# " in result
        assert "No critical" in result
