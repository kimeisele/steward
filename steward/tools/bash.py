"""
Bash Tool — Execute shell commands.

Safety: Commands run in a subprocess with timeout.
No shell=True escaping issues because we use subprocess directly.
"""

from __future__ import annotations

import subprocess
from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolResult


# Commands that are NEVER allowed — destructive or dangerous
_BLOCKED_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=",
    "format c:",
    "> /dev/sd",
    "chmod -r 777 /",
    ":(){ :|:& };:",
    "curl | bash",
    "curl | sh",
    "wget | bash",
    "wget | sh",
    "eval $(curl",
    "eval $(wget",
]


class BashTool(Tool):
    """Execute a bash command and return stdout/stderr.

    Safety: Blocks known destructive commands. Runs in subprocess with timeout.
    """

    def __init__(self, timeout: int = 120, cwd: str | None = None) -> None:
        super().__init__()
        self._timeout = timeout
        self._cwd = cwd

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Execute a bash command in a shell. Returns stdout and stderr. "
            "Use for running tests, git commands, installing packages, "
            "or any system operation."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "command": {
                "type": "string",
                "required": True,
                "description": "The bash command to execute",
            },
            "timeout": {
                "type": "integer",
                "required": False,
                "description": "Timeout in seconds (default: 120). Increase for long builds or tests.",
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        if "command" not in parameters:
            raise ValueError("Missing required parameter: command")
        if not isinstance(parameters["command"], str):
            raise TypeError("command must be a string")
        if not parameters["command"].strip():
            raise ValueError("command must not be empty")
        # Block known destructive commands
        cmd_lower = parameters["command"].lower()
        for pattern in _BLOCKED_PATTERNS:
            if pattern in cmd_lower:
                raise ValueError(f"Blocked dangerous command pattern: {pattern}")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        command = parameters["command"]
        timeout = parameters.get("timeout", self._timeout)

        try:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self._cwd,
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}" if output else result.stderr

            return ToolResult(
                success=result.returncode == 0,
                output=output.strip() if output else "",
                error=f"Exit code: {result.returncode}" if result.returncode != 0 else None,
                metadata={"exit_code": result.returncode},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error=f"Command timed out after {timeout}s")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
