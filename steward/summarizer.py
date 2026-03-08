"""
Conversation Summarizer — LLM-based context compaction.

When the context window fills up, the summarizer compresses older
messages into a single summary message. This lets steward run
indefinitely without losing critical context.

The dumb trim (_trim in types.py) is the fallback when the LLM
is unavailable or summarization fails.

    summarizer = Summarizer(provider)
    compacted = summarizer.summarize(conversation, target_ratio=0.5)
"""

from __future__ import annotations

import logging

from steward.types import Conversation, LLMProvider, Message, MessageRole

logger = logging.getLogger("STEWARD.SUMMARIZER")

# How much of the conversation to summarize (oldest N%)
_SUMMARIZE_OLDEST_RATIO = 0.5

# Maximum tokens for the summary itself
_MAX_SUMMARY_TOKENS = 2000

_SUMMARIZE_PROMPT = """\
Summarize the following conversation between a user and an AI assistant.
Focus on:
- What task was requested
- What files were read, written, or modified
- What tools were used and their key results
- What decisions were made
- Any errors encountered and how they were resolved
- Current state of the work

Be concise. Use bullet points. Preserve file paths and exact names.
Do NOT include any preamble — just the summary bullets.

Conversation to summarize:
"""


class Summarizer:
    """LLM-based conversation summarizer.

    Compresses older messages into a single summary message,
    preserving the system prompt and most recent messages.
    """

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def summarize(
        self,
        conversation: Conversation,
        target_ratio: float = _SUMMARIZE_OLDEST_RATIO,
    ) -> bool:
        """Summarize older messages in-place.

        Selects the oldest non-system messages (up to target_ratio of total),
        sends them to the LLM for summarization, then replaces them with
        a single summary message.

        Args:
            conversation: Conversation to compact (modified in-place)
            target_ratio: What fraction of messages to summarize (0.0-1.0)

        Returns:
            True if summarization occurred, False if skipped/failed
        """
        msgs = conversation.messages
        if len(msgs) < 4:
            return False  # too few messages to summarize

        # Identify summarizable range: everything after system, before the last N
        system_end = 1 if msgs[0].role == MessageRole.SYSTEM else 0
        non_system = msgs[system_end:]

        # Keep the most recent messages intact
        keep_count = max(2, int(len(non_system) * (1 - target_ratio)))
        to_summarize = non_system[: len(non_system) - keep_count]
        to_keep = non_system[len(non_system) - keep_count :]

        if len(to_summarize) < 2:
            return False  # not enough to summarize

        # Build the text to summarize
        summary_input = self._messages_to_text(to_summarize)

        # Call LLM to summarize
        try:
            summary_text = self._call_llm(summary_input)
        except Exception as e:
            logger.warning("Summarization failed: %s — falling back to trim", e)
            return False

        if not summary_text:
            return False

        # Replace summarized messages with a single summary
        summary_msg = Message(
            role=MessageRole.USER,
            content=(f"[Summary of {len(to_summarize)} earlier messages]\n{summary_text}"),
        )

        # Rebuild: system + summary + kept messages
        new_messages = msgs[:system_end] + [summary_msg] + list(to_keep)
        conversation.messages = new_messages

        logger.info(
            "Summarized %d messages → %d tokens (kept %d recent)",
            len(to_summarize),
            summary_msg.estimated_tokens,
            len(to_keep),
        )
        return True

    def _call_llm(self, text_to_summarize: str) -> str:
        """Call the LLM to produce a summary."""
        response = self._provider.invoke(
            messages=[
                {"role": "user", "content": _SUMMARIZE_PROMPT + text_to_summarize},
            ],
            max_tokens=_MAX_SUMMARY_TOKENS,
        )

        # Extract text from response
        if hasattr(response, "content"):
            content = response.content  # type: ignore[attr-defined]
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = [b.text if hasattr(b, "text") else str(b) for b in content if hasattr(b, "text")]
                return "\n".join(texts)
        return ""

    @staticmethod
    def _messages_to_text(messages: list[Message]) -> str:
        """Convert messages to readable text for the summarizer LLM."""
        lines: list[str] = []
        for m in messages:
            prefix = m.role.upper()
            if m.role == MessageRole.TOOL:
                # Truncate long tool outputs for the summary input
                content = m.content[:500] if len(m.content) > 500 else m.content
                lines.append(f"[TOOL RESULT] {content}")
            elif m.tool_uses:
                tools = ", ".join(
                    f"{tu.name}({', '.join(f'{k}={v}' for k, v in tu.parameters.items())})" for tu in m.tool_uses
                )
                text = m.content[:200] if m.content else ""
                lines.append(f"{prefix}: {text} [called: {tools}]")
            else:
                lines.append(f"{prefix}: {m.content}")
        return "\n".join(lines)


def should_summarize(conversation: Conversation, threshold: float = 0.7) -> bool:
    """Check if conversation needs summarization.

    Args:
        conversation: The conversation to check
        threshold: Token budget ratio that triggers summarization (0.0-1.0)

    Returns:
        True if total_tokens > max_tokens * threshold
    """
    return conversation.total_tokens > conversation.max_tokens * threshold
