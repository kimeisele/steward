"""
StewardIdentity — Deterministic fingerprint for fork/impersonation detection.

The fingerprint is SHA-256(agent_id + repo + identity_seed). The identity_seed
MUST come from environment variable STEWARD_IDENTITY_SEED, NOT hardcoded.
Otherwise forks can spoof the fingerprint by copying the seed.

Same steward + same secret → same fingerprint (deterministic).
Fingerprint change between heartbeats → trust reset (fork detection).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from steward import __version__


@dataclass(frozen=True)
class StewardIdentity:
    agent_id: str
    repo: str
    version: str
    fingerprint: str

    @classmethod
    def from_environment(
        cls,
        agent_id: str = "steward",
        repo: str = "",
    ) -> StewardIdentity:
        """Build identity from environment.

        Repo is resolved from data/federation/peer.json (nadi protocol).
        Fingerprint uses STEWARD_IDENTITY_SEED env var.
        """
        if not repo:
            repo = _load_repo_from_peer_json() or "steward"
        seed = os.environ.get("STEWARD_IDENTITY_SEED", "")
        fingerprint = cls.compute_fingerprint(agent_id, repo, seed)
        return cls(
            agent_id=agent_id,
            repo=repo,
            version=__version__,
            fingerprint=fingerprint,
        )


def _load_repo_from_peer_json() -> str:
    """Load repo identity from the nadi peer descriptor."""
    from pathlib import Path

    peer_path = Path("data/federation/peer.json")
    if not peer_path.exists():
        return ""
    try:
        import json

        data = json.loads(peer_path.read_text())
        return data.get("identity", {}).get("repo", "")
    except (json.JSONDecodeError, OSError):
        return ""

    @staticmethod
    def compute_fingerprint(agent_id: str, repo: str, seed: str) -> str:
        """Deterministic SHA-256 fingerprint."""
        raw = f"{agent_id}:{repo}:{seed}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "repo": self.repo,
            "version": self.version,
            "fingerprint": self.fingerprint,
        }
