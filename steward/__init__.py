"""Steward — Autonomous Agent Engine.

Public API:
    from steward import StewardAgent, AgentEvent
    from steward.provider import ProviderChamber, build_chamber
    from steward.services import boot, SVC_TOOL_REGISTRY, SVC_SAFETY_GUARD
    from steward.services import SVC_MEMORY, SVC_EVENT_BUS, SVC_PROMPT_CONTEXT
    from steward.state import save_conversation, load_conversation
"""

from __future__ import annotations

from typing import TYPE_CHECKING

__version__ = "0.17.0"

if TYPE_CHECKING:  # pragma: no cover
    from steward.agent import StewardAgent
    from steward.types import AgentEvent, AgentUsage, Conversation, LLMProvider, Message, ToolUse

__all__ = [
    "StewardAgent",
    "AgentEvent",
    "AgentUsage",
    "Conversation",
    "LLMProvider",
    "Message",
    "ToolUse",
]


def __getattr__(name: str) -> object:
    if name == "StewardAgent":
        from steward.agent import StewardAgent as _StewardAgent

        return _StewardAgent
    if name in {"AgentEvent", "AgentUsage", "Conversation", "LLMProvider", "Message", "ToolUse"}:
        from steward import types as _types

        return getattr(_types, name)
    raise AttributeError(name)
