"""
LLM Provider Adapters — vendor API translation layer.

Each adapter normalizes a vendor-specific LLM API to NormalizedResponse
at the boundary. This is pure translation, no routing or failover logic
(that's ProviderChamber's job).

Gita mapping: Karmendriyas (action organs) — each adapter is a
different hand that can grasp the same tool differently.
"""

from __future__ import annotations

import json
import logging
from typing import Iterator

from steward.provider.chamber import _normalize_usage
from steward.types import LLMUsage, NormalizedResponse, StreamDelta, ToolUse

logger = logging.getLogger("STEWARD.PROVIDER")


# ── Streaming Tool Call Accumulator ─────────────────────────────────


class _ToolCallAccumulator:
    """Accumulates tool call deltas from OpenAI streaming."""

    def __init__(self) -> None:
        self.id = ""
        self.name = ""
        self.arguments = ""

    def accumulate(self, delta: object) -> None:
        if hasattr(delta, "id") and delta.id:
            self.id = delta.id
        func = getattr(delta, "function", None)
        if func:
            if getattr(func, "name", None):
                self.name += func.name
            if getattr(func, "arguments", None):
                self.arguments += func.arguments

    def build(self) -> ToolUse:
        """Build a ToolUse from accumulated deltas."""
        params: dict = {}
        if self.arguments:
            try:
                params = json.loads(self.arguments)
            except (json.JSONDecodeError, TypeError):
                params = {"raw": self.arguments}
        return ToolUse(id=self.id, name=self.name, parameters=params if isinstance(params, dict) else {})


# ── Google Adapter ───────────────────────────────────────────────────


class GoogleAdapter:
    """Normalizes messages -> prompt for GoogleProvider.

    Returns NormalizedResponse at the boundary.
    """

    def __init__(self, provider: object) -> None:
        self._provider = provider

    def invoke(self, **kwargs: object) -> NormalizedResponse:
        messages = kwargs.pop("messages", None)  # type: ignore[arg-type]
        if messages and isinstance(messages, list):
            parts: list[str] = []
            for msg in messages:
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                    if content:
                        parts.append(str(content))
            prompt = "\n\n".join(parts)
            rf = kwargs.get("response_format")
            if isinstance(rf, dict) and rf.get("type") == "json_object":
                prompt += "\n\nIMPORTANT: Respond with valid JSON only. No markdown."
            kwargs["prompt"] = prompt
            kwargs["messages"] = messages
        elif "prompt" not in kwargs:
            kwargs["prompt"] = ""
        raw = self._provider.invoke(**kwargs)  # type: ignore[attr-defined]
        # Google response: .content (str), .usage (.input_tokens, .output_tokens)
        raw_usage = getattr(raw, "usage", None)
        return NormalizedResponse(
            content=getattr(raw, "content", "") or "",
            tool_calls=[],
            usage=_normalize_usage(raw_usage),
        )


# ── Mistral Adapter (OpenAI-compatible) ──────────────────────────────


class MistralAdapter:
    """OpenAI client -> NormalizedResponse for Mistral/Groq."""

    def __init__(self, client: object) -> None:
        self._client = client

    def invoke(self, **kwargs: object) -> NormalizedResponse:
        messages = kwargs.get("messages")
        model = str(kwargs.get("model", "mistral-small-latest"))
        max_tokens = int(kwargs.get("max_tokens", 512))  # type: ignore[arg-type]
        temperature = float(kwargs.get("temperature", 0.3))  # type: ignore[arg-type]
        response_format = kwargs.get("response_format")
        timeout = kwargs.get("timeout")

        if messages is None:
            prompt = str(kwargs.get("prompt", ""))
            messages = [{"role": "user", "content": prompt}]

        create_kwargs: dict[str, object] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format:
            create_kwargs["response_format"] = response_format
        if timeout:
            create_kwargs["timeout"] = timeout

        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = tools
            create_kwargs["tool_choice"] = "auto"

        response = self._client.chat.completions.create(**create_kwargs)  # type: ignore[attr-defined]
        return self._normalize(response)

    def invoke_stream(self, **kwargs: object) -> Iterator[StreamDelta]:
        """Stream LLM response, yielding StreamDelta chunks."""
        messages = kwargs.get("messages")
        model = str(kwargs.get("model", "mistral-small-latest"))
        max_tokens = int(kwargs.get("max_tokens", 512))  # type: ignore[arg-type]
        temperature = float(kwargs.get("temperature", 0.3))  # type: ignore[arg-type]
        timeout = kwargs.get("timeout")

        if messages is None:
            prompt = str(kwargs.get("prompt", ""))
            messages = [{"role": "user", "content": prompt}]

        create_kwargs: dict[str, object] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if timeout:
            create_kwargs["timeout"] = timeout

        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = tools
            create_kwargs["tool_choice"] = "auto"

        stream = self._client.chat.completions.create(**create_kwargs)  # type: ignore[attr-defined]

        full_text = ""
        accumulators: list[_ToolCallAccumulator] = []
        usage = None

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None  # type: ignore[attr-defined]
            if delta and getattr(delta, "content", None):
                full_text += delta.content
                yield StreamDelta(type="text_delta", text=delta.content)
            if delta and getattr(delta, "tool_calls", None):
                for tc_delta in delta.tool_calls:
                    idx = getattr(tc_delta, "index", 0)
                    while len(accumulators) <= idx:
                        accumulators.append(_ToolCallAccumulator())
                    accumulators[idx].accumulate(tc_delta)
            if hasattr(chunk, "usage") and chunk.usage is not None:  # type: ignore[attr-defined]
                usage = chunk.usage  # type: ignore[attr-defined]

        built_tools = [acc.build() for acc in accumulators] if accumulators else []
        yield StreamDelta(
            type="done",
            response=NormalizedResponse(
                content=full_text,
                tool_calls=built_tools,
                usage=_normalize_usage(usage),
            ),
        )

    @staticmethod
    def _normalize(response: object) -> NormalizedResponse:
        """Normalize OpenAI-format response to NormalizedResponse."""
        message = response.choices[0].message  # type: ignore[attr-defined]
        content = message.content or ""  # type: ignore[attr-defined]

        tool_calls: list[ToolUse] = []
        raw_tcs = getattr(message, "tool_calls", None)
        if raw_tcs:
            for tc in raw_tcs:
                func = tc.function if hasattr(tc, "function") else tc
                params = func.arguments if hasattr(func, "arguments") else {}
                if isinstance(params, str):
                    try:
                        params = json.loads(params)
                    except (json.JSONDecodeError, TypeError):
                        params = {"raw": params}
                tool_calls.append(
                    ToolUse(
                        id=tc.id if hasattr(tc, "id") else f"call_{id(tc)}",
                        name=func.name if hasattr(func, "name") else str(func),
                        parameters=params if isinstance(params, dict) else {},
                    )
                )

        return NormalizedResponse(
            content=content,
            tool_calls=tool_calls,
            usage=_normalize_usage(getattr(response, "usage", None)),
        )


