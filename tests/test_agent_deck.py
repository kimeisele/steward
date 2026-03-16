"""Tests for AgentDeck — seed-based agent registry (Pokedex)."""

from steward.agent_deck import (
    _BREED_THRESHOLD,
    _MAX_CARDS,
    _MIN_SPAWNS_FOR_SHARE,
    _WEIGHT_BOOST,
    _WEIGHT_DECAY,
    AgentCard,
    AgentDeck,
    install_starter_cards,
)


class TestAgentCard:
    def test_card_creation(self):
        card = AgentCard(seed=42, name="test_agent")
        assert card.seed == 42
        assert card.name == "test_agent"
        assert card.hebbian_weight == 0.5
        assert card.spawn_count == 0
        assert card.success_count == 0

    def test_success_rate_zero_spawns(self):
        card = AgentCard(seed=1, name="x")
        assert card.success_rate == 0.0

    def test_success_rate(self):
        card = AgentCard(seed=1, name="x", spawn_count=10, success_count=7)
        assert card.success_rate == 0.7

    def test_is_proven_requires_weight_and_spawns(self):
        card = AgentCard(seed=1, name="x", hebbian_weight=_BREED_THRESHOLD, spawn_count=2)
        assert card.is_proven

        card2 = AgentCard(seed=2, name="y", hebbian_weight=_BREED_THRESHOLD, spawn_count=1)
        assert not card2.is_proven

        card3 = AgentCard(seed=3, name="z", hebbian_weight=0.1, spawn_count=5)
        assert not card3.is_proven

    def test_is_shareable_requires_successes(self):
        card = AgentCard(
            seed=1,
            name="x",
            hebbian_weight=0.8,
            spawn_count=5,
            success_count=_MIN_SPAWNS_FOR_SHARE,
        )
        assert card.is_shareable

        card2 = AgentCard(
            seed=2,
            name="y",
            hebbian_weight=0.8,
            spawn_count=5,
            success_count=_MIN_SPAWNS_FOR_SHARE - 1,
        )
        assert not card2.is_shareable

    def test_serialization_roundtrip(self):
        card = AgentCard(
            seed=42,
            name="test",
            capabilities=("fix_tests", "lint"),
            system_prompt="Be helpful",
            tool_filter=("bash", "edit"),
            hebbian_weight=0.75,
            spawn_count=10,
            success_count=8,
            source="peer-1",
        )
        data = card.to_dict()
        restored = AgentCard.from_dict(data)
        assert restored.seed == card.seed
        assert restored.name == card.name
        assert restored.capabilities == card.capabilities
        assert restored.system_prompt == card.system_prompt
        assert restored.tool_filter == card.tool_filter
        assert restored.hebbian_weight == card.hebbian_weight
        assert restored.spawn_count == card.spawn_count
        assert restored.success_count == card.success_count
        assert restored.source == card.source


class TestAgentDeckMatch:
    def test_exact_seed_match(self):
        deck = AgentDeck()
        card = AgentCard(seed=42, name="exact")
        deck.register(card)
        assert deck.match(seed=42) is card

    def test_capability_match(self):
        deck = AgentDeck()
        card = AgentCard(seed=42, name="linter", capabilities=("fix_lint",))
        deck.register(card)
        assert deck.match(capability="fix_lint") is card

    def test_capability_match_picks_highest_weight(self):
        deck = AgentDeck()
        weak = AgentCard(seed=1, name="weak", capabilities=("fix",), hebbian_weight=0.3)
        strong = AgentCard(seed=2, name="strong", capabilities=("fix",), hebbian_weight=0.9)
        deck.register(weak)
        deck.register(strong)
        assert deck.match(capability="fix") is strong

    def test_no_match_returns_none(self):
        deck = AgentDeck()
        assert deck.match(seed=999) is None
        assert deck.match(capability="nonexistent") is None

    def test_seed_takes_priority(self):
        deck = AgentDeck()
        card = AgentCard(seed=42, name="by_seed", capabilities=("other",))
        deck.register(card)
        assert deck.match(seed=42, capability="nonexistent") is card


class TestAgentDeckBreed:
    def test_breed_creates_card(self):
        deck = AgentDeck()
        card = deck.breed("tester", "Run pytest and fix failures", seed=100)
        assert card.seed == 100
        assert card.name == "tester"
        assert deck.get(100) is card

    def test_breed_does_not_overwrite_proven(self):
        deck = AgentDeck()
        proven = AgentCard(
            seed=100,
            name="proven_tester",
            hebbian_weight=0.9,
            spawn_count=5,
        )
        deck.register(proven)
        result = deck.breed("new_tester", "something", seed=100)
        assert result is proven
        assert result.name == "proven_tester"

    def test_breed_generates_system_prompt(self):
        deck = AgentDeck()
        card = deck.breed("fixer", "Fix all the things", seed=200)
        assert "fixer" in card.system_prompt
        assert "Fix all the things" in card.system_prompt

    def test_breed_with_capabilities(self):
        deck = AgentDeck()
        card = deck.breed(
            "tester",
            "Run tests",
            seed=300,
            capabilities=("pytest", "testing"),
        )
        assert card.capabilities == ("pytest", "testing")


