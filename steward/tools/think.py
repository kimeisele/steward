"""
Think Tool — Neuro-Symbolic reasoning bridge.

The LLM calls this tool to pause, reason, and get structured feedback
from the symbolic Antahkarana (cognitive architecture) before acting.

This is NOT a scratchpad. The symbolic layer actively validates the
LLM's hypothesis against:
  - Chitta (memory): Has this been tried before? What happened?
  - Gandha (patterns): Are there known anti-patterns in this plan?
  - Vedana (health): Is the system healthy enough for this action?
  - KsetraJna (meta): What phase are we in? Are we stuck?

Returns structured guidance that grounds the LLM's next action.
"""

from __future__ import annotations

import logging
from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolResult

logger = logging.getLogger("STEWARD.THINK")


class ThinkTool(Tool):
    """Neuro-symbolic reasoning tool — LLM thinks, system validates."""

    def __init__(self) -> None:
        self._chitta: object | None = None
        self._vedana_source: object | None = None
        self._ksetrajna: object | None = None
        self._maha_buddhi: object | None = None

    @property
    def name(self) -> str:
        return "think"

    @property
    def description(self) -> str:
        return (
            "Pause and reason before acting. Submit a hypothesis or plan — "
            "the system validates it against memory, patterns, and health, "
            "then returns structured guidance. Use this before complex or "
            "risky actions, when stuck, or when you need to re-orient."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "hypothesis": {
                "type": "string",
                "required": True,
                "description": (
                    "Your current hypothesis, plan, or question. "
                    "What do you think is happening? What do you plan to do next?"
                ),
            },
            "action": {
                "type": "string",
                "required": False,
                "description": (
                    "The specific action you're considering (e.g., 'edit context_bridge.py', "
                    "'run tests', 'refactor immune.py'). If provided, the system checks "
                    "preconditions and known risks for this action."
                ),
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if "hypothesis" not in parameters or not parameters["hypothesis"].strip():
            raise ValueError("Missing required parameter: hypothesis")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        hypothesis = parameters["hypothesis"]
        planned_action = parameters.get("action", "")

        feedback = _build_symbolic_feedback(
            hypothesis=hypothesis,
            planned_action=planned_action,
            chitta=self._chitta,
            vedana_source=self._vedana_source,
            ksetrajna=self._ksetrajna,
            maha_buddhi=self._maha_buddhi,
        )

        logger.info("Think: %s → %s", hypothesis[:80], feedback.get("guidance", "")[:80])

        # Format as structured text for the LLM
        output = _format_feedback(feedback)
        return ToolResult(success=True, output=output)


def _build_symbolic_feedback(
    *,
    hypothesis: str,
    planned_action: str,
    chitta: object | None,
    vedana_source: object | None,
    ksetrajna: object | None,
    maha_buddhi: object | None,
) -> dict[str, object]:
    """Query all Antahkarana components and build structured feedback."""
    feedback: dict[str, Any] = {}

    # ── Chitta: Memory check ──────────────────────────────────────
    if chitta is not None:
        impressions = chitta.impressions
        phase = chitta.phase

        feedback["phase"] = phase
        feedback["round"] = len(impressions)

        # Check if planned action was tried before
        if planned_action:
            similar = [
                imp for imp in impressions
                if planned_action.lower() in str(imp).lower()
            ]
            if similar:
                last = similar[-1]
                feedback["memory"] = (
                    f"Similar action attempted {len(similar)}x before. "
                    f"Last result: {'success' if getattr(last, 'success', True) else 'FAILED'}."
                )
            else:
                feedback["memory"] = "No prior attempts of this action in memory."

        # Files already read (for read-before-write check)
        read_files = [
            imp.path for imp in impressions
            if hasattr(imp, 'name') and imp.name == "read_file" and hasattr(imp, 'path')
        ]
        if read_files:
            feedback["files_read"] = list(set(read_files))

    # ── Gandha: Pattern detection ─────────────────────────────────
    if chitta is not None:
        try:
            from steward.antahkarana.gandha import detect_patterns

            detection = detect_patterns(chitta.impressions)
            if detection and detection.pattern:
                feedback["pattern_warning"] = (
                    f"[{detection.severity.name}] Pattern detected: {detection.pattern}. "
                    f"Suggestion: {detection.suggestion}"
                )
        except Exception:
            logger.debug("Gandha pattern detection failed", exc_info=True)

    # ── Vedana: Health signal ─────────────────────────────────────
    if vedana_source is not None:
        try:
            vedana = vedana_source()
            feedback["health"] = round(vedana.health, 3)
            feedback["guna"] = vedana.guna
            if vedana.health < 0.5:
                feedback["health_warning"] = (
                    f"System health is LOW ({vedana.health:.2f}). "
                    "Consider simpler actions or diagnostic steps first."
                )
        except Exception:
            logger.debug("Vedana health signal failed", exc_info=True)

    # ── KsetraJna: Meta-observation ───────────────────────────────
    if ksetrajna is not None:
        try:
            if ksetrajna.last is not None:
                snap = ksetrajna.last
                feedback["meta_phase"] = snap.phase
                feedback["meta_round"] = snap.round
                if ksetrajna.is_stuck(window=5, threshold=0.05):
                    feedback["stuck_warning"] = (
                        "STAGNATION DETECTED: The last 5 observations show no progress. "
                        "Break the pattern — try a completely different approach."
                    )
                trend = ksetrajna.trend()
                if trend == "degrading":
                    feedback["trend_warning"] = (
                        "Health trend is DEGRADING. Recent actions are making things worse."
                    )
        except Exception:
            logger.debug("KsetraJna meta-observation failed", exc_info=True)

    # ── MahaBuddhi: Cognitive alignment ───────────────────────────
    if maha_buddhi is not None and hypothesis:
        try:
            cognition = maha_buddhi.think(hypothesis)
            if cognition:
                feedback["cognitive_frame"] = {
                    "approach": getattr(cognition, "approach", None),
                    "function": getattr(cognition, "function", None),
                    "mode": getattr(cognition, "mode", None),
                }
        except Exception:
            logger.debug("MahaBuddhi cognition failed", exc_info=True)

    # ── Synthesize guidance ───────────────────────────────────────
    guidance_parts = []

    if "stuck_warning" in feedback:
        guidance_parts.append(feedback["stuck_warning"])
    elif "health_warning" in feedback:
        guidance_parts.append(feedback["health_warning"])
    elif "trend_warning" in feedback:
        guidance_parts.append(feedback["trend_warning"])
    elif "pattern_warning" in feedback:
        guidance_parts.append(feedback["pattern_warning"])

    if "memory" in feedback:
        guidance_parts.append(feedback["memory"])

    if not guidance_parts:
        phase = feedback.get("phase", "ORIENT")
        guidance_parts.append(f"Phase: {phase}. Hypothesis acknowledged. Proceed with action.")

    feedback["guidance"] = " ".join(guidance_parts)

    return feedback


def _format_feedback(feedback: dict[str, object]) -> str:
    """Format symbolic feedback as structured text for the LLM."""
    lines = ["[Think — Symbolic Feedback]"]

    if "phase" in feedback:
        lines.append(f"Phase: {feedback['phase']} | Round: {feedback.get('round', '?')}")

    if "health" in feedback:
        lines.append(f"Health: {feedback['health']} ({feedback.get('guna', '?')})")

    if "cognitive_frame" in feedback:
        cf = feedback["cognitive_frame"]
        parts = [f"{k}={v}" for k, v in cf.items() if v]
        if parts:
            lines.append(f"Cognitive: {', '.join(parts)}")

    lines.append("")
    lines.append(feedback.get("guidance", "Proceed."))

    if "files_read" in feedback:
        lines.append(f"\nFiles in memory: {', '.join(feedback['files_read'][:10])}")

    return "\n".join(lines)
