"""Tests for briefing — cockpit display from living system state."""

from steward.briefing import generate_briefing


class TestGenerateBriefing:
    def test_returns_string_with_header(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert isinstance(result, str)
        assert "#" in result

    def test_includes_seed(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "Seed" in result or "134340638" in result

    def test_includes_architecture(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "Architecture" in result
        assert "services" in result.lower()

    def test_includes_murali(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "MURALI" in result or "genesis" in result

    def test_empty_project_still_works(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "#" in result
        assert len(result) > 50

    def test_critical_section_exists(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "critical" in result.lower() or "No critical" in result
