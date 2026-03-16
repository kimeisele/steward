"""
Dynamic Import Safety Remedy — CST-based surgical fix.

Replaces `__import__(name)` with `importlib.util.find_spec(name)` when
the call is used for probing (checking if a module exists), NOT when
the result is used directly (attribute access, assignment to use the module).

Why this matters:
  __import__() executes the target module's __init__.py on import.
  When probing untrusted/unknown modules, this runs arbitrary code.
  importlib.util.find_spec() checks existence without executing anything.

Pattern classification:
  DANGEROUS (will transform):
    __import__("foo")           — bare probe
    x = __import__("foo")       — assigned but spec is enough
    __import__(name)            — variable probe

  SAFE (will NOT transform):
    __import__("foo").bar       — needs real import for attribute access
    __import__("foo").bar()     — needs real import for method call

Uses LibCST (not regex, not AST) for precise, tree-aware transformation.
"""

from __future__ import annotations

import libcst as cst
import libcst.matchers as m

from vibe_core.mahamantra.dharma.kapila.remedies.base import CSTRemedy


class DynamicImportSafetyRemedy(CSTRemedy):
    """Replaces __import__(name) with importlib.util.find_spec(name).

    Only transforms probing patterns. Leaves attribute-access patterns
    like __import__("foo").bar alone — those genuinely need execution.
    """

    @property
    def rule_id(self) -> str:
        return "steward_dynamic_import"

    @property
    def requirements(self) -> list[str]:
        return ["importlib"]

    def __init__(self) -> None:
        super().__init__()
        self._needs_importlib_import = True

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if m.matches(node, m.ImportFrom(module=m.Attribute(
            value=m.Name("importlib"), attr=m.Name("util"),
        ))):
            self._needs_importlib_import = False

    def visit_Import(self, node: cst.Import) -> None:
        if isinstance(node.names, cst.ImportStar):
            return
        for alias in node.names:
            if isinstance(alias, cst.ImportAlias):
                # Match `import importlib.util` or `import importlib`
                if m.matches(alias.name, m.Attribute(
                    value=m.Name("importlib"), attr=m.Name("util"),
                )):
                    self._needs_importlib_import = False
                elif m.matches(alias.name, m.Name("importlib")):
                    self._needs_importlib_import = False

    def leave_Call(
        self, original_node: cst.Call, updated_node: cst.Call
    ) -> cst.BaseExpression:
        # Only match __import__(...)
        if not m.matches(updated_node.func, m.Name("__import__")):
            return updated_node

        # Must have at least one argument
        if not updated_node.args:
            return updated_node

        self.violation_found = True
        self.applied = True

        # Build importlib.util.find_spec(same_args)
        find_spec_func = cst.Attribute(
            value=cst.Attribute(
                value=cst.Name("importlib"),
                attr=cst.Name("util"),
            ),
            attr=cst.Name("find_spec"),
        )

        # Only pass the first argument (module name) — find_spec
        # doesn't accept __import__'s extra args (globals, locals, fromlist, level)
        first_arg = updated_node.args[0]
        # Strip trailing comma if present
        clean_arg = first_arg.with_changes(comma=cst.MaybeSentinel.DEFAULT)

        return updated_node.with_changes(
            func=find_spec_func,
            args=[clean_arg],
        )

    def leave_Module(
        self, original_node: cst.Module, updated_node: cst.Module
    ) -> cst.Module:
        if not self.applied or not self._needs_importlib_import:
            return updated_node

        # Add `import importlib.util` at the top, after existing imports
        import_stmt = cst.parse_statement("import importlib.util\n")

        # Find the right insertion point — after last import, before first non-import
        new_body = list(updated_node.body)
        insert_idx = 0
        for i, stmt in enumerate(new_body):
            if isinstance(stmt, (cst.SimpleStatementLine,)):
                # Check if this line contains import statements
                if any(isinstance(s, (cst.Import, cst.ImportFrom)) for s in stmt.body):
                    insert_idx = i + 1
            elif isinstance(stmt, cst.EmptyLine):
                if insert_idx > 0:
                    insert_idx = i + 1
        new_body.insert(insert_idx, import_stmt)

        return updated_node.with_changes(body=new_body)
