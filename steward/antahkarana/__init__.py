"""
Antahkarana — The Inner Instrument (4 Internal Elements).

Sankhya Categories 1-4 (ANTAHKARANA):
    1. MANAS  — Mind: perceives and classifies (cognition)
    2. BUDDHI — Intelligence: discriminates and decides (decision)
    3. AHANKARA — Ego: agent identity (→ steward.agent.StewardAgent)
    4. CITTA  — Consciousness: stores impressions (awareness)

Plus Tanmatra #9:
    9. GANDHA — Smell: detects patterns (detect)

Buddhi (element 2) is the DRIVER of the chariot. It orchestrates
the others but doesn't do their work:
    - Manas perceives → delivers ManasPerception
    - Chitta stores → delivers impression history
    - Gandha detects → delivers Detection results
    - Buddhi discriminates → makes BuddhiDirective / BuddhiVerdict

This decomposition follows BG 13.6-7 (Kshetra elements).
"""

from steward.antahkarana.chitta import (
    PHASE_COMPLETE,
    PHASE_EXECUTE,
    PHASE_ORIENT,
    PHASE_VERIFY,
    Chitta,
    ExecutionPhase,
    Impression,
)
from steward.antahkarana.gandha import Detection, VerdictAction, detect_patterns
from steward.antahkarana.manas import Manas, ManasPerception

__all__ = [
    "Manas",
    "ManasPerception",
    "Chitta",
    "Impression",
    "ExecutionPhase",
    "VerdictAction",
    "PHASE_ORIENT",
    "PHASE_EXECUTE",
    "PHASE_VERIFY",
    "PHASE_COMPLETE",
    "Detection",
    "detect_patterns",
]
