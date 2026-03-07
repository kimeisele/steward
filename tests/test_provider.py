"""Tests for ProviderChamber — multi-LLM failover with real substrate cells."""

from __future__ import annotations

from dataclasses import dataclass

from vibe_core.mahamantra.protocols._seed import COSMIC_FRAME, MAHA_QUANTUM

from steward.provider import ProviderChamber, _PRANA_CHEAP, _PRANA_FREE, _is_transient


# ── Fake Providers ───────────────────────────────────────────────────


@dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class FakeResponse:
    content: str = "response"
    tool_calls: list | None = None
    usage: FakeUsage | None = None

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = FakeUsage()


class FakeProvider:
    """Provider that always succeeds."""

    def __init__(self, name: str = "fake") -> None:
        self.name = name
        self.call_count = 0

    def invoke(self, **kwargs: object) -> FakeResponse:
        self.call_count += 1
        return FakeResponse(content=f"{self.name} response")


class FailingProvider:
    """Provider that always raises."""

    def invoke(self, **kwargs: object) -> object:
        raise ConnectionError("provider down")


# ── Tests ────────────────────────────────────────────────────────────


class TestProviderChamber:
    def test_single_provider(self):
        """Single provider returns response."""
        chamber = ProviderChamber()
        provider = FakeProvider("alpha")
        chamber.add_provider(
            name="alpha",
            provider=provider,
            model="alpha-v1",
            source_address=MAHA_QUANTUM * 10,
        )

        response = chamber.invoke(messages=[{"role": "user", "content": "hi"}])
        assert response is not None
        assert response.content == "alpha response"
        assert provider.call_count == 1

    def test_failover_to_next_provider(self):
        """If first provider fails, tries the next."""
        chamber = ProviderChamber()
        chamber.add_provider(
            name="failing",
            provider=FailingProvider(),
            model="fail-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_FREE,
        )
        backup = FakeProvider("backup")
        chamber.add_provider(
            name="backup",
            provider=backup,
            model="backup-v1",
            source_address=MAHA_QUANTUM * 11,
            prana=_PRANA_FREE,
        )

        response = chamber.invoke(messages=[])
        assert response is not None
        assert response.content == "backup response"
        assert backup.call_count == 1

    def test_all_providers_fail_returns_none(self):
        """If all providers fail, returns None."""
        chamber = ProviderChamber()
        chamber.add_provider(
            name="fail1",
            provider=FailingProvider(),
            model="fail-v1",
            source_address=MAHA_QUANTUM * 10,
        )
        chamber.add_provider(
            name="fail2",
            provider=FailingProvider(),
            model="fail-v2",
            source_address=MAHA_QUANTUM * 11,
        )

        response = chamber.invoke(messages=[])
        assert response is None

    def test_prana_ordering(self):
        """Higher-prana provider is tried first."""
        chamber = ProviderChamber()
        low = FakeProvider("low")
        high = FakeProvider("high")

        chamber.add_provider(
            name="low_prana",
            provider=low,
            model="low-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_CHEAP,  # low prana
        )
        chamber.add_provider(
            name="high_prana",
            provider=high,
            model="high-v1",
            source_address=MAHA_QUANTUM * 11,
            prana=_PRANA_FREE,  # high prana
        )

        response = chamber.invoke(messages=[])
        assert response is not None
        assert response.content == "high response"  # high prana tried first
        assert high.call_count == 1
        assert low.call_count == 0

    def test_integrity_degrades_on_failure(self):
        """Provider integrity decreases after failure."""
        chamber = ProviderChamber()
        chamber.add_provider(
            name="fragile",
            provider=FailingProvider(),
            model="fragile-v1",
            source_address=MAHA_QUANTUM * 10,
        )
        # Need a backup so invoke() doesn't just return None
        chamber.add_provider(
            name="backup",
            provider=FakeProvider(),
            model="backup-v1",
            source_address=MAHA_QUANTUM * 11,
        )

        chamber.invoke(messages=[])

        stats = chamber.stats()
        fragile = stats["providers"][0]
        assert fragile["integrity"] < COSMIC_FRAME  # degraded

    def test_prana_decreases_with_usage(self):
        """Provider prana decreases based on token usage."""
        chamber = ProviderChamber()
        chamber.add_provider(
            name="talker",
            provider=FakeProvider(),
            model="talk-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_FREE,
        )

        chamber.invoke(messages=[])

        stats = chamber.stats()
        # Prana should have decreased by input_tokens + output_tokens (100 + 50 = 150)
        assert stats["providers"][0]["prana"] == _PRANA_FREE - 150

    def test_stats(self):
        """Stats reports provider state."""
        chamber = ProviderChamber()
        chamber.add_provider(
            name="test",
            provider=FakeProvider(),
            model="test-v1",
            source_address=MAHA_QUANTUM * 10,
        )

        chamber.invoke(messages=[])
        stats = chamber.stats()

        assert stats["total_calls"] == 1
        assert stats["total_failures"] == 0
        assert len(stats["providers"]) == 1
        assert stats["providers"][0]["name"] == "test"

    def test_model_override(self):
        """Chamber uses cell's model, not caller's."""

        class ModelCapture:
            last_model: str | None = None

            def invoke(self, **kwargs: object) -> FakeResponse:
                self.last_model = str(kwargs.get("model", ""))
                return FakeResponse()

        capture = ModelCapture()
        chamber = ProviderChamber()
        chamber.add_provider(
            name="cap",
            provider=capture,
            model="cell-model-v2",
            source_address=MAHA_QUANTUM * 10,
        )

        chamber.invoke(model="caller-model-v1", messages=[])
        assert capture.last_model == "cell-model-v2"

    def test_empty_chamber_returns_none(self):
        """Empty chamber returns None."""
        chamber = ProviderChamber()
        assert chamber.invoke(messages=[]) is None
        assert len(chamber) == 0

    def test_retries_transient_errors(self):
        """Transient errors are retried before switching providers."""

        class TransientProvider:
            """Fails with timeout twice, then succeeds."""

            def __init__(self) -> None:
                self.call_count = 0

            def invoke(self, **kwargs: object) -> FakeResponse:
                self.call_count += 1
                if self.call_count <= 2:
                    raise TimeoutError("Request timed out")
                return FakeResponse(content="recovered")

        provider = TransientProvider()
        chamber = ProviderChamber()
        chamber.add_provider(
            name="flaky",
            provider=provider,
            model="flaky-v1",
            source_address=MAHA_QUANTUM * 10,
        )

        import steward.provider as pmod
        # Speed up retries for testing
        orig_delay = pmod._RETRY_BASE_DELAY
        pmod._RETRY_BASE_DELAY = 0.01
        try:
            response = chamber.invoke(messages=[])
        finally:
            pmod._RETRY_BASE_DELAY = orig_delay

        assert response is not None
        assert response.content == "recovered"
        assert provider.call_count == 3  # 2 fails + 1 success

    def test_non_transient_error_skips_retry(self):
        """Non-transient errors immediately switch to next provider."""

        class BadProvider:
            call_count = 0

            def invoke(self, **kwargs: object) -> object:
                self.call_count += 1
                raise ValueError("Invalid input format")

        bad = BadProvider()
        backup = FakeProvider("backup")
        chamber = ProviderChamber()
        chamber.add_provider(
            name="bad",
            provider=bad,
            model="bad-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_FREE,
        )
        chamber.add_provider(
            name="backup",
            provider=backup,
            model="backup-v1",
            source_address=MAHA_QUANTUM * 11,
            prana=_PRANA_FREE,
        )

        response = chamber.invoke(messages=[])
        assert response is not None
        assert response.content == "backup response"
        assert bad.call_count == 1  # no retries for non-transient


