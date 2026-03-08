"""Tests for the 5 Jnanendriyas — Steward's sense system.

Each sense implements SenseProtocol from steward-protocol.
All perception is deterministic (zero LLM).
"""

import tempfile
from pathlib import Path

from steward.senses.code_sense import CodeSense
from steward.senses.coordinator import SenseCoordinator
from steward.senses.git_sense import GitSense
from steward.senses.health_sense import HealthSense
from steward.senses.project_sense import ProjectSense
from steward.senses.test_sense import TestSense
from vibe_core.mahamantra.protocols._sense import (
    AggregatePerception,
    Jnanendriya,
    SensePerception,
    Tanmatra,
)

# ── GitSense (SROTRA) ─────────────────────────────────────────────────


class TestGitSense:
    """Test SROTRA — git perception."""

    def test_jnanendriya_is_srotra(self):
        sense = GitSense(cwd=".")
        assert sense.jnanendriya == Jnanendriya.SROTRA

    def test_tanmatra_is_sabda(self):
        sense = GitSense(cwd=".")
        assert sense.tanmatra == Tanmatra.SABDA

    def test_active_in_git_repo(self):
        sense = GitSense(cwd=".")
        assert sense.is_active is True

    def test_inactive_outside_git(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sense = GitSense(cwd=tmpdir)
            assert sense.is_active is False

    def test_perceive_in_git_repo(self):
        sense = GitSense(cwd=".")
        perception = sense.perceive()
        assert isinstance(perception, SensePerception)
        assert perception.sense == Jnanendriya.SROTRA
        assert perception.tanmatra == Tanmatra.SABDA
        assert perception.data["is_git"] is True
        assert "branch" in perception.data
        assert isinstance(perception.data["dirty_count"], int)
        assert isinstance(perception.data["recent_commits"], list)

    def test_perceive_outside_git(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sense = GitSense(cwd=tmpdir)
            perception = sense.perceive()
            assert perception.data["is_git"] is False
            assert perception.quality == "tamas"

    def test_pain_level_returns_float(self):
        sense = GitSense(cwd=".")
        pain = sense.get_pain_level()
        assert isinstance(pain, float)
        assert 0.0 <= pain <= 1.0

    def test_pain_zero_outside_git(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sense = GitSense(cwd=tmpdir)
            assert sense.get_pain_level() == 0.0


# ── ProjectSense (TVAK) ───────────────────────────────────────────────


class TestProjectSense:
    """Test TVAK — project structure perception."""

    def test_jnanendriya_is_tvak(self):
        sense = ProjectSense(cwd=".")
        assert sense.jnanendriya == Jnanendriya.TVAK

    def test_tanmatra_is_sparsa(self):
        sense = ProjectSense(cwd=".")
        assert sense.tanmatra == Tanmatra.SPARSA

    def test_perceive_python_project(self):
        sense = ProjectSense(cwd=".")
        perception = sense.perceive()
        assert perception.sense == Jnanendriya.TVAK
        assert "python" in perception.data["languages"]
        assert perception.data["primary_language"] == "python"
        assert perception.data["has_tests"] is True

    def test_perceive_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sense = ProjectSense(cwd=tmpdir)
            perception = sense.perceive()
            assert perception.data["primary_language"] == "unknown"
            assert perception.quality == "tamas"

    def test_key_dirs_detected(self):
        sense = ProjectSense(cwd=".")
        perception = sense.perceive()
        dirs = perception.data["key_dirs"]
        assert "tests" in dirs

    def test_config_files_found(self):
        sense = ProjectSense(cwd=".")
        perception = sense.perceive()
        configs = perception.data["config_files"]
        assert "pyproject.toml" in configs

    def test_pain_empty_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sense = ProjectSense(cwd=tmpdir)
            pain = sense.get_pain_level()
            assert pain > 0.0  # Unknown project = pain


# ── CodeSense (CAKSU) ──────────────────────────────────────────────────


class TestCodeSense:
    """Test CAKSU — code structure perception."""

    def test_jnanendriya_is_caksu(self):
        sense = CodeSense(cwd=".")
        assert sense.jnanendriya == Jnanendriya.CAKSU

    def test_tanmatra_is_rupa(self):
        sense = CodeSense(cwd=".")
        assert sense.tanmatra == Tanmatra.RUPA

    def test_perceive_python_codebase(self):
        sense = CodeSense(cwd=".")
        perception = sense.perceive()
        assert perception.sense == Jnanendriya.CAKSU
        assert perception.data["python_files"] > 0
        assert perception.data["total_classes"] > 0
        assert perception.data["total_functions"] > 0
        assert "steward" in perception.data["packages"]

    def test_perceive_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sense = CodeSense(cwd=tmpdir)
            perception = sense.perceive()
            assert perception.data["python_files"] == 0
            assert perception.data["total_classes"] == 0

    def test_syntax_errors_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad.py"
            bad_file.write_text("def broken(\n")
            sense = CodeSense(cwd=tmpdir)
            perception = sense.perceive()
            assert len(perception.data["syntax_errors"]) > 0

    def test_large_files_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            large = Path(tmpdir) / "big.py"
            large.write_text("x = 1\n" * 10_000)
            sense = CodeSense(cwd=tmpdir)
            perception = sense.perceive()
            assert len(perception.data["large_files"]) > 0


# ── TestSense (JIHVA) ──────────────────────────────────────────────────


class TestTestSense:
    """Test JIHVA — test quality perception."""

    def test_jnanendriya_is_jihva(self):
        sense = TestSense(cwd=".")
        assert sense.jnanendriya == Jnanendriya.JIHVA

    def test_tanmatra_is_rasa(self):
        sense = TestSense(cwd=".")
        assert sense.tanmatra == Tanmatra.RASA

    def test_perceive_pytest_project(self):
        sense = TestSense(cwd=".")
        perception = sense.perceive()
        assert perception.sense == Jnanendriya.JIHVA
        assert perception.data["framework"] == "pytest"
        assert perception.data["test_files"] > 0

    def test_perceive_no_tests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sense = TestSense(cwd=tmpdir)
            perception = sense.perceive()
            assert perception.data["test_files"] == 0
            assert perception.quality == "tamas"
            assert perception.intensity > 0.5  # No tests = high pain

    def test_pytest_config_detected(self):
        sense = TestSense(cwd=".")
        perception = sense.perceive()
        assert "pytest" in perception.data.get("pytest_config", "") or perception.data["framework"] == "pytest"

    def test_pain_no_tests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sense = TestSense(cwd=tmpdir)
            pain = sense.get_pain_level()
            assert pain > 0.0  # No tests = pain


# ── HealthSense (GHRANA) ───────────────────────────────────────────────


class TestHealthSense:
    """Test GHRANA — code health perception."""

    def test_jnanendriya_is_ghrana(self):
        sense = HealthSense(cwd=".")
        assert sense.jnanendriya == Jnanendriya.GHRANA

    def test_tanmatra_is_gandha(self):
        sense = HealthSense(cwd=".")
        assert sense.tanmatra == Tanmatra.GANDHA

    def test_perceive_codebase(self):
        sense = HealthSense(cwd=".")
        perception = sense.perceive()
        assert perception.sense == Jnanendriya.GHRANA
        assert perception.data["file_count"] > 0
        assert perception.data["has_gitignore"] is True

    def test_perceive_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sense = HealthSense(cwd=tmpdir)
            perception = sense.perceive()
            assert perception.data["file_count"] == 0
            assert perception.data["has_gitignore"] is False

    def test_large_files_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a large Python file
            large = Path(tmpdir) / "big.py"
            large.write_text("x = 1\n" * 10_000)  # >50KB
            sense = HealthSense(cwd=tmpdir)
            perception = sense.perceive()
            assert perception.data["large_file_count"] > 0
            assert perception.quality in ("rajas", "tamas")


# ── SenseCoordinator ──────────────────────────────────────────────────


class TestSenseCoordinator:
    """Test SenseCoordinator — environmental Manas."""

    def test_boots_5_senses(self):
        coordinator = SenseCoordinator(cwd=".")
        assert len(coordinator.senses) == 5
        assert Jnanendriya.SROTRA in coordinator.senses
        assert Jnanendriya.TVAK in coordinator.senses
        assert Jnanendriya.CAKSU in coordinator.senses
        assert Jnanendriya.JIHVA in coordinator.senses
        assert Jnanendriya.GHRANA in coordinator.senses

    def test_perceive_all_returns_aggregate(self):
        coordinator = SenseCoordinator(cwd=".")
        agg = coordinator.perceive_all()
        assert isinstance(agg, AggregatePerception)
        assert len(agg.perceptions) == 5

    def test_total_pain_returns_float(self):
        coordinator = SenseCoordinator(cwd=".")
        pain = coordinator.get_total_pain()
        assert isinstance(pain, float)
        assert 0.0 <= pain <= 1.0

    def test_format_for_prompt_nonempty(self):
        coordinator = SenseCoordinator(cwd=".")
        prompt = coordinator.format_for_prompt()
        assert "## Environment Perception" in prompt
        assert "Git:" in prompt
        assert "Project:" in prompt
        assert "Code:" in prompt
        assert "Tests:" in prompt

    def test_format_for_prompt_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coordinator = SenseCoordinator(cwd=tmpdir)
            prompt = coordinator.format_for_prompt()
            assert "## Environment Perception" in prompt

    def test_boot_summary(self):
        coordinator = SenseCoordinator(cwd=".")
        summary = coordinator.boot_summary()
        assert len(summary) == 5
        for key, data in summary.items():
            assert "active" in data
            assert "pain" in data
            assert "quality" in data

    def test_register_custom_sense(self):
        coordinator = SenseCoordinator(cwd=".")
        initial_count = len(coordinator.senses)
        # Can't easily create a mock sense without the protocol,
        # but verify register_sense accepts a GitSense
        git = GitSense(cwd=".")
        coordinator.register_sense(git)  # re-register (replaces)
        assert len(coordinator.senses) == initial_count  # same count (replaced)

    def test_perceive_all_handles_inactive_sense(self):
        """Inactive senses (outside git) are skipped gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            coordinator = SenseCoordinator(cwd=tmpdir)
            agg = coordinator.perceive_all()
            # GitSense is inactive but others should still work
            assert len(agg.perceptions) >= 4  # At least 4 senses active

    def test_dominant_sense_identified(self):
        coordinator = SenseCoordinator(cwd=".")
        agg = coordinator.perceive_all()
        # Should have a dominant sense (whichever screams loudest)
        if agg.perceptions:
            assert agg.dominant_sense is not None


# ── Perception Data Contract ──────────────────────────────────────────


class TestPerceptionDataContract:
    """Verify that all sense perceptions have valid data shapes."""

    def test_all_perceptions_have_valid_intensity(self):
        coordinator = SenseCoordinator(cwd=".")
        agg = coordinator.perceive_all()
        for sense, perception in agg.perceptions.items():
            assert 0.0 <= perception.intensity <= 1.0, (
                f"{sense}: intensity {perception.intensity} out of range"
            )

    def test_all_perceptions_have_valid_quality(self):
        coordinator = SenseCoordinator(cwd=".")
        agg = coordinator.perceive_all()
        for sense, perception in agg.perceptions.items():
            assert perception.quality in ("sattva", "rajas", "tamas"), (
                f"{sense}: invalid quality {perception.quality}"
            )

    def test_all_perceptions_have_data_dict(self):
        coordinator = SenseCoordinator(cwd=".")
        agg = coordinator.perceive_all()
        for sense, perception in agg.perceptions.items():
            assert isinstance(perception.data, dict), f"{sense}: data is not dict"
            assert len(perception.data) > 0, f"{sense}: data is empty"

    def test_perception_tanmatra_matches_sense(self):
        """Each perception's tanmatra must match its jnanendriya."""
        expected = {
            Jnanendriya.SROTRA: Tanmatra.SABDA,
            Jnanendriya.TVAK: Tanmatra.SPARSA,
            Jnanendriya.CAKSU: Tanmatra.RUPA,
            Jnanendriya.JIHVA: Tanmatra.RASA,
            Jnanendriya.GHRANA: Tanmatra.GANDHA,
        }
        coordinator = SenseCoordinator(cwd=".")
        agg = coordinator.perceive_all()
        for sense, perception in agg.perceptions.items():
            assert perception.tanmatra == expected[sense], (
                f"{sense}: tanmatra {perception.tanmatra} != expected {expected[sense]}"
            )
