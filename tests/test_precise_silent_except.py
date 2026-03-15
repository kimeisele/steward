"""Tests for PreciseSilentExceptRemedy — precision over aggression.

Verifies the remedy correctly classifies exception types:
- DANGEROUS (transforms): bare except, except Exception, except BaseException
- INTENTIONAL (leaves alone): ImportError, ValueError, KeyboardInterrupt, etc.
"""

from __future__ import annotations

import libcst as cst

from steward.remedies.precise_silent_except import (
    PreciseSilentExceptRemedy,
    _extract_exception_names,
    _is_dangerous_catch,
)

# ── Helper ──────────────────────────────────────────────────────────────

def _transform(code: str) -> tuple[str, bool, bool]:
    """Run the remedy on code, return (result, violation_found, applied)."""
    tree = cst.parse_module(code)
    remedy = PreciseSilentExceptRemedy()
    new_tree = tree.visit(remedy)
    return new_tree.code, remedy.violation_found, remedy.applied


# ── Classification tests ────────────────────────────────────────────────

class TestExceptionNameExtraction:
    """_extract_exception_names parses CST nodes correctly."""

    def test_simple_name(self):
        node = cst.parse_expression("ValueError")
        assert _extract_exception_names(node) == ["ValueError"]

    def test_qualified_name(self):
        node = cst.parse_expression("asyncio.CancelledError")
        assert _extract_exception_names(node) == ["asyncio.CancelledError"]

    def test_tuple_of_names(self):
        node = cst.parse_expression("(ValueError, TypeError)")
        names = _extract_exception_names(node)
        assert "ValueError" in names
        assert "TypeError" in names

    def test_none_returns_empty(self):
        assert _extract_exception_names(None) == []

    def test_mixed_tuple(self):
        node = cst.parse_expression("(ImportError, subprocess.CalledProcessError)")
        names = _extract_exception_names(node)
        assert "ImportError" in names
        assert "subprocess.CalledProcessError" in names


class TestIsDangerousCatch:
    """_is_dangerous_catch correctly classifies exception types."""

    def test_bare_except_is_dangerous(self):
        assert _is_dangerous_catch(None) is True

    def test_exception_is_dangerous(self):
        node = cst.parse_expression("Exception")
        assert _is_dangerous_catch(node) is True

    def test_base_exception_is_dangerous(self):
        node = cst.parse_expression("BaseException")
        assert _is_dangerous_catch(node) is True

    def test_value_error_is_intentional(self):
        node = cst.parse_expression("ValueError")
        assert _is_dangerous_catch(node) is False

    def test_import_error_is_intentional(self):
        node = cst.parse_expression("ImportError")
        assert _is_dangerous_catch(node) is False

    def test_keyboard_interrupt_is_intentional(self):
        node = cst.parse_expression("KeyboardInterrupt")
        assert _is_dangerous_catch(node) is False

    def test_os_error_is_intentional(self):
        node = cst.parse_expression("OSError")
        assert _is_dangerous_catch(node) is False

    def test_asyncio_cancelled_is_intentional(self):
        node = cst.parse_expression("asyncio.CancelledError")
        assert _is_dangerous_catch(node) is False

    def test_subprocess_called_process_error_is_intentional(self):
        node = cst.parse_expression("subprocess.CalledProcessError")
        assert _is_dangerous_catch(node) is False

    def test_json_decode_error_is_intentional(self):
        node = cst.parse_expression("json.JSONDecodeError")
        assert _is_dangerous_catch(node) is False

    def test_tuple_all_intentional_is_safe(self):
        node = cst.parse_expression("(ValueError, TypeError)")
        assert _is_dangerous_catch(node) is False

    def test_tuple_with_exception_is_dangerous(self):
        node = cst.parse_expression("(ValueError, Exception)")
        assert _is_dangerous_catch(node) is True

    def test_tuple_subprocess_and_file(self):
        node = cst.parse_expression("(subprocess.TimeoutExpired, FileNotFoundError)")
        assert _is_dangerous_catch(node) is False

    def test_cancelled_error_bare_is_intentional(self):
        node = cst.parse_expression("CancelledError")
        assert _is_dangerous_catch(node) is False

    def test_stop_iteration_is_intentional(self):
        node = cst.parse_expression("StopIteration")
        assert _is_dangerous_catch(node) is False

    def test_index_error_is_intentional(self):
        node = cst.parse_expression("IndexError")
        assert _is_dangerous_catch(node) is False

    def test_attribute_error_is_intentional(self):
        node = cst.parse_expression("AttributeError")
        assert _is_dangerous_catch(node) is False


