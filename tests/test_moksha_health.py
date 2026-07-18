"""Tests for MokshaHealthReportHook cognition instrument (spec §6).

Covers the `cognition` block in the health report: hard-down, degradation
(cycle delta), skip-collapse, fail-loud decode drift, and disk roundtrip
persistence of `consecutive_collapsed_cycles`.
"""

from __future__ import annotations

import json

import pytest

from steward.hooks.moksha_health import MokshaHealthReportHook, _build_health_report
from steward.phase_hook import PhaseContext
from steward.provider.chamber import ProviderChamber
from steward.services import SVC_PROVIDER
from steward.types import LLMUsage
from tests.fakes import FakeResponse
from vibe_core.di import ServiceRegistry
from vibe_core.mahamantra.protocols._seed import MAHA_QUANTUM


class FakeProvider:
    """Provider that always succeeds."""

    def __init__(self, name: str = "fake") -> None:
        self.name = name

    def invoke(self, **kwargs: object) -> FakeResponse:
        return FakeResponse(content=f"{self.name} response", usage=LLMUsage(input_tokens=10, output_tokens=5))


class StatsOnlyProvider:
    """Fake registered under SVC_PROVIDER exposing a raw crafted stats() dict."""

    def __init__(self, stats: dict) -> None:
        self._stats = stats

    def stats(self) -> dict:
        return self._stats


def _chamber_with_alive(n: int) -> ProviderChamber:
    chamber = ProviderChamber()
    for i in range(n):
        chamber.add_provider(
            name=f"p{i}",
            provider=FakeProvider(f"p{i}"),
            model="test-model",
            source_address=MAHA_QUANTUM * (10 + i),
        )
    return chamber


@pytest.fixture(autouse=True)
def _reset_registry():
    ServiceRegistry.reset_all()
    yield
    ServiceRegistry.reset_all()


