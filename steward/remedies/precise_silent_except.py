"""
Precise Silent Exception Remedy — fixes ONLY truly dangerous silent catches.

Unlike the upstream silent_failure remedy which blindly converts ALL
`except X: pass` to `logger.exception()`, this remedy classifies
exception types and only transforms genuinely dangerous patterns:

DANGEROUS (will transform):
  except Exception: pass          → logger.debug(...)
  except BaseException: pass      → logger.debug(...)
  except: pass                    → logger.debug(...)

INTENTIONAL (will NOT transform):
  except KeyboardInterrupt: pass  — normal user interruption
  except ImportError: pass        — optional dependency pattern
  except (ValueError, TypeError): pass  — expected parse/type failures
  except asyncio.CancelledError: pass   — normal cancellation
  except FileNotFoundError: pass  — expected missing file
  except OSError: pass            — expected OS-level failures
  except subprocess.*: pass       — expected subprocess failures
  except json.JSONDecodeError: pass — expected parse failures

Uses logger.debug() not logger.exception() — broad catches that were
silent are likely silent for a reason (high-frequency, non-critical).
Full stack traces (exception()) would spam logs.
"""

from __future__ import annotations

import libcst as cst
import libcst.matchers as m
from vibe_core.mahamantra.dharma.kapila.remedies.base import CSTRemedy

# Exception types that are INTENTIONALLY caught and silenced.
# These represent expected control flow, not hidden bugs.
_INTENTIONAL_EXCEPTIONS = frozenset({
    # Flow control
    "KeyboardInterrupt",
    "SystemExit",
    "GeneratorExit",
    "StopIteration",
    "StopAsyncIteration",
    "CancelledError",
    # Expected failures
    "ImportError",
    "ModuleNotFoundError",
    "FileNotFoundError",
    "NotADirectoryError",
    "PermissionError",
    "ProcessLookupError",
    "ConnectionError",
    "TimeoutError",
    # Parse/type (expected in try-parse patterns)
    "ValueError",
    "TypeError",
    "KeyError",
    "IndexError",
    "AttributeError",
    "UnicodeDecodeError",
    "UnicodeEncodeError",
    # OS/subprocess
    "OSError",
    "IOError",
    "CalledProcessError",
    "TimeoutExpired",
    "JSONDecodeError",
})

# Qualified names (module.Exception) that are intentional
_INTENTIONAL_QUALIFIED = frozenset({
    "asyncio.CancelledError",
    "asyncio.TimeoutError",
    "subprocess.CalledProcessError",
    "subprocess.TimeoutExpired",
    "json.JSONDecodeError",
    "signal.ItimerError",
})


def _extract_exception_names(exc_type: cst.BaseExpression | None) -> list[str]:
    """Extract all exception type names from a handler's type annotation."""
    if exc_type is None:
        return []  # bare except:

    if isinstance(exc_type, cst.Name):
        return [exc_type.value]

    if isinstance(exc_type, cst.Attribute):
        # e.g., asyncio.CancelledError, subprocess.TimeoutExpired
        parts = []
        node = exc_type
        while isinstance(node, cst.Attribute):
            parts.append(node.attr.value)
            node = node.value
        if isinstance(node, cst.Name):
            parts.append(node.value)
        parts.reverse()
        return [".".join(parts)]

    if isinstance(exc_type, cst.Tuple):
        # e.g., (ValueError, TypeError)
        names = []
        for el in exc_type.elements:
            names.extend(_extract_exception_names(el.value))
        return names

    return []


def _is_dangerous_catch(exc_type: cst.BaseExpression | None) -> bool:
    """Determine if this exception handler is a truly dangerous silent catch.

    Returns True for: bare except, except Exception, except BaseException
    Returns False for: specific intentional exceptions (ValueError, etc.)
    """
    if exc_type is None:
        # bare `except:` — always dangerous
        return True

    names = _extract_exception_names(exc_type)

    if not names:
        # Could not parse — be conservative, don't transform
        return False

    # If ANY name is Exception/BaseException, it's dangerous
    dangerous_bases = {"Exception", "BaseException"}
    for name in names:
        if name in dangerous_bases:
            return True

    # If ALL names are intentional, it's safe
    for name in names:
        short = name.rsplit(".", 1)[-1]  # asyncio.CancelledError → CancelledError
        if short not in _INTENTIONAL_EXCEPTIONS and name not in _INTENTIONAL_QUALIFIED:
            # Unknown exception type caught silently — flag it
            return True

    return False


