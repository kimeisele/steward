"""Tests for ProviderChamber — multi-LLM failover with real substrate cells."""

from __future__ import annotations

from dataclasses import dataclass

from vibe_core.mahamantra.protocols._seed import COSMIC_FRAME, MAHA_QUANTUM

from vibe_core.protocols.feedback import InMemoryFeedback, SignalType
from vibe_core.runtime.circuit_breaker import CircuitBreakerState

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
        """Provider prana decreases based on token usage + METABOLIC_COST."""
        from vibe_core.mahamantra.substrate.cell_system.cell import METABOLIC_COST

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
        # metabolize(-150): prana -= METABOLIC_COST (3) then prana += (-150)
        # Total drain = 153, cycle increments by 1
        total_tokens = 100 + 50  # FakeUsage defaults
        assert stats["providers"][0]["prana"] == _PRANA_FREE - total_tokens - METABOLIC_COST
        assert stats["providers"][0]["cycle"] == 1

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

    def test_prefer_capable_inverts_order(self):
        """prefer_capable=True tries expensive providers first."""
        chamber = ProviderChamber()
        cheap = FakeProvider("cheap")
        expensive = FakeProvider("expensive")

        chamber.add_provider(
            name="cheap",
            provider=cheap,
            model="cheap-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_FREE,
            cost_per_mtok=0.10,
        )
        chamber.add_provider(
            name="expensive",
            provider=expensive,
            model="expensive-v1",
            source_address=MAHA_QUANTUM * 11,
            prana=_PRANA_FREE,
            cost_per_mtok=3.0,
        )

        # Normal: cheap first (higher prana or equal → first registered)
        r1 = chamber.invoke(messages=[])
        assert r1 is not None

        # prefer_capable: expensive first
        r2 = chamber.invoke(messages=[], prefer_capable=True)
        assert r2 is not None
        assert r2.content == "expensive response"
        assert expensive.call_count >= 1

    def test_quota_blocks_when_exceeded(self):
        """When quota is exceeded, invoke returns None."""
        from vibe_core.runtime.quota_manager import QuotaLimits

        # Set RPM to 1 — second request should be blocked
        limits = QuotaLimits(requests_per_minute=1)
        chamber = ProviderChamber()
        chamber._quota = __import__("vibe_core.runtime.quota_manager", fromlist=["OperationalQuota"]).OperationalQuota(
            limits=limits
        )
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