class TestCognitionBlock:
    def test_cognition_block_healthy(self):
        chamber = _chamber_with_alive(2)
        ServiceRegistry.register(SVC_PROVIDER, chamber)

        report = _build_health_report()
        cog = report["cognition"]

        assert cog["providers_alive"] == 2
        assert cog["hard_down"] is False
        assert cog["degraded"] is False
        assert cog["consecutive_collapsed_cycles"] == 0

    def test_hard_down_increments(self):
        chamber = _chamber_with_alive(2)
        for cell in chamber._cells:
            cell.lifecycle.is_active = False
        ServiceRegistry.register(SVC_PROVIDER, chamber)

        prev = {"consecutive_collapsed_cycles": 3, "total_calls": 0, "total_failures": 0}
        report = _build_health_report(prev)
        cog = report["cognition"]

        assert cog["hard_down"] is True
        assert cog["consecutive_collapsed_cycles"] == 4

    def test_degraded_increments(self):
        chamber = _chamber_with_alive(1)
        chamber._total_calls = 0
        chamber._total_failures = 1  # failures, no success this cycle
        ServiceRegistry.register(SVC_PROVIDER, chamber)

        prev = {"consecutive_collapsed_cycles": 0, "total_calls": 0, "total_failures": 0}
        report = _build_health_report(prev)
        cog = report["cognition"]

        assert cog["hard_down"] is False
        assert cog["degraded"] is True
        assert cog["consecutive_collapsed_cycles"] == 1

    def test_healthy_fallback_stays_green(self):
        """Dead predecessor + healthy fallback (cd>0, fd>0) stays green."""
        chamber = _chamber_with_alive(1)
        chamber._total_calls = 1
        chamber._total_failures = 1
        ServiceRegistry.register(SVC_PROVIDER, chamber)

        prev = {"consecutive_collapsed_cycles": 5, "total_calls": 0, "total_failures": 0}
        report = _build_health_report(prev)
        cog = report["cognition"]

        assert cog["degraded"] is False
        assert cog["consecutive_collapsed_cycles"] == 0

    def test_transient_resets(self):
        chamber = _chamber_with_alive(1)
        chamber._total_calls = 1
        chamber._total_failures = 0
        ServiceRegistry.register(SVC_PROVIDER, chamber)

        prev = {"consecutive_collapsed_cycles": 5, "total_calls": 0, "total_failures": 0}
        report = _build_health_report(prev)
        cog = report["cognition"]

        assert cog["hard_down"] is False
        assert cog["degraded"] is False
        assert cog["skip_collapse"] is False
        assert cog["consecutive_collapsed_cycles"] == 0

    def test_no_provider_registered(self):
        prev = {"consecutive_collapsed_cycles": 5, "total_calls": 0, "total_failures": 0}
        report = _build_health_report(prev)
        cog = report["cognition"]

        assert cog["providers_total"] == 0
        assert cog["consecutive_collapsed_cycles"] == 5

    def test_skip_collapse_breaker(self):
        chamber = _chamber_with_alive(2)
        for breaker in chamber._breakers.values():
            for _ in range(5):
                breaker._record_failure(Exception("down"))
        ServiceRegistry.register(SVC_PROVIDER, chamber)

        prev = {"consecutive_collapsed_cycles": 0, "total_calls": 0, "total_failures": 0}
        report = _build_health_report(prev)
        cog = report["cognition"]

        assert cog["calls_delta"] == 0
        assert cog["fail_delta"] == 0
        assert cog["providers_usable"] == 0
        assert cog["skip_collapse"] is True
        assert cog["consecutive_collapsed_cycles"] == 1

    def test_decode_error_fails_loud(self):
        stats = {
            "providers": [
                {"name": "p0", "alive": True, "breaker": {"failure_count": 0}},  # missing 'state'
            ],
            "total_calls": 0,
            "total_failures": 0,
            "quota": {},
        }
        ServiceRegistry.register(SVC_PROVIDER, StatsOnlyProvider(stats))

        prev = {"consecutive_collapsed_cycles": 2, "total_calls": 0, "total_failures": 0}
        report = _build_health_report(prev)
        cog = report["cognition"]

        assert cog["decode_error"] is not None
        assert cog["hard_down"] is False
        assert cog["degraded"] is False
        assert cog["consecutive_collapsed_cycles"] == 2  # genuinely undecidable -> frozen

    def test_decode_error_does_not_mask_degraded(self):
        """Befund 1: an unambiguous collapse signal (degraded) must not be masked
        by an unrelated breaker/quota shape drift — only the undecidable
        skip_collapse signal is allowed to freeze the streak."""
        stats = {
            "providers": [
                {"name": "p0", "alive": True, "breaker": {"failure_count": 0}},  # missing 'state'
            ],
            "total_calls": 0,
            "total_failures": 1,  # fd=1, cd=0 -> degraded True regardless of decode drift
            "quota": {},
        }
        ServiceRegistry.register(SVC_PROVIDER, StatsOnlyProvider(stats))

        prev = {"consecutive_collapsed_cycles": 2, "total_calls": 0, "total_failures": 0}
        report = _build_health_report(prev)
        cog = report["cognition"]

        assert cog["decode_error"] is not None
        assert cog["degraded"] is True
        assert cog["consecutive_collapsed_cycles"] == 3  # advanced, not frozen


