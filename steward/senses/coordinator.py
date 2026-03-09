"""
SenseCoordinator — Manas for environmental perception.

Coordinates all 5 Jnanendriyas and produces AggregatePerception.
Implements ManasProtocol from steward-protocol.

This is the environmental Manas — it perceives the codebase/project.
The existing Manas (antahkarana.manas) perceives USER INTENT.
Both are complementary aspects of the mind:
    - antahkarana.manas: "WHAT does the user want?" (intent classification)
    - senses.coordinator: "WHAT does the environment look like?" (environmental perception)

Both feed into Buddhi for discrimination.
"""

from __future__ import annotations

import logging
from pathlib import Path

from steward.senses.code_sense import CodeSense
from steward.senses.gh import get_gh_client
from steward.senses.git_sense import GitSense
from steward.senses.health_sense import HealthSense
from steward.senses.project_sense import ProjectSense
from steward.senses.testing_sense import TestingSense
from vibe_core.mahamantra.protocols._sense import (
    AggregatePerception,
    Jnanendriya,
    ManasProtocol,
    SensePerception,
    SenseProtocol,
)

logger = logging.getLogger("STEWARD.SENSES")


class SenseCoordinator:
    """Coordinates all 5 Jnanendriyas — the environmental Manas.

    Boots all senses at init, provides perceive_all() for Buddhi,
    and formats perception data for system prompt injection.

    Implements ManasProtocol from steward-protocol.
    """

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = cwd or str(Path.cwd())
        self._senses: dict[Jnanendriya, SenseProtocol] = {}
        self._last_perception: AggregatePerception | None = None
        self._boot()

    @property
    def senses(self) -> dict[Jnanendriya, SenseProtocol]:
        return dict(self._senses)

    def register_sense(self, sense: SenseProtocol) -> None:
        """Register a sense implementation."""
        self._senses[sense.jnanendriya] = sense
        logger.debug("Registered sense: %s", sense.jnanendriya.value)

    def perceive_all(self) -> AggregatePerception:
        """Collect perception from all active senses.

        This is the main method — polls all senses and combines
        their input into AggregatePerception.
        """
        aggregate = AggregatePerception()

        for jnanendriya, sense in self._senses.items():
            if not sense.is_active:
                logger.debug("Sense %s inactive, skipping", jnanendriya.value)
                continue
            try:
                perception = sense.perceive()
                aggregate.add_perception(perception)
            except Exception as e:
                logger.warning("Sense %s failed: %s", jnanendriya.value, e)

        self._last_perception = aggregate

        if aggregate.perceptions:
            logger.info(
                "Perception complete: %d senses, pain=%.2f, dominant=%s",
                len(aggregate.perceptions),
                aggregate.total_pain,
                aggregate.dominant_sense.value if aggregate.dominant_sense else "none",
            )

        return aggregate

    def get_total_pain(self) -> float:
        """Get aggregate pain level from all senses."""
        if self._last_perception is None:
            self.perceive_all()
        return self._last_perception.total_pain if self._last_perception else 0.0

    def format_for_prompt(self) -> str:
        """Format sense perceptions for system prompt injection.

        Produces a concise structured summary of what the senses perceive.
        Only includes relevant data — no noise.
        """
        if self._last_perception is None:
            self.perceive_all()

        if not self._last_perception or not self._last_perception.perceptions:
            return ""

        parts = ["\n\n## Environment Perception"]

        for jnanendriya, perception in self._last_perception.perceptions.items():
            section = self._format_perception(jnanendriya, perception)
            if section:
                parts.append(section)

        # Pain summary (drives urgency)
        pain = self._last_perception.total_pain
        if pain > 0.3:
            dominant = self._last_perception.dominant_sense
            parts.append(
                f"\nAttention: pain={pain:.1f}"
                + (f", dominant={dominant.value}" if dominant else "")
            )

        return "\n".join(parts)

    def boot_summary(self) -> dict[str, dict]:
        """Get boot summaries from all senses (for logging/diagnostics)."""
        summaries: dict[str, dict] = {}
        for jnanendriya, sense in self._senses.items():
            perception = sense.perceive() if sense.is_active else None
            summaries[jnanendriya.value] = {
                "active": sense.is_active,
                "pain": sense.get_pain_level() if sense.is_active else 0.0,
                "quality": perception.quality if perception else "unknown",
            }
        return summaries

    # The 5 Jnanendriyas are Vedic Tattvas — architectural constants, not plugins.
    # BG 3.26.47-52: Sabda, Sparsa, Rupa, Rasa, Gandha — exactly 5, no more, no fewer.
    _REQUIRED_SENSES = frozenset({
        Jnanendriya.SROTRA,   # Ear (hears git)
        Jnanendriya.TVAK,     # Skin (feels project structure)
        Jnanendriya.CAKSU,    # Eye (sees code)
        Jnanendriya.JIHVA,    # Tongue (tastes tests)
        Jnanendriya.GHRANA,   # Nose (smells health)
    })

    def _boot(self) -> None:
        """Boot all 5 senses — fails hard if any sense is missing."""
        gh = get_gh_client()
        senses: list[SenseProtocol] = [
            GitSense(cwd=self._cwd, gh_client=gh),
            ProjectSense(cwd=self._cwd),
            CodeSense(cwd=self._cwd),
            TestingSense(cwd=self._cwd),
            HealthSense(cwd=self._cwd),
        ]
        for sense in senses:
            self.register_sense(sense)

        # HARD INVARIANT: exactly 5 senses, all present
        registered = frozenset(self._senses.keys())
        missing = self._REQUIRED_SENSES - registered
        if missing:
            raise RuntimeError(f"Sense boot failure — missing Jnanendriyas: {missing}")
        if len(self._senses) != 5:
            raise RuntimeError(f"Sense boot failure — expected 5, got {len(self._senses)}")

        logger.info("Senses booted: %d active", sum(1 for s in self._senses.values() if s.is_active))

    @staticmethod
    def _format_perception(jnanendriya: Jnanendriya, perception: SensePerception) -> str:
        """Format a single perception for prompt injection."""
        data = perception.data

        if jnanendriya == Jnanendriya.SROTRA:
            # Git sense — compact: branch + dirty + remote
            if not data.get("is_git"):
                return ""
            branch = data.get("branch", "?")
            dirty = data.get("dirty_count", 0)
            line = f"Git: {branch}, {dirty} dirty"
            if data.get("perceives") == "local+remote":
                ci = data.get("ci_conclusion", "?")
                prs = data.get("open_prs", 0)
                line += f", ci={ci}, {prs} open PRs"
            return line

        if jnanendriya == Jnanendriya.TVAK:
            # Project sense — compact: language only
            lang = data.get("primary_language", "unknown")
            return f"Project: {lang}"

        if jnanendriya == Jnanendriya.CAKSU:
            # Code sense — compact: counts only, errors if any
            files = data.get("python_files", 0)
            classes = data.get("total_classes", 0)
            functions = data.get("total_functions", 0)
            errors = data.get("syntax_errors", [])
            line = f"Code: {files} files, {classes} cls, {functions} fn"
            if errors:
                line += f", {len(errors)} syntax errors"
            return line

        if jnanendriya == Jnanendriya.JIHVA:
            # Test sense
            framework = data.get("framework", "unknown")
            count = data.get("test_files", 0)
            result = data.get("last_result", "unknown")
            parts = [f"Tests: {framework}, {count} files, last={result}"]
            return "\n".join(parts)

        if jnanendriya == Jnanendriya.GHRANA:
            # Health sense
            file_count = data.get("file_count", 0)
            smells = data.get("smell_count", 0)
            large = data.get("large_file_count", 0)
            stale = data.get("stale_file_count", 0)
            if smells > 0:
                return f"Health: {file_count} source files, {smells} smells ({large} large, {stale} stale)"
            return f"Health: {file_count} source files, clean"

        return ""

