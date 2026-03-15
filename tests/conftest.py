"""
STEWARD AGENT — Test Configuration
===================================

Shared fixtures, markers, singleton resets, API isolation.
Every test file imports from here automatically (pytest convention).

Federation standard: matches agent-city and steward-protocol conftest quality.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Generator

import pytest

# ═══════════════════════════════════════════════════════════════════════
# LOGGING — minimal noise during tests
# ═══════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.WARNING,
    format="%(name)s - %(levelname)s - %(message)s",
)


# ═══════════════════════════════════════════════════════════════════════
# PYTEST HOOKS — markers, auto-categorization
# ═══════════════════════════════════════════════════════════════════════


def pytest_configure(config):
    """Register markers and set defaults."""
    config.addinivalue_line("markers", "fast: Quick unit tests (<1s)")
    config.addinivalue_line("markers", "slow: Slow tests (>5s)")
    config.addinivalue_line("markers", "integration: Cross-module integration tests")
    config.addinivalue_line("markers", "substrate: Substrate wiring tests (Venu, MahaCompression)")
    config.addinivalue_line("markers", "senses: Jnanendriya sense tests")
    config.addinivalue_line("markers", "buddhi: Buddhi decision engine tests")
    config.addinivalue_line("markers", "tools: Tool execution tests")
    config.addinivalue_line("markers", "engine: AgentLoop engine tests")


def pytest_collection_modifyitems(config, items):
    """Auto-mark tests based on file name."""
    for item in items:
        fspath = str(item.fspath)

        if "test_substrate" in fspath:
            item.add_marker(pytest.mark.substrate)
        if "test_sense" in fspath or "test_coordinator" in fspath:
            item.add_marker(pytest.mark.senses)
        if "test_buddhi" in fspath:
            item.add_marker(pytest.mark.buddhi)
        if "test_tool" in fspath:
            item.add_marker(pytest.mark.tools)
        if "test_engine" in fspath or "test_loop" in fspath:
            item.add_marker(pytest.mark.engine)

        # Auto-mark slow tests by name
        if "slow" in item.name.lower() or "stress" in item.name.lower():
            item.add_marker(pytest.mark.slow)

        # Auto-mark integration tests
        if "integration" in item.name or "full_" in item.name:
            item.add_marker(pytest.mark.integration)


# ═══════════════════════════════════════════════════════════════════════
# CORE FIXTURES — singleton resets, API isolation
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch, tmp_path):
    """Reset ServiceRegistry + prevent real API calls between tests.

    Also redirects Path.cwd() to tmp_path so StewardAgent doesn't scan
    the real project directory (eliminates ~500ms per agent construction
    from sense filesystem scans).

    Without this, test outcomes depend on ordering (VenuOrchestrator
    accumulates ticks, ServiceRegistry leaks across tests).
    """
    # Prevent real LLM API calls
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)

    # Redirect Path.cwd() so agents don't scan the real project.
    # Tests that need real cwd can pass cwd= explicitly.
    monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path))

    yield

    # Reset ServiceRegistry after every test
    try:
        from vibe_core.di import ServiceRegistry

        ServiceRegistry.reset_all()
    except ImportError:
        pass

    # Reset GhClient singleton (prevent test contamination)
    from steward.senses.gh import _reset_gh_client

    _reset_gh_client()


@pytest.fixture
def tmp_dir() -> Generator[Path, None, None]:
    """Auto-cleaned temporary directory."""
    tmpdir = Path(tempfile.mkdtemp(prefix="steward_test_"))
    yield tmpdir
    import shutil

    shutil.rmtree(tmpdir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# FAKE LLM — canonical implementations in tests/fakes.py
# ═══════════════════════════════════════════════════════════════════════

from tests.fakes import FakeLLM, FakeResponse, FakeUsage  # noqa: F401 — re-exported for fixtures


@pytest.fixture
def fake_llm():
    """FakeLLM instance with single "ok" response."""
    return FakeLLM()


@pytest.fixture
def fake_llm_factory():
    """Factory for creating FakeLLM with custom responses.

    Usage:
        def test_something(fake_llm_factory):
            llm = fake_llm_factory([FakeResponse(content="done")])
    """
    return FakeLLM


# ═══════════════════════════════════════════════════════════════════════
# AGENT CLEANUP — stop Cetana threads, prevent accumulation
# ═══════════════════════════════════════════════════════════════════════

_active_agents: list = []
_active_cetanas: list = []


@pytest.fixture(autouse=True)
def _cleanup_agents():
    """Stop ALL Cetana daemon threads after each test.

    Two-layer cleanup:
    1. Tracked agents (via track_agent) — calls agent.close()
    2. ALL Cetana instances (via monkey-patch) — stops any leaked threads

    Without this, daemon threads accumulate during the test run,
    each polling vedana at 0.5Hz. Wastes CPU and causes flaky timing.
    """
    _active_agents.clear()
    _active_cetanas.clear()

    # Monkey-patch Cetana.start to auto-register for cleanup
    from steward.cetana import Cetana

    _original_start = Cetana.start

    def _tracked_start(self, block=False):
        _active_cetanas.append(self)
        return _original_start(self, block=block)

    Cetana.start = _tracked_start
    yield
    Cetana.start = _original_start

    # Layer 1: tracked agents
    for agent in _active_agents:
        try:
            agent.close()
        except Exception:
            pass
    _active_agents.clear()

    # Layer 2: any leaked Cetana instances
    for cetana in _active_cetanas:
        try:
            cetana.stop()
        except Exception:
            pass
    _active_cetanas.clear()


def track_agent(agent: object) -> object:
    """Register an agent for automatic cleanup after the test.

    Usage in tests:
        agent = track_agent(StewardAgent(provider=llm))
    """
    _active_agents.append(agent)
    return agent
