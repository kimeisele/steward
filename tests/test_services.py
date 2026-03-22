"""Tests for steward/services.py — boot(), integrity, tool_descriptions_for_llm()."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from steward.services import (
    SVC_ATTENTION,
    SVC_CACHE,
    SVC_DIAMOND,
    SVC_EVENT_BUS,
    SVC_FEEDBACK,
    SVC_INTEGRITY,
    SVC_MEMORY,
    SVC_NARASIMHA,
    SVC_PROMPT_CONTEXT,
    SVC_PROVIDER,
    SVC_SAFETY_GUARD,
    SVC_SIGNAL_BUS,
    SVC_TOOL_REGISTRY,
    boot,
    tool_descriptions_for_llm,
)
from vibe_core.di import ServiceRegistry
from vibe_core.tools.tool_protocol import Tool, ToolResult


class _DummyTool(Tool):
    """Minimal tool for test registration."""

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "A test tool"

    @property
    def parameters_schema(self) -> dict:
        return {
            "arg": {
                "type": "string",
                "required": True,
                "description": "A required arg",
            },
            "opt": {
                "type": "integer",
                "required": False,
                "description": "An optional arg",
            },
        }

    def validate(self, parameters: dict) -> None:
        if "arg" not in parameters:
            raise ValueError("Missing arg")

    def execute(self, parameters: dict) -> ToolResult:
        return ToolResult(success=True, output="ok")


class TestBoot:
    """Test the boot() DI wiring function."""

    def test_boot_returns_service_registry(self):
        result = boot(tools=[_DummyTool()])
        assert result is ServiceRegistry

    def test_boot_registers_tool_registry(self):
        boot(tools=[_DummyTool()])
        registry = ServiceRegistry.get(SVC_TOOL_REGISTRY)
        assert registry is not None
        assert len(registry) == 1

    def test_boot_registers_safety_guard(self):
        boot(tools=[_DummyTool()])
        guard = ServiceRegistry.get(SVC_SAFETY_GUARD)
        assert guard is not None

    def test_boot_registers_attention(self):
        boot(tools=[_DummyTool()])
        attention = ServiceRegistry.get(SVC_ATTENTION)
        assert attention is not None

    def test_boot_registers_feedback(self):
        boot(tools=[_DummyTool()])
        feedback = ServiceRegistry.get(SVC_FEEDBACK)
        assert feedback is not None

    def test_boot_registers_signal_bus(self):
        boot(tools=[_DummyTool()])
        bus = ServiceRegistry.get(SVC_SIGNAL_BUS)
        assert bus is not None

    def test_boot_registers_memory(self):
        boot(tools=[_DummyTool()])
        memory = ServiceRegistry.get(SVC_MEMORY)
        assert memory is not None

    def test_boot_registers_event_bus(self):
        boot(tools=[_DummyTool()])
        event_bus = ServiceRegistry.get(SVC_EVENT_BUS)
        assert event_bus is not None

    def test_boot_registers_narasimha(self):
        boot(tools=[_DummyTool()])
        narasimha = ServiceRegistry.get(SVC_NARASIMHA)
        assert narasimha is not None

    def test_boot_registers_prompt_context(self):
        boot(tools=[_DummyTool()])
        ctx = ServiceRegistry.get(SVC_PROMPT_CONTEXT)
        assert ctx is not None

    def test_boot_registers_integrity(self):
        boot(tools=[_DummyTool()])
        checker = ServiceRegistry.get(SVC_INTEGRITY)
        assert checker is not None

    def test_boot_with_provider(self):
        provider = MagicMock()
        provider.invoke = MagicMock()
        boot(tools=[_DummyTool()], provider=provider)
        result = ServiceRegistry.get(SVC_PROVIDER)
        assert result is provider

    def test_boot_without_provider(self):
        boot(tools=[_DummyTool()])
        # Provider not registered — get() returns None or raises
        result = ServiceRegistry.get(SVC_PROVIDER)
        assert result is None

    def test_boot_wires_feedback_to_provider(self):
        from steward.types import ChamberProvider

        provider = MagicMock(spec=ChamberProvider)
        boot(tools=[_DummyTool()], provider=provider)
        provider.set_feedback.assert_called_once()

    def test_boot_no_tools(self):
        """Boot with no tools should work but integrity check warns."""
        boot(tools=[])  # Should not raise

    def test_boot_logs_quarantine_warning_when_messages_pending(self, tmp_path, caplog, monkeypatch):
        fed_dir = tmp_path / "data" / "federation"
        fed_dir.mkdir(parents=True)
        quarantine_dir = fed_dir / "quarantine"
        quarantine_dir.mkdir()
        (quarantine_dir / "index.json").write_text(json.dumps(["a", "b"]))
        monkeypatch.setenv("STEWARD_FEDERATION_DIR", str(fed_dir))

        caplog.set_level("WARNING")
        boot(tools=[_DummyTool()], cwd=str(tmp_path))

        assert "System Boot: NADI Queue Active. WARNING: 2 messages in quarantine requiring attention." in caplog.text

    def test_boot_logs_quarantine_critical_when_backlog_exceeds_threshold(self, tmp_path, caplog, monkeypatch):
        fed_dir = tmp_path / "data" / "federation"
        fed_dir.mkdir(parents=True)
        quarantine_dir = fed_dir / "quarantine"
        quarantine_dir.mkdir()
        (quarantine_dir / "index.json").write_text(json.dumps([str(i) for i in range(51)]))
        monkeypatch.setenv("STEWARD_FEDERATION_DIR", str(fed_dir))

        caplog.set_level("WARNING")
        boot(tools=[_DummyTool()], cwd=str(tmp_path))

        assert any(record.levelname == "CRITICAL" for record in caplog.records)

    def test_boot_generates_genesis_node_keys_when_missing(self, tmp_path, monkeypatch):
        fed_dir = tmp_path / "data" / "federation"
        fed_dir.mkdir(parents=True)
        monkeypatch.setenv("STEWARD_FEDERATION_DIR", str(fed_dir))

        boot(tools=[_DummyTool()], cwd=str(tmp_path))

        key_path = fed_dir / ".node_keys.json"
        assert key_path.exists()
        payload = json.loads(key_path.read_text())
        assert payload["node_id"].startswith("ag_")
        assert payload["public_key"]
        assert payload["private_key"]


class TestIntegrity:
    """Test integrity check functions."""

    def test_integrity_passes_with_tools(self):
        boot(tools=[_DummyTool()])
        checker = ServiceRegistry.get(SVC_INTEGRITY)
        report = checker.check_all()
        assert report.passed_count >= 1

    def test_integrity_with_provider(self):
        provider = MagicMock()
        provider.invoke = MagicMock()
        boot(tools=[_DummyTool()], provider=provider)
        checker = ServiceRegistry.get(SVC_INTEGRITY)
        report = checker.check_all()
        assert report.passed_count >= 2  # tools + provider


class TestToolDescriptionsForLLM:
    """Test the OpenAI function-calling format conversion."""

    def test_single_tool_conversion(self):
        boot(tools=[_DummyTool()])
        registry = ServiceRegistry.get(SVC_TOOL_REGISTRY)
        descs = tool_descriptions_for_llm(registry)
        assert len(descs) == 1
        func = descs[0]
        assert func["type"] == "function"
        assert func["function"]["name"] == "dummy"
        params = func["function"]["parameters"]
        assert params["type"] == "object"
        assert "arg" in params["properties"]
        assert "opt" in params["properties"]
        assert "arg" in params["required"]
        assert "opt" not in params["required"]

    def test_descriptions_include_types(self):
        boot(tools=[_DummyTool()])
        registry = ServiceRegistry.get(SVC_TOOL_REGISTRY)
        descs = tool_descriptions_for_llm(registry)
        props = descs[0]["function"]["parameters"]["properties"]
        assert props["arg"]["type"] == "string"
        assert props["opt"]["type"] == "integer"

    def test_empty_registry(self):
        boot(tools=[])
        registry = ServiceRegistry.get(SVC_TOOL_REGISTRY)
        descs = tool_descriptions_for_llm(registry)
        assert descs == []


class TestEphemeralStorageWiring:
    """Test EphemeralStorage (SVC_CACHE) wiring."""

    def test_boot_registers_cache(self):
        boot(tools=[_DummyTool()])
        cache = ServiceRegistry.get(SVC_CACHE)
        assert cache is not None

    def test_cache_is_ephemeral_storage(self):
        from vibe_core.playbook.ephemeral_storage import EphemeralStorage

        boot(tools=[_DummyTool()])
        cache = ServiceRegistry.get(SVC_CACHE)
        assert isinstance(cache, EphemeralStorage)

    def test_cache_set_and_get(self):
        boot(tools=[_DummyTool()])
        cache = ServiceRegistry.get(SVC_CACHE)
        cache.set("test_key", {"value": 42}, ttl_seconds=60)
        result = cache.get("test_key")
        assert result == {"value": 42}

    def test_cache_stats(self):
        boot(tools=[_DummyTool()])
        cache = ServiceRegistry.get(SVC_CACHE)
        cache.set("k1", "v1")
        cache.get("k1")  # hit
        cache.get("missing")  # miss
        stats = cache.get_stats()
        assert stats["hits"] >= 1
        assert stats["misses"] >= 1
        assert stats["hit_rate"] > 0

    def test_cache_make_key_deterministic(self):
        from vibe_core.playbook.ephemeral_storage import EphemeralStorage

        k1 = EphemeralStorage.make_cache_key("tool_descriptions", "steward")
        k2 = EphemeralStorage.make_cache_key("tool_descriptions", "steward")
        assert k1 == k2  # Same inputs → same key


class TestDiamondProtocolDeferred:
    """Diamond is now ACTIVE — TDD enforcement via RED/GREEN gates."""

    def test_diamond_registered_at_boot(self):
        boot(tools=[_DummyTool()])
        diamond = ServiceRegistry.get(SVC_DIAMOND)
        assert diamond is not None


class TestVajraWiringChecks:
    """Test Vajra-style wiring integrity checks."""

    def test_integrity_checks_cache_wired(self):
        boot(tools=[_DummyTool()])
        checker = ServiceRegistry.get(SVC_INTEGRITY)
        report = checker.check_all()
        # vajra_cache_wired should pass
        names = [i.checker_name for i in report.issues]
        assert "vajra_cache_wired" not in names  # No issue = pass

    def test_integrity_checks_diamond_deferred(self):
        """Diamond integrity check is deferred — not registered."""
        boot(tools=[_DummyTool()])
        checker = ServiceRegistry.get(SVC_INTEGRITY)
        report = checker.check_all()
        names = [i.checker_name for i in report.issues]
        assert "vajra_diamond_wired" not in names  # Check doesn't exist anymore

    def test_integrity_checks_attention_wired(self):
        boot(tools=[_DummyTool()])
        checker = ServiceRegistry.get(SVC_INTEGRITY)
        report = checker.check_all()
        names = [i.checker_name for i in report.issues]
        assert "vajra_attention_wired" not in names

    def test_all_vajra_checks_pass(self):
        """All Vajra wiring checks should pass after clean boot."""
        boot(tools=[_DummyTool()])
        checker = ServiceRegistry.get(SVC_INTEGRITY)
        report = checker.check_all()
        vajra_issues = [i for i in report.issues if "vajra" in i.checker_name]
        assert len(vajra_issues) == 0, f"Vajra violations: {vajra_issues}"
