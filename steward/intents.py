"""
Deterministic Task Intents — typed control flow for autonomous operation.

Control flow belongs in code, not in prompts. The autonomy loop runs
purely on enums dispatched to Python methods. The LLM only wakes up
when a deterministic method finds a real error that requires code fixes.

Flow:
  1. Sankalpa.think() → SankalpaIntent (with intent_type string)
  2. intent_type mapped to TaskIntent enum (deterministic)
  3. TaskManager stores task with metadata["intent_type"]
  4. run_autonomous() → dispatch to Python method → 0 tokens
  5. If method finds real problem → THEN create LLM task
"""

from __future__ import annotations

import enum


class TaskIntent(enum.Enum):
    """Typed intents for deterministic autonomous task dispatch.

    Each value maps to a SankalpaIntent.intent_type string.
    Each intent dispatches to a hardcoded Python method — no LLM.

    Two categories:
    - Reactive: fix problems on current branch (HEALTH_CHECK, CI_CHECK)
    - Proactive: improvements via PR (UPDATE_DEPS, REMOVE_DEAD_CODE)
    """

    # Reactive — fix problems directly
    HEALTH_CHECK = "health_check"
    SENSE_SCAN = "sense_scan"
    CI_CHECK = "ci_check"
    POST_MERGE = "post_merge"

    # Reactive — federation monitoring
    FEDERATION_HEALTH = "federation_health"
    CROSS_REPO_DIAGNOSTIC = "cross_repo_diagnostic"
    HEAL_REPO = "heal_repo"

    # Proactive — improvements via feature branch + PR
    UPDATE_DEPS = "update_deps"
    REMOVE_DEAD_CODE = "remove_dead_code"

    # Autonomous — self-documentation
    SYNTHESIZE_BRIEFING = "synthesize_briefing"

    # Autonomous — federation architecture gaps
    FEDERATION_GAP_SCAN = "federation_gap_scan"

    # Reactive — inbound federation bottleneck (from peer scope gate)
    BOTTLENECK_ESCALATION = "bottleneck_escalation"

    @property
    def is_proactive(self) -> bool:
        """Proactive intents create PRs instead of direct fixes."""
        return self in _PROACTIVE_INTENTS

    @classmethod
    def from_intent_type(cls, intent_type: str) -> TaskIntent | None:
        """Map a SankalpaIntent.intent_type string to a TaskIntent enum.

        Returns None for unknown types (logged, not fed to LLM).
        """
        for member in cls:
            if member.value == intent_type:
                return member
        return None


_PROACTIVE_INTENTS = frozenset({TaskIntent.UPDATE_DEPS, TaskIntent.REMOVE_DEAD_CODE, TaskIntent.HEAL_REPO})


# Metadata key used in TaskManager tasks to store the intent type
INTENT_TYPE_KEY = "intent_type"
