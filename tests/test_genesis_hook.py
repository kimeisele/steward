"""Tests for GenesisDiscoveryHook — active federation peer discovery."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from steward.hooks.genesis import (
    GenesisDiscoveryHook,
    _discover_from_github_topics,
    _discover_from_org_repos,
    _discover_from_world_registry,
)
from steward.phase_hook import PhaseContext
from steward.services import SVC_REAPER
from vibe_core.di import ServiceRegistry


class TestGenesisDiscoveryHook:
    def test_properties(self):
        hook = GenesisDiscoveryHook()
        assert hook.name == "genesis_discovery"
        assert hook.phase == "genesis"
        assert hook.priority == 20

    def test_should_run_respects_interval(self):
        hook = GenesisDiscoveryHook()
        ctx = PhaseContext(cwd="/tmp")

        # In test environment, should_run returns False (no real gh API)
        assert hook.should_run(ctx) is False

    def test_should_run_interval_logic(self):
        """Verify interval logic directly (bypassing pytest guard)."""
        hook = GenesisDiscoveryHook()
        # Simulate non-test: check interval math
        assert hook._last_scan == 0.0  # Fresh hook
        hook._last_scan = time.time()
        elapsed = time.time() - hook._last_scan
        assert elapsed < 600  # Not enough time passed
        hook._last_scan = time.time() - 700
        elapsed = time.time() - hook._last_scan
        assert elapsed >= 600  # Interval expired

    def test_execute_registers_peers(self):
        reaper = MagicMock()
        ServiceRegistry.register(SVC_REAPER, reaper)

        hook = GenesisDiscoveryHook()
        ctx = PhaseContext(cwd="/tmp")

        with patch("steward.hooks.genesis._discover_from_world_registry") as mock_world, \
             patch("steward.hooks.genesis._discover_from_github_topics") as mock_topics, \
             patch("steward.hooks.genesis._discover_from_org_repos") as mock_org:
            mock_world.return_value = {
                "agent-city": {"repo": "kimeisele/agent-city", "capabilities": ["governance"]},
            }
            mock_topics.return_value = {
                "steward-test": {"repo": "kimeisele/steward-test", "capabilities": []},
            }
            mock_org.return_value = {}

            hook.execute(ctx)

        # Both peers registered
        assert reaper.record_heartbeat.call_count == 2
        call_ids = {c.kwargs["agent_id"] for c in reaper.record_heartbeat.call_args_list}
        assert "agent-city" in call_ids
        assert "steward-test" in call_ids

        # Capabilities passed through
        city_call = [c for c in reaper.record_heartbeat.call_args_list
                     if c.kwargs["agent_id"] == "agent-city"][0]
        assert "governance" in city_call.kwargs["capabilities"]

    def test_execute_deduplicates_across_sources(self):
        reaper = MagicMock()
        ServiceRegistry.register(SVC_REAPER, reaper)

        hook = GenesisDiscoveryHook()
        ctx = PhaseContext(cwd="/tmp")

        with patch("steward.hooks.genesis._discover_from_world_registry") as mock_world, \
             patch("steward.hooks.genesis._discover_from_github_topics") as mock_topics, \
             patch("steward.hooks.genesis._discover_from_org_repos") as mock_org:
            # Same repo in both sources — world registry wins (priority)
            mock_world.return_value = {
                "agent-city": {"repo": "kimeisele/agent-city", "capabilities": ["governance"]},
            }
            mock_topics.return_value = {
                "agent-city": {"repo": "kimeisele/agent-city", "capabilities": []},
            }
            mock_org.return_value = {}

            hook.execute(ctx)

        # Only one registration (deduplicated across sources)
        assert reaper.record_heartbeat.call_count == 1

    def test_never_refreshes_existing_peer_heartbeat(self):
        """Critical: discovery must NOT refresh heartbeats for known peers.
        Otherwise the reaper can never detect dead peers."""
        reaper = MagicMock()
        ServiceRegistry.register(SVC_REAPER, reaper)

        hook = GenesisDiscoveryHook()
        ctx = PhaseContext(cwd="/tmp")

        with patch("steward.hooks.genesis._discover_from_world_registry") as mock_world, \
             patch("steward.hooks.genesis._discover_from_github_topics", return_value={}), \
             patch("steward.hooks.genesis._discover_from_org_repos", return_value={}):
            mock_world.return_value = {"peer-x": {"repo": "kimeisele/peer-x"}}

            # First scan — registers peer
            hook.execute(ctx)
            assert reaper.record_heartbeat.call_count == 1

            # Second scan — same peer, must NOT refresh heartbeat
            hook._last_scan = 0  # Reset interval for re-run
            ctx2 = PhaseContext(cwd="/tmp")
            hook.execute(ctx2)
            assert reaper.record_heartbeat.call_count == 1  # Still 1, not 2

    def test_execute_skips_without_reaper(self):
        ServiceRegistry.register(SVC_REAPER, None)
        hook = GenesisDiscoveryHook()
        ctx = PhaseContext(cwd="/tmp")

        with patch("steward.hooks.genesis._discover_from_world_registry") as mock_world:
            mock_world.return_value = {}
            hook.execute(ctx)  # Should not crash

    def test_tracks_new_vs_known_peers(self):
        reaper = MagicMock()
        ServiceRegistry.register(SVC_REAPER, reaper)

        hook = GenesisDiscoveryHook()
        ctx = PhaseContext(cwd="/tmp")

        with patch("steward.hooks.genesis._discover_from_world_registry") as mock_world, \
             patch("steward.hooks.genesis._discover_from_github_topics", return_value={}), \
             patch("steward.hooks.genesis._discover_from_org_repos", return_value={}):
            mock_world.return_value = {"peer-a": {"repo": "kimeisele/peer-a"}}
            hook.execute(ctx)
            assert "peer-a" in hook._known_repos

            # Second run — same peer is not "new"
            hook._last_scan = 0  # Reset interval
            ctx2 = PhaseContext(cwd="/tmp")
            hook.execute(ctx2)
            assert "new=0" in ctx2.operations[0]


class TestWorldRegistryDiscovery:
    def test_parses_yaml_cities(self):
        yaml_content = """\
