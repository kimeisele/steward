"""Tests for SignalBus integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from steward.agent import StewardAgent
from steward.services import SVC_SIGNAL_BUS, boot
from vibe_core.di import ServiceRegistry
from vibe_core.steward.bus import Signal, SignalBus, SignalType

# ── Fake LLM for signal tests ────────────────────────────────────────


@dataclass
class _FakeResponse:
    content: str = ""
    tool_calls: list | None = None
    usage: object | None = None


class _FakeLLM:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self._idx = 0

    def invoke(self, **kwargs: object) -> _FakeResponse:
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        return _FakeResponse(content="[exhausted]")


# ── Tests ─────────────────────────────────────────────────────────────


class TestSignalBusWiring:
    def test_bus_registered_at_boot(self):
        boot()
        bus: SignalBus = ServiceRegistry.require(SVC_SIGNAL_BUS)
        assert isinstance(bus, SignalBus)

    def test_bus_id(self):
        boot()
        bus: SignalBus = ServiceRegistry.require(SVC_SIGNAL_BUS)
        assert bus.bus_id == "steward.agent"

    def test_emit_and_subscribe(self):
        boot()
        bus: SignalBus = ServiceRegistry.require(SVC_SIGNAL_BUS)

        received: list[Signal] = []
        bus.subscribe("test", SignalType.AGENT_STATUS_UPDATE, lambda s: received.append(s))

        bus.emit(
            Signal(
                signal_type=SignalType.AGENT_STATUS_UPDATE,
                source_agent="steward",
                payload={"action": "test"},
            )
        )

        assert len(received) == 1
        assert received[0].payload["action"] == "test"


class TestAgentSignalEmission:
    def test_startup_signal_emitted(self):
        """Agent emits AGENT_STARTUP signal when created."""
        received: list[Signal] = []
        # Create agent — boot() creates the bus, then startup signal is emitted
        llm = _FakeLLM([])
        agent = StewardAgent(provider=llm)

        # Subscribe AFTER agent creation to test startup was emitted
        # We need to check the bus history instead
        bus: SignalBus = ServiceRegistry.require(SVC_SIGNAL_BUS)
        history = bus.get_signal_history(signal_type=SignalType.AGENT_STARTUP)
        assert len(history) == 1
        assert history[0].source_agent == "steward"
        assert "tools" in history[0].payload

    def test_agent_emits_signals_on_text(self):
        """Agent emits turn_complete signal for text response."""
        llm = _FakeLLM([_FakeResponse(content="Hello!")])
        agent = StewardAgent(provider=llm)

        bus: SignalBus = ServiceRegistry.require(SVC_SIGNAL_BUS)
        received: list[Signal] = []
        bus.subscribe("tracker", SignalType.AGENT_STATUS_UPDATE, lambda s: received.append(s))

        agent.run_sync("Hi")

        # Should have at least a turn_complete signal
        turn_signals = [s for s in received if s.payload.get("action") == "turn_complete"]
        assert len(turn_signals) == 1

    def test_turn_complete_includes_usage(self):
        """turn_complete signal includes token count."""
        llm = _FakeLLM([_FakeResponse(content="Hello!")])
        agent = StewardAgent(provider=llm)

        bus: SignalBus = ServiceRegistry.require(SVC_SIGNAL_BUS)
        received: list[Signal] = []
        bus.subscribe("tracker", SignalType.AGENT_STATUS_UPDATE, lambda s: received.append(s))

        agent.run_sync("Hi")

        turn_signals = [s for s in received if s.payload.get("action") == "turn_complete"]
        assert len(turn_signals) == 1
        # Usage info should be in payload
        assert "tokens" in turn_signals[0].payload
        assert "tool_calls" in turn_signals[0].payload

    def test_tool_call_signals_emitted(self):
        """Agent emits tool_call status signals during tool use."""

        @dataclass
        class _FakeToolCall:
            id: str = "c1"
            function: object = None

        @dataclass
        class _FakeFunc:
            name: str = "bash"
            arguments: dict = None  # type: ignore[assignment]

            def __post_init__(self):
                if self.arguments is None:
                    self.arguments = {"command": "echo test"}

        tc = _FakeToolCall(function=_FakeFunc())
        llm = _FakeLLM(
            [
                _FakeResponse(content="", tool_calls=[tc]),
                _FakeResponse(content="Done"),
            ]
        )
        agent = StewardAgent(provider=llm)

        bus: SignalBus = ServiceRegistry.require(SVC_SIGNAL_BUS)
        received: list[Signal] = []
        bus.subscribe("tracker", SignalType.AGENT_STATUS_UPDATE, lambda s: received.append(s))

        agent.run_sync("Run something")

        tool_signals = [s for s in received if s.payload.get("action") == "tool_call"]
        assert len(tool_signals) >= 1
        assert tool_signals[0].payload["tool"] == "bash"

    def test_agent_emits_error_signal(self):
        """Agent emits AGENT_ERROR signal when LLM returns None."""

        class FailLLM:
            def invoke(self, **kwargs: Any) -> None:
                raise RuntimeError("boom")

        agent = StewardAgent(provider=FailLLM())

        bus: SignalBus = ServiceRegistry.require(SVC_SIGNAL_BUS)
        errors: list[Signal] = []
        bus.subscribe("err_tracker", SignalType.AGENT_ERROR, lambda s: errors.append(s))

        result = agent.run_sync("Hello")
        assert "Error" in result
        assert len(errors) >= 1
