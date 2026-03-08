"""Tests for the thin agent_internet tool."""

from __future__ import annotations

import json

import pytest

from steward.tools.agent_internet import AgentInternetTool


class TestAgentInternetTool:
    def setup_method(self):
        self.tool = AgentInternetTool()

    def test_name(self):
        assert self.tool.name == "agent_internet"

    def test_validate_requires_action(self):
        with pytest.raises(ValueError, match="Missing required parameter: action"):
            self.tool.validate({})

    def test_validate_rejects_unknown_action(self):
        with pytest.raises(ValueError, match="Unsupported action"):
            self.tool.validate({"action": "nope"})

    def test_validate_call_requires_selector(self):
        with pytest.raises(ValueError, match="call requires capability_id or contract_id"):
            self.tool.validate({"action": "call", "input_payload": {"query": "x"}})

    def test_validate_call_requires_object_payload(self):
        with pytest.raises(TypeError, match="input_payload must be an object"):
            self.tool.validate({"action": "call", "capability_id": "semantic_expand", "input_payload": "bad"})

    def test_execute_capabilities(self, monkeypatch):
        monkeypatch.setattr(
            "steward.tools.agent_internet.fetch_semantic_capabilities",
            lambda: {"kind": "agent_web_semantic_capability_manifest", "capabilities": []},
        )

        result = self.tool.execute({"action": "capabilities"})

        assert result.success is True
        assert json.loads(result.output)["kind"] == "agent_web_semantic_capability_manifest"

    def test_execute_call(self, monkeypatch):
        monkeypatch.setattr(
            "steward.tools.agent_internet.invoke_semantic_http",
            lambda capability_id=None, contract_id=None, version=None, input_payload=None: {
                "kind": "steward_agent_internet_semantic_proxy_invocation",
                "selector": {"capability_id": capability_id, "contract_id": contract_id, "version": version or 1},
                "request": {"query": {"q": input_payload["query"]}},
            },
        )

        result = self.tool.execute(
            {"action": "call", "capability_id": "semantic_expand", "input_payload": {"query": "bazaar"}}
        )

        assert result.success is True
        assert json.loads(result.output)["request"]["query"] == {"q": "bazaar"}

    def test_execute_surfaces_errors(self, monkeypatch):
        monkeypatch.setattr(
            "steward.tools.agent_internet.fetch_semantic_capabilities",
            lambda: (_ for _ in ()).throw(RuntimeError("missing_agent_internet_token")),
        )

        result = self.tool.execute({"action": "capabilities"})

        assert result.success is False
        assert result.error == "missing_agent_internet_token"
