"""
Tool Providers — pluggable tool discovery for federation scaling.

ToolProvider protocol enables dynamic tool registration from:
  - Builtin tools (bash, read, write, edit, grep, glob, etc.)
  - File system (.steward/tools/*.py modules)
  - Future: MCP servers, federation repos, runtime factories

Usage:
    providers = [BuiltinToolProvider(), FileSystemToolProvider()]
    all_tools = []
    for p in providers:
        all_tools.extend(p.provide(cwd="/path/to/project"))
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from vibe_core.tools.tool_protocol import Tool

logger = logging.getLogger("STEWARD.TOOLS.PROVIDERS")


class BuiltinToolProvider:
    """Provides the core tool set — the agent's karmendriyas (action organs).

    These 10 tools are always available regardless of workspace.
    """

    @property
    def name(self) -> str:
        return "builtin"

    def provide(self, cwd: str) -> list[Tool]:
        from steward.senses.gh import get_gh_client
        from steward.tools.agent_internet import AgentInternetTool
        from steward.tools.annotate import AnnotateTool
        from steward.tools.bash import BashTool
        from steward.tools.delegate import DelegateToPeerTool
        from steward.tools.edit import EditTool
        from steward.tools.explore import ExploreTool
        from steward.tools.git import GitTool
        from steward.tools.glob import GlobTool
        from steward.tools.grep import GrepTool
        from steward.tools.http import HttpTool
        from steward.tools.knowledge import KnowledgeGraphTool
        from steward.tools.read_file import ReadFileTool
        from steward.tools.sub_agent import SubAgentTool
        from steward.tools.synthesize_briefing import SynthesizeBriefingTool
        from steward.tools.think import ThinkTool
        from steward.tools.web_search import WebSearchTool
        from steward.tools.write_file import WriteFileTool

        return [
            AnnotateTool(),
            BashTool(cwd=cwd),
            ReadFileTool(),
            WriteFileTool(),
            GlobTool(cwd=cwd),
            EditTool(),
            GrepTool(cwd=cwd),
            ExploreTool(cwd=cwd),
            GitTool(cwd=cwd, gh_client=get_gh_client()),
            HttpTool(),
            WebSearchTool(),
            AgentInternetTool(),
            SubAgentTool(cwd=cwd),
            KnowledgeGraphTool(),
            DelegateToPeerTool(),
            SynthesizeBriefingTool(cwd=cwd),
            ThinkTool(),
        ]


class FileSystemToolProvider:
    """Discovers tools from .steward/tools/ directory.

    Each .py file in .steward/tools/ that defines a Tool subclass
    gets auto-registered. This enables per-project tool extensions
    without modifying the agent codebase.

    Convention:
        .steward/tools/deploy.py → class DeployTool(Tool)
        .steward/tools/lint.py   → class LintTool(Tool)

    Graceful: missing directory → empty list, bad module → skip + log.
    """

    @property
    def name(self) -> str:
        return "filesystem"

    def provide(self, cwd: str) -> list[Tool]:
        tools_dir = Path(cwd) / ".steward" / "tools"
        if not tools_dir.is_dir():
            return []

        tools: list[Tool] = []
        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                found = self._load_tools_from_module(py_file)
                tools.extend(found)
                if found:
                    logger.info(
                        "FileSystemToolProvider: loaded %d tool(s) from %s",
                        len(found),
                        py_file.name,
                    )
            except Exception as e:
                logger.warning(
                    "FileSystemToolProvider: failed to load %s: %s",
                    py_file.name,
                    e,
                )
        return tools

    @staticmethod
    def _load_tools_from_module(path: Path) -> list[Tool]:
        """Import a .py file and find all Tool subclasses."""
        module_name = f"steward_ext_tool_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return []
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        tools: list[Tool] = []
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, Tool)
                and obj is not Tool
                and not getattr(obj, "__abstract__", False)
            ):
                try:
                    tools.append(obj())
                except TypeError:
                    # Tool requires constructor args — skip
                    logger.debug("Skipping %s (requires constructor args)", attr_name)
        return tools


def collect_tools(
    providers: list[object],
    cwd: str,
    extra_tools: list[Tool] | None = None,
) -> list[Tool]:
    """Collect tools from all providers + explicit extras.

    Args:
        providers: ToolProvider instances
        cwd: Working directory for tool construction
        extra_tools: Additional Tool instances (e.g., from API caller)

    Returns:
        Deduplicated list of tools (by name, first wins)
    """
    all_tools: list[Tool] = []
    seen_names: set[str] = set()

    for provider in providers:
        try:
            provided = provider.provide(cwd)
            for tool in provided:
                if tool.name not in seen_names:
                    all_tools.append(tool)
                    seen_names.add(tool.name)
        except Exception as e:
            name = getattr(provider, "name", type(provider).__name__)
            logger.warning("ToolProvider %s failed: %s", name, e)

    for tool in extra_tools or []:
        if tool.name not in seen_names:
            all_tools.append(tool)
            seen_names.add(tool.name)

    return all_tools
