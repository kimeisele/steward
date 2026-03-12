"""
Agent Bus — Signal and Event emission via O(1) dispatch.

Extracted from agent.py god class. All bus communication
goes through these functions. The agent delegates, not inlines.
"""

from __future__ import annotations

import logging

from steward.services import SVC_EVENT_BUS, SVC_SIGNAL_BUS
from steward.types import AgentEvent, EventType, ToolResult
from vibe_core.di import ServiceRegistry

logger = logging.getLogger("STEWARD.BUS")


def emit_startup(tools: list[str], cwd: str) -> None:
    """Emit AGENT_STARTUP signal."""
    from vibe_core.steward.bus import Signal, SignalType

    bus = ServiceRegistry.get(SVC_SIGNAL_BUS)
    if bus is None:
        logger.debug("SignalBus not registered — telemetry signals disabled")
        return

    event_bus = ServiceRegistry.get(SVC_EVENT_BUS)
    if event_bus is None:
        logger.debug("EventBus not registered — Narada stream disabled")
    bus.emit(
        Signal(
            signal_type=SignalType.AGENT_STARTUP,
            source_agent="steward",
            payload={"tools": tools, "cwd": cwd},
        )
    )


# ── Signal Dispatch (SignalBus) ──────────────────────────────────


def _signal_tool_call(event: AgentEvent, bus: object) -> None:
    from vibe_core.steward.bus import Signal, SignalType

    bus.emit(
        Signal(
            signal_type=SignalType.AGENT_STATUS_UPDATE,
            source_agent="steward",
            payload={"action": "tool_call", "tool": event.tool_use.name if event.tool_use else ""},
        )
    )


def _signal_tool_result(event: AgentEvent, bus: object) -> None:
    from vibe_core.steward.bus import Signal, SignalType

    success = isinstance(event.content, ToolResult) and event.content.success
    bus.emit(
        Signal(
            signal_type=SignalType.AGENT_STATUS_UPDATE,
            source_agent="steward",
            payload={"action": "tool_result", "success": success},
        )
    )


def _signal_error(event: AgentEvent, bus: object) -> None:
    from vibe_core.steward.bus import Signal, SignalType

    bus.emit(
        Signal(
            signal_type=SignalType.AGENT_ERROR,
            source_agent="steward",
            payload={"error": str(event.content)},
        )
    )


def _signal_done(event: AgentEvent, bus: object) -> None:
    from vibe_core.steward.bus import Signal, SignalType

    payload: dict[str, object] = {"action": "turn_complete"}
    if event.usage:
        payload["tokens"] = event.usage.total_tokens
        payload["tool_calls"] = event.usage.tool_calls
    bus.emit(
        Signal(
            signal_type=SignalType.AGENT_STATUS_UPDATE,
            source_agent="steward",
            payload=payload,
        )
    )


_SIGNAL_DISPATCH: dict[EventType, object] = {
    EventType.TOOL_CALL: _signal_tool_call,
    EventType.TOOL_RESULT: _signal_tool_result,
    EventType.ERROR: _signal_error,
    EventType.DONE: _signal_done,
}


def emit_signal(event: AgentEvent) -> None:
    """Translate AgentEvent to SignalBus signal — O(1) dispatch."""
    bus = ServiceRegistry.get(SVC_SIGNAL_BUS)
    if bus is None:
        return
    handler = _SIGNAL_DISPATCH.get(event.type)
    if handler is not None:
        handler(event, bus)


# ── Event Bus Dispatch (Narada) ──────────────────────────────────


def _narada_tool_call(event: AgentEvent, ebus: object) -> None:
    from vibe_core.mahamantra.substrate.event_types import EventType as SubstrateEventType

    ebus.emit_sync(
        event_type=SubstrateEventType.ACTION,
        agent_id="steward",
        message=f"tool_call: {event.tool_use.name}" if event.tool_use else "tool_call",
    )


def _narada_tool_result(event: AgentEvent, ebus: object) -> None:
    from vibe_core.mahamantra.substrate.event_types import EventType as SubstrateEventType

    success = isinstance(event.content, ToolResult) and event.content.success
    ebus.emit_sync(
        event_type=SubstrateEventType.ACTION if success else SubstrateEventType.ERROR,
        agent_id="steward",
        message=f"tool_result: {'ok' if success else 'error'}",
    )


def _narada_error(event: AgentEvent, ebus: object) -> None:
    from vibe_core.mahamantra.substrate.event_types import EventType as SubstrateEventType

    ebus.emit_sync(
        event_type=SubstrateEventType.ERROR,
        agent_id="steward",
        message=f"error: {event.content}",
    )


def _narada_text(event: AgentEvent, ebus: object) -> None:
    from vibe_core.mahamantra.substrate.event_types import EventType as SubstrateEventType

    ebus.emit_sync(
        event_type=SubstrateEventType.THOUGHT,
        agent_id="steward",
        message="text_response",
    )


_NARADA_DISPATCH: dict[EventType, object] = {
    EventType.TOOL_CALL: _narada_tool_call,
    EventType.TOOL_RESULT: _narada_tool_result,
    EventType.ERROR: _narada_error,
    EventType.TEXT: _narada_text,
}


def emit_event_bus(event: AgentEvent) -> None:
    """Emit to EventBus (Narada stream) — O(1) dispatch."""
    event_bus = ServiceRegistry.get(SVC_EVENT_BUS)
    if event_bus is None:
        return
    handler = _NARADA_DISPATCH.get(event.type)
    if handler is not None:
        handler(event, event_bus)


def emit_anomaly(health: float, guna: str, beat_number: int) -> None:
    """Emit Cetana anomaly signal."""
    from vibe_core.steward.bus import Signal, SignalType

    bus = ServiceRegistry.get(SVC_SIGNAL_BUS)
    if bus is None:
        return
    bus.emit(
        Signal(
            signal_type=SignalType.AGENT_ERROR,
            source_agent="steward",
            payload={
                "anomaly": True,
                "health": health,
                "guna": guna,
                "consecutive": beat_number,
            },
        )
    )
