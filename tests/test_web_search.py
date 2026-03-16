"""Tests for steward/tools/web_search.py — WebSearchTool."""

from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# Ensure tavily module exists for patching (may not be installed in test env)
if "tavily" not in sys.modules:
    _mock_tavily = ModuleType("tavily")
    _mock_tavily.TavilyClient = None  # type: ignore[attr-defined]  # Patched per-test
    sys.modules["tavily"] = _mock_tavily

from steward.tools.web_search import WebSearchTool


class TestWebSearchTool:
    """Test WebSearchTool."""

    def setup_method(self):
        self.tool = WebSearchTool()

    def test_name(self):
        assert self.tool.name == "web_search"

    def test_description(self):
        assert "search" in self.tool.description.lower()

    def test_parameters_schema(self):
        schema = self.tool.parameters_schema
        assert "query" in schema
        assert schema["query"]["required"] is True

    def test_validate_missing_query(self):
        with pytest.raises(ValueError, match="Missing"):
            self.tool.validate({})

    def test_validate_empty_query(self):
        with pytest.raises(ValueError, match="empty"):
            self.tool.validate({"query": "  "})

    def test_validate_non_string(self):
        with pytest.raises(TypeError, match="string"):
            self.tool.validate({"query": 123})

    def test_validate_ok(self):
        self.tool.validate({"query": "python asyncio"})  # Should not raise

    def test_execute_no_api_key(self):
        # Ensure key is not set
        env = dict(os.environ)
        env.pop("TAVILY_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            result = self.tool.execute({"query": "test"})
            assert not result.success
            assert "TAVILY_API_KEY" in result.error

    def test_execute_with_results(self):
        mock_response = {
            "answer": "Python is great",
            "results": [
                {
                    "title": "Python Docs",
                    "url": "https://docs.python.org",
                    "content": "Official Python documentation",
                },
                {
                    "title": "Real Python",
                    "url": "https://realpython.com",
                    "content": "Python tutorials",
                },
            ],
        }

        mock_client = MagicMock()
        mock_client.search.return_value = mock_response

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            with patch("tavily.TavilyClient", return_value=mock_client):
                result = self.tool.execute({"query": "python"})
                assert result.success
                assert "Python" in result.output
                assert result.metadata["result_count"] == 2
                mock_client.search.assert_called_once()

    def test_execute_no_results(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            with patch("tavily.TavilyClient", return_value=mock_client):
                result = self.tool.execute({"query": "xyznonexistent"})
                assert result.success
                assert "No results" in result.output

    def test_execute_api_error(self):
        mock_client = MagicMock()
        mock_client.search.side_effect = RuntimeError("API rate limited")

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            with patch("tavily.TavilyClient", return_value=mock_client):
                result = self.tool.execute({"query": "test"})
                assert not result.success
                assert "rate limited" in result.error

    def test_execute_answer_included(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "answer": "42 is the answer",
            "results": [{"title": "T", "url": "http://x", "content": "C"}],
        }

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            with patch("tavily.TavilyClient", return_value=mock_client):
                result = self.tool.execute({"query": "meaning of life"})
                assert result.success
                assert "42 is the answer" in result.output

    def test_execute_long_content_truncated(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "T", "url": "http://x", "content": "x" * 600}],
        }

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            with patch("tavily.TavilyClient", return_value=mock_client):
                result = self.tool.execute({"query": "test"})
                assert result.success
                assert "..." in result.output

    def test_max_results_capped(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            with patch("tavily.TavilyClient", return_value=mock_client):
                self.tool.execute({"query": "test", "max_results": 20})
                call_args = mock_client.search.call_args
                assert call_args.kwargs.get("max_results", call_args[1].get("max_results", 0)) <= 10
