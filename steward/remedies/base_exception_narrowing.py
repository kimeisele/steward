"""
Base Exception Narrowing Remedy — CST-based surgical fix.

Replaces `except BaseException` with `except Exception` when the handler
does NOT re-raise. Handlers that re-raise are intentional cleanup patterns
(e.g., try/finally equivalents) and are left untouched.

Why this matters:
  except BaseException catches KeyboardInterrupt, SystemExit, and
  GeneratorExit — making the process unkillable via Ctrl+C and preventing
  graceful shutdown. This is almost never intentional.

Uses LibCST (not regex, not AST) for precise, tree-aware transformation.
"""

from __future__ import annotations

import libcst as cst
import libcst.matchers as m

from vibe_core.mahamantra.dharma.kapila.remedies.base import CSTRemedy


def _has_raise(body: cst.IndentedBlock) -> bool:
    """Check if a handler body contains any Raise statement (including re-raise)."""

    class _RaiseFinder(cst.CSTVisitor):
        found = False

        def visit_Raise(self, node: cst.Raise) -> None:
            self.found = True

    finder = _RaiseFinder()
    body.visit(finder)  # type: ignore[arg-type]
    return finder.found


class BaseExceptionNarrowingRemedy(CSTRemedy):
    """Narrows `except BaseException` to `except Exception` when safe.

    Safe = handler does NOT re-raise. If handler re-raises, the broad
    catch is intentional (cleanup pattern) and we leave it alone.
    """

    @property
    def rule_id(self) -> str:
        return "steward_base_exception_catch"

    @property
    def requirements(self) -> list[str]:
        return []

    def leave_ExceptHandler(
        self, original_node: cst.ExceptHandler, updated_node: cst.ExceptHandler
    ) -> cst.ExceptHandler:
        # Only target `except BaseException`
        if not isinstance(updated_node.type, cst.Name):
            return updated_node
        if updated_node.type.value != "BaseException":
            return updated_node

        # If handler re-raises, it's intentional cleanup — leave it
        if isinstance(updated_node.body, cst.IndentedBlock) and _has_raise(updated_node.body):
            return updated_node

        self.violation_found = True
        self.applied = True

        # Replace BaseException with Exception
        return updated_node.with_changes(
            type=cst.Name("Exception"),
        )
