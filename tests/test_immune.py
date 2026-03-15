"""Tests for StewardImmune — structural self-healing."""

from __future__ import annotations

from unittest.mock import MagicMock

from steward.immune import (
    CytokineBreaker,
    DiagnosisResult,
    StewardImmune,
    _extract_file_path,
    _match_pattern,
)


class TestCytokineBreaker:
    def test_not_tripped_initially(self):
        b = CytokineBreaker()
        assert not b.is_open()

    def test_trips_after_max_rollbacks(self):
        b = CytokineBreaker(max_consecutive=2)
        b.record_rollback()
        assert not b.is_open()
        b.record_rollback()
        assert b.is_open()

    def test_success_resets_consecutive(self):
        b = CytokineBreaker(max_consecutive=3)
        b.record_rollback()
        b.record_rollback()
        b.record_success()
        assert b.consecutive_rollbacks == 0
        b.record_rollback()
        assert not b.is_open()  # Only 1, needs 3

    def test_cooldown_expires(self):
        b = CytokineBreaker(max_consecutive=1, cooldown_s=0.01)
        b.record_rollback()
        assert b.is_open()
        import time

        time.sleep(0.02)
        assert not b.is_open()  # Cooldown expired


class TestPatternMatching:
    def test_matches_known_patterns(self):
        assert _match_pattern("except Exception: pass in foo.py") == "silent_exception"
        assert _match_pattern("LCOM4=5 in agent.py") == "god_class"
        assert _match_pattern("circular_import detected") == "circular_import"
        assert _match_pattern("no_ci found") == "no_ci"

    def test_no_match_returns_none(self):
        assert _match_pattern("something completely unknown xyz") is None

    def test_case_insensitive(self):
        assert _match_pattern("EXCEPT EXCEPTION in code") == "silent_exception"


class TestExtractFilePath:
    def test_extracts_existing_file(self):
        # Use a file we know exists
        result = _extract_file_path("Error in steward/immune.py: something")
        assert result is not None
        assert result.name == "immune.py"

    def test_returns_none_for_nonexistent(self):
        result = _extract_file_path("Error in nonexistent_xyz_123.py")
        assert result is None


class TestStewardImmune:
    def test_initializes(self):
        immune = StewardImmune(_cwd=".")
        assert isinstance(immune.stats(), dict)
        assert "heals_attempted" in immune.stats()

    def test_diagnose_known_pattern(self):
        immune = StewardImmune(_cwd=".")
        result = immune.diagnose("except Exception: pass in steward/immune.py")
        assert result.rule_id == "silent_exception"
        assert result.confidence >= 0

    def test_diagnose_unknown_pattern(self):
        immune = StewardImmune(_cwd=".")
        result = immune.diagnose("completely unknown gibberish xyz")
        assert not result.healable

    def test_heal_unhealable_returns_failure(self):
        immune = StewardImmune(_cwd=".")
        diagnosis = DiagnosisResult(
            pattern="unknown",
            rule_id=None,
            file_path=None,
            confidence=0.0,
            healable=False,
        )
        result = immune.heal(diagnosis)
        assert not result.success

    def test_stats_structure(self):
        immune = StewardImmune(_cwd=".")
        stats = immune.stats()
        assert "available" in stats
        assert "breaker" in stats
        assert "success_rate" in stats

    def test_scan_and_heal_respects_breaker(self):
        immune = StewardImmune(_cwd=".")
        immune._breaker.tripped = True
        immune._breaker.tripped_at = __import__("time").time()
        immune._breaker.cooldown_s = 9999

        results = immune.scan_and_heal(["some pattern"])
        assert results == []  # Breaker is open

    def test_with_hebbian(self):
        synaptic = MagicMock()
        synaptic.get_weight = MagicMock(return_value=0.8)

        immune = StewardImmune(_cwd=".", _synaptic=synaptic)
        result = immune.diagnose("LCOM4=6 in steward/agent.py")
        assert result.confidence == 0.8
        synaptic.get_weight.assert_called_with("immune:god_class", "heal")
