import json
from unittest.mock import MagicMock, patch

import pytest

from steward.interfaces.agent_internet import (
    AgentInternetProxyConfig,
    fetch_federated_index,
    fetch_public_graph,
    fetch_repo_graph_capabilities,
    fetch_repo_graph_context,
    fetch_repo_graph_neighbors,
    fetch_repo_graph_snapshot,
    fetch_search_index,
    fetch_semantic_capabilities,
    fetch_semantic_contracts,
    invoke_semantic_http,
    load_agent_internet_proxy_config,
    search_federated_index,
    search_index,
)


def _mock_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


def test_load_agent_internet_proxy_config_from_env(monkeypatch):
    monkeypatch.setenv("STEWARD_AGENT_INTERNET_BASE_URL", "https://agent.example")
    monkeypatch.setenv("STEWARD_AGENT_INTERNET_TOKEN", "secret")
    monkeypatch.setenv("STEWARD_AGENT_INTERNET_TIMEOUT_S", "7")

    config = load_agent_internet_proxy_config()

    assert config.base_url == "https://agent.example"
    assert config.bearer_token == "secret"
    assert config.timeout_s == 7


def test_load_agent_internet_proxy_config_requires_env(monkeypatch):
    monkeypatch.delenv("STEWARD_AGENT_INTERNET_BASE_URL", raising=False)
    monkeypatch.delenv("STEWARD_AGENT_INTERNET_TOKEN", raising=False)

    with pytest.raises(ValueError, match="missing_agent_internet_base_url"):
        load_agent_internet_proxy_config()


@patch("steward.interfaces.agent_internet.urllib.request.urlopen")
def test_fetch_semantic_capabilities(mock_urlopen):
    mock_urlopen.return_value = _mock_response(
        {
            "agent_web_semantic_capabilities": {
                "kind": "agent_web_semantic_capability_manifest",
                "capabilities": [
                    {"capability_id": "semantic_expand", "summary": "Expand queries", "mode": "read_only"}
                ],
            }
        }
    )
    config = AgentInternetProxyConfig(base_url="https://agent.example", bearer_token="secret", timeout_s=5)

    payload = fetch_semantic_capabilities(config)

    assert payload["kind"] == "agent_web_semantic_capability_manifest"
    req = mock_urlopen.call_args[0][0]
    assert req.get_header("Authorization") == "Bearer secret"


@patch("steward.interfaces.agent_internet.urllib.request.urlopen")
def test_fetch_semantic_contracts_by_contract_id(mock_urlopen):
    mock_urlopen.return_value = _mock_response(
        {
            "agent_web_semantic_contracts": {
                "contract_id": "semantic_expand.v1",
                "capability_id": "semantic_expand",
                "version": 1,
            }
        }
    )
    config = AgentInternetProxyConfig(base_url="https://agent.example", bearer_token="secret", timeout_s=5)

    payload = fetch_semantic_contracts(config=config, contract_id="semantic_expand.v1")

    assert payload["contract_id"] == "semantic_expand.v1"
    req = mock_urlopen.call_args[0][0]
    assert req.full_url.endswith("/v1/lotus/agent-web-semantic-contracts?contract_id=semantic_expand.v1")


@patch("steward.interfaces.agent_internet.urllib.request.urlopen")
def test_invoke_semantic_http(mock_urlopen):
    mock_urlopen.side_effect = [
        _mock_response(
            {
                "agent_web_semantic_capabilities": {
                    "standard_profile": {"profile_id": "agent_web_semantic_read_standard.v1"},
                    "capabilities": [
                        {"capability_id": "semantic_expand", "summary": "Expand queries", "mode": "read_only"}
                    ],
                }
            }
        ),
        _mock_response(
            {
                "agent_web_semantic_contracts": {
                    "contract_id": "semantic_expand.v1",
                    "capability_id": "semantic_expand",
                    "version": 1,
                    "request_schema": {
                        "required": ["query"],
                        "properties": {"query": {"type": "string", "http_name": "q"}},
                    },
                    "transport": {"http": {"path": "/v1/lotus/agent-web-semantic-expand"}},
                }
            }
        ),
        _mock_response(
            {
                "agent_web_semantic_expand": {
                    "kind": "agent_web_semantic_query_expansion",
                    "raw_query": "bazaar",
                }
            }
        ),
    ]
    config = AgentInternetProxyConfig(base_url="https://agent.example", bearer_token="secret", timeout_s=5)

    payload = invoke_semantic_http(
        config=config,
        capability_id="semantic_expand",
        input_payload={"query": "bazaar"},
    )

    assert payload["kind"] == "steward_agent_internet_semantic_proxy_invocation"
    assert payload["request"]["query"] == {"q": "bazaar"}
    assert payload["response"]["agent_web_semantic_expand"]["raw_query"] == "bazaar"


