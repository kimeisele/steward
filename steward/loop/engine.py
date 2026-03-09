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
import json
import logging
from typing import AsyncIterator

from steward.antahkarana.gandha import VerdictAction
from steward.buddhi import Buddhi, BuddhiDirective
from steward.context import ERROR_MARKER, SamskaraContext
from steward.services import lean_tool_signatures
from steward.summarizer import Summarizer, should_summarize
from steward.types import AgentEvent, AgentUsage, Conversation, EventType, LLMProvider, Message, MessageRole, ToolUse
from vibe_core.mahamantra.adapters.attention import MahaAttention
from vibe_core.mahamantra.adapters.compression import MahaCompression
from vibe_core.protocols.mahajanas.nrisimha.types.narasimha import NarasimhaProtocol, ThreatLevel
from vibe_core.protocols.memory import MemoryProtocol
from vibe_core.runtime.tool_safety_guard import ToolSafetyGuard
from vibe_core.tools.tool_protocol import ToolCall as ProtoToolCall
from vibe_core.tools.tool_protocol import ToolResult
from vibe_core.tools.tool_registry import ToolRegistry

# Narasimha severity ordinal rank — module-level constant (not recreated per call)
_SEVERITY_RANK = {
    ThreatLevel.GREEN: 0,
    ThreatLevel.YELLOW: 1,
    ThreatLevel.ORANGE: 2,
    ThreatLevel.RED: 3,
    ThreatLevel.APOCALYPSE: 4,
}

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

# Maximum tool-use iterations per turn to prevent infinite loops
MAX_TOOL_ROUNDS = 50

# Maximum characters for tool output in conversation (prevents context blowout)
# Brain-in-a-jar: slashed 6x — every token counts
MAX_TOOL_OUTPUT_CHARS = 8_000

# Maximum characters for user input (hard boundary — never send unbounded text to LLM)
MAX_INPUT_CHARS = 12_000

# Maximum characters for LLM text response stored in conversation
MAX_RESPONSE_CHARS = 16_000

# Maximum characters per tool call parameter value
MAX_PARAM_CHARS = 4_000

# Tool execution timeout (seconds) — prevents hung bash commands
TOOL_TIMEOUT_SECONDS = 120

# LLM retry attempts on transient failure
LLM_MAX_RETRIES = 1

