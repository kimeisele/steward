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
        repo: str = "kimeisele/steward",
    ) -> StewardIdentity:
        """Build identity from environment. Fingerprint uses STEWARD_IDENTITY_SEED."""
        seed = os.environ.get("STEWARD_IDENTITY_SEED", "")
        fingerprint = cls.compute_fingerprint(agent_id, repo, seed)
        return cls(
            agent_id=agent_id,
            repo=repo,
            version=__version__,
            fingerprint=fingerprint,
        )

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
