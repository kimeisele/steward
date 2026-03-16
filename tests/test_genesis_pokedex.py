"""Tests for GenesisPokedexSyncHook — agent-city Pokedex integration."""

import time
from unittest.mock import patch

import pytest

from steward.agent_deck import AgentCard, AgentDeck
from steward.hooks.genesis_pokedex import (
    GenesisPokedexSyncHook,
    convert_pokedex_entry,
)


# ── Sample pokedex entry (mirrors real agent-city format) ──────────

SAMPLE_ENTRY = {
    "name": "Hazel_OC",
    "seed": {
        "rama_coordinates": [48, 23, 10, 43, 12, 21],
        "signature": "021421121410221320074023511000",
        "coord_sum": 157,
        "coord_count": 6,
    },
    "elements": {"distribution": {"vayu": 3}, "dominant": "vayu"},
    "classification": {
        "guna": "RAJAS",
        "guna_description": "Active, opinionated, engaging",
        "varna": "PAKSHI",
        "varna_description": "Messenger",
        "zone": "governance",
    },
    "vitals": {"prana": 49, "prana_max": 108, "integrity": 0.542, "diw": 44125},
    "moltbook": {
        "karma": 1636,
        "is_active": True,
        "description": "Memory architect. Cron enthusiast.",
    },
    "status": "discovered",
}


class TestConvertPokedexEntry:
    def test_converts_valid_entry(self):
        card = convert_pokedex_entry(SAMPLE_ENTRY)
        assert card is not None
        assert card["name"] == "Hazel_OC"
        assert card["source"] == "agent-city:pokedex"
        assert card["spawn_count"] == 0
        assert card["success_count"] == 0
        # Weight derived from prana: 0.4 + 0.3 * (49/108) ~ 0.536
        assert 0.5 <= card["hebbian_weight"] <= 0.6

    def test_capabilities_from_zone(self):
        card = convert_pokedex_entry(SAMPLE_ENTRY)
        assert card is not None
        # governance zone -> review_code, code_review, analysis
        assert "review_code" in card["capabilities"]
        assert "code_review" in card["capabilities"]

    def test_capabilities_from_varna(self):
        card = convert_pokedex_entry(SAMPLE_ENTRY)
        assert card is not None
        # PAKSHI varna -> explore, codebase
        assert "explore" in card["capabilities"]
        assert "codebase" in card["capabilities"]

    def test_skips_archived_entry(self):
        entry = {**SAMPLE_ENTRY, "status": "archived"}
        assert convert_pokedex_entry(entry) is None

    def test_skips_exiled_entry(self):
        entry = {**SAMPLE_ENTRY, "status": "exiled"}
        assert convert_pokedex_entry(entry) is None

    def test_skips_frozen_entry(self):
        entry = {**SAMPLE_ENTRY, "status": "frozen"}
        assert convert_pokedex_entry(entry) is None

    def test_accepts_discovered_entry(self):
        entry = {**SAMPLE_ENTRY, "status": "discovered"}
        assert convert_pokedex_entry(entry) is not None

    def test_skips_entry_without_name(self):
        entry = {**SAMPLE_ENTRY, "name": ""}
        assert convert_pokedex_entry(entry) is None

    def test_seed_derived_from_coord_sum_and_diw(self):
        card = convert_pokedex_entry(SAMPLE_ENTRY)
        assert card is not None
        # coord_sum=157, diw=44125 -> seed = 157*10000 + 44125 = 1614125
        assert card["seed"] == 1614125

    def test_system_prompt_includes_identity(self):
        card = convert_pokedex_entry(SAMPLE_ENTRY)
        assert card is not None
        assert "Hazel_OC" in card["system_prompt"]
        assert "governance" in card["system_prompt"]
        assert "Memory architect" in card["system_prompt"]

    def test_engineering_zone_capabilities(self):
        entry = {**SAMPLE_ENTRY, "classification": {
            **SAMPLE_ENTRY["classification"],
            "zone": "engineering",
            "varna": "SHILPIN",
        }}
        card = convert_pokedex_entry(entry)
        assert card is not None
        assert "fix_tests" in card["capabilities"]
        assert "fix_lint" in card["capabilities"]


