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
    If text     -> yield AgentEvent(type="text") -> done

Tool routing: MahaAttention (Lotus Router) is the PRIMARY dispatcher.
O(1) lookup for any tool name, regardless of registry size.
ToolRegistry.execute() handles governance + execution.

Parallel execution: when the LLM requests multiple tools in one
response, they execute concurrently via asyncio.gather().
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from vibe_core.mahamantra.adapters.attention import MahaAttention
from vibe_core.protocols.memory import MemoryProtocol
from vibe_core.runtime.tool_safety_guard import ToolSafetyGuard
from vibe_core.tools.tool_protocol import ToolCall as ProtoToolCall, ToolResult
from vibe_core.tools.tool_registry import ToolRegistry

from steward.buddhi import Buddhi
from steward.context import SamskaraContext
from steward.services import tool_descriptions_for_llm
from steward.summarizer import Summarizer, should_summarize
from steward.types import AgentEvent, AgentUsage, Conversation, LLMProvider, Message, ToolUse

logger = logging.getLogger("STEWARD.LOOP")

# Maximum tool-use iterations per turn to prevent infinite loops
MAX_TOOL_ROUNDS = 50

# Maximum characters for tool output in conversation (prevents context blowout)
MAX_TOOL_OUTPUT_CHARS = 50_000

# Maximum characters for user input (hard boundary — never send unbounded text to LLM)
MAX_INPUT_CHARS = 20_000

# Maximum characters for LLM text response stored in conversation
MAX_RESPONSE_CHARS = 100_000

