"""
LLM Provider Adapters — vendor API translation layer.

Each adapter normalizes a vendor-specific LLM API to the standard
LLMProvider interface (invoke/invoke_stream). This is pure translation,
no routing or failover logic (that's ProviderChamber's job).

Gita mapping: Karmendriyas (action organs) — each adapter is a
different hand that can grasp the same tool differently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator

from steward.provider.chamber import _normalize_usage
from steward.types import LLMProvider, LLMUsage

logger = logging.getLogger("STEWARD.PROVIDER")


# ── Streaming Types ──────────────────────────────────────────────────


@dataclass
class _StreamDelta:
    """A streaming chunk from invoke_stream."""

    type: str  # "text_delta" | "done"
    text: str = ""
    response: object = None  # Final _StreamedResponse (on type="done")


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

    def build(self) -> object:
        return _BuiltToolCall(id=self.id, name=self.name, arguments=self.arguments)


@dataclass
class _BuiltToolCall:
    """Assembled tool call from streaming deltas."""

    id: str
    name: str
    arguments: str

    @property
    def function(self) -> object:
        return self


@dataclass
class _StreamedResponse:
    """Final response assembled from streaming chunks."""

    text: str
    tool_calls: list | None = None
    _raw_usage: object = None

    @property
    def content(self) -> str:
        return self.text

    @property
    def usage(self) -> LLMUsage:
        return _normalize_usage(self._raw_usage)


@dataclass
class _AdapterResponse:
    """Duck-type LLMResponse from OpenAI response."""

    _raw: object

    @property
    def content(self) -> str:
        return self._raw.choices[0].message.content or ""  # type: ignore[attr-defined]

    @property
    def tool_calls(self) -> list | None:
        choice = self._raw.choices[0].message  # type: ignore[attr-defined]
        return getattr(choice, "tool_calls", None)

    @property
    def usage(self) -> LLMUsage:
        return _normalize_usage(getattr(self._raw, "usage", None))


# ── Google Adapter ───────────────────────────────────────────────────


class GoogleAdapter:
    """Normalizes messages -> prompt for GoogleProvider."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def invoke(self, **kwargs: object) -> object:
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
        return self._provider.invoke(**kwargs)


# ── Mistral Adapter (OpenAI-compatible) ──────────────────────────────


class MistralAdapter:
    """OpenAI client -> LLMProvider.invoke() interface for Mistral."""

    def __init__(self, client: object) -> None:
        self._client = client

    def invoke(self, **kwargs: object) -> object:
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
        return _AdapterResponse(response)

    def invoke_stream(self, **kwargs: object) -> Iterator[object]:
        """Stream LLM response, yielding _StreamDelta chunks."""
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
        tool_calls: list[object] = []
        usage = None

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None  # type: ignore[attr-defined]
            if delta and getattr(delta, "content", None):
                full_text += delta.content
                yield _StreamDelta(type="text_delta", text=delta.content)
            if delta and getattr(delta, "tool_calls", None):
                for tc_delta in delta.tool_calls:
                    idx = getattr(tc_delta, "index", 0)
                    while len(tool_calls) <= idx:
                        tool_calls.append(_ToolCallAccumulator())
                    tool_calls[idx].accumulate(tc_delta)  # type: ignore[attr-defined]
            if hasattr(chunk, "usage") and chunk.usage is not None:  # type: ignore[attr-defined]
                usage = chunk.usage  # type: ignore[attr-defined]

        yield _StreamDelta(
            type="done",
            response=_StreamedResponse(
                text=full_text,
                tool_calls=[tc.build() for tc in tool_calls] if tool_calls else None,  # type: ignore[attr-defined]
                _raw_usage=usage,
            ),
        )


# ── Anthropic Adapter ────────────────────────────────────────────────


class AnthropicAdapter:
    """Converts steward format to Anthropic Messages API format."""

    def __init__(self, client: object) -> None:
        self._client = client

    def invoke(self, **kwargs: object) -> object:
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
                    tool_calls = msg.get("tool_calls")
                    if isinstance(tool_calls, list):
                        for tc in tool_calls:
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

        return self._client.messages.create(**create_kwargs)  # type: ignore[attr-defined]
