"""
Steward Service Wiring — DI bootstrap for the superagent.

Uses steward-protocol's ServiceRegistry for dependency injection.
All services registered at boot time with SVC_ constants.

    boot(tools=[...], provider=chamber)
    registry = ServiceRegistry.get(SVC_TOOL_REGISTRY)
"""

from __future__ import annotations

import logging

from steward.types import ChamberProvider, LLMProvider
from vibe_core.di import ServiceRegistry
from vibe_core.mahamantra.adapters.attention import MahaAttention
from vibe_core.runtime.tool_safety_guard import ToolSafetyGuard
from vibe_core.tools.tool_protocol import Tool
from vibe_core.tools.tool_registry import ToolRegistry

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


class SVC_FEEDBACK:
    """FeedbackProtocol — pain/pleasure signals for outcome learning."""


class SVC_PROMPT_CONTEXT:
    """PromptContext — dynamic context resolvers for system prompt."""


class SVC_NARASIMHA:
    """NarasimhaProtocol — hypervisor-level emergency killswitch."""


class SVC_INTEGRITY:
    """IntegrityChecker — boot-time validation of all services."""


class SVC_CACHE:
    """EphemeralStorage — TTL cache to avoid redundant work (protocol: playbook)."""


class SVC_DIAMOND:
    """NagaDiamondProtocol — TDD enforcement with RED/GREEN gates (protocol: naga)."""


class SVC_VENU:
    """VenuOrchestrator — O(1) 19-bit DIW rhythm driving execution cycle."""


class SVC_COMPRESSION:
    """MahaCompression — deterministic seed extraction for cache + learning."""


class SVC_SIKSASTAKAM:
    """SiksastakamSynth — 7-beat cache lifecycle from Verse 1."""


class SVC_ANTARANGA:
    """AntarangaRegistry — 512-slot O(1) contiguous state chamber (16 KB)."""


class SVC_NORTH_STAR:
    """North Star — infrastructure-level goal seed (not LLM prompt).

    The north_star is a MahaCompression seed derived from the system's purpose.
    Buddhi uses it for alignment checks. Integrity uses it for drift detection.
    It is NEVER sent to the LLM as text — it is a deterministic integer.
    """


# ── North Star (Dhruva) ─────────────────────────────────────────────
# The fixed point everything converges toward. Not English prose —
# a deterministic seed from MahaCompression. The words become reality
# because the architecture ENCODES them, not because the LLM reads them.
#
# This text is compressed to a seed at boot. The seed is the constant.
# Change the text = change the seed = change the attractor.
NORTH_STAR_TEXT = "execute tasks with minimal tokens by making the architecture itself intelligent"


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

    # 5. FeedbackProtocol (Vedana — pain/pleasure signals for learning)
    from vibe_core.protocols.feedback import InMemoryFeedback

    feedback = InMemoryFeedback()
    ServiceRegistry.register(SVC_FEEDBACK, feedback)

    # Wire feedback into ProviderChamber if it supports it
    if provider is not None and isinstance(provider, ChamberProvider):
        provider.set_feedback(feedback)

    # 6. SignalBus (agent event communication)
    from vibe_core.steward.bus import SignalBus

    bus = SignalBus(bus_id="steward.agent")
    ServiceRegistry.register(SVC_SIGNAL_BUS, bus)

    # 7. Memory (Chitta — persistent context across turns)
    from steward.memory import PersistentMemory

    memory = PersistentMemory(cwd=cwd)
    ServiceRegistry.register(SVC_MEMORY, memory)

    # 8. EventBus (Narada — real-time event stream + Sudarshana rate limiting)
    from vibe_core.mahamantra.substrate.services.event_bus import EventBus

    event_bus = EventBus(rate_limit_enabled=False)  # steward is trusted
    ServiceRegistry.register(SVC_EVENT_BUS, event_bus)

    # 9. NarasimhaProtocol (hypervisor killswitch — dormant until needed)
    from vibe_core.protocols.mahajanas.nrisimha.types.narasimha import NarasimhaProtocol

    narasimha = NarasimhaProtocol()
    ServiceRegistry.register(SVC_NARASIMHA, narasimha)

    # 10. PromptContext (dynamic system prompt resolvers)
    from pathlib import Path

    from vibe_core.runtime.prompt_context import PromptContext

    cwd_path = Path(cwd) if cwd else Path.cwd()
    prompt_ctx = PromptContext(vibe_root=cwd_path)
    ServiceRegistry.register(SVC_PROMPT_CONTEXT, prompt_ctx)

    # 11. EphemeralStorage (session-level TTL cache — avoids redundant LLM work)
    from vibe_core.playbook.ephemeral_storage import EphemeralStorage

    cache = EphemeralStorage(max_entries=500, default_ttl=300)
    ServiceRegistry.register(SVC_CACHE, cache)

    # 12. NagaDiamondProtocol (TDD enforcement — RED/GREEN gates)
    from vibe_core.naga.diamond import NagaDiamondProtocol

    diamond = NagaDiamondProtocol(
        workspace=cwd_path,
        auto_heal=False,  # Never auto-heal without consent
        timeout_seconds=30,
    )
    ServiceRegistry.register(SVC_DIAMOND, diamond)

    # 13. VenuOrchestrator (Krishna's Flute — O(1) DIW-based execution rhythm)
    from vibe_core.mahamantra.substrate.vm.venu_orchestrator import VenuOrchestrator

    venu = VenuOrchestrator()
    ServiceRegistry.register(SVC_VENU, venu)

    # 14. MahaCompression (deterministic seed extraction for cache + learning)
    from vibe_core.mahamantra.adapters.compression import MahaCompression

    compression = MahaCompression()
    ServiceRegistry.register(SVC_COMPRESSION, compression)

    # 15. North Star (Dhruva — fixed-point seed for alignment)
    north_star_seed = compression.compress(NORTH_STAR_TEXT).seed
    ServiceRegistry.register(SVC_NORTH_STAR, north_star_seed)

    # 16. SiksastakamSynth (7-beat cache lifecycle from Verse 1)
    from vibe_core.mahamantra.substrate.mantra.siksastakam import SiksastakamSynth

    siksastakam = SiksastakamSynth()
    ServiceRegistry.register(SVC_SIKSASTAKAM, siksastakam)

    # 17. AntarangaRegistry (512-slot O(1) state chamber — 16 KB contiguous RAM)
    from vibe_core.mahamantra.substrate.cell_system.antaranga import AntarangaRegistry

    antaranga = AntarangaRegistry()
    ServiceRegistry.register(SVC_ANTARANGA, antaranga)

    # 18. IntegrityChecker — boot-time validation (catch lazy-load failures early)
    from vibe_core.protocols.integrity import IntegrityChecker, IssueSeverity

    checker = IntegrityChecker()
    checker.register_checker(
        "tool_registry",
        lambda: _check_tools_registered(registry),
        IssueSeverity.CRITICAL,
    )
    checker.register_checker(
        "narasimha_protocol",
        lambda: _check_narasimha(narasimha),
        IssueSeverity.HIGH,
    )
    if provider is not None:
        checker.register_checker(
            "provider_chamber",
            lambda: _check_provider(provider),
            IssueSeverity.CRITICAL,
        )

    # Vajra wiring checks — verify all services are actually registered
    checker.register_checker(
        "vajra_cache_wired",
        lambda: _check_service_wired(SVC_CACHE, "EphemeralStorage"),
        IssueSeverity.HIGH,
    )
    checker.register_checker(
        "vajra_diamond_wired",
        lambda: _check_service_wired(SVC_DIAMOND, "NagaDiamondProtocol"),
        IssueSeverity.HIGH,
    )
    checker.register_checker(
        "vajra_attention_wired",
        lambda: _check_service_wired(SVC_ATTENTION, "MahaAttention"),
        IssueSeverity.CRITICAL,
    )
    checker.register_checker(
        "vajra_venu_wired",
        lambda: _check_service_wired(SVC_VENU, "VenuOrchestrator"),
        IssueSeverity.HIGH,
    )
    checker.register_checker(
        "vajra_venu_divinity",
        lambda: _check_venu_divinity(venu),
        IssueSeverity.HIGH,
    )
    checker.register_checker(
        "vajra_compression_wired",
        lambda: _check_service_wired(SVC_COMPRESSION, "MahaCompression"),
        IssueSeverity.HIGH,
    )
    checker.register_checker(
        "vajra_antaranga_wired",
        lambda: _check_service_wired(SVC_ANTARANGA, "AntarangaRegistry"),
        IssueSeverity.HIGH,
    )

    ServiceRegistry.register(SVC_INTEGRITY, checker)

    # Run integrity check at boot
    report = checker.check_all()
    if report.issues:
        for issue in report.issues:
            logger.warning("Integrity: %s", issue)
    logger.info(
        "Steward services booted (tools=%d, provider=%s, integrity=%d/%d in %.0fms)",
        len(registry),
        "yes" if provider else "none",
        report.passed_count,
        report.checked_count,
        report.duration_ms,
    )

    return ServiceRegistry


