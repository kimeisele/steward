"""
Agent Bus — Signal and Event emission.

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
        return
    bus.emit(
        Signal(
            signal_type=SignalType.AGENT_STARTUP,
            source_agent="steward",
            payload={"tools": tools, "cwd": cwd},
        )
    )


def emit_signal(event: AgentEvent) -> None:
    """Translate AgentEvent to SignalBus signal (fire-and-forget)."""
    from vibe_core.steward.bus import Signal, SignalType

    bus = ServiceRegistry.get(SVC_SIGNAL_BUS)
    if bus is None:
        return

    if event.type == EventType.TOOL_CALL:
        bus.emit(
            Signal(
                signal_type=SignalType.AGENT_STATUS_UPDATE,
                source_agent="steward",
                payload={
                    "action": "tool_call",
                    "tool": event.tool_use.name if event.tool_use else "",
                },
            )
        )
    elif event.type == EventType.TOOL_RESULT:
        success = isinstance(event.content, ToolResult) and event.content.success
        bus.emit(
            Signal(
                signal_type=SignalType.AGENT_STATUS_UPDATE,
                source_agent="steward",
                payload={"action": "tool_result", "success": success},
            )
        )
    elif event.type == EventType.ERROR:
        bus.emit(
            Signal(
                signal_type=SignalType.AGENT_ERROR,
                source_agent="steward",
                payload={"error": str(event.content)},
            )
        )
    elif event.type == EventType.DONE:
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


def emit_event_bus(event: AgentEvent) -> None:
    """Emit to EventBus (Narada stream) for observability."""
    from vibe_core.mahamantra.substrate.event_types import EventType as SubstrateEventType

    event_bus = ServiceRegistry.get(SVC_EVENT_BUS)
    if event_bus is None:
        return

    if event.type == EventType.TOOL_CALL:
        event_bus.emit_sync(
            event_type=SubstrateEventType.ACTION,
            agent_id="steward",
            message=f"tool_call: {event.tool_use.name}" if event.tool_use else "tool_call",
        )
    elif event.type == EventType.TOOL_RESULT:
        success = isinstance(event.content, ToolResult) and event.content.success
        event_bus.emit_sync(
            event_type=SubstrateEventType.ACTION if success else SubstrateEventType.ERROR,
            agent_id="steward",
            message=f"tool_result: {'ok' if success else 'error'}",
        )
    elif event.type == EventType.ERROR:
        event_bus.emit_sync(
            event_type=SubstrateEventType.ERROR,
            agent_id="steward",
            message=f"error: {event.content}",
        )
    elif event.type == EventType.TEXT:
        event_bus.emit_sync(
            event_type=SubstrateEventType.THOUGHT,
            agent_id="steward",
            message="text_response",
        )


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
