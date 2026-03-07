"""Test configuration — ServiceRegistry isolation between tests."""

import pytest
from vibe_core.di import ServiceRegistry


@pytest.fixture(autouse=True)
def _reset_service_registry():
    """Reset ServiceRegistry after every test to prevent pollution."""
    yield
    ServiceRegistry.reset_all()
