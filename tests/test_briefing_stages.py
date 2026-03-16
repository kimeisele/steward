"""Tests for briefing_stages — composable pipeline for CLAUDE.md generation."""

from steward.briefing_stages import (
    BUDGET_COMPACT,
    BUDGET_FULL,
    BUDGET_STANDARD,
    BUDGET_UNLIMITED,
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
        """Stages with should_run=False produce no output."""
        pipeline = BriefingPipeline()
        pipeline.register(StatusStage())
        # Empty ctx → StatusStage.should_run returns False
        result = pipeline.generate({}, {}, "/tmp")
        assert "## Status" not in result

    def test_stage_gate_runs(self):
        """Stages with should_run=True produce output."""
        pipeline = BriefingPipeline()
        pipeline.register(StatusStage())
        ctx = {"health": {"value": 0.9, "guna": "sattva"}}
        result = pipeline.generate(ctx, {}, "/tmp")
        assert "## Status" in result
        assert "Health: 0.9" in result


class TestIdentityStage:
    def test_includes_project_name(self):
        stage = IdentityStage()
        parts: list[str] = []
        ctx = {"project": {"name": "myproject"}}
        stage.enrich(parts, ctx, {}, "/tmp")
        assert any("myproject" in p for p in parts)

    def test_includes_north_star(self):
        stage = IdentityStage()
        parts: list[str] = []
        arch = {"north_star": "execute tasks with minimal tokens"}
        stage.enrich(parts, {}, arch, "/tmp")
        assert any("execute tasks" in p for p in parts)


class TestCriticalStage:
    def test_no_critical_shows_healthy(self):
        stage = CriticalStage()
        parts: list[str] = []
        stage.enrich(parts, {}, {}, "/tmp")
        assert any("No critical" in p for p in parts)

    def test_low_health_shows_critical(self):
        stage = CriticalStage()
        parts: list[str] = []
        ctx = {"health": {"value": 0.3, "guna": "tamas"}, "immune": {}, "federation": {}, "senses": {}}
        stage.enrich(parts, ctx, {}, "/tmp")
        assert any("CRITICAL" in p for p in parts)


class TestActionStage:
    def test_skips_when_no_issues(self):
        stage = ActionStage()
        assert not stage.should_run({}, {})

    def test_shows_issues(self):
        stage = ActionStage()
        parts: list[str] = []
        ctx = {"issues": [{"number": 42, "title": "Fix bug"}]}
        stage.enrich(parts, ctx, {}, "/tmp")
        assert any("#42" in p for p in parts)


class TestGapAwarenessStage:
    def test_skips_when_no_gaps(self):
        stage = GapAwarenessStage()
        assert not stage.should_run({}, {})

    def test_shows_gaps(self):
        stage = GapAwarenessStage()
        parts: list[str] = []
        ctx = {
            "gaps": {
                "active": [{"category": "tool", "description": "missing linter"}],
                "stats": {"total_tracked": 5, "resolved": 3},
            }
        }
        stage.enrich(parts, ctx, {}, "/tmp")
        assert any("Gap Awareness" in p for p in parts)
        assert any("missing linter" in p for p in parts)


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
        stage.enrich(parts, {}, {}, str(tmp_path))
        assert any("peer-alpha" in p for p in parts)
        assert any("scaling bottleneck" in p for p in parts)

    def test_empty_inbox_produces_nothing(self, tmp_path):
        import json

        fed_dir = tmp_path / "data" / "federation"
        fed_dir.mkdir(parents=True)
        (fed_dir / "nadi_inbox.json").write_text(json.dumps([]))

        stage = FederationInsightStage()
        parts: list[str] = []
        stage.enrich(parts, {}, {}, str(tmp_path))
        assert len(parts) == 0


class TestToolboxStage:
    def test_skips_when_no_tools(self):
        stage = ToolboxStage()
        assert not stage.should_run({}, {})

    def test_shows_tools(self):
        stage = ToolboxStage()
        parts: list[str] = []
        arch = {"tools": [{"name": "synthesize_briefing", "description": "Generate briefing."}]}
        stage.enrich(parts, {}, arch, "/tmp")
        assert any("synthesize_briefing" in p for p in parts)


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
        stage.enrich(parts, {}, arch, "/tmp")
        assert any("2 services" in p for p in parts)
        assert any("MURALI" in p for p in parts)


class TestSessionsStage:
    def test_skips_when_no_sessions(self):
        stage = SessionsStage()
        assert not stage.should_run({}, {})

    def test_shows_stats(self):
        stage = SessionsStage()
        parts: list[str] = []
        ctx = {"sessions": {"stats": {"total": 10, "success_rate": 0.8}}}
        stage.enrich(parts, ctx, {}, "/tmp")
        assert any("10 total" in p for p in parts)


class TestTokenBudget:
    """Token budget system — the slider that controls output length."""

    def test_estimate_tokens(self):
        assert _estimate_tokens("hello world") == max(1, len("hello world") // 4)
        assert _estimate_tokens("") == 1  # floor of 1

    def test_budget_default_is_standard(self):
        pipeline = default_pipeline()
        assert pipeline.token_budget == BUDGET_STANDARD

    def test_budget_custom(self):
        pipeline = default_pipeline(token_budget=1000)
        assert pipeline.token_budget == 1000

    def test_compact_smaller_than_standard(self):
        """Compact mode produces fewer tokens than standard."""
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

    def test_unlimited_never_truncates(self):
        """Unlimited budget includes everything."""
        pipeline = default_pipeline(token_budget=BUDGET_UNLIMITED)
        ctx = {
            "health": {"value": 0.9, "guna": "sattva"},
            "sessions": {"stats": {"total": 5, "success_rate": 0.8}},
        }
        arch = {
            "services": {"SVC_A": "a"},
            "kshetra": [],
            "phases": {"genesis": "boot"},
            "hooks": {},
        }
        result = pipeline.generate(ctx, arch, "/tmp")
        assert "## Architecture" in result
        assert "Sessions:" in result

    def test_fixed_stages_never_truncated(self):
        """Identity, Critical, Action are never compressible."""
        assert not IdentityStage().compressible
        assert not CriticalStage().compressible
        assert not ActionStage().compressible

    def test_compressible_stages_default_true(self):
        """Most stages are compressible by default."""
        assert OrientationStage().compressible
        assert EnvironmentStage().compressible
        assert ArchitectureStage().compressible
        assert SessionsStage().compressible

    def test_metadata_footer_present(self):
        """Output always ends with metadata comment."""
        pipeline = default_pipeline()
        result = pipeline.generate({}, {}, "/tmp")
        assert "<!-- briefing v" in result
        assert "tokens" in result
        assert "budget:" in result

    def test_budget_label_compact(self):
        pipeline = default_pipeline(token_budget=BUDGET_COMPACT)
        assert pipeline._budget_label() == "compact"

    def test_budget_label_standard(self):
        pipeline = default_pipeline(token_budget=BUDGET_STANDARD)
        assert pipeline._budget_label() == "standard"

    def test_budget_label_full(self):
        pipeline = default_pipeline(token_budget=BUDGET_FULL)
        assert pipeline._budget_label() == "full"

    def test_budget_label_unlimited(self):
        pipeline = default_pipeline(token_budget=BUDGET_UNLIMITED)
        assert pipeline._budget_label() == "unlimited"

    def test_very_tight_budget_still_has_identity(self):
        """Even at extremely tight budget, identity + critical always present."""
        pipeline = default_pipeline(token_budget=100)
        result = pipeline.generate({}, {}, "/tmp")
        assert "# " in result  # Identity header
        assert "No critical" in result  # Critical stage
