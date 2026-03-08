"""
ProviderChamber — Multi-LLM provider failover with real substrate cells.

Each LLM provider is a MahaCellUnified with prana-ordered priority.
Free providers have more prana = tried first. On failure, integrity
degrades and the next provider is tried.

Adapted from agent-city/city/sankirtan.py. This is the canonical
location — agent-city can later import from here.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date

from vibe_core.mahamantra.protocols._header import MahaHeader
from vibe_core.mahamantra.protocols._seed import COSMIC_FRAME, MAHA_QUANTUM
from vibe_core.mahamantra.substrate.cell_system.cell import (
    CellLifecycleState,
    MahaCellUnified,
)
from vibe_core.runtime.quota_manager import OperationalQuota, QuotaExceededError, QuotaLimits

from typing import Iterator

from steward.types import LLMProvider

logger = logging.getLogger("STEWARD.PROVIDER")

# ── Provider Source Addresses (deterministic, SSOT-derived) ──────────

_ADDR_GOOGLE = MAHA_QUANTUM * 10      # 1370
_ADDR_MISTRAL = MAHA_QUANTUM * 11     # 1507
_ADDR_DEEPSEEK = MAHA_QUANTUM * 12    # 1644
_ADDR_ANTHROPIC = MAHA_QUANTUM * 13   # 1781

# ── Prana Budgets ────────────────────────────────────────────────────

_PRANA_FREE = MAHA_QUANTUM * 100      # 13700 (free tier = full energy)
_PRANA_CHEAP = MAHA_QUANTUM * 10      # 1370  (paid = less energy = lower priority)

# Transient errors that warrant retry (not provider switch)
_TRANSIENT_ERRORS = (
    "timeout", "timed out", "rate limit", "429", "503", "502",
    "connection reset", "connection refused", "temporary",
    "overloaded", "capacity", "retry",
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
    daily_call_limit: int = 0     # 0 = unlimited
    daily_token_limit: int = 0    # 0 = unlimited
    cost_per_mtok_input: float = 0.0
    calls_today: int = 0
    tokens_today: int = 0
    supports_tools: bool = False  # structured tool-calling support


@dataclass
class ProviderChamber:
    """LLM provider selection via real MahaCellUnified resonance.

    Each provider is a MahaCellUnified with ProviderPayload.
    Sorted by prana (highest first = free/available first).
    On failure, integrity degrades; next provider is tried.
    """

    _cells: list[MahaCellUnified[ProviderPayload]] = field(default_factory=list)
    _last_reset: date = field(default_factory=date.today)
    _total_calls: int = 0
    _total_failures: int = 0
    _quota: OperationalQuota = field(default_factory=OperationalQuota)

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
        logger.info("Added provider '%s' (model=%s, prana=%d)", name, model, prana)

    def invoke(self, **kwargs: object) -> object | None:
        """Try provider cells in prana order until one succeeds.

        Each cell uses its own model. Caller's model kwarg is stripped.
        Supports `prefer_capable=True` kwarg to invert prana ordering
        (use most capable/expensive provider first for complex tasks).

        Returns LLMResponse or None if all providers exhausted.
        """
        self._maybe_reset_daily()
        prefer_capable = bool(kwargs.pop("prefer_capable", False))

        # Pre-flight quota check (OperationalQuota from substrate)
        try:
            self._quota.check_before_request(
                estimated_tokens=int(kwargs.get("max_tokens", 4096)),  # type: ignore[arg-type]
                operation="llm_invoke",
            )
        except QuotaExceededError as e:
            logger.warning("Quota exceeded — blocking request: %s", e)
            return None

        alive = [c for c in self._cells if c.is_alive]
        has_tools = bool(kwargs.get("tools"))

        if prefer_capable:
            # Complex task: sort by cost (highest = most capable first)
            alive.sort(key=lambda c: c.payload.cost_per_mtok_input, reverse=True)
            logger.debug("Adaptive routing: prefer_capable → cost-ordered")
        elif has_tools:
            # Tool-calling: prefer providers that support structured tools
            alive.sort(
                key=lambda c: (c.payload.supports_tools, c.lifecycle.prana),
                reverse=True,
            )
            logger.debug("Tool-calling: preferring tool-capable providers")
        else:
            alive.sort(key=lambda c: c.lifecycle.prana, reverse=True)

        for cell in alive:
            payload: ProviderPayload = cell.payload
            if not self._is_within_quota(payload):
                logger.debug("'%s' over quota, skipping", payload.name)
                continue

            # Membrane gate: signal() checks integrity before accepting work.
            # Returns None if membrane too damaged — skip this provider.
            if cell.signal(payload.name) is None:
                logger.info("'%s' membrane too weak (integrity=%d), skipping",
                            payload.name, cell.lifecycle.integrity)
                continue

            call_kwargs = dict(kwargs)
            call_kwargs["model"] = payload.model
            call_kwargs.pop("max_retries", None)

            last_error: Exception | None = None
            for attempt in range(_MAX_RETRIES + 1):
                try:
                    response = payload.provider.invoke(**call_kwargs)

                    # Track usage
                    input_tokens = 0
                    output_tokens = 0
                    if hasattr(response, "usage") and response.usage:  # type: ignore[attr-defined]
                        usage = response.usage  # type: ignore[attr-defined]
                        input_tokens = (
                            getattr(usage, "input_tokens", 0)
                            or getattr(usage, "prompt_tokens", 0)
                        )
                        output_tokens = (
                            getattr(usage, "output_tokens", 0)
                            or getattr(usage, "completion_tokens", 0)
                        )

                    # Cell lifecycle: metabolize with token cost as energy drain.
                    # metabolize() handles: METABOLIC_COST decay, age cycling,
                    # starvation apoptosis, max-age apoptosis.
                    total_tokens = input_tokens + output_tokens
                    cell.metabolize(-total_tokens)  # negative = energy spent
                    self._total_calls += 1

                    # Post-flight quota recording
                    cost = total_tokens / 1_000_000 * payload.cost_per_mtok_input
                    self._quota.record_request(
                        tokens_used=total_tokens,
                        cost_usd=cost,
                        operation=f"llm:{payload.name}",
                    )

                    logger.debug(
                        "'%s' responded (tokens: %d+%d, prana: %d, cycle: %d)",
                        payload.name, input_tokens, output_tokens,
                        cell.lifecycle.prana, cell.lifecycle.cycle,
                    )
                    return response

                except Exception as e:
                    last_error = e
                    if attempt < _MAX_RETRIES and _is_transient(e):
                        delay = _RETRY_BASE_DELAY * (2 ** attempt)
                        logger.info(
                            "'%s' transient error (%s), retry %d/%d in %.1fs",
                            payload.name, e, attempt + 1, _MAX_RETRIES, delay,
                        )
                        time.sleep(delay)
                        continue
                    break  # non-transient or retries exhausted → next provider

            # All retries failed — metabolize failure as energy drain
            if last_error is not None:
                self._total_failures += 1
                # Integrity degrades on failure (membrane damage)
                cell.lifecycle.integrity = max(
                    0, cell.lifecycle.integrity - (COSMIC_FRAME // 10)
                )
                # Failed call still costs metabolic energy
                cell.metabolize(0)
                logger.info(
                    "'%s' failed (%s: %s), integrity->%d, prana->%d, trying next",
                    payload.name, type(last_error).__name__, last_error,
                    cell.lifecycle.integrity, cell.lifecycle.prana,
                )
                continue

        logger.warning("ALL providers exhausted or failed")
        return None

    def invoke_stream(self, **kwargs: object) -> Iterator[object]:
        """Streaming invoke — yields _StreamDelta chunks.

        Uses the first alive provider that supports invoke_stream.
        Falls back to non-streaming invoke if no provider supports streaming.
        Quota checks, retries, and cell lifecycle apply as in invoke().
        """
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

        alive = [c for c in self._cells if c.is_alive]
        has_tools = bool(kwargs.get("tools"))
        if has_tools:
            alive.sort(
                key=lambda c: (c.payload.supports_tools, c.lifecycle.prana),
                reverse=True,
            )
        else:
            alive.sort(key=lambda c: c.lifecycle.prana, reverse=True)

        for cell in alive:
            payload: ProviderPayload = cell.payload
            if not self._is_within_quota(payload):
                continue

            if cell.signal(payload.name) is None:
                continue

            # Check if provider supports streaming
            if not hasattr(payload.provider, "invoke_stream"):
                # Fall back to non-streaming
                call_kwargs = dict(kwargs)
                call_kwargs["model"] = payload.model
                call_kwargs.pop("max_retries", None)
                try:
                    response = payload.provider.invoke(**call_kwargs)
                    self._total_calls += 1
                    # Yield complete text as single delta
                    text = ""
                    if hasattr(response, "content"):
                        text = response.content if isinstance(response.content, str) else ""  # type: ignore[attr-defined]
                    if text:
                        yield _StreamDelta(type="text_delta", text=text)
                    yield _StreamDelta(type="done", response=response)
                    return
                except Exception as e:
                    self._total_failures += 1
                    cell.lifecycle.integrity = max(
                        0, cell.lifecycle.integrity - (COSMIC_FRAME // 10)
                    )
                    cell.metabolize(0)
                    logger.info("'%s' failed streaming fallback: %s", payload.name, e)
                    continue

            call_kwargs = dict(kwargs)
            call_kwargs["model"] = payload.model
            call_kwargs.pop("max_retries", None)

            try:
                for delta in payload.provider.invoke_stream(**call_kwargs):
                    if hasattr(delta, "type") and delta.type == "done":  # type: ignore[attr-defined]
                        # Track usage from final response
                        final_resp = getattr(delta, "response", None)
                        if final_resp:
                            usage = getattr(final_resp, "usage", None)
                            if usage:
                                input_t = getattr(usage, "prompt_tokens", 0) or 0
                                output_t = getattr(usage, "completion_tokens", 0) or 0
                                total = input_t + output_t
                                cell.metabolize(-total)
                                cost = total / 1_000_000 * payload.cost_per_mtok_input
                                self._quota.record_request(
                                    tokens_used=total, cost_usd=cost,
                                    operation=f"llm_stream:{payload.name}",
                                )
                        self._total_calls += 1
                    yield delta
                return  # Success

            except Exception as e:
                self._total_failures += 1
                cell.lifecycle.integrity = max(
                    0, cell.lifecycle.integrity - (COSMIC_FRAME // 10)
                )
                cell.metabolize(0)
                logger.info("'%s' streaming failed: %s, trying next", payload.name, e)
                continue

        logger.warning("ALL providers exhausted for streaming")

    @property
    def quota(self) -> OperationalQuota:
        """Access the operational quota manager."""
        return self._quota

    def stats(self) -> dict[str, object]:
        return {
            "providers": [
                {
                    "name": c.payload.name,
                    "model": c.payload.model,
                    "prana": c.lifecycle.prana,
                    "integrity": c.lifecycle.integrity,
                    "cycle": c.lifecycle.cycle,
                    "alive": c.is_alive,
                }
                for c in self._cells
            ],
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "quota": self._quota.get_status(),
        }

    @staticmethod
    def _is_within_quota(payload: ProviderPayload) -> bool:
        if payload.daily_call_limit and payload.calls_today >= payload.daily_call_limit:
            return False
        if payload.daily_token_limit and payload.tokens_today >= payload.daily_token_limit:
            return False
        return True

    def _maybe_reset_daily(self) -> None:
        """Daily reset — restore all cells to genesis state.

        Cells that apoptosed (from starvation or age) are reborn.
        This is the natural daily cycle: death → rebirth.
        """
        today = date.today()
        if today > self._last_reset:
            for cell in self._cells:
                cell.lifecycle.prana = _PRANA_FREE
                cell.lifecycle.integrity = COSMIC_FRAME
                cell.lifecycle.cycle = 0
                cell.lifecycle.is_active = True
            self._last_reset = today
            logger.info("Daily reset — all provider cells reborn (prana=%d)", _PRANA_FREE)

    def __len__(self) -> int:
        return len(self._cells)


def _is_transient(error: Exception) -> bool:
    """Check if an error is transient (worth retrying)."""
    error_str = str(error).lower()
    return any(hint in error_str for hint in _TRANSIENT_ERRORS)


# ── Adapters ─────────────────────────────────────────────────────────


class GoogleAdapter:
    """Normalizes messages -> prompt for GoogleProvider."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def invoke(self, **kwargs: object) -> object:
        messages = kwargs.pop("messages", None)  # type: ignore[arg-type]
        if messages and isinstance(messages, list):
            parts: list[str] = []
            for msg in messages:
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                    if content:
                        parts.append(str(content))
            prompt = "\n\n".join(parts)
            rf = kwargs.get("response_format")
            if isinstance(rf, dict) and rf.get("type") == "json_object":
                prompt += "\n\nIMPORTANT: Respond with valid JSON only. No markdown."
            kwargs["prompt"] = prompt
            kwargs["messages"] = messages
        elif "prompt" not in kwargs:
            kwargs["prompt"] = ""
        return self._provider.invoke(**kwargs)