class TestCircuitBreaker:
    """Tests for per-cell CircuitBreaker integration."""

    def test_circuit_breaker_opens_after_failures(self):
        """5 consecutive failures → breaker opens → cell skipped."""
        chamber = ProviderChamber()
        chamber.add_provider(
            name="fragile",
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

        import steward.provider as pmod

        orig_delay = pmod._RETRY_BASE_DELAY
        pmod._RETRY_BASE_DELAY = 0.001
        try:
            # Trigger 5 failures (default threshold) — need enough invocations
            # Each invoke tries fragile (fails), then backup (succeeds)
            for _ in range(5):
                chamber.invoke(messages=[])

            # Breaker should now be OPEN for "fragile"
            breaker = chamber._breakers["fragile"]
            assert breaker.state == CircuitBreakerState.OPEN

            # Next call should skip fragile entirely (no retry delay)
            backup.call_count = 0
            r = chamber.invoke(messages=[])
            assert r is not None
            assert r.content == "backup response"
            assert backup.call_count == 1
        finally:
            pmod._RETRY_BASE_DELAY = orig_delay

    def test_circuit_breaker_per_provider(self):
        """Provider A breaker opens, Provider B still works normally."""
        chamber = ProviderChamber()
        chamber.add_provider(
            name="broken",
            provider=FailingProvider(),
            model="fail-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_FREE,
        )
        healthy = FakeProvider("healthy")
        chamber.add_provider(
            name="healthy",
            provider=healthy,
            model="ok-v1",
            source_address=MAHA_QUANTUM * 11,
            prana=_PRANA_FREE,
        )

        import steward.provider as pmod

        orig_delay = pmod._RETRY_BASE_DELAY
        pmod._RETRY_BASE_DELAY = 0.001
        try:
            for _ in range(5):
                chamber.invoke(messages=[])
        finally:
            pmod._RETRY_BASE_DELAY = orig_delay

        # "broken" breaker is OPEN
        assert chamber._breakers["broken"].state == CircuitBreakerState.OPEN
        # "healthy" breaker is still CLOSED
        assert chamber._breakers["healthy"].state == CircuitBreakerState.CLOSED

    def test_breaker_in_stats(self):
        """Stats include breaker status per provider."""
        chamber = ProviderChamber()
        chamber.add_provider(
            name="test",
            provider=FakeProvider(),
            model="test-v1",
            source_address=MAHA_QUANTUM * 10,
        )

        stats = chamber.stats()
        assert stats["providers"][0]["breaker"] is not None
        assert stats["providers"][0]["breaker"]["state"] == "closed"

    def test_daily_reset_clears_breakers(self):
        """Daily reset restores breakers to CLOSED."""
        from datetime import date, timedelta

        chamber = ProviderChamber()
        chamber.add_provider(
            name="test",
            provider=FailingProvider(),
            model="fail-v1",
            source_address=MAHA_QUANTUM * 10,
        )
        chamber.add_provider(
            name="backup",
            provider=FakeProvider(),
            model="ok-v1",
            source_address=MAHA_QUANTUM * 11,
        )

        import steward.provider as pmod

        orig_delay = pmod._RETRY_BASE_DELAY
        pmod._RETRY_BASE_DELAY = 0.001
        try:
            for _ in range(5):
                chamber.invoke(messages=[])
        finally:
            pmod._RETRY_BASE_DELAY = orig_delay

        assert chamber._breakers["test"].state == CircuitBreakerState.OPEN

        # Simulate next day
        chamber._last_reset = date.today() - timedelta(days=1)
        chamber._maybe_reset_daily()

        assert chamber._breakers["test"].state == CircuitBreakerState.CLOSED


class TestFeedbackProtocol:
    """Tests for FeedbackProtocol integration in ProviderChamber."""

    def test_feedback_records_success(self):
        """Successful invoke → signal_success called."""
        feedback = InMemoryFeedback()
        chamber = ProviderChamber()
        chamber.set_feedback(feedback)
        chamber.add_provider(
            name="test",
            provider=FakeProvider(),
            model="test-v1",
            source_address=MAHA_QUANTUM * 10,
        )

        chamber.invoke(messages=[])

        stats = feedback.get_stats()
        assert stats.success_count == 1
        assert stats.failure_count == 0

    def test_feedback_records_failure(self):
        """Failed invoke → signal_failure called."""
        feedback = InMemoryFeedback()
        chamber = ProviderChamber()
        chamber.set_feedback(feedback)
        chamber.add_provider(
            name="failing",
            provider=FailingProvider(),
            model="fail-v1",
            source_address=MAHA_QUANTUM * 10,
        )

        chamber.invoke(messages=[])  # will fail, return None

        stats = feedback.get_stats()
        assert stats.failure_count >= 1

    def test_feedback_pattern_detection(self):
        """After multiple failures of same type, pattern is detected."""
        feedback = InMemoryFeedback()
        chamber = ProviderChamber()
        chamber.set_feedback(feedback)
        chamber.add_provider(
            name="failing",
            provider=FailingProvider(),
            model="fail-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_FREE,
        )
        # Backup so invoke doesn't just die
        chamber.add_provider(
            name="backup",
            provider=FakeProvider(),
            model="ok-v1",
            source_address=MAHA_QUANTUM * 11,
            prana=_PRANA_FREE,
        )

        import steward.provider as pmod

        orig_delay = pmod._RETRY_BASE_DELAY
        pmod._RETRY_BASE_DELAY = 0.001
        try:
            for _ in range(3):
                chamber.invoke(messages=[])
        finally:
            pmod._RETRY_BASE_DELAY = orig_delay

        patterns = feedback.get_failure_patterns(command="failing", min_frequency=2)
        assert len(patterns) >= 1
        assert patterns[0].frequency >= 2

    def test_feedback_success_signals_have_context(self):
        """Success signals include model and prana context."""
        feedback = InMemoryFeedback()
        chamber = ProviderChamber()
        chamber.set_feedback(feedback)
        chamber.add_provider(
            name="test",
            provider=FakeProvider(),
            model="test-v1",
            source_address=MAHA_QUANTUM * 10,
        )

        chamber.invoke(messages=[])

        signals = feedback.get_recent_signals(signal_type=SignalType.SUCCESS)
        assert len(signals) == 1
        assert signals[0].command == "test"
        assert "model" in signals[0].context
        assert signals[0].duration_ms > 0


class TestModelTierRouting:
    """Tests for ModelTier-aware provider routing."""

    def test_flash_tier_prefers_cheapest(self):
        """FLASH tier sorts by cost ascending (cheapest first)."""
        chamber = ProviderChamber()
        cheap = FakeProvider("cheap")
        expensive = FakeProvider("expensive")

        chamber.add_provider(
            name="expensive",
            provider=expensive,
            model="exp-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_FREE,
            cost_per_mtok=3.0,
        )
        chamber.add_provider(
            name="cheap",
            provider=cheap,
            model="cheap-v1",
            source_address=MAHA_QUANTUM * 11,
            prana=_PRANA_FREE,
            cost_per_mtok=0.0,
        )

        r = chamber.invoke(messages=[], tier="flash")
        assert r is not None
        assert r.content == "cheap response"

    def test_pro_tier_prefers_capable(self):
        """PRO tier sorts by cost descending (most capable first)."""
        chamber = ProviderChamber()
        cheap = FakeProvider("cheap")
        expensive = FakeProvider("expensive")

        chamber.add_provider(
            name="cheap",
            provider=cheap,
            model="cheap-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_FREE,
            cost_per_mtok=0.0,
        )
        chamber.add_provider(
            name="expensive",
            provider=expensive,
            model="exp-v1",
            source_address=MAHA_QUANTUM * 11,
            prana=_PRANA_FREE,
            cost_per_mtok=3.0,
        )

        r = chamber.invoke(messages=[], tier="pro")
        assert r is not None
        assert r.content == "expensive response"

    def test_standard_tier_uses_prana_ordering(self):
        """STANDARD tier uses default prana ordering."""
        chamber = ProviderChamber()
        low = FakeProvider("low")
        high = FakeProvider("high")

        chamber.add_provider(
            name="low",
            provider=low,
            model="low-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_CHEAP,
        )
        chamber.add_provider(
            name="high",
            provider=high,
            model="high-v1",
            source_address=MAHA_QUANTUM * 11,
            prana=_PRANA_FREE,
        )

        r = chamber.invoke(messages=[], tier="standard")
        assert r is not None
        assert r.content == "high response"  # higher prana first

    def test_prefer_capable_maps_to_pro(self):
        """Legacy prefer_capable=True maps to PRO tier."""
        chamber = ProviderChamber()
        cheap = FakeProvider("cheap")
        expensive = FakeProvider("expensive")

        chamber.add_provider(
            name="cheap",
            provider=cheap,
            model="cheap-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_FREE,
            cost_per_mtok=0.0,
        )
        chamber.add_provider(
            name="expensive",
            provider=expensive,
            model="exp-v1",
            source_address=MAHA_QUANTUM * 11,
            prana=_PRANA_FREE,
            cost_per_mtok=3.0,
        )

        r = chamber.invoke(messages=[], prefer_capable=True)
        assert r is not None
        assert r.content == "expensive response"


class TestFeedbackAdaptiveRouting:
    """Tests for feedback-based adaptive routing (closed loop)."""

    def test_warned_provider_deprioritized(self):
        """Provider with >60% failure rate is tried last, not first."""
        feedback = InMemoryFeedback()
        chamber = ProviderChamber()
        chamber.set_feedback(feedback)

        flaky = FakeProvider("flaky")
        reliable = FakeProvider("reliable")

        chamber.add_provider(
            name="flaky",
            provider=flaky,
            model="flaky-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_FREE,
        )
        chamber.add_provider(
            name="reliable",
            provider=reliable,
            model="reliable-v1",
            source_address=MAHA_QUANTUM * 11,
            prana=_PRANA_FREE,
        )

        # Poison "flaky" with failures (>60% rate triggers warning)
        for _ in range(3):
            feedback.signal_failure("flaky", "timeout", {"model": "flaky-v1"})

        # Now invoke — reliable should be tried first despite same prana
        r = chamber.invoke(messages=[])
        assert r is not None
        assert r.content == "reliable response"
        assert reliable.call_count == 1
        assert flaky.call_count == 0  # deprioritized, not needed

    def test_warned_provider_still_available(self):
        """Warned provider is deprioritized but NOT skipped entirely."""
        feedback = InMemoryFeedback()
        chamber = ProviderChamber()
        chamber.set_feedback(feedback)

        flaky = FakeProvider("flaky")

        chamber.add_provider(
            name="flaky",
            provider=flaky,
            model="flaky-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_FREE,
        )

        # Poison with failures
        for _ in range(3):
            feedback.signal_failure("flaky", "timeout", {"model": "flaky-v1"})

        # Only provider — still used despite warning
        r = chamber.invoke(messages=[])
        assert r is not None
        assert r.content == "flaky response"
        assert flaky.call_count == 1

    def test_no_feedback_no_change(self):
        """Without feedback wired, routing is unchanged."""
        chamber = ProviderChamber()
        provider = FakeProvider("test")

        chamber.add_provider(
            name="test",
            provider=provider,
            model="test-v1",
            source_address=MAHA_QUANTUM * 10,
        )

        r = chamber.invoke(messages=[])
        assert r is not None
        assert r.content == "test response"

    def test_clean_provider_unaffected(self):
        """Provider with good track record is not penalized."""
        feedback = InMemoryFeedback()
        chamber = ProviderChamber()
        chamber.set_feedback(feedback)

        good = FakeProvider("good")

        chamber.add_provider(
            name="good",
            provider=good,
            model="good-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_FREE,
        )

        # Good track record (100% success)
        for _ in range(5):
            feedback.signal_success("good", {"model": "good-v1"})

        r = chamber.invoke(messages=[])
        assert r is not None
        assert r.content == "good response"

    def test_feedback_stats_in_stats(self):
        """stats() includes feedback section when feedback is wired."""
        feedback = InMemoryFeedback()
        chamber = ProviderChamber()
        chamber.set_feedback(feedback)
        chamber.add_provider(
            name="test",
            provider=FakeProvider(),
            model="test-v1",
            source_address=MAHA_QUANTUM * 10,
        )

        chamber.invoke(messages=[])

        stats = chamber.stats()
        assert "feedback" in stats
        fb = stats["feedback"]
        assert fb["total_signals"] == 1
        assert fb["success_rate"] == 1.0
        assert isinstance(fb["failure_patterns"], list)

    def test_feedback_stats_absent_without_feedback(self):
        """stats() has no feedback key when feedback is not wired."""
        chamber = ProviderChamber()
        chamber.add_provider(
            name="test",
            provider=FakeProvider(),
            model="test-v1",
            source_address=MAHA_QUANTUM * 10,
        )

        stats = chamber.stats()
        assert "feedback" not in stats

    def test_feedback_penalty_preserves_tier_sort(self):
        """Feedback penalty applies AFTER tier sort — both compose."""
        feedback = InMemoryFeedback()
        chamber = ProviderChamber()
        chamber.set_feedback(feedback)

        cheap_flaky = FakeProvider("cheap_flaky")
        expensive_clean = FakeProvider("expensive_clean")

        chamber.add_provider(
            name="cheap_flaky",
            provider=cheap_flaky,
            model="cheap-v1",
            source_address=MAHA_QUANTUM * 10,
            prana=_PRANA_FREE,
            cost_per_mtok=0.0,
        )
        chamber.add_provider(
            name="expensive_clean",
            provider=expensive_clean,
            model="exp-v1",
            source_address=MAHA_QUANTUM * 11,
            prana=_PRANA_FREE,
            cost_per_mtok=3.0,
        )

        # Poison cheap_flaky
        for _ in range(3):
            feedback.signal_failure("cheap_flaky", "error", {"model": "cheap-v1"})

        # Flash tier would normally prefer cheap first,
        # but feedback penalty pushes flaky to end
        r = chamber.invoke(messages=[], tier="flash")
        assert r is not None
        assert r.content == "expensive_clean response"


class TestNormalizeUsage:
    """Tests for _normalize_usage at the adapter boundary."""

    def test_normalize_none(self):
        from steward.provider import _normalize_usage

        u = _normalize_usage(None)
        assert u.input_tokens == 0
        assert u.output_tokens == 0

    def test_normalize_openai_format(self):
        """OpenAI uses prompt_tokens/completion_tokens."""
        from steward.provider import _normalize_usage
        from dataclasses import dataclass

        @dataclass
        class OpenAIUsage:
            prompt_tokens: int = 100
            completion_tokens: int = 50

        u = _normalize_usage(OpenAIUsage())
        assert u.input_tokens == 100
        assert u.output_tokens == 50

    def test_normalize_anthropic_format(self):
        """Anthropic uses input_tokens/output_tokens."""
        from steward.provider import _normalize_usage
        from dataclasses import dataclass

        @dataclass
        class AnthropicUsage:
            input_tokens: int = 200
            output_tokens: int = 80

        u = _normalize_usage(AnthropicUsage())
        assert u.input_tokens == 200
        assert u.output_tokens == 80

    def test_adapter_response_returns_llm_usage(self):
        """_AdapterResponse.usage returns LLMUsage, not raw object."""
        from steward.provider import _AdapterResponse
        from steward.types import LLMUsage
        from dataclasses import dataclass

        @dataclass
        class FakeChoice:
            message: object = None

            def __post_init__(self):
                self.message = type("M", (), {"content": "hi", "tool_calls": None})()

        @dataclass
        class FakeRaw:
            choices: list = None
            usage: object = None

            def __post_init__(self):
                self.choices = [FakeChoice()]
                self.usage = type("U", (), {"prompt_tokens": 42, "completion_tokens": 13})()

        resp = _AdapterResponse(FakeRaw())
        assert isinstance(resp.usage, LLMUsage)
        assert resp.usage.input_tokens == 42
        assert resp.usage.output_tokens == 13


class TestGroqCell:
    """Tests for Groq provider cell in build_chamber."""

    def test_groq_address_constant(self):
        """_ADDR_GROQ is defined correctly."""
        from steward.provider import _ADDR_GROQ

        assert _ADDR_GROQ == MAHA_QUANTUM * 14
