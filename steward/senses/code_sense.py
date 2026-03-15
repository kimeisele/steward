"""
CAKSU — The Eye (Code Sense).

Sees code structure through module analysis. Observes:
- Python module layout (packages, modules, __init__.py)
- Import graph health (missing imports, circular deps)
- Code shape (class/function counts, file sizes)
- LCOM4: class cohesion (connected components of method-attribute graph)

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
    Tanmatra,
)

logger = logging.getLogger("STEWARD.SENSE.CODE")

# Max files to analyze (prevent slowness on huge repos)
_MAX_FILES = 200

# Minimum methods for LCOM4 to be meaningful
_LCOM4_MIN_METHODS = 3


def _compute_lcom4(class_node: ast.ClassDef) -> int:
    """Compute LCOM4 (connected components of method-attribute graph).

    LCOM4 = 1: perfectly cohesive (all methods share attributes).
    LCOM4 > 1: class has independent responsibilities → should be split.

    Only methods with self.attr access are considered (properties included).
    Classes with fewer than _LCOM4_MIN_METHODS methods return 1 (trivially cohesive).
    """
    # Collect methods and their self.attr accesses
    # Exclude dunder methods (__init__, __repr__, etc.) — they naturally
    # touch all attributes and would falsely connect disjoint groups.
    method_attrs: dict[str, set[str]] = {}
    for node in class_node.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name
        if name.startswith("__") and name.endswith("__"):
            continue
        attrs: set[str] = set()
        # Walk method body for self.attr references
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name) and child.value.id == "self":
                attrs.add(child.attr)
        if attrs:  # Only methods that touch self.*
            method_attrs[name] = attrs

    if len(method_attrs) < _LCOM4_MIN_METHODS:
        return 1

    # Build adjacency: two methods are connected if they share ≥1 attribute
    methods = list(method_attrs.keys())
    adj: dict[str, set[str]] = {m: set() for m in methods}
    for i, m1 in enumerate(methods):
        for m2 in methods[i + 1 :]:
            if method_attrs[m1] & method_attrs[m2]:
                adj[m1].add(m2)
                adj[m2].add(m1)

    # Count connected components via BFS
    visited: set[str] = set()
    components = 0
    for m in methods:
        if m in visited:
            continue
        components += 1
        queue = [m]
        while queue:
            current = queue.pop()
            if current in visited:
                continue
            visited.add(current)
            queue.extend(adj[current] - visited)

    return components


# ── Branchless CC Dispatch ─────────────────────────────────────────
# O(1) dict lookup per AST node instead of if/elif chains.
# Extensible: add a type → add a dict entry. No code changes.
_CC_WEIGHT: dict[type, object] = {
    ast.If: 1,
    ast.IfExp: 1,
    ast.For: 1,
    ast.AsyncFor: 1,
    ast.While: 1,
    ast.ExceptHandler: 1,
    # BoolOp: weight is dynamic (len(values) - 1), handled via callable
}


def _method_complexity(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """McCabe cyclomatic complexity — branchless O(1) dispatch per node."""
    cc = 1
    for node in ast.walk(func_node):
        weight = _CC_WEIGHT.get(type(node))
        if weight is not None:
            cc += weight
        elif isinstance(node, ast.BoolOp):
            cc += len(node.values) - 1
    return cc


def _compute_wmc(class_node: ast.ClassDef) -> int:
    """Compute WMC (Weighted Methods per Class — sum of cyclomatic complexities).

    WMC = sum of McCabe CC for each non-dunder method.
    Low WMC (< ~20) = simple class (router, data holder, facade).
    High WMC (> ~20) = complex class with deep branching logic.

    Used alongside LCOM4 to distinguish routers (high LCOM4, low WMC)
    from real god-classes (high LCOM4, high WMC).
    """
    total = 0
    for node in class_node.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("__") and node.name.endswith("__"):
            continue
        total += _method_complexity(node)
    return total


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
        """Perceive code structure — modules, classes, functions, imports, cohesion."""
        py_files = sorted(self._cwd.rglob("*.py"))[:_MAX_FILES]

        packages: list[str] = []
        total_classes = 0
        total_functions = 0
        total_lines = 0
        import_errors: list[str] = []
        large_files: list[str] = []
        low_cohesion: list[dict[str, object]] = []

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
                rel_path = str(f.relative_to(self._cwd))
                # Only top-level defs — O(body) not O(all_nodes).
                # ast.walk() traverses EVERY node and times out on large files.
                for node in tree.body:
                    if isinstance(node, ast.ClassDef):
                        total_classes += 1
                        # LCOM4: only for classes with 3+ methods
                        lcom4 = _compute_lcom4(node)
                        if lcom4 > 1:
                            wmc = _compute_wmc(node)
                            low_cohesion.append(
                                {
                                    "class": node.name,
                                    "file": rel_path,
                                    "lcom4": lcom4,
                                    "wmc": wmc,
                                }
                            )
                    elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                        total_functions += 1

            except SyntaxError:
                import_errors.append(str(f.relative_to(self._cwd)))
            except (OSError, UnicodeDecodeError):
                continue

        # Sort by worst LCOM4 first
        low_cohesion.sort(key=lambda x: x["lcom4"], reverse=True)

        # Determine quality
        quality = "sattva"
        intensity = 0.3

        if import_errors:
            quality = "tamas" if len(import_errors) > 3 else "rajas"
            intensity += min(0.4, len(import_errors) * 0.1)

        if large_files:
            intensity += min(0.2, len(large_files) * 0.05)

        if low_cohesion:
            intensity += min(0.2, len(low_cohesion) * 0.03)

        file_count = len(
            [
                f
                for f in py_files
                if not any(
                    p.startswith(".") or p == "__pycache__" or p in ("venv", ".venv")
                    for p in f.relative_to(self._cwd).parts
                )
            ]
        )

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
                "low_cohesion": low_cohesion[:10],
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