# File operation dispatch — tool name → (op_type, safety_method)
_FILE_OP_MAP: dict[str, str] = {
    "read_file": "read",
    "write_file": "write",
    "edit_file": "write",
}


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
        self._compression = MahaCompression()
        self._json_mode = json_mode

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

        self._conversation.add(Message(role=MessageRole.USER, content=user_message))
        usage = AgentUsage()

        # Context management: once at turn start (not every round)
        self._manage_context()

        for round_num in range(MAX_TOOL_ROUNDS):
            # Buddhi pre-flight: deterministic tool selection + token budget
            context_pct = (
                self._conversation.total_tokens / self._conversation.max_tokens
                if self._conversation.max_tokens
                else 0.0
            )
            directive = self._buddhi.pre_flight(user_message, round_num, context_pct)
            if round_num == 0:
                usage.buddhi_action = directive.action.value
                usage.buddhi_guna = directive.guna.value
                usage.buddhi_tier = directive.tier.value
            usage.buddhi_phase = directive.phase

            # Try streaming if provider supports it
            streamed_text_deltas: list[str] = []
            response = await self._call_llm_streaming(directive, streamed_text_deltas)
            usage.llm_calls += 1
            if response is None:
                yield AgentEvent(type=EventType.ERROR, content="LLM returned no response")
                return

            # Track tokens from LLM response
            self._accumulate_usage(response, usage)

            tool_calls = self._extract_tool_calls(response)

            if not tool_calls:
                # Pure text response — turn is done
                text = self._extract_text(response)
                if len(text) > MAX_RESPONSE_CHARS:
                    text = text[:MAX_RESPONSE_CHARS] + f"\n[truncated at {MAX_RESPONSE_CHARS} chars]"
                self._conversation.add(Message(role=MessageRole.ASSISTANT, content=text))
                usage.rounds = round_num + 1

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
                    content=self._extract_text(response),
                    tool_uses=tool_calls,
                )
            )

            # Phase 1: O(1) route + safety check (fast, sequential)
            to_execute: list[tuple[ToolUse, ProtoToolCall]] = []
            blocked: list[tuple[ToolUse, str]] = []  # (tool_call, error_msg)
            for tc in tool_calls:
                usage.tool_calls += 1
                yield AgentEvent(type=EventType.TOOL_CALL, tool_use=tc)

                block_reason = self._check_tool_gates(tc)
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
                waves = self._partition_by_dependency(to_execute)
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
                            result = self._coerce_result(raw)
                            self._record_tool_file_ops(tc, result)

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

    def _check_tool_gates(self, tc: ToolUse) -> str | None:
        """Check all pre-execution gates for a tool call.

        Returns error message if blocked, None if cleared.
        Gates (in order): O(1) Lotus route → Narasimha → Iron Dome.
        """
        # Gate 1: O(1) Lotus route — verify tool exists
        if self._attention:
            route = self._attention.attend(tc.name)
            if not route.found:
                return f"Tool '{tc.name}' not found (O(1) route miss)"

        # Gate 2: Narasimha killswitch — audit bash for dangerous patterns
        if self._narasimha and tc.name == "bash":
            cmd = str(tc.parameters.get("command", ""))
            threat = self._narasimha.audit_agent(
                "steward",
                cmd,
                {"tool": tc.name},
            )
            if threat and _SEVERITY_RANK.get(threat.severity, 0) >= _SEVERITY_RANK[ThreatLevel.RED]:
                logger.warning("Narasimha blocked bash: %s", threat.description)
                return f"Narasimha blocked: {threat.description}"

        # Gate 3: Iron Dome safety check
        if self._safety_guard:
            allowed, violation = self._safety_guard.check_action(
                tc.name,
                tc.parameters,
            )
            if not allowed:
                return violation.message if violation else "Blocked by safety guard"

        return None  # All gates passed

    @staticmethod
    def _accumulate_usage(response: object, usage: AgentUsage) -> None:
        """Extract token counts from LLM response and add to usage.

        Adapters normalize usage to LLMUsage at the boundary,
        so we just read .input_tokens and .output_tokens directly.
        """
        if not hasattr(response, "usage") or response.usage is None:  # type: ignore[attr-defined]
            return
        resp_usage = response.usage  # type: ignore[attr-defined]
        usage.input_tokens += getattr(resp_usage, "input_tokens", 0) or 0
        usage.output_tokens += getattr(resp_usage, "output_tokens", 0) or 0

    def _record_file_op(self, path: str, op: str) -> None:
        """Record file operation in Memory for cross-turn awareness."""
        if not self._memory or not path:
            return
        # Track files touched this session
        key = f"files_{op}"
        existing = self._memory.recall(key, session_id="steward") or []
        if path not in existing:
            existing.append(path)
            self._memory.remember(key, existing, session_id="steward", tags=["file_ops"])

    @staticmethod
    def _coerce_result(raw: object) -> ToolResult:
        """Convert raw asyncio.gather result to ToolResult."""
        if isinstance(raw, asyncio.TimeoutError):
            return ToolResult(success=False, error=f"Tool timed out after {TOOL_TIMEOUT_SECONDS}s")
        if isinstance(raw, BaseException):
            return ToolResult(success=False, error=str(raw))
        return raw  # type: ignore[return-value]

    def _record_tool_file_ops(self, tc: ToolUse, result: ToolResult) -> None:
        """Record file read/write for Iron Dome + Memory (branchless dispatch)."""
        file_op = _FILE_OP_MAP.get(tc.name) if result.success else None
        if not file_op:
            return
        path = str(tc.parameters.get("path", ""))
        if self._safety_guard:
            getattr(self._safety_guard, f"record_file_{file_op}")(path)
        if self._memory:
            self._record_file_op(path, file_op)

    @staticmethod
    def _partition_by_dependency(to_execute: list[tuple[ToolUse, object]]) -> list[list[int]]:
        """Partition tool indices into dependency-ordered waves.

        Protocol lesson (ActionStep.depends_on in steward-protocol):
        If tool A writes a file that tool B reads/tests, B must wait
        for A to complete. Tools within a wave run in parallel.
        Waves run sequentially.

        Returns list of waves, each wave is a list of indices into to_execute.
        """
        if len(to_execute) <= 1:
            return [list(range(len(to_execute)))]

        # Collect paths being written
        written_paths: set[str] = set()
        writer_indices: set[int] = set()
        for i, (tc, _) in enumerate(to_execute):
            if tc.name in ("write_file", "edit_file"):
                path = tc.parameters.get("path", "")
                if path:
                    written_paths.add(path)
                    writer_indices.add(i)

        if not written_paths:
            return [list(range(len(to_execute)))]  # No writes — all parallel

        # Find non-writers that reference any written path
        dependent_indices: set[int] = set()
        for i, (tc, _) in enumerate(to_execute):
            if i in writer_indices:
                continue
            for v in tc.parameters.values():
                if isinstance(v, str) and any(wp in v for wp in written_paths):
                    dependent_indices.add(i)
                    break

        if not dependent_indices:
            return [list(range(len(to_execute)))]  # No dependencies — all parallel

        # Wave 1: writers + independent, Wave 2: dependents
        wave1 = [i for i in range(len(to_execute)) if i not in dependent_indices]
        wave2 = sorted(dependent_indices)
        return [wave1, wave2]

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

    async def _call_llm(self, directive: BuddhiDirective | None = None) -> object | None:
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
    ) -> object | None:
        """Call LLM with streaming, falling back to non-streaming.

        Collects text_delta chunks into text_deltas list for the caller
        to yield as AgentEvents. Returns the final complete response.
        """
        if not hasattr(self._provider, "invoke_stream"):
            return await self._call_llm(directive)

        kwargs = self._build_llm_kwargs(directive)

        try:

            def _stream() -> object | None:
                response = None
                for delta in self._provider.invoke_stream(**kwargs):  # type: ignore[attr-defined]
                    if hasattr(delta, "type"):
                        if delta.type == "text_delta" and text_deltas is not None:  # type: ignore[attr-defined]
                            text_deltas.append(delta.text)  # type: ignore[attr-defined]
                        elif delta.type == "done":  # type: ignore[attr-defined]
                            response = getattr(delta, "response", None)
                return response

            return await asyncio.to_thread(_stream)

        except Exception as e:
            logger.warning("Stream failed (%s: %s) — falling back", type(e).__name__, e)
            return await self._call_llm(directive)

    @staticmethod
    def _extract_raw_content(response: object) -> str:
        """Extract raw text content from any LLM response format."""
        if hasattr(response, "content"):
            content = response.content  # type: ignore[attr-defined]
            if isinstance(content, str):
                return content
            # Anthropic-style: content is a list of blocks
            if isinstance(content, list):
                texts = [
                    b.text if hasattr(b, "text") else str(b)
                    for b in content
                    if hasattr(b, "text") or (isinstance(b, dict) and b.get("type") == "text")
                ]
                return "\n".join(texts)
        return ""

    @staticmethod
    def _strip_fences(text: str) -> str:
        """Strip markdown code fences (Google Gemini wraps JSON in ```json...```)."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            first_nl = cleaned.find("\n")
            if first_nl != -1:
                cleaned = cleaned[first_nl + 1:]
            if cleaned.rstrip().endswith("```"):
                cleaned = cleaned.rstrip()[:-3].rstrip()
        return cleaned

    @staticmethod
    def _parse_json_response(content: str) -> tuple[list[ToolUse], str]:
        """Parse brain-in-a-jar JSON response into (tool_calls, response_text).

        Formats:
          {"tool": "name", "params": {...}}         → single tool call
          {"tools": [{"name": "n", "params": {...}}, ...]} → parallel calls
          {"response": "text"}                      → final answer

        Returns ([], content) if not valid JSON — fallback to plain text.
        """
        if not content or not content.strip():
            return [], ""

        cleaned = AgentLoop._strip_fences(content)

        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            return [], content  # Not JSON — treat as plain text

        if not isinstance(data, dict):
            return [], content

        calls: list[ToolUse] = []

        # Single tool call
        if "tool" in data:
            params = data.get("params", data.get("parameters", {}))
            if isinstance(params, dict):
                params = AgentLoop._clamp_params(params)
            calls.append(ToolUse(
                id="json_0",
                name=str(data["tool"]),
                parameters=params if isinstance(params, dict) else {},
            ))
            return calls, ""

        # Multiple tool calls (parallel)
        if "tools" in data and isinstance(data["tools"], list):
            for i, tc in enumerate(data["tools"]):
                if isinstance(tc, dict) and ("name" in tc or "tool" in tc):
                    name = str(tc.get("name", tc.get("tool", "")))
                    params = tc.get("params", tc.get("parameters", {}))
                    if isinstance(params, dict):
                        params = AgentLoop._clamp_params(params)
                    calls.append(ToolUse(
                        id=f"json_{i}",
                        name=name,
                        parameters=params if isinstance(params, dict) else {},
                    ))
            if calls:
                return calls, ""

        # Text response
        if "response" in data:
            return [], str(data["response"])

        # Unknown JSON — treat as text
        return [], content

    @staticmethod
    def _extract_text(response: object) -> str:
        """Extract text content from LLM response.

        Brain-in-a-jar: extracts "response" value from JSON.
        Fallback: raw text content.
        """
        raw = AgentLoop._extract_raw_content(response)
        if raw:
            _, response_text = AgentLoop._parse_json_response(raw)
            if response_text:
                return response_text
        return raw

    @staticmethod
    def _clamp_params(params: dict) -> dict:
        """Clamp tool parameter values to prevent context blowout.

        Agent-city lesson: every field has an explicit size cap.
        """
        clamped: dict = {}
        for k, v in params.items():
            if isinstance(v, str) and len(v) > MAX_PARAM_CHARS:
                clamped[k] = v[:MAX_PARAM_CHARS] + f"[truncated at {MAX_PARAM_CHARS}]"
            else:
                clamped[k] = v
        return clamped

    @staticmethod
    def _extract_tool_calls(response: object) -> list[ToolUse]:
        """Extract tool calls from LLM response.

        Priority order:
        1. Standard tool_calls (OpenAI/Anthropic format) — backward compat
        2. Brain-in-a-jar JSON mode — parses content as JSON

        Clamps all parameter values to MAX_PARAM_CHARS.
        """
        calls: list[ToolUse] = []

        # 1. OpenAI format: response.tool_calls
        if hasattr(response, "tool_calls") and response.tool_calls:  # type: ignore[attr-defined]
            for tc in response.tool_calls:  # type: ignore[attr-defined]
                func = tc.function if hasattr(tc, "function") else tc
                params = func.arguments if hasattr(func, "arguments") else {}
                if isinstance(params, str):
                    try:
                        params = json.loads(params)
                    except json.JSONDecodeError:
                        params = {"raw": params}
                if isinstance(params, dict):
                    params = AgentLoop._clamp_params(params)
                calls.append(
                    ToolUse(
                        id=tc.id if hasattr(tc, "id") else f"call_{id(tc)}",
                        name=func.name if hasattr(func, "name") else str(func),
                        parameters=params,
                    )
                )
            return calls

        # 2. Anthropic format: content blocks with type="tool_use"
        if hasattr(response, "content") and isinstance(response.content, list):  # type: ignore[attr-defined]
            for block in response.content:  # type: ignore[attr-defined]
                if hasattr(block, "type") and block.type == "tool_use":
                    raw_params = block.input if hasattr(block, "input") else {}
                    calls.append(
                        ToolUse(
                            id=block.id,
                            name=block.name,
                            parameters=AgentLoop._clamp_params(raw_params)
                            if isinstance(raw_params, dict)
                            else raw_params,
                        )
                    )
            if calls:
                return calls

        # 3. Brain-in-a-jar: JSON mode — parse content as JSON
        raw = AgentLoop._extract_raw_content(response)
        if raw:
            json_calls, _ = AgentLoop._parse_json_response(raw)
            if json_calls:
                return json_calls

        return calls
