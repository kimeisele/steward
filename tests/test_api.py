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

    def test_federation_semantic_routes_exist(self):
        from steward.interfaces.api import create_app

        app = create_app()
        routes = [r.path for r in app.routes]
        assert "/federation/semantic/capabilities" in routes
        assert "/federation/semantic/contracts" in routes
        assert "/federation/semantic/call" in routes

    def test_federation_semantic_proxy_routes(self, monkeypatch):
        from fastapi.testclient import TestClient

        monkeypatch.setattr(
            "steward.interfaces.agent_internet.fetch_semantic_capabilities",
            lambda: {"kind": "agent_web_semantic_capability_manifest", "capabilities": []},
        )
        monkeypatch.setattr(
            "steward.interfaces.agent_internet.fetch_semantic_contracts",
            lambda capability_id=None, contract_id=None, version=None: {
                "contract_id": contract_id or f"{capability_id}.v1",
                "capability_id": capability_id or "semantic_expand",
                "version": version or 1,
            },
        )
        monkeypatch.setattr(
            "steward.interfaces.agent_internet.invoke_semantic_http",
            lambda capability_id=None, contract_id=None, version=None, input_payload=None: {
                "kind": "steward_agent_internet_semantic_proxy_invocation",
                "selector": {
                    "capability_id": capability_id or "semantic_expand",
                    "contract_id": contract_id or "semantic_expand.v1",
                    "version": version or 1,
                },
                "request": {"query": {"q": input_payload["query"]}},
                "response": {"agent_web_semantic_expand": {"raw_query": input_payload["query"]}},
            },
        )

        from steward.interfaces.api import create_app

        client = TestClient(create_app())

        response = client.get("/federation/semantic/capabilities")
        assert response.status_code == 200
        assert response.json()["kind"] == "agent_web_semantic_capability_manifest"

        response = client.get("/federation/semantic/contracts", params={"contract_id": "semantic_expand.v1"})
        assert response.status_code == 200
        assert response.json()["contract_id"] == "semantic_expand.v1"

        response = client.post(
            "/federation/semantic/call",
            json={"capability_id": "semantic_expand", "input_payload": {"query": "bazaar"}},
        )
        assert response.status_code == 200
        assert response.json()["response"]["agent_web_semantic_expand"]["raw_query"] == "bazaar"


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
