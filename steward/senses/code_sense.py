"""
CAKSU — The Eye (Code Sense).

Sees code structure through module analysis. Observes:
- Python module layout (packages, modules, __init__.py)
- Import graph health (missing imports, circular deps)
- Code shape (class/function counts, file sizes)

Tanmatra: RUPA (form — the visible structure of code)
Mahabhuta: TEJAS (fire — computational analysis)

SB 3.26.49: "From the fire, the sense of sight was generated..."
Code structure IS visible form — the agent sees it through analysis.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from vibe_core.mahamantra.protocols._sense import (
    Jnanendriya,
    SensePerception,
    SenseProtocol,
    Tanmatra,
)

logger = logging.getLogger("STEWARD.SENSE.CODE")

# Max files to analyze (prevent slowness on huge repos)
_MAX_FILES = 200


class CodeSense:
    """CAKSU — perceives code structure through module analysis.

    Implements SenseProtocol. All perception is deterministic
    (AST parsing + file system). Zero LLM.
    """

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = Path(cwd) if cwd else Path.cwd()

    @property
    def jnanendriya(self) -> Jnanendriya:
        return Jnanendriya.CAKSU

    @property
    def tanmatra(self) -> Tanmatra:
        return Tanmatra.RUPA

    @property
    def is_active(self) -> bool:
        return self._cwd.is_dir()

    def perceive(self) -> SensePerception:
        """Perceive code structure — modules, classes, functions, imports."""
        py_files = sorted(self._cwd.rglob("*.py"))[:_MAX_FILES]

        packages: list[str] = []
        total_classes = 0
        total_functions = 0
        total_lines = 0
        import_errors: list[str] = []
        large_files: list[str] = []

        for f in py_files:
            # Skip hidden dirs, __pycache__, .venv, node_modules
            parts = f.relative_to(self._cwd).parts
            if any(p.startswith(".") or p == "__pycache__" or p in ("venv", ".venv", "node_modules") for p in parts):
                continue

            # Detect packages
            if f.name == "__init__.py":
                pkg = str(f.parent.relative_to(self._cwd))
                if pkg != "." and pkg not in packages:
                    packages.append(pkg)

            # Quick AST analysis
            try:
                source = f.read_text(encoding="utf-8", errors="replace")
                lines = source.count("\n") + 1
                total_lines += lines

                if lines > 500:
                    large_files.append(str(f.relative_to(self._cwd)))

                tree = ast.parse(source, filename=str(f))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        total_classes += 1
                    elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                        total_functions += 1

            except SyntaxError:
                import_errors.append(str(f.relative_to(self._cwd)))
            except (OSError, UnicodeDecodeError):
                continue

        # Determine quality
        quality = "sattva"
        intensity = 0.3

        if import_errors:
            quality = "tamas" if len(import_errors) > 3 else "rajas"
            intensity += min(0.4, len(import_errors) * 0.1)

        if large_files:
            intensity += min(0.2, len(large_files) * 0.05)

        file_count = len([f for f in py_files if not any(
            p.startswith(".") or p == "__pycache__" or p in ("venv", ".venv")
            for p in f.relative_to(self._cwd).parts
        )])

        return SensePerception(
            sense=Jnanendriya.CAKSU,
            tanmatra=Tanmatra.RUPA,
            data={
                "python_files": file_count,
                "packages": packages[:20],
                "total_classes": total_classes,
                "total_functions": total_functions,
                "total_lines": total_lines,
                "syntax_errors": import_errors[:10],
                "large_files": large_files[:10],
            },
            intensity=intensity,
            quality=quality,
        )

    def get_pain_level(self) -> float:
        """Pain = syntax errors + oversized files."""
        perception = self.perceive()
        if perception.quality == "tamas":
            return perception.intensity
        return perception.intensity * 0.2

