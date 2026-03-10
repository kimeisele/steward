"""
Agent Memory — persistence operations for Hebbian, Chitta, Gaps, Stats.

Extracted from agent.py god class. All load/save operations are
pure functions that take the components as arguments.
"""

from __future__ import annotations

import logging

from steward.buddhi import Buddhi
from steward.gaps import GapTracker
from steward.session_ledger import SessionLedger, SessionRecord
from steward.types import AgentUsage
from vibe_core.mahamantra.substrate.manas.synaptic import HebbianSynaptic
from vibe_core.protocols.memory import MemoryProtocol

logger = logging.getLogger("STEWARD.MEMORY")


def load_synaptic(memory: MemoryProtocol, synaptic: HebbianSynaptic) -> None:
    """Restore Hebbian synaptic weights from PersistentMemory.

    TODO(steward-protocol): Add HebbianSynaptic.restore(dict) to avoid
    direct _weights access. Until then, this is the only place that
    bypasses encapsulation — kept intentionally in one module.
    """
    data = memory.recall("synaptic_weights", session_id="steward")
    if data and isinstance(data, dict):
        synaptic._weights.update({k: float(v) for k, v in data.items()})
        logger.debug("Synaptic weights restored: %d entries", len(data))


def save_synaptic(memory: MemoryProtocol, synaptic: HebbianSynaptic) -> None:
    """Persist Hebbian synaptic weights to PersistentMemory."""
    weights = synaptic.snapshot()
    if weights:
        memory.remember(
            "synaptic_weights",
            weights,
            session_id="steward",
            tags=["synaptic", "hebbian"],
        )


def load_chitta(memory: MemoryProtocol, buddhi: Buddhi) -> None:
    """Restore Chitta's cross-turn state from PersistentMemory."""
    summary = memory.recall("chitta_summary", session_id="steward")
    if summary and isinstance(summary, dict):
        buddhi.load_chitta_summary(summary)
        logger.debug(
            "Chitta restored: %d prior reads",
            buddhi.chitta_prior_reads_count,
        )


def save_chitta(memory: MemoryProtocol, buddhi: Buddhi) -> None:
    """Persist Chitta's cross-turn state to PersistentMemory."""
    summary = buddhi.chitta_summary()
    memory.remember(
        "chitta_summary",
        summary,
        session_id="steward",
        tags=["chitta"],
    )


def load_gaps(memory: MemoryProtocol, gaps: GapTracker) -> None:
    """Restore gap tracker state from PersistentMemory."""
    data = memory.recall("gap_tracker", session_id="steward")
    if data and isinstance(data, list):
        gaps.load_from_dict(data)
        active = len(gaps)
        if active:
            logger.debug("Restored %d active gaps", active)


def save_gaps(memory: MemoryProtocol, gaps: GapTracker) -> None:
    """Persist gap tracker state to PersistentMemory."""
    memory.remember(
        "gap_tracker",
        gaps.to_dict(),
        session_id="steward",
        tags=["gaps"],
    )


def record_session_stats(memory: MemoryProtocol, usage: AgentUsage) -> None:
    """Record cumulative session stats in Memory."""
    existing = memory.recall("session_stats", session_id="steward") or {}
    stats = {
        "turns": existing.get("turns", 0) + 1,
        "total_input_tokens": existing.get("total_input_tokens", 0) + usage.input_tokens,
        "total_output_tokens": existing.get("total_output_tokens", 0) + usage.output_tokens,
        "total_tool_calls": existing.get("total_tool_calls", 0) + usage.tool_calls,
        "total_errors": existing.get("total_errors", 0) + usage.buddhi_errors,
        "total_reflections": existing.get("total_reflections", 0) + usage.buddhi_reflections,
    }
    classifications = existing.get("classifications", {})
    if usage.buddhi_action:
        classifications[usage.buddhi_action] = classifications.get(usage.buddhi_action, 0) + 1
    stats["classifications"] = classifications
    memory.remember("session_stats", stats, session_id="steward", tags=["stats"])


def record_session_ledger(
    ledger: SessionLedger,
    buddhi: Buddhi,
    task: str,
    usage: AgentUsage,
) -> None:
    """Record this task in the session ledger for cross-session learning."""
    outcome = "error" if usage.buddhi_errors > usage.tool_calls // 2 else "success"
    if usage.buddhi_errors > 0 and outcome == "success":
        outcome = "partial"

    ledger.record(
        SessionRecord(
            task=task,
            outcome=outcome,
            summary=f"{usage.buddhi_action or 'task'}: {usage.rounds} rounds, {usage.tool_calls} tools",
            tokens=usage.input_tokens + usage.output_tokens,
            tool_calls=usage.tool_calls,
            rounds=usage.rounds,
            files_read=buddhi.chitta_files_read[:10],
            files_written=buddhi.chitta_files_written[:10],
            buddhi_action=usage.buddhi_action or "",
            buddhi_phase=str(usage.buddhi_phase) if usage.buddhi_phase else "",
            errors=usage.buddhi_errors,
        )
    )


def load_persona() -> dict[str, str] | None:
    """Derive Jiva identity from MahaMantra VM (deterministic, from seed)."""
    try:
        from vibe_core.mahamantra import mahamantra

        vm = mahamantra("steward")
        jiva = {
            "guna": vm["guna"]["mode"],
            "guardian": vm["guardian"],
            "quarter": vm["quarter"],
            "trinity": vm["trinity_function"],
            "position": str(vm["position"]),
            "holy_name": vm["holy_name"],
        }
        logger.info(
            "Jiva identity: %s | %s | %s | %s",
            jiva["guna"], jiva["guardian"], jiva["quarter"], jiva["trinity"],
        )
        return jiva
    except Exception as e:
        logger.debug("Jiva derivation skipped: %s", e)
        return None