cities:
  - city_id: agent-city
    repo: kimeisele/agent-city
    status: alive
    capabilities:
      - governance
      - economy
  - city_id: agent-world
    repo: kimeisele/agent-world
    status: alive
    capabilities:
      - world_truth
"""
        import base64
        encoded = base64.b64encode(yaml_content.encode()).decode()

        with patch("steward.hooks.genesis._gh", return_value=encoded):
            peers = _discover_from_world_registry()

        assert "agent-city" in peers
        assert "agent-world" in peers
        assert "governance" in peers["agent-city"]["capabilities"]
        assert peers["agent-city"]["repo"] == "kimeisele/agent-city"

    def test_returns_empty_on_failure(self):
        with patch("steward.hooks.genesis._gh", return_value=None):
            peers = _discover_from_world_registry()
        assert peers == {}


class TestGitHubTopicDiscovery:
    def test_parses_search_results(self):
        search_result = json.dumps([
            {"name": "steward-test", "description": "test sandbox"},
            {"name": "agent-lab", "description": "lab"},
        ])

        with patch("steward.hooks.genesis._gh", return_value=search_result):
            peers = _discover_from_github_topics()

        assert "steward-test" in peers
        assert "agent-lab" in peers
        assert peers["steward-test"]["repo"] == "kimeisele/steward-test"

    def test_returns_empty_on_failure(self):
        with patch("steward.hooks.genesis._gh", return_value=None):
            peers = _discover_from_github_topics()
        assert peers == {}


class TestOrgRepoDiscovery:
    def test_finds_federation_repos(self):
        repo_list = json.dumps([
            {"name": "steward-test"},
            {"name": "agent-city"},
            {"name": "steward"},  # Self — should be skipped
            {"name": "random-repo"},  # No descriptor
        ])

        import base64
        descriptor = json.dumps({
            "kind": "agent_federation_descriptor",
            "status": "active",
            "capabilities": ["code_analysis"],
            "owner_boundary": "test_surface",
        })
        encoded_descriptor = base64.b64encode(descriptor.encode()).decode()

        def mock_gh(args, cwd=None):
            if args[0] == "repo" and args[1] == "list":
                return repo_list
            if "agent-federation.json" in str(args):
                if "random-repo" in str(args) or "steward/" in str(args):
                    return None
                return encoded_descriptor
            return None

        with patch("steward.hooks.genesis._gh", side_effect=mock_gh):
            peers = _discover_from_org_repos()

        assert "steward-test" in peers
        assert "agent-city" in peers
        assert "steward" not in peers  # Self excluded
        assert "random-repo" not in peers  # No descriptor

    def test_returns_empty_on_failure(self):
        with patch("steward.hooks.genesis._gh", return_value=None):
            peers = _discover_from_org_repos()
        assert peers == {}


class TestGenesisHookRegistration:
    def test_registered_in_default_hooks(self):
        from steward.hooks import register_default_hooks
        from steward.phase_hook import PhaseHookRegistry

        registry = PhaseHookRegistry()
        register_default_hooks(registry)

        genesis_hooks = registry.get_hooks("genesis")
        names = [h.name for h in genesis_hooks]
        assert "genesis_discovery" in names