class MistralAdapter:
    """OpenAI client -> LLMProvider.invoke() interface for Mistral."""

    def __init__(self, client: object) -> None:
        self._client = client

    def invoke(self, **kwargs: object) -> object:
        messages = kwargs.get("messages")
        model = str(kwargs.get("model", "mistral-small-latest"))
        max_tokens = int(kwargs.get("max_tokens", 512))  # type: ignore[arg-type]
        temperature = float(kwargs.get("temperature", 0.3))  # type: ignore[arg-type]
        response_format = kwargs.get("response_format")
        timeout = kwargs.get("timeout")

        if messages is None:
            prompt = str(kwargs.get("prompt", ""))
            messages = [{"role": "user", "content": prompt}]

        create_kwargs: dict[str, object] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format:
            create_kwargs["response_format"] = response_format
        if timeout:
            create_kwargs["timeout"] = timeout

        # Pass tools for structured tool-calling (OpenAI format)
        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = tools
            create_kwargs["tool_choice"] = "auto"

        response = self._client.chat.completions.create(**create_kwargs)  # type: ignore[attr-defined]
        return _AdapterResponse(response)

    def invoke_stream(self, **kwargs: object) -> Iterator[object]:
        """Stream LLM response, yielding _StreamDelta chunks.

        Each chunk has .type ("text_delta"|"tool_call_delta"|"done")
        and .text (for text_delta) or accumulated response (for done).
        """
        messages = kwargs.get("messages")
        model = str(kwargs.get("model", "mistral-small-latest"))
        max_tokens = int(kwargs.get("max_tokens", 512))  # type: ignore[arg-type]
        temperature = float(kwargs.get("temperature", 0.3))  # type: ignore[arg-type]
        timeout = kwargs.get("timeout")

        if messages is None:
            prompt = str(kwargs.get("prompt", ""))
            messages = [{"role": "user", "content": prompt}]

        create_kwargs: dict[str, object] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if timeout:
            create_kwargs["timeout"] = timeout

        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = tools
            create_kwargs["tool_choice"] = "auto"

        stream = self._client.chat.completions.create(**create_kwargs)  # type: ignore[attr-defined]

        # Accumulate full content + tool calls for final response
        full_text = ""
        tool_calls: list[object] = []
        usage = None

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None  # type: ignore[attr-defined]
            if delta and getattr(delta, "content", None):
                full_text += delta.content
                yield _StreamDelta(type="text_delta", text=delta.content)
            if delta and getattr(delta, "tool_calls", None):
                # Tool call deltas need assembly (OpenAI accumulation)
                for tc_delta in delta.tool_calls:
                    idx = getattr(tc_delta, "index", 0)
                    while len(tool_calls) <= idx:
                        tool_calls.append(_ToolCallAccumulator())
                    tool_calls[idx].accumulate(tc_delta)  # type: ignore[attr-defined]
            if hasattr(chunk, "usage") and chunk.usage is not None:  # type: ignore[attr-defined]
                usage = chunk.usage  # type: ignore[attr-defined]

        # Build final response object compatible with _AdapterResponse
        yield _StreamDelta(
            type="done",
            response=_StreamedResponse(
                text=full_text,
                tool_calls=[tc.build() for tc in tool_calls] if tool_calls else None,  # type: ignore[attr-defined]
                usage=usage,
            ),
        )


