"""
Sruti — "That which is heard."

Bidirectional instruction file synthesis.

The principle: LISTEN before you SPEAK. READ before you WRITE.

Iron Dome enforces this mechanically — blocks blind writes.
Sruti does it organically — reads everything (existing instructions +
codebase perception), and produces a unified text that contains both.

Not a merge. Not a diff. Not "human section + system section."
One document that flows from having heard both voices.

This is acintya applied to configuration:
The output is simultaneously from the human AND from the system.
Neither overwrites the other because both were heard before speaking.

    sruti = Sruti(cwd="/project")
    text = sruti.synthesize()
    # → A unified instruction file reflecting both existing content
    #   and current codebase reality

The Nadi pattern: read from one channel, write to another,
but what flows through is one stream.
"""

from __future__ import annotations

import logging
from pathlib import Path

from steward.senses.coordinator import SenseCoordinator

logger = logging.getLogger("STEWARD.SRUTI")

# Candidate paths for existing instruction files (priority order)
_INSTRUCTION_CANDIDATES = [
    ".steward/instructions.md",
    "CLAUDE.md",
]

# Candidate paths for project identity / context
_CONTEXT_CANDIDATES = [
    "README.md",
    "docs/authority/charter.md",
    "pyproject.toml",
    ".steward/skills",
]


