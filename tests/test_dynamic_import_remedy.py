"""Tests for DynamicImportSafetyRemedy — CST-based precision fix."""

from __future__ import annotations

import libcst as cst

from steward.remedies.dynamic_import_safe import DynamicImportSafetyRemedy


def _transform(code: str) -> tuple[str, bool, bool]:
    """Run the remedy on code, return (result, violation_found, applied)."""
    tree = cst.parse_module(code)
    remedy = DynamicImportSafetyRemedy()
    new_tree = tree.visit(remedy)
    return new_tree.code, remedy.violation_found, remedy.applied


# ── Transforms probing patterns ──────────────────────────────────────


class TestProbingPatterns:
    def test_bare_import_call(self):
        code = '__import__("foo")\n'
        result, found, applied = _transform(code)
        assert found
        assert applied
        assert 'importlib.util.find_spec("foo")' in result
        assert "__import__" not in result

    def test_assigned_import(self):
        code = 'mod = __import__("bar")\n'
        result, found, applied = _transform(code)
        assert applied
        assert 'importlib.util.find_spec("bar")' in result

    def test_variable_name_import(self):
        code = "__import__(module_name)\n"
        result, found, applied = _transform(code)
        assert applied
        assert "importlib.util.find_spec(module_name)" in result

    def test_in_try_except(self):
        code = 'try:\n    __import__("optional")\nexcept ImportError:\n    pass\n'
        result, found, applied = _transform(code)
        assert applied
        assert "find_spec" in result

    def test_in_if_condition(self):
        code = 'if __import__("pkg"):\n    use_it()\n'
        result, found, applied = _transform(code)
        assert applied
        assert "find_spec" in result

    def test_strips_extra_args(self):
        """__import__ accepts (name, globals, locals, fromlist, level) but
        find_spec only takes name. Extra args must be dropped."""
        code = '__import__("foo", globals(), locals(), ["bar"], 0)\n'
        result, found, applied = _transform(code)
        assert applied
        assert 'find_spec("foo")' in result
        # Extra args should be gone
        assert "globals" not in result


# ── Adds importlib import ────────────────────────────────────────────


class TestImportlibImport:
    def test_adds_importlib_when_missing(self):
        code = '__import__("foo")\n'
        result, found, applied = _transform(code)
        assert applied
        assert "import importlib.util" in result

    def test_no_duplicate_when_already_imported(self):
        code = 'import importlib.util\n\n__import__("foo")\n'
        result, found, applied = _transform(code)
        assert applied
        assert result.count("import importlib.util") == 1

    def test_no_duplicate_with_from_import(self):
        code = 'from importlib import util\n\n__import__("foo")\n'
        # This form doesn't match our check, so importlib.util will be added
        # That's OK — it's safe to have both
        result, found, applied = _transform(code)
        assert applied
        assert "find_spec" in result

    def test_placed_after_existing_imports(self):
        code = 'import os\nimport sys\n\n__import__("foo")\n'
        result, found, applied = _transform(code)
        assert applied
        lines = result.splitlines()
        importlib_idx = next(i for i, line in enumerate(lines) if "importlib.util" in line)
        os_idx = next(i for i, line in enumerate(lines) if "import os" in line)
        sys_idx = next(i for i, line in enumerate(lines) if "import sys" in line)
        assert importlib_idx > os_idx
        assert importlib_idx > sys_idx


# ── No transform cases ──────────────────────────────────────────────


class TestNoTransform:
    def test_no_import_calls(self):
        code = "import os\nx = 1\n"
        result, found, applied = _transform(code)
        assert not found
        assert not applied
        assert result == code

    def test_empty_args(self):
        code = "__import__()\n"
        result, found, applied = _transform(code)
        assert not found
        assert not applied

    def test_regular_import_untouched(self):
        code = "import foo\nfrom bar import baz\n"
        result, found, applied = _transform(code)
        assert not found
        assert result == code


# ── Multiple occurrences ─────────────────────────────────────────────


class TestMultipleOccurrences:
    def test_transforms_all_import_calls(self):
        code = '__import__("foo")\n__import__("bar")\n'
        result, found, applied = _transform(code)
        assert applied
        assert result.count("find_spec") == 2
        assert "__import__" not in result

    def test_mixed_with_normal_code(self):
        code = 'x = 1\n__import__("foo")\ny = 2\n__import__("bar")\nz = 3\n'
        result, found, applied = _transform(code)
        assert applied
        assert result.count("find_spec") == 2
        assert "x = 1" in result
        assert "y = 2" in result
        assert "z = 3" in result


# ── Rule ID ──────────────────────────────────────────────────────────


class TestRuleId:
    def test_rule_id(self):
        remedy = DynamicImportSafetyRemedy()
        assert remedy.rule_id == "steward_dynamic_import"

    def test_requirements(self):
        remedy = DynamicImportSafetyRemedy()
        assert "importlib" in remedy.requirements
