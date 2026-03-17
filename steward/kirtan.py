"""
KirtanLoop — Call and Response Primitive for Autonomous Actions.

Like HebbianSynaptic is the primitive for LEARNING,
KirtanLoop is the primitive for VERIFICATION.

Every action the steward takes should have a response:
  1. CALL:     Register action with expected outcome
  2. VERIFY:   Next cycle, check if outcome was achieved
  3. CLOSE:    Success → Hebbian weight ↑
  4. RETRY:    Not yet → increment attempt, try different approach
  5. ESCALATE: Max retries → return payload for real action (GitHub Issue, not MD file)

Persisted to disk (survives CI restarts).

    Hare Krishna Hare Krishna Krishna Krishna Hare Hare
    Hare Rama   Hare Rama   Rama   Rama   Hare Hare
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("STEWARD.KIRTAN")


@dataclass
class KirtanCall:
    """A registered action awaiting response."""

    action_id: str
    target: str
    expected_outcome: str
    created_at: float
    max_retries: int = 3
    attempts: int = 0
    last_checked_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> KirtanCall:
        return cls(
            action_id=data["action_id"],
            target=data["target"],
            expected_outcome=data["expected_outcome"],
            created_at=data.get("created_at", 0.0),
            max_retries=data.get("max_retries", 3),
            attempts=data.get("attempts", 0),
            last_checked_at=data.get("last_checked_at", 0.0),
        )


@dataclass
class KirtanResult:
    """Outcome of a verify check."""

    action_id: str
    target: str
    result: str  # "closed" | "retry" | "escalate"
    attempts: int


class KirtanLoop:
    """Call and Response primitive. Like HebbianSynaptic but for actions.

    Usage:
        kirtan = KirtanLoop()

        # CALL — register an action
        kirtan.call("diagnose:agent-city", target="agent-city",
                    expected_outcome="peer_alive")

        # VERIFY — next cycle, check outcomes
        outcomes = {"diagnose:agent-city": True}  # True = outcome met
        results = kirtan.verify_all(outcomes)

        for r in results:
            if r.result == "closed":
                pass  # success, loop done
            elif r.result == "escalate":
                payload = kirtan.escalate(r.action_id)
                # CREATE GITHUB ISSUE with payload
    """

    def __init__(self, ledger_path: str = "data/federation/kirtan_ledger.json") -> None:
        self._path = Path(ledger_path)
        self._calls: dict[str, KirtanCall] = {}
        self._load()

    def call(
        self,
        action_id: str,
        target: str,
        expected_outcome: str,
        max_retries: int = 3,
    ) -> None:
        """Register a CALL — an action that expects a response."""
        if action_id in self._calls:
            return  # Already tracking this action

        self._calls[action_id] = KirtanCall(
            action_id=action_id,
            target=target,
            expected_outcome=expected_outcome,
            created_at=time.time(),
            max_retries=max_retries,
        )
        self._save()
        logger.info("KIRTAN CALL: %s → expecting %s", action_id, expected_outcome)

    def verify_all(self, outcomes: dict[str, bool]) -> list[KirtanResult]:
        """Check all open calls against provided outcomes.

        Args:
            outcomes: dict of action_id → True (outcome met) / False (not met).
                      Actions not in outcomes dict are checked but count as not met.

        Returns:
            List of KirtanResult with result = "closed" | "retry" | "escalate".
        """
        results: list[KirtanResult] = []
        to_remove: list[str] = []
        now = time.time()

        for action_id, call in list(self._calls.items()):
            met = outcomes.get(action_id, False)
            call.attempts += 1
            call.last_checked_at = now

            if met:
                # SUCCESS — loop closed
                results.append(KirtanResult(
                    action_id=action_id,
                    target=call.target,
                    result="closed",
                    attempts=call.attempts,
                ))
                to_remove.append(action_id)
                logger.info(
                    "KIRTAN CLOSED: %s after %d attempt(s)",
                    action_id, call.attempts,
                )

            elif call.attempts >= call.max_retries:
                # MAX RETRIES — escalate
                results.append(KirtanResult(
                    action_id=action_id,
                    target=call.target,
                    result="escalate",
                    attempts=call.attempts,
                ))
                to_remove.append(action_id)
                logger.warning(
                    "KIRTAN ESCALATE: %s — no response after %d attempts",
                    action_id, call.attempts,
                )

            else:
                # RETRY — still waiting
                results.append(KirtanResult(
                    action_id=action_id,
                    target=call.target,
                    result="retry",
                    attempts=call.attempts,
                ))

        for aid in to_remove:
            del self._calls[aid]

        if results:
            self._save()

        return results

    def close(self, action_id: str, success: bool = True) -> None:
        """Manually close a call (e.g. when verified through other means)."""
        if action_id in self._calls:
            call = self._calls.pop(action_id)
            self._save()
            logger.info(
                "KIRTAN CLOSE: %s (success=%s, attempts=%d)",
                action_id, success, call.attempts,
            )

    def escalate(self, action_id: str) -> dict:
        """Build escalation payload for a failed call.

        The CALLER decides what to do with this — create GitHub Issue,
        send NADI message, increase heartbeat frequency. KirtanLoop
        does not assume the escalation channel.
        """
        # The call was already removed in verify_all, but we can
        # build the payload from the action_id
        parts = action_id.split(":", 1)
        action_type = parts[0] if parts else "unknown"
        target = parts[1] if len(parts) > 1 else "unknown"

        return {
            "action_id": action_id,
            "action_type": action_type,
            "target": target,
            "message": (
                f"Kirtan loop exhausted for '{action_id}'. "
                f"Action was taken but expected outcome was never observed. "
                f"Manual intervention required."
            ),
            "labels": ["federation-health", "kirtan-escalation"],
        }

    def open_calls(self) -> list[KirtanCall]:
        """All unresolved calls."""
        return list(self._calls.values())

    def _load(self) -> None:
        """Load ledger from disk."""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            if isinstance(data, list):
                for item in data:
                    call = KirtanCall.from_dict(item)
                    self._calls[call.action_id] = call
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.warning("Kirtan ledger load failed: %s", e)

    def _save(self) -> None:
        """Persist ledger to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [call.to_dict() for call in self._calls.values()]
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(self._path)
