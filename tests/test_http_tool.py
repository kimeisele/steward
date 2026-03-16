"""Tests for the HTTP tool — SSRF protection, validation, execution."""

import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from steward.tools.http import HttpTool, _is_private_ip


class TestHttpToolValidation:
    """Test parameter validation and SSRF protection."""

    def setup_method(self):
        self.tool = HttpTool()

    def test_name(self):
        assert self.tool.name == "http"

    def test_description_not_empty(self):
        assert len(self.tool.description) > 20

    def test_parameters_schema_has_url(self):
        schema = self.tool.parameters_schema
        assert "url" in schema
        assert schema["url"]["required"] is True

    def test_validate_missing_url(self):
        with pytest.raises(ValueError, match="Missing required parameter: url"):
            self.tool.validate({})

    def test_validate_empty_url(self):
        with pytest.raises(ValueError, match="url must not be empty"):
            self.tool.validate({"url": "  "})

    def test_validate_non_string_url(self):
        with pytest.raises(TypeError, match="url must be a string"):
            self.tool.validate({"url": 123})

    def test_validate_ftp_scheme_blocked(self):
        with pytest.raises(ValueError, match="URL scheme must be http or https"):
            self.tool.validate({"url": "ftp://example.com/file"})

    def test_validate_file_scheme_blocked(self):
        with pytest.raises(ValueError, match="URL scheme must be http or https"):
            self.tool.validate({"url": "file:///etc/passwd"})

    def test_validate_no_hostname(self):
        with pytest.raises(ValueError, match="URL must have a hostname"):
            self.tool.validate({"url": "http://"})

    def test_validate_bad_method(self):
        with pytest.raises(ValueError, match="Unsupported HTTP method"):
            self.tool.validate({"url": "https://example.com", "method": "TRACE"})

    @patch("steward.tools.http._is_private_ip", return_value=False)
    def test_validate_valid_methods(self, _mock_ip):
        for method in ["GET", "POST", "PUT", "DELETE", "HEAD", "PATCH"]:
            self.tool.validate({"url": "https://example.com", "method": method})

    @patch("steward.tools.http._is_private_ip", return_value=True)
    def test_validate_blocks_private_ip(self, mock_ip):
        with pytest.raises(ValueError, match="private/internal IP"):
            self.tool.validate({"url": "http://internal-server.local/api"})

    def test_validate_accepts_public_url(self):
        # Mock _is_private_ip to return False (avoid DNS resolution in tests)
        with patch("steward.tools.http._is_private_ip", return_value=False):
            self.tool.validate({"url": "https://api.github.com/repos"})


class TestPrivateIPDetection:
    """Test SSRF protection via private IP detection."""

    def test_localhost_is_private(self):
        assert _is_private_ip("127.0.0.1") is True

    def test_private_class_a(self):
        assert _is_private_ip("10.0.0.1") is True

    def test_private_class_b(self):
        assert _is_private_ip("172.16.0.1") is True

    def test_private_class_c(self):
        assert _is_private_ip("192.168.1.1") is True

    def test_unresolvable_is_not_private(self):
        # Can't resolve → not marked as private (will fail at connect time)
        assert _is_private_ip("definitely-not-a-real-host-12345.invalid") is False


class TestHttpToolExecution:
    """Test HTTP execution with mocked responses."""

    def setup_method(self):
        self.tool = HttpTool(timeout=5)

    @patch("steward.tools.http.urllib.request.urlopen")
    @patch("steward.tools.http._is_private_ip", return_value=False)
    def test_successful_get(self, mock_ip, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = self.tool.execute({"url": "https://api.example.com/data"})
        assert result.success is True
        assert '"ok": true' in result.output
        assert result.metadata["status_code"] == 200

    @patch("steward.tools.http.urllib.request.urlopen")
    @patch("steward.tools.http._is_private_ip", return_value=False)
    def test_post_with_json_body(self, mock_ip, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.read.return_value = b'{"id": 42}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = self.tool.execute(
            {
                "url": "https://api.example.com/items",
                "method": "POST",
                "body": '{"name": "test"}',
            }
        )
        assert result.success is True
        assert result.metadata["status_code"] == 201

    @patch("steward.tools.http.urllib.request.urlopen")
    @patch("steward.tools.http._is_private_ip", return_value=False)
    def test_http_error(self, mock_ip, mock_urlopen):
        error = urllib.error.HTTPError("https://example.com", 404, "Not Found", {}, None)
        error.read = MagicMock(return_value=b"page not found")
        mock_urlopen.side_effect = error

        result = self.tool.execute({"url": "https://example.com/missing"})
        assert result.success is False
        assert "404" in result.error
        assert result.metadata["status_code"] == 404

    @patch("steward.tools.http.urllib.request.urlopen")
    @patch("steward.tools.http._is_private_ip", return_value=False)
    def test_url_error(self, mock_ip, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Name resolution failed")

        result = self.tool.execute({"url": "https://nonexistent.invalid/api"})
        assert result.success is False
        assert "URL error" in result.error

    @patch("steward.tools.http.urllib.request.urlopen")
    @patch("steward.tools.http._is_private_ip", return_value=False)
    def test_timeout_error(self, mock_ip, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError()

        result = self.tool.execute({"url": "https://slow.example.com"})
        assert result.success is False
        assert "timed out" in result.error

    @patch("steward.tools.http.urllib.request.urlopen")
    @patch("steward.tools.http._is_private_ip", return_value=False)
    def test_truncation_on_large_response(self, mock_ip, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {"Content-Type": "text/plain"}
        # Return exactly max bytes to simulate truncation
        mock_resp.read.return_value = b"x" * 1_048_576
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = self.tool.execute({"url": "https://example.com/huge"})
        assert result.success is True
        assert result.metadata["truncated"] is True
        assert "TRUNCATED" in result.output

    @patch("steward.tools.http.urllib.request.urlopen")
    @patch("steward.tools.http._is_private_ip", return_value=False)
    def test_custom_headers(self, mock_ip, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_resp.read.return_value = b"ok"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = self.tool.execute(
            {
                "url": "https://api.example.com",
                "headers": {"Authorization": "Bearer token123"},
            }
        )
        assert result.success is True

        # Verify the request was constructed with custom headers
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.get_header("Authorization") == "Bearer token123"

    def test_to_llm_description(self):
        desc = self.tool.to_llm_description()
        assert desc["name"] == "http"
        assert "parameters" in desc
        assert "url" in desc["parameters"]
