"""
State persistence — Phoenix pattern for conversation state.

THE GUARANTEE: Steward assumes it can be killed anytime.
On restart: read state -> continue where stopped.

Atomic write (temp + rename) prevents corrupted state files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from steward.types import Conversation, Message, ToolUse

logger = logging.getLogger("STEWARD.STATE")

STATE_DIR_NAME = ".steward"
STATE_FILE_NAME = "session.json"
_STATE_VERSION = 1


def _state_dir(cwd: str | None = None) -> Path:
    base = Path(cwd) if cwd else Path.cwd()
    return base / STATE_DIR_NAME


def _state_file(cwd: str | None = None) -> Path:
    return _state_dir(cwd) / STATE_FILE_NAME


def save_conversation(conv: Conversation, cwd: str | None = None) -> None:
    """Save conversation to disk (atomic write, Phoenix pattern)."""
    try:
        state_dir = _state_dir(cwd)
        state_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "version": _STATE_VERSION,
            "max_tokens": conv.max_tokens,
            "messages": [_msg_to_dict(m) for m in conv.messages],
        }

        state_file = _state_file(cwd)
        temp = state_file.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2))
        temp.replace(state_file)

    except Exception as e:
        logger.error("Failed to save state: %s", e)


def load_conversation(cwd: str | None = None) -> Conversation | None:
    """Load conversation from disk. Returns None if no valid state."""
    state_file = _state_file(cwd)
    if not state_file.exists():
        return None

    try:
        data = json.loads(state_file.read_text())

        if data.get("version") != _STATE_VERSION:
            return None

        messages = [_dict_to_msg(d) for d in data.get("messages", [])]
        max_tokens = data.get("max_tokens", 100_000)

        return Conversation(messages=messages, max_tokens=max_tokens)

    except Exception:
        return None


def clear_state(cwd: str | None = None) -> None:
    """Clear saved state."""
    state_file = _state_file(cwd)
    try:
        if state_file.exists():
            state_file.unlink()
    except Exception as e:
        logger.error("Failed to clear state: %s", e)


def _msg_to_dict(msg: Message) -> dict[str, object]:
    d: dict[str, object] = {"role": msg.role, "content": msg.content}
    if msg.tool_uses:
        d["tool_uses"] = [
            {"id": tu.id, "name": tu.name, "parameters": tu.parameters}
            for tu in msg.tool_uses
        ]
    if msg.tool_use_id:
        d["tool_use_id"] = msg.tool_use_id
    return d


def _dict_to_msg(d: dict) -> Message:  # type: ignore[type-arg]
    tool_uses: list[ToolUse] = []
    raw_tool_uses = d.get("tool_uses")
    if isinstance(raw_tool_uses, list):
        for tu_dict in raw_tool_uses:
            if isinstance(tu_dict, dict):
                params = tu_dict.get("parameters", {})
                if not isinstance(params, dict):
                    params = {}
                tool_uses.append(ToolUse(
                    id=str(tu_dict.get("id", "")),
                    name=str(tu_dict.get("name", "")),
                    parameters=params,
                ))

    tool_use_id = d.get("tool_use_id")
    return Message(
        role=str(d.get("role", "user")),
        content=str(d.get("content", "")),
        tool_uses=tool_uses,
        tool_use_id=str(tool_use_id) if tool_use_id else None,
    )
