"""Tests for context_bridge — steward's living state assembly."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from steward.context_bridge import (
    _atomic_write,
    assemble_context,
    collect_architecture_metadata,
    write_context_json,
)


class TestAssembleContext:
    def test_returns_dict_with_required_keys(self, tmp_path):
        with patch("steward.context_bridge.Path.cwd", return_value=tmp_path):
            ctx = assemble_context(cwd=str(tmp_path))
        assert isinstance(ctx, dict)
        assert "version" in ctx
        assert "timestamp" in ctx
        assert "senses" in ctx
        assert "health" in ctx
        assert "gaps" in ctx

    def test_version_is_current(self, tmp_path):
        ctx = assemble_context(cwd=str(tmp_path))
        assert ctx["version"] == 1

    def test_timestamp_is_numeric(self, tmp_path):
        ctx = assemble_context(cwd=str(tmp_path))
        assert isinstance(ctx["timestamp"], (int, float))
        assert ctx["timestamp"] > 0


class TestCollectArchitectureMetadata:
    def test_returns_dict_with_services(self):
        metadata = collect_architecture_metadata()
        assert isinstance(metadata, dict)
        assert "services" in metadata

    def test_services_are_strings(self):
        metadata = collect_architecture_metadata()
        services = metadata.get("services", [])
        assert all(isinstance(s, str) for s in services)


class TestWriteContextJson:
    def test_writes_to_steward_dir(self, tmp_path):
        ctx = {"version": 1, "data": "test"}
        result = write_context_json(str(tmp_path), ctx)
        assert result is True
        path = tmp_path / ".steward" / "context.json"
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["data"] == "test"

    def test_dedup_skips_unchanged(self, tmp_path):
        ctx = {"version": 1, "data": "test"}
        write_context_json(str(tmp_path), ctx)
        # Second write with same content should be skipped
        result = write_context_json(str(tmp_path), ctx)
        assert result is False

    def test_writes_on_change(self, tmp_path):
        ctx1 = {"version": 1, "data": "v1"}
        write_context_json(str(tmp_path), ctx1)
        ctx2 = {"version": 1, "data": "v2"}
        result = write_context_json(str(tmp_path), ctx2)
        assert result is True


class TestAtomicWrite:
    def test_writes_file(self, tmp_path):
        target = tmp_path / "test.txt"
        _atomic_write(target, "hello world")
        assert target.read_text() == "hello world"

    def test_overwrites_existing(self, tmp_path):
        target = tmp_path / "test.txt"
        target.write_text("old")
        _atomic_write(target, "new")
        assert target.read_text() == "new"

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "sub" / "dir" / "test.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, "content")
        assert target.read_text() == "content"
