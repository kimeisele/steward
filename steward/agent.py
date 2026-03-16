"""
StewardAgent — The autonomous superagent.

This is the public API. Users create a StewardAgent, give it a task,
and it executes autonomously using the tool-use loop.

    agent = StewardAgent(provider=llm)
    result = await agent.run("Fix the failing tests in src/")

    # Or synchronous:
    result = agent.run_sync("Fix the failing tests in src/")

The agent manages its own conversation, tools, and context window.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import AsyncIterator

from steward import __version__, agent_bus, agent_memory
from steward.antahkarana.ksetrajna import KsetraJna
from steward.antahkarana.vedana import measure_vedana
from steward.autonomy import AutonomyEngine
from steward.buddhi import Buddhi
from steward.cetana import Cetana
from steward.config import StewardConfig, load_config
from steward.context import SamskaraContext
from steward.gaps import GapTracker
from steward.loop.engine import AgentLoop
from steward.protocols import RemotePerception, ToolProvider
from steward.senses import SenseCoordinator
from steward.services import (
    SVC_ANTARANGA,
    SVC_ATTENTION,
    SVC_CACHE,
    SVC_COMPRESSION,
    SVC_FEEDBACK,
    SVC_MAHA_LLM,
    SVC_MEMORY,
    SVC_NARASIMHA,
    SVC_NORTH_STAR,
    SVC_PHASE_HOOKS,
    SVC_PROMPT_CONTEXT,
    SVC_SAFETY_GUARD,
    SVC_SIKSASTAKAM,
    SVC_SYNAPSE_STORE,
    SVC_TOOL_REGISTRY,
    SVC_VENU,
    boot,
)
from steward.session_ledger import SessionLedger
from steward.tool_providers import BuiltinToolProvider, FileSystemToolProvider, collect_tools
from steward.tools.circuit_breaker import CircuitBreaker
from steward.types import (
    AgentEvent,
    ChamberProvider,
    Conversation,
    EventType,
    LLMProvider,
    Message,
    MessageRole,
    ToolResult,
)
from vibe_core.di import ServiceRegistry
from vibe_core.mahamantra.adapters.attention import MahaAttention
from vibe_core.mahamantra.protocols._gad import GADBase
from vibe_core.mahamantra.substrate.manas.synaptic import HebbianSynaptic
from vibe_core.protocols.memory import MemoryProtocol
from vibe_core.runtime.tool_safety_guard import ToolSafetyGuard
from vibe_core.tools.tool_protocol import Tool
from vibe_core.tools.tool_registry import ToolRegistry

logger = logging.getLogger("STEWARD.AGENT")

_BASE_SYSTEM_PROMPT = """\
Software agent. Use tools to complete tasks. Read before edit. Test after change.
"""


def _load_project_instructions(cwd: str) -> str | None:
    """Load project-specific instructions from the working directory.

    Looks for (in order):
    1. .steward/instructions.md
    2. CLAUDE.md

    Returns the file contents or None.
    """
    candidates = [
        Path(cwd) / ".steward" / "instructions.md",
        Path(cwd) / "CLAUDE.md",
    ]
    for path in candidates:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    logger.info("Loaded project instructions from %s", path)
                    return content
            except OSError as e:
                logger.warning("Failed to read %s: %s", path, e)
    return None


def _build_system_prompt(base: str, cwd: str) -> str:
    """Build minimal system prompt. Every token counts.

    Only includes: base instruction + cwd.
    Tool signatures injected by engine (brain-in-a-jar).
    """
    return f"{base.rstrip()}\ncwd: {cwd}"


class StewardAgent(GADBase):
    """Autonomous agent that executes tasks using LLM + tools.

    GAD-000 compliant superagent:
    - Discoverable: discover() returns capabilities
    - Observable: get_state() returns full agent state
    - Parseable: structured event stream
    - Composable: tools are independent
    - Idempotent: O(1) Lotus routing, deterministic
    - Recoverable: session resume via samskara

    Args:
        provider: LLM provider (anything with invoke(**kwargs) -> response)
        system_prompt: System prompt for the agent
        cwd: Working directory for tools (default: current directory)
        max_context_tokens: Maximum context window size
        max_output_tokens: Maximum tokens per LLM response
        tools: Additional Tool instances to register
    """

    def __init__(
        self,
        provider: LLMProvider,
        system_prompt: str | None = None,
        cwd: str | None = None,
        max_context_tokens: int | None = None,
        max_output_tokens: int | None = None,
        tools: list[Tool] | None = None,
        tool_providers: list[ToolProvider] | None = None,
        config: StewardConfig | None = None,
    ) -> None:
        GADBase.__init__(self)
        self._provider = provider
        self._cwd = cwd or str(Path.cwd())

        # Load config from file, merge with explicit args
        self._config = config or load_config(self._cwd)
        self._max_output_tokens = max_output_tokens or self._config.max_output_tokens
        ctx_tokens = max_context_tokens or self._config.max_context_tokens

        # Initialize conversation
        self._conversation = Conversation(max_tokens=ctx_tokens)

        # Build tool list via ToolProvider protocol (pluggable discovery)
        self._tool_providers = tool_providers or [BuiltinToolProvider(), FileSystemToolProvider()]
        all_tools = collect_tools(self._tool_providers, self._cwd, extra_tools=tools)

        # Boot services (wires ToolRegistry, SafetyGuard, MahaAttention, Memory, EventBus)
        boot(tools=all_tools, provider=provider, cwd=self._cwd)

        # Pull services from DI
        self._registry: ToolRegistry = ServiceRegistry.require(SVC_TOOL_REGISTRY)
        self._safety_guard: ToolSafetyGuard = ServiceRegistry.require(SVC_SAFETY_GUARD)
        self._attention: MahaAttention = ServiceRegistry.require(SVC_ATTENTION)
        self._memory: MemoryProtocol = ServiceRegistry.require(SVC_MEMORY)

        # Hebbian synaptic learning (real HebbianSynaptic from steward-protocol)
        # No file-backed state_dir — weights persist via PersistentMemory
        # so they survive ephemeral contexts (CI, API containers)
        self._synaptic = HebbianSynaptic()
        agent_memory.load_synaptic(self._memory, self._synaptic)
        self._synaptic.decay()  # temporal decay on boot — old patterns fade

        # Buddhi persists across turns (cross-turn Chitta awareness)
        self._buddhi = Buddhi(synaptic=self._synaptic)
        agent_memory.load_chitta(self._memory, self._buddhi)

        # Session ledger (cross-session learning)
        self._ledger = SessionLedger(cwd=self._cwd)

        # Circuit breaker — verify LLM fixes don't make things worse
        self._breaker = CircuitBreaker(cwd=self._cwd)

        # 5 Jnanendriyas — deterministic environmental perception (zero LLM)
        self._senses = SenseCoordinator(cwd=self._cwd)

        # Actuators — real muscles for git/GitHub operations
        from steward.actuators import GitActuator, GitHubActuator
        from steward.senses.gh import get_gh_client

        self._git_actuator = GitActuator(cwd=self._cwd)
        self._github_actuator = GitHubActuator(gh_client=get_gh_client())

        # AutonomyEngine — all autonomous task detection, dispatch, and fix logic
        # Extracted from StewardAgent to reduce LCOM4 (god-class → focused modules)
        self._autonomy = AutonomyEngine(
            breaker=self._breaker,
            senses=self._senses,
            synaptic=self._synaptic,
            memory=self._memory,
            ledger=self._ledger,
            cwd=self._cwd,
            run_fn=self.run,
            vedana_fn=lambda: self.vedana,
            git_actuator=self._git_actuator,
            github_actuator=self._github_actuator,
            conversation_reset_fn=self._reset_conversation,
        )

        # Gap tracker — self-awareness of capability gaps
        self._gaps = GapTracker()
        agent_memory.load_gaps(self._memory, self._gaps)

        # Persona — persistent identity (from steward-protocol)
        # Lazy: mahamantra import takes ~4s. Only compute when discover() is called.
        self._persona: dict[str, str] | None = None
        self._persona_loaded = False

        # Build system prompt — minimal. LLM only needs: instruction + cwd.
        # Tool sigs injected by engine. Everything else is infrastructure.
        self._custom_prompt = system_prompt is not None
        if system_prompt is not None:
            self._system_prompt = system_prompt
            self._base_system_prompt = system_prompt
        else:
            self._base_system_prompt = _build_system_prompt(
                _BASE_SYSTEM_PROMPT,
                self._cwd,
            )
            self._system_prompt = self._base_system_prompt

            # Senses perceive lazily — deferred to run_stream() / run_autonomous()
            # Boot must be fast. Perception only when intent actually needs it.

        # Emit AGENT_STARTUP signal
        agent_bus.emit_startup(self._registry.list_tools(), self._cwd)

        # Cetana — autonomous heartbeat driven by vedana health (BG 13.6-7)
        # Daemon thread: adapts monitoring frequency to agent health.
        # Does NOT think or act — only observes and signals.
        self._health_lock = threading.Lock()
        self._health_anomaly_flag = False
        self._health_anomaly_detail_str = ""
        self._last_user_interaction = time.monotonic()

        # Phase dispatch table — O(1) routing, no if/elif chain
        from steward.cetana import Phase

        self._phase_dispatch = {
            Phase.GENESIS: self._phase_genesis,
            Phase.DHARMA: self._phase_dharma,
            Phase.KARMA: self._phase_karma,
            Phase.MOKSHA: self._phase_moksha,
        }

        self._cetana = Cetana(
            vedana_source=lambda: self.vedana,
            on_anomaly=self._on_cetana_anomaly,
            on_phase=self._on_cetana_phase,
        )
        self._cetana.start()

        # KsetraJna — meta-observer of the entire field (BG 13.1-2)
        # Watches all antahkarana components, produces BubbleSnapshots.
        # Zero LLM tokens. Foundation for BuddyBubble peer observation.
        self._ksetrajna = KsetraJna(
            vedana_source=lambda: self.vedana,
            chitta_source=lambda: self._buddhi.stats,
            cetana_source=lambda: self._cetana.stats(),
            buddhi_source=lambda: {
                "action": self._buddhi.last_action,
                "tier": self._buddhi.last_tier,
            },
            gandha_source=lambda: self._buddhi.last_pattern,
        )

        # Wire ThinkTool to Antahkarana (neuro-symbolic bridge)
        self._wire_think_tool()

        logger.info(
            "StewardAgent initialized (cwd=%s, tools=%s)",
            self._cwd,
            self._registry.list_tools(),
        )

    async def run(self, task: str) -> str:
        """Execute a task autonomously (async).

        The agent will use tools as needed until it produces a final
        text response. Returns the agent's response.
        """
        # Guard: ensure conversation is initialized (bridges to Component 1)
        if self._conversation is None:
            raise RuntimeError("Agent not initialized — no conversation")
        final_text = ""
        streamed_chunks: list[str] = []
        async for event in self.run_stream(task):
            if event.type == EventType.TEXT_DELTA:
                streamed_chunks.append(str(event.content) if event.content else "")
            elif event.type == EventType.TEXT:
                final_text = str(event.content) if event.content else ""
            elif event.type == EventType.ERROR:
                return f"[Error: {event.content}]"
        if streamed_chunks:
            return "".join(streamed_chunks)
        return final_text

    def run_sync(self, task: str) -> str:
        """Execute a task autonomously (sync wrapper)."""
        if self._conversation is None:
            raise RuntimeError("Agent not initialized — no conversation")
        return asyncio.run(self.run(task))

    async def chat(self, message: str) -> str:
        """Continue an existing conversation (async)."""
        if self._conversation is None:
            raise RuntimeError("Agent not initialized — no conversation")
        return await self.run(message)

    def chat_sync(self, message: str) -> str:
        """Continue an existing conversation (sync wrapper)."""
        if self._conversation is None:
            raise RuntimeError("Agent not initialized — no conversation")
        return self.run_sync(message)

    async def run_autonomous(self, idle_minutes: int | None = None) -> str | None:
        """Delegate to AutonomyEngine — all autonomous logic lives there."""
        if self._conversation is None:
            raise RuntimeError("Agent not initialized — no conversation")
        return await self._autonomy.run_autonomous(idle_minutes=idle_minutes)

    def run_autonomous_sync(self, idle_minutes: int | None = None) -> str | None:
        """Sync wrapper for run_autonomous (one-shot, legacy)."""
        if self._conversation is None:
            raise RuntimeError("Agent not initialized — no conversation")
        return asyncio.run(self.run_autonomous(idle_minutes=idle_minutes))

    def run_daemon(self) -> None:
        """Run as persistent daemon — boot once, Cetana drives all work.

        Blocks until SIGTERM/SIGINT. The 4-phase heartbeat cycle:
          GENESIS: discover/generate tasks from Sankalpa
          DHARMA:  check health invariants, federation, reaper
          KARMA:   execute next pending task (the actual work)
          MOKSHA:  persist state, Hebbian learning

        At SAMADHI (healthy), beats every 10s. Zero CPU between beats
        (OS-level Event.wait). Caller must call close() after return.
        """
        logger.info(
            "Daemon mode — boot once, Cetana drives autonomous work (freq=%.1fHz)",
            self._cetana.frequency_hz,
        )
        try:
            self._cetana._stop_event.wait()  # Blocks until signal
        except KeyboardInterrupt:
            pass

    # ── Autonomy ──────────────────────────────────────────────────────
    # All autonomous methods (detection, fix pipelines, Hebbian learning,
    # branch/PR management) live in steward.autonomy.AutonomyEngine.
    # Access via agent._autonomy — no thin delegators (they hurt LCOM4).

    async def run_stream(self, task: str) -> AsyncIterator[AgentEvent]:
        """Execute a task and yield events as they happen.

        Re-perceives senses before each run for live environmental awareness.
        Emits to both SignalBus (simple) and EventBus (full Narada stream).
        Passes Memory to AgentLoop for cross-turn file tracking.
        Buddhi persists across turns — Chitta retains file awareness.
        Records cumulative session stats in Memory after each turn.
        """
        self._last_user_interaction = time.monotonic()
        # Re-perceive senses (cheap, deterministic, zero LLM)
        # Inject perception + gaps into system prompt — agent needs awareness
        if not self._custom_prompt:
            self._senses.perceive_all()
            context_parts = [self._base_system_prompt]
            sense_context = self._senses.format_for_prompt()
            if sense_context:
                context_parts.append(sense_context)
            gap_context = self._gaps.format_for_prompt()
            if gap_context:
                context_parts.append(gap_context)
            # Session ledger: last 3 session summaries (~200 tokens max)
            # Gives the agent "last time I worked on X, it succeeded/failed"
            ledger_context = self._ledger.prompt_context()
            if ledger_context:
                context_parts.append(ledger_context)
            # Dynamic context: live system data (time, branch) — zero LLM cost
            prompt_ctx = ServiceRegistry.get(SVC_PROMPT_CONTEXT)
            if prompt_ctx is not None:
                try:
                    resolved = prompt_ctx.resolve(["system_time", "current_branch"])
                    dyn_parts = [f"{k}: {v}" for k, v in resolved.items() if v]
                    if dyn_parts:
                        context_parts.append("\n[Dynamic Context]\n" + "\n".join(dyn_parts) + "\n")
                except Exception as e:
                    logger.debug("Dynamic context resolution failed (non-fatal): %s", e)
            effective_prompt = "".join(context_parts)
        else:
            effective_prompt = self._system_prompt

        # Update system message if conversation already has one (multi-run freshness)
        if self._conversation.messages and self._conversation.messages[0].role == MessageRole.SYSTEM:
            self._conversation.messages[0] = Message(role=MessageRole.SYSTEM, content=effective_prompt)

        loop = AgentLoop(
            provider=self._provider,
            registry=self._registry,
            conversation=self._conversation,
            system_prompt=effective_prompt,
            max_tokens=self._max_output_tokens,
            safety_guard=self._safety_guard,
            attention=self._attention,
            memory=self._memory,
            buddhi=self._buddhi,
            narasimha=ServiceRegistry.get(SVC_NARASIMHA),
            json_mode=not self._custom_prompt,  # Brain-in-a-jar for default prompts only
            venu=ServiceRegistry.get(SVC_VENU),
            cache=ServiceRegistry.get(SVC_CACHE),
            antaranga=ServiceRegistry.get(SVC_ANTARANGA),
            ksetrajna=self._ksetrajna,
            health_gate=self,  # StewardAgent implements HealthGate protocol
            compression=ServiceRegistry.get(SVC_COMPRESSION),
            north_star=ServiceRegistry.get(SVC_NORTH_STAR),
            feedback=ServiceRegistry.get(SVC_FEEDBACK),
            maha_llm=ServiceRegistry.get(SVC_MAHA_LLM),
            siksastakam=ServiceRegistry.get(SVC_SIKSASTAKAM),
        )
        async for event in loop.run(task):
            agent_bus.emit_signal(event)
            agent_bus.emit_event_bus(event)
            # Track tool failures as gaps
            if event.type == EventType.TOOL_RESULT and isinstance(event.content, ToolResult):
                if not event.content.success:
                    tool_name = event.tool_use.name if event.tool_use else "unknown"
                    self._gaps.record_tool_failure(tool_name, event.content.error or "")
            if event.type == EventType.DONE and event.usage:
                agent_memory.record_session_stats(self._memory, event.usage)
                agent_memory.record_session_ledger(self._ledger, self._buddhi, task, event.usage)
                # Hebbian learning: record outcome, persist to Memory
                success = event.usage.buddhi_errors <= event.usage.tool_calls // 2
                self._buddhi.record_outcome(success)
                agent_memory.save_synaptic(self._memory, self._synaptic)
                # Cross-turn: merge reads, clear impressions, persist
                self._buddhi.end_turn()
                self._ksetrajna.observe()  # Meta-observation at turn boundary
                agent_memory.save_chitta(self._memory, self._buddhi)
                agent_memory.save_gaps(self._memory, self._gaps)
            yield event

    @property
    def conversation(self) -> Conversation:
        """Access the conversation history."""
        return self._conversation

    @property
    def registry(self) -> ToolRegistry:
        """Access the tool registry."""
        return self._registry

    @property
    def memory(self) -> MemoryProtocol:
        """Access the agent memory."""
        return self._memory

    @property
    def config(self) -> StewardConfig:
        """Access the loaded configuration."""
        return self._config

    @property
    def buddhi_phase(self) -> str:
        """Current execution phase (delegates to Buddhi)."""
        return self._buddhi.phase

    def resume(self, conversation: Conversation) -> None:
        """Resume from a previous session's conversation.

        Compacts old messages into a samskara impression so the agent
        has context about what was done without wasting tokens on
        the full raw conversation.
        """
        # Samskara-compact the old conversation (deterministic, free)
        samskara = SamskaraContext()
        samskara.compact(conversation, keep_recent=4)

        self._conversation = conversation
        logger.info(
            "Resumed session (%d messages, %d tokens)",
            len(conversation.messages),
            conversation.total_tokens,
        )

    def reset(self) -> None:
        """Clear conversation history, safety guard, Buddhi, gaps, and session memory."""
        self._conversation = Conversation(max_tokens=self._conversation.max_tokens)
        self._safety_guard.reset_session()
        self._buddhi.reset()
        self._gaps = GapTracker()
        self._memory.clear_session("steward")
        logger.info("Conversation reset")

    def _reset_conversation(self) -> None:
        """Reset conversation between autonomous tasks — keep system prompt only.

        Called before each KARMA dispatch. Each task is independent.
        Learning persists via Hebbian weights (cross-session).
        Conversation is ephemeral — prevents state bloat in daemon mode.
        """
        if self._conversation is None:
            return
        sys_msg = (
            self._conversation.messages[0]
            if self._conversation.messages and self._conversation.messages[0].role == MessageRole.SYSTEM
            else None
        )
        max_tok = self._conversation.max_tokens
        self._conversation = Conversation(max_tokens=max_tok)
        if sys_msg is not None:
            self._conversation.messages.insert(0, sys_msg)

    # ── GAD-000 Protocol Implementation ──────────────────────────────

    def _srotra_scope(self) -> str:
        """Determine SROTRA perception scope: local or local+remote."""
        from vibe_core.mahamantra.protocols._sense import Jnanendriya

        git_sense = self._senses.senses.get(Jnanendriya.SROTRA)
        if git_sense and isinstance(git_sense, RemotePerception) and git_sense.has_remote_perception():
            return "local+remote"
        return "local"

    def discover(self) -> dict[str, object]:
        """GAD-000 Discoverability — machine-readable capability description.

        Complete BG 13.6-7 Ksetra (field) mapping:
          24 Prakriti elements (kshetra.py) + 1 Jiva (LLM)
          + Ksetra-jna (field observer)
          + Ksetra properties (vedana, cetana, dhrti, iccha/dvesha)
        """
        from steward.kshetra import STEWARD_KSHETRA

        return {
            "name": "StewardAgent",
            "version": __version__,
            "type": "superagent",
            "architecture": "sankhya_25",
            "kshetra_elements": len(STEWARD_KSHETRA) + 1,  # 24 Prakriti + 1 Jiva
            "tools": self._registry.list_tools(),
            "tool_providers": [p.name for p in self._tool_providers],
            "providers": len(self._provider) if isinstance(self._provider, ChamberProvider) else 1,
            # ── Antahkarana (BG 13.6: inner instrument) ──
            "antahkarana": {
                "manas": "steward.antahkarana.manas",  # perceive intent
                "buddhi": "steward.buddhi",  # discriminate
                "ahankara": "steward.agent",  # identity (Jiva)
                "chitta": "steward.antahkarana.chitta",  # store impressions
                "gandha": "steward.antahkarana.gandha",  # detect patterns (tanmatra #9)
            },
            # ── Ksetra-jna (BG 13.1-2: knower of the field) ──
            "ksetrajna": "steward.antahkarana.ksetrajna",  # meta-observer
            # ── Ksetra properties (BG 13.6-7: field qualities) ──
            "kshetra_properties": {
                "vedana": True,  # sukham/duhkham — health pulse
                "cetana": True,  # life symptoms — heartbeat
                "dhrti": True,  # conviction — narasimha + safety guard
                "iccha_dvesha": True,  # desire/aversion — hebbian synaptic
            },
            # ── 5 Jnanendriyas (BG 13.6: knowledge senses) ──
            "jnanendriyas": {
                "srotra": {"module": "git_sense", "perceives": self._srotra_scope()},
                "tvak": {"module": "project_sense", "perceives": "local"},
                "caksu": {"module": "code_sense", "perceives": "local"},
                "jihva": {"module": "testing_sense", "perceives": "local"},
                "ghrana": {"module": "health_sense", "perceives": "local"},
            },
            # ── 5 Karmendriyas (BG 13.6: action organs) ──
            "karmendriyas": {
                "vak": "AgentLoop._call_llm",  # speech → LLM prompts
                "pani": "ToolRegistry.execute",  # hands → tool execution
                "pada": "MahaAttention",  # feet → O(1) routing
                "payu": "SamskaraContext.compact",  # elimination → context GC
                "upastha": "boot",  # creation → service genesis
            },
            "active_gaps": len(self._gaps),
            "jiva": self._get_persona(),
            "synaptic_weights": self._synaptic.weight_count,
            "protocol_services": {
                "cache": ServiceRegistry.get(SVC_CACHE) is not None,
                "narasimha": ServiceRegistry.get(SVC_NARASIMHA) is not None,
            },
            "cwd": self._cwd,
            "max_context_tokens": self._conversation.max_tokens,
            "max_output_tokens": self._max_output_tokens,
        }

    def get_state(self) -> dict[str, object]:
        """GAD-000 Observability — current agent state."""
        session_stats = self._memory.recall("session_stats", session_id="steward") or {}
        cache = ServiceRegistry.get(SVC_CACHE)
        cache_stats = cache.get_stats() if cache else {}
        return {
            "conversation_messages": len(self._conversation.messages),
            "conversation_tokens": self._conversation.total_tokens,
            "context_budget_pct": int(self._conversation.total_tokens / self._conversation.max_tokens * 100)
            if self._conversation.max_tokens
            else 0,
            "tools_registered": self._registry.list_tools(),
            "safety_guard_active": self._safety_guard is not None,
            "memory_active": self._memory is not None,
            "ksetrajna": self._ksetrajna.stats(),
            "buddhi_phase": self._buddhi.phase,
            "chitta_stats": self._buddhi.stats,
            "session_stats": session_stats,
            "gaps": self._gaps.stats,
            "senses": self._senses.boot_summary(),
            "cache_stats": cache_stats,
            "vedana": {
                "health": self.vedana.health,
                "guna": self.vedana.guna,
                "provider": self.vedana.provider_health,
                "errors": self.vedana.error_pressure,
                "context": self.vedana.context_pressure,
                "synaptic": self.vedana.synaptic_confidence,
                "tools": self.vedana.tool_success_rate,
            },
            "cetana": self._cetana.stats(),
            "config": {
                "model": self._config.model,
                "auto_summarize": self._config.auto_summarize,
                "persist_memory": self._config.persist_memory,
            },
        }

    @property
    def ksetrajna(self) -> KsetraJna:
        """KsetraJna — meta-observer of the entire field."""
        return self._ksetrajna

    @property
    def vedana(self):
        """Sukham/Duhkham — the agent's own health pulse."""
        # Provider health
        p_alive, p_total = 1, 1
        if isinstance(self._provider, ChamberProvider):
            stats = self._provider.stats()
            providers = stats.get("providers", [])
            p_total = max(len(providers), 1)
            p_alive = sum(1 for p in providers if isinstance(p, dict) and p.get("alive"))

        # Context pressure
        ctx_used = (
            self._conversation.total_tokens / self._conversation.max_tokens if self._conversation.max_tokens else 0.0
        )

        # Synaptic weights — via public API (no private access)
        syn_weights = self._buddhi.synaptic_weights()

        # Buddhi error/call counts from recent session
        session_stats = self._memory.recall("session_stats", session_id="steward") or {}
        errors = session_stats.get("total_errors", 0)
        calls = session_stats.get("total_tool_calls", 0)

        return measure_vedana(
            provider_alive=p_alive,
            provider_total=p_total,
            recent_errors=errors,
            recent_calls=max(calls, 1),
            context_used=ctx_used,
            synaptic_weights=syn_weights,
            tool_successes=max(calls - errors, 0),
            tool_total=max(calls, 1),
        )

    def test_tapas(self) -> bool:
        """GAD-000 Austerity — are resources constrained?"""
        # Tapas: context budget is within limits
        return self._conversation.total_tokens <= self._conversation.max_tokens

    def test_saucam(self) -> bool:
        """GAD-000 Cleanliness — are connections authorized?"""
        # Saucam: safety guard is active (Iron Dome)
        return self._safety_guard is not None

    # ── HealthGate Protocol ──────────────────────────────────────────

    @property
    def health_anomaly(self) -> bool:
        with self._health_lock:
            return self._health_anomaly_flag

    @property
    def health_anomaly_detail(self) -> str:
        with self._health_lock:
            return self._health_anomaly_detail_str

    def clear_health_anomaly(self) -> None:
        with self._health_lock:
            self._health_anomaly_flag = False
            self._health_anomaly_detail_str = ""

    def _wire_think_tool(self) -> None:
        """Connect ThinkTool to Antahkarana components (neuro-symbolic bridge)."""
        from steward.tools.think import ThinkTool

        for tool_name in self._registry.list_tools():
            tool = self._registry.get(tool_name)
            if isinstance(tool, ThinkTool):
                tool._chitta = self._buddhi._chitta
                tool._vedana_source = lambda: self.vedana
                tool._ksetrajna = self._ksetrajna
                try:
                    from vibe_core.mahamantra.substrate.manas.buddhi import MahaBuddhi

                    tool._maha_buddhi = MahaBuddhi()
                except ImportError:
                    pass
                logger.debug("ThinkTool wired to Antahkarana")
                return

    def close(self) -> None:
        """Graceful shutdown — persist state and stop heartbeat."""
        # Save Hebbian weights for cross-session learning
        synapse_store = ServiceRegistry.get(SVC_SYNAPSE_STORE)
        if synapse_store is not None:
            try:
                synapse_store.save()
            except Exception as e:
                logger.warning("Synapse save failed during shutdown: %s", e)
        self._cetana.stop()

    def _on_cetana_phase(self, phase: object, beat: object) -> None:
        """Cetana 4-phase MURALI callback — O(1) dispatch table."""
        from steward.cetana import Phase

        if not isinstance(phase, Phase):
            return

        handler = self._phase_dispatch.get(phase)
        if handler is None:
            return
        try:
            handler()
        except Exception as e:
            logger.debug("Cetana phase %s error (non-fatal): %s", phase.name, e)

    def _phase_genesis(self) -> None:
        """GENESIS: dispatch discovery hooks, then generate tasks via Sankalpa."""
        ctx = self._make_phase_context()
        hooks = ServiceRegistry.get(SVC_PHASE_HOOKS)
        if hooks is not None:
            from steward.phase_hook import GENESIS

            hooks.dispatch(GENESIS, ctx)
        # After discovery hooks run, generate tasks from Sankalpa
        self._autonomy.phase_genesis(
            last_interaction=self._last_user_interaction,
        )

    def _phase_dharma(self) -> None:
        """DHARMA: dispatch registered hooks (health, reaper, marketplace, federation)."""
        ctx = self._make_phase_context()
        hooks = ServiceRegistry.get(SVC_PHASE_HOOKS)
        if hooks is not None:
            from steward.phase_hook import DHARMA

            hooks.dispatch(DHARMA, ctx)
        # Read back mutable output from hooks
        if ctx.health_anomaly:
            with self._health_lock:
                self._health_anomaly_flag = True
                self._health_anomaly_detail_str = ctx.health_anomaly_detail

    def _phase_karma(self) -> None:
        """KARMA: dispatch registered hooks, then execute next task via AutonomyEngine."""
        ctx = self._make_phase_context()
        hooks = ServiceRegistry.get(SVC_PHASE_HOOKS)
        if hooks is not None:
            from steward.phase_hook import KARMA

            hooks.dispatch(KARMA, ctx)
        self._autonomy.phase_karma()

    def _phase_moksha(self) -> None:
        """MOKSHA: dispatch registered hooks (synapse, persistence, federation)."""
        ctx = self._make_phase_context()
        hooks = ServiceRegistry.get(SVC_PHASE_HOOKS)
        if hooks is not None:
            from steward.phase_hook import MOKSHA

            hooks.dispatch(MOKSHA, ctx)

    def _make_phase_context(self) -> object:
        """Build PhaseContext for hook dispatch."""
        from steward.phase_hook import PhaseContext

        return PhaseContext(
            cwd=self._cwd,
            vedana=self.vedana,
            last_interaction=self._last_user_interaction,
        )

    def _on_cetana_anomaly(self, beat: object) -> None:
        """Cetana detected health anomaly — set flag + emit signal.

        The anomaly flag is read by the engine loop to inject health warnings.
        This is the bridge: Cetana (observer) → Engine (actor).
        """
        from steward.cetana import CetanaBeat

        if not isinstance(beat, CetanaBeat):
            return

        # Set anomaly flag — engine reads via HealthGate protocol
        # Lock protects cross-thread access (Cetana daemon → async loop)
        with self._health_lock:
            self._health_anomaly_flag = True
            self._health_anomaly_detail_str = (
                f"health={beat.vedana.health:.2f} ({beat.vedana.guna}), "
                f"provider={beat.vedana.provider_health:.2f}, "
                f"errors={beat.vedana.error_pressure:.2f}"
            )

        agent_bus.emit_anomaly(beat.vedana.health, beat.vedana.guna, beat.beat_number)

    # ── Private Helpers ────────────────────────────────────────────────

    def _get_persona(self) -> dict[str, str] | None:
        """Lazy persona derivation — mahamantra import takes ~4s."""
        if not self._persona_loaded:
            self._persona = agent_memory.load_persona()
            self._persona_loaded = True
        return self._persona
