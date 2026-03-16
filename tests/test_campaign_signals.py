"""Tests for campaign_signals — success signal evaluation."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from steward.campaign_signals import (
    CampaignHealth,
    SignalResult,
    _eval_active_missions_at_most,
    _eval_ci_green,
    _eval_federation_healthy,
    _eval_immune_clean,
    _load_campaign,
    evaluate,
)

# ── _load_campaign ────────────────────────────────────────────────────


class TestLoadCampaign:
    def setup_method(self):
        # Clear cache between tests
        import steward.campaign_signals as mod

        mod._campaign_cache = None

    def test_loads_from_file(self, tmp_path):
        campaigns_dir = tmp_path / "campaigns"
        campaigns_dir.mkdir()
        campaign = {
            "campaigns": [
                {
                    "id": "test-campaign",
                    "north_star": "test",
                    "success_signals": [{"kind": "ci_green", "target": True}],
                }
            ]
        }
        (campaigns_dir / "default.json").write_text(json.dumps(campaign))

        result = _load_campaign(str(tmp_path))
        assert result["id"] == "test-campaign"
        assert len(result["success_signals"]) == 1

    def test_missing_file_returns_empty(self, tmp_path):
        result = _load_campaign(str(tmp_path))
        assert result == {}

    def test_caches_result(self, tmp_path):
        campaigns_dir = tmp_path / "campaigns"
        campaigns_dir.mkdir()
        (campaigns_dir / "default.json").write_text(json.dumps({"campaigns": [{"id": "cached"}]}))
        first = _load_campaign(str(tmp_path))
        # Delete file — should still return cached
        (campaigns_dir / "default.json").unlink()
        second = _load_campaign(str(tmp_path))
        assert first is second

    def test_malformed_json_returns_empty(self, tmp_path):
        campaigns_dir = tmp_path / "campaigns"
        campaigns_dir.mkdir()
        (campaigns_dir / "default.json").write_text("not json")
        result = _load_campaign(str(tmp_path))
        assert result == {}


# ── Individual signal evaluators ──────────────────────────────────────


class TestFederationHealthy:
    def test_no_reaper_is_healthy(self):
        with patch("steward.campaign_signals.ServiceRegistry.get", return_value=None):
            actual, met = _eval_federation_healthy(True, None)
        assert met is True

    def test_no_peers_is_healthy(self):
        reaper = MagicMock()
        reaper.alive_peers.return_value = []
        reaper.suspect_peers.return_value = []
        reaper.dead_peers.return_value = []
        with patch("steward.campaign_signals.ServiceRegistry.get", return_value=reaper):
            actual, met = _eval_federation_healthy(True, None)
        assert met is True

    def test_dead_peers_is_unhealthy(self):
        reaper = MagicMock()
        reaper.alive_peers.return_value = [MagicMock()]
        reaper.suspect_peers.return_value = []
        reaper.dead_peers.return_value = [MagicMock()]
        with patch("steward.campaign_signals.ServiceRegistry.get", return_value=reaper):
            actual, met = _eval_federation_healthy(True, None)
        assert met is False
        assert actual["dead"] == 1
        assert actual["alive"] == 1

    def test_all_alive_is_healthy(self):
        reaper = MagicMock()
        reaper.alive_peers.return_value = [MagicMock(), MagicMock()]
        reaper.suspect_peers.return_value = []
        reaper.dead_peers.return_value = []
        with patch("steward.campaign_signals.ServiceRegistry.get", return_value=reaper):
            actual, met = _eval_federation_healthy(True, None)
        assert met is True


class TestImmuneClean:
    def test_no_senses_is_clean(self):
        actual, met = _eval_immune_clean(True, None)
        assert met is True

    def test_low_pain_is_clean(self):
        senses = MagicMock()
        aggregate = MagicMock()
        aggregate.total_pain = 0.3
        senses.perceive_all.return_value = aggregate
        actual, met = _eval_immune_clean(True, senses)
        assert met is True

    def test_high_pain_is_not_clean(self):
        senses = MagicMock()
        aggregate = MagicMock()
        aggregate.total_pain = 0.9
        senses.perceive_all.return_value = aggregate
        actual, met = _eval_immune_clean(True, senses)
        assert met is False


class TestCiGreen:
    def test_no_senses_is_green(self):
        actual, met = _eval_ci_green(True, None)
        assert met is True

    def test_passing_ci_is_green(self):
        senses = MagicMock()
        perception = MagicMock()
        perception.data = {"ci_status": {"conclusion": "success", "name": "CI"}}
        senses.senses = {MagicMock(): MagicMock()}
        # Mock the git sense
        git_sense = MagicMock()
        git_sense.perceive.return_value = perception
        from vibe_core.mahamantra.protocols._sense import Jnanendriya

        senses.senses = {Jnanendriya.SROTRA: git_sense}
        actual, met = _eval_ci_green(True, senses)
        assert met is True

    def test_failing_ci_is_red(self):
        senses = MagicMock()
        perception = MagicMock()
        perception.data = {"ci_status": {"conclusion": "failure", "name": "CI"}}
        git_sense = MagicMock()
        git_sense.perceive.return_value = perception
        from vibe_core.mahamantra.protocols._sense import Jnanendriya

        senses.senses = {Jnanendriya.SROTRA: git_sense}
        actual, met = _eval_ci_green(True, senses)
        assert met is False


class TestActiveMissionsAtMost:
    def test_no_task_manager_is_ok(self):
        with patch("steward.campaign_signals.ServiceRegistry.get", return_value=None):
            actual, met = _eval_active_missions_at_most(3, None)
        assert met is True

    def test_under_limit_is_ok(self):
        task_mgr = MagicMock()
        task_mgr.list_tasks.return_value = [MagicMock()]
        with patch("steward.campaign_signals.ServiceRegistry.get", return_value=task_mgr):
            actual, met = _eval_active_missions_at_most(3, None)
        assert met is True

    def test_over_limit_is_not_ok(self):
        task_mgr = MagicMock()
        task_mgr.list_tasks.return_value = [MagicMock(), MagicMock(), MagicMock()]
        with patch("steward.campaign_signals.ServiceRegistry.get", return_value=task_mgr):
            actual, met = _eval_active_missions_at_most(3, None)
        # 3+3=6 (called twice: PENDING + IN_PROGRESS), > 3
        assert met is False


# ── CampaignHealth ────────────────────────────────────────────────────


class TestCampaignHealth:
    def test_ci_green_from_signals(self):
        health = CampaignHealth(
            signals=(SignalResult(kind="ci_green", target=True, actual=True, met=True),),
        )
        assert health.ci_green is True

    def test_ci_red_from_signals(self):
        health = CampaignHealth(
            signals=(SignalResult(kind="ci_green", target=True, actual=False, met=False),),
        )
        assert health.ci_green is False

    def test_no_ci_signal_defaults_green(self):
        health = CampaignHealth(
            signals=(SignalResult(kind="federation_healthy", target=True, actual=True, met=True),),
        )
        assert health.ci_green is True

    def test_all_met(self):
        health = CampaignHealth(
            signals=(
                SignalResult(kind="ci_green", target=True, actual=True, met=True),
                SignalResult(kind="federation_healthy", target=True, actual=True, met=True),
            ),
        )
        assert health.all_met is True

    def test_failing_kinds(self):
        health = CampaignHealth(
            signals=(
                SignalResult(kind="ci_green", target=True, actual=False, met=False),
                SignalResult(kind="federation_healthy", target=True, actual=True, met=True),
            ),
        )
        assert health.failing_kinds == ("ci_green",)

    def test_priority_boost_for_failing_signal(self):
        health = CampaignHealth(
            signals=(SignalResult(kind="federation_healthy", target=True, actual=False, met=False),),
        )
        # federation_health intent should get boosted
        assert health.priority_boost("federation_health") == 20
        # unrelated intent should not
        assert health.priority_boost("update_deps") == 0

    def test_priority_boost_stacks(self):
        health = CampaignHealth(
            signals=(
                SignalResult(kind="federation_healthy", target=True, actual=False, met=False),
                SignalResult(kind="immune_clean", target=True, actual=False, met=False),
            ),
        )
        # heal_repo maps to both federation_healthy AND immune_clean
        assert health.priority_boost("heal_repo") == 40

    def test_empty_health_is_green(self):
        health = CampaignHealth()
        assert health.ci_green is True
        assert health.all_met is True
        assert health.failing_kinds == ()


# ── Full evaluate() ───────────────────────────────────────────────────


class TestEvaluate:
    def setup_method(self):
        import steward.campaign_signals as mod

        mod._campaign_cache = None

    def test_evaluate_with_real_campaign_file(self, tmp_path):
        campaigns_dir = tmp_path / "campaigns"
        campaigns_dir.mkdir()
        campaign = {
            "campaigns": [
                {
                    "id": "test",
                    "success_signals": [
                        {"kind": "ci_green", "target": True},
                        {"kind": "federation_healthy", "target": True},
                    ],
                }
            ]
        }
        (campaigns_dir / "default.json").write_text(json.dumps(campaign))

        with patch("steward.campaign_signals.ServiceRegistry.get", return_value=None):
            health = evaluate(str(tmp_path), senses=None)

        assert health.campaign_id == "test"
        assert len(health.signals) == 2
        # No senses, no reaper → both vacuously True
        assert health.all_met is True

    def test_evaluate_no_campaign_file(self, tmp_path):
        health = evaluate(str(tmp_path), senses=None)
        assert health.signals == ()
        assert health.all_met is True

    def test_evaluate_unknown_signal_kind_skipped(self, tmp_path):
        import steward.campaign_signals as mod

        mod._campaign_cache = None
        campaigns_dir = tmp_path / "campaigns"
        campaigns_dir.mkdir()
        campaign = {
            "campaigns": [
                {
                    "id": "test",
                    "success_signals": [
                        {"kind": "nonexistent_signal", "target": True},
                        {"kind": "ci_green", "target": True},
                    ],
                }
            ]
        }
        (campaigns_dir / "default.json").write_text(json.dumps(campaign))

        health = evaluate(str(tmp_path), senses=None)
        assert len(health.signals) == 1  # Only ci_green, nonexistent skipped
        assert health.signals[0].kind == "ci_green"
