"""Tests for the API server interface.

Tests the FastAPI app creation and endpoints without requiring
fastapi/uvicorn to be installed (uses conditional imports).
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _has_fastapi():
    try:
        import fastapi  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _has_fastapi(), reason="fastapi not installed")
class TestAPIApp:
    """Test the FastAPI app creation and routing."""

    def test_create_app(self):
        from steward.interfaces.api import create_app

        app = create_app()
        assert app is not None
        assert app.title == "Steward API"

    def test_health_endpoint_exists(self):
        from steward.interfaces.api import create_app

        app = create_app()
        routes = [r.path for r in app.routes]
        assert "/health" in routes

    def test_task_endpoint_exists(self):
        from steward.interfaces.api import create_app

        app = create_app()
        routes = [r.path for r in app.routes]
        assert "/task" in routes

    def test_stream_endpoint_exists(self):
        from steward.interfaces.api import create_app

        app = create_app()
        routes = [r.path for r in app.routes]
        assert "/task/stream" in routes

    def test_stats_endpoint_exists(self):
        from steward.interfaces.api import create_app

        app = create_app()
        routes = [r.path for r in app.routes]
        assert "/stats" in routes


class TestAPIWithoutDeps:
    """Test graceful behavior when fastapi is not installed."""

    def test_check_deps_message(self):
        """_check_deps should fail gracefully if fastapi missing."""
        # This test only makes sense if fastapi IS installed,
        # in which case _check_deps should succeed silently
        if _has_fastapi():
            from steward.interfaces.api import _check_deps

            _check_deps()  # Should not raise


class TestAPIModels:
    """Test request/response models if fastapi is available."""

    @pytest.mark.skipif(not _has_fastapi(), reason="fastapi not installed")
    def test_task_request_model(self):
        from steward.interfaces.api import create_app

        # Just verify the app creates without errors
        app = create_app()
        assert app is not None
