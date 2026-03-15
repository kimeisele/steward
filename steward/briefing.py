"""
Briefing — dynamic context generation for external consumers (e.g. Claude Code).

Boots senses, gaps, and session ledger without the full agent stack.
Outputs structured markdown that any LLM consumer can use as a bootstrap.

Usage:
    from steward.briefing import generate_briefing
    print(generate_briefing("/path/to/project"))

Or via CLI:
    python -m steward --briefing
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from steward.gaps import GapTracker
from steward.senses.coordinator import SenseCoordinator
from steward.session_ledger import SessionLedger

logger = logging.getLogger("STEWARD.BRIEFING")


def _load_gaps_from_disk(cwd: str) -> GapTracker:
    """Load gap tracker from .steward/memory.json without booting full memory service."""
    tracker = GapTracker()
    memory_file = Path(cwd) / ".steward" / "memory.json"
    if memory_file.is_file():
        try:
            data = json.loads(memory_file.read_text(encoding="utf-8"))
            # PersistentMemory stores under steward session
            gaps_data = data.get("steward", {}).get("gap_tracker", {}).get("value")
            if isinstance(gaps_data, list):
                tracker.load_from_dict(gaps_data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not load gaps: %s", e)
    return tracker


def generate_briefing(cwd: str | None = None) -> str:
    """Generate a dynamic context briefing from steward's system state.

    Boots SenseCoordinator, GapTracker, and SessionLedger independently
    (no LLM provider needed — pure deterministic perception).

    Returns structured markdown suitable for injection into any LLM context.
    """
    cwd = cwd or str(Path.cwd())
    parts: list[str] = []

    parts.append("# Steward Briefing")
    parts.append(f"Project: {Path(cwd).name}")
    parts.append(f"Path: {cwd}")

    # 1. Environmental perception (5 senses — deterministic, zero LLM)
    try:
        senses = SenseCoordinator(cwd=cwd)
        senses.perceive_all(force=True)
        sense_context = senses.format_for_prompt()
        if sense_context:
            parts.append(sense_context)
    except Exception as e:
        logger.warning("Senses failed: %s", e)

    # 2. Capability gaps (what steward couldn't do)
    try:
        gaps = _load_gaps_from_disk(cwd)
        gap_context = gaps.format_for_prompt()
        if gap_context:
            parts.append(gap_context)
    except Exception as e:
        logger.warning("Gap loading failed: %s", e)

    # 3. Session history (what steward did recently)
    try:
        ledger = SessionLedger(cwd=cwd)
        ledger_context = ledger.prompt_context()
        if ledger_context:
            parts.append(f"\n## Recent Sessions\n{ledger_context}")
    except Exception as e:
        logger.warning("Session ledger failed: %s", e)

    # 4. Project instructions (if any)
    instructions_paths = [
        Path(cwd) / ".steward" / "instructions.md",
        Path(cwd) / "CLAUDE.md",
    ]
    for path in instructions_paths:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"\n## Project Instructions\n{content}")
                    break
            except OSError:
                pass

    return "\n".join(parts)
