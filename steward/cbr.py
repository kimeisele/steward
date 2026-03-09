"""
CBR Signal Processor — Constant Bitrate Token Stream.

Models token budget as a DSP signal chain, not hardcoded thresholds.
Each stage is a protocol-driven processor:

    Input Signal → Normalize → Compress → Limit → Output Budget

Audio DSP analogy:
    - Normalize: map raw metrics to 0.0-1.0 range
    - Compress: reduce dynamic range (prevent starvation AND waste)
    - Limit: hard ceiling (CBR budget, never exceeded)

The input signal is a composite of:
    - context_pressure: how full is the context window (0.0-1.0)
    - task_complexity: Manas-derived action weight (0.0-1.0)
    - cache_confidence: Hebbian seed confidence (0.0-1.0)

The output is a token budget in [floor, ceiling] range.

Protocol-driven: no concrete classes in the interface.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# ── CBR Constants ───────────────────────────────────────────────────
# Tick = quantization granularity (64 tokens = finer than 256, preserves DSP precision).
# Floor/ceiling are tick-derived multiples.
CBR_TICK = 64
CBR_FLOOR = CBR_TICK * 8   # 512 — minimum viable output (never starve)
CBR_CEILING = CBR_TICK * 16  # 1024 — maximum per LLM call
CBR_SYSTEM_OVERHEAD = 100  # system prompt + tool sigs (constant)


# ── Signal Types ────────────────────────────────────────────────────


@dataclass(frozen=True)
class CBRSignal:
    """Input signal to the CBR processor.

    All values normalized to 0.0-1.0 range.
    """

    context_pressure: float  # 0.0 = empty, 1.0 = full context window
    task_weight: float  # 0.0 = trivial (query), 1.0 = heavy (implement)
    cache_confidence: float  # 0.0 = unknown, 1.0 = definitely cached


@dataclass(frozen=True)
class CBROutput:
    """Output of the CBR signal chain."""

    budget: int  # token budget for this tick (always in [floor, ceiling])
    gain: float  # 0.0-1.0 — how much of the ceiling is allocated
    compressed: bool  # True if compressor reduced the budget
    limited: bool  # True if limiter capped the budget


# ── Protocol ────────────────────────────────────────────────────────


@runtime_checkable
class CBRProcessor(Protocol):
    """Protocol for CBR signal processing.

    Implementations can be swapped without changing the engine.
    """

    def process(self, signal: CBRSignal) -> CBROutput:
        """Process input signal → token budget."""
        ...

    @property
    def floor(self) -> int:
        """Minimum budget (never go below)."""
        ...

    @property
    def ceiling(self) -> int:
        """Maximum budget (never exceed)."""
        ...


# ── Implementation ──────────────────────────────────────────────────


class DSPProcessor:
    """CBR signal processor using audio DSP principles.

    Signal chain (branchless where possible):
        1. Gain staging: task_weight sets the base amplitude
        2. Compressor: context_pressure sidechain → logarithmic attenuation
        3. Cache gate: continuous attenuation (no hard switch)
        4. Limiter: brick wall ceiling/floor
        5. Quantize: CBR_TICK boundary

    Compressor uses real dB math:
        gain_reduction = overshoot × (1 - 1/ratio)
        attenuation = 10^(-gain_reduction)

    This is the actual dB-to-linear conversion from audio DSP.
    Threshold = 0.5 (50% context), Ratio = 3:1.
    """

    def __init__(
        self,
        floor: int = CBR_FLOOR,
        ceiling: int = CBR_CEILING,
        threshold: float = 0.5,
        ratio: float = 3.0,
    ) -> None:
        self._floor = floor
        self._ceiling = ceiling
        self._threshold = threshold
        self._ratio = ratio

    @property
    def floor(self) -> int:
        return self._floor

    @property
    def ceiling(self) -> int:
        return self._ceiling

    def process(self, signal: CBRSignal) -> CBROutput:
        """Full signal chain: gain → compress → gate → limit → quantize.

        Branchless: max() replaces if/else, continuous functions replace switches.
        """
        # 1. Gain staging: task_weight sets base amplitude (0.0-1.0)
        gain = signal.task_weight

        # 2. Compressor: context_pressure as sidechain input.
        #    Logarithmic attenuation — real dB math, not linear hack.
        #    Branchless: max(0, ...) handles below-threshold case (overshoot=0 → no effect).
        overshoot = max(0.0, signal.context_pressure - self._threshold)
        # Standard compressor gain reduction: GR = overshoot × (1 - 1/ratio)
        # At ratio=1: GR=0 (no compression). At ratio=∞: GR=overshoot (hard limiter).
        gain_reduction = overshoot * (1.0 - 1.0 / self._ratio)
        # dB-to-linear: 10^(-GR) — the actual formula from audio DSP.
        # Smooth, monotonic, logarithmic curve. No cliffs.
        attenuation = math.pow(10.0, -gain_reduction)
        gain *= attenuation
        compressed = overshoot > 0.0

        # 3. Cache gate: continuous attenuation — no hard switch.
        #    gain *= (1.0 - confidence × 0.5)
        #    At 0.0: no effect. At 1.0: halved. Linear ramp, branchless.
        gain *= 1.0 - signal.cache_confidence * 0.5

        # 4. Map gain to token budget
        budget_range = self._ceiling - self._floor
        raw_budget = self._floor + int(gain * budget_range)

        # 5. Limiter: brick wall (branchless clamp)
        limited = raw_budget > self._ceiling
        raw_budget = max(self._floor, min(self._ceiling, raw_budget))

        # 6. Quantize to CBR_TICK boundary
        budget = max(self._floor, (raw_budget // CBR_TICK) * CBR_TICK)

        return CBROutput(
            budget=budget,
            gain=gain,
            compressed=compressed,
            limited=limited,
        )


# ── Convenience ─────────────────────────────────────────────────────

# Default processor instance — used by Buddhi
_DEFAULT_PROCESSOR = DSPProcessor()


def process_cbr(
    context_pressure: float,
    task_weight: float,
    cache_confidence: float = 0.0,
) -> CBROutput:
    """Process CBR signal with default processor.

    Args:
        context_pressure: 0.0 (empty) to 1.0 (full context window)
        task_weight: 0.0 (trivial query) to 1.0 (heavy implementation)
        cache_confidence: 0.0 (unknown) to 1.0 (definitely cached)

    Returns:
        CBROutput with budget, gain, and quality flags
    """
    return _DEFAULT_PROCESSOR.process(
        CBRSignal(
            context_pressure=context_pressure,
            task_weight=task_weight,
            cache_confidence=cache_confidence,
        )
    )
