"""
Steward Service Wiring — DI bootstrap for the superagent.

Uses steward-protocol's ServiceRegistry for dependency injection.
All services registered at boot time with SVC_ constants.

    boot(tools=[...], provider=chamber)
    registry = ServiceRegistry.get(SVC_TOOL_REGISTRY)
"""

from __future__ import annotations

import logging

from vibe_core.di import ServiceRegistry
from vibe_core.mahamantra.adapters.attention import MahaAttention
from vibe_core.runtime.tool_safety_guard import ToolSafetyGuard
from vibe_core.tools.tool_protocol import Tool
from vibe_core.tools.tool_registry import ToolRegistry

from steward.types import LLMProvider

logger = logging.getLogger("STEWARD.SERVICES")


# ── SVC_ Constants (marker types for ServiceRegistry keys) ───────────


class SVC_TOOL_REGISTRY:
    """ToolRegistry — tool lookup and execution."""


class SVC_SAFETY_GUARD:
    """ToolSafetyGuard — Iron Dome protection."""


class SVC_ATTENTION:
    """MahaAttention — O(1) tool routing."""


class SVC_PROVIDER:
    """ProviderChamber — multi-LLM failover."""


class SVC_SIGNAL_BUS:
    """SignalBus — agent event communication."""


class SVC_MEMORY:
    """MemoryProtocol — persistent agent memory (Chitta)."""


class SVC_EVENT_BUS:
    """EventBus — real-time event stream with Sudarshana rate limiting."""


class SVC_PROMPT_CONTEXT:
    """PromptContext — dynamic context resolvers for system prompt."""


# ── Boot ─────────────────────────────────────────────────────────────


def boot(
    tools: list[Tool] | None = None,
    provider: LLMProvider | None = None,
    cwd: str | None = None,
) -> type[ServiceRegistry]:
    """Wire all steward services into ServiceRegistry.

    Args:
        tools: Tool instances to register
        provider: LLM provider (ProviderChamber or single provider)

    Returns:
        ServiceRegistry class (call .get(SVC_*) to retrieve services)
    """
    ServiceRegistry.reset_all()

    # 1. ToolRegistry
    registry = ToolRegistry()
    if tools:
        for tool in tools:
            registry.register(tool)
    ServiceRegistry.register(SVC_TOOL_REGISTRY, registry)

    # 2. ToolSafetyGuard (Iron Dome)
    guard = ToolSafetyGuard()
    ServiceRegistry.register(SVC_SAFETY_GUARD, guard)

    # 3. MahaAttention (O(1) tool routing)
    attention = MahaAttention()
    if tools:
        for tool in tools:
            attention.memorize(tool.name, tool)
    ServiceRegistry.register(SVC_ATTENTION, attention)

    # 4. Provider (if given)
    if provider is not None:
        ServiceRegistry.register(SVC_PROVIDER, provider)

    # 5. SignalBus (agent event communication)
    from vibe_core.steward.bus import SignalBus

    bus = SignalBus(bus_id="steward.agent")
    ServiceRegistry.register(SVC_SIGNAL_BUS, bus)

    # 6. Memory (Chitta — persistent context across turns)
    from steward.memory import PersistentMemory

    memory = PersistentMemory(cwd=cwd)
    ServiceRegistry.register(SVC_MEMORY, memory)

    # 7. EventBus (Narada — real-time event stream + Sudarshana rate limiting)
    from vibe_core.mahamantra.substrate.services.event_bus import EventBus

    event_bus = EventBus(rate_limit_enabled=False)  # steward is trusted
    ServiceRegistry.register(SVC_EVENT_BUS, event_bus)

    # 8. PromptContext (dynamic system prompt resolvers)
    from pathlib import Path

    from vibe_core.runtime.prompt_context import PromptContext

    cwd_path = Path(cwd) if cwd else Path.cwd()
    prompt_ctx = PromptContext(vibe_root=cwd_path)
    ServiceRegistry.register(SVC_PROMPT_CONTEXT, prompt_ctx)

    logger.info(
        "Steward services booted (tools=%d, provider=%s)",
        len(registry),
        "yes" if provider else "none",
    )

    return ServiceRegistry


# ── Helpers ──────────────────────────────────────────────────────────


def tool_descriptions_for_llm(registry: ToolRegistry) -> list[dict[str, object]]:
    """Convert ToolRegistry descriptions to OpenAI tool-calling format.

    Transforms our flat parameter schemas into JSON Schema format:
    {"type": "object", "properties": {...}, "required": [...]}
    """
    result: list[dict[str, object]] = []
    for desc in registry.get_tool_descriptions():
        raw_params = desc.get("parameters", {})

        # Convert flat params to JSON Schema
        properties: dict[str, object] = {}
        required: list[str] = []
        for param_name, param_spec in raw_params.items():
            if isinstance(param_spec, dict):
                prop: dict[str, object] = {
                    "type": param_spec.get("type", "string"),
                }
                if "description" in param_spec:
                    prop["description"] = param_spec["description"]
                properties[param_name] = prop
                if param_spec.get("required"):
                    required.append(param_name)

        function_def: dict[str, object] = {
            "name": desc["name"],
            "description": desc.get("description", ""),
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
        result.append({"type": "function", "function": function_def})
    return result
