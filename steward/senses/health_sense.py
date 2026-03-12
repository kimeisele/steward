"""
GHRANA — The Nose (Health Sense).

Smells code entropy and staleness. Detects:
- Oversized files (complexity smell)
- Stale files (not recently modified)
- Configuration health
- Dependency staleness

Tanmatra: GANDHA (smell — detecting corruption and decay)
Mahabhuta: PRTHVI (earth — the solid base of the codebase)

SB 3.26.51: "From earth, the sense of smell was generated..."
Code health IS smell — rot, decay, and freshness are perceptible.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from vibe_core.mahamantra.protocols._sense import (
    Jnanendriya,
    SensePerception,
    SenseProtocol,
    Tanmatra,
)

logger = logging.getLogger("STEWARD.SENSE.HEALTH")

# Thresholds
_LARGE_FILE_BYTES = 50_000  # 50KB — suspiciously large for a source file
_STALE_DAYS = 90  # 90 days without modification
_MAX_SCAN = 500  # max files to scan


class HealthSense:
    """GHRANA — perceives code health through file metrics.

    Implements SenseProtocol. All perception is deterministic
    (file stat + size checks). Zero LLM.
    """

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = Path(cwd) if cwd else Path.cwd()

    @property
    def jnanendriya(self) -> Jnanendriya:
        return Jnanendriya.GHRANA

    @property
    def tanmatra(self) -> Tanmatra:
        return Tanmatra.GANDHA

    @property
    def is_active(self) -> bool:
        return self._cwd.is_dir()

    def perceive(self) -> SensePerception:
        """Perceive codebase health — file sizes, staleness, config."""
        now = time.time()
        stale_threshold = now - (_STALE_DAYS * 86400)

        source_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".rb"}
        skip_dirs = {
            "__pycache__",
            ".git",
            "node_modules",
            ".venv",
            "venv",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
        }

        large_files: list[str] = []
        stale_files: list[str] = []
        total_size = 0
        file_count = 0
        scanned = 0

        for f in self._cwd.rglob("*"):
            if scanned >= _MAX_SCAN:
                break
            if not f.is_file():
                continue
            if f.suffix not in source_exts:
                continue

            parts = f.relative_to(self._cwd).parts
            if any(p in skip_dirs or p.startswith(".") for p in parts):
                continue

            scanned += 1
            try:
                stat = f.stat()
                file_count += 1
                total_size += stat.st_size

                rel = str(f.relative_to(self._cwd))
                if stat.st_size > _LARGE_FILE_BYTES:
                    large_files.append(rel)
                if stat.st_mtime < stale_threshold:
                    stale_files.append(rel)
            except OSError:
                continue

        # Check for common health indicators
        has_lockfile = (self._cwd / "poetry.lock").exists() or (self._cwd / "package-lock.json").exists()
        has_gitignore = (self._cwd / ".gitignore").exists()
        has_readme = (self._cwd / "README.md").exists() or (self._cwd / "readme.md").exists()

        # Determine quality
        quality = "sattva"
        intensity = 0.2

        smell_count = len(large_files) + (len(stale_files) // 5)  # stale weighs less
        if smell_count > 5:
            quality = "tamas"
            intensity = min(0.8, 0.3 + smell_count * 0.05)
        elif smell_count > 0:
            quality = "rajas"
            intensity = min(0.5, 0.2 + smell_count * 0.03)

        if not has_gitignore:
            intensity += 0.1
        if not has_readme:
            intensity += 0.05

        return SensePerception(
            sense=Jnanendriya.GHRANA,
            tanmatra=Tanmatra.GANDHA,
            data={
                "file_count": file_count,
                "total_size_kb": total_size // 1024,
                "large_files": large_files[:10],
                "large_file_count": len(large_files),
                "stale_files": stale_files[:10],
                "stale_file_count": len(stale_files),
                "has_lockfile": has_lockfile,
                "has_gitignore": has_gitignore,
                "has_readme": has_readme,
                "smell_count": smell_count,
            },
            intensity=intensity,
            quality=quality,
        )

    def get_pain_level(self) -> float:
        """Pain = large files + stale code + missing config."""
        perception = self.perceive()
        if perception.quality == "tamas":
            return perception.intensity
        return perception.intensity * 0.2
