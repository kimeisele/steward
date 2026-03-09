"""
Steward Senses — The 5 Jnanendriyas (Knowledge-Acquiring Senses).

Each sense implements SenseProtocol from steward-protocol and provides
DETERMINISTIC perception of its domain. Zero LLM. Pure infrastructure.

The 5 senses map to Kapila's Sankhya (SB 3.26.47-52):

    SROTRA (Ear)    → GitSense      — hears project history via git
    TVAK   (Skin)   → ProjectSense  — feels project structure via filesystem
    CAKSU  (Eye)    → CodeSense     — sees code structure via module analysis
    JIHVA  (Tongue) → TestingSense   — tastes code quality via test results
    GHRANA (Nose)    → HealthSense   — smells entropy via file metrics

SenseCoordinator implements ManasProtocol — coordinates all 5 senses
and produces AggregatePerception for Buddhi to discriminate on.

Usage:
    coordinator = SenseCoordinator(cwd="/project")
    perception = coordinator.perceive_all()
    pain = coordinator.get_total_pain()  # drives urgency
    prompt = coordinator.format_for_prompt()  # inject into system prompt
"""

from __future__ import annotations

from steward.senses.coordinator import SenseCoordinator
from steward.senses.gh import GhClient, get_gh_client

__all__ = ["SenseCoordinator", "GhClient", "get_gh_client"]
