"""Regression tests for the phonetic locality channel."""

from steward.antahkarana.manas import Manas
from vibe_core.mahamantra.adapters.compression import MahaCompression

VARIANTS = [
    "fix the failing test in test_agent.py",
    "fix the failing test in test_agent.py.",
    "Fix the failing test in test_agent.py",
    "fix the failing test in test_agent.py ",
]


def test_category_invariant_under_punctuation_and_case():
    """Punctuation and case variants keep the produced and consumed category."""
    results = [MahaCompression().compress(value) for value in VARIANTS]
    categories = {result.seed >> 24 for result in results}
    positions = {result.position for result in results}

    assert len(categories) == 1, f"Lokalitätskanal gebrochen: {categories}"
    assert len(positions) == 1, f"Kategoriefeld wird falsch gelesen: {positions}"


def test_tool_namespaces_invariant():
    """Manas classification must not become a punctuation/case lottery."""
    actions = {Manas().perceive(value).action for value in VARIANTS}

    assert len(actions) == 1, f"Tool-Lotterie aktiv: {actions}"
