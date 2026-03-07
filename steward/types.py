"""
Core types for the Steward agent engine.

Message: A single message in a conversation (user, assistant, tool_result).
Conversation: Ordered list of messages with context-window awareness.
ToolUse: A tool call emitted by the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolUse:
    """A tool invocation requested by the LLM."""

    id: str                        # unique call ID for correlating results
    name: str                      # tool name (e.g. "bash", "read_file")
    parameters: dict[str, Any]     # tool-specific parameters


@dataclass
class Message:
    """A single message in the conversation.

    Roles:
        system    — system prompt (always first)
        user      — human input
        assistant — LLM response (may include tool_uses)
        tool      — tool execution result (correlated by tool_use_id)
    """

    role: str                                   # system | user | assistant | tool
    content: str = ""                           # text content
    tool_uses: list[ToolUse] = field(default_factory=list)   # assistant only
    tool_use_id: str | None = None              # tool only — correlates to ToolUse.id

    @property
    def estimated_tokens(self) -> int:
        """Rough token estimate (~4 chars per token)."""
        n = len(self.content) // 4
        for tu in self.tool_uses:
            n += len(str(tu.parameters)) // 4 + 20  # overhead for name/id
        return max(n, 1)


@dataclass
class Conversation:
    """Ordered message list with context-window management.

    The system message (index 0) is never evicted.
    When the total exceeds max_tokens, oldest non-system messages
    are dropped from the front.
    """

    messages: list[Message] = field(default_factory=list)
    max_tokens: int = 100_000  # conservative default

    def add(self, msg: Message) -> None:
        self.messages.append(msg)
        self._trim()

    @property
    def total_tokens(self) -> int:
        return sum(m.estimated_tokens for m in self.messages)

    def to_dicts(self) -> list[dict[str, Any]]:
        """Serialize for LLM API calls."""
        out: list[dict[str, Any]] = []
        for m in self.messages:
            d: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.tool_uses:
                d["tool_calls"] = [
                    {
                        "id": tu.id,
                        "type": "function",
                        "function": {"name": tu.name, "arguments": tu.parameters},
                    }
                    for tu in m.tool_uses
                ]
            if m.tool_use_id:
                d["tool_call_id"] = m.tool_use_id
            out.append(d)
        return out

    def _trim(self) -> None:
        """Drop oldest non-system messages until under max_tokens."""
        while self.total_tokens > self.max_tokens and len(self.messages) > 2:
            # Find first non-system message to drop
            for i, m in enumerate(self.messages):
                if m.role != "system":
                    self.messages.pop(i)
                    break
            else:
                break  # only system messages left
