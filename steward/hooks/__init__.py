"""
Steward Phase Hooks — Composable capabilities for MURALI phase dispatch.

Each hook is a focused piece of phase logic. Registration happens at boot.
Adding new capabilities = adding a hook here, not editing agent.py.

Imports are deferred to register_default_hooks() to break the
services.py ↔ hooks ↔ services.py circular import chain.
"""

from __future__ import annotations

from steward.phase_hook import PhaseHookRegistry


def register_default_hooks(registry: PhaseHookRegistry) -> None:
    """Register all built-in steward hooks.

    Imports are inside the function body to break circular imports:
    services.py → hooks/__init__.py → hooks/dharma.py → services.py
    """
    from steward.hooks.dharma import (
        DharmaFederationHook,
        DharmaHealthHook,
        DharmaMarketplaceHook,
        DharmaReaperHook,
    )
    from steward.hooks.genesis import GenesisDiscoveryHook
    from steward.hooks.karma import (
        KarmaA2AProgressHook,
        KarmaFederationCallbackHook,
        KarmaTaskPrioritizationHook,
    )
    from steward.hooks.moksha import (
        MokshaFederationHook,
        MokshaPersistenceHook,
        MokshaSynapseHook,
    )

    # GENESIS hooks
    registry.register(GenesisDiscoveryHook())

    from steward.hooks.dharma_immune import DharmaImmuneHook

    # DHARMA hooks (priority order: health → reaper → marketplace → federation → immune)
    registry.register(DharmaHealthHook())
    registry.register(DharmaReaperHook())
    registry.register(DharmaMarketplaceHook())
    registry.register(DharmaFederationHook())
    registry.register(DharmaImmuneHook())

    # KARMA hooks (callback → prioritization → a2a progress)
    registry.register(KarmaFederationCallbackHook())
    registry.register(KarmaTaskPrioritizationHook())
    registry.register(KarmaA2AProgressHook())

    from steward.hooks.moksha_bridge import MokshaContextBridgeHook
    from steward.hooks.moksha_health import MokshaHealthReportHook

    # MOKSHA hooks (synapse → health → persistence → federation → context bridge)
    registry.register(MokshaSynapseHook())
    registry.register(MokshaHealthReportHook())
    registry.register(MokshaPersistenceHook())
    registry.register(MokshaFederationHook())
    registry.register(MokshaContextBridgeHook())
