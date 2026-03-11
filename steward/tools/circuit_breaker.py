"""
Circuit Breaker — Prevent cascading failures during auto-fixes.

Pattern from agent-city's CytokineBreaker:
    1. Run baseline tests (capture current failure count)
    2. Apply fix
    3. Re-run tests
    4. If failures INCREASED → rollback via git checkout HEAD -- <file>
    5. After 3 consecutive rollbacks → suspend auto-fixing

This is the safety net that makes autonomous code changes viable.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("STEWARD.CIRCUIT_BREAKER")

# Suspend auto-fixing after N consecutive rollbacks
MAX_CONSECUTIVE_ROLLBACKS = 3
# Suspension duration in seconds
SUSPEND_DURATION = 300  # 5 minutes


def _is_test_file(filepath: str) -> bool:
    """Check if a file path looks like a test file."""
    import os

    basename = os.path.basename(filepath)
    return basename.startswith("test_") or basename.endswith("_test.py")


def _count_test_elements(source: str) -> dict | None:
    """Count test-relevant AST elements — O(1) dispatch per node."""
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    stats = {
        "test_functions": 0,
        "asserts": 0,
        "trivial_asserts": 0,
        "test_classes": 0,
    }

    def _count_func(node: object) -> None:
        if node.name.startswith("test_"):
            stats["test_functions"] += 1

    def _count_class(node: object) -> None:
        if node.name.startswith("Test"):
            stats["test_classes"] += 1

    def _count_assert(node: object) -> None:
        stats["asserts"] += 1
        if isinstance(node.test, ast.Constant) and node.test.value in (True, 1):
            stats["trivial_asserts"] += 1

    dispatch: dict[type, object] = {
        ast.FunctionDef: _count_func,
        ast.AsyncFunctionDef: _count_func,
        ast.ClassDef: _count_class,
        ast.Assert: _count_assert,
    }

    for node in ast.walk(tree):
        handler = dispatch.get(type(node))
        if handler is not None:
            handler(node)

    return stats


def _extract_public_surface(source: str) -> dict | None:
    """Extract public API surface from Python source via AST.

    Returns dict with:
    - all_exports: set of names in __all__, or None if no __all__
    - decorated_endpoints: set of function names with route-like decorators
    - public_names: set of public module-level function/class names (no _ prefix)

    Returns None if source can't be parsed.
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    surface = {
        "all_exports": None,
        "decorated_endpoints": set(),
        "public_names": set(),
    }

    # Route-like decorator patterns (attribute names to match)
    _ROUTE_DECORATORS = frozenset({
        "route", "get", "post", "put", "delete", "patch",
        "api_view", "action", "endpoint",
    })

    for node in ast.iter_child_nodes(tree):
        # Extract __all__ assignments
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        surface["all_exports"] = {
                            elt.value
                            for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        }

        # Extract public functions and classes
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                surface["public_names"].add(node.name)

            # Check for route-like decorators
            for decorator in node.decorator_list:
                dec_name = _decorator_leaf_name(decorator)
                if dec_name and dec_name in _ROUTE_DECORATORS:
                    surface["decorated_endpoints"].add(node.name)
                    break

        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                surface["public_names"].add(node.name)

    return surface


def _decorator_leaf_name(decorator: object) -> str | None:
    """Extract the leaf name from a decorator AST node.

    Handles: @route, @app.route, @router.get, @app.router.get
    Returns the rightmost name segment. O(1) dispatch per node type.
    """
    import ast

    _LEAF_EXTRACT: dict[type, object] = {
        ast.Name: lambda n: n.id,
        ast.Attribute: lambda n: n.attr,
        ast.Call: lambda n: _decorator_leaf_name(n.func),
    }

    extractor = _LEAF_EXTRACT.get(type(decorator))
    return extractor(decorator) if extractor is not None else None


@dataclass
class GateResult:
    """Outcome of a single verification gate."""

    passed: bool
    gate: str = ""
    detail: str = ""


@dataclass
class FixResult:
    """Outcome of a circuit-breaker-guarded fix attempt."""

    applied: bool = False  # fix was applied and kept
    rolled_back: bool = False  # fix was rolled back (made things worse)
    suspended: bool = False  # breaker is suspended (too many rollbacks)
    baseline_failures: int = 0
    post_failures: int = 0
    error: str | None = None
    gate_results: list[GateResult] = field(default_factory=list)


