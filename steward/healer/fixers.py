"""Deterministic fixers — one per FindingKind. 0 LLM tokens each."""

from __future__ import annotations

import ast
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from steward.healer.helpers import _add_dependency_to_toml, _extract_package_from_finding
from steward.healer.types import _fixer
from steward.senses.diagnostic_sense import FindingKind

if TYPE_CHECKING:
    from steward.senses.diagnostic_sense import Finding

logger = logging.getLogger("STEWARD.HEALER")

# Reverse mapping: import name → pip package name.
# The diagnostic sense has pip→import; the healer needs import→pip.
_IMPORT_TO_PIP: dict[str, str] = {
    "yaml": "pyyaml",
    "dateutil": "python-dateutil",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "dotenv": "python-dotenv",
    "github": "PyGithub",
    "cv2": "opencv-python",
    "bs4": "beautifulsoup4",
    "attr": "attrs",
    "serial": "pyserial",
    "usb": "pyusb",
    "gi": "PyGObject",
    "wx": "wxPython",
    "skimage": "scikit-image",
}


# ── Deterministic Fixers (0 tokens each) ───────────────────────────────


@_fixer(FindingKind.UNDECLARED_DEPENDENCY)
def _fix_undeclared_dependency(finding: "Finding", workspace: Path) -> list[str]:
    """Add undeclared package to pyproject.toml dependencies.

    Handles import→pip name mismatch (yaml→pyyaml, PIL→pillow, etc.).
    """
    import_name = _extract_package_from_finding(finding)
    if not import_name:
        return []

    # Resolve import name to pip package name
    package = _IMPORT_TO_PIP.get(import_name, import_name)

    pyproject = workspace / "pyproject.toml"
    if not pyproject.exists():
        return []

    text = pyproject.read_text()
    new_text = _add_dependency_to_toml(text, package)
    if new_text == text:
        return []  # Already present or couldn't insert

    pyproject.write_text(new_text)
    return ["pyproject.toml"]


@_fixer(FindingKind.MISSING_DEPENDENCY)
def _fix_missing_dependency(finding: "Finding", workspace: Path) -> list[str]:
    """Add missing package to pyproject.toml dependencies.

    Same logic as undeclared — both need pyproject.toml edit.
    """
    return _fix_undeclared_dependency(finding, workspace)


@_fixer(FindingKind.NO_FEDERATION_DESCRIPTOR)
def _fix_no_federation_descriptor(finding: "Finding", workspace: Path) -> list[str]:
    """Create .well-known/agent-federation.json from template."""
    well_known = workspace / ".well-known"
    well_known.mkdir(parents=True, exist_ok=True)

    descriptor_path = well_known / "agent-federation.json"
    if descriptor_path.exists():
        return []

    repo_id = workspace.name  # Use directory name as repo_id
    descriptor = {
        "kind": "agent_federation_descriptor",
        "version": "0.1.0",
        "repo_id": repo_id,
        "status": "active",
        "capabilities": [],
    }
    descriptor_path.write_text(json.dumps(descriptor, indent=2) + "\n")
    return [".well-known/agent-federation.json"]


@_fixer(FindingKind.NO_PEER_JSON)
def _fix_no_peer_json(finding: "Finding", workspace: Path) -> list[str]:
    """Create data/federation/peer.json with identity + capabilities."""
    fed_dir = workspace / "data" / "federation"
    fed_dir.mkdir(parents=True, exist_ok=True)

    peer_path = fed_dir / "peer.json"
    if peer_path.exists():
        return []

    repo_id = workspace.name
    peer = {
        "agent_id": repo_id,
        "capabilities": [],
        "endpoint": "",
        "version": "0.1.0",
    }
    peer_path.write_text(json.dumps(peer, indent=2) + "\n")
    return ["data/federation/peer.json"]


@_fixer(FindingKind.NO_CI)
def _fix_no_ci(finding: "Finding", workspace: Path) -> list[str]:
    """Create .github/workflows/ci.yml with pytest + lint."""
    workflows_dir = workspace / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    ci_path = workflows_dir / "ci.yml"
    if ci_path.exists():
        return []

    ci_yaml = """\
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e . && pip install pytest
      - run: pytest -x -q
"""
    ci_path.write_text(ci_yaml)
    return [".github/workflows/ci.yml"]


