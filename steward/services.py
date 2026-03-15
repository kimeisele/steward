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


class SVC_MAHA_LLM:
    """MahaLLMKernel — deterministic semantic engine (L0 zero-cost intent)."""


class SVC_SYNAPSE_STORE:
    """SynapseStore — persistent Hebbian weights across sessions."""


class SVC_TASK_MANAGER:
    """TaskManager — persistent task tracking with priority selection."""


class SVC_SANKALPA:
    """SankalpaOrchestrator — autonomous mission planning and intent generation."""


class SVC_KNOWLEDGE_GRAPH:
    """UnifiedKnowledgeGraph — 4-dimensional codebase understanding (zero tokens)."""


class SVC_OUROBOROS:
    """OuroborosLoopOrchestrator — self-healing pipeline (detect → verify → heal)."""


class SVC_MARKETPLACE:
    """Marketplace — slot conflict resolution for federation peers."""


class SVC_FEDERATION:
    """FederationBridge — cross-agent message routing."""


class SVC_FEDERATION_TRANSPORT:
    """FederationTransport — pluggable transport for cross-agent messaging."""


class SVC_GIT_NADI_SYNC:
    """GitNadiSync — git pull/push for federation nadi files."""


class SVC_FEDERATION_RELAY:
    """GitHubFederationRelay — GitHub API bridge to hub repo."""


class SVC_REAPER:
    """HeartbeatReaper — network garbage collection for federation peers."""


class SVC_PHASE_HOOKS:
    """PhaseHookRegistry — composable phase dispatch for MURALI."""


