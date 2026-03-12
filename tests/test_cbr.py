"""Tests for CBR Signal Processor — DSP-based token budget.

Tests the signal chain: Normalize → Compress → Limit.
All values are physical/mathematical — no magic thresholds.
"""

from steward.cbr import (
    CBR_CEILING,
    CBR_FLOOR,
    CBR_TICK,
    CBROutput,
    CBRProcessor,
    CBRSignal,
    DSPProcessor,
    process_cbr,
)


class TestCBRConstants:
    """CBR constants are mathematically sound."""

    def test_tick_is_power_of_two(self):
        """CBR tick must be a power of 2 (clean binary boundary)."""
        assert CBR_TICK > 0
        assert CBR_TICK & (CBR_TICK - 1) == 0  # power of 2

    def test_floor_is_tick_multiple(self):
        assert CBR_FLOOR % CBR_TICK == 0
        assert CBR_FLOOR >= CBR_TICK * 2  # never starve

    def test_ceiling_is_tick_multiple(self):
        assert CBR_CEILING % CBR_TICK == 0
        assert CBR_CEILING > CBR_FLOOR

    def test_floor_ceiling_range(self):
        """Range must allow meaningful graduation."""
        assert CBR_CEILING / CBR_FLOOR >= 2  # at least 2:1 dynamic range


class TestDSPProcessorProtocol:
    """DSPProcessor implements CBRProcessor protocol."""

    def test_implements_protocol(self):
        proc = DSPProcessor()
        assert isinstance(proc, CBRProcessor)

    def test_floor_ceiling_properties(self):
        proc = DSPProcessor()
        assert proc.floor == CBR_FLOOR
        assert proc.ceiling == CBR_CEILING


class TestGainStaging:
    """Task weight sets the base gain (amplitude)."""

    def test_trivial_task_low_budget(self):
        """task_weight=0.0 → floor budget (minimum)."""
        out = process_cbr(context_pressure=0.0, task_weight=0.0)
        assert out.budget == CBR_FLOOR

    def test_heavy_task_high_budget(self):
        """task_weight=1.0 → ceiling budget (maximum)."""
        out = process_cbr(context_pressure=0.0, task_weight=1.0)
        assert out.budget == CBR_CEILING

    def test_medium_task_medium_budget(self):
        """task_weight=0.5 → somewhere in the middle."""
        out = process_cbr(context_pressure=0.0, task_weight=0.5)
        assert CBR_FLOOR <= out.budget <= CBR_CEILING

    def test_monotonic_increase(self):
        """Higher task weight → higher or equal budget (monotonic)."""
        budgets = [process_cbr(context_pressure=0.0, task_weight=w / 10.0).budget for w in range(11)]
        for i in range(1, len(budgets)):
            assert budgets[i] >= budgets[i - 1], f"Budget decreased at weight {i / 10}: {budgets[i]} < {budgets[i - 1]}"


class TestCompressor:
    """Context pressure compresses the gain (reduces dynamic range)."""

    def test_no_compression_below_threshold(self):
        """Below threshold (0.5), no compression applied."""
        out = process_cbr(context_pressure=0.3, task_weight=1.0)
        assert not out.compressed
        assert out.budget == CBR_CEILING

    def test_compression_above_threshold(self):
        """Above threshold, compression reduces budget."""
        out_low = process_cbr(context_pressure=0.3, task_weight=1.0)
        out_high = process_cbr(context_pressure=0.8, task_weight=1.0)
        assert out_high.compressed
        assert out_high.budget < out_low.budget

    def test_compression_is_graduated(self):
        """Compression is smooth, not a cliff (soft knee)."""
        budgets = [process_cbr(context_pressure=p / 10.0, task_weight=1.0).budget for p in range(11)]
        # No single step should drop more than 50% of remaining range
        for i in range(1, len(budgets)):
            if budgets[i] < budgets[i - 1]:
                drop = budgets[i - 1] - budgets[i]
                remaining = budgets[i - 1] - CBR_FLOOR
                if remaining > 0:
                    assert drop <= remaining * 0.6, (
                        f"Cliff detected at pressure {i / 10}: dropped {drop} of {remaining}"
                    )

    def test_never_below_floor(self):
        """Even at maximum pressure, budget never goes below floor."""
        out = process_cbr(context_pressure=1.0, task_weight=1.0)
        assert out.budget >= CBR_FLOOR

    def test_full_pressure_full_weight(self):
        """Maximum pressure with maximum task weight: still >= floor."""
        out = process_cbr(context_pressure=0.99, task_weight=1.0)
        assert out.budget >= CBR_FLOOR
        assert out.compressed