@dataclass
class _StreamDelta:
    """A streaming chunk from invoke_stream."""

    type: str  # "text_delta" | "done"
    text: str = ""
    response: object = None  # Final _StreamedResponse (on type="done")


class _ToolCallAccumulator:
    """Accumulates tool call deltas from OpenAI streaming."""

    def __init__(self) -> None:
        self.id = ""
        self.name = ""
        self.arguments = ""

    def accumulate(self, delta: object) -> None:
        if hasattr(delta, "id") and delta.id:
            self.id = delta.id
        func = getattr(delta, "function", None)
        if func:
            if getattr(func, "name", None):
                self.name += func.name
            if getattr(func, "arguments", None):
                self.arguments += func.arguments

    def build(self) -> object:
        return _BuiltToolCall(id=self.id, name=self.name, arguments=self.arguments)


@dataclass
class _BuiltToolCall:
    """Assembled tool call from streaming deltas."""

    id: str
    name: str
    arguments: str

    @property
    def function(self) -> object:
        return self


@dataclass
class _StreamedResponse:
    """Final response assembled from streaming chunks."""

    text: str
    tool_calls: list | None = None
    usage: object = None

    @property
    def content(self) -> str:
        return self.text


@dataclass
class _AdapterResponse:
    """Duck-type LLMResponse from OpenAI response."""

    _raw: object

    @property
    def content(self) -> str:
        return self._raw.choices[0].message.content or ""  # type: ignore[attr-defined]

    @property
    def tool_calls(self) -> list | None:
        choice = self._raw.choices[0].message  # type: ignore[attr-defined]
        return getattr(choice, "tool_calls", None)

    @property
    def usage(self) -> object | None:
        return getattr(self._raw, "usage", None)


