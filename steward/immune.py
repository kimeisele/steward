"""
StewardImmune — Structural self-healing with Hebbian learning.

Adapted from agent-city's CityImmune. Composes steward's existing
infrastructure into a unified immune system:

Pipeline:
  finding → diagnose(pattern) → get_remedy_confidence(pattern, remedy)
    → heal(file, rule_id) → ShuddhiEngine CST surgical fix
    → verify (test baseline) → learn(pattern, remedy, success)

CytokineBreaker prevents autoimmune cascades:
  If heal increases test failures → rollback + escalate.
  After 3 consecutive rollbacks → all healing suspended 5 min.

Ref: agent-city/city/immune.py, steward issue #5
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from vibe_core.mahamantra.substrate.manas.synaptic import HebbianSynaptic

logger = logging.getLogger("STEWARD.IMMUNE")

# Minimum Hebbian confidence to attempt healing
_HEAL_THRESHOLD = 0.3

# Circuit Breaker
_MAX_CASCADE_FAILURES = 0  # heal must not increase failures AT ALL
_BREAKER_COOLDOWN_S = 300  # 5 min cooldown
_MAX_CONSECUTIVE_ROLLBACKS = 3


# ── Data Types ───────────────────────────────────────────────────────


@dataclass
class DiagnosisResult:
    """Result of diagnosing a failure pattern."""

    pattern: str
    rule_id: str | None
    file_path: Path | None
    confidence: float
    healable: bool


@dataclass
class HealResult:
    """Result of attempting to heal a diagnosed issue."""

    pattern: str
    rule_id: str
    success: bool
    message: str = ""
    diff: str = ""


@dataclass
class CytokineBreaker:
    """Circuit breaker — prevents autoimmune cascades.

    If a heal increases test failures, the fix is rolled back.
    After max_consecutive rollbacks, ALL healing is suspended.
    """

    rollbacks: int = 0
    consecutive_rollbacks: int = 0
    tripped: bool = False
    tripped_at: float = 0.0
    cooldown_s: float = _BREAKER_COOLDOWN_S
    max_consecutive: int = _MAX_CONSECUTIVE_ROLLBACKS

    def record_rollback(self) -> None:
        self.rollbacks += 1
        self.consecutive_rollbacks += 1
        if self.consecutive_rollbacks >= self.max_consecutive:
            self.tripped = True
            self.tripped_at = time.time()
            logger.critical(
                "CYTOKINE STORM: breaker TRIPPED after %d rollbacks. Healing suspended %ds.",
                self.consecutive_rollbacks,
                int(self.cooldown_s),
            )

    def record_success(self) -> None:
        self.consecutive_rollbacks = 0

    def is_open(self) -> bool:
        if not self.tripped:
            return False
        if (time.time() - self.tripped_at) >= self.cooldown_s:
            self.tripped = False
            self.consecutive_rollbacks = 0
            logger.info("Cytokine breaker: cooldown expired, healing re-enabled.")
            return False
        return True

    def stats(self) -> dict:
        return {
            "rollbacks": self.rollbacks,
            "consecutive_rollbacks": self.consecutive_rollbacks,
            "tripped": self.tripped,
            "cooldown_remaining": (
                max(0, self.cooldown_s - (time.time() - self.tripped_at))
                if self.tripped
                else 0
            ),
        }


# ── StewardImmune ────────────────────────────────────────────────────


@dataclass
class StewardImmune:
    """Structural self-healing with Hebbian-learned remedy confidence.

    Uses ShuddhiEngine for CST surgical fixes when available.
    Falls back to AST-level fixes from steward's own healer fixers.
    """

    _engine: object = field(default=None)
    _synaptic: Optional["HebbianSynaptic"] = field(default=None)
    _available: bool = field(default=False)
    _heals_attempted: int = 0
    _heals_succeeded: int = 0
    _heals_rolled_back: int = 0
    _breaker: CytokineBreaker = field(default_factory=CytokineBreaker)
    _cwd: str = field(default=".")

    def __post_init__(self) -> None:
        if self._engine is not None:
            self._available = True
            return

        try:
            from vibe_core.mahamantra.dharma.kumaras.engine import ShuddhiEngine

            self._engine = ShuddhiEngine()
            remedies = self._engine.list_remedies()
            logger.info("StewardImmune initialized with ShuddhiEngine (%d remedies)", len(remedies))
        except Exception as e:
            logger.info("ShuddhiEngine unavailable (%s) — AST-level fixers active", e)

        # Always available — AST fixers work without ShuddhiEngine
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    def diagnose(self, detail: str) -> DiagnosisResult:
        """Diagnose a failure pattern → find matching remedy + confidence."""
        rule_id = _match_pattern(detail)
        file_path = _extract_file_path(detail)
        confidence = 0.5

        if rule_id and self._synaptic is not None:
            confidence = self._synaptic.get_weight(f"immune:{rule_id}", "heal")

        healable = (
            rule_id is not None
            and file_path is not None
            and confidence >= _HEAL_THRESHOLD
        )

        return DiagnosisResult(
            pattern=detail,
            rule_id=rule_id,
            file_path=file_path,
            confidence=confidence,
            healable=healable,
        )

    def heal(self, diagnosis: DiagnosisResult) -> HealResult:
        """Attempt healing based on diagnosis. Records outcome in Hebbian."""
        if not diagnosis.healable or diagnosis.rule_id is None or diagnosis.file_path is None:
            return HealResult(
                pattern=diagnosis.pattern,
                rule_id=diagnosis.rule_id or "unknown",
                success=False,
                message="Not healable (no remedy or low confidence)",
            )

        self._heals_attempted += 1

        try:
            # Try ShuddhiEngine first (CST surgical fix)
            if self._available and self._engine is not None and self._engine.can_heal(diagnosis.rule_id):
                result = self._engine.purify(diagnosis.file_path, diagnosis.rule_id)
                success = result.success
                diff = getattr(result, "diff", "")
                message = getattr(result, "message", "")
            else:
                # Fallback: steward's own AST-level fixers
                success, message, diff = self._try_ast_fix(diagnosis)

            if success:
                self._heals_succeeded += 1

            self._learn(diagnosis.rule_id, success)

            return HealResult(
                pattern=diagnosis.pattern,
                rule_id=diagnosis.rule_id,
                success=success,
                message=message,
                diff=diff,
            )
        except Exception as e:
            self._learn(diagnosis.rule_id, False)
            logger.warning("Immune heal failed for %s (%s): %s", diagnosis.file_path, diagnosis.rule_id, e)
            return HealResult(
                pattern=diagnosis.pattern,
                rule_id=diagnosis.rule_id,
                success=False,
                message=str(e),
            )

    def scan_and_heal(self, details: list[str]) -> list[HealResult]:
        """Diagnose + heal with CytokineBreaker protection.

        For each healable finding:
        1. Check circuit breaker
        2. Snapshot test baseline
        3. Apply fix
        4. Verify test count didn't increase
        5. If worse → rollback + escalate
        """
        if self._breaker.is_open():
            logger.warning("Immune: breaker OPEN — healing suspended.")
            return []

        results: list[HealResult] = []
        for detail in details:
            if self._breaker.is_open():
                logger.warning("Immune: breaker tripped mid-batch — aborting.")
                break

            diagnosis = self.diagnose(detail)
            if not diagnosis.healable:
                continue

            baseline = self._count_test_failures()
            if baseline is None:
                logger.warning("Immune: cannot count test failures — skipping for safety.")
                continue

            result = self.heal(diagnosis)
            results.append(result)

            if not result.success:
                continue

            after = self._count_test_failures()
            if after is None:
                self._rollback_file(diagnosis.file_path)
                result.success = False
                result.message = "Rolled back: verification unavailable"
                self._heals_rolled_back += 1
                self._breaker.record_rollback()
                self._learn(diagnosis.rule_id, False)
                continue

            delta = after - baseline
            if delta > _MAX_CASCADE_FAILURES:
                logger.error(
                    "CYTOKINE: heal of '%s' in %s INCREASED failures by %d (%d → %d). ROLLING BACK.",
                    diagnosis.rule_id, diagnosis.file_path, delta, baseline, after,
                )
                self._rollback_file(diagnosis.file_path)
                result.success = False
                result.message = f"Rolled back: failures increased by {delta}"
                self._heals_rolled_back += 1
                self._heals_succeeded -= 1
                self._breaker.record_rollback()
                self._learn(diagnosis.rule_id, False)
            else:
                self._breaker.record_success()
                logger.info(
                    "Immune: %s → %s VERIFIED (failures: %d → %d)",
                    diagnosis.rule_id, diagnosis.file_path, baseline, after,
                )

        return results

    def run_self_diagnostics(self) -> list[HealResult]:
        """Atomic self-diagnostic — no pytest, no full suite.

        Uses DiagnosticSense (AST-level, <1 second) to find pathogens.
        Each finding is matched to a known pathogen and healed if possible.
        This is how a real immune system works — targeted antibodies,
        not a full-body MRI every heartbeat.
        """
        from steward.senses.diagnostic_sense import diagnose_repo

        try:
            report = diagnose_repo(self._cwd)
        except Exception as e:
            logger.warning("Immune: diagnostic failed: %s", e)
            return []

        if not report.findings:
            return []

        # Convert findings to pathogen detail strings for scan_and_heal
        pathogens = [
            f"{f.kind.value} in {f.file}: {f.detail}"
            for f in report.findings
            if f.severity.value in ("critical", "warning")
        ]

        if not pathogens:
            return []

        logger.info("Immune: %d pathogens detected", len(pathogens))
        return self.scan_and_heal(pathogens)

    def stats(self) -> dict:
        return {
            "available": self._available,
            "heals_attempted": self._heals_attempted,
            "heals_succeeded": self._heals_succeeded,
            "heals_rolled_back": self._heals_rolled_back,
            "breaker": self._breaker.stats(),
            "success_rate": (
                round(self._heals_succeeded / self._heals_attempted, 3)
                if self._heals_attempted > 0
                else 0.0
            ),
        }

    # ── Internals ────────────────────────────────────────────────────

    def _learn(self, rule_id: str | None, success: bool) -> None:
        if self._synaptic is not None and rule_id:
            self._synaptic.update(f"immune:{rule_id}", "heal", success=success)

    def _try_ast_fix(self, diagnosis: DiagnosisResult) -> tuple[bool, str, str]:
        """Try steward's own deterministic fixers as fallback."""
        from steward.healer import _FIXERS
        from steward.senses.diagnostic_sense import Finding, FindingKind, Severity

        if diagnosis.file_path is None or diagnosis.rule_id is None:
            return False, "No file or rule", ""

        # Map rule_id to FindingKind
        try:
            kind = FindingKind(diagnosis.rule_id)
        except ValueError:
            return False, f"Unknown finding kind: {diagnosis.rule_id}", ""

        fixer = _FIXERS.get(kind)
        if fixer is None:
            return False, f"No fixer for {kind.value}", ""

        finding = Finding(
            kind=kind,
            severity=Severity.WARNING,
            file=str(diagnosis.file_path),
            detail=diagnosis.pattern,
        )
        workspace = Path(self._cwd)
        changed = fixer(finding, workspace)
        if changed:
            return True, f"Fixed via {kind.value} fixer", ""
        return False, "Fixer returned no changes", ""

    def _count_test_failures(self) -> int | None:
        """Count findings via DiagnosticSense (not pytest — atomic, fast)."""
        from steward.senses.diagnostic_sense import diagnose_repo

        try:
            report = diagnose_repo(self._cwd)
            return len([f for f in report.findings if f.severity.value == "critical"])
        except Exception as e:
            logger.warning("Immune: diagnostic count failed: %s", e)
            return None

    @staticmethod
    def _rollback_file(file_path: Path | None) -> bool:
        """Surgical rollback — restore single file from git HEAD."""
        if file_path is None or not file_path.exists():
            return False
        try:
            subprocess.run(
                ["git", "checkout", "HEAD", "--", str(file_path)],
                capture_output=True, text=True, check=True, timeout=10,
            )
            logger.info("Immune: rolled back %s", file_path)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error("Immune: rollback FAILED for %s: %s", file_path, e)
            return False


# ── Pattern Matching ─────────────────────────────────────────────────

# Known pathogens — maps detail patterns to remedy rule_ids
_PATHOGEN_PATTERNS: dict[str, str] = {
    "except Exception": "silent_exception",
    "except pass": "silent_exception",
    "Any": "any_type_usage",
    "LCOM4": "god_class",
    "circular_import": "circular_import",
    "syntax_error": "syntax_error",
    "undeclared_dependency": "undeclared_dependency",
    "no_federation_descriptor": "no_federation_descriptor",
    "no_ci": "no_ci",
    "no_tests": "no_tests",
    "broken_import": "broken_import",
}


def _match_pattern(detail: str) -> str | None:
    """Match a detail string to a known pathogen rule_id."""
    detail_lower = detail.lower()
    for pattern, rule_id in _PATHOGEN_PATTERNS.items():
        if pattern.lower() in detail_lower:
            return rule_id
    return None


def _extract_file_path(detail: str) -> Path | None:
    """Extract .py file path from detail string."""
    import re

    match = re.search(r"([\w/.]+\.py)", detail)
    if match:
        candidate = Path(match.group(1))
        if candidate.exists():
            return candidate
    return None