# Maximum characters per tool call parameter value
MAX_PARAM_CHARS = 10_000


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
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._conversation = conversation
        self._max_tokens = max_tokens
        self._safety_guard = safety_guard
        self._attention = attention
        self._memory = memory
        self._samskara = SamskaraContext()
        self._buddhi = Buddhi()

        # Ensure system prompt is first message
        if system_prompt and (
            not conversation.messages or conversation.messages[0].role != "system"
        ):
            conversation.messages.insert(0, Message(role="system", content=system_prompt))

    async def run(self, user_message: str) -> AsyncIterator[AgentEvent]:
        """Execute one full agent turn as an async event stream.

        Adds the user message, runs the LLM loop until a text
        response is produced, yielding events along the way.
        """
        # Hard boundary: truncate unbounded input (agent-city lesson)
        if len(user_message) > MAX_INPUT_CHARS:
            user_message = user_message[:MAX_INPUT_CHARS] + f"\n[truncated at {MAX_INPUT_CHARS} chars]"
        self._conversation.add(Message(role="user", content=user_message))
        usage = AgentUsage()

        for round_num in range(MAX_TOOL_ROUNDS):
            response = await self._call_llm()
            usage.llm_calls += 1
            if response is None:
                yield AgentEvent(type="error", content="LLM returned no response")
                return

            # Track tokens from LLM response
            self._accumulate_usage(response, usage)

            tool_calls = self._extract_tool_calls(response)

            if not tool_calls:
                # Pure text response — turn is done
                text = self._extract_text(response)
                if len(text) > MAX_RESPONSE_CHARS:
                    text = text[:MAX_RESPONSE_CHARS] + f"\n[truncated at {MAX_RESPONSE_CHARS} chars]"
                self._conversation.add(Message(role="assistant", content=text))
                usage.rounds = round_num + 1
                yield AgentEvent(type="text", content=text)
                yield AgentEvent(type="done", usage=usage)
                logger.debug(
                    "Turn complete after %d rounds (%d tokens)",
                    round_num + 1, usage.total_tokens,
                )
                return

            # Tool use response — add assistant message, then execute tools
            self._conversation.add(
                Message(
                    role="assistant",
                    content=self._extract_text(response),
                    tool_uses=tool_calls,
                )
            )

            # Phase 1: O(1) route + safety check (fast, sequential)
            to_execute: list[tuple[ToolUse, ProtoToolCall]] = []
            for tc in tool_calls:
                usage.tool_calls += 1
                yield AgentEvent(type="tool_call", tool_use=tc)

                # O(1) Lotus route — verify tool exists before execution
                if self._attention:
                    route = self._attention.attend(tc.name)
                    if not route.found:
                        error_msg = f"Tool '{tc.name}' not found (O(1) route miss)"
                        self._conversation.add(
                            Message(role="tool", content=f"[Error] {error_msg}", tool_use_id=tc.id)
                        )
                        yield AgentEvent(
                            type="tool_result",
                            content=ToolResult(success=False, error=error_msg),
                            tool_use=tc,
                        )
                        continue

                # Iron Dome safety check
                if self._safety_guard:
                    allowed, violation = self._safety_guard.check_action(
                        tc.name, tc.parameters
                    )
                    if not allowed:
                        error_msg = violation.message if violation else "Blocked by safety guard"
                        self._conversation.add(
                            Message(role="tool", content=f"[Error] {error_msg}", tool_use_id=tc.id)
                        )
                        yield AgentEvent(
                            type="tool_result",
                            content=ToolResult(success=False, error=error_msg),
                            tool_use=tc,
                        )
                        continue

                # Cleared for execution
                proto_call = ProtoToolCall(
                    tool_name=tc.name,
                    parameters=tc.parameters,
                    call_id=tc.id,
                    caller_agent_id="steward",
                )
                to_execute.append((tc, proto_call))

            # Phase 2: Execute all cleared tools in parallel
            if to_execute:
                tasks = [
                    asyncio.to_thread(self._registry.execute, pc)
                    for _, pc in to_execute
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Phase 3: Process results, record file ops, yield events
                for (tc, _), raw_result in zip(to_execute, results):
                    if isinstance(raw_result, BaseException):
                        result = ToolResult(success=False, error=str(raw_result))
                    else:
                        result = raw_result

                    # Record file operations for Iron Dome + Memory
                    if result.success:
                        if tc.name == "read_file":
                            path = str(tc.parameters.get("path", ""))
                            if self._safety_guard:
                                self._safety_guard.record_file_read(path)
                            if self._memory:
                                self._record_file_op(path, "read")
                        elif tc.name in ("write_file", "edit_file"):
                            path = str(tc.parameters.get("path", ""))
                            if self._safety_guard:
                                self._safety_guard.record_file_write(path)
                            if self._memory:
                                self._record_file_op(path, "write")

                    output = result.output if result.success else f"[Error] {result.error}"
                    output_str = str(output) if output else ""
                    if len(output_str) > MAX_TOOL_OUTPUT_CHARS:
                        output_str = (
                            output_str[:MAX_TOOL_OUTPUT_CHARS]
                            + f"\n\n[truncated — {len(output_str)} chars total, "
                            f"showing first {MAX_TOOL_OUTPUT_CHARS}]"
                        )
                    self._conversation.add(
                        Message(role="tool", content=output_str, tool_use_id=tc.id)
                    )
                    yield AgentEvent(type="tool_result", content=result, tool_use=tc)
                    logger.debug(
                        "Tool %s: %s (round %d)",
                        tc.name,
                        "ok" if result.success else result.error,
                        round_num + 1,
                    )

            # Phase 4: Buddhi evaluation — discriminative intelligence
            if to_execute:
                buddhi_results = [
                    (
                        not isinstance(r, BaseException) and r.success,
                        str(r) if isinstance(r, BaseException) else (r.error or ""),
                    )
                    for r in results
                ]
                verdict = self._buddhi.evaluate(
                    [tc for tc, _ in to_execute],
                    buddhi_results,
                )
                if verdict.action == "abort":
                    usage.rounds = round_num + 1
                    yield AgentEvent(
                        type="error",
                        content=f"Buddhi abort: {verdict.reason}. {verdict.suggestion}",
                    )
                    return
                if verdict.action == "reflect":
                    # Inject reflection prompt — LLM will reconsider approach
                    reflection = (
                        f"[Buddhi reflection: {verdict.reason}] "
                        f"{verdict.suggestion}"
                    )
                    self._conversation.add(
                        Message(role="user", content=reflection)
                    )
                    logger.info("Buddhi injected reflection: %s", verdict.reason)

        usage.rounds = MAX_TOOL_ROUNDS
        yield AgentEvent(type="error", content="Maximum tool rounds exceeded")

    def run_sync(self, user_message: str) -> str:
        """Synchronous wrapper — runs the async loop and returns final text.

        For simple usage and testing. Use run() for streaming events.
        """
        async def _collect() -> str:
            final_text = ""
            async for event in self.run(user_message):
                if event.type == "text":
                    final_text = str(event.content) if event.content else ""
                elif event.type == "error":
                    return f"[Error: {event.content}]"
            return final_text

        return asyncio.run(_collect())

    @staticmethod
    def _accumulate_usage(response: object, usage: AgentUsage) -> None:
        """Extract token counts from LLM response and add to usage."""
        if not hasattr(response, "usage") or response.usage is None:  # type: ignore[attr-defined]
            return
        resp_usage = response.usage  # type: ignore[attr-defined]
        usage.input_tokens += (
            getattr(resp_usage, "input_tokens", 0)
            or getattr(resp_usage, "prompt_tokens", 0)
            or 0
        )
        usage.output_tokens += (
            getattr(resp_usage, "output_tokens", 0)
            or getattr(resp_usage, "completion_tokens", 0)
            or 0
        )

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

    async def _call_llm(self) -> object | None:
        """Call the LLM provider with current conversation + tools.

        Context budget management (80% infra / 20% LLM):
        1. At 50%: Samskara compaction (deterministic, zero tokens)
        2. At 70%: LLM summarization (fallback, costs tokens)
        3. Over 100%: _trim() evicts oldest messages (last resort)
        """
        # Phase 1: Samskara compaction at 50% — FREE, deterministic
        if self._samskara.should_compact(self._conversation, threshold=0.5):
            pct = int(self._conversation.total_tokens / self._conversation.max_tokens * 100)
            logger.info("Context at %d%% — samskara compaction (free)", pct)
            if self._samskara.compact(self._conversation):
                logger.info(
                    "Samskara compacted — now at %d tokens (%d%%)",
                    self._conversation.total_tokens,
                    int(self._conversation.total_tokens / self._conversation.max_tokens * 100),
                )

        # Phase 2: LLM summarization at 70% — fallback, costs tokens
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

        try:
            kwargs: dict[str, object] = {
                "messages": self._conversation.to_dicts(),
                "max_tokens": self._max_tokens,
            }
            # Add tool descriptions if we have tools
            tools = tool_descriptions_for_llm(self._registry)
            if tools:
                kwargs["tools"] = tools

            return await asyncio.to_thread(self._provider.invoke, **kwargs)
        except Exception as e:
            # Agent-city lesson: LLM failure is EXPECTED, not exceptional.
            # Deterministic path continues — caller handles None gracefully.
            logger.warning("LLM call failed (%s: %s) — deterministic path continues", type(e).__name__, e)
            return None

    @staticmethod
    def _extract_text(response: object) -> str:
        """Extract text content from LLM response."""
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

        Handles both OpenAI format (response.tool_calls) and
        Anthropic format (content blocks with type=tool_use).
        Clamps all parameter values to MAX_PARAM_CHARS.
        """
        calls: list[ToolUse] = []

        # OpenAI format: response.choices[0].message.tool_calls
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
                calls.append(ToolUse(
                    id=tc.id if hasattr(tc, "id") else f"call_{id(tc)}",
                    name=func.name if hasattr(func, "name") else str(func),
                    parameters=params,
                ))
            return calls

        # Anthropic format: content blocks with type="tool_use"
        if hasattr(response, "content") and isinstance(response.content, list):  # type: ignore[attr-defined]
            for block in response.content:  # type: ignore[attr-defined]
                if hasattr(block, "type") and block.type == "tool_use":
                    raw_params = block.input if hasattr(block, "input") else {}
                    calls.append(ToolUse(
                        id=block.id,
                        name=block.name,
                        parameters=AgentLoop._clamp_params(raw_params) if isinstance(raw_params, dict) else raw_params,
                    ))

        # Stop reason check (Anthropic: stop_reason == "tool_use")
        if not calls and hasattr(response, "stop_reason"):
            if response.stop_reason == "tool_use":  # type: ignore[attr-defined]
                logger.warning("stop_reason=tool_use but no tool calls found")

        return calls
