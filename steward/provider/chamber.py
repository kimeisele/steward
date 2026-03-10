"""
ProviderChamber — Multi-LLM provider failover with real substrate cells.

Each LLM provider is a MahaCellUnified with prana-ordered priority.
Free providers have more prana = tried first. On failure, integrity
degrades and the next provider is tried.

Gita mapping: this is part of the Karmendriya (action organ) layer.
The Chamber selects WHICH action organ to use, not what action to take
(that's Buddhi's job).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Iterator

from steward.types import LLMProvider, LLMUsage, NormalizedResponse, StreamDelta, StreamingProvider
from vibe_core.mahamantra.protocols._header import MahaHeader
from vibe_core.mahamantra.protocols._seed import COSMIC_FRAME, MAHA_QUANTUM
from vibe_core.mahamantra.substrate.cell_system.cell import (
    CellLifecycleState,
    MahaCellUnified,
)
from vibe_core.protocols.feedback import FeedbackProtocol
from vibe_core.runtime.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from vibe_core.runtime.quota_manager import OperationalQuota, QuotaExceededError

logger = logging.getLogger("STEWARD.PROVIDER")

# ── Provider Source Addresses (deterministic, SSOT-derived) ──────────

_ADDR_GOOGLE = MAHA_QUANTUM * 10  # 1370
_ADDR_MISTRAL = MAHA_QUANTUM * 11  # 1507
_ADDR_DEEPSEEK = MAHA_QUANTUM * 12  # 1644
_ADDR_ANTHROPIC = MAHA_QUANTUM * 13  # 1781
_ADDR_GROQ = MAHA_QUANTUM * 14  # 1918

# ── Prana Budgets ────────────────────────────────────────────────────

_PRANA_FREE = MAHA_QUANTUM * 100  # 13700 (free tier = full energy)
_PRANA_CHEAP = MAHA_QUANTUM * 10  # 1370  (paid = less energy = lower priority)

# Transient errors that warrant retry (not provider switch)
_TRANSIENT_ERRORS = (
    "timeout",
    "timed out",
    "rate limit",
    "429",
    "503",
    "502",
    "connection reset",
    "connection refused",
    "temporary",
    "overloaded",
    "capacity",
    "retry",
)

_MAX_RETRIES = 2
_RETRY_BASE_DELAY = 1.0  # seconds


# ── Provider Cell Payload ────────────────────────────────────────────


@dataclass(frozen=True)
class ProviderPayload:
    """Payload for a provider MahaCellUnified."""

    name: str
    provider: LLMProvider
    model: str
    daily_call_limit: int = 0  # 0 = unlimited
    daily_token_limit: int = 0  # 0 = unlimited
    cost_per_mtok_input: float = 0.0
    calls_today: int = 0
    tokens_today: int = 0
    supports_tools: bool = False  # structured tool-calling support


def _is_transient(error: Exception) -> bool:
    """Check if an error is transient (worth retrying)."""
    error_str = str(error).lower()
    return any(hint in error_str for hint in _TRANSIENT_ERRORS)


def _normalize_usage(raw_usage: object) -> LLMUsage:
    """Normalize vendor-specific usage to LLMUsage at the adapter boundary.

    Handles: OpenAI (prompt_tokens/completion_tokens),
             Anthropic (input_tokens/output_tokens), and mixed formats.
    """
    if raw_usage is None:
        return LLMUsage()
    inp = getattr(raw_usage, "input_tokens", 0) or getattr(raw_usage, "prompt_tokens", 0) or 0
    out = getattr(raw_usage, "output_tokens", 0) or getattr(raw_usage, "completion_tokens", 0) or 0
    return LLMUsage(input_tokens=inp, output_tokens=out)


@dataclass
class ProviderChamber:
    """LLM provider selection via real MahaCellUnified resonance.

    Each provider is a MahaCellUnified with ProviderPayload.
    Sorted by prana (highest first = free/available first).
    On failure, integrity degrades; next provider is tried.

    CircuitBreaker (per-cell): skips a provider for 30s after 5 failures/60s.
    FeedbackProtocol: records success/failure signals for pattern detection.
    """

    _cells: list[MahaCellUnified[ProviderPayload]] = field(default_factory=list)
    _breakers: dict[str, CircuitBreaker] = field(default_factory=dict)
    _last_reset: date = field(default_factory=date.today)
    _total_calls: int = 0
    _total_failures: int = 0
    _quota: OperationalQuota = field(default_factory=OperationalQuota)
    _feedback: FeedbackProtocol | None = None

    def add_provider(
        self,
        name: str,
        provider: LLMProvider,
        model: str,
        source_address: int,
        prana: int = _PRANA_FREE,
        daily_call_limit: int = 0,
        daily_token_limit: int = 0,
        cost_per_mtok: float = 0.0,
        supports_tools: bool = False,
    ) -> None:
        """Add a provider as a real MahaCellUnified."""
        header = MahaHeader.create(
            source=source_address,
            target=0,
            operation=hash(name) & 0xFFFF,
        )
        lifecycle = CellLifecycleState(
            prana=prana,
            integrity=COSMIC_FRAME,
            cycle=0,
            is_active=True,
        )
        payload = ProviderPayload(
            name=name,
            provider=provider,
            model=model,
            daily_call_limit=daily_call_limit,
            daily_token_limit=daily_token_limit,
            cost_per_mtok_input=cost_per_mtok,
            supports_tools=supports_tools,
        )
        cell: MahaCellUnified[ProviderPayload] = MahaCellUnified(
            header=header,
            lifecycle=lifecycle,
            payload=payload,
        )
        self._cells.append(cell)
        self._breakers[name] = CircuitBreaker(CircuitBreakerConfig())
        logger.info("Added provider '%s' (model=%s, prana=%d)", name, model, prana)

    def set_feedback(self, feedback: FeedbackProtocol) -> None:
        """Wire FeedbackProtocol for outcome tracking."""
        self._feedback = feedback

    def _apply_feedback_penalty(
        self,
        cells: list[MahaCellUnified[ProviderPayload]],
    ) -> list[MahaCellUnified[ProviderPayload]]:
        """Deprioritize providers with high failure rates.

        Feedback-based soft penalty: providers with >60% failure rate
        are moved to end of sort order (still available, just tried last).
        """
        if not self._feedback:
            return cells

        clean: list[MahaCellUnified[ProviderPayload]] = []
        warned: list[MahaCellUnified[ProviderPayload]] = []
        for cell in cells:
            warning = self._feedback.should_warn(
                cell.payload.name,
                {"model": cell.payload.model},
            )
            if warning:
                warned.append(cell)
                logger.debug("Feedback penalty: %s (%s)", cell.payload.name, warning)
            else:
                clean.append(cell)

        return clean + warned

    def _sorted_providers(
        self,
        *,
        tier: str = "",
        has_tools: bool = False,
    ) -> list[MahaCellUnified[ProviderPayload]]:
        """Sort alive providers by tier + feedback penalty."""
        alive = [c for c in self._cells if c.is_alive]

        if tier == "pro":
            alive.sort(key=lambda c: c.payload.cost_per_mtok_input, reverse=True)
        elif tier == "flash":
            alive.sort(key=lambda c: c.payload.cost_per_mtok_input)
        elif has_tools:
            alive.sort(
                key=lambda c: (c.payload.supports_tools, c.lifecycle.prana),
                reverse=True,
            )
        else:
            alive.sort(key=lambda c: c.lifecycle.prana, reverse=True)

        return self._apply_feedback_penalty(alive)

    def invoke(self, **kwargs: object) -> NormalizedResponse | None:
        """Try provider cells in tier-aware order until one succeeds.

        Returns NormalizedResponse or None if all providers exhausted.
        """
        self._maybe_reset_daily()
        tier = str(kwargs.pop("tier", ""))
        prefer_capable = bool(kwargs.pop("prefer_capable", False))
        if prefer_capable and not tier:
            tier = "pro"

        try:
            self._quota.check_before_request(
                estimated_tokens=int(kwargs.get("max_tokens", 4096)),  # type: ignore[arg-type]
                operation="llm_invoke",
            )
        except QuotaExceededError as e:
            logger.warning("Quota exceeded — blocking request: %s", e)
            return None

        alive = self._sorted_providers(tier=tier, has_tools=bool(kwargs.get("tools")))

        for cell in alive:
            payload: ProviderPayload = cell.payload
            if not self._is_within_quota(payload):
                logger.debug("'%s' over quota, skipping", payload.name)
                continue

            breaker = self._breakers.get(payload.name)
            if breaker:
                can_exec, reason = breaker.can_execute()
                if not can_exec:
                    logger.info("'%s' circuit breaker OPEN (%s), skipping", payload.name, reason)
                    continue

            if cell.signal(payload.name) is None:
                logger.info("'%s' membrane too weak (integrity=%d), skipping", payload.name, cell.lifecycle.integrity)
                continue

            call_kwargs = dict(kwargs)
            call_kwargs["model"] = payload.model
            call_kwargs.pop("max_retries", None)

            last_error: Exception | None = None
            t0 = time.monotonic()
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    response = payload.provider.invoke(**call_kwargs)
                    duration_ms = (time.monotonic() - t0) * 1000

                    usage = response.usage
                    self._record_call_success(
                        cell,
                        breaker,
                        usage.input_tokens,
                        usage.output_tokens,
                        duration_ms,
                    )

                    logger.debug(
                        "'%s' responded (tokens: %d+%d, prana: %d, cycle: %d)",
                        payload.name,
                        usage.input_tokens,
                        usage.output_tokens,
                        cell.lifecycle.prana,
                        cell.lifecycle.cycle,
                    )
                    return response

                except Exception as e:
                    last_error = e
                    if attempt < _MAX_RETRIES and _is_transient(e):
                        delay = _RETRY_BASE_DELAY * (2**attempt)
                        logger.info(
                            "'%s' transient error (%s), retry %d/%d in %.1fs",
                            payload.name,
                            e,
                            attempt + 1,
                            _MAX_RETRIES,
                            delay,
                        )
                        time.sleep(delay)
                        continue
                    break  # non-transient or retries exhausted → next provider

            if last_error is not None:
                duration_ms = (time.monotonic() - t0) * 1000
                self._record_call_failure(cell, breaker, last_error, duration_ms)
                logger.info(
                    "'%s' failed (%s: %s), integrity->%d, prana->%d, trying next",
                    payload.name,
                    type(last_error).__name__,
                    last_error,
                    cell.lifecycle.integrity,
                    cell.lifecycle.prana,
                )
                continue

        alive_count = sum(1 for c in self._cells if c.is_alive)
        logger.error(
            "ALL providers exhausted (%d total, %d alive, %d failures)",
            len(self._cells), alive_count, self._total_failures,
        )
        return None

    def invoke_stream(self, **kwargs: object) -> Iterator[StreamDelta]:
        """Streaming invoke — yields StreamDelta chunks."""
        self._maybe_reset_daily()
        kwargs.pop("prefer_capable", None)

        try:
            self._quota.check_before_request(
                estimated_tokens=int(kwargs.get("max_tokens", 4096)),  # type: ignore[arg-type]
                operation="llm_stream",
            )
        except QuotaExceededError as e:
            logger.warning("Quota exceeded — blocking stream: %s", e)
            return

        alive = self._sorted_providers(has_tools=bool(kwargs.get("tools")))

        for cell in alive:
            payload: ProviderPayload = cell.payload
            if not self._is_within_quota(payload):
                continue

            breaker = self._breakers.get(payload.name)
            if breaker:
                can_exec, reason = breaker.can_execute()
                if not can_exec:
                    logger.info("'%s' circuit breaker OPEN (%s), skipping stream", payload.name, reason)
                    continue

            if cell.signal(payload.name) is None:
                continue

            t0 = time.monotonic()

            if not isinstance(payload.provider, StreamingProvider):
                logger.debug("'%s' lacks invoke_stream, falling back to non-streaming", payload.name)
                call_kwargs = dict(kwargs)
                call_kwargs["model"] = payload.model
                call_kwargs.pop("max_retries", None)
                try:
                    response = payload.provider.invoke(**call_kwargs)
                    duration_ms = (time.monotonic() - t0) * 1000
                    self._record_call_success(
                        cell,
                        breaker,
                        response.usage.input_tokens,
                        response.usage.output_tokens,
                        duration_ms,
                    )
                    if response.content:
                        yield StreamDelta(type="text_delta", text=response.content)
                    yield StreamDelta(type="done", response=response)
                    return
                except Exception as e:
                    duration_ms = (time.monotonic() - t0) * 1000
                    self._record_call_failure(cell, breaker, e, duration_ms)
                    logger.info("'%s' failed streaming fallback: %s", payload.name, e)
                    continue

            call_kwargs = dict(kwargs)
            call_kwargs["model"] = payload.model
            call_kwargs.pop("max_retries", None)

            try:
                for delta in payload.provider.invoke_stream(**call_kwargs):
                    if delta.type == "done":
                        duration_ms = (time.monotonic() - t0) * 1000
                        usage = delta.response.usage if delta.response else LLMUsage()
                        self._record_call_success(
                            cell,
                            breaker,
                            usage.input_tokens,
                            usage.output_tokens,
                            duration_ms,
                        )
                    yield delta
                return

            except Exception as e:
                duration_ms = (time.monotonic() - t0) * 1000
                self._record_call_failure(cell, breaker, e, duration_ms)
                logger.info("'%s' streaming failed: %s, trying next", payload.name, e)
                continue

        alive_count = sum(1 for c in self._cells if c.is_alive)
        logger.error(
            "ALL providers exhausted for streaming (%d total, %d alive, %d failures)",
            len(self._cells), alive_count, self._total_failures,
        )

    @property
    def quota(self) -> OperationalQuota:
        """Access the operational quota manager."""
        return self._quota

    def stats(self) -> dict[str, object]:
        result: dict[str, object] = {
            "providers": [
                {
                    "name": c.payload.name,
                    "model": c.payload.model,
                    "prana": c.lifecycle.prana,
                    "integrity": c.lifecycle.integrity,
                    "cycle": c.lifecycle.cycle,
                    "alive": c.is_alive,
                    "breaker": self._breakers[c.payload.name].get_status()
                    if c.payload.name in self._breakers
                    else None,
                }
                for c in self._cells
            ],
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "quota": self._quota.get_status(),
        }
        if self._feedback:
            fb_stats = self._feedback.get_stats()
            result["feedback"] = {
                "total_signals": fb_stats.total_signals,
                "success_rate": fb_stats.success_rate,
                "failure_patterns": [
                    {"provider": p.command, "error": p.error_pattern[:80], "frequency": p.frequency}
                    for p in self._feedback.get_failure_patterns()[:5]
                ],
            }
        return result

    def _record_call_success(
        self,
        cell: MahaCellUnified[ProviderPayload],
        breaker: CircuitBreaker | None,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
    ) -> None:
        """Record a successful provider call."""
        if breaker:
            # TODO(steward-protocol): Add CircuitBreaker.record_success() public API.
            # ProviderChamber bypasses call() for custom orchestration.
            breaker._record_success()

        total_tokens = input_tokens + output_tokens
        cell.metabolize(-total_tokens)
        self._total_calls += 1

        cost = total_tokens / 1_000_000 * cell.payload.cost_per_mtok_input
        self._quota.record_request(
            tokens_used=total_tokens,
            cost_usd=cost,
            operation=f"llm:{cell.payload.name}",
        )

        if self._feedback:
            self._feedback.signal_success(
                cell.payload.name,
                {"model": cell.payload.model, "cell_prana": cell.lifecycle.prana},
                duration_ms=duration_ms,
            )

    def _record_call_failure(
        self,
        cell: MahaCellUnified[ProviderPayload],
        breaker: CircuitBreaker | None,
        error: Exception | str,
        duration_ms: float,
    ) -> None:
        """Record a failed provider call."""
        self._total_failures += 1

        if breaker:
            # TODO(steward-protocol): Add CircuitBreaker.record_failure() public API.
            err = error if isinstance(error, Exception) else Exception(error)
            breaker._record_failure(err)

        cell.lifecycle.integrity = max(0, cell.lifecycle.integrity - (COSMIC_FRAME // 10))
        cell.metabolize(0)

        if self._feedback:
            error_str = f"{type(error).__name__}: {error}" if isinstance(error, Exception) else str(error)
            self._feedback.signal_failure(
                cell.payload.name,
                error_str,
                {"model": cell.payload.model, "cell_prana": cell.lifecycle.prana},
                duration_ms=duration_ms,
            )

    @staticmethod
    def _is_within_quota(payload: ProviderPayload) -> bool:
        if payload.daily_call_limit and payload.calls_today >= payload.daily_call_limit:
            return False
        if payload.daily_token_limit and payload.tokens_today >= payload.daily_token_limit:
            return False
        return True

    def _maybe_reset_daily(self) -> None:
        """Daily reset — restore all cells to genesis state."""
        today = date.today()
        if today > self._last_reset:
            for cell in self._cells:
                cell.lifecycle.prana = _PRANA_FREE
                cell.lifecycle.integrity = COSMIC_FRAME
                cell.lifecycle.cycle = 0
                cell.lifecycle.is_active = True
            for breaker in self._breakers.values():
                breaker.reset()
            self._last_reset = today
            logger.info("Daily reset — all provider cells reborn (prana=%d)", _PRANA_FREE)

    def __len__(self) -> int:
        return len(self._cells)
