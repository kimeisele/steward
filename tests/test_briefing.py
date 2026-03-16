"""Tests for briefing — cockpit display from living system state."""

from steward.briefing import (
    _collect_critical,
    _generate_orientation,
    generate_briefing,
    write_claude_md,
)


class TestGenerateBriefing:
    def test_returns_string_with_header(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert isinstance(result, str)
        assert "#" in result

    def test_includes_auto_generated_marker(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "AUTO-GENERATED" in result

    def test_includes_north_star(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "execute tasks" in result or "north_star" in result.lower()

    def test_includes_architecture(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "Architecture" in result
        assert "services" in result.lower()

    def test_includes_murali(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "MURALI" in result or "genesis" in result

    def test_includes_phase_info(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "genesis" in result or "MURALI" in result

    def test_empty_project_still_works(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "#" in result
        assert len(result) > 50

    def test_no_critical_when_healthy(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        # Critical section only appears when something is actually wrong
        assert "Critical" not in result or "No critical" in result

    def test_includes_orientation(self):
        """When run from the real repo, auto-generated orientation should be present."""
        result = generate_briefing(cwd=".")
        # The auto-generated orientation should detect key directories
        assert "antahkarana" in result or "cognitive" in result.lower()


class TestGenerateOrientation:
    def test_empty_dir(self, tmp_path):
        """Orientation from empty dir still produces status section."""
        result = _generate_orientation({}, str(tmp_path))
        assert "## Status" in result

    def test_detects_key_dirs(self):
        """In the real repo, key directories should be detected."""
        from steward.context_bridge import collect_architecture_metadata

        arch = collect_architecture_metadata()
        result = _generate_orientation(arch, ".")
        assert "antahkarana" in result
        assert "senses" in result
        assert "tools" in result

    def test_includes_invariants(self):
        from steward.context_bridge import collect_architecture_metadata

        arch = collect_architecture_metadata()
        result = _generate_orientation(arch, ".")
        assert "NORTH_STAR_TEXT" in result
        assert "MahaCompression" in result

    def test_includes_workflow(self):
        result = _generate_orientation({}, ".")
        assert "ruff" in result or "make check" in result


class TestWriteClaudeMd:
    def test_writes_file(self, tmp_path):
        written = write_claude_md(str(tmp_path), force=True)
        assert written
        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "AUTO-GENERATED" in content

    def test_rate_limited(self, tmp_path):
        write_claude_md(str(tmp_path), force=True)
        # Second call within rate limit should be skipped
        written = write_claude_md(str(tmp_path), force=False)
        assert not written

    def test_force_bypasses_rate_limit(self, tmp_path):
        write_claude_md(str(tmp_path), force=True)
        written = write_claude_md(str(tmp_path), force=True)
        assert written


class TestCollectCritical:
    def test_healthy_returns_empty(self):
        ctx = {"health": {"value": 0.9}, "immune": {}, "federation": {}, "senses": {}}
        assert _collect_critical(ctx) == []

    def test_low_health_triggers_critical(self):
        ctx = {"health": {"value": 0.3, "guna": "tamas"}, "immune": {}, "federation": {}, "senses": {}}
        critical = _collect_critical(ctx)
        assert any("CRITICAL" in c for c in critical)

    def test_tripped_breaker_triggers_critical(self):
        ctx = {"health": {}, "immune": {"breaker": {"tripped": True}}, "federation": {}, "senses": {}}
        critical = _collect_critical(ctx)
        assert any("TRIPPED" in c for c in critical)
