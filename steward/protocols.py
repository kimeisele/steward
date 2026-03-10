"""
Steward Protocols — typed interfaces, no duck-typing, no hasattr.

Every cross-component communication goes through a protocol.
Components talk to interfaces, not implementations.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from vibe_core.tools.tool_protocol import Tool


@runtime_checkable
class HealthGate(Protocol):
    """Bridge between Cetana (observer) and Engine (actor).

    Instead of getattr(agent, "_health_anomaly"), the engine
    reads this interface. Clean contract, no coupling.
    """

    @property
    def health_anomaly(self) -> bool:
        """Is there an active health anomaly?"""
        ...

    @property
    def health_anomaly_detail(self) -> str:
        """Human-readable detail of the anomaly."""
        ...

    def clear_health_anomaly(self) -> None:
        """Reset the anomaly flag after reading."""
        ...


@runtime_checkable
class RemotePerception(Protocol):
    """Whether a sense has remote perception capability."""

    def has_remote_perception(self) -> bool:
        """Can this sense perceive beyond local?"""
        ...


@runtime_checkable
class ToolProvider(Protocol):
    """Provides tools to the agent — pluggable tool discovery.

    Implementations:
        BuiltinToolProvider — hardcoded default tools (bash, read, write, etc.)
        FileSystemToolProvider — discovers from .steward/tools/
        Future: MCPToolProvider, FederationToolProvider

    Federation: external repos register ToolProviders. Agent discovers
    tools at boot without hardcoded imports.
    """

    @property
    def name(self) -> str:
        """Provider name for diagnostics."""
        ...

    def provide(self, cwd: str) -> list[Tool]:
        """Discover and return available tools for the given workspace."""
        ...