class PreciseSilentExceptRemedy(CSTRemedy):
    """Transforms only truly dangerous silent exception handlers.

    Replaces bare `pass` in dangerous catches with `logger.debug()`.
    Leaves intentional silent catches (ImportError, ValueError, etc.) alone.
    """

    @property
    def rule_id(self) -> str:
        return "steward_silent_except"

    @property
    def requirements(self) -> list[str]:
        return ["logging"]

    def __init__(self) -> None:
        super().__init__()
        self._has_logger = False
        self._logger_name = "logger"

    def visit_Assign(self, node: cst.Assign) -> None:
        if len(node.targets) != 1:
            return
        target = node.targets[0].target
        if isinstance(target, cst.Name) and m.matches(
            node.value,
            m.Call(func=m.Attribute(value=m.Name("logging"), attr=m.Name("getLogger"))),
        ):
            self._logger_name = target.value
            self._has_logger = True

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if isinstance(node.module, cst.Name) and node.module.value == "logging":
            self._has_logger = True

    def visit_Import(self, node: cst.Import) -> None:
        if isinstance(node.names, cst.ImportStar):
            return
        for name in node.names:
            if isinstance(name, cst.ImportAlias):
                if isinstance(name.name, cst.Name) and name.name.value == "logging":
                    self._has_logger = True

    def leave_ExceptHandler(
        self, original_node: cst.ExceptHandler, updated_node: cst.ExceptHandler
    ) -> cst.ExceptHandler:
        # Only transform if body is bare `pass`
        if not self._is_bare_pass(updated_node):
            return updated_node

        # Only transform DANGEROUS catches
        if not _is_dangerous_catch(updated_node.type):
            return updated_node

        self.violation_found = True

        # Don't transform if no logger available
        if not self._has_logger:
            return updated_node

        self.applied = True

        # Ensure we have an exception variable
        exc_name = "_exc"
        if updated_node.name and isinstance(updated_node.name, cst.AsName):
            if isinstance(updated_node.name.name, cst.Name):
                exc_name = updated_node.name.name.value

        new_name = cst.AsName(
            name=cst.Name(exc_name),
            whitespace_before_as=cst.SimpleWhitespace(" "),
            whitespace_after_as=cst.SimpleWhitespace(" "),
        )

        # Build: logger.debug("Caught %s: %s", type(_exc).__name__, _exc)
        log_stmt = cst.parse_statement(
            f'{self._logger_name}.debug("Caught %%s: %%s", type({exc_name}).__name__, {exc_name})'
        )

        changes: dict[str, object] = {
            "name": new_name,
            "body": cst.IndentedBlock(body=[log_stmt]),
        }

        # Bare `except:` has type=None — LibCST requires type when name is set.
        # Convert to `except Exception as _exc:`.
        if updated_node.type is None:
            changes["type"] = cst.Name("Exception")
            changes["whitespace_after_except"] = cst.SimpleWhitespace(" ")

        return updated_node.with_changes(**changes)

    @staticmethod
    def _is_bare_pass(handler: cst.ExceptHandler) -> bool:
        """Check if handler body is just `pass` or `...`."""
        body = handler.body
        if not isinstance(body, cst.IndentedBlock):
            return False
        stmts = body.body
        if len(stmts) != 1:
            return False
        stmt = stmts[0]
        if isinstance(stmt, cst.SimpleStatementLine):
            if len(stmt.body) == 1:
                inner = stmt.body[0]
                if isinstance(inner, cst.Pass):
                    return True
                if isinstance(inner, cst.Expr) and isinstance(inner.value, cst.Ellipsis):
                    return True
        return False
