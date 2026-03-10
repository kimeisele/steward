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
from pathlib import Path
from typing import AsyncIterator

from steward import __version__
from steward import agent_bus, agent_memory
from steward.antahkarana.ksetrajna import KsetraJna
from steward.antahkarana.vedana import measure_vedana
from steward.buddhi import Buddhi
from steward.cetana import Cetana
from steward.config import StewardConfig, load_config
from steward.context import SamskaraContext
from steward.gaps import GapTracker
from steward.loop.engine import AgentLoop
from steward.protocols import RemotePerception
from steward.senses import SenseCoordinator
from steward.services import (
    SVC_ANTARANGA,
    SVC_ATTENTION,
    SVC_CACHE,
    SVC_DIAMOND,
    SVC_MEMORY,
    SVC_NARASIMHA,
    SVC_SAFETY_GUARD,
    SVC_TOOL_REGISTRY,
    SVC_VENU,
    boot,
)
from steward.session_ledger import SessionLedger
from steward.tools.agent_internet import AgentInternetTool
from steward.tools.bash import BashTool
from steward.tools.edit import EditTool
from steward.tools.glob import GlobTool
from steward.tools.grep import GrepTool
from steward.tools.http import HttpTool
from steward.tools.read_file import ReadFileTool
from steward.tools.sub_agent import SubAgentTool
from steward.tools.web_search import WebSearchTool
from steward.tools.write_file import WriteFileTool
from steward.types import AgentEvent, ChamberProvider, Conversation, EventType, LLMProvider, Message, MessageRole, ToolResult
from vibe_core.di import ServiceRegistry
from vibe_core.mahamantra.substrate.manas.synaptic import HebbianSynaptic
from vibe_core.mahamantra.adapters.attention import MahaAttention
from vibe_core.mahamantra.protocols._gad import GADBase
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


