"""
Brain-in-a-jar JSON Parser — parses LLM JSON responses into tool calls.

Extracted from engine.py. All functions are pure (no state).

JSON protocol:
  {"tool": "name", "params": {...}}         → single tool call
  {"tools": [{"name": "n", "params": {...}}, ...]} → parallel calls
  {"response": "text"}                      → final answer
"""

from __future__ import annotations

import json
import logging

from steward.types import NormalizedResponse, ToolUse

logger = logging.getLogger("STEWARD.LOOP.JSON")

# Tool call parameter value (edit_file old_string/new_string)
MAX_PARAM_CHARS = 2_000  # 500 tokens


def strip_fences(text: str) -> str:
    """Strip markdown code fences (Google Gemini wraps JSON in ```json...```)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        if first_nl != -1:
            cleaned = cleaned[first_nl + 1 :]
        else:
            # No newline — ```json{...}``` on one line
            cleaned = cleaned[3:]
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3].rstrip()
    return cleaned


def extract_json_object(text: str) -> str | None:
    """Extract first complete JSON object {...} from text via brace-matching.

    Handles preamble text, malformed fences, or LLM chatter around JSON.
    String-aware: ignores braces inside JSON string values.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def clamp_params(params: dict) -> dict:
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


def parse_json_response(content: str) -> tuple[list[ToolUse], str]:
    """Parse brain-in-a-jar JSON response into (tool_calls, response_text).

    Formats:
      {"tool": "name", "params": {...}}         → single tool call
      {"tools": [{"name": "n", "params": {...}}, ...]} → parallel calls
      {"response": "text"}                      → final answer

    Returns ([], content) if not valid JSON — fallback to plain text.
    """
    if not content or not content.strip():
        return [], ""

    cleaned = strip_fences(content)

    data = None
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        # Fallback: extract JSON object from mixed content (preamble, malformed fences)
        extracted = extract_json_object(cleaned)
        if extracted:
            try:
                data = json.loads(extracted)
                logger.info("JSON recovered from mixed content (extraction fallback)")
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug("JSON extraction fallback also failed: %s", e)

    if data is None:
        # Log when content LOOKS like JSON but failed to parse — tool calls may be lost
        if cleaned.lstrip()[:1] in ("{", "["):
            logger.warning("JSON-like content unparseable — tool calls may be lost: %.200s", cleaned[:200])
        return [], content

    if not isinstance(data, dict):
        return [], content

    calls: list[ToolUse] = []

    # Single tool call
    if "tool" in data:
        params = data.get("params", data.get("parameters", {}))
        if isinstance(params, dict):
            params = clamp_params(params)
        calls.append(
            ToolUse(
                id="json_0",
                name=str(data["tool"]),
                parameters=params if isinstance(params, dict) else {},
            )
        )
        return calls, ""

    # Multiple tool calls (parallel)
    if "tools" in data and isinstance(data["tools"], list):
        for i, tc in enumerate(data["tools"]):
            if isinstance(tc, dict) and ("name" in tc or "tool" in tc):
                name = str(tc.get("name", tc.get("tool", "")))
                params = tc.get("params", tc.get("parameters", {}))
                if isinstance(params, dict):
                    params = clamp_params(params)
                calls.append(
                    ToolUse(
                        id=f"json_{i}",
                        name=name,
                        parameters=params if isinstance(params, dict) else {},
                    )
                )
        if calls:
            return calls, ""

    # Text response
    if "response" in data:
        return [], str(data["response"])

    # Unknown JSON — treat as text
    return [], content


def extract_raw_content(response: NormalizedResponse) -> str:
    """Extract raw text content from NormalizedResponse."""
    return response.content


def extract_text(response: NormalizedResponse) -> str:
    """Extract text content from NormalizedResponse.

    Brain-in-a-jar: extracts "response" value from JSON.
    Fallback: raw text content.
    """
    raw = extract_raw_content(response)
    if raw:
        _, response_text = parse_json_response(raw)
        if response_text:
            return response_text
    return raw


def looks_like_failed_json(response: NormalizedResponse) -> str | None:
    """Detect if the LLM tried to produce JSON but failed.

    Returns a diagnostic message if the response looks like malformed JSON
    that should have been a tool call, or None if it's genuinely plain text.
    """
    if response.tool_calls:
        return None  # Adapter already parsed it — no failure
    raw = response.content
    if not raw or not raw.strip():
        return None
    cleaned = strip_fences(raw).lstrip()
    if not cleaned.startswith("{") and not cleaned.startswith("["):
        return None  # Not JSON-shaped — genuinely plain text

    # It LOOKS like JSON. Does it parse?
    calls, text = parse_json_response(raw)
    if calls or text != raw:
        return None  # Parsed successfully (tool calls or response key)

    # Failed to parse — build diagnostic
    try:
        json.loads(cleaned)
        return None  # Actually valid JSON (unknown structure)
    except (json.JSONDecodeError, TypeError) as e:
        return f'Malformed JSON: {e}. Reply with valid JSON: {{"tool": ..., "params": ...}} or {{"response": "..."}}'


def extract_tool_calls(response: NormalizedResponse) -> list[ToolUse]:
    """Extract tool calls from NormalizedResponse.

    Priority:
    1. Adapter-normalized tool_calls (already ToolUse from adapters)
    2. Brain-in-a-jar JSON mode — parses content as JSON
    """
    if response.tool_calls:
        return response.tool_calls

    # Brain-in-a-jar: JSON mode — parse content as JSON
    if response.content:
        json_calls, _ = parse_json_response(response.content)
        if json_calls:
            return json_calls

    return []
