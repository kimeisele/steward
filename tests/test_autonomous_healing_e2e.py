"""End-to-end test: Discovery → Reaper lifecycle → HEAL_REPO trigger.

Proves the autonomous loop works without human intervention:
1. GenesisDiscoveryHook discovers a peer
2. Peer never sends its own heartbeat
3. Reaper marks it SUSPECT → DEAD
4. AutonomyEngine triggers HEAL_REPO
5. IntentHandler detects degraded peer
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from steward.hooks.genesis import GenesisDiscoveryHook
from steward.phase_hook import PhaseContext
from steward.reaper import HeartbeatReaper, PeerStatus
from steward.services import SVC_REAPER
from vibe_core.di import ServiceRegistry


class TestAutonomousHealingLoop:
    """The complete autonomous loop: discover → decay → heal."""

    def test_discovery_registers_peer_once(self):
        """Genesis discovers a peer and registers it in reaper."""
        reaper = HeartbeatReaper(lease_ttl_s=10)
        ServiceRegistry.register(SVC_REAPER, reaper)

        hook = GenesisDiscoveryHook()

        with patch("steward.hooks.genesis._discover_from_world_registry") as mock_world, \
             patch("steward.hooks.genesis._discover_from_github_topics", return_value={}), \
             patch("steward.hooks.genesis._discover_from_org_repos", return_value={}):
            mock_world.return_value = {
                "steward-test": {"repo": "kimeisele/steward-test", "capabilities": ["code_analysis"]},
            }

            ctx = PhaseContext(cwd="/tmp")
            hook.execute(ctx)

        # Peer is registered and ALIVE
        peers = reaper.alive_peers()
        assert len(peers) == 1
        assert peers[0].agent_id == "steward-test"
        assert peers[0].status == PeerStatus.ALIVE

    def test_peer_decays_without_heartbeat(self):
        """After discovery, if peer never sends its own heartbeat, it decays."""
        reaper = HeartbeatReaper(lease_ttl_s=10)
        ServiceRegistry.register(SVC_REAPER, reaper)

        # Register peer at t=1000
        reaper.record_heartbeat("steward-test", timestamp=1000.0, source="genesis_discovery")

        # Time passes: t=1000 + 15 (>10 TTL)
        consequences = reaper.reap(now=1015.0)

        # Peer should be SUSPECT
        suspects = reaper.suspect_peers()
        assert len(suspects) == 1
        assert suspects[0].agent_id == "steward-test"

    def test_peer_becomes_dead_after_two_misses(self):
        """Two missed lease windows → DEAD."""
        reaper = HeartbeatReaper(lease_ttl_s=10)

        reaper.record_heartbeat("steward-test", timestamp=1000.0)

        # First miss → SUSPECT
        reaper.reap(now=1015.0)
        assert reaper.suspect_peers()[0].status == PeerStatus.SUSPECT

        # Second miss → DEAD
        reaper.reap(now=1030.0)
        dead = reaper.dead_peers()
        assert len(dead) == 1
        assert dead[0].agent_id == "steward-test"

    def test_genesis_does_not_revive_dead_peer(self):
        """Discovery must NOT refresh heartbeat of known peer."""
        reaper = HeartbeatReaper(lease_ttl_s=10)
        ServiceRegistry.register(SVC_REAPER, reaper)

        hook = GenesisDiscoveryHook()

        with patch("steward.hooks.genesis._discover_from_world_registry") as mock_world, \
             patch("steward.hooks.genesis._discover_from_github_topics", return_value={}), \
             patch("steward.hooks.genesis._discover_from_org_repos", return_value={}):
            mock_world.return_value = {
                "steward-test": {"repo": "kimeisele/steward-test"},
            }

            # First scan: registers peer
            ctx = PhaseContext(cwd="/tmp")
            hook.execute(ctx)

            # Peer decays to DEAD
            reaper.reap(now=time.time() + 20)
            reaper.reap(now=time.time() + 40)
            assert len(reaper.dead_peers()) == 1

            # Second scan: must NOT revive the dead peer
            hook._last_scan = 0
            ctx2 = PhaseContext(cwd="/tmp")
            hook.execute(ctx2)

            # Peer is still DEAD — not revived by discovery
            assert len(reaper.dead_peers()) == 1
            assert len(reaper.alive_peers()) == 0

    def test_heal_repo_intent_fires_for_degraded_peer(self):
        """IntentHandler detects degraded peer → returns healing instruction."""
        from steward.intent_handlers import IntentHandlers

        reaper = HeartbeatReaper(lease_ttl_s=10)
        reaper.record_heartbeat("steward-test", timestamp=1000.0)
        reaper.reap(now=1015.0)  # → SUSPECT
        ServiceRegistry.register(SVC_REAPER, reaper)

        class FakeSenses:
            senses = {}
            def perceive_all(self):
                pass

        handlers = IntentHandlers(senses=FakeSenses(), vedana_fn=lambda: None, cwd="/tmp")
        result = handlers.execute_heal_repo()

        assert result is not None
        assert "steward-test" in result
        assert "healing" in result.lower()

    def test_full_loop_discovery_to_heal_trigger(self):
        """Complete loop: discover → decay → intent fires."""
        reaper = HeartbeatReaper(lease_ttl_s=10)
        ServiceRegistry.register(SVC_REAPER, reaper)

        hook = GenesisDiscoveryHook()

        with patch("steward.hooks.genesis._discover_from_world_registry") as mock_world, \
             patch("steward.hooks.genesis._discover_from_github_topics", return_value={}), \
             patch("steward.hooks.genesis._discover_from_org_repos", return_value={}):
            mock_world.return_value = {
                "steward-test": {"repo": "kimeisele/steward-test", "capabilities": ["code_analysis"]},
            }

            # GENESIS: discover peer
            ctx = PhaseContext(cwd="/tmp")
            hook.execute(ctx)
            assert len(reaper.alive_peers()) == 1

            # DHARMA: time passes, peer doesn't heartbeat, reaper reaps
            reaper.reap(now=time.time() + 20)  # → SUSPECT
            assert len(reaper.suspect_peers()) == 1

            # KARMA: intent handler detects degraded peer
            from steward.intent_handlers import IntentHandlers

            class FakeSenses:
                senses = {}
                def perceive_all(self):
                    pass

            handlers = IntentHandlers(senses=FakeSenses(), vedana_fn=lambda: None, cwd="/tmp")
            result = handlers.execute_heal_repo()

            # The autonomous loop fires
            assert result is not None
            assert "steward-test" in result
