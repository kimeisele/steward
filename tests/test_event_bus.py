"""Tests for EventBus integration in steward."""

from __future__ import annotations

import asyncio

from tests.fakes import FakeLLM, FakeResponse

from steward.agent import StewardAgent
from steward.services import SVC_EVENT_BUS, boot
from steward.types import ToolUse
from vibe_core.di import ServiceRegistry
from vibe_core.mahamantra.substrate.services.event_bus import EventBus


# ── Tests ────────────────────────────────────────────────────────────


class TestEventBusWiring:
    def test_event_bus_registered_at_boot(self) -> None:
        """EventBus is registered in ServiceRegistry at boot."""
        boot()
        event_bus = ServiceRegistry.get(SVC_EVENT_BUS)
        assert event_bus is not None
        assert isinstance(event_bus, EventBus)

    def test_event_bus_rate_limiting_disabled_for_steward(self) -> None:
        """Steward's EventBus has rate limiting disabled (trusted agent)."""
        boot()
        event_bus = ServiceRegistry.get(SVC_EVENT_BUS)
        # steward agent should never be rate limited
        assert not event_bus.is_rate_limited("steward")

    def test_event_bus_stats_available(self) -> None:
        """EventBus stats are accessible."""
        boot()
        event_bus = ServiceRegistry.get(SVC_EVENT_BUS)
        stats = event_bus.get_stats()
        assert "total_events_emitted" in stats
        assert "total_subscribers" in stats


class TestEventBusEmission:
    def test_text_response_emits_thought_event(self) -> None:
        """Text response emits THOUGHT event to EventBus."""
        llm = FakeLLM([FakeResponse(content="Hello!")])
        agent = StewardAgent(provider=llm)

        event_bus: EventBus = ServiceRegistry.require(SVC_EVENT_BUS)
        initial_count = event_bus._event_count

        agent.run_sync("Hi")

        # Should have emitted at least one event (THOUGHT for text response)
        assert event_bus._event_count > initial_count

    def test_tool_call_emits_action_event(self) -> None:
        """Tool calls emit ACTION events to EventBus."""
        tc = ToolUse(id="call_1", name="bash", parameters={"command": "echo hi"})
        responses = [
            FakeResponse(content="", tool_calls=[tc]),
            FakeResponse(content="Done"),
        ]
        llm = FakeLLM(responses)
        agent = StewardAgent(provider=llm)

        event_bus: EventBus = ServiceRegistry.require(SVC_EVENT_BUS)
        initial_count = event_bus._event_count

        agent.run_sync("Run echo")

        # Should have emitted ACTION events for tool_call and tool_result
        assert event_bus._event_count > initial_count + 1

    def test_event_bus_history_populated(self) -> None:
        """Events appear in EventBus history."""
        llm = FakeLLM([FakeResponse(content="Result")])
        agent = StewardAgent(provider=llm)

        event_bus: EventBus = ServiceRegistry.require(SVC_EVENT_BUS)
        agent.run_sync("Test")

        history = event_bus.get_history(limit=10)
        assert len(history) >= 1
        # All events should be from steward agent
        assert all(e.agent_id == "steward" for e in history)

    def test_error_emits_error_event(self) -> None:
        """LLM errors emit ERROR events to EventBus."""

        class CrashLLM:
            def invoke(self, **kwargs: Any) -> Any:
                raise ConnectionError("network down")

        agent = StewardAgent(provider=CrashLLM())
        event_bus: EventBus = ServiceRegistry.require(SVC_EVENT_BUS)

        agent.run_sync("Do something")

        history = event_bus.get_history(limit=10)
        error_events = [e for e in history if e.event_type == "ERROR"]
        assert len(error_events) >= 1