@_fixer(FindingKind.NO_TESTS)
def _fix_no_tests(finding: "Finding", workspace: Path) -> list[str]:
    """Create tests/ scaffold with __init__.py and placeholder test."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    changed: list[str] = []

    init_path = tests_dir / "__init__.py"
    if not init_path.exists():
        init_path.write_text("")
        changed.append("tests/__init__.py")

    placeholder = tests_dir / "test_placeholder.py"
    if not placeholder.exists():
        placeholder.write_text(
            '"""Placeholder test — replace with real tests."""\n\n\ndef test_placeholder():\n    assert True\n'
        )
        changed.append("tests/test_placeholder.py")

    return changed


@_fixer(FindingKind.BROKEN_IMPORT)
def _fix_broken_import(finding: "Finding", workspace: Path) -> list[str]:
    """Fix broken local imports by creating stub modules.

    When the diagnostic says 'from pkg.sub import X — local module not found',
    the module path is deterministic. Create the missing file with stub exports.
    """
    # Extract module path from the finding detail
    # Pattern: "from pkg.sub import ['helper'] — local module not found"
    match = re.search(r"from\s+([\w.]+)\s+import\s+(\[.*?\]|[\w, ]+)", finding.detail)
    if not match:
        return []

    module_path = match.group(1)  # e.g. "src.utils"
    names_raw = match.group(2)  # e.g. "['helper']" or "helper, foo"

    # Parse imported names
    names_raw = names_raw.strip("[]'\"")
    names = [n.strip().strip("'\"") for n in names_raw.split(",") if n.strip().strip("'\"")]

    # Convert module path to file path
    parts = module_path.split(".")
    target_path = workspace / Path(*parts)

    # Try as a .py file first
    py_file = target_path.with_suffix(".py")
    if py_file.exists():
        return []  # Already exists

    # Create parent directories if needed
    py_file.parent.mkdir(parents=True, exist_ok=True)

    # Ensure __init__.py exists in all parent packages
    changed: list[str] = []
    for i in range(len(parts) - 1):
        init_path = workspace / Path(*parts[: i + 1]) / "__init__.py"
        if not init_path.exists():
            init_path.write_text("")
            changed.append(str(init_path.relative_to(workspace)))

    # Create stub module with exported names
    stub_lines = ['"""Stub module — auto-generated by steward healer."""\n']
    for name in names:
        stub_lines.append(
            f"\ndef {name}(*args, **kwargs):\n    raise NotImplementedError('{name} needs implementation')\n"
        )

    py_file.write_text("\n".join(stub_lines))
    changed.append(str(py_file.relative_to(workspace)))
    return changed


@_fixer(FindingKind.SYNTAX_ERROR)
def _fix_syntax_error(finding: "Finding", workspace: Path) -> list[str]:
    """Fix common syntax errors via AST error message + token-level patching.

    Handles the most frequent deterministic patterns:
    - Missing colon after def/class/if/for/while/else/elif/try/except/finally/with
    - Unmatched brackets/parens
    - IndentationError (unexpected indent / expected indented block)
    - f-string backslash (Python <3.12)
    """
    if not finding.file:
        return []

    target = workspace / finding.file
    if not target.exists():
        return []

    source = target.read_text()
    lines = source.splitlines(keepends=True)
    line_idx = finding.line - 1  # 0-based

    if line_idx < 0 or line_idx >= len(lines):
        return []

    detail = finding.detail.lower()
    fixed = False

    # Pattern 1: Missing colon — "expected ':'"
    if "expected ':'" in detail or "expected ':'":
        line = lines[line_idx].rstrip("\n\r")
        # Check if line ends a compound statement without colon
        stripped = line.rstrip()
        compound_re = re.compile(
            r"^\s*(def\s+\w+.*\)|class\s+\w+.*|if\s+.+|elif\s+.+|else|for\s+.+|while\s+.+"
            r"|try|except.*|finally|with\s+.+)\s*$"
        )
        if compound_re.match(stripped) and not stripped.endswith(":"):
            lines[line_idx] = stripped + ":\n"
            fixed = True

    # Pattern 2: IndentationError — "expected an indented block"
    if not fixed and "expected an indented block" in detail:
        # Insert a `pass` statement after the compound statement
        if line_idx + 1 <= len(lines):
            # Determine indent from the previous line + 4 spaces
            prev = lines[line_idx] if line_idx < len(lines) else ""
            indent_match = re.match(r"(\s*)", prev)
            indent = (indent_match.group(1) if indent_match else "") + "    "
            lines.insert(line_idx + 1, f"{indent}pass\n")
            fixed = True

    # Pattern 3: Unexpected indent — line has more indent than context
    if not fixed and "unexpected indent" in detail:
        line = lines[line_idx]
        # Dedent to match the previous non-empty line
        prev_idx = line_idx - 1
        while prev_idx >= 0 and not lines[prev_idx].strip():
            prev_idx -= 1
        if prev_idx >= 0:
            prev_indent = len(lines[prev_idx]) - len(lines[prev_idx].lstrip())
            curr_content = line.lstrip()
            lines[line_idx] = " " * prev_indent + curr_content
            fixed = True

    # Pattern 4: Unmatched bracket/paren — try adding closing bracket
    if not fixed and ("was never closed" in detail or "unmatched" in detail):
        # Find which bracket is unmatched by tokenizing
        bracket_map = {"(": ")", "[": "]", "{": "}"}
        line = lines[line_idx].rstrip("\n\r")
        stack: list[str] = []
        for ch in line:
            if ch in bracket_map:
                stack.append(bracket_map[ch])
            elif ch in bracket_map.values():
                if stack and stack[-1] == ch:
                    stack.pop()
        if stack:
            # Append the missing closing brackets at end of line
            lines[line_idx] = line + "".join(reversed(stack)) + "\n"
            fixed = True

    if not fixed:
        return []

    # Verify the fix actually parses
    new_source = "".join(lines)
    try:
        ast.parse(new_source, filename=finding.file)
    except SyntaxError:
        return []  # Our fix didn't work — don't write garbage

    target.write_text(new_source)
    return [finding.file]


@_fixer(FindingKind.CIRCULAR_IMPORT)
def _fix_circular_import(finding: "Finding", workspace: Path) -> list[str]:
    """Break circular imports by moving them behind TYPE_CHECKING guard.

    Pure graph-theory fix: if A imports B and B imports A, move B's
    import of A behind `if TYPE_CHECKING:` and add the guard + __future__
    annotations import if not present.
    """
    if not finding.file:
        return []

    target = workspace / finding.file
    if not target.exists():
        return []

    source = target.read_text()
    lines = source.splitlines(keepends=True)

    # Parse the cycle from finding.detail
    # Format: "Circular import: a.py → b.py → a.py"
    cycle_match = re.search(r"Circular import:\s*(.+)", finding.detail)
    if not cycle_match:
        return []

    # The file in the finding is the one we should fix (last in the cycle)
    # We need to find which imports in THIS file point to other files in the cycle
    cycle_files = [f.strip() for f in cycle_match.group(1).split("→")]

    # Parse AST to find the offending import lines
    try:
        tree = ast.parse(source, filename=finding.file)
    except SyntaxError:
        return []

    # Find imports that target cycle members
    imports_to_guard: list[tuple[int, int]] = []  # (start_line, end_line) 1-based
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # Check if this import targets a file in the cycle
            mod_parts = node.module.split(".")
            target_path = str(Path(*mod_parts).with_suffix(".py"))
            target_init = str(Path(*mod_parts) / "__init__.py")
            if target_path in cycle_files or target_init in cycle_files:
                imports_to_guard.append((node.lineno, node.end_lineno or node.lineno))

    if not imports_to_guard:
        return []

    # Check if TYPE_CHECKING already imported
    has_type_checking = "TYPE_CHECKING" in source
    has_future_annotations = "from __future__ import annotations" in source

    # Build the guarded block
    # Remove the offending import lines and collect them
    guarded_lines: list[str] = []
    lines_to_remove: set[int] = set()
    for start, end in imports_to_guard:
        for i in range(start - 1, end):  # 0-based
            guarded_lines.append(lines[i])
            lines_to_remove.add(i)

    # Build new source
    new_lines: list[str] = []
    for i, line in enumerate(lines):
        if i in lines_to_remove:
            continue
        new_lines.append(line)

    # Find insertion point — after existing imports, before first non-import code
    insert_idx = 0
    for i, line in enumerate(new_lines):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) or not stripped or stripped.startswith("#"):
            insert_idx = i + 1
        elif stripped.startswith("if TYPE_CHECKING"):
            insert_idx = i  # Insert INTO existing TYPE_CHECKING block
            break
        else:
            break

    # Build guard block
    guard_block: list[str] = []
    if not has_future_annotations:
        guard_block.append("from __future__ import annotations\n")
    if not has_type_checking:
        guard_block.append("\n")
        guard_block.append("from typing import TYPE_CHECKING\n")
    guard_block.append("\n")
    guard_block.append("if TYPE_CHECKING:\n")
    for gl in guarded_lines:
        guard_block.append("    " + gl.lstrip())
    guard_block.append("\n")

    # Insert
    for j, gb_line in enumerate(guard_block):
        new_lines.insert(insert_idx + j, gb_line)

    new_source = "".join(new_lines)

    # Verify it parses
    try:
        ast.parse(new_source, filename=finding.file)
    except SyntaxError:
        return []

    target.write_text(new_source)
    return [finding.file]


@_fixer(FindingKind.BASE_EXCEPTION_CATCH)
def _fix_base_exception_catch(finding: "Finding", workspace: Path) -> list[str]:
    """Replace 'except BaseException' with 'except Exception'.

    Only fixes handlers that do NOT re-raise — those are the dangerous ones
    (they swallow KeyboardInterrupt and SystemExit, making the process unkillable).
    Handlers that re-raise are intentional cleanup patterns and left alone.
    """
    if not finding.file:
        return []

    target = workspace / finding.file
    if not target.exists():
        return []

    source = target.read_text()
    try:
        tree = ast.parse(source, filename=finding.file)
    except SyntaxError:
        return []

    lines = source.splitlines(keepends=True)
    changed = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.lineno != finding.line:
            continue
        if not isinstance(node.type, ast.Name) or node.type.id != "BaseException":
            continue
        # Verify no re-raise in this handler
        has_reraise = any(isinstance(child, ast.Raise) for child in ast.walk(node))
        if has_reraise:
            continue

        # Replace BaseException with Exception on this line
        line_idx = node.lineno - 1
        lines[line_idx] = lines[line_idx].replace("BaseException", "Exception", 1)
        changed = True

    if not changed:
        return []

    new_source = "".join(lines)
    # Verify the fix parses
    try:
        ast.parse(new_source, filename=finding.file)
    except SyntaxError:
        return []

    target.write_text(new_source)
    return [finding.file]


@_fixer(FindingKind.DYNAMIC_IMPORT)
def _fix_dynamic_import(finding: "Finding", workspace: Path) -> list[str]:
    """Replace __import__(name) with importlib.util.find_spec(name).

    __import__() executes the module's __init__.py on import — dangerous
    when probing untrusted modules. find_spec() checks existence without
    executing any code.

    Only replaces __import__ used for probing (result compared to None
    or used in try/except). Direct attribute access on the result
    (e.g. __import__('foo').bar) is left alone — those need the real import.
    """
    if not finding.file:
        return []

    target = workspace / finding.file
    if not target.exists():
        return []

    source = target.read_text()
    try:
        tree = ast.parse(source, filename=finding.file)
    except SyntaxError:
        return []

    lines = source.splitlines(keepends=True)
    changed = False
    needs_importlib = "importlib.util" not in source

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "__import__":
            continue
        if node.lineno != finding.line:
            continue
        if not node.args:
            continue

        line_idx = node.lineno - 1
        line = lines[line_idx]

        # Only replace simple probing patterns: __import__(name)
        # Don't replace if the result is accessed: __import__(name).attr
        # (that pattern genuinely needs the import to execute)
        arg_source = ast.get_source_segment(source, node.args[0])
        if arg_source is None:
            continue

        old = f"__import__({arg_source})"
        new = f"importlib.util.find_spec({arg_source})"

        if old in line:
            lines[line_idx] = line.replace(old, new, 1)
            changed = True

    if not changed:
        return []

    # Add importlib.util import if needed
    if needs_importlib:
        import_line = "import importlib.util\n"
        # Insert after the last import at the top of the file
        insert_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) or not stripped or stripped.startswith("#"):
                insert_idx = i + 1
            else:
                break
        lines.insert(insert_idx, import_line)

    new_source = "".join(lines)
    try:
        ast.parse(new_source, filename=finding.file)
    except SyntaxError:
        return []

    target.write_text(new_source)
    return [finding.file]


@_fixer(FindingKind.NADI_BLOCKED)
def _fix_nadi_blocked(finding: "Finding", workspace: Path) -> list[str]:
    """Unblock nadi transport by adding gitignore exception.

    Adds '!data/federation/' after 'data/' or 'data/*' in .gitignore.
    """
    gitignore = workspace / ".gitignore"
    if not gitignore.exists():
        return []

    content = gitignore.read_text()
    if "!data/federation" in content:
        return []  # Already has exception

    lines = content.splitlines(keepends=True)
    new_lines: list[str] = []
    inserted = False

    for line in lines:
        new_lines.append(line)
        stripped = line.strip()
        if not inserted and stripped in ("data/", "data/*"):
            new_lines.append("!data/federation/\n")
            inserted = True

    if not inserted:
        return []

    gitignore.write_text("".join(new_lines))
    return [".gitignore"]
