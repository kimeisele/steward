"""
Tool Dispatch — routing, safety gates, dependency waves.

Extracted from engine.py. Tool execution lifecycle:
  1. check_tool_gates: O(1) Lotus route → Narasimha → Iron Dome
  2. partition_by_dependency: write→read wave ordering
  3. coerce_result: raw asyncio result → ToolResult
  4. record_tool_file_ops: Iron Dome + Memory tracking
"""

from __future__ import annotations

import asyncio
import logging

from steward.context import ERROR_MARKER
from steward.types import ToolUse
from vibe_core.mahamantra.adapters.attention import MahaAttention
from vibe_core.protocols.mahajanas.nrisimha.types.narasimha import NarasimhaProtocol, ThreatLevel
from vibe_core.protocols.memory import MemoryProtocol
from vibe_core.runtime.tool_safety_guard import ToolSafetyGuard
from vibe_core.tools.tool_protocol import ToolResult

logger = logging.getLogger("STEWARD.LOOP.DISPATCH")

# Tool execution timeout (seconds) — prevents hung bash commands
TOOL_TIMEOUT_SECONDS = 120

# Narasimha severity ordinal rank — module-level constant
_SEVERITY_RANK = {
    ThreatLevel.GREEN: 0,
    ThreatLevel.YELLOW: 1,
    ThreatLevel.ORANGE: 2,
    ThreatLevel.RED: 3,
    ThreatLevel.APOCALYPSE: 4,
}

# File operation dispatch — tool name → op type
_FILE_OP_MAP: dict[str, str] = {
    "read_file": "read",
    "write_file": "write",
    "edit_file": "write",
}


def check_tool_gates(
    tc: ToolUse,
    attention: MahaAttention | None,
    narasimha: NarasimhaProtocol | None,
    safety_guard: ToolSafetyGuard | None,
) -> str | None:
    """Check all pre-execution gates for a tool call.

    Returns error message if blocked, None if cleared.
    Gates (in order): O(1) Lotus route → Narasimha → Iron Dome.
    """
    # Gate 1: O(1) Lotus route — verify tool exists
    if attention:
        route = attention.attend(tc.name)
        if not route.found:
            return f"Tool '{tc.name}' not found (O(1) route miss)"

    # Gate 2: Narasimha killswitch — audit bash for dangerous patterns
    if narasimha and tc.name == "bash":
        cmd = str(tc.parameters.get("command", ""))
        threat = narasimha.audit_agent(
            "steward",
            cmd,
            {"tool": tc.name},
        )
        if threat and _SEVERITY_RANK.get(threat.severity, 0) >= _SEVERITY_RANK[ThreatLevel.RED]:
            logger.warning("Narasimha blocked bash: %s", threat.description)
            return f"Narasimha blocked: {threat.description}"

    # Gate 3: Iron Dome safety check
    if safety_guard:
        allowed, violation = safety_guard.check_action(
            tc.name,
            tc.parameters,
        )
        if not allowed:
            return violation.message if violation else "Blocked by safety guard"

    return None  # All gates passed


def coerce_result(raw: object) -> ToolResult:
    """Convert raw asyncio.gather result to ToolResult."""
    if isinstance(raw, asyncio.TimeoutError):
        return ToolResult(success=False, error=f"Tool timed out after {TOOL_TIMEOUT_SECONDS}s")
    if isinstance(raw, BaseException):
        return ToolResult(success=False, error=str(raw))
    return raw  # type: ignore[return-value]


def record_file_op(memory: MemoryProtocol | None, path: str, op: str) -> None:
    """Record file operation in Memory for cross-turn awareness."""
    if not memory or not path:
        return
    key = f"files_{op}"
    existing = memory.recall(key, session_id="steward") or []
    if path not in existing:
        existing.append(path)
        memory.remember(key, existing, session_id="steward", tags=["file_ops"])


def record_tool_file_ops(
    tc: ToolUse,
    result: ToolResult,
    safety_guard: ToolSafetyGuard | None,
    memory: MemoryProtocol | None,
) -> None:
    """Record file read/write for Iron Dome + Memory (branchless dispatch)."""
    file_op = _FILE_OP_MAP.get(tc.name) if result.success else None
    if not file_op:
        return
    path = str(tc.parameters.get("path", ""))
    if safety_guard:
        if file_op == "read":
            safety_guard.record_file_read(path)
        elif file_op == "write":
            safety_guard.record_file_write(path)
    if memory:
        record_file_op(memory, path, file_op)


def partition_by_dependency(to_execute: list[tuple[ToolUse, object]]) -> list[list[int]]:
    """Partition tool indices into dependency-ordered waves.

    Protocol lesson (ActionStep.depends_on in steward-protocol):
    If tool A writes a file that tool B reads/tests, B must wait
    for A to complete. Tools within a wave run in parallel.
    Waves run sequentially.

    Returns list of waves, each wave is a list of indices into to_execute.
    """
    if len(to_execute) <= 1:
        return [list(range(len(to_execute)))]

    # Collect paths being written
    written_paths: set[str] = set()
    writer_indices: set[int] = set()
    for i, (tc, _) in enumerate(to_execute):
        if tc.name in ("write_file", "edit_file"):
            path = tc.parameters.get("path", "")
            if path:
                written_paths.add(path)
                writer_indices.add(i)

    if not written_paths:
        return [list(range(len(to_execute)))]  # No writes — all parallel

    # Find non-writers that reference any written path
    dependent_indices: set[int] = set()
    for i, (tc, _) in enumerate(to_execute):
        if i in writer_indices:
            continue
        for v in tc.parameters.values():
            if isinstance(v, str) and any(wp in v for wp in written_paths):
                dependent_indices.add(i)
                break

    if not dependent_indices:
        return [list(range(len(to_execute)))]  # No dependencies — all parallel

    # Wave 1: writers + independent, Wave 2: dependents
    wave1 = [i for i in range(len(to_execute)) if i not in dependent_indices]
    wave2 = sorted(dependent_indices)
    return [wave1, wave2]
