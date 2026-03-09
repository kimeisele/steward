"""
Core types for the Steward agent engine.

Message: A single message in a conversation (user, assistant, tool_result).
Conversation: Ordered list of messages with context-window awareness.
ToolUse: A tool call emitted by the LLM.
AgentEvent: Event yielded by the async agent loop.
LLMProvider: Protocol for LLM backends.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterator, Protocol, runtime_checkable

from vibe_core.tools.tool_protocol import ToolResult


class MessageRole(StrEnum):
    """Message roles — single source of truth.

    StrEnum so values work as dict keys and in string comparisons.
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class EventType(StrEnum):
    """Agent event types — single source of truth.

    StrEnum so values work as dict keys and in string comparisons.
    """

    TEXT_DELTA = "text_delta"
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    DONE = "done"


# JSON value types — what LLM tool parameters contain
JsonValue = str | int | float | bool | None | list | dict


@dataclass
class LLMUsage:
    """Normalized token usage from any LLM provider.

    Adapters normalize vendor-specific names (prompt_tokens, completion_tokens)
    to this canonical format at the boundary. Consumers never need getattr cascades.
    """

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ToolUse:
    """A tool invocation requested by the LLM."""

    id: str  # unique call ID for correlating results
    name: str  # tool name (e.g. "bash", "read_file")
    parameters: dict[str, JsonValue]  # tool-specific parameters


@dataclass
class NormalizedResponse:
    """Single response type from all LLM providers.

    Adapters normalize vendor-specific responses at the boundary.
    Downstream code never duck-types.
    """

    content: str = ""
    tool_calls: list[ToolUse] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)


@dataclass
class StreamDelta:
    """Streaming chunk from invoke_stream.

    text_delta: chunk text in .text
    done: final NormalizedResponse in .response
    """

    type: str  # "text_delta" | "done"
    text: str = ""
    response: NormalizedResponse | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers.

    All providers return NormalizedResponse from invoke().
    """

    def invoke(self, **kwargs: object) -> NormalizedResponse: ...


@runtime_checkable
class StreamingProvider(LLMProvider, Protocol):
    """Provider that supports streaming."""

    def invoke_stream(self, **kwargs: object) -> Iterator[StreamDelta]: ...


@runtime_checkable
class ChamberProvider(StreamingProvider, Protocol):
    """ProviderChamber — multi-provider with stats and feedback."""

    def stats(self) -> dict[str, object]: ...
    def set_feedback(self, feedback: object) -> None: ...
    def __len__(self) -> int: ...


@dataclass
class Message:
    """A single message in the conversation.

    Roles:
        system    — system prompt (always first)
        user      — human input
        assistant — LLM response (may include tool_uses)
        tool      — tool execution result (correlated by tool_use_id)
    """

    role: str  # system | user | assistant | tool
    content: str = ""  # text content
    tool_uses: list[ToolUse] = field(default_factory=list)  # assistant only
    tool_use_id: str | None = None  # tool only — correlates to ToolUse.id
    metadata: dict[str, object] = field(default_factory=dict)  # structured data (errors, etc.)

    @property
    def estimated_tokens(self) -> int:
        """Conservative token estimate.

        Uses ~3 chars per token (not 4) because code/JSON tokenizes worse
        than natural language. 3:1 is safer for budget calculations.
        Actual token counts come from LLM usage response for CBR accounting.
        """
        n = len(self.content) // 3
        for tu in self.tool_uses:
            n += len(str(tu.parameters)) // 3 + 20  # overhead for name/id
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

    def to_dicts(self) -> list[dict[str, object]]:
        """Serialize for LLM API calls — brain-in-a-jar format.

        - TOOL messages become user messages (JSON mode has no tool_call_id)
        - Consecutive same-role messages merged (providers expect alternating roles)
        - No tool_calls in assistant messages (tool info is in JSON content)
        """
        out: list[dict[str, object]] = []
        for m in self.messages:
            role = m.role
            content = m.content

            # Brain-in-a-jar: tool results sent as user messages
            if role == MessageRole.TOOL:
                role = MessageRole.USER

            # Merge consecutive same-role messages (prevents provider errors)
            if out and out[-1]["role"] == role:
                out[-1]["content"] = str(out[-1]["content"]) + "\n---\n" + content
            else:
                out.append({"role": role, "content": content})

        return out

    def _trim(self) -> None:
        """Smart context trimming — evict tool results first, then oldest.

        Priority order for eviction (highest first):
        1. Tool result messages (largest, least valuable long-term)
        2. Oldest non-system, non-user messages
        3. Oldest non-system messages

        When trimming occurs, inserts a summary marker so the LLM
        knows context was compacted.
        """
        if self.total_tokens <= self.max_tokens:
            return

        trimmed_count = 0
        # Phase 1: Drop oldest tool results first (they're biggest)
        while self.total_tokens > self.max_tokens and len(self.messages) > 2:
            for i, m in enumerate(self.messages):
                if m.role == MessageRole.TOOL:
                    self.messages.pop(i)
                    trimmed_count += 1
                    break
            else:
                break  # no more tool messages

        # Phase 2: Drop oldest non-system messages
        while self.total_tokens > self.max_tokens and len(self.messages) > 2:
            for i, m in enumerate(self.messages):
                if m.role != MessageRole.SYSTEM:
                    self.messages.pop(i)
                    trimmed_count += 1
                    break
            else:
                break  # only system messages left

        # Insert compaction marker after system message
        if trimmed_count > 0 and len(self.messages) >= 2:
            marker = Message(
                role=MessageRole.USER,
                content=f"[{trimmed_count} earlier messages trimmed for context budget]",
            )
            # Insert after system prompt
            insert_idx = 1 if self.messages[0].role == MessageRole.SYSTEM else 0
            self.messages.insert(insert_idx, marker)


@dataclass
class AgentUsage:
    """Token usage and run statistics for a single turn."""

    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    rounds: int = 0
    # Buddhi diagnostics (observable cognition)
    buddhi_action: str = ""  # SemanticActionType (e.g., "RESEARCH", "IMPLEMENT")
    buddhi_guna: str = ""  # IntentGuna (e.g., "SATTVA", "RAJAS")
    buddhi_tier: str = ""  # ModelTier (flash/standard/pro)
    buddhi_phase: str = ""  # Chitta phase (ORIENT/EXECUTE/VERIFY/COMPLETE)
    buddhi_errors: int = 0  # total tool errors detected by Buddhi
    buddhi_reflections: int = 0  # number of reflect/redirect injections
    # Venu / substrate diagnostics
    venu_diw: int = 0  # DIW from VenuOrchestrator for this turn
    input_seed: int = 0  # MahaCompression seed for input
    cache_hit: bool = False  # whether cache bypass was used
    # CBR: Constant Bitrate Token Stream
    cbr_budget: int = 0  # tokens budgeted for this tick
    cbr_consumed: int = 0  # tokens actually consumed (0 on cache hit)
    cbr_reserve: int = 0  # delta = budget - consumed (saved tokens)
    # Quality signals — self-reflection on output integrity
    truncated: bool = False  # output was truncated (hit char limit)
    cbr_exceeded: bool = False  # consumed > budget (over CBR)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class AgentEvent:
    """Event yielded by the async agent loop.

    Types:
        text_delta  — streaming text chunk (real-time output)
        text        — final complete text response from LLM
        tool_call   — LLM requested a tool invocation
        tool_result — tool execution completed
        error       — something went wrong
        done        — turn is complete (usage field populated)
    """

    type: EventType
    content: str | ToolResult | None = None
    tool_use: ToolUse | None = None
    usage: AgentUsage | None = None
