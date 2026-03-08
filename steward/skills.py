"""
SkillRegistry — Dynamic capability loading for Steward.

Skills are reusable knowledge patterns stored as markdown files in
.steward/skills/. Each skill tells the agent HOW to do something.

Unlike static tools, skills are:
- Contextually loaded (matched by keyword relevance)
- Learnable (agent can create new skills from experience)
- Composable (skills can reference other skills)

Skill format (.steward/skills/deploy-to-pypi.md):

    # Deploy to PyPI
    trigger: publish, release, pypi, deploy package
    ---
    Steps to publish a Python package to PyPI:
    1. Bump version in pyproject.toml and __init__.py
    2. Run tests: pytest tests/ -x -q
    3. Build: python -m build
    4. Upload: twine upload dist/*

The `trigger` line contains keywords that activate this skill.
Everything after `---` is the skill content injected into context.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("STEWARD.SKILLS")

_SKILLS_DIR = ".steward/skills"
_MAX_SKILL_SIZE = 4000  # Max chars per skill (context budget)
_MAX_INJECTED = 3  # Max skills injected per turn


@dataclass(frozen=True)
class Skill:
    """A loaded skill definition."""

    name: str
    triggers: list[str]
    content: str
    source_path: str


@dataclass
class SkillRegistry:
    """Loads and matches skills from .steward/skills/ directory.

    Skills are markdown files with a trigger line and content body.
    The registry matches task text against skill triggers to find
    relevant skills, then injects them into the system prompt.
    """

    _skills: list[Skill] = field(default_factory=list)
    _cwd: str = ""

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = cwd or str(Path.cwd())
        self._skills = []
        self._load_skills()

    def _load_skills(self) -> None:
        """Load all skills from .steward/skills/ directory."""
        skills_dir = Path(self._cwd) / _SKILLS_DIR
        if not skills_dir.is_dir():
            return

        for path in sorted(skills_dir.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8").strip()
                if not text:
                    continue

                skill = self._parse_skill(text, str(path))
                if skill:
                    self._skills.append(skill)
                    logger.debug("Loaded skill: %s (%d triggers)", skill.name, len(skill.triggers))

            except OSError as e:
                logger.warning("Failed to read skill %s: %s", path, e)

        if self._skills:
            logger.info("Loaded %d skills from %s", len(self._skills), skills_dir)

    @staticmethod
    def _parse_skill(text: str, source_path: str) -> Skill | None:
        """Parse a skill markdown file into a Skill object.

        Expected format:
            # Skill Name
            trigger: keyword1, keyword2, keyword3
            ---
            Content body here...
        """
        lines = text.split("\n")

        # Extract name from first heading
        name = ""
        trigger_line = ""
        separator_idx = -1

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("# ") and not name:
                name = stripped[2:].strip()
            elif stripped.lower().startswith("trigger:"):
                trigger_line = stripped[len("trigger:") :].strip()
            elif stripped == "---":
                separator_idx = i
                break

        if not name:
            name = Path(source_path).stem.replace("-", " ").replace("_", " ").title()

        if separator_idx < 0:
            # No separator — entire content is the skill body
            content = text
        else:
            content = "\n".join(lines[separator_idx + 1 :]).strip()

        if not content:
            return None

        # Parse triggers
        triggers: list[str] = []
        if trigger_line:
            triggers = [t.strip().lower() for t in trigger_line.split(",") if t.strip()]

        # Also add words from the name as triggers
        name_words = [w.lower() for w in re.split(r"[\s\-_]+", name) if len(w) > 2]
        triggers.extend(name_words)

        # Deduplicate
        triggers = list(dict.fromkeys(triggers))

        # Truncate content if too large
        if len(content) > _MAX_SKILL_SIZE:
            content = content[:_MAX_SKILL_SIZE] + "\n[... truncated]"

        return Skill(name=name, triggers=triggers, content=content, source_path=source_path)

    def match(self, task: str) -> list[Skill]:
        """Find skills relevant to a task description.

        Scores each skill by trigger keyword overlap with the task text.
        Returns the top matches (up to _MAX_INJECTED).
        """
        if not self._skills:
            return []

        task_lower = task.lower()
        task_words = set(re.split(r"\W+", task_lower))

        scored: list[tuple[int, Skill]] = []
        for skill in self._skills:
            score = 0
            for trigger in skill.triggers:
                # Exact substring match in task text (highest weight)
                if trigger in task_lower:
                    score += 3
                # Word overlap
                trigger_words = set(trigger.split())
                overlap = task_words & trigger_words
                score += len(overlap)

            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:_MAX_INJECTED]]

    def format_for_prompt(self, skills: list[Skill]) -> str:
        """Format matched skills for injection into system prompt."""
        if not skills:
            return ""

        parts = ["\n## Relevant Skills"]
        for skill in skills:
            parts.append(f"\n### {skill.name}")
            parts.append(skill.content)

        return "\n".join(parts)

    def create_skill(self, name: str, triggers: list[str], content: str) -> Skill | None:
        """Create a new skill file from agent experience.

        Writes to .steward/skills/<name>.md and registers it.
        Returns the created Skill or None on failure.
        """
        skills_dir = Path(self._cwd) / _SKILLS_DIR
        skills_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize filename
        filename = re.sub(r"[^\w\-]", "-", name.lower().strip())
        filename = re.sub(r"-+", "-", filename).strip("-")
        if not filename:
            return None

        path = skills_dir / f"{filename}.md"

        trigger_str = ", ".join(triggers)
        text = f"# {name}\ntrigger: {trigger_str}\n---\n{content}\n"

        try:
            path.write_text(text, encoding="utf-8")
            skill = Skill(
                name=name,
                triggers=[t.lower() for t in triggers],
                content=content,
                source_path=str(path),
            )
            self._skills.append(skill)
            logger.info("Created skill: %s at %s", name, path)
            return skill
        except OSError as e:
            logger.warning("Failed to create skill %s: %s", name, e)
            return None

    @property
    def skills(self) -> list[Skill]:
        """All loaded skills."""
        return list(self._skills)

    def __len__(self) -> int:
        return len(self._skills)
