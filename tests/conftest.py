"""Test configuration — ServiceRegistry isolation between tests."""

import pytest

try:
    from vibe_core.di import ServiceRegistry
    _HAS_VIBE_CORE = True
except ImportError:
    _HAS_VIBE_CORE = False


@pytest.fixture(autouse=True)
def _reset_service_registry():
    """Reset ServiceRegistry after every test to prevent pollution."""
    yield
    if _HAS_VIBE_CORE:
        ServiceRegistry.reset_all()