class TestLimiter:
    """Hard ceiling and floor (brick wall limiter)."""

    def test_budget_never_exceeds_ceiling(self):
        """No matter what, budget <= ceiling."""
        for w in range(11):
            for p in range(11):
                out = process_cbr(
                    context_pressure=p / 10.0,
                    task_weight=w / 10.0,
                )
                assert out.budget <= CBR_CEILING, (
                    f"Budget {out.budget} > ceiling {CBR_CEILING} at w={w / 10} p={p / 10}"
                )

    def test_budget_never_below_floor(self):
        """No matter what, budget >= floor."""
        for w in range(11):
            for p in range(11):
                out = process_cbr(
                    context_pressure=p / 10.0,
                    task_weight=w / 10.0,
                )
                assert out.budget >= CBR_FLOOR, f"Budget {out.budget} < floor {CBR_FLOOR} at w={w / 10} p={p / 10}"


class TestQuantization:
    """Output budget is always quantized to CBR_TICK boundary."""

    def test_budget_is_tick_aligned(self):
        """Budget is always a multiple of CBR_TICK."""
        for w in range(11):
            for p in range(11):
                out = process_cbr(
                    context_pressure=p / 10.0,
                    task_weight=w / 10.0,
                )
                assert out.budget % CBR_TICK == 0, f"Budget {out.budget} not aligned to tick {CBR_TICK}"


class TestCacheGate:
    """High cache confidence reduces budget (we might not need LLM)."""

    def test_high_cache_confidence_reduces_budget(self):
        """cache_confidence > 0.8 halves the gain."""
        out_low = process_cbr(context_pressure=0.0, task_weight=1.0, cache_confidence=0.0)
        out_high = process_cbr(context_pressure=0.0, task_weight=1.0, cache_confidence=0.9)
        assert out_high.budget < out_low.budget

    def test_cache_gate_is_proportional(self):
        """Cache gate scales continuously — no hard switch."""
        out_0 = process_cbr(context_pressure=0.0, task_weight=1.0, cache_confidence=0.0)
        out_50 = process_cbr(context_pressure=0.0, task_weight=1.0, cache_confidence=0.5)
        out_100 = process_cbr(context_pressure=0.0, task_weight=1.0, cache_confidence=1.0)
        assert out_0.budget >= out_50.budget >= out_100.budget
        assert out_0.budget > out_100.budget  # extremes differ


class TestCustomProcessor:
    """Custom processor with different parameters."""

    def test_custom_threshold(self):
        """Lower threshold → compression starts earlier."""
        proc = DSPProcessor(threshold=0.3)
        out = proc.process(CBRSignal(context_pressure=0.4, task_weight=1.0, cache_confidence=0.0))
        assert out.compressed  # already compressed at 0.4

    def test_custom_ratio(self):
        """Higher ratio → more aggressive compression."""
        mild = DSPProcessor(ratio=2.0)
        aggressive = DSPProcessor(ratio=10.0)

        signal = CBRSignal(context_pressure=0.8, task_weight=1.0, cache_confidence=0.0)
        out_mild = mild.process(signal)
        out_aggressive = aggressive.process(signal)
        assert out_aggressive.budget <= out_mild.budget

    def test_custom_floor_ceiling(self):
        """Custom floor/ceiling respected."""
        proc = DSPProcessor(floor=128, ceiling=2048)
        assert proc.floor == 128
        assert proc.ceiling == 2048


class TestSignalDataclass:
    """CBRSignal and CBROutput are immutable."""

    def test_signal_frozen(self):
        sig = CBRSignal(context_pressure=0.5, task_weight=0.5, cache_confidence=0.0)
        try:
            sig.context_pressure = 0.9  # type: ignore
            assert False, "Should be frozen"
        except AttributeError:
            pass

    def test_output_frozen(self):
        out = CBROutput(budget=512, gain=0.5, compressed=False, limited=False)
        try:
            out.budget = 1024  # type: ignore
            assert False, "Should be frozen"
        except AttributeError:
            pass