class Sruti:
    """Listen-first instruction synthesizer.

    The cycle:
        1. HEAR what was written before (existing instructions)
        2. HEAR what the codebase says (via Senses — deterministic perception)
        3. HEAR what the project declares about itself (README, charter, config)
        4. SPEAK — produce one unified instruction text

    No markers. No ownership tags. No mechanical merge.
    The output integrates because the input was fully heard.
    """

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = cwd or str(Path.cwd())
        self._root = Path(self._cwd)

    # ── 1. LISTEN ─────────────────────────────────────────────────────

    def hear_existing(self) -> str | None:
        """Hear what was already written in the instruction file.

        Returns the content as-is. No parsing, no sectioning.
        We hear the whole voice, not fragments.
        """
        for candidate in _INSTRUCTION_CANDIDATES:
            path = self._root / candidate
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8").strip()
                    if content:
                        logger.info("Heard existing instructions from %s", path)
                        return content
                except OSError as e:
                    logger.warning("Could not hear %s: %s", path, e)
        logger.info("No existing instructions found — blank canvas")
        return None

    def hear_codebase(self) -> dict[str, str]:
        """Hear what the codebase says via the 5 Senses.

        Returns structured perception data. This is deterministic —
        zero LLM, pure observation.
        """
        try:
            senses = SenseCoordinator(cwd=self._cwd)
            perception = senses.perceive_all()
            prompt_text = senses.format_for_prompt()

            # Also collect raw data for richer synthesis
            raw = {}
            for jnanendriya, p in perception.perceptions.items():
                raw[jnanendriya.value] = p.data

            return {
                "formatted": prompt_text,
                "pain": str(perception.total_pain),
                "dominant": perception.dominant_sense.value if perception.dominant_sense else "none",
                "raw": str(raw),
            }
        except Exception as e:
            logger.warning("Sense perception failed: %s", e)
            return {"formatted": "", "pain": "0", "dominant": "none", "raw": ""}

    def hear_project_identity(self) -> dict[str, str]:
        """Hear what the project says about itself.

        Reads README, charter, pyproject.toml, skill files —
        the project's own voice about what it is and how it works.
        """
        identity: dict[str, str] = {}

        # README
        readme = self._root / "README.md"
        if readme.is_file():
            try:
                identity["readme"] = readme.read_text(encoding="utf-8").strip()
            except OSError:
                pass

        # Charter
        charter = self._root / "docs" / "authority" / "charter.md"
        if charter.is_file():
            try:
                identity["charter"] = charter.read_text(encoding="utf-8").strip()
            except OSError:
                pass

        # pyproject.toml — project metadata
        pyproject = self._root / "pyproject.toml"
        if pyproject.is_file():
            try:
                identity["pyproject"] = pyproject.read_text(encoding="utf-8").strip()
            except OSError:
                pass

        # Skills — what the project knows how to do
        skills_dir = self._root / ".steward" / "skills"
        if skills_dir.is_dir():
            skill_texts = []
            for skill_file in sorted(skills_dir.glob("*.md")):
                try:
                    skill_texts.append(f"### {skill_file.stem}\n{skill_file.read_text(encoding='utf-8').strip()}")
                except OSError:
                    pass
            if skill_texts:
                identity["skills"] = "\n\n".join(skill_texts)

        return identity

    # ── 2. SPEAK ──────────────────────────────────────────────────────

    def synthesize(self) -> str:
        """Listen to everything, then speak one unified instruction text.

        This is the core act: hearing both voices (existing + codebase)
        and producing something that is neither "old" nor "new" but
        integrated.

        Without an LLM available, this produces a deterministic synthesis.
        With an LLM, it could produce truly organic prose.
        The structure is the same either way — listen first, speak second.
        """
        # HEAR
        existing = self.hear_existing()
        codebase = self.hear_codebase()
        identity = self.hear_project_identity()

        # SPEAK
        return self._compose(existing, codebase, identity)

    def _compose(
        self,
        existing: str | None,
        codebase: dict[str, str],
        identity: dict[str, str],
    ) -> str:
        """Compose the unified instruction text.

        Deterministic composition. The intelligence is in what we
        include and how we structure it — informed by what we heard.

        If existing instructions exist, they form the foundation.
        New perception data flows around and through them,
        never replacing but extending.
        """
        sections: list[str] = []

        # ── Project identity (from its own voice) ──
        project_name = self._extract_project_name(identity)
        sections.append(f"# {project_name}")
        sections.append("")

        # If there were existing instructions, they are the FIRST voice.
        # We don't put them in a "legacy" section — they ARE the document's root.
        if existing:
            # The existing content is not "old" — it's the human voice.
            # We weave codebase awareness around it, not on top of it.
            sections.append(existing)
            sections.append("")

            # Only add perception data that ISN'T already covered
            # by the existing instructions. Listen to what's already said.
            perception_additions = self._perception_additions(existing, codebase, identity)
            if perception_additions:
                sections.append(perception_additions)
        else:
            # Blank canvas — compose from pure perception
            sections.append(self._compose_fresh(codebase, identity))

        return "\n".join(sections).strip() + "\n"

    def _perception_additions(
        self,
        existing: str,
        codebase: dict[str, str],
        identity: dict[str, str],
    ) -> str:
        """Determine what the codebase perception adds that isn't already said.

        This is the acintya moment: we don't blindly append everything.
        We check what was already heard (existing content) and only
        add what's genuinely new information.
        """
        additions: list[str] = []
        existing_lower = existing.lower()

        # Test commands — add if not mentioned
        if "pytest" not in existing_lower and "test" not in existing_lower:
            additions.append("## Testing")
            additions.append("```bash")
            additions.append("python -m pytest tests/ -x -q --timeout=30")
            additions.append("```")
            additions.append("")

        # Lint commands — add if not mentioned
        if "ruff" not in existing_lower and "lint" not in existing_lower:
            additions.append("## Linting")
            additions.append("```bash")
            additions.append("ruff format --check steward/ tests/")
            additions.append("ruff check steward/ tests/ --select=E9,F63,F7,F82")
            additions.append("```")
            additions.append("")

        # Architecture — add if not mentioned
        if "sankhya" not in existing_lower and "architecture" not in existing_lower:
            charter = identity.get("charter", "")
            if charter:
                additions.append("## Architecture")
                # Extract the core identity from charter, don't dump it all
                for line in charter.split("\n"):
                    if line.startswith("- **") or line.startswith("| "):
                        additions.append(line)
                additions.append("")

        # Current codebase state — always fresh, always relevant
        formatted = codebase.get("formatted", "").strip()
        if formatted:
            additions.append(formatted)
            additions.append("")

        # Pain signal — if the codebase is hurting, say so
        pain = float(codebase.get("pain", "0"))
        if pain > 0.3:
            dominant = codebase.get("dominant", "unknown")
            additions.append(f"**Current attention needed:** pain={pain:.1f}, dominant sense: {dominant}")
            additions.append("")

        return "\n".join(additions)

    def _compose_fresh(
        self,
        codebase: dict[str, str],
        identity: dict[str, str],
    ) -> str:
        """Compose from scratch when no existing instructions exist.

        This is the blank canvas case. We speak entirely from
        what the codebase and project identity tell us.
        """
        parts: list[str] = []

        # Project description from README (first paragraph)
        readme = identity.get("readme", "")
        if readme:
            first_para = self._first_paragraph(readme)
            if first_para:
                parts.append(first_para)
                parts.append("")

        # Architecture from charter
        charter = identity.get("charter", "")
        if charter:
            parts.append("## Architecture")
            parts.append("")
            for line in charter.split("\n"):
                stripped = line.strip()
                if stripped.startswith("- **") or stripped.startswith("| "):
                    parts.append(stripped)
            parts.append("")

        # Build/Test/Lint commands from pyproject.toml
        pyproject = identity.get("pyproject", "")
        parts.append("## Development")
        parts.append("")
        parts.append("```bash")
        parts.append("# Install")
        if "steward-agent" in pyproject:
            parts.append("pip install -e '.[providers]'")
        else:
            parts.append("pip install -e .")
        parts.append("")
        parts.append("# Test")
        parts.append("python -m pytest tests/ -x -q --timeout=30")
        parts.append("")
        parts.append("# Lint")
        parts.append("ruff format --check steward/ tests/")
        parts.append("ruff check steward/ tests/ --select=E9,F63,F7,F82")
        parts.append("```")
        parts.append("")

        # Skills
        skills = identity.get("skills", "")
        if skills:
            parts.append("## Skills")
            parts.append("")
            parts.append(skills)
            parts.append("")

        # Safety invariants
        parts.append("## Invariants")
        parts.append("")
        parts.append("- Read before write (Iron Dome)")
        parts.append("- Test after change")
        parts.append("- Never commit .env, credentials, or __pycache__")
        parts.append("- Fix source code, not tests (unless test is wrong)")
        parts.append("- Use `python -m pytest` (not bare `pytest`)")
        parts.append("")

        # Live codebase state
        formatted = codebase.get("formatted", "").strip()
        if formatted:
            parts.append(formatted)
            parts.append("")

        return "\n".join(parts)

    # ── 3. WRITE (with Iron Dome respect) ─────────────────────────────

    def write(self, path: str | None = None) -> Path:
        """Synthesize and write the instruction file.

        Respects Iron Dome: we READ first (in synthesize()),
        then WRITE. The output contains what was heard.

        Returns the path written to.
        """
        content = self.synthesize()
        target = Path(path) if path else self._default_write_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        logger.info("Wrote synthesized instructions to %s (%d bytes)", target, len(content))
        return target

    def _default_write_path(self) -> Path:
        """Default output path: .steward/instructions.md"""
        return self._root / ".steward" / "instructions.md"

    # ── Helpers ───────────────────────────────────────────────────────

    def _extract_project_name(self, identity: dict[str, str]) -> str:
        """Extract project name from identity data."""
        readme = identity.get("readme", "")
        for line in readme.split("\n"):
            if line.startswith("# "):
                return line[2:].strip()
        # Fallback to directory name
        return self._root.name.capitalize()

    @staticmethod
    def _first_paragraph(text: str) -> str:
        """Extract first meaningful paragraph from markdown text."""
        lines: list[str] = []
        started = False
        for line in text.split("\n"):
            stripped = line.strip()
            # Skip headings and empty lines at start
            if not started:
                if stripped and not stripped.startswith("#") and not stripped.startswith("```"):
                    started = True
                    lines.append(stripped)
                continue
            # Stop at next heading or empty line after content
            if not stripped or stripped.startswith("#"):
                break
            lines.append(stripped)
        return " ".join(lines)