class TestIsTransient:
    def test_timeout_is_transient(self) -> None:
        assert _is_transient(TimeoutError("Request timed out"))

    def test_rate_limit_is_transient(self) -> None:
        assert _is_transient(Exception("Rate limit exceeded (429)"))

    def test_503_is_transient(self) -> None:
        assert _is_transient(Exception("Service unavailable 503"))

    def test_value_error_is_not_transient(self) -> None:
        assert not _is_transient(ValueError("Invalid JSON"))

    def test_auth_error_is_not_transient(self) -> None:
        assert not _is_transient(Exception("Authentication failed"))


class TestOperationalQuota:
    """Tests for OperationalQuota integration in ProviderChamber."""

    def test_quota_tracks_requests(self):
        """Successful invoke records usage in OperationalQuota."""
        chamber = ProviderChamber()
        chamber.add_provider(
            name="test",
            provider=FakeProvider(),
            model="test-v1",
            source_address=MAHA_QUANTUM * 10,
        )

        chamber.invoke(messages=[])

        status = chamber.quota.get_status()
        assert status["totals"]["total_requests"] == 1

    def test_quota_in_stats(self):
        """Stats includes quota status."""
        chamber = ProviderChamber()
        chamber.add_provider(
            name="test",
            provider=FakeProvider(),
            model="test-v1",
            source_address=MAHA_QUANTUM * 10,
        )

        chamber.invoke(messages=[])
        stats = chamber.stats()

        assert "quota" in stats
        quota_stats = stats["quota"]
        assert "requests" in quota_stats
        assert "cost" in quota_stats

    def test_quota_blocks_when_exceeded(self):
        """When quota is exceeded, invoke returns None."""
        from vibe_core.runtime.quota_manager import QuotaLimits

        # Set RPM to 1 — second request should be blocked
        limits = QuotaLimits(requests_per_minute=1)
        chamber = ProviderChamber()
        chamber._quota = __import__("vibe_core.runtime.quota_manager", fromlist=["OperationalQuota"]).OperationalQuota(limits=limits)
        chamber.add_provider(
            name="test",
            provider=FakeProvider(),
            model="test-v1",
            source_address=MAHA_QUANTUM * 10,
        )

        # First call should succeed
        r1 = chamber.invoke(messages=[])
        assert r1 is not None

        # Second call should be blocked by quota
        r2 = chamber.invoke(messages=[])
        assert r2 is None