class TestAgentDeckLearn:
    def test_success_boosts_weight(self):
        deck = AgentDeck()
        card = AgentCard(seed=1, name="x", hebbian_weight=0.5)
        deck.register(card)
        deck.learn(card, success=True)
        assert card.hebbian_weight == 0.5 + _WEIGHT_BOOST
        assert card.spawn_count == 1
        assert card.success_count == 1

    def test_failure_decays_weight(self):
        deck = AgentDeck()
        card = AgentCard(seed=1, name="x", hebbian_weight=0.5)
        deck.register(card)
        deck.learn(card, success=False)
        assert card.hebbian_weight == 0.5 - _WEIGHT_DECAY
        assert card.spawn_count == 1
        assert card.success_count == 0

    def test_weight_clamped_to_bounds(self):
        deck = AgentDeck()
        high = AgentCard(seed=1, name="high", hebbian_weight=0.99)
        deck.register(high)
        deck.learn(high, success=True)
        assert high.hebbian_weight == 1.0

        low = AgentCard(seed=2, name="low", hebbian_weight=0.01)
        deck.register(low)
        deck.learn(low, success=False)
        assert low.hebbian_weight == 0.0


class TestAgentDeckFederation:
    def test_shareable_cards(self):
        deck = AgentDeck()
        card = AgentCard(
            seed=1,
            name="proven",
            hebbian_weight=0.8,
            spawn_count=5,
            success_count=_MIN_SPAWNS_FOR_SHARE,
        )
        deck.register(card)
        shareable = deck.shareable_cards()
        assert card in shareable

    def test_ingest_shared_card(self):
        deck = AgentDeck()
        card_data = AgentCard(
            seed=99,
            name="remote_agent",
            capabilities=("ci_automation",),
            hebbian_weight=0.8,
            spawn_count=10,
            success_count=8,
        ).to_dict()

        result = deck.ingest_shared_card(card_data, source="peer-alpha")
        assert result is not None
        assert result.source == "peer-alpha"
        assert result.hebbian_weight == 0.8 * 0.8  # discounted
        assert result.spawn_count == 0  # reset for local validation

    def test_ingest_rejects_weaker_card(self):
        deck = AgentDeck()
        local = AgentCard(seed=99, name="local_strong", hebbian_weight=0.9)
        deck.register(local)

        card_data = AgentCard(
            seed=99,
            name="remote_weak",
            hebbian_weight=0.7,
        ).to_dict()

        result = deck.ingest_shared_card(card_data, source="peer-beta")
        assert result is None
        assert deck.get(99).name == "local_strong"

    def test_ingest_rejects_corrupt_data(self):
        deck = AgentDeck()
        result = deck.ingest_shared_card({"garbage": True}, source="peer")
        assert result is None


class TestAgentDeckPersistence:
    def test_save_and_load(self, tmp_path):
        deck = AgentDeck()
        deck.register(AgentCard(seed=1, name="alpha", capabilities=("a",), hebbian_weight=0.8))
        deck.register(AgentCard(seed=2, name="beta", capabilities=("b",), hebbian_weight=0.6))

        path = tmp_path / "deck.json"
        deck.save(path)

        deck2 = AgentDeck()
        loaded = deck2.load(path)
        assert loaded == 2
        assert deck2.get(1).name == "alpha"
        assert deck2.get(2).name == "beta"

    def test_load_missing_file(self, tmp_path):
        deck = AgentDeck()
        loaded = deck.load(tmp_path / "nonexistent.json")
        assert loaded == 0

    def test_load_corrupt_file(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("not json")
        deck = AgentDeck()
        loaded = deck.load(path)
        assert loaded == 0


class TestAgentDeckCapacity:
    def test_evicts_weakest_at_capacity(self):
        deck = AgentDeck()
        for i in range(_MAX_CARDS + 1):
            deck.register(AgentCard(seed=i, name=f"card_{i}", hebbian_weight=i / _MAX_CARDS))
        assert len(deck.list_cards()) == _MAX_CARDS


class TestStarterCards:
    def test_installs_starter_cards(self):
        deck = AgentDeck()
        installed = install_starter_cards(deck)
        assert installed == 5
        cards = deck.list_cards()
        names = {c.name for c in cards}
        assert "test_fixer" in names
        assert "lint_fixer" in names
        assert "code_reviewer" in names
        assert "dependency_updater" in names
        assert "explorer" in names

    def test_does_not_overwrite_existing(self):
        deck = AgentDeck()
        install_starter_cards(deck)
        # Modify a card
        cards = deck.list_cards()
        cards[0].hebbian_weight = 0.99
        # Re-install — should not overwrite
        installed = install_starter_cards(deck)
        assert installed == 0


class TestAgentDeckStats:
    def test_stats(self):
        deck = AgentDeck()
        deck.register(AgentCard(seed=1, name="a", hebbian_weight=0.8, spawn_count=5, success_count=4))
        deck.register(AgentCard(seed=2, name="b", hebbian_weight=0.3, spawn_count=3, success_count=1))
        s = deck.stats()
        assert s["total_cards"] == 2
        assert s["total_spawns"] == 8
        assert s["total_successes"] == 5
