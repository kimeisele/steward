"""
Session Ledger — Cross-session learning via automatic session recording.

After each task, the ledger records: what was asked, what happened,
how many tokens/tools/rounds, which files were touched.

On startup, recent sessions are injected into the system prompt
so the agent starts with context about past work.

Storage: .steward/sessions.json (Phoenix atomic writes).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from vibe_core.utils.atomic_io import atomic_write_json

logger = logging.getLogger("STEWARD.LEDGER")

_LEDGER_VERSION = 1
_MAX_SESSIONS = 50  # Keep last 50 sessions
_PROMPT_SESSIONS = 5  # Include last 5 in system prompt


@dataclass
class SessionRecord:
    """A single recorded session."""

    task: str  # Original user request (truncated)
    outcome: str  # "success" | "error" | "partial"
    summary: str  # What was accomplished (1-2 sentences)
    timestamp: str = ""
    tokens: int = 0
    tool_calls: int = 0
    rounds: int = 0
    files_read: list[str] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    buddhi_action: str = ""
    buddhi_phase: str = ""
    errors: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SessionRecord:
        return cls(
            task=d.get("task", ""),
            outcome=d.get("outcome", ""),
            summary=d.get("summary", ""),
            timestamp=d.get("timestamp", ""),
            tokens=d.get("tokens", 0),
            tool_calls=d.get("tool_calls", 0),
            rounds=d.get("rounds", 0),
            files_read=d.get("files_read", []),
            files_written=d.get("files_written", []),
            buddhi_action=d.get("buddhi_action", ""),
            buddhi_phase=d.get("buddhi_phase", ""),
            errors=d.get("errors", 0),
        )


class SessionLedger:
    """Records and retrieves session history for cross-session learning.

    Usage:
        ledger = SessionLedger(cwd="/project")
        ledger.record(SessionRecord(task="Fix bug", outcome="success", ...))
        context = ledger.prompt_context()  # For system prompt injection
    """

    def __init__(self, cwd: str | None = None) -> None:
        base = Path(cwd) if cwd else Path.cwd()
        self._state_dir = base / ".steward"
        self._ledger_file = self._state_dir / "sessions.json"
        self._sessions: list[SessionRecord] = []
        self._load()

    def record(self, session: SessionRecord) -> None:
        """Record a completed session."""
        if not session.timestamp:
            session.timestamp = datetime.now(timezone.utc).isoformat()

        # Truncate task to prevent bloat
        if len(session.task) > 200:
            session.task = session.task[:200] + "..."

        # Truncate file lists
        session.files_read = session.files_read[:20]
        session.files_written = session.files_written[:20]

        self._sessions.append(session)

        # Trim to max
        if len(self._sessions) > _MAX_SESSIONS:
            self._sessions = self._sessions[-_MAX_SESSIONS:]

        self._save()
        logger.info(
            "Session recorded: %s (%s, %d tokens, %d tools)",
            session.outcome,
            session.buddhi_action or "unknown",
            session.tokens,
            session.tool_calls,
        )

    def prompt_context(self) -> str:
        """Generate context string for system prompt injection.

        Returns a concise summary of recent sessions, or empty string
        if no history exists.
        """
        if not self._sessions:
            return ""

        recent = self._sessions[-_PROMPT_SESSIONS:]
        lines = ["Previous sessions in this project:"]
        for s in recent:
            date = s.timestamp[:10] if s.timestamp else "?"
            files = ", ".join(s.files_written[:3]) if s.files_written else "none"
            lines.append(
                f"  [{date}] {s.outcome}: {s.task[:80]} ({s.tokens} tokens, {s.rounds} rounds, files: {files})"
            )

        return "\n".join(lines)

    @property
    def sessions(self) -> list[SessionRecord]:
        return list(self._sessions)

    @property
    def stats(self) -> dict[str, object]:
        """Aggregate stats across all recorded sessions."""
        if not self._sessions:
            return {"total_sessions": 0}

        total_tokens = sum(s.tokens for s in self._sessions)
        total_tools = sum(s.tool_calls for s in self._sessions)
        successes = sum(1 for s in self._sessions if s.outcome == "success")
        return {
            "total_sessions": len(self._sessions),
            "success_rate": successes / len(self._sessions) if self._sessions else 0,
            "total_tokens": total_tokens,
            "total_tool_calls": total_tools,
            "avg_tokens_per_session": total_tokens // len(self._sessions) if self._sessions else 0,
        }

    def _save(self) -> None:
        """Persist ledger to disk (Phoenix atomic write)."""
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "version": _LEDGER_VERSION,
                "sessions": [s.to_dict() for s in self._sessions],
            }
            atomic_write_json(self._ledger_file, data)
        except Exception as e:
            logger.warning("Ledger save failed: %s", e)

    def _load(self) -> None:
        """Load ledger from disk."""
        if not self._ledger_file.exists():
            return
        try:
            raw = json.loads(self._ledger_file.read_text())
            if raw.get("version") != _LEDGER_VERSION:
                return
            self._sessions = [SessionRecord.from_dict(d) for d in raw.get("sessions", [])]
            logger.debug("Ledger loaded (%d sessions)", len(self._sessions))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Ledger load failed (%s), starting fresh", e)
