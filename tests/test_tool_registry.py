"""Tests for ToolRegistry."""

from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolResult

from steward.tool_registry import ToolRegistry


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


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        assert reg.get("echo") is not None
        assert reg.get("nonexistent") is None

    def test_execute_success(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        result = reg.execute("echo", {"message": "hello"})
        assert result.success
        assert result.output == "hello"

    def test_execute_unknown_tool(self):
        reg = ToolRegistry()
        result = reg.execute("nonexistent", {})
        assert not result.success
        assert "Unknown tool" in result.error

    def test_execute_validation_failure(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        result = reg.execute("echo", {})  # missing required 'message'
        assert not result.success
        assert "Validation failed" in result.error

    def test_execute_tool_crash(self):
        reg = ToolRegistry()
        reg.register(FailTool())
        result = reg.execute("fail", {})
        assert not result.success
        assert "boom" in result.error

    def test_to_llm_tools(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        tools = reg.to_llm_tools()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "echo"

    def test_contains_and_len(self):
        reg = ToolRegistry()
        assert len(reg) == 0
        reg.register(EchoTool())
        assert len(reg) == 1
        assert "echo" in reg
        assert "nope" not in reg

    def test_tool_names(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.register(FailTool())
        assert set(reg.tool_names) == {"echo", "fail"}
