"""Tests for file-related tools: read_file, write_file, edit_file, glob, grep, bash."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from steward.tools.bash import BashTool, _BLOCKED_PATTERNS
from steward.tools.edit import EditTool
from steward.tools.glob import GlobTool
from steward.tools.grep import GrepTool
from steward.tools.read_file import ReadFileTool
from steward.tools.write_file import WriteFileTool


# ── ReadFileTool ────────────────────────────────────────────────────


class TestReadFileTool:
    def setup_method(self):
        self.tool = ReadFileTool()

    def test_name_and_schema(self):
        assert self.tool.name == "read_file"
        assert "path" in self.tool.parameters_schema

    def test_validate_missing_path(self):
        with pytest.raises(ValueError, match="path"):
            self.tool.validate({})

    def test_validate_ok(self):
        self.tool.validate({"path": "/tmp/test.txt"})

    def test_read_nonexistent_file(self):
        result = self.tool.execute({"path": "/tmp/_steward_test_nonexistent_xyz"})
        assert not result.success
        assert "not found" in result.error.lower()

    def test_read_directory(self, tmp_path):
        result = self.tool.execute({"path": str(tmp_path)})
        assert not result.success
        assert "Not a file" in result.error

    def test_read_file_contents(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("line one\nline two\nline three\n")
        result = self.tool.execute({"path": str(f)})
        assert result.success
        assert "line one" in result.output
        assert "line two" in result.output
        assert result.metadata["total_lines"] == 3

    def test_read_with_offset_and_limit(self, tmp_path):
        f = tmp_path / "lines.txt"
        f.write_text("\n".join(f"L{i}" for i in range(1, 21)))
        result = self.tool.execute({"path": str(f), "offset": 5, "limit": 3})
        assert result.success
        assert "L5" in result.output
        assert "L7" in result.output
        assert result.metadata["returned_lines"] == 3

    def test_long_line_truncation(self, tmp_path):
        f = tmp_path / "long.txt"
        f.write_text("x" * 3000)
        result = self.tool.execute({"path": str(f)})
        assert result.success
        assert "[truncated]" in result.output


# ── WriteFileTool ───────────────────────────────────────────────────


class TestWriteFileTool:
    def setup_method(self):
        self.tool = WriteFileTool()

    def test_name_and_schema(self):
        assert self.tool.name == "write_file"
        assert "path" in self.tool.parameters_schema
        assert "content" in self.tool.parameters_schema

    def test_validate_missing_path(self):
        with pytest.raises(ValueError, match="path"):
            self.tool.validate({"content": "x"})

    def test_validate_missing_content(self):
        with pytest.raises(ValueError, match="content"):
            self.tool.validate({"path": "/tmp/x"})

    def test_write_new_file(self, tmp_path):
        target = tmp_path / "out.txt"
        result = self.tool.execute({"path": str(target), "content": "hello world"})
        assert result.success
        assert target.read_text() == "hello world"
        assert result.metadata["bytes_written"] == 11

    def test_write_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "a" / "b" / "c" / "deep.txt"
        result = self.tool.execute({"path": str(target), "content": "deep"})
        assert result.success
        assert target.read_text() == "deep"

    def test_overwrite_existing(self, tmp_path):
        target = tmp_path / "exist.txt"
        target.write_text("old")
        result = self.tool.execute({"path": str(target), "content": "new"})
        assert result.success
        assert target.read_text() == "new"


# ── EditTool ────────────────────────────────────────────────────────


class TestEditTool:
    def setup_method(self):
        self.tool = EditTool()

    def test_name_and_schema(self):
        assert self.tool.name == "edit_file"
        assert "old_string" in self.tool.parameters_schema

    def test_validate_missing_params(self):
        with pytest.raises(ValueError, match="path"):
            self.tool.validate({"old_string": "a", "new_string": "b"})

    def test_validate_same_strings(self):
        with pytest.raises(ValueError, match="different"):
            self.tool.validate({"path": "x", "old_string": "same", "new_string": "same"})

    def test_edit_nonexistent_file(self):
        result = self.tool.execute({"path": "/tmp/_steward_nonexist", "old_string": "a", "new_string": "b"})
        assert not result.success

    def test_edit_not_found(self, tmp_path):
        f = tmp_path / "e.txt"
        f.write_text("hello world")
        result = self.tool.execute({"path": str(f), "old_string": "xyz", "new_string": "abc"})
        assert not result.success
        assert "not found" in result.error

    def test_edit_ambiguous(self, tmp_path):
        f = tmp_path / "dup.txt"
        f.write_text("aa\naa\n")
        result = self.tool.execute({"path": str(f), "old_string": "aa", "new_string": "bb"})
        assert not result.success
        assert "2 times" in result.error

    def test_edit_success(self, tmp_path):
        f = tmp_path / "ok.txt"
        f.write_text("hello world\ngoodbye moon\n")
        result = self.tool.execute({"path": str(f), "old_string": "hello world", "new_string": "hi earth"})
        assert result.success
        assert f.read_text() == "hi earth\ngoodbye moon\n"


# ── GlobTool ────────────────────────────────────────────────────────


class TestGlobTool:
    def test_name_and_schema(self):
        tool = GlobTool()
        assert tool.name == "glob"
        assert "pattern" in tool.parameters_schema

    def test_validate_missing_pattern(self):
        with pytest.raises(ValueError, match="pattern"):
            GlobTool().validate({})

    def test_glob_finds_files(self, tmp_path):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        (tmp_path / "c.txt").write_text("z")
        tool = GlobTool(cwd=str(tmp_path))
        result = tool.execute({"pattern": "*.py"})
        assert result.success
        assert result.metadata["match_count"] == 2
        assert "a.py" in result.output
        assert "b.py" in result.output
        assert "c.txt" not in result.output

    def test_glob_no_matches(self, tmp_path):
        tool = GlobTool(cwd=str(tmp_path))
        result = tool.execute({"pattern": "*.xyz"})
        assert result.success
        assert "No matches" in result.output

    def test_glob_custom_path(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "f.rs").write_text("fn main()")
        tool = GlobTool()
        result = tool.execute({"pattern": "*.rs", "path": str(sub)})
        assert result.success
        assert "f.rs" in result.output

    def test_glob_invalid_path(self):
        tool = GlobTool()
        result = tool.execute({"pattern": "*.py", "path": "/tmp/_steward_no_such_dir_xyz"})
        assert not result.success


# ── GrepTool ────────────────────────────────────────────────────────


class TestGrepTool:
    def test_name_and_schema(self):
        tool = GrepTool()
        assert tool.name == "grep"
        assert "pattern" in tool.parameters_schema

    def test_validate_missing_pattern(self):
        with pytest.raises(ValueError, match="pattern"):
            GrepTool().validate({})

    def test_validate_invalid_regex(self):
        with pytest.raises(ValueError, match="regex"):
            GrepTool().validate({"pattern": "[invalid"})

    def test_grep_finds_matches(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    return 42\ndef bye():\n    pass\n")
        tool = GrepTool(cwd=str(tmp_path))
        result = tool.execute({"pattern": "def \\w+"})
        assert result.success
        assert result.metadata["match_count"] == 2
        assert "hello" in result.output
        assert "bye" in result.output

    def test_grep_no_matches(self, tmp_path):
        (tmp_path / "empty.py").write_text("nothing here\n")
        tool = GrepTool(cwd=str(tmp_path))
        result = tool.execute({"pattern": "ZZZZZ"})
        assert result.success
        assert "No matches" in result.output

    def test_grep_single_file(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("alpha\nbeta\ngamma\n")
        tool = GrepTool()
        result = tool.execute({"pattern": "eta", "path": str(f)})
        assert result.success
        assert "beta" in result.output

    def test_grep_with_glob_filter(self, tmp_path):
        (tmp_path / "a.py").write_text("target_line\n")
        (tmp_path / "b.txt").write_text("target_line\n")
        tool = GrepTool(cwd=str(tmp_path))
        result = tool.execute({"pattern": "target_line", "glob": "*.py"})
        assert result.success
        assert "a.py" in result.output
        assert "b.txt" not in result.output

    def test_grep_path_not_found(self):
        tool = GrepTool()
        result = tool.execute({"pattern": "x", "path": "/tmp/_steward_no_such_xyz"})
        assert not result.success


# ── BashTool ────────────────────────────────────────────────────────


class TestBashTool:
    def setup_method(self):
        self.tool = BashTool(timeout=10)

    def test_name_and_schema(self):
        assert self.tool.name == "bash"
        assert "command" in self.tool.parameters_schema

    def test_validate_missing_command(self):
        with pytest.raises(ValueError, match="command"):
            self.tool.validate({})

    def test_validate_empty_command(self):
        with pytest.raises(ValueError, match="empty"):
            self.tool.validate({"command": "  "})

    def test_validate_non_string(self):
        with pytest.raises(TypeError, match="string"):
            self.tool.validate({"command": 123})

    def test_blocked_commands(self):
        """All blocked patterns should raise when used directly."""
        for pattern in _BLOCKED_PATTERNS:
            with pytest.raises(ValueError, match="Blocked"):
                self.tool.validate({"command": pattern})

    def test_execute_echo(self):
        result = self.tool.execute({"command": "echo hello"})
        assert result.success
        assert "hello" in result.output

    def test_execute_failing_command(self):
        result = self.tool.execute({"command": "false"})
        assert not result.success
        assert result.metadata["exit_code"] != 0

    def test_execute_with_cwd(self, tmp_path):
        tool = BashTool(cwd=str(tmp_path))
        result = tool.execute({"command": "pwd"})
        assert result.success
        assert str(tmp_path) in result.output

    def test_timeout_respected(self):
        tool = BashTool(timeout=1)
        result = tool.execute({"command": "sleep 10"})
        assert not result.success
        assert "timed out" in result.error.lower()