# ── Transformation tests ────────────────────────────────────────────────

class TestTransformDangerous:
    """Dangerous catches ARE transformed."""

    def test_bare_except_with_logging(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    x()\n"
            "except:\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is True
        assert applied is True
        assert "logger.debug" in result
        assert "pass" not in result.split("except")[1]

    def test_except_exception_with_logging(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    x()\n"
            "except Exception:\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is True
        assert applied is True
        assert "logger.debug" in result

    def test_except_base_exception_with_logging(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    x()\n"
            "except BaseException:\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is True
        assert applied is True
        assert "logger.debug" in result

    def test_preserves_existing_exception_name(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    x()\n"
            "except Exception as e:\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert applied is True
        # Should preserve the 'e' variable name
        assert "as e:" in result or "as e :" in result

    def test_violation_without_logger(self):
        """Dangerous catch without logging: violation found but NOT applied."""
        code = (
            "try:\n"
            "    x()\n"
            "except Exception:\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is True
        assert applied is False
        # Code should be unchanged
        assert "pass" in result


class TestLeaveIntentional:
    """Intentional catches are NOT transformed."""

    def test_import_error_untouched(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    import optional\n"
            "except ImportError:\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False
        assert "pass" in result

    def test_value_error_untouched(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    int(x)\n"
            "except ValueError:\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False

    def test_keyboard_interrupt_untouched(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    wait()\n"
            "except KeyboardInterrupt:\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False

    def test_os_error_untouched(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    os.remove(f)\n"
            "except OSError:\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False

    def test_asyncio_cancelled_untouched(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    await task\n"
            "except asyncio.CancelledError:\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False

    def test_subprocess_tuple_untouched(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    run()\n"
            "except (subprocess.TimeoutExpired, FileNotFoundError):\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False

    def test_json_decode_error_untouched(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    json.loads(s)\n"
            "except json.JSONDecodeError:\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False

    def test_multi_intentional_untouched(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    parse(s)\n"
            "except (json.JSONDecodeError, OSError):\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False


class TestNonPassBodies:
    """Handlers with bodies other than bare pass are NOT touched."""

    def test_handler_with_logging_untouched(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    x()\n"
            "except Exception as e:\n"
            "    logger.error(e)\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False

    def test_handler_with_return_untouched(self):
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    x()\n"
            "except Exception:\n"
            "    return None\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False

    def test_handler_with_ellipsis_is_bare(self):
        """Ellipsis (...) is treated as bare pass."""
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    x()\n"
            "except Exception:\n"
            "    ...\n"
        )
        result, violation, applied = _transform(code)
        assert violation is True
        assert applied is True


class TestRealWorldPatterns:
    """Test against patterns actually found in the steward codebase."""

    def test_steward_think_tool_pattern(self):
        """The except Exception: pass in think.py should be flagged."""
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "if chitta is not None:\n"
            "    try:\n"
            "        from steward.antahkarana.gandha import detect_patterns\n"
            "        detection = detect_patterns(chitta.impressions)\n"
            "    except Exception:\n"
            "        pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is True
        assert applied is True
        assert "logger.debug" in result

    def test_steward_context_bridge_subprocess_pattern(self):
        """(subprocess.TimeoutExpired, FileNotFoundError) should NOT be flagged."""
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    result = subprocess.run(cmd, timeout=10)\n"
            "except (subprocess.TimeoutExpired, FileNotFoundError):\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False

    def test_steward_agent_import_error_pattern(self):
        """except ImportError: pass should NOT be flagged."""
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    from steward.optional import module\n"
            "except ImportError:\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False

    def test_steward_telegram_cancelled_pattern(self):
        """except asyncio.CancelledError: pass should NOT be flagged."""
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    await self._poll()\n"
            "except asyncio.CancelledError:\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False

    def test_steward_briefing_json_os_pattern(self):
        """(json.JSONDecodeError, OSError) should NOT be flagged."""
        code = (
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "try:\n"
            "    data = json.loads(path.read_text())\n"
            "except (json.JSONDecodeError, OSError):\n"
            "    pass\n"
        )
        result, violation, applied = _transform(code)
        assert violation is False
        assert applied is False


class TestRemedyProperties:
    """Verify remedy metadata."""

    def test_rule_id(self):
        remedy = PreciseSilentExceptRemedy()
        assert remedy.rule_id == "steward_silent_except"

    def test_requirements(self):
        remedy = PreciseSilentExceptRemedy()
        assert "logging" in remedy.requirements

    def test_initial_state(self):
        remedy = PreciseSilentExceptRemedy()
        assert remedy.applied is False
        assert remedy.violation_found is False
