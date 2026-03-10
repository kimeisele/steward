"""
Agent Loop Engine — The core agentic cycle (async-first).

This is the beating heart of Steward. It implements the fundamental
agent loop that all autonomous agents follow:

    User message
       |
    Build context (system prompt + conversation + tool descriptions)
       |
    LLM call (with tools)
       |
    Parse response
       |
    If tool_use -> O(1) Lotus route -> safety check -> execute -> loop
    If text     -> yield AgentEvent(type=EventType.TEXT) -> done

Tool routing: MahaAttention (Lotus Router) is the PRIMARY dispatcher.
O(1) lookup for any tool name, regardless of registry size.
ToolRegistry.execute() handles governance + execution.

Parallel execution: when the LLM requests multiple tools in one
response, they execute concurrently with dependency awareness —
write→read dependencies are detected and serialized into waves.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from steward.antahkarana.gandha import VerdictAction
from steward.antahkarana.ksetrajna import KsetraJna
from steward.buddhi import Buddhi, BuddhiDirective
from steward.protocols import HealthGate
from steward.cbr import CBR_CEILING, CBR_SYSTEM_OVERHEAD
from steward.context import ERROR_MARKER, SamskaraContext
from steward.loop import json_parser, tool_dispatch
from steward.services import lean_tool_signatures
from steward.summarizer import Summarizer, should_summarize
from steward.types import (
    AgentEvent,
    AgentUsage,
    ChamberProvider,
    Conversation,
    EventType,
    LLMProvider,
    Message,
    MessageRole,
    NormalizedResponse,
    StreamingProvider,
    ToolUse,
)
from vibe_core.di import ServiceRegistry
from vibe_core.mahamantra.adapters.attention import MahaAttention
from vibe_core.mahamantra.adapters.compression import MahaCompression
from vibe_core.mahamantra.substrate.cell_system.antaranga import (
    AntarangaRegistry,
    FLAG_ACTIVE,
    GENESIS_PRANA_U32,
    INTEGRITY_FULL,
)
from vibe_core.mahamantra.substrate.vm.venu_orchestrator import VenuOrchestrator
from vibe_core.playbook.ephemeral_storage import EphemeralStorage
from vibe_core.protocols.mahajanas.nrisimha.types.narasimha import NarasimhaProtocol
from vibe_core.protocols.memory import MemoryProtocol
from vibe_core.runtime.tool_safety_guard import ToolSafetyGuard
from vibe_core.tools.tool_protocol import ToolCall as ProtoToolCall
from vibe_core.tools.tool_protocol import ToolResult
from vibe_core.tools.tool_registry import ToolRegistry

logger = logging.getLogger("STEWARD.LOOP")

# Brain-in-a-jar instruction template — injected into system prompt
# Replaces 1500-token JSON Schema tool descriptions with ~60-token one-liners
_TOOL_JSON_INSTRUCTION = """

## Tools
{tool_sigs}

