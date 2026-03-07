"""
Steward Configuration — YAML-based project settings.

Loads .steward/config.yaml from the working directory and provides
typed access to settings with sensible defaults.

    config = load_config("/path/to/project")
    config.max_output_tokens  # 4096
    config.model              # "auto"
    config.tools_enabled      # ["bash", "read_file", ...]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("STEWARD.CONFIG")

_CONFIG_FILENAME = "config.yaml"


@dataclass
class StewardConfig:
    """Steward configuration with defaults.

    Loaded from .steward/config.yaml. Missing keys use defaults.
    """

    # LLM settings
    model: str = "auto"                     # "auto" = ProviderChamber picks, or specific model
    max_output_tokens: int = 4096           # Max tokens per LLM response
    max_context_tokens: int = 100_000       # Context window budget
    temperature: float = 0.0                # LLM temperature

    # Tool settings
    tools_enabled: list[str] = field(default_factory=lambda: [
        "bash", "read_file", "write_file", "glob", "edit_file", "grep",
    ])

    # Behavior
    auto_summarize: bool = True             # LLM-based summarization at 70%
    summarize_threshold: float = 0.7        # Context % that triggers summarization
    confirm_destructive: bool = True        # Ask before rm, git push --force, etc.
    max_tool_rounds: int = 50               # Max tool-use iterations per turn

    # Persistence
    persist_memory: bool = True             # Use PersistentMemory (JSON-backed)
    persist_conversation: bool = True       # Save conversation state between sessions


def load_config(cwd: str | None = None) -> StewardConfig:
    """Load configuration from .steward/config.yaml.

    Falls back to defaults if file doesn't exist or is invalid.
    """
    cwd_path = Path(cwd) if cwd else Path.cwd()
    config_file = cwd_path / ".steward" / _CONFIG_FILENAME

    if not config_file.is_file():
        return StewardConfig()

    try:
        import yaml
    except ImportError:
        logger.debug("PyYAML not installed, using defaults")
        return StewardConfig()

    try:
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            logger.warning("Config file is not a YAML mapping, using defaults")
            return StewardConfig()

        return _parse_config(raw)

    except Exception as e:
        logger.warning("Failed to load config (%s), using defaults", e)
        return StewardConfig()


def _parse_config(raw: dict[str, object]) -> StewardConfig:
    """Parse raw YAML dict into StewardConfig."""
    config = StewardConfig()

    # LLM settings
    if "model" in raw and isinstance(raw["model"], str):
        config.model = raw["model"]
    if "max_output_tokens" in raw and isinstance(raw["max_output_tokens"], int):
        config.max_output_tokens = raw["max_output_tokens"]
    if "max_context_tokens" in raw and isinstance(raw["max_context_tokens"], int):
        config.max_context_tokens = raw["max_context_tokens"]
    if "temperature" in raw and isinstance(raw["temperature"], (int, float)):
        config.temperature = float(raw["temperature"])

    # Tool settings
    if "tools_enabled" in raw and isinstance(raw["tools_enabled"], list):
        config.tools_enabled = [str(t) for t in raw["tools_enabled"]]

    # Behavior
    if "auto_summarize" in raw and isinstance(raw["auto_summarize"], bool):
        config.auto_summarize = raw["auto_summarize"]
    if "summarize_threshold" in raw and isinstance(raw["summarize_threshold"], (int, float)):
        config.summarize_threshold = float(raw["summarize_threshold"])
    if "confirm_destructive" in raw and isinstance(raw["confirm_destructive"], bool):
        config.confirm_destructive = raw["confirm_destructive"]
    if "max_tool_rounds" in raw and isinstance(raw["max_tool_rounds"], int):
        config.max_tool_rounds = raw["max_tool_rounds"]

    # Persistence
    if "persist_memory" in raw and isinstance(raw["persist_memory"], bool):
        config.persist_memory = raw["persist_memory"]
    if "persist_conversation" in raw and isinstance(raw["persist_conversation"], bool):
        config.persist_conversation = raw["persist_conversation"]

    return config
