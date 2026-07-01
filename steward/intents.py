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

    # Membran-Signale (eingehend von Föderation — Stadt & Welt)
    BOTTLENECK_ESCALATION = "bottleneck_escalation"  # agent-city brain_health/critique
    GOVERNANCE_BOUNTY = "governance_bounty"  # agent-world Legislator

    # Stagnations-Diagnose (Kapitel 3b: Willensbildung)
    DIAGNOSE_STAGNATION = "diagnose_stagnation"

    @property
    def is_proactive(self) -> bool:
        """Proactive intents create PRs instead of direct fixes."""
        return self in _PROACTIVE_INTENTS

    @property
    def is_membran(self) -> bool:
        """Membran intents process inbound federation signals and require a task payload."""
        return self in _MEMBRAN_INTENTS

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

_MEMBRAN_INTENTS = frozenset({TaskIntent.BOTTLENECK_ESCALATION, TaskIntent.GOVERNANCE_BOUNTY})


# TaskIntent → check_conscience permission key mapping (Kapitel 3a: dharmische Gating).
# Lesende/detektierende Intents → "review_todos" (keine Schreibrechte erforderlich).
# Schreibende Intents → echter Permission-Key aus INTENT_PERMISSION_MAP.
INTENT_TO_CONSCIENCE: dict[TaskIntent, str] = {
    # Lesend/detektierend — keine besonderen Rechte
    TaskIntent.HEALTH_CHECK: "review_todos",
    TaskIntent.SENSE_SCAN: "review_todos",
    TaskIntent.CI_CHECK: "review_todos",
    TaskIntent.FEDERATION_HEALTH: "review_todos",
    TaskIntent.CROSS_REPO_DIAGNOSTIC: "review_todos",
    TaskIntent.FEDERATION_GAP_SCAN: "review_todos",
    TaskIntent.SYNTHESIZE_BRIEFING: "doc_update",        # schreibt Doku
    TaskIntent.DIAGNOSE_STAGNATION: "review_todos",     # lesender Detektor
    # Schreibend — brauchen echte Rechte
    TaskIntent.HEAL_REPO: "contract_import_fix",          # code_modify
    TaskIntent.BOTTLENECK_ESCALATION: "contract_import_fix",  # code_modify
    TaskIntent.GOVERNANCE_BOUNTY: "contract_import_fix",  # code_modify
    TaskIntent.POST_MERGE: "commit_and_push",             # git
    TaskIntent.UPDATE_DEPS: "create_pr",                  # git_push + pr_create
    TaskIntent.REMOVE_DEAD_CODE: "create_pr",             # git_push + pr_create
}


# Metadata key used in TaskManager tasks to store the intent type
INTENT_TYPE_KEY = "intent_type"
