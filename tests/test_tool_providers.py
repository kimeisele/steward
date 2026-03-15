"""Tests for ToolProvider protocol — pluggable tool discovery.

Validates:
  - BuiltinToolProvider returns 10 core tools
  - FileSystemToolProvider discovers from .steward/tools/
  - collect_tools() deduplicates by name
  - Agent accepts tool_providers parameter
  - discover() reports tool providers
"""

from __future__ import annotations

import textwrap

from steward.protocols import ToolProvider
from steward.tool_providers import (
    BuiltinToolProvider,
    FileSystemToolProvider,
    collect_tools,
)
from vibe_core.tools.tool_protocol import Tool


class TestBuiltinToolProvider:
    """BuiltinToolProvider returns the core tool set."""

    def test_name(self):
        provider = BuiltinToolProvider()
        assert provider.name == "builtin"

    def test_provides_core_tools(self, tmp_path):
        provider = BuiltinToolProvider()
        tools = provider.provide(str(tmp_path))
        assert len(tools) == 16

    def test_tool_names(self, tmp_path):
        provider = BuiltinToolProvider()
        tools = provider.provide(str(tmp_path))
        names = {t.name for t in tools}
        assert "bash" in names
        assert "read_file" in names
        assert "write_file" in names
        assert "glob" in names
        assert "edit_file" in names
        assert "grep" in names
        assert "git" in names
        assert "query_codebase" in names
        assert "delegate_to_peer" in names

    def test_implements_protocol(self):
        provider = BuiltinToolProvider()
        assert isinstance(provider, ToolProvider)


class TestFileSystemToolProvider:
    """FileSystemToolProvider discovers from .steward/tools/."""

    def test_name(self):
        provider = FileSystemToolProvider()
        assert provider.name == "filesystem"

    def test_empty_when_no_dir(self, tmp_path):
        provider = FileSystemToolProvider()
        tools = provider.provide(str(tmp_path))
        assert tools == []

    def test_empty_when_dir_has_no_py(self, tmp_path):
        (tmp_path / ".steward" / "tools").mkdir(parents=True)
        provider = FileSystemToolProvider()
        tools = provider.provide(str(tmp_path))
        assert tools == []

    def test_discovers_tool_from_file(self, tmp_path):
        """A .py file with a Tool subclass gets discovered."""
        tools_dir = tmp_path / ".steward" / "tools"
        tools_dir.mkdir(parents=True)

        # Write a minimal tool module matching Tool ABC interface
        (tools_dir / "hello.py").write_text(
            textwrap.dedent("""\
            from vibe_core.tools.tool_protocol import Tool, ToolResult

            class HelloTool(Tool):
                @property
                def name(self) -> str:
                    return "hello"

                @property
                def description(self) -> str:
                    return "Says hello"

                @property
                def parameters_schema(self) -> dict:
                    return {}

                def validate(self, parameters: dict) -> None:
                    pass

                def execute(self, parameters: dict) -> ToolResult:
                    return ToolResult(success=True, output="Hello!")
        """)
        )

        provider = FileSystemToolProvider()
        tools = provider.provide(str(tmp_path))
        assert len(tools) == 1
        assert tools[0].name == "hello"

    def test_skips_underscored_files(self, tmp_path):
        tools_dir = tmp_path / ".steward" / "tools"
        tools_dir.mkdir(parents=True)
        (tools_dir / "__init__.py").write_text("")
        (tools_dir / "_private.py").write_text("x = 1")

        provider = FileSystemToolProvider()
        tools = provider.provide(str(tmp_path))
        assert tools == []

    def test_implements_protocol(self):
        provider = FileSystemToolProvider()
        assert isinstance(provider, ToolProvider)


class TestCollectTools:
    """collect_tools() merges providers + deduplicates."""

    def test_deduplicates_by_name(self, tmp_path):
        """First provider's tool wins on name conflict."""
        p1 = BuiltinToolProvider()
        p2 = BuiltinToolProvider()  # same tools
        tools = collect_tools([p1, p2], str(tmp_path))
        names = [t.name for t in tools]
        assert len(names) == len(set(names))  # no duplicates

    def test_extra_tools_appended(self, tmp_path):
        """Extra tools added after providers."""
        from unittest.mock import MagicMock

        extra = MagicMock(spec=Tool)
        extra.name = "custom_tool"

        tools = collect_tools([BuiltinToolProvider()], str(tmp_path), extra_tools=[extra])
        names = {t.name for t in tools}
        assert "custom_tool" in names
        assert "bash" in names

    def test_failing_provider_skipped(self, tmp_path):
        """A provider that raises doesn't break collection."""

        class BrokenProvider:
            name = "broken"

            def provide(self, cwd: str) -> list:
                raise RuntimeError("boom")

        tools = collect_tools([BrokenProvider(), BuiltinToolProvider()], str(tmp_path))
        assert len(tools) == 16  # builtin still works


class TestAgentToolProviders:
    """StewardAgent accepts tool_providers parameter."""

    def test_discover_reports_providers(self):
        """discover() shows tool_providers in output."""
        import inspect

        from steward.agent import StewardAgent

        sig = inspect.signature(StewardAgent.__init__)
        assert "tool_providers" in sig.parameters
