# Add a New Tool
trigger: tool, new tool, create tool, add tool
---
To add a new tool to steward:

1. Create `steward/tools/<tool_name>.py` implementing `vibe_core.tools.tool_protocol.Tool`:
   - `name` property → tool name string
   - `description` property → what the tool does (for LLM)
   - `parameters_schema` property → dict of parameter definitions
   - `validate(parameters)` → raise ValueError on bad input
   - `execute(parameters)` → return `ToolResult(success=bool, output=str)`

2. Register in `steward/tools/__init__.py`:
   - Import the new tool class
   - Add to `__all__`

3. Add to `steward/agent.py` `_builtin_tools()`:
   - Import at top
   - Add instance to the return list

4. Write tests in `tests/test_<tool_name>.py`

5. If the tool needs a new dependency, add to `pyproject.toml` optional-dependencies.
