"""
Architectural Invariant: No `Any` in core steward code.

Tool files (steward/tools/) are exempt — the Tool ABC from
steward-protocol forces `dict[str, Any]` in override signatures.
That's the ABC's contract, not ours.

Core code uses: LLMProvider, Tool, object, JsonValue, ToolResult.
If someone adds `Any` to a core module, this test hard-fails.

Uses AST parsing — no grep babysitting, no false positives on
comments, docstrings, or variable names containing "Any".
"""

import ast
from pathlib import Path

STEWARD_PKG = Path(__file__).parent.parent / "steward"

# Tool files are exempt: Tool ABC forces dict[str, Any] in signatures.
EXEMPT_DIRS = frozenset({"tools"})


def _find_any_imports(filepath: Path) -> list[int]:
    """Return line numbers where `Any` is imported from `typing`."""
    try:
        tree = ast.parse(filepath.read_text())
    except SyntaxError:
        return []

    violations: list[int] = []
    for node in ast.walk(tree):
        # from typing import Any
        # from typing import Protocol, Any, runtime_checkable
        if isinstance(node, ast.ImportFrom) and node.module in ("typing", "typing_extensions"):
            for alias in node.names:
                if alias.name == "Any":
                    violations.append(node.lineno)
    return violations


class TestNoAnyInCoreCode:
    def test_core_modules_do_not_import_any(self):
        """Core steward modules MUST NOT import `Any` from typing.

        Allowed alternatives:
            - LLMProvider protocol   — for LLM backends
            - Tool                   — for tool instances
            - object                 — for truly unknown types
            - JsonValue              — for JSON parameter data
            - ToolResult             — for tool execution results
            - specific dataclasses   — for everything else
        """
        violations: list[str] = []

        for py_file in sorted(STEWARD_PKG.rglob("*.py")):
            rel = py_file.relative_to(STEWARD_PKG)

            # Skip exempt directories
            if any(part in EXEMPT_DIRS for part in rel.parts):
                continue

            for lineno in _find_any_imports(py_file):
                violations.append(f"  steward/{rel}:{lineno}")

        assert not violations, (
            "`Any` imported in core code (files outside steward/tools/):\n"
            + "\n".join(violations)
            + "\n\n"
            "Use LLMProvider, Tool, object, or JsonValue instead.\n"
            "Only steward/tools/*.py may use Any (Tool ABC forces it)."
        )

    def test_tool_files_only_use_any_for_abc_overrides(self):
        """Tool files should ONLY use Any for Tool ABC method signatures.

        If a tool file uses Any beyond parameters_schema, validate,
        execute signatures — that's a smell. Catch it.
        """
        tools_dir = STEWARD_PKG / "tools"
        if not tools_dir.is_dir():
            return

        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name == "__init__.py":
                continue

            source = py_file.read_text()
            tree = ast.parse(source)

            # Count how many times `Any` appears in annotations
            # (excluding the 3 ABC override signatures + parameters_schema return)
            any_annotation_count = 0
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "Any":
                    any_annotation_count += 1

            # Each tool has exactly 4 ABC signatures using Any:
            #   parameters_schema -> dict[str, Any]
            #   validate(parameters: dict[str, Any])
            #   execute(parameters: dict[str, Any]) -> ToolResult (but return has ToolResult not Any)
            # Plus the import itself.
            # Allow up to 5 occurrences (import + 3 method params + return type).
            # If there are more, someone snuck in extra Any usage.
            max_allowed = 6  # generous: import + schema + validate + execute + maybe return type + margin
            rel = py_file.relative_to(STEWARD_PKG)
            assert any_annotation_count <= max_allowed, (
                f"steward/{rel}: Too many `Any` usages ({any_annotation_count} > {max_allowed}). "
                f"Only use Any for Tool ABC override signatures."
            )