def _check_tools_registered(registry: ToolRegistry) -> None:
    """Integrity check: at least one tool is registered."""
    if len(registry) == 0:
        raise RuntimeError("No tools registered")


def _check_narasimha(narasimha: object) -> None:
    """Integrity check: Narasimha protocol is functional."""
    from vibe_core.protocols.mahajanas.nrisimha.types.narasimha import NarasimhaProtocol
    if not isinstance(narasimha, NarasimhaProtocol):
        raise RuntimeError("NarasimhaProtocol missing audit_agent()")


def _check_provider(provider: object) -> None:
    """Integrity check: provider can accept calls."""
    if not callable(getattr(provider, "invoke", None)):
        raise RuntimeError("Provider missing invoke()")


def _check_venu_divinity(venu: object) -> None:
    """Integrity check: VenuOrchestrator structural verification."""
    from vibe_core.mahamantra.substrate.vm.venu_orchestrator import VenuOrchestrator
    if not isinstance(venu, VenuOrchestrator) or not venu.verify_divinity():
        raise RuntimeError("VenuOrchestrator failed divinity verification")


def _check_service_wired(svc_key: type, name: str) -> None:
    """Vajra wiring check: verify a service is registered and non-None."""
    svc = ServiceRegistry.get(svc_key)
    if svc is None:
        raise RuntimeError(f"VAJRA: {name} not wired (SVC key: {svc_key.__name__})")


# ── Helpers ──────────────────────────────────────────────────────────


def lean_tool_signatures(registry: ToolRegistry) -> str:
    """One-line tool signatures for brain-in-a-jar system prompt.

    Names + required params only. No descriptions — tool names are self-documenting.
    ~100 tokens for ALL tools vs ~1500 tokens for full JSON Schema.
    """
    lines = []
    for desc in registry.get_tool_descriptions():
        name = desc["name"]
        raw_params = desc.get("parameters", {})
        if isinstance(raw_params, dict):
            param_parts = []
            for pname, pspec in raw_params.items():
                if isinstance(pspec, dict):
                    required = pspec.get("required", False)
                    marker = "" if required else "?"
                    param_parts.append(f"{pname}{marker}")
                else:
                    param_parts.append(pname)
            sig = f"{name}({', '.join(param_parts)})"
        else:
            sig = f"{name}()"
        lines.append(sig)
    return "\n".join(lines)


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
