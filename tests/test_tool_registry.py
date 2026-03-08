"""Tests for steward-protocol's ToolRegistry (real substrate)."""

from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolCall, ToolResult
from vibe_core.tools.tool_registry import ToolRegistry


class EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes back the message"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {"message": {"type": "string", "required": True}}

    def validate(self, parameters: dict[str, Any]) -> None:
        if "message" not in parameters:
            raise ValueError("Missing: message")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output=parameters["message"])


class FailTool(Tool):
    @property
    def name(self) -> str:
        return "fail"

    @property
    def description(self) -> str:
        return "Always fails"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {}

    def validate(self, parameters: dict[str, Any]) -> None:
        pass

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        raise RuntimeError("boom")


class TestToolDescriptionFormat:
    """Verify tool descriptions are in OpenAI JSON Schema format."""

    def test_descriptions_have_json_schema_parameters(self):
        from steward.services import tool_descriptions_for_llm

        reg = ToolRegistry()
        reg.register(EchoTool())
        descs = tool_descriptions_for_llm(reg)

        assert len(descs) == 1
        d = descs[0]
        assert d["type"] == "function"
        func = d["function"]
        assert "name" in func
        assert "parameters" in func
        params = func["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert "required" in params

    def test_required_fields_extracted(self):
        from steward.services import tool_descriptions_for_llm
        from steward.tools.bash import BashTool

        reg = ToolRegistry()
        reg.register(BashTool())
        descs = tool_descriptions_for_llm(reg)

        func = descs[0]["function"]
        params = func["parameters"]
        assert "command" in params["required"]
        assert "timeout" not in params["required"]


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        assert reg.get("echo") is not None
        assert reg.get("nonexistent") is None

    def test_execute_success(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        call = ToolCall(tool_name="echo", parameters={"message": "hello"})
        result = reg.execute(call)
        assert result.success
        assert result.output == "hello"

    def test_execute_unknown_tool(self):
        reg = ToolRegistry()
        call = ToolCall(tool_name="nonexistent", parameters={})
        result = reg.execute(call)
        assert not result.success
        assert "not found" in result.error

    def test_execute_validation_failure(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        call = ToolCall(tool_name="echo", parameters={})
        result = reg.execute(call)
        assert not result.success
        assert "validation" in result.error.lower() or "Missing" in result.error

    def test_execute_tool_crash(self):
        reg = ToolRegistry()
        reg.register(FailTool())
        call = ToolCall(tool_name="fail", parameters={})
        result = reg.execute(call)
        assert not result.success
        assert "boom" in result.error

    def test_get_tool_descriptions(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        descs = reg.get_tool_descriptions()
        assert len(descs) == 1
        assert descs[0]["name"] == "echo"

    def test_has_and_len(self):
        reg = ToolRegistry()
        assert len(reg) == 0
        reg.register(EchoTool())
        assert len(reg) == 1
        assert reg.has("echo")
        assert not reg.has("nope")

    def test_list_tools(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.register(FailTool())
        assert set(reg.list_tools()) == {"echo", "fail"}
