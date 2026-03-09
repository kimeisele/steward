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
from steward.buddhi import Buddhi
from steward.config import StewardConfig, load_config
from steward.context import SamskaraContext
from steward.gaps import GapTracker
from steward.loop.engine import AgentLoop
from steward.senses import SenseCoordinator
from steward.services import (
    SVC_ATTENTION,
    SVC_CACHE,
    SVC_DIAMOND,
    SVC_EVENT_BUS,
    SVC_MEMORY,
    SVC_NARASIMHA,
    SVC_PROMPT_CONTEXT,
    SVC_SAFETY_GUARD,
    SVC_SIGNAL_BUS,
    SVC_TOOL_REGISTRY,
    SVC_VENU,
    boot,
)
from steward.session_ledger import SessionLedger, SessionRecord
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
from steward.types import AgentEvent, AgentUsage, Conversation, EventType, LLMProvider, Message, MessageRole
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
        self._load_synaptic_from_memory()
        self._synaptic.decay()  # temporal decay on boot — old patterns fade

        # Buddhi persists across turns (cross-turn Chitta awareness)
        self._buddhi = Buddhi(synaptic=self._synaptic)
        self._load_chitta_from_memory()

        # Session ledger (cross-session learning)
        self._ledger = SessionLedger(cwd=self._cwd)

        # 5 Jnanendriyas — deterministic environmental perception (zero LLM)
        self._senses = SenseCoordinator(cwd=self._cwd)

        # Gap tracker — self-awareness of capability gaps
        self._gaps = GapTracker()
        self._load_gaps_from_memory()

        # Persona — persistent identity (from steward-protocol)
        self._persona = self._load_persona()

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
        self._emit_startup_signal()

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
        # Re-perceive senses (infrastructure use — cheap, deterministic, zero LLM)
        if not self._custom_prompt:
            self._senses.perceive_all()
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
        )
        async for event in loop.run(task):
            self._emit_signal(event)
            self._emit_event_bus(event)
            # Track tool failures as gaps
            if event.type == EventType.TOOL_RESULT and event.content:
                result = event.content
                if hasattr(result, "success") and not result.success:  # type: ignore[union-attr]
                    error = getattr(result, "error", "") or ""
                    tool_name = event.tool_use.name if event.tool_use else "unknown"
                    self._gaps.record_tool_failure(tool_name, str(error))
            if event.type == EventType.DONE and event.usage:
                self._record_session_stats(event.usage)
                self._record_session_ledger(task, event.usage)
                # Hebbian learning: record outcome, persist to Memory
                success = event.usage.buddhi_errors <= event.usage.tool_calls // 2
                self._buddhi.record_outcome(success)
                self._save_synaptic_to_memory()
                # Cross-turn: merge reads, clear impressions, persist
                self._buddhi._chitta.end_turn()
                self._save_chitta_to_memory()
                self._save_gaps_to_memory()
            yield event

    def _emit_startup_signal(self) -> None:
        """Emit AGENT_STARTUP signal when agent is created."""
        from vibe_core.steward.bus import Signal, SignalType

        bus = ServiceRegistry.get(SVC_SIGNAL_BUS)
        if bus is None:
            return
        bus.emit(
            Signal(
                signal_type=SignalType.AGENT_STARTUP,
                source_agent="steward",
                payload={"tools": self._registry.list_tools(), "cwd": self._cwd},
            )
        )

    def _emit_signal(self, event: AgentEvent) -> None:
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
            success = False
            if event.content and hasattr(event.content, "success"):
                success = event.content.success  # type: ignore[union-attr]
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

    def _emit_event_bus(self, event: AgentEvent) -> None:
        """Emit to real EventBus (Narada stream) for observability."""
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
            success = False
            if event.content and hasattr(event.content, "success"):
                success = event.content.success  # type: ignore[union-attr]
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

    def _load_synaptic_from_memory(self) -> None:
        """Restore Hebbian synaptic weights from PersistentMemory.

        Survives ephemeral contexts (CI, API containers) — no local files needed.
        """
        data = self._memory.recall("synaptic_weights", session_id="steward")
        if data and isinstance(data, dict):
            for key, weight in data.items():
                self._synaptic._weights[key] = float(weight)
            logger.debug("Synaptic weights restored: %d entries", len(data))

    def _save_synaptic_to_memory(self) -> None:
        """Persist Hebbian synaptic weights to PersistentMemory."""
        weights = self._synaptic.snapshot()
        if weights:
            self._memory.remember(
                "synaptic_weights",
                weights,
                session_id="steward",
                tags=["synaptic", "hebbian"],
            )

    def _load_chitta_from_memory(self) -> None:
        """Restore Chitta's cross-turn state from PersistentMemory."""
        summary = self._memory.recall("chitta_summary", session_id="steward")
        if summary and isinstance(summary, dict):
            self._buddhi._chitta.load_summary(summary)
            logger.debug(
                "Chitta restored: %d prior reads",
                len(self._buddhi._chitta.prior_reads),
            )

    def _save_chitta_to_memory(self) -> None:
        """Persist Chitta's cross-turn state to PersistentMemory."""
        summary = self._buddhi._chitta.to_summary()
        self._memory.remember(
            "chitta_summary",
            summary,
            session_id="steward",
            tags=["chitta"],
        )

    def _load_gaps_from_memory(self) -> None:
        """Restore gap tracker state from PersistentMemory."""
        data = self._memory.recall("gap_tracker", session_id="steward")
        if data and isinstance(data, list):
            self._gaps.load_from_dict(data)
            active = len(self._gaps)
            if active:
                logger.debug("Restored %d active gaps", active)

    def _save_gaps_to_memory(self) -> None:
        """Persist gap tracker state to PersistentMemory."""
        self._memory.remember(
            "gap_tracker",
            self._gaps.to_dict(),
            session_id="steward",
            tags=["gaps"],
        )

    def _load_persona(self) -> dict[str, str] | None:
        """Derive Jiva identity from MahaMantra VM (deterministic, from seed).

        No YAML files, no text injection. Identity IS what the seed computes.
        Uses mahamantra() from steward-protocol — the same VM that agent-city uses.
        """
        try:
            from vibe_core.mahamantra import mahamantra

            vm = mahamantra("steward")
            jiva = {
                "guna": vm["guna"]["mode"],
                "guardian": vm["guardian"],
                "quarter": vm["quarter"],
                "trinity": vm["trinity_function"],
                "position": str(vm["position"]),
                "holy_name": vm["holy_name"],
            }
            logger.info(
                "Jiva identity: %s | %s | %s | %s",
                jiva["guna"], jiva["guardian"], jiva["quarter"], jiva["trinity"],
            )
            return jiva
        except Exception as e:
            logger.debug("Jiva derivation skipped: %s", e)
            return None

    def _format_persona_prompt(self) -> str:
        """Minimal Jiva identity section — who, not how to behave."""
        if not self._persona:
            return ""
        j = self._persona
        return (
            f"\n\n## Jiva Identity\n"
            f"{j['guna']} | {j['guardian']} | {j['quarter']} | {j['trinity']}"
        )

    def _record_session_stats(self, usage: AgentUsage) -> None:
        """Record cumulative session stats in Memory (Chitta).

        Tracks tokens, tool calls, and Buddhi classifications across turns.
        Persists across sessions via PersistentMemory.
        """
        existing = self._memory.recall("session_stats", session_id="steward") or {}
        stats = {
            "turns": existing.get("turns", 0) + 1,
            "total_input_tokens": existing.get("total_input_tokens", 0) + usage.input_tokens,
            "total_output_tokens": existing.get("total_output_tokens", 0) + usage.output_tokens,
            "total_tool_calls": existing.get("total_tool_calls", 0) + usage.tool_calls,
            "total_errors": existing.get("total_errors", 0) + usage.buddhi_errors,
            "total_reflections": existing.get("total_reflections", 0) + usage.buddhi_reflections,
        }
        # Track Buddhi classification distribution
        classifications = existing.get("classifications", {})
        if usage.buddhi_action:
            classifications[usage.buddhi_action] = classifications.get(usage.buddhi_action, 0) + 1
        stats["classifications"] = classifications
        self._memory.remember("session_stats", stats, session_id="steward", tags=["stats"])

    def _record_session_ledger(self, task: str, usage: AgentUsage) -> None:
        """Record this task in the session ledger for cross-session learning."""
        chitta = self._buddhi._chitta
        outcome = "error" if usage.buddhi_errors > usage.tool_calls // 2 else "success"
        if usage.buddhi_errors > 0 and outcome == "success":
            outcome = "partial"

        self._ledger.record(
            SessionRecord(
                task=task,
                outcome=outcome,
                summary=f"{usage.buddhi_action or 'task'}: {usage.rounds} rounds, {usage.tool_calls} tools",
                tokens=usage.input_tokens + usage.output_tokens,
                tool_calls=usage.tool_calls,
                rounds=usage.rounds,
                files_read=chitta.files_read[:10],
                files_written=chitta.files_written[:10],
                buddhi_action=usage.buddhi_action or "",
                buddhi_phase=str(usage.buddhi_phase) if usage.buddhi_phase else "",
                errors=usage.buddhi_errors,
            )
        )

    def _resolve_dynamic_context(self) -> dict[str, str] | None:
        """Resolve dynamic context from PromptContext (git, time, etc.)."""
        prompt_ctx = ServiceRegistry.get(SVC_PROMPT_CONTEXT)
        if prompt_ctx is None:
            return None
        try:
            # Only resolve what senses don't cover
            # (GitSense covers branch/commits, ProjectSense covers structure)
            return prompt_ctx.resolve(["system_time", "project_structure"])
        except Exception:
            logger.debug("PromptContext resolve failed, skipping dynamic context")
            return None

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

    def discover(self) -> dict[str, object]:
        """GAD-000 Discoverability — machine-readable capability description.

        Includes Kshetra awareness (25 Sankhya elements mapped).
        """
        from steward.kshetra import STEWARD_KSHETRA

        return {
            "name": "StewardAgent",
            "version": __version__,
            "type": "superagent",
            "architecture": "sankhya_25",
            "kshetra_elements": len(STEWARD_KSHETRA) + 1,  # 24 Prakriti + 1 Jiva
            "tools": self._registry.list_tools(),
            "providers": len(self._provider) if hasattr(self._provider, "__len__") else 1,
            "capabilities": [
                "autonomous_coding",
                "tool_execution",
                "context_compaction",
                "session_resume",
                "multi_provider_failover",
                "buddhi_phase_machine",
                "gandha_pattern_detection",
                "ephemeral_cache",
                "diamond_tdd",
                "web_search",
                "gap_detection",
                "jiva_identity",
                "hebbian_synaptic",
            ],
            "antahkarana": ["manas", "buddhi", "chitta", "gandha"],
            "jnanendriyas": list(self._senses.senses.keys()),
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
        cache_stats = cache.get_stats() if cache and hasattr(cache, "get_stats") else {}
        return {
            "conversation_messages": len(self._conversation.messages),
            "conversation_tokens": self._conversation.total_tokens,
            "context_budget_pct": int(self._conversation.total_tokens / self._conversation.max_tokens * 100)
            if self._conversation.max_tokens
            else 0,
            "tools_registered": self._registry.list_tools(),
            "safety_guard_active": self._safety_guard is not None,
            "memory_active": self._memory is not None,
            "heartbeat_state": self.heartbeat.get_summary(),
            "buddhi_phase": self._buddhi.phase,
            "chitta_stats": self._buddhi.stats,
            "session_stats": session_stats,
            "gaps": self._gaps.stats,
            "senses": self._senses.boot_summary(),
            "cache_stats": cache_stats,
            "config": {
                "model": self._config.model,
                "auto_summarize": self._config.auto_summarize,
                "persist_memory": self._config.persist_memory,
            },
        }

    def test_tapas(self) -> bool:
        """GAD-000 Austerity — are resources constrained?"""
        # Tapas: context budget is within limits
        return self._conversation.total_tokens <= self._conversation.max_tokens

    def test_saucam(self) -> bool:
        """GAD-000 Cleanliness — are connections authorized?"""
        # Saucam: safety guard is active (Iron Dome)
        return self._safety_guard is not None

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
