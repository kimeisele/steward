"""Thin agent-internet semantic proxy client for steward API wrappers."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentInternetProxyConfig:
    base_url: str
    bearer_token: str
    timeout_s: int = 5


def load_agent_internet_proxy_config(
    *,
    base_url: str | None = None,
    bearer_token: str | None = None,
    timeout_s: int | None = None,
) -> AgentInternetProxyConfig:
    resolved_base_url = str(base_url or os.environ.get("STEWARD_AGENT_INTERNET_BASE_URL", "")).rstrip("/")
    resolved_token = str(bearer_token or os.environ.get("STEWARD_AGENT_INTERNET_TOKEN", ""))
    resolved_timeout_s = int(timeout_s or os.environ.get("STEWARD_AGENT_INTERNET_TIMEOUT_S", "5"))
    if not resolved_base_url:
        raise ValueError("missing_agent_internet_base_url")
    if not resolved_token:
        raise ValueError("missing_agent_internet_token")
    return AgentInternetProxyConfig(
        base_url=resolved_base_url,
        bearer_token=resolved_token,
        timeout_s=resolved_timeout_s,
    )


def fetch_semantic_capabilities(config: AgentInternetProxyConfig | None = None) -> dict:
    payload = _request_json(config or load_agent_internet_proxy_config(), "/v1/lotus/agent-web-semantic-capabilities")
    return dict(payload["agent_web_semantic_capabilities"])


def fetch_semantic_contracts(
    *,
    config: AgentInternetProxyConfig | None = None,
    capability_id: str | None = None,
    contract_id: str | None = None,
    version: int | None = None,
) -> dict:
    query = _query(capability_id=capability_id, contract_id=contract_id, version=version)
    suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
    payload = _request_json(
        config or load_agent_internet_proxy_config(), f"/v1/lotus/agent-web-semantic-contracts{suffix}"
    )
    return dict(payload["agent_web_semantic_contracts"])


def invoke_semantic_http(
    *,
    config: AgentInternetProxyConfig | None = None,
    capability_id: str | None = None,
    contract_id: str | None = None,
    version: int | None = None,
    input_payload: dict | None = None,
) -> dict:
    resolved_config = config or load_agent_internet_proxy_config()
    capabilities = fetch_semantic_capabilities(config=resolved_config)
    contract = fetch_semantic_contracts(
        config=resolved_config,
        capability_id=capability_id,
        contract_id=contract_id,
        version=version,
    )
    capability = _find_capability(capabilities=capabilities, capability_id=str(contract["capability_id"]))
    invocation = _build_http_invocation(contract=contract, input_payload=dict(input_payload or {}))
    response = _request_json(resolved_config, invocation["path_with_query"])
    return {
        "kind": "steward_agent_internet_semantic_proxy_invocation",
        "version": 1,
        "standard_profile_id": dict(capabilities.get("standard_profile", {})).get("profile_id"),
        "selector": {
            "capability_id": contract["capability_id"],
            "contract_id": contract["contract_id"],
            "version": contract["version"],
        },
        "capability": {
            "capability_id": capability["capability_id"],
            "summary": capability["summary"],
        },
        "contract": contract,
        "request": {
            "transport_kind": "http",
            "path": invocation["path"],
            "query": invocation["query"],
        },
        "response": response,
    }


def _request_json(config: AgentInternetProxyConfig, path: str) -> dict:
    request = urllib.request.Request(f"{config.base_url}{path}", method="GET")
    request.add_header("Authorization", f"Bearer {config.bearer_token}")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "steward-agent/agent-internet-proxy")
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else exc.reason
        raise RuntimeError(f"agent_internet_http_error:{exc.code}:{detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"agent_internet_url_error:{exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"agent_internet_timeout:{config.timeout_s}") from exc


def _query(**values: object) -> dict[str, str]:
    return {str(key): str(value) for key, value in values.items() if value not in (None, "")}


def _find_capability(*, capabilities: dict, capability_id: str) -> dict:
    for capability in capabilities.get("capabilities", []):
        payload = dict(capability)
        if payload.get("capability_id") == capability_id:
            return payload
    raise RuntimeError(f"unknown_capability:{capability_id}")


def _build_http_invocation(*, contract: dict, input_payload: dict) -> dict:
    transport = dict(contract.get("transport", {})).get("http", {})
    request_schema = dict(contract.get("request_schema", {}))
    properties = dict(request_schema.get("properties", {}))
    required = set(request_schema.get("required", []))
    query: dict[str, str] = {}
    for name, schema in properties.items():
        schema_payload = dict(schema)
        if name in input_payload:
            query[str(schema_payload.get("http_name", name))] = str(input_payload[name])
        elif name in required:
            raise ValueError(f"missing_input:{name}")
    encoded = urllib.parse.urlencode(query)
    path = str(transport.get("path", ""))
    return {"path": path, "query": query, "path_with_query": f"{path}?{encoded}" if encoded else path}
