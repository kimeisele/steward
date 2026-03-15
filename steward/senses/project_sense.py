"""
TVAK — The Skin (Project Sense).

Feels the project structure through the filesystem. Touches:
- Language and framework detection
- Key directories and config files
- Dependency state
- Project size and shape

Tanmatra: SPARSA (touch — feeling the filesystem structure)
Mahabhuta: VAYU (air — filesystem is the medium the agent breathes)

SB 3.26.48: "From the ether, the air was generated with the quality of touch..."
The filesystem IS touch — the agent feels the project through it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from vibe_core.mahamantra.protocols._sense import (
    Jnanendriya,
    SensePerception,
    Tanmatra,
)

logger = logging.getLogger("STEWARD.SENSE.PROJECT")

# Config files that identify project types
_LANGUAGE_MARKERS: dict[str, list[str]] = {
    "python": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile"],
    "javascript": ["package.json"],
    "typescript": ["tsconfig.json"],
    "rust": ["Cargo.toml"],
    "go": ["go.mod"],
    "java": ["pom.xml", "build.gradle"],
    "ruby": ["Gemfile"],
    "elixir": ["mix.exs"],
}

_FRAMEWORK_MARKERS: dict[str, list[str]] = {
    "django": ["manage.py"],
    "flask": ["app.py", "wsgi.py"],
    "fastapi": ["main.py"],
    "nextjs": ["next.config.js", "next.config.mjs", "next.config.ts"],
    "react": ["src/App.tsx", "src/App.jsx", "src/App.js"],
    "vue": ["vue.config.js"],
}

# Key directories to check
_KEY_DIRS = ["src", "lib", "tests", "test", "docs", "scripts", "config", ".github", ".steward"]


class ProjectSense:
    """TVAK — perceives project structure through the filesystem.

    Implements SenseProtocol. All perception is deterministic
    (filesystem stat calls). Zero LLM.
    """

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = Path(cwd) if cwd else Path.cwd()

    @property
    def jnanendriya(self) -> Jnanendriya:
        return Jnanendriya.TVAK

    @property
    def tanmatra(self) -> Tanmatra:
        return Tanmatra.SPARSA

    @property
    def is_active(self) -> bool:
        return self._cwd.is_dir()

    def perceive(self) -> SensePerception:
        """Perceive project structure — language, framework, key dirs."""
        languages = self._detect_languages()
        frameworks = self._detect_frameworks()
        key_dirs = self._detect_key_dirs()
        config_files = self._detect_config_files()

        # Count source files (top 2 levels only, fast)
        py_count = len(list(self._cwd.glob("**/*.py")))
        js_count = len(list(self._cwd.glob("**/*.js"))) + len(list(self._cwd.glob("**/*.ts")))

        primary_language = languages[0] if languages else "unknown"

        # Determine quality
        quality = "sattva"
        intensity = 0.3  # baseline

        if not languages:
            quality = "tamas"
            intensity = 0.6  # unknown project type is painful

        if not key_dirs:
            intensity += 0.1  # flat project structure

        return SensePerception(
            sense=Jnanendriya.TVAK,
            tanmatra=Tanmatra.SPARSA,
            data={
                "languages": languages,
                "primary_language": primary_language,
                "frameworks": frameworks,
                "key_dirs": key_dirs,
                "config_files": config_files,
                "python_files": py_count,
                "js_ts_files": js_count,
                "has_tests": "tests" in key_dirs or "test" in key_dirs,
                "has_ci": ".github" in key_dirs,
            },
            intensity=intensity,
            quality=quality,
        )

    def get_pain_level(self) -> float:
        """Pain = unknown project type, missing structure."""
        perception = self.perceive()
        if perception.quality == "tamas":
            return perception.intensity
        return 0.0

    def _detect_languages(self) -> list[str]:
        """Detect project languages from config file markers."""
        found: list[str] = []
        for lang, markers in _LANGUAGE_MARKERS.items():
            for marker in markers:
                if (self._cwd / marker).exists():
                    if lang not in found:
                        found.append(lang)
                    break
        return found

    def _detect_frameworks(self) -> list[str]:
        """Detect frameworks from file markers."""
        found: list[str] = []
        for framework, markers in _FRAMEWORK_MARKERS.items():
            for marker in markers:
                if (self._cwd / marker).exists():
                    if framework not in found:
                        found.append(framework)
                    break
        return found

    def _detect_key_dirs(self) -> list[str]:
        """Detect which key directories exist."""
        return [d for d in _KEY_DIRS if (self._cwd / d).is_dir()]

    def _detect_config_files(self) -> list[str]:
        """Find all config/project files in root."""
        config_patterns = ["*.toml", "*.yaml", "*.yml", "*.json", "*.cfg", "*.ini"]
        found: list[str] = []
        for pattern in config_patterns:
            for f in self._cwd.glob(pattern):
                if f.is_file() and not f.name.startswith("."):
                    found.append(f.name)
        return sorted(found)[:20]  # cap at 20