def _build_system_prompt(
    base: str,
    cwd: str,
    tool_names: list[str],
    dynamic_context: dict[str, str] | None = None,
    project_instructions: str | None = None,
    session_history: str | None = None,
) -> str:
    """Build minimal system prompt. Every token counts.

    Only includes: base instruction + cwd.
    Tool signatures injected by engine (brain-in-a-jar).
    Everything else is deterministic infrastructure — LLM doesn't need it.
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

        # Build tool list
        builtin_tools = self._builtin_tools()
        all_tools = builtin_tools + (tools or [])

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

        # 5 Jnanendriyas — deterministic environmental perception (zero LLM)
        self._senses = SenseCoordinator(cwd=self._cwd)

        # Gap tracker — self-awareness of capability gaps
        self._gaps = GapTracker()
        agent_memory.load_gaps(self._memory, self._gaps)

        # Persona — persistent identity (from steward-protocol)
        self._persona = agent_memory.load_persona()

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
                self._registry.list_tools(),
            )
            self._system_prompt = self._base_system_prompt

            # Senses still perceive (infrastructure use), just not in LLM prompt
            self._senses.perceive_all()

        # Emit AGENT_STARTUP signal
        agent_bus.emit_startup(self._registry.list_tools(), self._cwd)

        # Cetana — autonomous heartbeat driven by vedana health (BG 13.6-7)
        # Daemon thread: adapts monitoring frequency to agent health.
        # Does NOT think or act — only observes and signals.
        self._health_anomaly_flag = False
        self._health_anomaly_detail_str = ""
        self._cetana = Cetana(
            vedana_source=lambda: self.vedana,
            on_anomaly=self._on_cetana_anomaly,
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
        final_text = ""
        streamed_chunks: list[str] = []
        async for event in self.run_stream(task):
            if event.type == EventType.TEXT_DELTA:
                streamed_chunks.append(str(event.content) if event.content else "")
            elif event.type == EventType.TEXT:
                final_text = str(event.content) if event.content else ""
            elif event.type == EventType.ERROR:
                return f"[Error: {event.content}]"
        # If we got streaming chunks, assemble them
        if streamed_chunks:
            return "".join(streamed_chunks)
        return final_text

    def run_sync(self, task: str) -> str:
        """Execute a task autonomously (sync wrapper).

        Convenience method for simple usage and testing.
        """
        return asyncio.run(self.run(task))

    async def chat(self, message: str) -> str:
        """Continue an existing conversation (async)."""
        return await self.run(message)

    def chat_sync(self, message: str) -> str:
        """Continue an existing conversation (sync wrapper)."""
        return self.run_sync(message)

    async def run_stream(self, task: str) -> AsyncIterator[AgentEvent]:
        """Execute a task and yield events as they happen.

        Re-perceives senses before each run for live environmental awareness.
        Emits to both SignalBus (simple) and EventBus (full Narada stream).
        Passes Memory to AgentLoop for cross-turn file tracking.
        Buddhi persists across turns — Chitta retains file awareness.
        Records cumulative session stats in Memory after each turn.
        """
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
            # NOTE: Session ledger is NOT injected into prompt.
            # Learning is INFRASTRUCTURE (Hebbian, Chitta, Gandha patterns),
            # not LLM prompt bloat. The 25th element observes, not memorizes.
            effective_prompt = "".join(context_parts)
        else:
            effective_prompt = self._system_prompt

        # Update system message if conversation already has one (multi-run freshness)
        if (
            self._conversation.messages
            and self._conversation.messages[0].role == MessageRole.SYSTEM
        ):
            self._conversation.messages[0] = Message(
                role=MessageRole.SYSTEM, content=effective_prompt
            )

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
            "providers": len(self._provider) if isinstance(self._provider, ChamberProvider) else 1,
            # ── Antahkarana (BG 13.6: inner instrument) ──
            "antahkarana": {
                "manas": "steward.antahkarana.manas",       # perceive intent
                "buddhi": "steward.buddhi",                  # discriminate
                "ahankara": "steward.agent",                 # identity (Jiva)
                "chitta": "steward.antahkarana.chitta",      # store impressions
                "gandha": "steward.antahkarana.gandha",      # detect patterns (tanmatra #9)
            },
            # ── Ksetra-jna (BG 13.1-2: knower of the field) ──
            "ksetrajna": "steward.antahkarana.ksetrajna",    # meta-observer
            # ── Ksetra properties (BG 13.6-7: field qualities) ──
            "kshetra_properties": {
                "vedana": True,        # sukham/duhkham — health pulse
                "cetana": True,        # life symptoms — heartbeat
                "dhrti": True,         # conviction — narasimha + safety guard
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
                "vak": "AgentLoop._call_llm",        # speech → LLM prompts
                "pani": "ToolRegistry.execute",       # hands → tool execution
                "pada": "MahaAttention",              # feet → O(1) routing
                "payu": "SamskaraContext.compact",     # elimination → context GC
                "upastha": "boot",                     # creation → service genesis
            },
            "active_gaps": len(self._gaps),
            "jiva": self._persona,
            "synaptic_weights": self._synaptic.weight_count,
            "protocol_services": {
                "cache": ServiceRegistry.get(SVC_CACHE) is not None,
                "diamond": ServiceRegistry.get(SVC_DIAMOND) is not None,
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
            self._conversation.total_tokens / self._conversation.max_tokens
            if self._conversation.max_tokens
            else 0.0
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
        return self._health_anomaly_flag

    @property
    def health_anomaly_detail(self) -> str:
        return self._health_anomaly_detail_str

    def clear_health_anomaly(self) -> None:
        self._health_anomaly_flag = False
        self._health_anomaly_detail_str = ""

    def close(self) -> None:
        """Graceful shutdown — stop cetana heartbeat."""
        self._cetana.stop()

    def _on_cetana_anomaly(self, beat: object) -> None:
        """Cetana detected health anomaly — set flag + emit signal.

        The anomaly flag is read by the engine loop to inject health warnings.
        This is the bridge: Cetana (observer) → Engine (actor).
        """
        from steward.cetana import CetanaBeat

        if not isinstance(beat, CetanaBeat):
            return

        # Set anomaly flag — engine reads via HealthGate protocol
        self._health_anomaly_flag = True
        self._health_anomaly_detail_str = (
            f"health={beat.vedana.health:.2f} ({beat.vedana.guna}), "
            f"provider={beat.vedana.provider_health:.2f}, "
            f"errors={beat.vedana.error_pressure:.2f}"
        )

        agent_bus.emit_anomaly(beat.vedana.health, beat.vedana.guna, beat.beat_number)

    # ── Private Helpers ────────────────────────────────────────────────

    def _builtin_tools(self) -> list[Tool]:
        """Build the default tool set."""
        return [
            BashTool(cwd=self._cwd),
            ReadFileTool(),
            WriteFileTool(),
            GlobTool(cwd=self._cwd),
            EditTool(),
            GrepTool(cwd=self._cwd),
            HttpTool(),
            WebSearchTool(),
            AgentInternetTool(),
            SubAgentTool(cwd=self._cwd),
        ]
