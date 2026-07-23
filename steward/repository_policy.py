"""Explicit repository boundaries for legacy GitHub mutation paths."""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
AGENT_CITY_REPOSITORY = "kimeisele/agent-city"
STEWARD_REPOSITORY = "kimeisele/steward"


def parse_repository(value: str) -> str | None:
    """Parse an explicit owner/name or canonical GitHub PR URL."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if REPOSITORY_RE.fullmatch(value):
        return value
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 4 or parts[2] != "pull" or not parts[3].isdigit():
        return None
    repo = f"{parts[0]}/{parts[1]}"
    return repo if REPOSITORY_RE.fullmatch(repo) else None


def repository_from_pr_url(value: str) -> tuple[str, int] | None:
    repo = parse_repository(value)
    if repo is None or "/pull/" not in value:
        return None
    parsed = urlparse(value.strip())
    number = parsed.path.strip("/").split("/")[-1]
    return repo, int(number)


def allowed_mutation_repositories() -> frozenset[str]:
    """Resolve the explicit legacy allowlist; default is Steward itself only."""
    raw = os.environ.get("STEWARD_ALLOWED_MUTATION_REPOSITORIES", "")
    if not raw.strip():
        return frozenset({STEWARD_REPOSITORY})
    values = {item.strip() for item in raw.split(",") if item.strip()}
    return frozenset(value for value in values if REPOSITORY_RE.fullmatch(value))


def mutation_repository_allowed(repository: str) -> bool:
    return repository in allowed_mutation_repositories() and repository != AGENT_CITY_REPOSITORY