class AnthropicAdapter:
    """Converts steward format to Anthropic Messages API format.

    Anthropic differences from OpenAI:
    - System prompt is a separate parameter, not a message
    - Tools use input_schema (not parameters wrapped in function)
    - Tool use is in content blocks (type=tool_use), not tool_calls field
    - Tool results are user messages with tool_result content blocks
    """

    def __init__(self, client: object) -> None:
        self._client = client

    def invoke(self, **kwargs: object) -> object:
        messages = kwargs.get("messages")
        model = str(kwargs.get("model", "claude-sonnet-4-20250514"))
        max_tokens = int(kwargs.get("max_tokens", 4096))  # type: ignore[arg-type]

        # Separate system prompt and convert messages
        system = ""
        api_messages: list[dict[str, object]] = []

        if isinstance(messages, list):
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                if role == "system":
                    system = str(msg.get("content", ""))
                elif role == "tool":
                    # Anthropic: tool results are user messages with tool_result blocks
                    api_messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": str(msg.get("tool_call_id", "")),
                            "content": str(msg.get("content", "")),
                        }],
                    })
                elif role == "assistant" and msg.get("tool_calls"):
                    # Anthropic: tool calls are content blocks on assistant message
                    content_blocks: list[dict[str, object]] = []
                    text = str(msg.get("content", ""))
                    if text:
                        content_blocks.append({"type": "text", "text": text})
                    tool_calls = msg.get("tool_calls")
                    if isinstance(tool_calls, list):
                        for tc in tool_calls:
                            if isinstance(tc, dict):
                                func = tc.get("function", {})
                                if isinstance(func, dict):
                                    content_blocks.append({
                                        "type": "tool_use",
                                        "id": tc.get("id", ""),
                                        "name": func.get("name", ""),
                                        "input": func.get("arguments", {}),
                                    })
                    api_messages.append({"role": "assistant", "content": content_blocks})
                else:
                    api_messages.append({"role": str(role), "content": msg.get("content", "")})

        # Convert tools to Anthropic format
        anthropic_tools: list[dict[str, object]] | None = None
        tools = kwargs.get("tools")
        if isinstance(tools, list):
            anthropic_tools = []
            for tool in tools:
                if isinstance(tool, dict) and tool.get("type") == "function":
                    func = tool.get("function")
                    if isinstance(func, dict):
                        anthropic_tools.append({
                            "name": func.get("name", ""),
                            "description": func.get("description", ""),
                            "input_schema": func.get("parameters", {}),
                        })

        create_kwargs: dict[str, object] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
        }
        if system:
            create_kwargs["system"] = system
        if anthropic_tools:
            create_kwargs["tools"] = anthropic_tools

        return self._client.messages.create(**create_kwargs)  # type: ignore[attr-defined]


