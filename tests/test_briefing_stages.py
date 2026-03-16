"""Tests for briefing_stages — composable pipeline for CLAUDE.md generation."""

from steward.briefing_stages import (
    ActionStage,
    ArchitectureStage,
    BriefingPipeline,
    BriefingStage,
    CriticalStage,
    EnvironmentStage,
    FederationInsightStage,
    GapAwarenessStage,
    IdentityStage,
    SessionsStage,
    StatusStage,
    ToolboxStage,
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