class SVC_IMMUNE:
    """StewardImmune — unified self-healing system.

    diagnose() → heal() → verify → Hebbian learn.
    CytokineBreaker prevents autoimmune cascades.
    """


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
    # TODO(multi-agent): reset_all() nukes every registered service.
    # If two StewardAgent instances share a process, the second boot()
    # destroys the first agent's wiring. Needs scoped registries or
    # per-agent namespaces in steward-protocol ServiceRegistry.
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

    # 12. NagaDiamondProtocol — DEFERRED (registered but not consumed by agent loop)
    # Will be activated when TDD gating is implemented.

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

    # 18. MahaLLMKernel (L0 deterministic intent — zero LLM cost)
    from vibe_core.mahamantra.substrate.encoding.maha_llm_kernel import MahaLLMKernel

    maha_llm = MahaLLMKernel()
    ServiceRegistry.register(SVC_MAHA_LLM, maha_llm)

    # 19. SynapseStore (persistent Hebbian weights — cross-session learning)
    from vibe_core.state.synapse_store import SynapseStore

    synapse_store = SynapseStore(workspace=cwd_path)
    synapse_store.load()
    ServiceRegistry.register(SVC_SYNAPSE_STORE, synapse_store)

    # 20. TaskManager (persistent task tracking)
    from vibe_core.task_management.task_manager import TaskManager

    task_manager = TaskManager(project_root=cwd_path)
    ServiceRegistry.register(SVC_TASK_MANAGER, task_manager)

    # 21. SankalpaOrchestrator (autonomous mission planning — the "will")
    from vibe_core.mahamantra.substrate.sankalpa.will import SankalpaOrchestrator

    sankalpa = SankalpaOrchestrator(workspace=cwd_path)
    _add_steward_missions(sankalpa)
    ServiceRegistry.register(SVC_SANKALPA, sankalpa)

    # 22. KnowledgeGraph (4-dimensional codebase understanding — zero tokens)
    #     Lazy scan: graph is created empty at boot, populated on first query
    #     via ensure_scanned(). Avoids ~200ms AST scan on every boot.
    from vibe_core.knowledge.graph import UnifiedKnowledgeGraph

    knowledge_graph = _LazyKnowledgeGraph(cwd_path)
    ServiceRegistry.register(SVC_KNOWLEDGE_GRAPH, knowledge_graph)

    # 23. Ouroboros (self-healing pipeline: detect → ingest → heal)
    from vibe_core.ouroboros.loop_orchestrator import OuroborosLoopOrchestrator

    ouroboros = OuroborosLoopOrchestrator(workspace=str(cwd_path))
    ServiceRegistry.register(SVC_OUROBOROS, ouroboros)

    # 25. HeartbeatReaper (federation peer liveness + trust degradation)
    from steward.reaper import HeartbeatReaper

    reaper = HeartbeatReaper()
    peers_path = cwd_path / ".steward" / "peers.json"
    reaper.load(peers_path)
    ServiceRegistry.register(SVC_REAPER, reaper)

    # 26. Marketplace (slot conflict resolution for federation peers)
    from steward.marketplace import Marketplace

    marketplace = Marketplace()
    market_path = cwd_path / ".steward" / "marketplace.json"
    marketplace.load(market_path)
    ServiceRegistry.register(SVC_MARKETPLACE, marketplace)

    # 27. FederationBridge (cross-agent message routing → Reaper + Marketplace)
    from steward.federation import FederationBridge

    federation = FederationBridge(reaper=reaper, marketplace=marketplace)
    ServiceRegistry.register(SVC_FEDERATION, federation)

    # 28. FederationTransport (auto-discover: env var or default data/federation/)
    import os

    fed_dir = os.environ.get("STEWARD_FEDERATION_DIR") or (str(Path(cwd) / "data" / "federation") if cwd else "")
    if Path(fed_dir).is_dir():
        from steward.federation_transport import create_transport

        transport = create_transport(fed_dir)
        ServiceRegistry.register(SVC_FEDERATION_TRANSPORT, transport)
        logger.info("Federation transport: %s → %s", type(transport).__name__, fed_dir)

        # 28b. GitNadiSync (git network layer for federation — only if git checkout)
        from steward.git_nadi_sync import GitNadiSync

        git_sync = GitNadiSync(fed_dir)
        if git_sync.is_git_repo:
            ServiceRegistry.register(SVC_GIT_NADI_SYNC, git_sync)
            logger.info("Git nadi sync: active (interval=%ds)", git_sync._sync_interval_s)

        # 28c. GitHubFederationRelay (GitHub API bridge to hub — cross-repo delivery)
        from steward.federation_relay import GitHubFederationRelay

        relay = GitHubFederationRelay(
            agent_id="steward",
            local_outbox=Path(fed_dir) / "nadi_outbox.json",
            local_inbox=Path(fed_dir) / "nadi_inbox.json",
        )
        if relay.available:
            ServiceRegistry.register(SVC_FEDERATION_RELAY, relay)
            logger.info("Federation relay: active (hub=%s)", relay._hub_repo)

    # 29. PhaseHookRegistry (composable MURALI phase dispatch)
    from steward.hooks import register_default_hooks
    from steward.phase_hook import PhaseHookRegistry

    phase_hooks = PhaseHookRegistry()
    register_default_hooks(phase_hooks)
    ServiceRegistry.register(SVC_PHASE_HOOKS, phase_hooks)

    # 30. StewardImmune (unified self-healing)
    from steward.immune import StewardImmune

    immune = StewardImmune(
        _synaptic=synapse_store,
        _cwd=cwd,
    )
    ServiceRegistry.register(SVC_IMMUNE, immune)

    # 24. IntegrityChecker — boot-time validation (catch lazy-load failures early)
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
    # vajra_diamond_wired — DEFERRED (Diamond not booted)
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
    checker.register_checker(
        "vajra_knowledge_graph_wired",
        lambda: _check_service_wired(SVC_KNOWLEDGE_GRAPH, "UnifiedKnowledgeGraph"),
        IssueSeverity.HIGH,
    )
    checker.register_checker(
        "vajra_ouroboros_wired",
        lambda: _check_service_wired(SVC_OUROBOROS, "OuroborosLoopOrchestrator"),
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
    if not isinstance(provider, LLMProvider):
        raise RuntimeError("Provider does not implement LLMProvider protocol")


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


def _add_steward_missions(sankalpa: object) -> None:
    """Add steward-specific missions with 10-minute triggers for cron autonomy.

    The default Sankalpa mission requires 60 min idle. Steward runs every 15 min,
    so we need shorter triggers. This adds a "Steward Autonomy" mission that fires
    after 10 minutes idle with no pending tasks.
    """
    from vibe_core.mahamantra.protocols.sankalpa.types import (
        MissionPriority,
        MissionStatus,
        SankalpaMission,
        SankalpaStrategy,
        SankalpaTrigger,
        StrategyFrequency,
        TriggerType,
    )

    mission_id = "mission_steward_autonomy"
    # Don't add if already exists (persisted from previous boot)
    existing = sankalpa.registry.get_all_missions()
    if any(m.id == mission_id for m in existing):
        return

    mission = SankalpaMission(
        id=mission_id,
        name="Steward Autonomy",
        description="Autonomous codebase maintenance every 15 minutes",
        priority=MissionPriority.HIGH,
        status=MissionStatus.ACTIVE,
        strategies=[
            SankalpaStrategy(
                id="strategy_quick_check",
                name="Quick Health Check",
                description="Run senses, check CI status, scan for issues",
                trigger=SankalpaTrigger(
                    trigger_type=TriggerType.IDLE_BASED,
                    idle_minutes=10,
                ),
                frequency=StrategyFrequency.DAILY,
                intent_type="health_check",
                intent_template={"actions": ["sense_scan", "ci_check"]},
                requires_ci_green=False,
                requires_no_pending_intents=True,
                max_executions_per_day=6,
                enabled=True,
            ),
            SankalpaStrategy(
                id="strategy_update_deps",
                name="Update Dependencies",
                description="Check for outdated packages, create PR to update",
                trigger=SankalpaTrigger(
                    trigger_type=TriggerType.IDLE_BASED,
                    idle_minutes=30,
                ),
                frequency=StrategyFrequency.WEEKLY,
                intent_type="update_deps",
                intent_template={},
                requires_ci_green=True,
                requires_no_pending_intents=True,
                max_executions_per_day=1,
                enabled=True,
            ),
            SankalpaStrategy(
                id="strategy_remove_dead_code",
                name="Remove Dead Code",
                description="Detect low-cohesion modules, create PR to refactor",
                trigger=SankalpaTrigger(
                    trigger_type=TriggerType.IDLE_BASED,
                    idle_minutes=30,
                ),
                frequency=StrategyFrequency.WEEKLY,
                intent_type="remove_dead_code",
                intent_template={},
                requires_ci_green=True,
                requires_no_pending_intents=True,
                max_executions_per_day=1,
                enabled=True,
            ),
            SankalpaStrategy(
                id="strategy_federation_health",
                name="Federation Health Check",
                description="Monitor peer liveness, outbox queue, transport health",
                trigger=SankalpaTrigger(
                    trigger_type=TriggerType.IDLE_BASED,
                    idle_minutes=10,
                ),
                frequency=StrategyFrequency.DAILY,
                intent_type="federation_health",
                intent_template={},
                requires_ci_green=False,
                requires_no_pending_intents=True,
                max_executions_per_day=12,
                enabled=True,
            ),
            SankalpaStrategy(
                id="strategy_heal_repo",
                name="Heal Federation Repos",
                description="Diagnose and fix degraded federation peers via PR",
                trigger=SankalpaTrigger(
                    trigger_type=TriggerType.IDLE_BASED,
                    idle_minutes=15,
                ),
                frequency=StrategyFrequency.DAILY,
                intent_type="heal_repo",
                intent_template={},
                requires_ci_green=False,
                requires_no_pending_intents=True,
                max_executions_per_day=4,
                enabled=True,
            ),
            SankalpaStrategy(
                id="strategy_cross_repo_diagnostic",
                name="Cross-Repo Diagnostic",
                description="Scan federation repos for structural issues",
                trigger=SankalpaTrigger(
                    trigger_type=TriggerType.IDLE_BASED,
                    idle_minutes=15,
                ),
                frequency=StrategyFrequency.DAILY,
                intent_type="cross_repo_diagnostic",
                intent_template={},
                requires_ci_green=False,
                requires_no_pending_intents=True,
                max_executions_per_day=4,
                enabled=True,
            ),
            SankalpaStrategy(
                id="strategy_synthesize_briefing",
                name="Synthesize Context Briefing",
                description=(
                    "Use synthesize_briefing tool to update .steward/CLAUDE.md "
                    "from steward's living state and architecture metadata"
                ),
                trigger=SankalpaTrigger(
                    trigger_type=TriggerType.IDLE_BASED,
                    idle_minutes=15,
                ),
                frequency=StrategyFrequency.DAILY,
                intent_type="synthesize_briefing",
                intent_template={},
                requires_ci_green=False,
                requires_no_pending_intents=True,
                max_executions_per_day=6,
                enabled=True,
            ),
        ],
        owner="steward",
    )
    sankalpa.registry.add_mission(mission)
    logger.info("Sankalpa: added steward autonomy mission (10min trigger)")


class _LazyKnowledgeGraph:
    """KnowledgeGraph that only scans the codebase on first query.

    Avoids ~200ms of AST parsing at boot. The graph is populated lazily
    when ensure_scanned() is called (typically by the agent loop before
    using get_context_for_task).
    """

    def __init__(self, workspace: object) -> None:
        from vibe_core.knowledge.graph import UnifiedKnowledgeGraph

        self._graph = UnifiedKnowledgeGraph()
        self._workspace = workspace
        self._scanned = False

    def ensure_scanned(self) -> None:
        """Populate the graph from the codebase if not already done."""
        if self._scanned:
            return
        self._scanned = True
        try:
            from vibe_core.knowledge.code_scanner import CodeScanner

            scanner = CodeScanner(self._graph)
            stats = scanner.scan_directory(self._workspace)
            logger.info(
                "KnowledgeGraph: scanned %d files → %d modules, %d classes, %d functions",
                stats.get("files_scanned", 0),
                stats.get("modules_added", 0),
                stats.get("classes_added", 0),
                stats.get("functions_added", 0),
            )
        except Exception as e:
            logger.warning("KnowledgeGraph scan failed (non-fatal): %s", e)

    @property
    def graph(self) -> object:
        """Access the underlying UnifiedKnowledgeGraph (triggers scan if needed)."""
        self.ensure_scanned()
        return self._graph

    def get_context_for_task(self, task_concept: str, depth: int = 1) -> dict:
        """Delegate to underlying graph (triggers scan if needed)."""
        self.ensure_scanned()
        return self._graph.get_context_for_task(task_concept, depth)

    def compile_prompt_context(self, task_concept: str) -> str:
        """Delegate to underlying graph (triggers scan if needed)."""
        self.ensure_scanned()
        return self._graph.compile_prompt_context(task_concept)


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
