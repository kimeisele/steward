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
    """

    HEALTH_CHECK = "health_check"
    SENSE_SCAN = "sense_scan"
    CI_CHECK = "ci_check"

    @classmethod
    def from_intent_type(cls, intent_type: str) -> TaskIntent | None:
        """Map a SankalpaIntent.intent_type string to a TaskIntent enum.

        Returns None for unknown types (logged, not fed to LLM).
        """
        for member in cls:
            if member.value == intent_type:
                return member
        return None


# Metadata key used in TaskManager tasks to store the intent type
INTENT_TYPE_KEY = "intent_type"