class TestGenesisPokedexSyncHook:
    def test_hook_properties(self):
        hook = GenesisPokedexSyncHook()
        assert hook.name == "genesis_pokedex_sync"
        assert hook.phase == "genesis"
        assert hook.priority == 25

    def test_should_run_respects_interval(self):
        hook = GenesisPokedexSyncHook()

        with patch("shutil.which", return_value="/usr/bin/gh"):
            ctx = _make_ctx()
            assert hook.should_run(ctx) is True

            hook._last_sync = time.time()
            ctx2 = _make_ctx()
            assert hook.should_run(ctx2) is False

    def test_should_run_skips_without_gh(self):
        hook = GenesisPokedexSyncHook()
        ctx = _make_ctx()

        with patch("shutil.which", return_value=None):
            assert hook.should_run(ctx) is False

    def test_ingests_cards_into_deck(self):
        """Mock _fetch_pokedex and verify cards get ingested."""
        from steward.services import SVC_AGENT_DECK
        from vibe_core.di import ServiceRegistry

        deck = AgentDeck()
        ServiceRegistry.register(SVC_AGENT_DECK, deck)

        try:
            hook = GenesisPokedexSyncHook()
            ctx = _make_ctx()

            agents = [
                SAMPLE_ENTRY,
                {**SAMPLE_ENTRY, "name": "TestBot", "status": "discovered",
                 "seed": {**SAMPLE_ENTRY["seed"], "coord_sum": 200},
                 "vitals": {**SAMPLE_ENTRY["vitals"], "diw": 55555}},
            ]

            with (
                patch("steward.hooks.genesis_pokedex._get_federation_owner", return_value="kimeisele"),
                patch("steward.hooks.genesis_pokedex._fetch_pokedex", return_value=agents),
            ):
                hook.execute(ctx)

            cards = deck.list_cards()
            assert len(cards) >= 2
            names = {c.name for c in cards}
            assert "Hazel_OC" in names
            assert "TestBot" in names
            assert any("genesis_pokedex_sync" in op for op in ctx.operations)
        finally:
            ServiceRegistry.reset_all()

    def test_local_proven_cards_not_overwritten(self):
        """Proven local cards should survive Pokedex sync."""
        from steward.services import SVC_AGENT_DECK
        from vibe_core.di import ServiceRegistry

        deck = AgentDeck()

        local_card = AgentCard(
            seed=1614125,
            name="local_proven",
            capabilities=("review_code",),
            hebbian_weight=0.9,
            spawn_count=10,
            success_count=8,
        )
        deck.register(local_card)
        ServiceRegistry.register(SVC_AGENT_DECK, deck)

        try:
            hook = GenesisPokedexSyncHook()
            ctx = _make_ctx()

            with (
                patch("steward.hooks.genesis_pokedex._get_federation_owner", return_value="kimeisele"),
                patch("steward.hooks.genesis_pokedex._fetch_pokedex", return_value=[SAMPLE_ENTRY]),
            ):
                hook.execute(ctx)

            card = deck.get(1614125)
            assert card is not None
            assert card.name == "local_proven"
            assert card.hebbian_weight == 0.9
        finally:
            ServiceRegistry.reset_all()

    def test_graceful_when_unavailable(self):
        """No crash when agent-city is unavailable."""
        from steward.services import SVC_AGENT_DECK
        from vibe_core.di import ServiceRegistry

        deck = AgentDeck()
        ServiceRegistry.register(SVC_AGENT_DECK, deck)

        try:
            hook = GenesisPokedexSyncHook()
            ctx = _make_ctx()

            with (
                patch("steward.hooks.genesis_pokedex._get_federation_owner", return_value="kimeisele"),
                patch("steward.hooks.genesis_pokedex._fetch_pokedex", return_value=None),
            ):
                hook.execute(ctx)

            assert len(deck.list_cards()) == 0
        finally:
            ServiceRegistry.reset_all()


class TestInstallStarterCardsPokedexSeeded:
    def test_pokedex_seeded_skips_covered_capabilities(self):
        """When pokedex_seeded=True, skip starters whose primary cap is covered."""
        from steward.agent_deck import install_starter_cards

        deck = AgentDeck()

        pokedex_card = AgentCard(
            seed=999999,
            name="PokedexFixer",
            capabilities=("fix_tests", "testing"),
            source="agent-city:pokedex",
        )
        deck.register(pokedex_card)

        installed = install_starter_cards(deck, pokedex_seeded=True)

        names = {c.name for c in deck.list_cards()}
        assert "PokedexFixer" in names
        assert installed < 5

    def test_pokedex_seeded_false_installs_all(self):
        """When pokedex_seeded=False (default), install all starters."""
        from steward.agent_deck import install_starter_cards

        deck = AgentDeck()
        installed = install_starter_cards(deck, pokedex_seeded=False)
        assert installed == 5


def _make_ctx():
    """Create a PhaseContext for testing."""
    from steward.phase_hook import PhaseContext
    return PhaseContext(cwd="/tmp")
