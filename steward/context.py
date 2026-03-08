"""
Samskara Context Engine — Deterministic conversation compaction.

"An agent doesn't need to know what it said 10 days ago.
It only needs to know the LESSON from that interaction."

Uses MahaCompression for intent-level deduplication and
deterministic structure extraction for context-preserving compaction.
Zero tokens spent on compression — LLM summarizer is fallback only.

Architecture (80% infra / 20% LLM):
    RECENT messages    → keep full text (LLM needs exact context)
    OLDER messages     → samskara extraction (deterministic, free)
    VERY OLD messages  → seed only (pattern detection)
    FALLBACK           → LLM summarization (only if needed)

    context = SamskaraContext(compressor)
    compacted = context.compact(conversation, keep_recent=4)
"""

from __future__ import annotations

import logging
import re

from vibe_core.mahamantra.adapters.compression import MahaCompression

from steward.types import Conversation, Message, MessageRole

logger = logging.getLogger("STEWARD.CONTEXT")

# Patterns for deterministic extraction
_FILE_PATH_RE = re.compile(r"(?:^|[\s\"'])((?:/[\w./-]+|\.[\w./-]+)\.(?:py|js|ts|yaml|yml|json|md|txt|toml|cfg|sh|rs|go|c|h|cpp|java))")
ERROR_MARKER = "[Error]"

# Tool name → file set key (branchless dispatch)
_TOOL_FILE_SET: dict[str, str] = {
    "read_file": "read",
    "write_file": "written",
    "edit_file": "written",
}


def _extract_structure(messages: list[Message]) -> str:
    """Extract deterministic structure from messages without LLM.

    Extracts:
    - File paths mentioned (read, written, edited)
    - Tools used and their outcomes
    - Key decisions (based on tool sequences)

    This is the 80% infra part — structure, not meaning.
    """
    files_read: set[str] = set()
    files_written: set[str] = set()
    tools_used: dict[str, int] = {}
    errors: list[str] = []

    for msg in messages:
        content = msg.content

        # Extract file paths
        for match in _FILE_PATH_RE.finditer(content):
            path = match.group(1).strip()
            if msg.role == MessageRole.TOOL:
                files_read.add(path)
            elif "write" in content.lower() or "edit" in content.lower():
                files_written.add(path)
            else:
                files_read.add(path)

        # Extract tool uses
        if msg.tool_uses:
            for tu in msg.tool_uses:
                tools_used[tu.name] = tools_used.get(tu.name, 0) + 1
                # Track file operations from tool parameters (branchless dispatch)
                path = str(tu.parameters.get("path", ""))
                file_set_key = _TOOL_FILE_SET.get(tu.name)
                if path and file_set_key:
                    target = files_read if file_set_key == "read" else files_written
                    target.add(path)

        # Extract errors from tool results
        if msg.role == MessageRole.TOOL and ERROR_MARKER in content:
            # Keep first line of error only
            error_line = content.split("\n")[0][:100]
            errors.append(error_line)

    # Build compact summary
    parts: list[str] = []

    if files_read:
        parts.append(f"Files read: {', '.join(sorted(files_read)[:10])}")
    if files_written:
        parts.append(f"Files modified: {', '.join(sorted(files_written)[:10])}")
    if tools_used:
        tool_summary = ", ".join(f"{name}({count})" for name, count in sorted(tools_used.items()))
        parts.append(f"Tools: {tool_summary}")
    if errors:
        parts.append(f"Errors: {len(errors)} ({errors[0][:60]})")

    return "\n".join(parts) if parts else "No structured data extracted"


class SamskaraContext:
    """Deterministic conversation compaction using MahaCompression.

    Replaces LLM-based summarization for the common case.
    LLM summarizer is only used as fallback when deterministic
    extraction doesn't capture enough context.
    """

    def __init__(self, compressor: MahaCompression | None = None) -> None:
        self._compressor = compressor or MahaCompression()

    def compact(
        self,
        conversation: Conversation,
        keep_recent: int = 4,
    ) -> bool:
        """Compact older messages into a samskara impression.

        Keeps the most recent `keep_recent` non-system messages intact.
        Older messages are replaced with a deterministic samskara:
        extracted structure + intent seed.

        Args:
            conversation: Conversation to compact (modified in-place)
            keep_recent: Number of recent non-system messages to preserve

        Returns:
            True if compaction occurred, False if not needed
        """
        msgs = conversation.messages
        if len(msgs) < keep_recent + 3:
            return False  # not enough to compact

        # Split: system | older | recent
        system_end = 1 if msgs[0].role == MessageRole.SYSTEM else 0
        non_system = msgs[system_end:]

        if len(non_system) <= keep_recent:
            return False

        to_compact = non_system[: len(non_system) - keep_recent]
        to_keep = non_system[len(non_system) - keep_recent:]

        if len(to_compact) < 2:
            return False

        # Phase 1: Deterministic structure extraction (80% infra)
        structure = _extract_structure(to_compact)

        # Phase 2: MahaCompression seed for pattern identity
        full_text = "\n".join(m.content for m in to_compact)
        result = self._compressor.compress(full_text, extract_summary=False)

        # Phase 3: Deduplicate by seed (same intent = merge)
        msg_seeds: list[int] = []
        for m in to_compact:
            if m.content:
                seed = self._compressor.compress(m.content, extract_summary=False).seed
                msg_seeds.append(seed)
        unique_seeds = len(set(msg_seeds))

        # Build samskara message
        samskara_content = (
            f"[Samskara of {len(to_compact)} messages | "
            f"seed={result.seed} | "
            f"{unique_seeds} unique intents | "
            f"ratio={result.compression_ratio:.0f}x]\n"
            f"{structure}"
        )

        samskara_msg = Message(role=MessageRole.USER, content=samskara_content)

        # Rebuild conversation
        conversation.messages = msgs[:system_end] + [samskara_msg] + list(to_keep)

        logger.info(
            "Samskara compaction: %d messages → 1 impression (%d→%d tokens, %d unique intents)",
            len(to_compact),
            sum(m.estimated_tokens for m in to_compact),
            samskara_msg.estimated_tokens,
            unique_seeds,
        )
        return True

    def should_compact(
        self,
        conversation: Conversation,
        threshold: float = 0.5,
    ) -> bool:
        """Check if conversation would benefit from samskara compaction.

        Uses a lower threshold than LLM summarization (0.5 vs 0.7)
        because samskara compaction is free — no tokens spent.

        Args:
            conversation: Conversation to check
            threshold: Token budget ratio that triggers compaction

        Returns:
            True if compaction would be beneficial
        """
        if len(conversation.messages) < 6:
            return False
        return conversation.total_tokens > conversation.max_tokens * threshold
