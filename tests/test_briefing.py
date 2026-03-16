"""Tests for briefing — cockpit display from living system state."""

from steward.briefing import (
    _collect_critical,
    _load_orientation,
    generate_briefing,
    write_claude_md,
)


class TestGenerateBriefing:
    def test_returns_string_with_header(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert isinstance(result, str)
        assert "#" in result

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
        assert "Critical" not in result or "No critical" in result

    def test_includes_orientation_from_conventions(self):
        """When run from the real repo, orientation block should be present."""
        result = generate_briefing(cwd=".")
        # The conventions.md in .steward/ has architecture explanation
        assert "Antahkarana" in result or "cognitive" in result.lower()


class TestWriteClaudeMd:
    def test_writes_file(self, tmp_path):
        written = write_claude_md(str(tmp_path), force=True)
        assert written
        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()

    def test_hash_dedup(self, tmp_path):
        write_claude_md(str(tmp_path), force=True)
        # Second call with same content should be skipped
        written = write_claude_md(str(tmp_path), force=False)
        assert not written

    def test_force_bypasses_dedup(self, tmp_path):
        write_claude_md(str(tmp_path), force=True)
        written = write_claude_md(str(tmp_path), force=True)
        assert written


class TestLoadOrientation:
    def test_no_file_returns_empty(self, tmp_path):
        assert _load_orientation(str(tmp_path)) == ""

    def test_loads_content_skipping_file_comments(self, tmp_path):
        steward_dir = tmp_path / ".steward"
        steward_dir.mkdir()
        (steward_dir / "conventions.md").write_text(
            "# File-level comment\n# Another comment\n\n## What this is\nSteward is an agent.\n"
        )
        result = _load_orientation(str(tmp_path))
        assert "## What this is" in result
        assert "Steward is an agent" in result

    def test_preserves_markdown_structure(self, tmp_path):
        steward_dir = tmp_path / ".steward"
        steward_dir.mkdir()
        content = "# Top comment\n\n## Section One\nContent here.\n\n## Section Two\nMore content.\n"
        (steward_dir / "conventions.md").write_text(content)
        result = _load_orientation(str(tmp_path))
        assert "## Section One" in result
        assert "## Section Two" in result

    def test_empty_file_returns_empty(self, tmp_path):
        steward_dir = tmp_path / ".steward"
        steward_dir.mkdir()
        (steward_dir / "conventions.md").write_text("")
        assert _load_orientation(str(tmp_path)) == ""


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
