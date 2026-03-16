"""
AgentDeck — Seed-Based Agent Registry (Steward's Pokedex).

Agents are deterministic seeds. Each AgentCard encodes a specialized
agent profile: seed, capabilities, system prompt, tool filter, and
Hebbian effectiveness weight. The deck learns which profiles work
for which tasks and breeds new profiles from task descriptions.

Local use:  SubAgentTool queries the deck → spawns specialized agents.
Federation: OP_SHARE_AGENT_CARD shares proven profiles with peers.

Persistence: .steward/agent_deck.json
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("STEWARD.AGENT_DECK")

# Hebbian thresholds for agent card learning
_MIN_SPAWNS_FOR_SHARE = 3  # share with federation after N successful spawns
_WEIGHT_BOOST = 0.1  # success reward
_WEIGHT_DECAY = 0.05  # failure penalty
_BREED_THRESHOLD = 0.4  # minimum weight to consider a card "proven"
_MAX_CARDS = 256  # capacity limit


@dataclass
class AgentCard:
    """A reusable agent profile keyed by deterministic seed.

    The seed is derived from MahaCompression.compress(task_description).seed.
    Same task description = same seed = same agent profile = deterministic.
    """

    seed: int
    name: str
    capabilities: tuple[str, ...] = ()
    system_prompt: str = ""
    tool_filter: tuple[str, ...] = ()  # empty = all tools
    hebbian_weight: float = 0.5  # learned effectiveness (0.0-1.0)
    spawn_count: int = 0
    success_count: int = 0
    created_at: float = field(default_factory=time.time)
    source: str = "local"  # "local" or peer agent_id

    @property
    def success_rate(self) -> float:
        if self.spawn_count == 0:
            return 0.0
        return self.success_count / self.spawn_count

    @property
    def is_proven(self) -> bool:
        return self.hebbian_weight >= _BREED_THRESHOLD and self.spawn_count >= 2

    @property
    def is_shareable(self) -> bool:
        return self.success_count >= _MIN_SPAWNS_FOR_SHARE and self.is_proven

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "name": self.name,
            "capabilities": list(self.capabilities),
            "system_prompt": self.system_prompt,
            "tool_filter": list(self.tool_filter),
            "hebbian_weight": round(self.hebbian_weight, 4),
            "spawn_count": self.spawn_count,
            "success_count": self.success_count,
            "created_at": self.created_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AgentCard:
        return cls(
            seed=data["seed"],
            name=data["name"],
            capabilities=tuple(data.get("capabilities", ())),
            system_prompt=data.get("system_prompt", ""),
            tool_filter=tuple(data.get("tool_filter", ())),
            hebbian_weight=data.get("hebbian_weight", 0.5),
            spawn_count=data.get("spawn_count", 0),
            success_count=data.get("success_count", 0),
            created_at=data.get("created_at", 0.0),
            source=data.get("source", "local"),
        )


@dataclass
class AgentDeck:
    """The Pokedex — registry of agent profiles keyed by seed.

    Usage:
        deck = AgentDeck()
        card = deck.match(seed=12345, capability="fix_tests")
        if card:
            # spawn specialized agent with card.system_prompt + card.tool_filter
            ...
            deck.learn(card, success=True)
        else:
            # no match — breed a new card
            card = deck.breed("fix_tests", "Run and fix failing pytest tests", seed=12345)
    """

    _cards: dict[int, AgentCard] = field(default_factory=dict)
    _capability_index: dict[str, set[int]] = field(default_factory=dict)

    def register(self, card: AgentCard) -> None:
        """Add or update a card in the deck."""
        self._cards[card.seed] = card
        for cap in card.capabilities:
            self._capability_index.setdefault(cap, set()).add(card.seed)
        if len(self._cards) > _MAX_CARDS:
            self._evict_weakest()

    def get(self, seed: int) -> AgentCard | None:
        return self._cards.get(seed)

    def match(self, *, seed: int | None = None, capability: str = "") -> AgentCard | None:
        """Find the best agent card for a seed and/or capability.

        Priority:
        1. Exact seed match (if seed given and card exists)
        2. Best card with matching capability (highest hebbian_weight)
        3. None (no match — caller should breed or use generic)
        """
        # Exact seed match
        if seed is not None:
            card = self._cards.get(seed)
            if card is not None:
                return card

        # Capability match — pick highest weight
        if capability:
            candidates = self._capability_index.get(capability, set())
            if candidates:
                best = max(
                    (self._cards[s] for s in candidates if s in self._cards),
                    key=lambda c: c.hebbian_weight,
                    default=None,
                )
                return best

        return None

    def breed(
        self,
        name: str,
        task_description: str,
        *,
        seed: int | None = None,
        capabilities: tuple[str, ...] = (),
        system_prompt: str = "",
        tool_filter: tuple[str, ...] = (),
    ) -> AgentCard:
        """Create a new agent card from a task description.

        If seed is not provided, computes it from the task description
        via MahaCompression. The card starts with neutral weight (0.5)
        and must prove itself through learning.
        """
        if seed is None:
            seed = self._compute_seed(task_description)

        # Check if card already exists — don't overwrite proven cards
        existing = self._cards.get(seed)
        if existing is not None and existing.is_proven:
            logger.debug("DECK: card '%s' already proven — skipping breed", existing.name)
            return existing

        if not system_prompt:
            system_prompt = (
                f"You are a specialized agent for: {name}. "
                f"Task: {task_description}. "
                f"Complete the task efficiently and return a clear result."
            )

        card = AgentCard(
            seed=seed,
            name=name,
            capabilities=capabilities,
            system_prompt=system_prompt,
            tool_filter=tool_filter,
        )
        self.register(card)
        logger.info("DECK: bred new card '%s' (seed=%d)", name, seed)
        return card

    def learn(self, card: AgentCard, *, success: bool) -> None:
        """Update Hebbian weight after a spawn completes.

        Success boosts weight, failure decays it. Weights are clamped
        to [0.0, 1.0]. The card's spawn/success counters are also updated.
        """
        card.spawn_count += 1
        if success:
            card.success_count += 1
            card.hebbian_weight = min(1.0, card.hebbian_weight + _WEIGHT_BOOST)
        else:
            card.hebbian_weight = max(0.0, card.hebbian_weight - _WEIGHT_DECAY)

        logger.debug(
            "DECK: learn '%s' success=%s weight=%.2f (%d/%d)",
            card.name,
            success,
            card.hebbian_weight,
            card.success_count,
            card.spawn_count,
        )

    def shareable_cards(self) -> list[AgentCard]:
        """Cards proven enough to share with federation peers."""
        return [c for c in self._cards.values() if c.is_shareable]

    def ingest_shared_card(self, card_data: dict, source: str) -> AgentCard | None:
        """Ingest a card shared by a federation peer.

        Only accepts if:
        1. We don't have a better local card for this seed
        2. The shared card has reasonable weight
        """
        try:
            card = AgentCard.from_dict(card_data)
        except (KeyError, TypeError, ValueError) as e:
            logger.debug("DECK: rejected shared card: %s", e)
            return None

        card.source = source

        existing = self._cards.get(card.seed)
        if existing is not None and existing.hebbian_weight >= card.hebbian_weight:
            logger.debug(
                "DECK: local card '%s' (%.2f) beats shared '%s' (%.2f) — skipping",
                existing.name,
                existing.hebbian_weight,
                card.name,
                card.hebbian_weight,
            )
            return None

        # Discount foreign cards slightly — trust but verify
        card.hebbian_weight *= 0.8
        card.spawn_count = 0  # reset counters — needs local validation
        card.success_count = 0

        self.register(card)
        logger.info("DECK: ingested shared card '%s' from %s (seed=%d)", card.name, source, card.seed)
        return card

    def list_cards(self) -> list[AgentCard]:
        return list(self._cards.values())

    def stats(self) -> dict:
        cards = self.list_cards()
        proven = [c for c in cards if c.is_proven]
        return {
            "total_cards": len(cards),
            "proven_cards": len(proven),
            "shareable_cards": len(self.shareable_cards()),
            "total_spawns": sum(c.spawn_count for c in cards),
            "total_successes": sum(c.success_count for c in cards),
            "avg_weight": sum(c.hebbian_weight for c in cards) / len(cards) if cards else 0.0,
        }

    # ── Persistence ──────────────────────────────────────────────────

    def save(self, path: Path) -> None:
        data = {
            "version": 1,
            "saved_at": time.time(),
            "cards": [c.to_dict() for c in self._cards.values()],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2))
        temp.replace(path)

    def load(self, path: Path) -> int:
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return 0

        loaded = 0
        for entry in data.get("cards", []):
            try:
                card = AgentCard.from_dict(entry)
                self.register(card)
                loaded += 1
            except (KeyError, TypeError, ValueError) as e:
                logger.debug("Skipped corrupt agent card: %s", e)
        return loaded

    # ── Private ──────────────────────────────────────────────────────

    def _evict_weakest(self) -> None:
        """Remove the weakest card when at capacity."""
        if not self._cards:
            return
        weakest = min(self._cards.values(), key=lambda c: (c.hebbian_weight, -c.created_at))
        del self._cards[weakest.seed]
        for cap in weakest.capabilities:
            seeds = self._capability_index.get(cap)
            if seeds:
                seeds.discard(weakest.seed)
        logger.debug("DECK: evicted weakest card '%s' (weight=%.2f)", weakest.name, weakest.hebbian_weight)

    @staticmethod
    def _compute_seed(text: str) -> int:
        """Compute deterministic seed from text via MahaCompression."""
        from vibe_core.mahamantra.adapters.compression import MahaCompression

        mc = MahaCompression()
        return mc.compress(text).seed


# ── Built-in Starter Cards ────────────────────────────────────────────

_STARTER_CARDS = [
    AgentCard(
        seed=0,  # placeholder — computed at registration
        name="test_fixer",
        capabilities=("fix_tests", "pytest", "testing"),
        system_prompt=(
            "You are a test-fixing specialist. Diagnose failing tests, "
            "read the test file and source code, identify the root cause, "
            "and fix it. Prefer minimal changes. Run pytest to verify."
        ),
        tool_filter=("read_file", "edit", "bash", "grep", "glob"),
    ),
    AgentCard(
        seed=0,
        name="lint_fixer",
        capabilities=("fix_lint", "ruff", "linting"),
        system_prompt=(
            "You are a lint-fixing specialist. Run ruff check, read the "
            "violations, and fix them. Prefer auto-fixable rules. "
            "Run ruff check again to verify all violations are resolved."
        ),
        tool_filter=("read_file", "edit", "bash", "grep", "glob"),
    ),
    AgentCard(
        seed=0,
        name="code_reviewer",
        capabilities=("review_code", "code_review", "analysis"),
        system_prompt=(
            "You are a code review specialist. Analyze the code for: "
            "correctness, security (OWASP top 10), performance, readability. "
            "Report findings with severity and specific line references."
        ),
        tool_filter=("read_file", "grep", "glob", "bash"),
    ),
    AgentCard(
        seed=0,
        name="dependency_updater",
        capabilities=("update_deps", "dependencies", "pip"),
        system_prompt=(
            "You are a dependency update specialist. Check for outdated "
            "packages, update pyproject.toml, run tests to verify compatibility. "
            "Create atomic updates — one package at a time if risky."
        ),
        tool_filter=("read_file", "edit", "bash", "grep", "glob"),
    ),
    AgentCard(
        seed=0,
        name="explorer",
        capabilities=("explore", "codebase", "architecture"),
        system_prompt=(
            "You are a codebase exploration specialist. Map the architecture, "
            "find key files, understand patterns, and report your findings "
            "in a structured format. Do not modify any files."
        ),
        tool_filter=("read_file", "grep", "glob", "bash"),
    ),
]


def install_starter_cards(deck: AgentDeck) -> int:
    """Register built-in starter cards with computed seeds.

    Starter cards are Steward's core agent profiles — always installed,
    never skipped. Only cards that already exist are preserved (learned
    weights survive across restarts). Federation-imported cards are
    additive and never replace starters.

    Returns count of newly installed cards.
    """
    installed = 0
    for template in _STARTER_CARDS:
        seed = deck._compute_seed(template.name)
        if deck.get(seed) is not None:
            continue  # already exists — don't overwrite
        card = AgentCard(
            seed=seed,
            name=template.name,
            capabilities=template.capabilities,
            system_prompt=template.system_prompt,
            tool_filter=template.tool_filter,
            source="starter",
        )
        deck.register(card)
        installed += 1
    return installed
