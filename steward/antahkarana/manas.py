"""
Manas — The Mind (Perceiving Faculty).

PrakritiElement #1 — Protocol Layer: cognition
Category: ANTAHKARANA (Internal Instrument)

In Sankhya, Manas is the mind that PERCEIVES and CLASSIFIES.
It answers: "WHAT is this?" — not "SHOULD I do this?" (that's Buddhi).

Manas takes raw user input and produces a structured perception:
    - SemanticActionType (what kind of task?)
    - IntentGuna (what quality/mode?)
    - Function (BRAHMA/VISHNU/SHIVA)
    - Approach (GENESIS/DHARMA/KARMA/MOKSHA)

Uses REAL substrate primitives (zero LLM):
    - MahaBuddhi.think() — Lotus VM cognitive frame
    - MahaCompression.decode_samskara_intent() — guna from seed
"""

from __future__ import annotations

from dataclasses import dataclass

from vibe_core.mahamantra.adapters.compression import MahaCompression
from vibe_core.mahamantra.protocols.compression import IntentGuna
from vibe_core.mahamantra.substrate.buddhi import get_buddhi
from vibe_core.runtime.semantic_actions import SemanticActionType


@dataclass(frozen=True)
class ManasPerception:
    """The result of Manas perceiving a user message.

    This is what Manas delivers to Buddhi for discrimination.
    """

    action: SemanticActionType
    guna: IntentGuna
    function: str  # BRAHMA/VISHNU/SHIVA
    approach: str  # GENESIS/DHARMA/KARMA/MOKSHA


# Trinity function -> SemanticActionType affinity
# MahaBuddhi returns lowercase trinity names from seed VM
_FUNCTION_AFFINITY: dict[str, SemanticActionType] = {
    "creator": SemanticActionType.IMPLEMENT,     # Brahma
    "maintainer": SemanticActionType.MONITOR,     # Vishnu
    "destroyer": SemanticActionType.REFACTOR,     # Shiva
    "carrier": SemanticActionType.IMPLEMENT,      # agent-city trinity
    "deliverer": SemanticActionType.RESPOND,      # agent-city trinity
    "enhancer": SemanticActionType.REFACTOR,      # agent-city trinity
}

# Approach -> SemanticActionType affinity
# MahaBuddhi returns lowercase approach names from Gita phase
_APPROACH_AFFINITY: dict[str, SemanticActionType] = {
    "genesis": SemanticActionType.IMPLEMENT,
    "dharma": SemanticActionType.REVIEW,
    "karma": SemanticActionType.DEBUG,
    "moksha": SemanticActionType.RESEARCH,
}


class Manas:
    """The perceiving mind — classifies user intent.

    PrakritiElement.MANAS -> Protocol Layer: cognition

    Uses substrate cognitive primitives (zero LLM):
    - MahaCompression -> guna classification from seed
    - MahaBuddhi.think() -> cognitive frame (function/approach)
    - Maps to SemanticActionType taxonomy
    """

    def __init__(self) -> None:
        self._compression = MahaCompression()
        self._maha_buddhi = get_buddhi()

    def perceive(self, message: str) -> ManasPerception:
        """Perceive and classify a user message.

        Deterministic. Zero LLM tokens.

        1. MahaCompression -> seed -> IntentGuna
        2. MahaBuddhi.think() -> cognitive frame
        3. Map to SemanticActionType
        """
        # Step 1: Compression -> guna
        cr = self._compression.compress(message)
        guna = self._compression.decode_samskara_intent(cr.seed).guna

        # Step 2: MahaBuddhi -> cognitive frame
        cognition = self._maha_buddhi.think(message)
        function = cognition.function
        approach = cognition.approach

        # Step 3: Map to SemanticActionType
        # Priority: approach affinity > function affinity > guna default
        action = _APPROACH_AFFINITY.get(approach)
        if action is None:
            action = _FUNCTION_AFFINITY.get(function)
        if action is None:
            guna_defaults = {
                IntentGuna.SATTVA: SemanticActionType.RESEARCH,
                IntentGuna.RAJAS: SemanticActionType.IMPLEMENT,
                IntentGuna.TAMAS: SemanticActionType.DEBUG,
                IntentGuna.SUDDHA: SemanticActionType.IMPLEMENT,
            }
            action = guna_defaults.get(guna, SemanticActionType.IMPLEMENT)

        return ManasPerception(
            action=action,
            guna=guna,
            function=function,
            approach=approach,
        )
