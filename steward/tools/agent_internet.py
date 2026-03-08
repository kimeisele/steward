"""Thin tool for agent-internet semantic discovery and invocation."""

from __future__ import annotations

import json
from typing import Any

from steward.interfaces.agent_internet import (
    fetch_semantic_capabilities,
    fetch_semantic_contracts,
    invoke_semantic_http,
)
from vibe_core.tools.tool_protocol import Tool, ToolResult


class AgentInternetTool(Tool):
    """Discover or invoke published agent-internet semantic capabilities."""

    @property
    def name(self) -> str:
        return "agent_internet"

    @property
    def description(self) -> str:
        return (
            "Use the published agent-internet semantic surface via environment-configured HTTP access. "
            "Actions: capabilities, contracts, call. Requires STEWARD_AGENT_INTERNET_BASE_URL and "
            "STEWARD_AGENT_INTERNET_TOKEN in the environment."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "required": True,
                "description": "One of: capabilities, contracts, call",
            },
            "capability_id": {
                "type": "string",
                "required": False,
                "description": "Capability selector, e.g. semantic_expand",
            },
            "contract_id": {
                "type": "string",
                "required": False,
                "description": "Contract selector, e.g. semantic_expand.v1",
            },
            "version": {
                "type": "integer",
                "required": False,
                "description": "Optional contract version selector",
            },
            "input_payload": {
                "type": "object",
                "required": False,
                "description": "Input values for action=call, keyed by contract request property name",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        action = parameters.get("action")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("Missing required parameter: action")
        if action not in {"capabilities", "contracts", "call"}:
            raise ValueError(f"Unsupported action: {action}")
        if action == "call":
            if not isinstance(parameters.get("input_payload", {}), dict):
                raise TypeError("input_payload must be an object")
            if not parameters.get("capability_id") and not parameters.get("contract_id"):
                raise ValueError("call requires capability_id or contract_id")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        action = str(parameters["action"])
        try:
            if action == "capabilities":
                payload = fetch_semantic_capabilities()
            elif action == "contracts":
                payload = fetch_semantic_contracts(
                    capability_id=_string_or_none(parameters.get("capability_id")),
                    contract_id=_string_or_none(parameters.get("contract_id")),
                    version=_int_or_none(parameters.get("version")),
                )
            else:
                payload = invoke_semantic_http(
                    capability_id=_string_or_none(parameters.get("capability_id")),
                    contract_id=_string_or_none(parameters.get("contract_id")),
                    version=_int_or_none(parameters.get("version")),
                    input_payload=dict(parameters.get("input_payload", {})),
                )
            return ToolResult(success=True, output=json.dumps(payload, indent=2, sort_keys=True))
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


def _string_or_none(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
