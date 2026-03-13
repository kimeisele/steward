"""Tests for Phase 4: DiagnosticSense — structured repo analysis."""

import json

import pytest

from steward.senses.diagnostic_sense import CIStatus, DiagnosticReport, diagnose_repo


class TestDiagnosticReport:
    """DiagnosticReport dataclass behavior."""

    def test_healthy_report(self):
        report = DiagnosticReport(
            repo="test/repo",
            clone_ok=True,
            test_count=42,
            ci_statuses=(CIStatus("CI", "success", "completed"),),
        )
        assert report.is_healthy
        assert report.test_count == 42

    def test_unhealthy_clone_failure(self):
        report = DiagnosticReport(repo="test/repo", clone_ok=False)
        assert not report.is_healthy

    def test_unhealthy_test_collection_error(self):
        report = DiagnosticReport(
            repo="test/repo",
            clone_ok=True,
            test_collection_error="ModuleNotFoundError",
        )
        assert not report.is_healthy

    def test_unhealthy_ci_failure(self):
        report = DiagnosticReport(
            repo="test/repo",
            clone_ok=True,
            ci_statuses=(CIStatus("CI", "failure", "completed"),),
        )
        assert not report.is_healthy

    def test_to_dict(self):
        report = DiagnosticReport(
            repo="test/repo",
            clone_ok=True,
            test_count=10,
            has_federation_descriptor=True,
            peer_capabilities=("code_analysis",),
        )
        d = report.to_dict()
        assert d["repo"] == "test/repo"
        assert d["clone_ok"] is True
        assert d["test_count"] == 10
        assert d["has_federation_descriptor"] is True
        assert d["peer_capabilities"] == ["code_analysis"]
        assert d["is_healthy"] is True

    def test_to_dict_with_ci_statuses(self):
        report = DiagnosticReport(
            repo="test/repo",
            clone_ok=True,
            ci_statuses=(
                CIStatus("CI", "success", "completed"),
                CIStatus("Lint", "failure", "completed"),
            ),
        )
        d = report.to_dict()
        assert len(d["ci_statuses"]) == 2
        assert d["ci_statuses"][0]["workflow"] == "CI"
        assert d["ci_statuses"][1]["conclusion"] == "failure"

    def test_empty_report(self):
        report = DiagnosticReport(repo="empty")
        assert not report.is_healthy
        assert report.test_count == 0
        assert report.ci_statuses == ()
        assert report.errors == ()


class TestDiagnoseRepo:
    """diagnose_repo() integration — tests with non-existent repo."""

    def test_nonexistent_repo_returns_clone_failure(self):
        report = diagnose_repo("/nonexistent/path/to/repo.git", timeout=10)
        assert not report.clone_ok
        assert not report.is_healthy
        assert len(report.errors) > 0

    def test_report_has_repo_field(self):
        report = diagnose_repo("/nonexistent/repo.git", timeout=10)
        assert report.repo == "/nonexistent/repo.git"


class TestCIStatus:
    """CIStatus is a clean frozen data object."""

    def test_ci_status_fields(self):
        ci = CIStatus(workflow="CI", conclusion="success", status="completed")
        assert ci.workflow == "CI"
        assert ci.conclusion == "success"
        assert ci.status == "completed"

    def test_ci_status_frozen(self):
        ci = CIStatus("CI", "success", "completed")
        with pytest.raises(AttributeError):
            ci.conclusion = "failure"


class TestCrossRepoDiagnosticIntent:
    """CROSS_REPO_DIAGNOSTIC intent handler finds degraded peers."""

    def test_intent_exists(self):
        from steward.intents import TaskIntent

        assert TaskIntent.CROSS_REPO_DIAGNOSTIC.value == "cross_repo_diagnostic"

    def test_handler_returns_none_without_reaper(self):
        from steward.intent_handlers import IntentHandlers

        class FakeSenses:
            senses = {}
            def perceive_all(self):
                pass

        handlers = IntentHandlers(
            senses=FakeSenses(),
            vedana_fn=lambda: None,
            cwd="/tmp",
        )
        result = handlers.execute_cross_repo_diagnostic()
        assert result is None  # No reaper registered

    def test_handler_returns_none_when_no_degraded_peers(self):
        from steward.intent_handlers import IntentHandlers
        from steward.reaper import HeartbeatReaper
        from steward.services import SVC_REAPER
        from vibe_core.di import ServiceRegistry

        reaper = HeartbeatReaper()
        reaper.record_heartbeat("healthy-peer", timestamp=1000.0)
        ServiceRegistry.register(SVC_REAPER, reaper)

        class FakeSenses:
            senses = {}
            def perceive_all(self):
                pass

        handlers = IntentHandlers(
            senses=FakeSenses(),
            vedana_fn=lambda: None,
            cwd="/tmp",
        )
        result = handlers.execute_cross_repo_diagnostic()
        assert result is None  # No degraded peers

    def test_handler_reports_degraded_peers(self):
        from steward.intent_handlers import IntentHandlers
        from steward.reaper import HeartbeatReaper
        from steward.services import SVC_REAPER
        from vibe_core.di import ServiceRegistry

        reaper = HeartbeatReaper(lease_ttl_s=100)
        reaper.record_heartbeat("dying-peer", timestamp=500.0)
        reaper.reap(now=1000.0)  # → SUSPECT
        ServiceRegistry.register(SVC_REAPER, reaper)

        class FakeSenses:
            senses = {}
            def perceive_all(self):
                pass

        handlers = IntentHandlers(
            senses=FakeSenses(),
            vedana_fn=lambda: None,
            cwd="/tmp",
        )
        result = handlers.execute_cross_repo_diagnostic()
        assert result is not None
        assert "dying-peer" in result
        assert "suspect" in result
