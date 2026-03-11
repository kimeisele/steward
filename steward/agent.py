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
    SVC_MEMORY,
    SVC_NARASIMHA,
    SVC_NORTH_STAR,
    SVC_SAFETY_GUARD,
    SVC_SANKALPA,
    SVC_SYNAPSE_STORE,
    SVC_TASK_MANAGER,
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


def _parse_intent_from_title(title: str) -> object | None:
    """Parse TaskIntent from title prefix like '[HEALTH_CHECK] ...'.

    Returns TaskIntent enum or None. Title prefix is the persistence-safe
    encoding — survives TaskManager disk serialization (unlike metadata).
    """
    from steward.intents import TaskIntent

    if not title.startswith("["):
        return None
    bracket_end = title.find("]")
    if bracket_end < 2:
        return None
    intent_name = title[1:bracket_end]
    # Match by enum name (e.g., "HEALTH_CHECK")
    try:
        return TaskIntent[intent_name]
    except KeyError:
        return None


def _problem_fingerprint(problem: str) -> str:
    """Extract granular context from a problem description.

    Prevents learned helplessness by making Hebbian keys specific:
    - If file paths found: "api.py:utils.py" (file-specific learning)
    - If error type found: "TypeError:async" (error-specific learning)
    - Fallback: first 3 significant words (keyword-based)

    This ensures "failed to fix async bug in api.py" doesn't poison
    the weight for "fix typo in readme.md" — they're different contexts.
    """
    import re

    # Level 1: Extract file paths (most specific)
    files = re.findall(r"[\w/.-]+\.py\b", problem)
    if files:
        # Deduplicate, sort, take first 3
        unique = sorted(set(files))[:3]
        return ":".join(unique)

    # Level 2: Extract error type keywords
    error_types = re.findall(
        r"\b(TypeError|ValueError|ImportError|SyntaxError|AttributeError|KeyError|RuntimeError)\b",
        problem,
    )
    if error_types:
        return ":".join(sorted(set(error_types))[:2])

    # Level 3: Extract workflow/test names (for CI)
    workflow = re.search(r"workflow\s+'([^']+)'", problem)
    if workflow:
        return workflow.group(1)

    # Level 4: Significant words fallback
    words = re.findall(r"\b[a-z]{5,}\b", problem.lower())
    # Filter out generic words
    generic = {"check", "error", "agent", "health", "found", "failing", "critical", "please", "should"}
    specific = [w for w in words if w not in generic]
    if specific:
        return ":".join(sorted(set(specific))[:3])

    return ""


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
        self._health_lock = threading.Lock()
        self._health_anomaly_flag = False
        self._health_anomaly_detail_str = ""
        self._last_user_interaction = time.monotonic()
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

    async def run_autonomous(self, idle_minutes: int | None = None) -> str | None:
        """Pick the next task from TaskManager and execute it deterministically.

        Deterministic dispatch: reads intent_type from task metadata,
        maps to TaskIntent enum, calls a Python method. 0 LLM tokens.
        The LLM only wakes up if the method finds a real error to fix.

        Args:
            idle_minutes: Override idle time for task generation.
                In cron mode the agent just booted (idle_minutes=0),
                but we want Sankalpa to fire. Pass 15 for a 15-min cron cycle.

        Returns the result text, or None if no tasks are pending.
        Called by cron/scheduler when no user input is available.
        """
        from steward.intents import TaskIntent
        from vibe_core.task_types import TaskStatus

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            return None

        # Generate tasks first — Sankalpa might not have fired yet
        # (cron runs last <1min, Sankalpa needs idle time to trigger)
        self._phase_genesis(idle_override=idle_minutes)

        task = task_mgr.get_next_task()
        if task is None:
            return None

        logger.info("Autonomous: working on task '%s' (id=%s)", task.title, task.id)
        task_mgr.update_task(task.id, status=TaskStatus.IN_PROGRESS)

        # Parse intent from title prefix [INTENT_NAME] — persistence-safe
        # (metadata mutation is in-memory only, title persists to disk)
        intent = _parse_intent_from_title(task.title)

        if intent is None:
            logger.warning("Autonomous: no typed intent in task '%s' — skipping", task.title)
            task_mgr.update_task(task.id, status=TaskStatus.COMPLETED)
            return None

        try:
            problem = self._dispatch_intent(intent)
            task_mgr.update_task(task.id, status=TaskStatus.COMPLETED)

            # Record in session ledger (even without LLM)
            self._ledger.record_autonomous(intent.name, problem is not None)

            if problem:
                # Granular Hebbian confidence — context-specific, not intent-global
                context = _problem_fingerprint(problem)
                granular_key = f"auto:{intent.name}:{context}" if context else f"auto:{intent.name}"
                auto_weight = self._synaptic.get_weight(granular_key, "fix")

                if auto_weight < 0.2:
                    # DON'T skip — escalate to human attention
                    logger.warning(
                        "Hebbian confidence too low (%.2f) for %s:%s — escalating",
                        auto_weight, intent.name, context,
                    )
                    self._escalate_problem(problem, intent.name, auto_weight)
                    return None

                # Real problem found — guard with CircuitBreaker + Hebbian learning
                logger.info(
                    "Autonomous: %s:%s found problem (confidence=%.2f), invoking LLM",
                    intent.name, context, auto_weight,
                )
                return await self._guarded_llm_fix(problem, intent_name=intent.name)

            logger.info("Autonomous: intent %s completed (no issues found)", intent.name)
            return None
        except Exception as e:
            logger.error("Autonomous: task '%s' failed: %s", task.title, e)
            task_mgr.update_task(task.id, status=TaskStatus.FAILED)
            return None

    def run_autonomous_sync(self, idle_minutes: int | None = None) -> str | None:
        """Sync wrapper for run_autonomous."""
        return asyncio.run(self.run_autonomous(idle_minutes=idle_minutes))

    def _dispatch_intent(self, intent: object) -> str | None:
        """Dispatch a TaskIntent to its deterministic handler.

        Returns None if no issues found, or a problem description
        string that should be sent to the LLM for fixing.
        """
        from steward.intents import TaskIntent

        dispatch = {
            TaskIntent.HEALTH_CHECK: self._execute_health_check,
            TaskIntent.SENSE_SCAN: self._execute_sense_scan,
            TaskIntent.CI_CHECK: self._execute_ci_check,
        }
        handler = dispatch.get(intent)
        if handler is None:
            logger.warning("No handler for intent %s", intent)
            return None
        return handler()

    async def _guarded_llm_fix(self, problem: str, intent_name: str = "") -> str | None:
        """Run LLM fix with multi-gate circuit breaker + Hebbian learning.

        Verification pipeline (fast → slow):
        1. Check breaker not suspended
        2. Baseline test failures
        3. Snapshot working tree
        4. Run LLM fix
        5. Find newly changed files
        6. FAST GATES (milliseconds):
           - Lint gate: ruff — no new syntax/logic errors
           - Security gate: bandit — no new vulnerabilities
           - Blast radius gate: scope limit on files/lines changed
        7. SLOW GATE (seconds): test suite — no new failures

        Hebbian learning (granular, not intent-global):
        - Context-level: auto:{intent}:{fingerprint}/fix
        - Gate-level: auto:{intent}:{fingerprint}/gate:{name}
        - File-level: file:{path}/auto_fix (per-file reputation)

        If ANY gate fails → rollback ALL changes immediately.
        Returns LLM result on success, None on rollback/suspension.
        """
        if self._breaker.is_suspended:
            logger.warning("Circuit breaker suspended — skipping LLM fix for: %s", problem[:100])
            return None

        # Granular Hebbian key: intent + problem context (not just intent)
        context = _problem_fingerprint(problem)
        hebbian_trigger = f"auto:{intent_name}:{context}" if (intent_name and context) else f"auto:{intent_name or 'unknown'}"

        # Step 1: Baseline tests
        test_cmd = "pytest -x -q"
        baseline = self._breaker.count_failures(test_cmd)
        if baseline is None:
            logger.warning("Cannot establish test baseline — running LLM fix unguarded")
            return await self.run(problem)

        # Step 2: Snapshot current dirty files
        files_before = self._breaker.changed_files()

        # Step 3: LLM fix
        result = await self.run(problem)

        # Step 4: Find newly changed files
        files_after = self._breaker.changed_files()
        new_changes = files_after - files_before
        if not new_changes:
            self._breaker.record_success()
            self._hebbian_learn(hebbian_trigger, success=True, changed_files=set())
            return result

        # Step 5: Fast gates (milliseconds) — run BEFORE expensive test suite
        gate_results = self._breaker.run_gates(new_changes)
        failed_gates = [g for g in gate_results if not g.passed]
        if failed_gates:
            details = "; ".join(g.detail for g in failed_gates)
            rolled = self._breaker.rollback_files(new_changes)
            self._breaker.record_rollback()
            self._hebbian_learn(hebbian_trigger, success=False, failed_gates=failed_gates, changed_files=new_changes)
            logger.warning(
                "Verification gates FAILED — rolled back %d files. Gates: %s",
                len(rolled), details,
            )
            return None

        # Step 6: Slow gate — test suite
        post = self._breaker.count_failures(test_cmd)
        if post is None:
            rolled = self._breaker.rollback_files(new_changes)
            self._breaker.record_rollback()
            self._hebbian_learn(hebbian_trigger, success=False, changed_files=new_changes)
            logger.warning("Post-fix test run failed — rolled back %d files: %s", len(rolled), rolled)
            return None

        # Step 7: Compare test results
        if post > baseline:
            rolled = self._breaker.rollback_files(new_changes)
            self._breaker.record_rollback()
            self._hebbian_learn(hebbian_trigger, success=False, changed_files=new_changes)
            logger.warning(
                "LLM fix rolled back (failures %d → %d), %d files: %s",
                baseline, post, len(rolled), rolled,
            )
            return None

        # All gates passed — fix accepted
        self._breaker.record_success()
        self._hebbian_learn(hebbian_trigger, success=True, gate_results=gate_results, changed_files=new_changes)
        logger.info(
            "LLM fix verified: %d gates passed, tests %d → %d, %d files changed",
            len(gate_results), baseline, post, len(new_changes),
        )
        return result

    def _hebbian_learn(
        self,
        trigger: str,
        success: bool,
        failed_gates: list | None = None,
        gate_results: list | None = None,
        changed_files: set[str] | None = None,
    ) -> None:
        """Update Hebbian weights from autonomous fix outcome.

        Three levels of learning granularity:
        1. Context-level: trigger/fix — the specific problem context
        2. Gate-level: trigger/gate:{name} — which verification gates pass/fail
        3. File-level: file:{path}/auto_fix — per-file success/failure history

        This prevents learned helplessness: failing to fix api.py doesn't
        poison the weight for fixing utils.py. Each file builds its own
        reputation independently.
        """
        # Level 1: Context-level learning
        new_weight = self._synaptic.update(trigger, "fix", success)
        logger.debug("Hebbian: %s/fix %s → %.2f", trigger, "reinforced" if success else "weakened", new_weight)

        # Level 2: Gate-specific learning
        if failed_gates:
            for gate in failed_gates:
                self._synaptic.update(trigger, f"gate:{gate.gate}", success=False)
        if success and gate_results:
            for gate in gate_results:
                if gate.passed:
                    self._synaptic.update(trigger, f"gate:{gate.gate}", success=True)

        # Level 3: Per-file learning — builds file reputation map
        if changed_files:
            for filepath in changed_files:
                if filepath.endswith(".py"):
                    self._synaptic.update(f"file:{filepath}", "auto_fix", success)

        # Persist to Memory for cross-session survival
        agent_memory.save_synaptic(self._memory, self._synaptic)

    def _escalate_problem(self, problem: str, intent_name: str, confidence: float) -> None:
        """Escalate a problem the agent can't fix autonomously.

        When Hebbian confidence is too low for a direct fix, don't silently
        skip — record the problem for human attention. The agent NEVER gives up,
        it recognizes its limits and asks for help.

        Writes to .steward/needs_attention.md (human-readable log).
        """
        from datetime import datetime, timezone

        escalation_dir = Path(self._cwd) / ".steward"
        escalation_dir.mkdir(parents=True, exist_ok=True)
        escalation_file = escalation_dir / "needs_attention.md"

        timestamp = datetime.now(timezone.utc).isoformat()[:19]
        entry = (
            f"\n## [{timestamp}] {intent_name} (confidence: {confidence:.2f})\n"
            f"{problem}\n"
            f"_Agent confidence too low for autonomous fix. Human review needed._\n"
        )

        try:
            with open(escalation_file, "a") as f:
                f.write(entry)
            logger.info(
                "Escalated to human: %s (confidence=%.2f) → %s",
                intent_name, confidence, escalation_file,
            )
        except OSError as e:
            logger.warning("Failed to write escalation file: %s", e)

    def _execute_health_check(self) -> str | None:
        """Deterministic health check — 0 tokens.

        Re-perceive senses, check vedana health, report anomalies.
        Returns a problem description only if health is critical.
        """
        self._senses.perceive_all()
        v = self.vedana
        if v.health < 0.3:
            return (
                f"Agent health critical: health={v.health:.2f} ({v.guna}), "
                f"provider={v.provider_health:.2f}, errors={v.error_pressure:.2f}, "
                f"context={v.context_pressure:.2f}. Diagnose and fix the root cause."
            )
        return None

    def _execute_sense_scan(self) -> str | None:
        """Deterministic sense scan — 0 tokens.

        Full sense re-perception. Returns problem description if
        aggregate pain is high (tamas signals from senses).
        """
        aggregate = self._senses.perceive_all()
        if aggregate.total_pain > 0.7:
            failing = [
                f"{j.name}={p.intensity:.2f}"
                for j, p in aggregate.perceptions.items()
                if p.quality == "tamas"
            ]
            return f"Sense scan critical: total_pain={aggregate.total_pain:.2f}, failing={', '.join(failing)}. Investigate."
        return None

    def _execute_ci_check(self) -> str | None:
        """Deterministic CI status check — 0 tokens.

        Query GitSense for CI status. Returns problem description
        only if CI is failing and needs fixing.
        """
        from vibe_core.mahamantra.protocols._sense import Jnanendriya

        git_sense = self._senses.senses.get(Jnanendriya.SROTRA)
        if git_sense is None:
            return None
        try:
            perception = git_sense.perceive()
            ci_status = perception.get("ci_status") if isinstance(perception, dict) else None
            if ci_status and ci_status.get("conclusion") == "failure":
                failing = ci_status.get("name", "unknown workflow")
                return f"CI is failing: workflow '{failing}'. Check the logs and fix the failing tests."
        except Exception as e:
            logger.debug("CI check failed (non-fatal): %s", e)
        return None

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
            compression=ServiceRegistry.get(SVC_COMPRESSION),
            north_star=ServiceRegistry.get(SVC_NORTH_STAR),
            feedback=ServiceRegistry.get(SVC_FEEDBACK),
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

    def close(self) -> None:
        """Graceful shutdown — persist state and stop heartbeat."""
        # Save Hebbian weights for cross-session learning
        synapse_store = ServiceRegistry.get(SVC_SYNAPSE_STORE)
        if synapse_store is not None:
            try:
                synapse_store.save()
            except Exception:
                pass
        self._cetana.stop()

    def _on_cetana_phase(self, phase: object, beat: object) -> None:
        """Cetana 4-phase MURALI callback — wires infrastructure into heartbeat.

        Runs in daemon thread. Must be fast and non-blocking.
        GENESIS: refresh senses, generate tasks via Sankalpa
        DHARMA: integrity checks (lightweight)
        KARMA: trigger pending self-healing work
        MOKSHA: persist learning state (SynapseStore)
        """
        from steward.cetana import Phase

        if not isinstance(phase, Phase):
            return

        try:
            if phase == Phase.GENESIS:
                self._phase_genesis()
            elif phase == Phase.DHARMA:
                self._phase_dharma()
            elif phase == Phase.KARMA:
                self._phase_karma()
            elif phase == Phase.MOKSHA:
                self._phase_moksha()
        except Exception as e:
            logger.debug("Cetana phase %s error (non-fatal): %s", phase.name, e)

    def _phase_genesis(self, idle_override: int | None = None) -> None:
        """GENESIS: Discover — generate typed tasks from Sankalpa intents.

        Maps SankalpaIntent.intent_type → TaskIntent enum. Only creates
        tasks for known intents. Unknown intent types are logged and skipped.
        Each task carries metadata["intent_type"] for deterministic dispatch.

        Args:
            idle_override: Override idle time (for cron mode where agent just booted).
        """
        from steward.intents import INTENT_TYPE_KEY, TaskIntent

        sankalpa = ServiceRegistry.get(SVC_SANKALPA)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if sankalpa is None or task_mgr is None:
            return

        from vibe_core.task_types import TaskStatus

        if idle_override is not None:
            idle_minutes = idle_override
        else:
            idle_minutes = int((time.monotonic() - self._last_user_interaction) / 60)

        # Only count active tasks (not completed/failed) — otherwise
        # Sankalpa never fires again after first run
        active = (
            task_mgr.list_tasks(status=TaskStatus.PENDING)
            + task_mgr.list_tasks(status=TaskStatus.IN_PROGRESS)
        )
        intents = sankalpa.think(
            idle_minutes=idle_minutes,
            pending_intents=len(active),
            ci_green=True,  # TODO: wire GitSense CI status
        )
        for intent in intents:
            # Only accept known typed intents — reject free-text
            typed = TaskIntent.from_intent_type(intent.intent_type)
            if typed is None:
                logger.debug("GENESIS: unknown intent_type '%s' — skipping", intent.intent_type)
                continue

            # Dedup only against active tasks (allow re-running after completion)
            if any(
                t.title.startswith(f"[{typed.name}]")
                for t in active
            ):
                continue

            # Title encodes intent type as prefix — persists to disk
            # (task.metadata mutation is in-memory only, lost on restart)
            # MissionPriority (str enum) → int 0-100 (TaskManager expects int)
            _PRIORITY_MAP = {"critical": 90, "high": 70, "medium": 50, "low": 25}
            raw_priority = getattr(intent, "priority", "medium")
            if hasattr(raw_priority, "value"):
                priority = _PRIORITY_MAP.get(raw_priority.value, 50)
            elif isinstance(raw_priority, int):
                priority = raw_priority
            else:
                priority = _PRIORITY_MAP.get(str(raw_priority), 50)
            task_mgr.add_task(
                title=f"[{typed.name}] {intent.title}",
                priority=priority,
            )

    def _phase_dharma(self) -> None:
        """DHARMA: Govern — vedana health monitoring.

        Checks agent health pulse. If health drops below threshold,
        sets anomaly flag (readable by engine via HealthGate protocol).
        Runs in daemon thread — must be fast, non-blocking.
        """
        v = self.vedana
        if v.health < 0.3:
            with self._health_lock:
                self._health_anomaly_flag = True
                self._health_anomaly_detail_str = (
                    f"DHARMA: health={v.health:.2f} ({v.guna}), "
                    f"errors={v.error_pressure:.2f}, context={v.context_pressure:.2f}"
                )
            logger.warning("DHARMA: health critical (%.2f %s)", v.health, v.guna)

    def _phase_karma(self) -> None:
        """KARMA: Execute — log pending task count.

        The heartbeat observes and signals, it does not execute.
        Actual task dispatch happens in run_autonomous() (called by cron).
        KARMA just logs how many tasks are pending for observability.
        """
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            return
        pending = task_mgr.list_tasks()
        if pending:
            logger.debug("KARMA: %d pending tasks", len(pending))

    def _phase_moksha(self) -> None:
        """MOKSHA: Reflect — persist learning state."""
        synapse_store = ServiceRegistry.get(SVC_SYNAPSE_STORE)
        if synapse_store is not None:
            try:
                synapse_store.save()
            except Exception as e:
                logger.debug("SynapseStore save failed (non-fatal): %s", e)

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
