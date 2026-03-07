"""
Agent Loop Engine — The core agentic cycle.

This is the beating heart of Steward. It implements the fundamental
agent loop that all autonomous agents follow:

    User message
       ↓
    Build context (system prompt + conversation + tool descriptions)
       ↓
    LLM call (with tools)
       ↓
    Parse response
       ↓
    If tool_use → execute tool → add result to conversation → loop back ↑
    If text     → yield to caller (done for this turn)

The loop is synchronous by design. Async is complexity tax we don't
need for a single-agent engine.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

from steward.tool_registry import ToolRegistry
from steward.types import Conversation, Message, ToolUse

logger = logging.getLogger("STEWARD.LOOP")

# Maximum tool-use iterations per turn to prevent infinite loops
MAX_TOOL_ROUNDS = 50


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers.

    Any object with an invoke(**kwargs) -> response method works.
    Response must have:
        .content: str           — text response
        .tool_calls: list|None  — tool use requests (optional)
        .usage: object|None     — token usage (optional)
    """

    def invoke(self, **kwargs: Any) -> Any: ...


class AgentLoop:
    """Execute the agentic tool-use loop for a single turn.

    A "turn" starts with a user message and ends when the LLM
    produces a text response (no more tool calls).

    Usage:
        loop = AgentLoop(provider=llm, registry=tools, conversation=conv)
        response = loop.run("Fix the bug in main.py")
    """

    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        conversation: Conversation,
        system_prompt: str = "",
        max_tokens: int = 4096,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._conversation = conversation
        self._max_tokens = max_tokens

        # Ensure system prompt is first message
        if system_prompt and (
            not conversation.messages or conversation.messages[0].role != "system"
        ):
            conversation.messages.insert(0, Message(role="system", content=system_prompt))

    def run(self, user_message: str) -> str:
        """Execute one full agent turn.

        Adds the user message, runs the LLM loop until a text
        response is produced, and returns that text.
        """
        self._conversation.add(Message(role="user", content=user_message))

        for round_num in range(MAX_TOOL_ROUNDS):
            response = self._call_llm()
            if response is None:
                return "[Error: LLM returned no response]"

            tool_calls = self._extract_tool_calls(response)

            if not tool_calls:
                # Pure text response — turn is done
                text = self._extract_text(response)
                self._conversation.add(Message(role="assistant", content=text))
                logger.debug("Turn complete after %d rounds", round_num + 1)
                return text

            # Tool use response — execute tools and loop
            self._conversation.add(
                Message(
                    role="assistant",
                    content=self._extract_text(response),
                    tool_uses=tool_calls,
                )
            )

            for tc in tool_calls:
                result = self._registry.execute(tc.name, tc.parameters, call_id=tc.id)
                # Add tool result to conversation
                output = result.output if result.success else f"[Error] {result.error}"
                self._conversation.add(
                    Message(
                        role="tool",
                        content=str(output) if output else "",
                        tool_use_id=tc.id,
                    )
                )
                logger.debug(
                    "Tool %s: %s (round %d)",
                    tc.name,
                    "ok" if result.success else result.error,
                    round_num + 1,
                )

        return "[Error: Maximum tool rounds exceeded]"

    def _call_llm(self) -> Any:
        """Call the LLM provider with current conversation + tools."""
        try:
            kwargs: dict[str, Any] = {
                "messages": self._conversation.to_dicts(),
                "max_tokens": self._max_tokens,
            }
            # Add tool descriptions if we have tools
            tools = self._registry.to_llm_tools()
            if tools:
                kwargs["tools"] = tools

            return self._provider.invoke(**kwargs)
        except Exception as e:
            logger.error("LLM call failed: %s", e, exc_info=True)
            return None

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Extract text content from LLM response."""
        if hasattr(response, "content"):
            content = response.content
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
    def _extract_tool_calls(response: Any) -> list[ToolUse]:
        """Extract tool calls from LLM response.

        Handles both OpenAI format (response.tool_calls) and
        Anthropic format (content blocks with type=tool_use).
        """
        calls: list[ToolUse] = []

        # OpenAI format: response.choices[0].message.tool_calls
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                func = tc.function if hasattr(tc, "function") else tc
                params = func.arguments if hasattr(func, "arguments") else {}
                if isinstance(params, str):
                    try:
                        params = json.loads(params)
                    except json.JSONDecodeError:
                        params = {"raw": params}
                calls.append(ToolUse(
                    id=tc.id if hasattr(tc, "id") else f"call_{id(tc)}",
                    name=func.name if hasattr(func, "name") else str(func),
                    parameters=params,
                ))
            return calls

        # Anthropic format: content blocks with type="tool_use"
        if hasattr(response, "content") and isinstance(response.content, list):
            for block in response.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    calls.append(ToolUse(
                        id=block.id,
                        name=block.name,
                        parameters=block.input if hasattr(block, "input") else {},
                    ))

        # Stop reason check (Anthropic: stop_reason == "tool_use")
        if not calls and hasattr(response, "stop_reason"):
            if response.stop_reason == "tool_use":
                logger.warning("stop_reason=tool_use but no tool calls found")

        return calls
