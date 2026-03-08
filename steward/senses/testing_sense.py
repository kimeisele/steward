"""
JIHVA — The Tongue (Test Sense).

Tastes code quality through test framework detection and results. Evaluates:
- Test framework and configuration
- Test file count and distribution
- Last test run results (if available)
- Test coverage presence

Tanmatra: RASA (taste — quality judgment through validation)
Mahabhuta: JALA (water — validation flows like water through code)

SB 3.26.50: "From water, the sense of taste was generated..."
Tests ARE the taste — they tell if the code is sweet (passing) or bitter (failing).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from vibe_core.mahamantra.protocols._sense import (
    Jnanendriya,
    SensePerception,
    SenseProtocol,
    Tanmatra,
)

logger = logging.getLogger("STEWARD.SENSE.TEST")

# Test framework detection patterns
_FRAMEWORK_CONFIG: dict[str, list[str]] = {
    "pytest": ["pytest.ini", "conftest.py"],
    "unittest": [],  # detected via file patterns
    "jest": ["jest.config.js", "jest.config.ts", "jest.config.mjs"],
    "mocha": [".mocharc.yml", ".mocharc.yaml", ".mocharc.json"],
    "vitest": ["vitest.config.ts", "vitest.config.js"],
}


class TestingSense:
    """JIHVA — perceives test quality through test framework analysis.

    Implements SenseProtocol. All perception is deterministic
    (file discovery + config parsing). Zero LLM.
    """

    __test__ = False  # not a pytest test class

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = Path(cwd) if cwd else Path.cwd()

    @property
    def jnanendriya(self) -> Jnanendriya:
        return Jnanendriya.JIHVA

    @property
    def tanmatra(self) -> Tanmatra:
        return Tanmatra.RASA

    @property
    def is_active(self) -> bool:
        return self._cwd.is_dir()

    def perceive(self) -> SensePerception:
        """Perceive test landscape — framework, file count, last results."""
        framework = self._detect_framework()
        test_files = self._find_test_files()
        test_count = len(test_files)
        has_coverage = self._has_coverage_config()
        last_result = self._read_last_result()

        # pytest config from pyproject.toml
        pytest_config = self._read_pytest_config()

        # Determine quality
        quality = "sattva"
        intensity = 0.3

        if test_count == 0:
            quality = "tamas"
            intensity = 0.8  # no tests = high pain

        if last_result == "failed":
            quality = "tamas"
            intensity = 0.7

        if not framework:
            intensity += 0.1  # no framework detected

        return SensePerception(
            sense=Jnanendriya.JIHVA,
            tanmatra=Tanmatra.RASA,
            data={
                "framework": framework or "unknown",
                "test_files": test_count,
                "test_file_list": [str(f.relative_to(self._cwd)) for f in test_files[:20]],
                "has_coverage": has_coverage,
                "last_result": last_result,
                "pytest_config": pytest_config,
            },
            intensity=intensity,
            quality=quality,
        )

    def get_pain_level(self) -> float:
        """Pain = no tests, failing tests, no coverage."""
        perception = self.perceive()
        if perception.quality == "tamas":
            return perception.intensity
        return 0.0

    def _detect_framework(self) -> str | None:
        """Detect test framework from config files and pyproject.toml."""
        # Check pyproject.toml for pytest config
        pyproject = self._cwd / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                if "[tool.pytest" in content:
                    return "pytest"
            except OSError:
                pass

        # Check dedicated config files
        for framework, configs in _FRAMEWORK_CONFIG.items():
            for config in configs:
                if (self._cwd / config).exists():
                    return framework

        # Fallback: check if test files exist with test_ prefix (implies pytest/unittest)
        test_files = list(self._cwd.rglob("test_*.py"))[:1]
        if test_files:
            return "pytest"

        return None

    def _find_test_files(self) -> list[Path]:
        """Find test files in the project."""
        test_files: list[Path] = []

        # Python test files
        for pattern in ["test_*.py", "*_test.py"]:
            for f in self._cwd.rglob(pattern):
                parts = f.relative_to(self._cwd).parts
                if not any(p.startswith(".") or p == "__pycache__" or p in ("venv", ".venv") for p in parts):
                    test_files.append(f)

        # JS/TS test files
        for pattern in ["*.test.js", "*.test.ts", "*.spec.js", "*.spec.ts"]:
            for f in self._cwd.rglob(pattern):
                parts = f.relative_to(self._cwd).parts
                if not any(p.startswith(".") or p == "node_modules" for p in parts):
                    test_files.append(f)

        return sorted(set(test_files))[:100]

    def _has_coverage_config(self) -> bool:
        """Check for coverage configuration."""
        markers = [".coveragerc", "coverage.xml", "htmlcov"]
        for m in markers:
            if (self._cwd / m).exists():
                return True

        # Check pyproject.toml for coverage config
        pyproject = self._cwd / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                if "[tool.coverage" in content:
                    return True
            except OSError:
                pass
        return False

    def _read_last_result(self) -> str:
        """Try to determine last test result (from common output locations)."""
        # Check for pytest cache
        cache_file = self._cwd / ".pytest_cache" / "v" / "cache" / "lastfailed"
        if cache_file.exists():
            try:
                content = cache_file.read_text(encoding="utf-8").strip()
                if not content or content == "{}":
                    return "passed"
                # Validate: check that at least one referenced test file still exists.
                # Stale cache entries reference deleted tests → treat as stale.
                if self._lastfailed_is_stale(content):
                    return "unknown"
                return "failed"
            except OSError:
                pass

        # Check for JUnit XML results
        for xml in self._cwd.glob("**/junit*.xml"):
            try:
                content = xml.read_text(encoding="utf-8")[:2000]
                if 'failures="0"' in content and 'errors="0"' in content:
                    return "passed"
                return "failed"
            except OSError:
                pass

        return "unknown"

    def _lastfailed_is_stale(self, content: str) -> bool:
        """Check if lastfailed cache is stale (superseded by a newer clean run).

        Pytest writes nodeids on EVERY run but only writes lastfailed when
        tests fail. If nodeids is newer than lastfailed, the most recent
        run had no failures — the lastfailed data is stale.
        """
        lastfailed_path = self._cwd / ".pytest_cache" / "v" / "cache" / "lastfailed"
        nodeids_path = self._cwd / ".pytest_cache" / "v" / "cache" / "nodeids"

        if not nodeids_path.exists():
            return False  # can't determine → trust lastfailed

        try:
            lf_mtime = lastfailed_path.stat().st_mtime
            ni_mtime = nodeids_path.stat().st_mtime
            # nodeids newer → a clean run happened after the failures
            return ni_mtime > lf_mtime
        except OSError:
            return False

    def _read_pytest_config(self) -> str:
        """Extract pytest config summary from pyproject.toml."""
        pyproject = self._cwd / "pyproject.toml"
        if not pyproject.exists():
            return ""
        try:
            content = pyproject.read_text(encoding="utf-8")
            # Extract testpaths
            match = re.search(r'testpaths\s*=\s*\[([^\]]+)\]', content)
            if match:
                return f"testpaths={match.group(1).strip()}"
        except OSError:
            pass
        return ""

