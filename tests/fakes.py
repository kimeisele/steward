"""
Shared test fakes — canonical implementations for all test files.

Import from here instead of redefining FakeUsage/FakeResponse/FakeLLM
in every test file. Keeps test infrastructure DRY.

Usage:
    from tests.fakes import FakeLLM, FakeResponse, FakeUsage
"""

from __future__ import annotations

from typing import Any

from steward.types import LLMUsage, NormalizedResponse, StreamDelta

# ── Type Aliases ──────────────────────────────────────────────────────
# The real types already have sensible defaults. These aliases give
# test files the familiar names without redefining dataclasses.

FakeUsage = LLMUsage
FakeResponse = NormalizedResponse


# ── FakeLLM ───────────────────────────────────────────────────────────


class FakeLLM:
    """Deterministic fake LLM for tests. Never calls real APIs.

    Does NOT implement invoke_stream — the engine will use the
    non-streaming invoke() path. Use FakeStreamingLLM for streaming tests.

    Usage:
        llm = FakeLLM([NormalizedResponse(content="ok")])
        resp = llm.invoke(messages=[...])
        assert resp.content == "ok"
    """

    def __init__(self, responses: list[NormalizedResponse] | None = None) -> None:
        self._responses = list(responses) if responses is not None else [NormalizedResponse(content="ok")]
        self._call_count = 0
        self.calls: list[dict[str, object]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last_call(self) -> dict[str, object] | None:
        return self.calls[-1] if self.calls else None

    def invoke(self, **kwargs: Any) -> NormalizedResponse:
        self.calls.append(kwargs)
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        return NormalizedResponse(content="[no more responses]")

    def reset(self) -> None:
        """Reset call history and restart response sequence."""
        self._call_count = 0
        self.calls.clear()


class FakeStreamingLLM(FakeLLM):
    """FakeLLM with streaming support. Engine will use invoke_stream()."""

    def invoke_stream(self, **kwargs: Any) -> list[StreamDelta]:
        resp = self.invoke(**kwargs)
        events: list[StreamDelta] = []
        if resp.content:
            events.append(StreamDelta(type="text_delta", text=resp.content))
        events.append(StreamDelta(type="done", response=resp))
        return events
