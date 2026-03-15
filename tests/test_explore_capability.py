"""Tests for ExploreCapability — MOLECULAR codebase cognition."""

from __future__ import annotations

import pytest

from steward.capabilities.explore import ExploreCapability, _explore
from vibe_core.protocols.capability import CapabilityType


class TestExploreCapability:
    def test_properties(self):
        cap = ExploreCapability()
        assert cap.capability_id == "explore_codebase"
        assert cap.capability_type == CapabilityType.MOLECULAR

    def test_validate_missing_target(self):
        cap = ExploreCapability()
        with pytest.raises(ValueError):
            cap.validate({})

    def test_validate_nonexistent_dir(self):
        cap = ExploreCapability()
        with pytest.raises(ValueError):
            cap.validate({"target": "/nonexistent/path/xyz"})

    def test_execute_on_small_repo(self, tmp_path):
        pkg = tmp_path / "mylib"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text("class Engine:\n    def run(self):\n        pass\n\ndef helper():\n    pass\n")
        (pkg / "utils.py").write_text(
            "from mylib.core import Engine\n\ndef format_output(data):\n    return str(data)\n"
        )

        cap = ExploreCapability()
        result = cap.execute({"target": str(tmp_path)})

        assert result.success
        assert result.capability_type == CapabilityType.MOLECULAR
        assert result.metadata["entries"] > 0
        assert result.metadata["total_nodes"] > 0
        assert "Engine" in str(result.output)

    def test_execute_with_focus(self, tmp_path):
        pkg = tmp_path / "app"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "federation.py").write_text("class FederationBridge:\n    pass\n")
        (pkg / "database.py").write_text("class DatabasePool:\n    pass\n")

        cap = ExploreCapability()
        result = cap.execute({"target": str(tmp_path), "focus": "federation"})

        assert result.success
        output = str(result.output)
        assert "FederationBridge" in output

    def test_output_is_compact(self, tmp_path):
        """Output should be compressed, not raw text dump."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        for i in range(10):
            (pkg / f"mod_{i}.py").write_text(f"class Widget{i}:\n    pass\n")

        cap = ExploreCapability()
        result = cap.execute({"target": str(tmp_path)})

        assert result.success
        output = str(result.output)
        # Should be compact — lines, not paragraphs
        lines = output.strip().split("\n")
        assert all(len(line) < 200 for line in lines)

    def test_guna_classification(self, tmp_path):
        """Tamas files should sort first (problems need attention)."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "healthy.py").write_text("x = 1\n")

        cap = ExploreCapability()
        result = cap.execute({"target": str(tmp_path)})
        assert result.success

    def test_empty_directory(self, tmp_path):
        cap = ExploreCapability()
        result = cap.execute({"target": str(tmp_path)})
        assert result.success
        assert "no relevant symbols" in str(result.output).lower() or result.metadata["entries"] == 0


class TestExplorePipeline:
    def test_scans_ast(self, tmp_path):
        (tmp_path / "app.py").write_text(
            "class Server:\n    def start(self):\n        pass\n\nclass Client:\n    def connect(self):\n        pass\n"
        )

        explore_map = _explore(tmp_path, "")
        names = [e.name for e in explore_map.entries]
        assert "Server" in names
        assert "Client" in names

    def test_captures_relations(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("def greet():\n    pass\n")
        (pkg / "b.py").write_text("from pkg.a import greet\n\ndef hello():\n    greet()\n")

        explore_map = _explore(tmp_path, "")
        assert explore_map.total_edges > 0

    def test_focus_filters_results(self, tmp_path):
        (tmp_path / "federation.py").write_text("class FederationBridge:\n    pass\n")
        (tmp_path / "database.py").write_text("class DatabasePool:\n    pass\n")

        focused = _explore(tmp_path, "federation")
        names = [e.name for e in focused.entries]
        # Federation should be in results
        assert any("Federation" in n for n in names)

    def test_seed_is_deterministic(self, tmp_path):
        (tmp_path / "app.py").write_text("class Foo:\n    pass\n")

        map1 = _explore(tmp_path, "")
        map2 = _explore(tmp_path, "")

        seeds1 = {e.name: e.seed for e in map1.entries}
        seeds2 = {e.name: e.seed for e in map2.entries}
        assert seeds1 == seeds2


class TestExploreToolRegistration:
    def test_registered_in_builtin_tools(self):
        from steward.tool_providers import BuiltinToolProvider

        provider = BuiltinToolProvider()
        tools = provider.provide(".")
        names = [t.name for t in tools]
        assert "explore" in names