@dataclass
class CircuitBreaker:
    """Baseline → fix → verify → rollback-if-worse pattern.

    Usage:
        breaker = CircuitBreaker(cwd="/path/to/repo")
        result = breaker.guarded_fix(
            file_path="src/foo.py",
            fix_fn=lambda: apply_my_fix(),
            test_cmd="pytest tests/test_foo.py -x -q",
        )
        if result.rolled_back:
            print("Fix made things worse — rolled back")
    """

    cwd: str
    test_timeout: int = 120
    max_changed_files: int = 10
    max_changed_lines: int = 500
    _consecutive_rollbacks: int = field(default=0, repr=False)
    _suspended_until: float = field(default=0.0, repr=False)
    _total_fixes: int = field(default=0, repr=False)
    _total_rollbacks: int = field(default=0, repr=False)

    @property
    def is_suspended(self) -> bool:
        """Check if breaker is in suspension (too many rollbacks)."""
        if self._suspended_until == 0.0:
            return False
        if time.monotonic() >= self._suspended_until:
            self._suspended_until = 0.0
            self._consecutive_rollbacks = 0
            logger.info("Circuit breaker suspension expired — resuming")
            return False
        return True

    def guarded_fix(
        self,
        file_path: str,
        fix_fn: callable,
        test_cmd: str = "pytest -x -q",
    ) -> FixResult:
        """Apply a fix with circuit breaker protection.

        Args:
            file_path: File being modified (for surgical rollback)
            fix_fn: Callable that applies the fix (modifies file_path)
            test_cmd: Test command to verify fix didn't make things worse

        Returns:
            FixResult with outcome details
        """
        if self.is_suspended:
            return FixResult(suspended=True, error="Circuit breaker suspended — too many consecutive rollbacks")

        # Step 1: Baseline — count current failures
        baseline = self.count_failures(test_cmd)
        if baseline is None:
            return FixResult(error="Failed to establish baseline (test command error)")

        # Step 2: Apply fix
        try:
            fix_fn()
        except Exception as e:
            return FixResult(error=f"Fix function raised: {e}")

        # Verify file actually changed
        path = Path(file_path)
        if not path.exists():
            return FixResult(error=f"File not found after fix: {file_path}")

        # Step 3: Re-run tests
        post = self.count_failures(test_cmd)
        if post is None:
            # Can't verify — rollback to be safe
            self.rollback_file(file_path)
            self.record_rollback()
            return FixResult(
                rolled_back=True,
                baseline_failures=baseline,
                error="Post-fix test run failed — rolled back as precaution",
            )

        # Step 4: Compare
        if post > baseline:
            # Fix made things WORSE — rollback
            self.rollback_file(file_path)
            self.record_rollback()
            logger.warning(
                "Fix rolled back: %s (failures %d → %d)",
                file_path, baseline, post,
            )
            return FixResult(
                rolled_back=True,
                baseline_failures=baseline,
                post_failures=post,
            )

        # Fix kept (same or fewer failures)
        self._consecutive_rollbacks = 0
        self._total_fixes += 1
        logger.info("Fix applied: %s (failures %d → %d)", file_path, baseline, post)
        return FixResult(
            applied=True,
            baseline_failures=baseline,
            post_failures=post,
        )

    def count_failures(self, test_cmd: str = "pytest -x -q") -> int | None:
        """Run test command and count failures. Returns None on error."""
        try:
            result = subprocess.run(
                ["bash", "-c", test_cmd],
                capture_output=True,
                text=True,
                timeout=self.test_timeout,
                cwd=self.cwd,
            )
            # pytest exit codes: 0=pass, 1=failures, 2+=error
            if result.returncode > 1:
                logger.warning("Test command error (rc=%d): %s", result.returncode, result.stderr[:200])
                return None

            # Parse "N failed" from pytest output
            import re
            match = re.search(r"(\d+) failed", result.stdout + result.stderr)
            if match:
                return int(match.group(1))

            # No failures found in output
            return 0 if result.returncode == 0 else 1
        except subprocess.TimeoutExpired:
            logger.warning("Test command timed out after %ds", self.test_timeout)
            return None
        except Exception as e:
            logger.warning("Test command failed: %s", e)
            return None

    def changed_files(self) -> set[str]:
        """Get list of modified/untracked files in working tree via git."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.cwd,
            )
            files = set()
            if result.returncode == 0:
                files = {f.strip() for f in result.stdout.strip().split("\n") if f.strip()}
            # Also include staged changes
            result2 = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.cwd,
            )
            if result2.returncode == 0:
                files |= {f.strip() for f in result2.stdout.strip().split("\n") if f.strip()}
            return files
        except Exception as e:
            logger.warning("changed_files failed: %s", e)
            return set()

    def rollback_file(self, file_path: str) -> bool:
        """Surgical single-file rollback via git checkout HEAD."""
        try:
            result = subprocess.run(
                ["git", "checkout", "HEAD", "--", file_path],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.cwd,
            )
            if result.returncode == 0:
                logger.info("Rolled back: %s", file_path)
                return True
            logger.warning("Rollback failed for %s: %s", file_path, result.stderr[:200])
            return False
        except Exception as e:
            logger.warning("Rollback exception for %s: %s", file_path, e)
            return False

    def rollback_files(self, file_paths: set[str]) -> list[str]:
        """Rollback multiple files. Returns list of successfully rolled back paths."""
        rolled_back = []
        for fp in sorted(file_paths):
            if self.rollback_file(fp):
                rolled_back.append(fp)
        return rolled_back

    def record_rollback(self) -> None:
        """Track consecutive rollbacks and trigger suspension if needed."""
        self._consecutive_rollbacks += 1
        self._total_rollbacks += 1
        if self._consecutive_rollbacks >= MAX_CONSECUTIVE_ROLLBACKS:
            self._suspended_until = time.monotonic() + SUSPEND_DURATION
            logger.warning(
                "Circuit breaker SUSPENDED for %ds after %d consecutive rollbacks",
                SUSPEND_DURATION, self._consecutive_rollbacks,
            )

    def record_success(self) -> None:
        """Record a successful fix — resets consecutive rollback counter."""
        self._consecutive_rollbacks = 0
        self._total_fixes += 1

    # ── Verification Gates ────────────────────────────────────────────
    # Fast checks (milliseconds) that run BEFORE the expensive test suite.
    # Each gate is differential: only fails if LLM INTRODUCED new problems.

    def check_lint(self, changed_files: set[str]) -> GateResult:
        """Static analysis gate — ruff on changed .py files.

        Differential: compares violations in LLM-modified files vs baseline
        (HEAD versions). Only fails if new violations were introduced.
        Graceful: skips if ruff not installed.
        """
        import re as _re

        py_files = sorted(f for f in changed_files if f.endswith(".py"))
        if not py_files:
            return GateResult(passed=True, gate="lint")

        # Count violations on current (LLM-modified) files
        post_count = self._run_tool_count(
            ["ruff", "check", "--no-fix", "--quiet"] + py_files
        )
        if post_count is None:
            return GateResult(passed=True, gate="lint", detail="ruff not available")
        if post_count == 0:
            return GateResult(passed=True, gate="lint")

        # Differential: get baseline violations from HEAD versions
        baseline_count = self._baseline_lint_count(py_files)

        new_violations = post_count - baseline_count
        if new_violations > 0:
            return GateResult(
                passed=False,
                gate="lint",
                detail=f"ruff: {new_violations} new violations ({baseline_count}→{post_count}) in {', '.join(py_files[:3])}",
            )
        return GateResult(passed=True, gate="lint")

    def check_security(self, changed_files: set[str]) -> GateResult:
        """Security/SAST gate — bandit on changed .py files.

        Differential: compares findings in LLM-modified files vs baseline.
        Only fails if new medium+ severity findings were introduced.
        Graceful: skips if bandit not installed.
        """
        py_files = sorted(f for f in changed_files if f.endswith(".py"))
        if not py_files:
            return GateResult(passed=True, gate="security")

        # Count findings on current (LLM-modified) files
        post_count = self._run_tool_count(
            ["bandit", "-ll", "-q", "--format", "json"] + py_files,
            count_fn=self._count_bandit_findings,
        )
        if post_count is None:
            return GateResult(passed=True, gate="security", detail="bandit not available")
        if post_count == 0:
            return GateResult(passed=True, gate="security")

        # Differential: get baseline findings from HEAD versions
        baseline_count = self._baseline_security_count(py_files)

        new_findings = post_count - baseline_count
        if new_findings > 0:
            return GateResult(
                passed=False,
                gate="security",
                detail=f"bandit: {new_findings} new security findings ({baseline_count}→{post_count})",
            )
        return GateResult(passed=True, gate="security")

    def check_blast_radius(self, changed_files: set[str]) -> GateResult:
        """Blast radius gate — limit scope of autonomous changes.

        Prevents the LLM from rewriting half the codebase when tasked
        with fixing a single bug. Checks file count and line count.
        """
        import re as _re

        # File count check
        if len(changed_files) > self.max_changed_files:
            return GateResult(
                passed=False,
                gate="blast_radius",
                detail=f"Too many files changed: {len(changed_files)} > {self.max_changed_files}",
            )

        # Line count check (only for the specific changed files)
        py_files = sorted(f for f in changed_files if f.endswith(".py"))
        if not py_files:
            return GateResult(passed=True, gate="blast_radius")

        try:
            result = subprocess.run(
                ["git", "diff", "--stat", "--"] + py_files,
                capture_output=True,
                text=True,
                cwd=self.cwd,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                match_ins = _re.search(r"(\d+) insertion", result.stdout)
                match_del = _re.search(r"(\d+) deletion", result.stdout)
                insertions = int(match_ins.group(1)) if match_ins else 0
                deletions = int(match_del.group(1)) if match_del else 0
                total_lines = insertions + deletions
                if total_lines > self.max_changed_lines:
                    return GateResult(
                        passed=False,
                        gate="blast_radius",
                        detail=f"Too many lines changed: {total_lines} > {self.max_changed_lines} ({insertions}+/{deletions}-)",
                    )
        except Exception as e:
            logger.debug("blast_radius line count failed: %s", e)

        return GateResult(passed=True, gate="blast_radius")

    def check_cohesion(self, changed_files: set[str]) -> GateResult:
        """Cohesion gate — 2D matrix: LCOM4 × WMC.

        LCOM4 alone produces false positives on routers and facades
        (high LCOM4 but low complexity). The second dimension — WMC
        (Weighted Methods per Class, sum of cyclomatic complexities) —
        distinguishes simple routers from real god-classes:

            LCOM4 ≤ 4            → PASS (cohesive enough)
            LCOM4 > 4, WMC ≤ 20 → PASS (router/facade — false positive)
            LCOM4 > 4, WMC > 20 → FAIL (real god-class)
        """
        import ast

        from steward.senses.code_sense import _compute_lcom4, _compute_wmc

        max_lcom4 = 4   # Structural threshold: disconnected method groups
        max_wmc = 20     # Complexity threshold: branching density

        py_files = [f for f in changed_files if f.endswith(".py") and not _is_test_file(f)]
        if not py_files:
            return GateResult(passed=True, gate="cohesion")

        violations = []
        for filepath in py_files:
            full_path = Path(self.cwd) / filepath
            if not full_path.exists():
                continue
            try:
                source = full_path.read_text()
                tree = ast.parse(source)
            except (SyntaxError, OSError):
                continue

            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                lcom4 = _compute_lcom4(node)
                if lcom4 > max_lcom4:
                    wmc = _compute_wmc(node)
                    if wmc > max_wmc:
                        violations.append(
                            f"{node.name} in {filepath} (LCOM4={lcom4}, WMC={wmc})"
                        )

        if violations:
            return GateResult(
                passed=False,
                gate="cohesion",
                detail=f"God-class regression: {'; '.join(violations)}",
            )
        return GateResult(passed=True, gate="cohesion")

    def check_test_integrity(self, changed_files: set[str]) -> GateResult:
        """Test integrity gate — prevent Goodhart test gaming via AST.

        Catches the agent rewriting tests to trivially pass:
        - Deleting test functions (assert count decreased)
        - Replacing assertions with `assert True`
        - Removing test classes entirely

        Compares AST structure of test files before (HEAD) and after (LLM).
        Only checks files that match test file patterns (test_*.py, *_test.py).
        """
        import ast

        test_files = sorted(
            f for f in changed_files
            if f.endswith(".py") and _is_test_file(f)
        )
        if not test_files:
            return GateResult(passed=True, gate="test_integrity")

        cwd_path = Path(self.cwd)
        problems = []

        for filepath in test_files:
            full_path = cwd_path / filepath

            # Get HEAD version via git show
            try:
                head_result = subprocess.run(
                    ["git", "show", f"HEAD:{filepath}"],
                    capture_output=True,
                    text=True,
                    cwd=self.cwd,
                    timeout=10,
                )
            except Exception:
                continue

            if head_result.returncode != 0:
                continue  # New test file — no baseline, skip

            if not full_path.exists():
                problems.append(f"{filepath}: test file deleted")
                continue

            # Parse both versions
            head_stats = _count_test_elements(head_result.stdout)
            current_stats = _count_test_elements(full_path.read_text())

            if head_stats is None or current_stats is None:
                continue  # Syntax error — lint gate will catch it

            # Check 1: Test functions decreased
            if current_stats["test_functions"] < head_stats["test_functions"]:
                lost = head_stats["test_functions"] - current_stats["test_functions"]
                problems.append(
                    f"{filepath}: {lost} test function(s) removed "
                    f"({head_stats['test_functions']}→{current_stats['test_functions']})"
                )

            # Check 2: Assert count decreased significantly
            if head_stats["asserts"] > 0 and current_stats["asserts"] < head_stats["asserts"]:
                lost = head_stats["asserts"] - current_stats["asserts"]
                # Allow minor assertion changes (refactoring), flag major drops
                ratio = current_stats["asserts"] / head_stats["asserts"]
                if ratio < 0.7:  # More than 30% assertions lost
                    problems.append(
                        f"{filepath}: {lost} assertions removed "
                        f"({head_stats['asserts']}→{current_stats['asserts']}, {ratio:.0%} remaining)"
                    )

            # Check 3: Trivial assertions (assert True, assert 1)
            if current_stats["trivial_asserts"] > head_stats["trivial_asserts"]:
                new_trivial = current_stats["trivial_asserts"] - head_stats["trivial_asserts"]
                problems.append(
                    f"{filepath}: {new_trivial} trivial assertion(s) added (assert True/1)"
                )

        if problems:
            return GateResult(
                passed=False,
                gate="test_integrity",
                detail="; ".join(problems),
            )
        return GateResult(passed=True, gate="test_integrity")

    def check_api_surface(self, changed_files: set[str]) -> GateResult:
        """API surface gate — prevent deletion of public interfaces via AST.

        Catches the agent removing externally-visible code:
        - Functions/classes listed in __all__
        - Decorated endpoints (@app.route, @router.get, etc.)
        - Public module-level functions (not starting with _)

        Compares HEAD vs LLM version. Only fails if public surface DECREASED.
        """
        import ast

        py_files = sorted(
            f for f in changed_files
            if f.endswith(".py") and not _is_test_file(f)
        )
        if not py_files:
            return GateResult(passed=True, gate="api_surface")

        cwd_path = Path(self.cwd)
        problems = []

        for filepath in py_files:
            full_path = cwd_path / filepath

            # Get HEAD version
            try:
                head_result = subprocess.run(
                    ["git", "show", f"HEAD:{filepath}"],
                    capture_output=True,
                    text=True,
                    cwd=self.cwd,
                    timeout=10,
                )
            except Exception:
                continue

            if head_result.returncode != 0:
                continue  # New file — no baseline

            if not full_path.exists():
                # Entire source file deleted — check if it had public surface
                head_surface = _extract_public_surface(head_result.stdout)
                if head_surface and head_surface["public_names"]:
                    problems.append(
                        f"{filepath}: source file deleted "
                        f"(had {len(head_surface['public_names'])} public names)"
                    )
                continue

            head_surface = _extract_public_surface(head_result.stdout)
            current_surface = _extract_public_surface(full_path.read_text())

            if head_surface is None or current_surface is None:
                continue  # Syntax error — lint gate handles it

            # Check 1: __all__ entries removed
            head_all = head_surface["all_exports"]
            current_all = current_surface["all_exports"]
            if head_all is not None and current_all is not None:
                removed_exports = head_all - current_all
                if removed_exports:
                    problems.append(
                        f"{filepath}: __all__ exports removed: {', '.join(sorted(removed_exports))}"
                    )

            # Check 2: Decorated endpoints removed
            removed_endpoints = head_surface["decorated_endpoints"] - current_surface["decorated_endpoints"]
            if removed_endpoints:
                problems.append(
                    f"{filepath}: decorated endpoints removed: {', '.join(sorted(removed_endpoints))}"
                )

            # Check 3: Public functions/classes removed (only flag if significant)
            removed_public = head_surface["public_names"] - current_surface["public_names"]
            if len(removed_public) >= 2:
                # Allow removing 1 public name (refactoring), flag 2+
                problems.append(
                    f"{filepath}: {len(removed_public)} public names removed: "
                    f"{', '.join(sorted(removed_public)[:5])}"
                )

        if problems:
            return GateResult(
                passed=False,
                gate="api_surface",
                detail="; ".join(problems),
            )
        return GateResult(passed=True, gate="api_surface")

    def run_gates(self, changed_files: set[str]) -> list[GateResult]:
        """Run all verification gates on changed files.

        Gates run in order: lint → security → blast radius → test integrity → API surface.
        All gates run even if earlier ones fail (collect all violations).
        """
        return [
            self.check_lint(changed_files),
            self.check_security(changed_files),
            self.check_blast_radius(changed_files),
            self.check_cohesion(changed_files),
            self.check_test_integrity(changed_files),
            self.check_api_surface(changed_files),
        ]

    # ── Gate Helpers ──────────────────────────────────────────────────

    def _run_tool_count(
        self,
        cmd: list[str],
        count_fn: callable | None = None,
    ) -> int | None:
        """Run a CLI tool and count violations/findings.

        Returns None if tool not installed (graceful degradation).
        Default count: number of non-empty output lines.
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.cwd,
                timeout=30,
            )
        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired:
            logger.warning("Gate tool timed out: %s", cmd[0])
            return None
        except Exception as e:
            logger.debug("Gate tool failed: %s", e)
            return None

        if count_fn:
            return count_fn(result)

        # Default: count non-empty lines in stdout (ruff format)
        if result.returncode == 0:
            return 0
        lines = [line for line in result.stdout.strip().split("\n") if line.strip()]
        return len(lines)

    @staticmethod
    def _count_bandit_findings(result: subprocess.CompletedProcess) -> int:
        """Parse bandit JSON output to count findings."""
        import json

        if result.returncode == 0:
            return 0
        try:
            data = json.loads(result.stdout)
            return len(data.get("results", []))
        except (json.JSONDecodeError, KeyError):
            # Fallback: any non-zero exit = at least 1 finding
            return 1 if result.returncode != 0 else 0

    def _baseline_lint_count(self, py_files: list[str]) -> int:
        """Get ruff violation count from HEAD versions of files.

        Saves current versions, restores HEAD, runs ruff, restores current.
        """
        return self._differential_check(
            py_files,
            lambda files: self._run_tool_count(
                ["ruff", "check", "--no-fix", "--quiet"] + files
            ),
        )

    def _baseline_security_count(self, py_files: list[str]) -> int:
        """Get bandit finding count from HEAD versions of files."""
        return self._differential_check(
            py_files,
            lambda files: self._run_tool_count(
                ["bandit", "-ll", "-q", "--format", "json"] + files,
                count_fn=self._count_bandit_findings,
            ),
        )

    def _differential_check(
        self,
        py_files: list[str],
        check_fn: callable,
    ) -> int:
        """Run a check against HEAD versions of files (differential).

        1. Save current (LLM) file contents
        2. Restore HEAD versions
        3. Run check → baseline count
        4. Restore LLM versions (always, even on error)

        Returns 0 if baseline can't be established (new files have no baseline).
        """
        saved: dict[str, bytes] = {}
        cwd_path = Path(self.cwd)
        try:
            # Save current versions
            for f in py_files:
                p = cwd_path / f
                if p.exists():
                    saved[f] = p.read_bytes()

            # Restore HEAD versions
            restorable = []
            for f in py_files:
                result = subprocess.run(
                    ["git", "show", f"HEAD:{f}"],
                    capture_output=True,
                    text=True,
                    cwd=self.cwd,
                    timeout=10,
                )
                if result.returncode == 0:
                    (cwd_path / f).write_text(result.stdout)
                    restorable.append(f)

            if not restorable:
                return 0  # All files are new — no baseline

            # Run check on baseline versions
            baseline = check_fn(restorable)
            return baseline if baseline is not None else 0
        except Exception as e:
            logger.debug("Differential check failed: %s", e)
            return 0
        finally:
            # ALWAYS restore LLM versions
            for f, content in saved.items():
                try:
                    (cwd_path / f).write_bytes(content)
                except Exception:
                    pass

    def stats(self) -> dict:
        """Diagnostics."""
        return {
            "total_fixes": self._total_fixes,
            "total_rollbacks": self._total_rollbacks,
            "consecutive_rollbacks": self._consecutive_rollbacks,
            "is_suspended": self.is_suspended,
        }