@patch("steward.interfaces.agent_internet.urllib.request.urlopen")
def test_fetch_repo_graph_snapshot(mock_urlopen):
    mock_urlopen.return_value = _mock_response(
        {"agent_web_repo_graph": {"kind": "agent_web_repo_graph_snapshot", "nodes": []}}
    )
    config = AgentInternetProxyConfig(base_url="https://agent.example", bearer_token="secret", timeout_s=5)

    payload = fetch_repo_graph_snapshot(config=config, root="/repo", node_type="agent", limit=3)

    assert payload["kind"] == "agent_web_repo_graph_snapshot"
    req = mock_urlopen.call_args[0][0]
    assert req.full_url.endswith("/v1/lotus/agent-web-repo-graph?root=%2Frepo&node_type=agent&limit=3")


@patch("steward.interfaces.agent_internet.urllib.request.urlopen")
def test_fetch_repo_graph_neighbors_and_context(mock_urlopen):
    mock_urlopen.side_effect = [
        _mock_response({"agent_web_repo_graph_neighbors": {"record": {"node_id": "module.city"}, "neighbors": []}}),
        _mock_response({"agent_web_repo_graph_context": {"concept": "governance", "context": "ctx"}}),
    ]
    config = AgentInternetProxyConfig(base_url="https://agent.example", bearer_token="secret", timeout_s=5)

    neighbors = fetch_repo_graph_neighbors(config=config, root="/repo", node_id="module.city", depth=1, limit=2)
    context = fetch_repo_graph_context(config=config, root="/repo", concept="governance")

    assert neighbors["record"]["node_id"] == "module.city"
    assert context["concept"] == "governance"


@patch("steward.interfaces.agent_internet.urllib.request.urlopen")
def test_fetch_repo_graph_capabilities(mock_urlopen):
    mock_urlopen.return_value = _mock_response(
        {"agent_web_repo_graph_capabilities": {"capabilities": [{"capability_id": "repo_graph_snapshot"}]}}
    )
    config = AgentInternetProxyConfig(base_url="https://agent.example", bearer_token="secret", timeout_s=5)

    payload = fetch_repo_graph_capabilities(config=config)

    assert payload["capabilities"][0]["capability_id"] == "repo_graph_snapshot"


@patch("steward.interfaces.agent_internet.urllib.request.urlopen")
def test_fetch_public_graph_and_search(mock_urlopen):
    mock_urlopen.side_effect = [
        _mock_response({"agent_web_graph": {"kind": "agent_web_public_graph", "nodes": []}}),
        _mock_response({"agent_web_index": {"kind": "agent_web_search_index", "records": []}}),
        _mock_response(
            {"agent_web_search": {"kind": "agent_web_search_results", "results": [{"title": "Marketplace"}]}}
        ),
    ]
    config = AgentInternetProxyConfig(base_url="https://agent.example", bearer_token="secret", timeout_s=5)

    graph = fetch_public_graph(config=config, root="/repo")
    index = fetch_search_index(config=config, root="/repo")
    search = search_index(config=config, root="/repo", query="marketplace", limit=3)

    assert graph["kind"] == "agent_web_public_graph"
    assert index["kind"] == "agent_web_search_index"
    assert search["results"][0]["title"] == "Marketplace"


@patch("steward.interfaces.agent_internet.urllib.request.urlopen")
def test_fetch_federated_index_and_search(mock_urlopen):
    mock_urlopen.side_effect = [
        _mock_response({"agent_web_federated_index": {"stats": {"source_count": 2}}}),
        _mock_response({"agent_web_federated_search": {"results": [{"source_city_id": "city-b"}]}}),
    ]
    config = AgentInternetProxyConfig(base_url="https://agent.example", bearer_token="secret", timeout_s=5)

    index = fetch_federated_index(config=config, index_path="/tmp/index.json")
    search = search_federated_index(config=config, query="bazaar", limit=2, index_path="/tmp/index.json")

    assert index["stats"]["source_count"] == 2
    assert search["results"][0]["source_city_id"] == "city-b"
