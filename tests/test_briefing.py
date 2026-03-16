"""Tests for briefing — cockpit display from living system state."""

from steward.briefing import (
    _collect_critical,
    _derive_conventions,
    _load_static_rules,
    generate_briefing,
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

    def test_includes_service_docstrings(self, tmp_path):
        """Services should show descriptions, not just names."""
        result = generate_briefing(cwd=str(tmp_path))
        # At least one service should have its docstring visible
        assert "ToolRegistry" in result or "tool lookup" in result.lower()

    def test_includes_murali(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "MURALI" in result or "genesis" in result

    def test_includes_phase_descriptions(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "Discover" in result or "Govern" in result

    def test_empty_project_still_works(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        assert "#" in result
        assert len(result) > 50

    def test_no_critical_when_healthy(self, tmp_path):
        result = generate_briefing(cwd=str(tmp_path))
        # CRITICAL section only appears when something is actually wrong
        assert "CRITICAL" not in result or "Health" in result


class TestDeriveConventions:
    def test_empty_dir_returns_empty(self, tmp_path):
        assert _derive_conventions(str(tmp_path)) == []

    def test_reads_ruff_config(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[tool.ruff]\nline-length = 100\ntarget-version = "py312"\n')
        rules = _derive_conventions(str(tmp_path))
        assert any("ruff" in r for r in rules)
        assert any("100" in r for r in rules)

    def test_reads_pytest_config(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\ntimeout = 30\n")
        rules = _derive_conventions(str(tmp_path))
        assert any("pytest" in r for r in rules)


class TestLoadStaticRules:
    def test_no_file_returns_empty(self, tmp_path):
        assert _load_static_rules(str(tmp_path)) == []

    def test_loads_conventions(self, tmp_path):
        steward_dir = tmp_path / ".steward"
        steward_dir.mkdir()
        (steward_dir / "conventions.md").write_text("# Header comment\n- Rule one\n- Rule two\n")
        rules = _load_static_rules(str(tmp_path))
        assert len(rules) == 2
        assert "Rule one" in rules
        assert "Rule two" in rules

    def test_skips_comments_and_blanks(self, tmp_path):
        steward_dir = tmp_path / ".steward"
        steward_dir.mkdir()
        (steward_dir / "conventions.md").write_text("# Comment\n\n- Actual rule\n\n# Another comment\n")
        rules = _load_static_rules(str(tmp_path))
        assert len(rules) == 1
        assert "Actual rule" in rules


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
