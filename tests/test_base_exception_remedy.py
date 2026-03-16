"""Tests for BaseExceptionNarrowingRemedy — CST-based precision fix."""

from __future__ import annotations

import libcst as cst

from steward.remedies.base_exception_narrowing import (
    BaseExceptionNarrowingRemedy,
    _has_raise,
)


def _transform(code: str) -> tuple[str, bool, bool]:
    """Run the remedy on code, return (result, violation_found, applied)."""
    tree = cst.parse_module(code)
    remedy = BaseExceptionNarrowingRemedy()
    new_tree = tree.visit(remedy)
    return new_tree.code, remedy.violation_found, remedy.applied


# ── _has_raise helper ──────────────────────────────────────────────────


class TestHasRaise:
    def test_bare_raise(self):
        body = cst.parse_statement("try:\n    pass\nexcept:\n    raise\n")
        # Get the handler body
        handler = body.handlers[0]
        assert _has_raise(handler.body)

    def test_raise_with_value(self):
        body = cst.parse_statement("try:\n    pass\nexcept:\n    raise ValueError('x')\n")
        handler = body.handlers[0]
        assert _has_raise(handler.body)

    def test_no_raise(self):
        body = cst.parse_statement("try:\n    pass\nexcept:\n    pass\n")
        handler = body.handlers[0]
        assert not _has_raise(handler.body)

    def test_pass_body(self):
        body = cst.parse_statement("try:\n    pass\nexcept:\n    x = 1\n")
        handler = body.handlers[0]
        assert not _has_raise(handler.body)


# ── Transforms dangerous patterns ────────────────────────────────────


class TestDangerousPatterns:
    def test_bare_base_exception_pass(self):
        code = "try:\n    do_stuff()\nexcept BaseException:\n    pass\n"
        result, found, applied = _transform(code)
        assert found
        assert applied
        assert "except Exception:" in result
        assert "BaseException" not in result

    def test_base_exception_with_as(self):
        code = "try:\n    x()\nexcept BaseException as e:\n    log(e)\n"
        result, found, applied = _transform(code)
        assert applied
        assert "except Exception as e:" in result

    def test_base_exception_with_body(self):
        code = "try:\n    work()\nexcept BaseException:\n    cleanup()\n    log_error()\n"
        result, found, applied = _transform(code)
        assert applied
        assert "except Exception:" in result
        # Body preserved
        assert "cleanup()" in result
        assert "log_error()" in result

    def test_multiple_handlers(self):
        code = "try:\n    x()\nexcept ValueError:\n    pass\nexcept BaseException:\n    swallow()\n"
        result, found, applied = _transform(code)
        assert applied
        assert "except ValueError:" in result  # Untouched
        assert "except Exception:" in result  # Narrowed
        assert "BaseException" not in result


# ── Leaves safe patterns alone ────────────────────────────────────────


class TestSafePatterns:
    def test_base_exception_with_reraise(self):
        code = "try:\n    x()\nexcept BaseException:\n    cleanup()\n    raise\n"
        result, found, applied = _transform(code)
        assert not found
        assert not applied
        assert "BaseException" in result  # Unchanged

    def test_base_exception_with_raise_new(self):
        code = "try:\n    x()\nexcept BaseException as e:\n    raise RuntimeError() from e\n"
        result, found, applied = _transform(code)
        assert not applied
        assert "BaseException" in result

    def test_except_exception_untouched(self):
        code = "try:\n    x()\nexcept Exception:\n    pass\n"
        result, found, applied = _transform(code)
        assert not found
        assert not applied
        assert result == code

    def test_specific_exceptions_untouched(self):
        code = "try:\n    x()\nexcept ValueError:\n    pass\n"
        result, found, applied = _transform(code)
        assert not found
        assert result == code

    def test_bare_except_untouched(self):
        """Bare except is handled by PreciseSilentExceptRemedy, not this one."""
        code = "try:\n    x()\nexcept:\n    pass\n"
        result, found, applied = _transform(code)
        assert not found
        assert result == code

    def test_tuple_exceptions_untouched(self):
        code = "try:\n    x()\nexcept (ValueError, TypeError):\n    pass\n"
        result, found, applied = _transform(code)
        assert not found
        assert result == code


# ── Rule ID ──────────────────────────────────────────────────────────


class TestRuleId:
    def test_rule_id(self):
        remedy = BaseExceptionNarrowingRemedy()
        assert remedy.rule_id == "steward_base_exception_catch"

    def test_requirements_empty(self):
        remedy = BaseExceptionNarrowingRemedy()
        assert remedy.requirements == []