# ── Anthropic Adapter ────────────────────────────────────────────────


class AnthropicAdapter:
    """Converts steward format to Anthropic Messages API format.

    Returns NormalizedResponse at the boundary.
    """

    def __init__(self, client: object) -> None:
        self._client = client

    def invoke(self, **kwargs: object) -> NormalizedResponse:
        messages = kwargs.get("messages")
        model = str(kwargs.get("model", "claude-sonnet-4-20250514"))
        max_tokens = int(kwargs.get("max_tokens", 4096))  # type: ignore[arg-type]

        system = ""
        api_messages: list[dict[str, object]] = []

        if isinstance(messages, list):
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role")
                if role == "system":
                    system = str(msg.get("content", ""))
                elif role == "tool":
                    api_messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": str(msg.get("tool_call_id", "")),
                                    "content": str(msg.get("content", "")),
                                }
                            ],
                        }
                    )
                elif role == "assistant" and msg.get("tool_calls"):
                    content_blocks: list[dict[str, object]] = []
                    text = str(msg.get("content", ""))
                    if text:
                        content_blocks.append({"type": "text", "text": text})
                    tool_calls_raw = msg.get("tool_calls")
                    if isinstance(tool_calls_raw, list):
                        for tc in tool_calls_raw:
                            if isinstance(tc, dict):
                                func = tc.get("function", {})
                                if isinstance(func, dict):
                                    content_blocks.append(
                                        {
                                            "type": "tool_use",
                                            "id": tc.get("id", ""),
                                            "name": func.get("name", ""),
                                            "input": func.get("arguments", {}),
                                        }
                                    )
                    api_messages.append({"role": "assistant", "content": content_blocks})
                else:
                    api_messages.append({"role": str(role), "content": msg.get("content", "")})

        anthropic_tools: list[dict[str, object]] | None = None
        tools = kwargs.get("tools")
        if isinstance(tools, list):
            anthropic_tools = []
            for tool in tools:
                if isinstance(tool, dict) and tool.get("type") == "function":
                    func = tool.get("function")
                    if isinstance(func, dict):
                        anthropic_tools.append(
                            {
                                "name": func.get("name", ""),
                                "description": func.get("description", ""),
                                "input_schema": func.get("parameters", {}),
                            }
                        )

        create_kwargs: dict[str, object] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
        }
        if system:
            create_kwargs["system"] = system
        if anthropic_tools:
            create_kwargs["tools"] = anthropic_tools

        raw = self._client.messages.create(**create_kwargs)  # type: ignore[attr-defined]

        # Normalize Anthropic response: content is a list of blocks
        content = ""
        tool_calls: list[ToolUse] = []
        raw_content = getattr(raw, "content", [])
        if isinstance(raw_content, list):
            text_parts: list[str] = []
            for block in raw_content:
                block_type = getattr(block, "type", "")
                if block_type == "text":
                    text_parts.append(getattr(block, "text", ""))
                elif block_type == "tool_use":
                    raw_input = getattr(block, "input", {})
                    tool_calls.append(
                        ToolUse(
                            id=getattr(block, "id", ""),
                            name=getattr(block, "name", ""),
                            parameters=raw_input if isinstance(raw_input, dict) else {},
                        )
                    )
            content = "\n".join(text_parts)
        elif isinstance(raw_content, str):
            content = raw_content

        return NormalizedResponse(
            content=content,
            tool_calls=tool_calls,
            usage=_normalize_usage(getattr(raw, "usage", None)),
        )