class TestDiskRoundtrip:
    def test_roundtrip_increment(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        steward_dir = tmp_path / ".steward"
        steward_dir.mkdir()
        (steward_dir / "federation_health.json").write_text(
            json.dumps({"cognition": {"consecutive_collapsed_cycles": 3, "total_calls": 0, "total_failures": 0}})
        )

        chamber = _chamber_with_alive(2)
        for cell in chamber._cells:
            cell.lifecycle.is_active = False
        ServiceRegistry.register(SVC_PROVIDER, chamber)

        hook = MokshaHealthReportHook()
        ctx = PhaseContext(cwd=str(tmp_path))
        hook.execute(ctx)

        written = json.loads((steward_dir / "federation_health.json").read_text())
        assert written["cognition"]["consecutive_collapsed_cycles"] == 4

    def test_roundtrip_missing_and_torn(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        chamber = _chamber_with_alive(2)
        ServiceRegistry.register(SVC_PROVIDER, chamber)

        hook = MokshaHealthReportHook()
        ctx = PhaseContext(cwd=str(tmp_path))
        hook.execute(ctx)  # missing file -> defaults, no crash

        steward_dir = tmp_path / ".steward"
        (steward_dir / "federation_health.json").write_text("{not json")

        hook.execute(ctx)  # torn file -> defaults, no crash

        (steward_dir / "federation_health.json").write_text(json.dumps({"peers": {}}))

        hook.execute(ctx)  # no cognition key -> defaults, no crash

        written = json.loads((steward_dir / "federation_health.json").read_text())
        assert written["cognition"]["consecutive_collapsed_cycles"] == 0

    def test_execute_appends_ok_and_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        hook = MokshaHealthReportHook()
        ctx = PhaseContext(cwd=str(tmp_path))

        result = hook.execute(ctx)

        assert result is None
        assert "moksha_health_report:ok" in ctx.operations


class TestProtocolShapeValidation:
    """Befund 3: spec §5.3a claims execute() validates the installed
    steward-protocol shape once on first call — this must actually happen."""

    def test_validate_protocol_shape_matches_installed_package(self):
        """Re-runs the impl-step-1 version cross-check as a regression test:
        the real installed steward-protocol get_status() shapes must decode
        cleanly through the pinned decoders."""
        from steward.hooks.moksha_health import _breaker_ok, _quota_ok
        from vibe_core.runtime.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
        from vibe_core.runtime.quota_manager import OperationalQuota

        assert _breaker_ok(CircuitBreaker(CircuitBreakerConfig()).get_status()) is True
        assert _quota_ok(OperationalQuota().get_status()) is True

    def test_validate_protocol_shape_once_sets_flag(self, monkeypatch):
        import steward.hooks.moksha_health as mh

        monkeypatch.setattr(mh, "_version_validated", False)
        mh._validate_protocol_shape_once()
        assert mh._version_validated is True

    def test_validate_protocol_shape_runs_only_once(self, monkeypatch):
        import steward.hooks.moksha_health as mh

        monkeypatch.setattr(mh, "_version_validated", False)
        calls = []
        real_breaker_ok = mh._breaker_ok

        def spy(b):
            calls.append(b)
            return real_breaker_ok(b)

        monkeypatch.setattr(mh, "_breaker_ok", spy)
        mh._validate_protocol_shape_once()
        mh._validate_protocol_shape_once()
        mh._validate_protocol_shape_once()

        assert len(calls) == 1  # validated once, subsequent calls are no-ops

    def test_execute_triggers_validation(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import steward.hooks.moksha_health as mh

        monkeypatch.setattr(mh, "_version_validated", False)
        hook = MokshaHealthReportHook()
        ctx = PhaseContext(cwd=str(tmp_path))

        hook.execute(ctx)

        assert mh._version_validated is True

    def test_validate_protocol_shape_detects_drift(self, monkeypatch, caplog):
        import logging

        import steward.hooks.moksha_health as mh
        from vibe_core.runtime.circuit_breaker import CircuitBreaker

        monkeypatch.setattr(mh, "_version_validated", False)
        monkeypatch.setattr(CircuitBreaker, "get_status", lambda self: {"failure_count": 0})

        with caplog.at_level(logging.ERROR, logger="STEWARD.HOOKS.MOKSHA_HEALTH"):
            mh._validate_protocol_shape_once()

        assert mh._version_validated is True  # non-fatal: logged, not raised
        assert any("shape drift" in r.message for r in caplog.records)
