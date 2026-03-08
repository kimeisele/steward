"""Tests for StewardConfig loading."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from steward.config import StewardConfig, _parse_config, load_config

# ── Fake LLM for agent tests ────────────────────────────────────────


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class FakeResponse:
    content: str = ""
    tool_calls: list[Any] | None = None
    usage: FakeUsage | None = None

    def __post_init__(self) -> None:
        if self.usage is None:
            self.usage = FakeUsage()


class FakeLLM:
    def invoke(self, **kwargs: Any) -> FakeResponse:
        return FakeResponse(content="ok")


# ── Tests ────────────────────────────────────────────────────────────


class TestStewardConfigDefaults:
    def test_defaults(self) -> None:
        """Default config values are sensible."""
        config = StewardConfig()
        assert config.model == "auto"
        assert config.max_output_tokens == 4096
        assert config.max_context_tokens == 100_000
        assert config.temperature == 0.0
        assert config.auto_summarize is True
        assert config.summarize_threshold == 0.7
        assert config.max_tool_rounds == 50
        assert config.persist_memory is True
        assert "bash" in config.tools_enabled
        assert "read_file" in config.tools_enabled

    def test_no_config_file_returns_defaults(self) -> None:
        """Missing config file returns defaults."""
        with tempfile.TemporaryDirectory() as tmp:
            config = load_config(tmp)
            assert config.model == "auto"
            assert config.max_output_tokens == 4096


class TestLoadConfig:
    def _write_yaml(self, tmp: str, content: str) -> None:
        steward_dir = Path(tmp) / ".steward"
        steward_dir.mkdir(exist_ok=True)
        (steward_dir / "config.yaml").write_text(content)

    def test_loads_yaml_config(self) -> None:
        """Loads config from .steward/config.yaml."""
        try:
            import yaml  # noqa: F401
        except ImportError:
            return  # skip if PyYAML not installed

        with tempfile.TemporaryDirectory() as tmp:
            self._write_yaml(
                tmp,
                """\
model: claude-sonnet-4-20250514
max_output_tokens: 8192
temperature: 0.3
auto_summarize: false
""",
            )
            config = load_config(tmp)
            assert config.model == "claude-sonnet-4-20250514"
            assert config.max_output_tokens == 8192
            assert config.temperature == 0.3
            assert config.auto_summarize is False

    def test_partial_config_merges_with_defaults(self) -> None:
        """Partial YAML only overrides specified keys."""
        try:
            import yaml  # noqa: F401
        except ImportError:
            return

        with tempfile.TemporaryDirectory() as tmp:
            self._write_yaml(tmp, "model: mistral-small-latest\n")
            config = load_config(tmp)
            assert config.model == "mistral-small-latest"
            # Defaults still apply
            assert config.max_output_tokens == 4096
            assert config.auto_summarize is True

    def test_corrupted_yaml_returns_defaults(self) -> None:
        """Corrupted YAML falls back to defaults."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write_yaml(tmp, "{{{{invalid yaml!!!!")
            config = load_config(tmp)
            assert config.model == "auto"

    def test_non_mapping_yaml_returns_defaults(self) -> None:
        """YAML that isn't a mapping returns defaults."""
        try:
            import yaml  # noqa: F401
        except ImportError:
            return

        with tempfile.TemporaryDirectory() as tmp:
            self._write_yaml(tmp, "- list\n- not\n- a mapping\n")
            config = load_config(tmp)
            assert config.model == "auto"

    def test_tools_enabled_override(self) -> None:
        """Can override which tools are enabled."""
        try:
            import yaml  # noqa: F401
        except ImportError:
            return

        with tempfile.TemporaryDirectory() as tmp:
            self._write_yaml(
                tmp,
                """\
tools_enabled:
  - read_file
  - grep
""",
            )
            config = load_config(tmp)
            assert config.tools_enabled == ["read_file", "grep"]


class TestParseConfig:
    def test_parse_all_fields(self) -> None:
        """All config fields are parsed correctly."""
        raw = {
            "model": "gpt-4",
            "max_output_tokens": 2048,
            "max_context_tokens": 50_000,
            "temperature": 0.5,
            "tools_enabled": ["bash", "read_file"],
            "auto_summarize": False,
            "summarize_threshold": 0.8,
            "confirm_destructive": False,
            "max_tool_rounds": 25,
            "persist_memory": False,
            "persist_conversation": False,
        }
        config = _parse_config(raw)
        assert config.model == "gpt-4"
        assert config.max_output_tokens == 2048
        assert config.max_context_tokens == 50_000
        assert config.temperature == 0.5
        assert config.tools_enabled == ["bash", "read_file"]
        assert config.auto_summarize is False
        assert config.summarize_threshold == 0.8
        assert config.confirm_destructive is False
        assert config.max_tool_rounds == 25
        assert config.persist_memory is False
        assert config.persist_conversation is False

    def test_ignores_unknown_fields(self) -> None:
        """Unknown fields are silently ignored."""
        raw = {"model": "test", "unknown_field": 42, "another": "ignored"}
        config = _parse_config(raw)
        assert config.model == "test"

    def test_ignores_wrong_types(self) -> None:
        """Wrong types for known fields are ignored (defaults kept)."""
        raw = {"model": 123, "max_output_tokens": "not-int", "auto_summarize": "yes"}
        config = _parse_config(raw)
        assert config.model == "auto"  # default, because 123 is not str
        assert config.max_output_tokens == 4096
        assert config.auto_summarize is True


class TestAgentWithConfig:
    def test_agent_uses_config_defaults(self) -> None:
        """Agent loads config and uses it."""
        from steward.agent import StewardAgent

        llm = FakeLLM()
        agent = StewardAgent(provider=llm)
        assert agent.config.model == "auto"
        assert agent.config.max_output_tokens == 4096

    def test_explicit_args_override_config(self) -> None:
        """Explicit constructor args override config file values."""
        from steward.agent import StewardAgent

        llm = FakeLLM()
        agent = StewardAgent(provider=llm, max_output_tokens=8192)
        assert agent._max_output_tokens == 8192

    def test_explicit_config_object(self) -> None:
        """Can pass a StewardConfig directly."""
        from steward.agent import StewardAgent

        custom = StewardConfig(model="custom-model", max_output_tokens=2048)
        llm = FakeLLM()
        agent = StewardAgent(provider=llm, config=custom)
        assert agent.config.model == "custom-model"
        assert agent._max_output_tokens == 2048
