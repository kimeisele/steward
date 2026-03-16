"""Tests for the API server interface.

Tests the FastAPI app creation and endpoints without requiring
fastapi/uvicorn to be installed (uses conditional imports).
"""

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
        assert "/agent-internet/semantic/capabilities" in routes
        assert "/agent-internet/semantic/contracts" in routes
        assert "/agent-internet/semantic/call" in routes
        assert "/agent-internet/repo-graph/capabilities" in routes
        assert "/agent-internet/repo-graph/contracts" in routes
        assert "/agent-internet/repo-graph" in routes
        assert "/agent-internet/repo-graph/neighbors" in routes
        assert "/agent-internet/repo-graph/context" in routes
        assert "/agent-internet/public-graph" in routes
        assert "/agent-internet/search-index" in routes
        assert "/agent-internet/search" in routes
        assert "/agent-internet/federated-index" in routes
        assert "/agent-internet/federated-search" in routes


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


@pytest.mark.skipif(not _has_fastapi(), reason="fastapi not installed")
class TestAgentInternetProxyAPI:
    def test_agent_internet_capabilities_proxy(self, monkeypatch):
        from fastapi.testclient import TestClient

        from steward.interfaces.api import create_app

        monkeypatch.setenv("STEWARD_AGENT_INTERNET_BASE_URL", "https://agent.example")
        monkeypatch.setenv("STEWARD_AGENT_INTERNET_TOKEN", "secret")
        monkeypatch.delenv("STEWARD_API_TOKEN", raising=False)
        monkeypatch.setattr(
            "steward.interfaces.agent_internet.fetch_semantic_capabilities",
            lambda: {"kind": "agent_web_semantic_capability_manifest", "capabilities": []},
        )

        client = TestClient(create_app())
        response = client.get("/agent-internet/semantic/capabilities")

        assert response.status_code == 200
        assert response.json()["kind"] == "agent_web_semantic_capability_manifest"

    def test_agent_internet_contracts_proxy(self, monkeypatch):
        from fastapi.testclient import TestClient

        from steward.interfaces.api import create_app

        monkeypatch.setenv("STEWARD_AGENT_INTERNET_BASE_URL", "https://agent.example")
        monkeypatch.setenv("STEWARD_AGENT_INTERNET_TOKEN", "secret")
        monkeypatch.delenv("STEWARD_API_TOKEN", raising=False)

        def _fake_fetch(*, capability_id=None, contract_id=None, version=None):
            return {
                "contract_id": contract_id or "semantic_expand.v1",
                "capability_id": capability_id or "semantic_expand",
                "version": version or 1,
            }

        monkeypatch.setattr("steward.interfaces.agent_internet.fetch_semantic_contracts", _fake_fetch)

        client = TestClient(create_app())
        response = client.get("/agent-internet/semantic/contracts?contract_id=semantic_expand.v1")

        assert response.status_code == 200
        assert response.json()["contract_id"] == "semantic_expand.v1"

    def test_agent_internet_call_proxy(self, monkeypatch):
        from fastapi.testclient import TestClient

        from steward.interfaces.api import create_app

        monkeypatch.setenv("STEWARD_AGENT_INTERNET_BASE_URL", "https://agent.example")
        monkeypatch.setenv("STEWARD_AGENT_INTERNET_TOKEN", "secret")
        monkeypatch.delenv("STEWARD_API_TOKEN", raising=False)

        def _fake_invoke(*, capability_id=None, contract_id=None, version=None, input_payload=None):
            return {
                "kind": "steward_agent_internet_semantic_proxy_invocation",
                "selector": {
                    "capability_id": capability_id or "semantic_expand",
                    "contract_id": contract_id or "semantic_expand.v1",
                    "version": version or 1,
                },
                "request": {"query": {"q": input_payload.get("query")}},
                "response": {"agent_web_semantic_expand": {"raw_query": input_payload.get("query")}},
            }

        monkeypatch.setattr("steward.interfaces.agent_internet.invoke_semantic_http", _fake_invoke)

        client = TestClient(create_app())
        response = client.post(
            "/agent-internet/semantic/call",
            json={"capability_id": "semantic_expand", "input_payload": {"query": "bazaar"}},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["kind"] == "steward_agent_internet_semantic_proxy_invocation"
        assert payload["response"]["agent_web_semantic_expand"]["raw_query"] == "bazaar"

    def test_agent_internet_repo_graph_proxy(self, monkeypatch):
        from fastapi.testclient import TestClient

        from steward.interfaces.api import create_app

        monkeypatch.setenv("STEWARD_AGENT_INTERNET_BASE_URL", "https://agent.example")
        monkeypatch.setenv("STEWARD_AGENT_INTERNET_TOKEN", "secret")
        monkeypatch.delenv("STEWARD_API_TOKEN", raising=False)
        monkeypatch.setattr(
            "steward.interfaces.agent_internet.fetch_repo_graph_snapshot",
            lambda **kwargs: {"kind": "agent_web_repo_graph_snapshot", "recorded_root": kwargs["root"]},
        )

        client = TestClient(create_app())
        response = client.get("/agent-internet/repo-graph?root=/repo&limit=2")

        assert response.status_code == 200
        assert response.json()["kind"] == "agent_web_repo_graph_snapshot"

    def test_agent_internet_public_graph_and_search_proxy(self, monkeypatch):
        from fastapi.testclient import TestClient

        from steward.interfaces.api import create_app

        monkeypatch.setenv("STEWARD_AGENT_INTERNET_BASE_URL", "https://agent.example")
        monkeypatch.setenv("STEWARD_AGENT_INTERNET_TOKEN", "secret")
        monkeypatch.delenv("STEWARD_API_TOKEN", raising=False)
        monkeypatch.setattr(
            "steward.interfaces.agent_internet.fetch_public_graph", lambda **kwargs: {"kind": "agent_web_public_graph"}
        )
        monkeypatch.setattr(
            "steward.interfaces.agent_internet.search_index",
            lambda **kwargs: {"kind": "agent_web_search_results", "results": [{"title": kwargs["query"]}]},
        )

        client = TestClient(create_app())
        public_graph = client.get("/agent-internet/public-graph?root=/repo")
        search = client.get("/agent-internet/search?root=/repo&q=marketplace&limit=3")

        assert public_graph.status_code == 200
        assert public_graph.json()["kind"] == "agent_web_public_graph"
        assert search.status_code == 200
        assert search.json()["results"][0]["title"] == "marketplace"

    def test_agent_internet_federated_search_proxy(self, monkeypatch):
        from fastapi.testclient import TestClient

        from steward.interfaces.api import create_app

        monkeypatch.setenv("STEWARD_AGENT_INTERNET_BASE_URL", "https://agent.example")
        monkeypatch.setenv("STEWARD_AGENT_INTERNET_TOKEN", "secret")
        monkeypatch.delenv("STEWARD_API_TOKEN", raising=False)
        monkeypatch.setattr(
            "steward.interfaces.agent_internet.search_federated_index",
            lambda **kwargs: {"results": [{"source_city_id": "city-b"}]},
        )

        client = TestClient(create_app())
        response = client.get("/agent-internet/federated-search?q=bazaar&limit=2")

        assert response.status_code == 200
        assert response.json()["results"][0]["source_city_id"] == "city-b"