Reply ONLY with JSON:
  Tool call: {{"tool": "<name>", "params": {{...}}}}
  Parallel:  {{"tools": [{{"name": "<n>", "params": {{...}}}}, ...]}}
  Answer:    {{"response": "<your answer>"}}"""

# ── CBR: Constant Bitrate Token Stream ──────────────────────────────
# Budget comes from the DSP signal processor (steward.cbr).
# CBR_CEILING: maximum possible budget per LLM call.
# CBR_SYSTEM_OVERHEAD: constant cost of system prompt + tool sigs (~100 tokens).
# Buddhi runs the DSP chain → directive.max_tokens = actual budget for this call.

# Maximum tool-use iterations per turn to prevent infinite loops
MAX_TOOL_ROUNDS = 50

# Char limits — CBR-aligned. 1 token ~= 4 chars.
# Tool output: feeds back into context (input to next LLM call)
MAX_TOOL_OUTPUT_CHARS = 4_000  # 1000 tokens — bounded context input

# User input: hard boundary
MAX_INPUT_CHARS = 4_000  # 1000 tokens — same discipline as tool output

# LLM text response stored in conversation (output side)
MAX_RESPONSE_CHARS = 2_000  # 500 tokens — CBR-proportional

# Re-export from extracted modules (backward compat for tests)
MAX_PARAM_CHARS = json_parser.MAX_PARAM_CHARS
TOOL_TIMEOUT_SECONDS = tool_dispatch.TOOL_TIMEOUT_SECONDS  # single source in tool_dispatch

# LLM retry attempts on transient failure
LLM_MAX_RETRIES = 1

class AgentLoop:
    """Execute the agentic tool-use loop for a single turn.

    A "turn" starts with a user message and ends when the LLM
    produces a text response (no more tool calls).

    Tool routing goes through MahaAttention (Lotus Router) for O(1) lookup.
    Multiple tool calls in a single LLM response execute in parallel.

    Usage:
        loop = AgentLoop(provider=llm, registry=tools, conversation=conv)
        async for event in loop.run("Fix the bug in main.py"):
            if event.type == "text":
                print(event.content)
    """

    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        conversation: Conversation,
        system_prompt: str = "",
        max_tokens: int = 4096,
        safety_guard: ToolSafetyGuard | None = None,
        attention: MahaAttention | None = None,
        memory: MemoryProtocol | None = None,
        buddhi: Buddhi | None = None,
        narasimha: NarasimhaProtocol | None = None,
        json_mode: bool = True,
        venu: VenuOrchestrator | None = None,
        cache: EphemeralStorage | None = None,
        antaranga: AntarangaRegistry | None = None,
        ksetrajna: KsetraJna | None = None,
        health_gate: HealthGate | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._conversation = conversation
        self._max_tokens = max_tokens
        self._safety_guard = safety_guard
        self._attention = attention
        self._memory = memory
        self._narasimha = narasimha
        self._samskara = SamskaraContext()
        self._buddhi = buddhi or Buddhi()  # Use injected or create fresh
        # Use SVC_COMPRESSION from registry if available (singleton), else create fresh
        from steward.services import SVC_COMPRESSION
        self._compression = ServiceRegistry.get(SVC_COMPRESSION) or MahaCompression()
        self._json_mode = json_mode
        self._venu = venu
        self._cache = cache
        self._antaranga = antaranga
        self._antaranga_touched: set[int] = set()  # slots collided this round
        self._ksetrajna = ksetrajna
        self._health_gate = health_gate

        # Ensure system prompt is first message
        if system_prompt and (not conversation.messages or conversation.messages[0].role != MessageRole.SYSTEM):
            conversation.messages.insert(0, Message(role=MessageRole.SYSTEM, content=system_prompt))

        # Brain-in-a-jar: inject lean tool signatures into system prompt
        # ~60 tokens vs ~1500 for full JSON Schema. Eliminates tools parameter.
        if json_mode and conversation.messages and conversation.messages[0].role == MessageRole.SYSTEM:
            sigs = lean_tool_signatures(registry)
            if sigs:
                tool_section = _TOOL_JSON_INSTRUCTION.format(tool_sigs=sigs)
                sys_msg = conversation.messages[0]
                # Guard against double-injection on multi-run
                if "Reply ONLY with JSON:" not in sys_msg.content:
                    conversation.messages[0] = Message(
                        role=MessageRole.SYSTEM,
                        content=sys_msg.content + tool_section,
                    )

    async def run(self, user_message: str) -> AsyncIterator[AgentEvent]:
        """Execute one full agent turn as an async event stream.

        Adds the user message, runs the LLM loop until a text
        response is produced, yielding events along the way.
        """
        # Hard boundary: truncate unbounded input (agent-city lesson)
        if len(user_message) > MAX_INPUT_CHARS:
            user_message = user_message[:MAX_INPUT_CHARS] + f"\n[truncated at {MAX_INPUT_CHARS} chars]"

        # Entry-point compression: deterministic seed for this request
        cr = self._compression.compress(user_message)
        logger.debug("Input compressed: seed=%d, ratio=%.1f", cr.seed, cr.compression_ratio)

        # Venu: step the orchestrator for this turn's DIW context
        venu_diw = 0
        if self._venu:
            venu_diw = self._venu.step()
            logger.debug("Venu DIW: %d (position=%d)", venu_diw, (venu_diw & 0x3F))

        # SikSasTakam: map Venu position to 7-beat cycle
        # Beat 1 (CLEANSE_HEART_MIRROR) → proactive cache invalidation
        # Beat 3 (SPREAD_MOONLIGHT) → graceful degradation awareness
        if venu_diw and self._cache:
            position = venu_diw & 0x3F  # 6-bit position (0-63)
            beat = (position % 7) + 1  # 1-7 cycle
            if beat == 1:  # CLEANSE_HEART_MIRROR — cache invalidation
                evicted = self._cache.cleanup()
                if evicted:
                    logger.info(
                        "SikSasTakam Beat 1 (CLEANSE_HEART_MIRROR): purged %d stale entries",
                        evicted,
                    )

        # North Star alignment check — is this task aligned with agent purpose?
        from steward.services import SVC_NORTH_STAR
        north_star = ServiceRegistry.get(SVC_NORTH_STAR)
        if north_star and isinstance(north_star, int):
            # XOR distance between input seed and north star seed
            # Low distance = aligned, high distance = divergent
            alignment = 1.0 - min(bin(cr.seed ^ north_star).count("1") / 32.0, 1.0)
            logger.debug("North Star alignment: %.2f (seed=%d, star=%d)", alignment, cr.seed, north_star)
        else:
            alignment = 1.0  # No north star = assume aligned

        # Track beat for observability
        venu_beat = ((venu_diw & 0x3F) % 7) + 1 if venu_diw else 0

        self._conversation.add(Message(role=MessageRole.USER, content=user_message))
        usage = AgentUsage()
        usage.venu_diw = venu_diw
        usage.venu_beat = venu_beat
        usage.input_seed = cr.seed
        usage.cbr_budget = CBR_CEILING  # max possible; Buddhi DSP refines per-call

        # Cache check: only replay when Hebbian confidence is HIGH (> 0.7).
        # This means the seed has been seen 5+ times successfully.
        # First-success caching is toxic for agents — context differs each time.
        cache_conf = self._buddhi.seed_confidence(cr.seed)
        if self._cache and cache_conf > 0.7:
            cached_response = self._cache.get(str(cr.seed))
            if cached_response:
                logger.info("Cache HIT on seed %d (confidence=%.2f) — zero LLM cost", cr.seed, cache_conf)
                usage.cache_hit = True
                usage.rounds = 0
                usage.cbr_consumed = 0
                usage.cbr_reserve = CBR_CEILING  # full budget saved (cache hit)
                # Strip JSON wrapper if present
                _, parsed = json_parser.parse_json_response(cached_response)
                text = parsed if parsed else cached_response
                self._conversation.add(Message(role=MessageRole.ASSISTANT, content=text))
                yield AgentEvent(type=EventType.TEXT, content=text)
                yield AgentEvent(type=EventType.DONE, usage=usage)
                return

        # Context management: once at turn start (not every round)
        self._manage_context()

        for round_num in range(MAX_TOOL_ROUNDS):
            # Cetana health check — abort if heartbeat detected critical anomaly
            if self._health_gate and self._health_gate.health_anomaly:
                detail = self._health_gate.health_anomaly_detail
                self._health_gate.clear_health_anomaly()
                logger.warning("Cetana anomaly detected mid-turn: %s", detail)
                guidance = f"[Cetana: health anomaly] {detail}. Consider finishing quickly or switching to a lighter approach."
                self._conversation.add(Message(role=MessageRole.USER, content=guidance))

            # Buddhi pre-flight: deterministic tool selection + token budget
            context_pct = (
                self._conversation.total_tokens / self._conversation.max_tokens
                if self._conversation.max_tokens
                else 0.0
            )
            directive = self._buddhi.pre_flight(user_message, round_num, context_pct, seed=cr.seed)
            if round_num == 0:
                usage.buddhi_action = directive.action.value
                usage.buddhi_guna = directive.guna.value
                usage.buddhi_tier = directive.tier.value
            usage.buddhi_phase = directive.phase
            usage.cbr_budget = directive.max_tokens  # DSP-computed budget

            # Try streaming if provider supports it
            streamed_text_deltas: list[str] = []
            response = await self._call_llm_streaming(directive, streamed_text_deltas)
            usage.llm_calls += 1
            if response is None:
                # Surface provider-level failure info if available
                diag = "LLM returned no response"
                if isinstance(self._provider, ChamberProvider):
                    stats = self._provider.stats()
                    n_fail = stats.get("total_failures", 0)
                    n_total = stats.get("total_calls", 0)
                    providers = stats.get("providers", [])
                    dead = [p["name"] for p in providers if isinstance(p, dict) and not p.get("alive")]
                    diag = f"All providers failed ({n_fail} failures / {n_total} calls)"
                    if dead:
                        diag += f" — dead: {', '.join(dead)}"
                yield AgentEvent(type=EventType.ERROR, content=diag)
                return

            # Track tokens from LLM response
            self._accumulate_usage(response, usage)

            tool_calls = json_parser.extract_tool_calls(response)

            if not tool_calls:
                # Pure text response — turn is done
                text = json_parser.extract_text(response)
                was_truncated = len(text) > MAX_RESPONSE_CHARS
                if was_truncated:
                    text = text[:MAX_RESPONSE_CHARS] + f"\n[truncated at {MAX_RESPONSE_CHARS} chars]"
                self._conversation.add(Message(role=MessageRole.ASSISTANT, content=text))
                usage.rounds = round_num + 1

                # Quality signals: truncation + CBR overshoot + Antaranga density
                usage.truncated = was_truncated
                if self._antaranga:
                    usage.antaranga_active = self._antaranga.active_count()
                usage.cbr_consumed = usage.total_tokens
                usage.cbr_exceeded = usage.cbr_consumed > usage.cbr_budget
                usage.cbr_reserve = max(0, usage.cbr_budget - usage.cbr_consumed)

                # Hebbian learning: ALWAYS success=True for completed turns.
                # Truncation and CBR overshoot are quality SIGNALS, not failures.
                # Recording truncation as failure causes reward hacking:
                # the agent learns to produce NOOPs instead of useful-but-long output.
                self._buddhi.record_seed(cr.seed, success=True)

                # Cache store: only when Hebbian confidence is HIGH (> 0.7).
                # Requires ~5 successful uses of this seed pattern.
                # First-success caching is dangerous — the response may be mediocre.
                # Venu-modulated TTL: DIW position influences cache freshness.
                # Higher DIW = more execution context passed = shorter TTL (fresher).
                # Base 60s, reduced by Venu position (0-63 range from 6-bit field).
                base_ttl = 60
                if venu_diw:
                    position = venu_diw & 0x3F  # 6-bit position (0-63)
                    ttl_factor = 1.0 - (position / 63.0) * 0.5  # 1.0 to 0.5
                    base_ttl = max(15, int(base_ttl * ttl_factor))
                if self._cache and text:
                    store_conf = self._buddhi.seed_confidence(cr.seed)
                    if store_conf > 0.7:
                        self._cache.set(str(cr.seed), text[:2000], ttl_seconds=base_ttl)
                        logger.debug("Cache STORE: seed %d (confidence=%.2f, ttl=%ds)", cr.seed, store_conf, base_ttl)
                if was_truncated:
                    logger.info("Quality: response truncated at %d chars (seed %d)", MAX_RESPONSE_CHARS, cr.seed)
                if usage.cbr_exceeded:
                    logger.info("Quality: CBR exceeded %d/%d tokens (seed %d)", usage.cbr_consumed, usage.cbr_budget, cr.seed)

                # Brain-in-a-jar: check if streamed deltas are JSON (don't yield raw JSON)
                if streamed_text_deltas:
                    assembled = "".join(streamed_text_deltas)
                    if not assembled.strip().startswith("{"):
                        # Plain text streaming — yield deltas
                        for delta in streamed_text_deltas:
                            yield AgentEvent(type=EventType.TEXT_DELTA, content=delta)
                    else:
                        # JSON mode — emit parsed text as TEXT event
                        yield AgentEvent(type=EventType.TEXT, content=text)
                else:
                    yield AgentEvent(type=EventType.TEXT, content=text)
                yield AgentEvent(type=EventType.DONE, usage=usage)
                logger.debug(
                    "Turn complete after %d rounds (%d tokens)",
                    round_num + 1,
                    usage.total_tokens,
                )
                return

            # Tool use response — add assistant message, then execute tools
            self._conversation.add(
                Message(
                    role=MessageRole.ASSISTANT,
                    content=json_parser.extract_text(response),
                    tool_uses=tool_calls,
                )
            )

            # Phase 1: O(1) route + safety check (fast, sequential)
            to_execute: list[tuple[ToolUse, ProtoToolCall]] = []
            blocked: list[tuple[ToolUse, str]] = []  # (tool_call, error_msg)
            for tc in tool_calls:
                usage.tool_calls += 1
                yield AgentEvent(type=EventType.TOOL_CALL, tool_use=tc)

                block_reason = tool_dispatch.check_tool_gates(tc, self._attention, self._narasimha, self._safety_guard)
                if block_reason:
                    self._conversation.add(
                        Message(role=MessageRole.TOOL, content=f"{ERROR_MARKER} {block_reason}", tool_use_id=tc.id)
                    )
                    yield AgentEvent(
                        type=EventType.TOOL_RESULT,
                        content=ToolResult(success=False, error=block_reason),
                        tool_use=tc,
                    )
                    blocked.append((tc, block_reason))
                    continue

                # Cleared for execution
                proto_call = ProtoToolCall(
                    tool_name=tc.name,
                    parameters=tc.parameters,
                    call_id=tc.id,
                    caller_agent_id="steward",
                )
                to_execute.append((tc, proto_call))

            # Phase 2: Execute tools, respecting write→read dependencies
            # Protocol lesson (ActionStep.depends_on): if tool A writes a file
            # that tool B reads/tests, B must wait for A to complete.
            results: list[object] = []
            if to_execute:
                waves = tool_dispatch.partition_by_dependency(to_execute)
                if len(waves) > 1:
                    logger.info(
                        "Dependency-aware execution: %d waves (%s)",
                        len(waves),
                        " → ".join(str(len(w)) for w in waves),
                    )

                results = [None] * len(to_execute)
                for wave in waves:
                    indexed_futures: dict[asyncio.Future, int] = {}
                    for idx in wave:
                        tc, pc = to_execute[idx]
                        fut = asyncio.ensure_future(
                            asyncio.wait_for(
                                asyncio.to_thread(self._registry.execute, pc),
                                timeout=TOOL_TIMEOUT_SECONDS,
                            )
                        )
                        indexed_futures[fut] = idx

                    # Yield results as each completes within this wave
                    remaining = set(indexed_futures.keys())
                    while remaining:
                        done, remaining = await asyncio.wait(remaining, return_when=asyncio.FIRST_COMPLETED)
                        for fut in done:
                            idx = indexed_futures[fut]
                            tc, _ = to_execute[idx]
                            try:
                                raw = fut.result()
                            except BaseException as e:
                                raw = e
                            results[idx] = raw
                            result = tool_dispatch.coerce_result(raw)
                            tool_dispatch.record_tool_file_ops(tc, result, self._safety_guard, self._memory)

                            # Antaranga collision: tool execution → standing wave
                            if self._antaranga:
                                tool_seed = self._compression.compress(tc.name).seed
                                slot = tool_seed % 512
                                prana = GENESIS_PRANA_U32 if result.success else GENESIS_PRANA_U32 // 4
                                integrity = INTEGRITY_FULL if result.success else INTEGRITY_FULL // 2
                                self._antaranga.collide(
                                    slot=slot,
                                    v_source=cr.seed & 0xFFFFFFFF,
                                    v_target=tool_seed & 0xFFFFFFFF,
                                    v_operation=round_num & 0xFFFFFFFF,
                                    v_arcanam=usage.tool_calls & 0xFFFFFFFF,
                                    v_atma=venu_diw & 0xFFFFFFFF,
                                    v_prana=prana,
                                    v_integrity=integrity,
                                    v_cycle=round_num & 0xFFFF,
                                )
                                self._antaranga_touched.add(slot)

                            output = result.output if result.success else f"{ERROR_MARKER} {result.error}"
                            output_str = str(output) if output else ""
                            # Prefix with tool name (JSON mode context — LLM needs to know which tool produced this)
                            output_str = f"[{tc.name}] {output_str}"
                            if len(output_str) > MAX_TOOL_OUTPUT_CHARS:
                                output_str = (
                                    output_str[:MAX_TOOL_OUTPUT_CHARS]
                                    + f"\n\n[truncated — {len(output_str)} chars total, "
                                    f"showing first {MAX_TOOL_OUTPUT_CHARS}]"
                                )
                                usage.truncated = True
                            # Store structured error info in message metadata
                            meta = {}
                            if not result.success:
                                meta = {"success": False, "error": result.error}
                            self._conversation.add(
                                Message(
                                    role=MessageRole.TOOL,
                                    content=output_str,
                                    tool_use_id=tc.id,
                                    metadata=meta,
                                )
                            )
                            yield AgentEvent(type=EventType.TOOL_RESULT, content=result, tool_use=tc)
                            logger.debug(
                                "Tool %s: %s (round %d)",
                                tc.name,
                                "ok" if result.success else result.error,
                                round_num + 1,
                            )

            # Phase 4: Buddhi evaluation — ALL tool outcomes (blocked + executed)
            buddhi_event = self._apply_buddhi_verdict(
                blocked,
                to_execute,
                results if to_execute else [],
                usage,
                round_num,
            )
            if buddhi_event:
                if buddhi_event.type == EventType.ERROR:
                    yield buddhi_event
                    return
                # Reflection/redirect: guidance injected, continue loop

            # Phase 5: KsetraJna mid-turn observation — detect stuck/stagnation
            if self._ksetrajna:
                self._ksetrajna.observe()
                if self._ksetrajna.is_stuck():
                    logger.warning("KsetraJna: agent stuck (drift < threshold over %d observations)", 5)
                    guidance = "[KsetraJna: stagnation detected] The field is not changing. Break the pattern — try a completely different approach or tool."
                    self._conversation.add(Message(role=MessageRole.USER, content=guidance))
                    usage.buddhi_reflections += 1

            # Phase 6: Antaranga DIW modulation — Venu rhythm shapes standing wave
            # Only modulate slots that were touched this round (avoid 512-scan)
            if self._antaranga and venu_diw and self._antaranga_touched:
                for slot_idx in self._antaranga_touched:
                    self._antaranga.apply_diw(slot_idx, venu_diw)
                self._antaranga_touched.clear()

        usage.rounds = MAX_TOOL_ROUNDS
        yield AgentEvent(type=EventType.ERROR, content="Maximum tool rounds exceeded")

    def run_sync(self, user_message: str) -> str:
        """Synchronous wrapper — runs the async loop and returns final text.

        For simple usage and testing. Use run() for streaming events.
        """

        async def _collect() -> str:
            final_text = ""
            async for event in self.run(user_message):
                if event.type == EventType.TEXT:
                    final_text = str(event.content) if event.content else ""
                elif event.type == EventType.ERROR:
                    return f"[Error: {event.content}]"
            return final_text

        return asyncio.run(_collect())

    @staticmethod
    def _accumulate_usage(response: NormalizedResponse, usage: AgentUsage) -> None:
        """Extract token counts from NormalizedResponse and add to usage."""
        if not response.usage:
            return
        inp = response.usage.input_tokens
        out = response.usage.output_tokens
        if inp == 0 and out == 0:
            logger.info("LLM usage reports 0/0 tokens — provider not tracking (CBR blind)")
        usage.input_tokens += inp
        usage.output_tokens += out

    # Backward-compatible delegates — tests reference these as AgentLoop._*
    _partition_by_dependency = staticmethod(tool_dispatch.partition_by_dependency)

    def _apply_buddhi_verdict(
        self,
        blocked: list[tuple[ToolUse, str]],
        to_execute: list[tuple[ToolUse, object]],
        results: list[object],
        usage: AgentUsage,
        round_num: int,
    ) -> AgentEvent | None:
        """Evaluate all tool outcomes via Buddhi. Returns event if action needed."""
        all_calls: list[ToolUse] = [tc for tc, _ in blocked]
        all_outcomes: list[tuple[bool, str]] = [(False, err) for _, err in blocked]

        for (tc, _), raw in zip(to_execute, results):
            all_calls.append(tc)
            if isinstance(raw, BaseException):
                all_outcomes.append((False, str(raw)))
            else:
                all_outcomes.append((raw.success, raw.error or ""))

        if not all_calls:
            return None

        usage.buddhi_errors += sum(1 for ok, _ in all_outcomes if not ok)
        verdict = self._buddhi.evaluate(all_calls, all_outcomes)

        # Wire feedback protocol — every tool outcome is a learning signal
        from steward.services import SVC_FEEDBACK
        feedback = ServiceRegistry.get(SVC_FEEDBACK)
        if feedback:
            ctx = {"round": round_num}
            for tc, (ok, err) in zip(all_calls, all_outcomes):
                if ok:
                    feedback.signal_success(tc.name, ctx)
                else:
                    feedback.signal_failure(tc.name, err or "unknown", ctx)

        if verdict.action == VerdictAction.ABORT:
            usage.rounds = round_num + 1
            usage.buddhi_reflections += 1
            return AgentEvent(
                type=EventType.ERROR,
                content=f"Buddhi abort: {verdict.reason}. {verdict.suggestion}",
            )

        if verdict.action in (VerdictAction.REFLECT, VerdictAction.REDIRECT):
            usage.buddhi_reflections += 1
            label = verdict.action.value  # "reflect" or "redirect"
            guidance = f"[Buddhi {label}: {verdict.reason}] {verdict.suggestion}"
            self._conversation.add(Message(role=MessageRole.USER, content=guidance))
            logger.info("Buddhi injected %s: %s", label, verdict.reason)
            return AgentEvent(type=EventType.TEXT, content="")  # signal: continue loop

        return None

    def _manage_context(self) -> None:
        """Context budget management — runs before every LLM call.

        Three-tier defense (80% infra / 20% LLM):
        1. At 50%: Samskara compaction (deterministic, zero cost)
        2. At 70%: LLM summarization (fallback, costs tokens)
        3. Over 100%: _trim() evicts oldest messages (last resort, in Conversation)
        """
        if self._samskara.should_compact(self._conversation, threshold=0.5):
            pct = int(self._conversation.total_tokens / self._conversation.max_tokens * 100)
            logger.info("Context at %d%% — samskara compaction (free)", pct)
            if self._samskara.compact(self._conversation):
                logger.info(
                    "Samskara compacted — now at %d tokens (%d%%)",
                    self._conversation.total_tokens,
                    int(self._conversation.total_tokens / self._conversation.max_tokens * 100),
                )

        if should_summarize(self._conversation, threshold=0.7):
            pct = int(self._conversation.total_tokens / self._conversation.max_tokens * 100)
            logger.info("Context at %d%% — LLM summarization (fallback)", pct)
            try:
                summarizer = Summarizer(self._provider)
                if summarizer.summarize(self._conversation):
                    logger.info(
                        "Summarized — now at %d tokens (%d%%)",
                        self._conversation.total_tokens,
                        int(self._conversation.total_tokens / self._conversation.max_tokens * 100),
                    )
            except Exception as e:
                logger.warning("Summarization failed: %s — _trim() will handle overflow", e)

    def _build_llm_kwargs(self, directive: BuddhiDirective | None = None) -> dict[str, object]:
        """Build kwargs for LLM call — brain-in-a-jar mode.

        No tools parameter. Tool info is in system prompt as lean signatures.
        JSON mode enforced via response_format.
        Buddhi directive controls token budget and ModelTier routing.
        """
        # CBR: Buddhi sets max_tokens per action/phase.
        # CBR tracks budget vs consumed for quality awareness — not a hard cap on output
        # because tool calls (edit_file content) can legitimately exceed CBR output budget.
        max_tokens = self._max_tokens
        if directive and directive.max_tokens:
            max_tokens = directive.max_tokens

        kwargs: dict[str, object] = {
            "messages": self._conversation.to_dicts(),
            "max_tokens": max_tokens,
        }

        # Brain-in-a-jar: JSON mode (no tools parameter, saves ~1500 tokens/call)
        if self._json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        else:
            # Legacy mode: send full tool schemas (custom prompts, backward compat)
            from steward.services import tool_descriptions_for_llm
            all_tools = tool_descriptions_for_llm(self._registry)
            if all_tools:
                kwargs["tools"] = all_tools

        # ModelTier routing: Buddhi decides which cost tier to use
        if directive:
            kwargs["tier"] = directive.tier.value

        return kwargs

    async def _call_llm(self, directive: BuddhiDirective | None = None) -> NormalizedResponse | None:
        """Call the LLM provider (non-streaming).

        Retries once on transient failure before returning None.
        """
        kwargs = self._build_llm_kwargs(directive)

        for attempt in range(1 + LLM_MAX_RETRIES):
            try:
                return await asyncio.to_thread(self._provider.invoke, **kwargs)
            except Exception as e:
                if attempt < LLM_MAX_RETRIES:
                    logger.warning("LLM call failed (attempt %d): %s — retrying", attempt + 1, e)
                    continue
                logger.warning("LLM call failed (%s: %s) — no retries left", type(e).__name__, e)
                return None

    async def _call_llm_streaming(
        self,
        directive: BuddhiDirective | None = None,
        text_deltas: list[str] | None = None,
    ) -> NormalizedResponse | None:
        """Call LLM with streaming, falling back to non-streaming.

        Collects text_delta chunks into text_deltas list for the caller
        to yield as AgentEvents. Returns the final complete response.
        """
        if not isinstance(self._provider, StreamingProvider):
            return await self._call_llm(directive)

        kwargs = self._build_llm_kwargs(directive)

        try:

            def _stream() -> NormalizedResponse | None:
                response = None
                for delta in self._provider.invoke_stream(**kwargs):
                    if delta.type == "text_delta" and text_deltas is not None:
                        text_deltas.append(delta.text)
                    elif delta.type == "done":
                        response = delta.response
                return response

            return await asyncio.to_thread(_stream)

        except Exception as e:
            logger.warning("Stream failed (%s: %s) — falling back", type(e).__name__, e)
            return await self._call_llm(directive)

    # Backward-compatible delegates — tests reference these as AgentLoop._*
    _parse_json_response = staticmethod(json_parser.parse_json_response)
    _extract_json_object = staticmethod(json_parser.extract_json_object)
    _clamp_params = staticmethod(json_parser.clamp_params)
