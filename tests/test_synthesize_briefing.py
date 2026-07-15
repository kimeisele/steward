import importlib
from unittest.mock import MagicMock

import pytest

from steward.services import SVC_PROVIDER
from steward.tools.synthesize_briefing import SynthesizeBriefingTool
from tests.fakes import FakeLLM, FakeResponse
from vibe_core.di import ServiceRegistry


@pytest.fixture
def synthesis_sources(monkeypatch):
    annotations = importlib.import_module("steward.annotations")
    monkeypatch.setattr("steward.context_bridge.assemble_context", lambda _cwd: {})
    monkeypatch.setattr("steward.context_bridge.collect_architecture_metadata", lambda: {})
    monkeypatch.setattr(annotations, "collect_validated", lambda: [])


@pytest.mark.parametrize("parameters", [{}, {"output_path": "stdout"}])
def test_preview_modes_never_write(parameters, tmp_path, synthesis_sources):
    provider = FakeLLM([FakeResponse(content="# preview only")])
    ServiceRegistry.register(SVC_PROVIDER, provider)

    result = SynthesizeBriefingTool(cwd=str(tmp_path)).execute(parameters)

    assert result.success
    assert result.output == "# preview only"
    assert result.metadata["mode"] == "preview"
    assert result.metadata["canonical"] is False
    assert not (tmp_path / "CLAUDE.md").exists()


@pytest.mark.parametrize("target_kind", ["root", "relative", "traversal", "absolute"])
def test_persisted_output_is_rejected_before_assembly(monkeypatch, tmp_path, target_kind):
    monkeypatch.chdir(tmp_path)
    output_paths = {
        "root": "CLAUDE.md",
        "relative": "preview.md",
        "traversal": "nested/../escape.md",
        "absolute": str(tmp_path / "absolute.md"),
    }
    output_path = output_paths[target_kind]
    assemble = MagicMock()
    monkeypatch.setattr("steward.context_bridge.assemble_context", assemble)
    provider = FakeLLM([FakeResponse(content="# must not run")])
    ServiceRegistry.register(SVC_PROVIDER, provider)

    result = SynthesizeBriefingTool(cwd=str(tmp_path)).execute({"output_path": output_path})

    assert not result.success
    assemble.assert_not_called()
    assert provider.call_count == 0
    assert not (tmp_path / "CLAUDE.md").exists()


def test_provider_failure_does_not_write(tmp_path, synthesis_sources):
    result = SynthesizeBriefingTool(cwd=str(tmp_path)).execute({})

    assert not result.success
    assert not (tmp_path / "CLAUDE.md").exists()
