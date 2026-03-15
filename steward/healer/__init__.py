"""
Healer package — modular autonomous repair pipeline.

Split from monolithic healer.py into focused modules:
- types.py: FixStrategy, HealResult, classify(), _fixer registry
- fixers.py: 11 deterministic fixers (0 tokens each)
- compound.py: CI_FAILING compound pipeline
- helpers.py: TOML editing, package extraction, PR body, error summary
- pipeline.py: RepoHealer orchestrator
"""

# Import fixers to trigger @_fixer registration (side-effect imports)
import steward.healer.compound as _compound_module  # noqa: F401
import steward.healer.fixers as _fixers_module  # noqa: F401

# Re-export public API (backward compatible)
from steward.healer.compound import _COMPOUND_FIXERS, _fix_ci_failing
from steward.healer.fixers import (
    _IMPORT_TO_PIP,
    _fix_broken_import,
    _fix_circular_import,
    _fix_nadi_blocked,
    _fix_no_ci,
    _fix_no_federation_descriptor,
    _fix_no_peer_json,
    _fix_no_tests,
    _fix_syntax_error,
    _fix_undeclared_dependency,
)
from steward.healer.helpers import (
    _add_dependency_to_toml,
    _build_pr_body,
    _extract_ci_error_summary,
    _extract_package_from_finding,
)
from steward.healer.pipeline import RepoHealer
from steward.healer.types import (
    _FIXERS,
    FixStrategy,
    HealResult,
    _fixer,
    classify,
)

__all__ = [
    "FixStrategy",
    "HealResult",
    "RepoHealer",
    "classify",
    "_FIXERS",
    "_fixer",
    "_COMPOUND_FIXERS",
]
