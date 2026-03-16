"""Healer types — FixStrategy, HealResult, classification."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from steward.senses.diagnostic_sense import FindingKind

if TYPE_CHECKING:
    from steward.senses.diagnostic_sense import Finding


class FixStrategy(enum.Enum):
    """How to fix a finding.

    DETERMINISTIC: Pure Python, 0 tokens. Pattern-matchable.
    COMPOUND: Deterministic pipeline first, gated LLM fallback if needed.
    SKIP: Info-level or no fixer available yet.
    """

    DETERMINISTIC = "deterministic"
    COMPOUND = "compound"
    SKIP = "skip"


_STRATEGY: dict[FindingKind, FixStrategy] = {
    FindingKind.UNDECLARED_DEPENDENCY: FixStrategy.DETERMINISTIC,
    FindingKind.MISSING_DEPENDENCY: FixStrategy.DETERMINISTIC,
    FindingKind.NO_FEDERATION_DESCRIPTOR: FixStrategy.DETERMINISTIC,
    FindingKind.NO_PEER_JSON: FixStrategy.DETERMINISTIC,
    FindingKind.NO_CI: FixStrategy.DETERMINISTIC,
    FindingKind.NO_TESTS: FixStrategy.DETERMINISTIC,
    FindingKind.BROKEN_IMPORT: FixStrategy.DETERMINISTIC,
    FindingKind.SYNTAX_ERROR: FixStrategy.DETERMINISTIC,
    FindingKind.CIRCULAR_IMPORT: FixStrategy.DETERMINISTIC,
    FindingKind.CI_FAILING: FixStrategy.COMPOUND,
    FindingKind.NADI_BLOCKED: FixStrategy.DETERMINISTIC,
    FindingKind.BASE_EXCEPTION_CATCH: FixStrategy.DETERMINISTIC,
    FindingKind.DYNAMIC_IMPORT: FixStrategy.DETERMINISTIC,
    FindingKind.UNBOUNDED_COLLECTION: FixStrategy.SKIP,  # needs human decision on size
    FindingKind.LARGE_FILE: FixStrategy.SKIP,
}


def classify(kind: FindingKind) -> FixStrategy:
    """Classify a finding kind into a fix strategy."""
    return _STRATEGY.get(kind, FixStrategy.SKIP)


@dataclass(frozen=True)
class HealResult:
    """Outcome of a single repo healing attempt."""

    repo: str
    findings_total: int = 0
    findings_fixable: int = 0
    findings_fixed: int = 0
    pr_url: str = ""
    error: str = ""


# Fixer registry — populated by @_fixer decorator in fixers.py
_FIXERS: dict[FindingKind, Callable[["Finding", Path], list[str]]] = {}


def _fixer(kind: FindingKind):
    """Decorator to register a deterministic fixer for a FindingKind."""

    def decorator(fn: Callable[["Finding", Path], list[str]]):
        _FIXERS[kind] = fn
        return fn

    return decorator
