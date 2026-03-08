"""
HTTP Tool — Fetch URLs, call APIs, download docs.

Uses urllib (stdlib) — zero new dependencies.
Supports GET, POST, PUT, DELETE with JSON bodies and custom headers.
Safety: blocks internal/private IPs, enforces timeout, limits response size.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from ipaddress import ip_address, ip_network
from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolResult

# Max response body size (1 MB) — prevents OOM on huge downloads
_MAX_RESPONSE_BYTES = 1_048_576

# Default timeout for HTTP requests (seconds)
_DEFAULT_TIMEOUT = 30

# Private/internal IP ranges — never allow requests to these
_BLOCKED_NETWORKS = [
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("127.0.0.0/8"),
    ip_network("169.254.0.0/16"),
    ip_network("::1/128"),
    ip_network("fc00::/7"),
    ip_network("fe80::/10"),
]

# Blocked URL schemes
_ALLOWED_SCHEMES = {"http", "https"}


def _is_private_ip(hostname: str) -> bool:
    """Check if hostname resolves to a private/internal IP."""
    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in addr_info:
            ip = ip_address(sockaddr[0])
            for network in _BLOCKED_NETWORKS:
                if ip in network:
                    return True
    except (socket.gaierror, ValueError):
        pass
    return False


class HttpTool(Tool):
    """Fetch URLs, call REST APIs, download documentation.

    Safety: blocks private IPs (SSRF protection), enforces timeout,
    limits response size to 1 MB.
    """

    def __init__(self, timeout: int = _DEFAULT_TIMEOUT) -> None:
        super().__init__()
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "http"

    @property
    def description(self) -> str:
        return (
            "Make HTTP requests to fetch web pages, call APIs, or download data. "
            "Supports GET, POST, PUT, DELETE with JSON bodies and custom headers. "
            "Use for fetching documentation, API calls, or downloading files."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "url": {
                "type": "string",
                "required": True,
                "description": "The URL to fetch (must be http or https)",
            },
            "method": {
                "type": "string",
                "required": False,
                "description": "HTTP method: GET, POST, PUT, DELETE (default: GET)",
            },
            "headers": {
                "type": "object",
                "required": False,
                "description": "Custom HTTP headers as key-value pairs",
            },
            "body": {
                "type": "string",
                "required": False,
                "description": "Request body (for POST/PUT). JSON string or plain text.",
            },
            "timeout": {
                "type": "integer",
                "required": False,
                "description": f"Request timeout in seconds (default: {_DEFAULT_TIMEOUT})",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if "url" not in parameters:
            raise ValueError("Missing required parameter: url")
        url = parameters["url"]
        if not isinstance(url, str):
            raise TypeError("url must be a string")
        if not url.strip():
            raise ValueError("url must not be empty")

        # Validate scheme
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ValueError(f"URL scheme must be http or https, got: {parsed.scheme!r}")
        if not parsed.hostname:
            raise ValueError("URL must have a hostname")

        # SSRF protection — block private IPs
        if _is_private_ip(parsed.hostname):
            raise ValueError(f"Blocked: {parsed.hostname} resolves to a private/internal IP")

        # Validate method
        method = parameters.get("method", "GET").upper()
        if method not in {"GET", "POST", "PUT", "DELETE", "HEAD", "PATCH"}:
            raise ValueError(f"Unsupported HTTP method: {method}")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        url = parameters["url"]
        method = parameters.get("method", "GET").upper()
        headers = parameters.get("headers", {})
        body = parameters.get("body")
        timeout = parameters.get("timeout", self._timeout)

        try:
            # Build request
            data = None
            if body is not None:
                data = body.encode("utf-8") if isinstance(body, str) else body
                if "Content-Type" not in headers:
                    # Auto-detect JSON
                    try:
                        json.loads(body)
                        headers["Content-Type"] = "application/json"
                    except (json.JSONDecodeError, TypeError):
                        headers["Content-Type"] = "text/plain"

            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            req.add_header("User-Agent", "steward-agent/0.12")

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                resp_headers = dict(resp.headers)
                content_type = resp_headers.get("Content-Type", "")

                # Read with size limit
                body_bytes = resp.read(_MAX_RESPONSE_BYTES)
                truncated = len(body_bytes) == _MAX_RESPONSE_BYTES

                # Decode
                if "text" in content_type or "json" in content_type or "xml" in content_type:
                    charset = "utf-8"
                    if "charset=" in content_type:
                        charset = content_type.split("charset=")[-1].split(";")[0].strip()
                    body_text = body_bytes.decode(charset, errors="replace")
                else:
                    body_text = body_bytes.decode("utf-8", errors="replace")

                output = body_text
                if truncated:
                    output += "\n\n[TRUNCATED — response exceeded 1 MB]"

                return ToolResult(
                    success=True,
                    output=output,
                    metadata={
                        "status_code": status,
                        "content_type": content_type,
                        "content_length": len(body_bytes),
                        "truncated": truncated,
                    },
                )

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read(_MAX_RESPONSE_BYTES).decode("utf-8", errors="replace")
            except Exception:
                pass
            return ToolResult(
                success=False,
                output=error_body if error_body else None,
                error=f"HTTP {e.code}: {e.reason}",
                metadata={"status_code": e.code},
            )
        except urllib.error.URLError as e:
            return ToolResult(success=False, error=f"URL error: {e.reason}")
        except TimeoutError:
            return ToolResult(success=False, error=f"Request timed out after {timeout}s")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