# ── Chamber Builder ──────────────────────────────────────────────────


def _is_valid_key(key: str) -> bool:
    if not key:
        return False
    placeholders = ["your-", "xxx", "placeholder", "example", "test-key"]
    return not any(p in key.lower() for p in placeholders)


def build_chamber() -> ProviderChamber:
    """Build ProviderChamber from available API keys.

    Priority order (free first, cheapest last):
    1. Google Gemini (free tier) — if GOOGLE_API_KEY set
    2. Mistral (free experiment) — if MISTRAL_API_KEY set
    3. DeepSeek via OpenRouter (cheap paid) — if OPENROUTER_API_KEY set
    """
    chamber = ProviderChamber()

    # Cell 1: Google Gemini (FREE)
    google_key = os.environ.get("GOOGLE_API_KEY")
    if google_key and _is_valid_key(google_key):
        try:
            from vibe_core.runtime.providers.google import GoogleProvider

            raw_provider = GoogleProvider(api_key=google_key)
            adapter = GoogleAdapter(raw_provider)
            chamber.add_provider(
                name="google_flash",
                provider=adapter,
                model="gemini-2.5-flash",
                source_address=_ADDR_GOOGLE,
                prana=_PRANA_FREE,
                daily_call_limit=1000,
                cost_per_mtok=0.0,
            )
        except Exception as e:
            logger.warning("Google provider failed: %s", e)

    # Cell 2: Mistral (FREE experiment)
    mistral_key = os.environ.get("MISTRAL_API_KEY")
    if mistral_key and _is_valid_key(mistral_key):
        try:
            from openai import OpenAI

            client = OpenAI(api_key=mistral_key, base_url="https://api.mistral.ai/v1")
            adapter = MistralAdapter(client)
            chamber.add_provider(
                name="mistral",
                provider=adapter,
                model="mistral-small-latest",
                source_address=_ADDR_MISTRAL,
                prana=_PRANA_FREE,
                daily_call_limit=2880,
                daily_token_limit=30_000_000,
                cost_per_mtok=0.10,
                supports_tools=True,
            )
        except ImportError:
            logger.warning("openai package needed for Mistral")
        except Exception as e:
            logger.warning("Mistral provider failed: %s", e)

    # Cell 3: DeepSeek via OpenRouter (cheap paid fallback)
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key and _is_valid_key(openrouter_key):
        try:
            from vibe_core.runtime.providers.openrouter import OpenRouterProvider

            provider = OpenRouterProvider(api_key=openrouter_key)
            chamber.add_provider(
                name="deepseek",
                provider=provider,
                model="deepseek/deepseek-v3.2",
                source_address=_ADDR_DEEPSEEK,
                prana=_PRANA_CHEAP,
                daily_call_limit=0,
                cost_per_mtok=0.27,
                supports_tools=True,
            )
        except Exception as e:
            logger.warning("OpenRouter provider failed: %s", e)

    # Cell 4: Anthropic Claude (paid, highest capability)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key and _is_valid_key(anthropic_key):
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=anthropic_key)
            adapter = AnthropicAdapter(client)
            chamber.add_provider(
                name="claude",
                provider=adapter,
                model="claude-sonnet-4-20250514",
                source_address=_ADDR_ANTHROPIC,
                prana=_PRANA_CHEAP,  # paid = lower prana = tried after free
                daily_call_limit=0,
                cost_per_mtok=3.0,
                supports_tools=True,
            )
        except ImportError:
            logger.warning("anthropic package needed for Claude")
        except Exception as e:
            logger.warning("Anthropic provider failed: %s", e)

    if len(chamber) == 0:
        logger.warning("No providers — LLM calls will fail")
    else:
        logger.info("Chamber ready with %d providers", len(chamber))

    return chamber
