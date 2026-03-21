"""Tests for SVC_CETANA service registration and context_bridge integration."""

from __future__ import annotations


def test_svc_cetana_constant_exists():
    """SVC_CETANA must exist as a service marker class."""
    from steward.services import SVC_CETANA

    assert isinstance(SVC_CETANA, type)
    assert SVC_CETANA.__doc__ is not None
    assert "heartbeat" in SVC_CETANA.__doc__.lower() or "cetana" in SVC_CETANA.__doc__.lower()


def test_context_bridge_uses_svc_cetana():
    """context_bridge._get_cetana should use SVC_CETANA, not string key."""
    import inspect

    from steward.context_bridge import _get_cetana

    source = inspect.getsource(_get_cetana)
    assert "SVC_CETANA" in source
    # Should NOT use the old string-based lookup
    assert '"cetana"' not in source


def test_get_cetana_returns_none_when_not_registered():
    """Without registration, _get_cetana returns None."""
    from vibe_core.di import ServiceRegistry

    ServiceRegistry.reset_all()

    from steward.context_bridge import _get_cetana

    result = _get_cetana()
    assert result is None


def test_get_cetana_returns_registered_instance():
    """When registered via SVC_CETANA, _get_cetana returns the instance."""
    from steward.services import SVC_CETANA
    from vibe_core.di import ServiceRegistry

    ServiceRegistry.reset_all()

    sentinel = object()
    ServiceRegistry.register(SVC_CETANA, sentinel)

    from steward.context_bridge import _get_cetana

    result = _get_cetana()
    assert result is sentinel

    ServiceRegistry.reset_all()
