"""
Federation Hub Relay — GitHub API bridge between local transport and hub repo.

The federation hub (steward-federation) is a shared GitHub repo that acts as
the message bus. Each agent:
  1. PUSHES its outbox messages → hub's nadi_inbox.json (for redistribution)
  2. PULLS hub's nadi_outbox.json → filters for messages targeted at self

This relay replaces the need for agent-internet's relay pump. It uses the
GitHub Contents API to read/write nadi files directly in the hub repo.

Integration:
    DHARMA phase: relay.pull_from_hub()   — fetch inbound messages
    MOKSHA phase: relay.push_to_hub()     — deliver outbound messages

Requires GITHUB_TOKEN in environment (or gh_token file).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("STEWARD.FEDERATION.RELAY")

# Default hub repo (owner/repo)
DEFAULT_HUB_REPO = "kimeisele/steward-federation"
GITHUB_API = "https://api.github.com"

# Minimum interval between relay operations (prevent API rate limiting)
MIN_RELAY_INTERVAL_S = 60


class GitHubFederationRelay:
    """Relay messages between local federation transport and GitHub hub repo.

    Uses GitHub Contents API — no git clone needed. Atomic read-modify-write
    with SHA-based optimistic concurrency (GitHub rejects stale SHAs).
    """

    def __init__(
        self,
        agent_id: str = "steward",
        hub_repo: str = DEFAULT_HUB_REPO,
        local_outbox: Path | None = None,
        local_inbox: Path | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._hub_repo = hub_repo
        self._local_outbox = local_outbox or Path("data/federation/nadi_outbox.json")
        self._local_inbox = local_inbox or Path("data/federation/nadi_inbox.json")
        self._token = self._load_token()
        self._last_pull: float = 0.0
        self._last_push: float = 0.0
        self._pull_count: int = 0
        self._push_count: int = 0
        self._errors: int = 0

    @property
    def available(self) -> bool:
        return bool(self._token)

    def _load_token(self) -> str:
        token = os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")
        if not token:
            token_file = Path.home() / ".config" / "gh_token"
            if token_file.exists():
                token = token_file.read_text().strip()
        return token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"token {self._token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "steward-federation-relay/1.0",
        }

    def _get_file(self, path: str) -> tuple[list, str]:
        """Fetch a JSON file from the hub repo. Returns (content, sha)."""
        import urllib.request

        url = f"{GITHUB_API}/repos/{self._hub_repo}/contents/{path}"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                content = json.loads(base64.b64decode(data["content"]).decode())
                return content if isinstance(content, list) else [], data["sha"]
        except Exception as e:
            logger.debug("Hub read %s failed: %s", path, e)
            return [], ""

    def _put_file(self, path: str, content: list, sha: str, message: str) -> bool:
        """Write a JSON file to the hub repo via Contents API."""
        import urllib.request

        url = f"{GITHUB_API}/repos/{self._hub_repo}/contents/{path}"
        encoded = base64.b64encode(json.dumps(content, indent=2).encode()).decode()
        body = json.dumps(
            {
                "message": message,
                "content": encoded,
                "sha": sha,
            }
        ).encode()
        req = urllib.request.Request(url, data=body, headers=self._headers(), method="PUT")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning("Hub write %s failed: %s", path, e)
            self._errors += 1
            return False

    def pull_from_hub(self) -> int:
        """Fetch messages from hub's outbox targeted at this agent.

        Reads hub nadi_outbox.json, filters for target=self._agent_id,
        appends to local nadi_inbox.json. Returns count of new messages.
        """
        if not self._token:
            return 0

        now = time.monotonic()
        if (now - self._last_pull) < MIN_RELAY_INTERVAL_S:
            return 0  # Throttled

        hub_outbox, _ = self._get_file("nadi_outbox.json")
        if not hub_outbox:
            self._last_pull = time.monotonic()
            return 0

        # Filter: messages targeted at us (or broadcast "*")
        for_us = [m for m in hub_outbox if isinstance(m, dict) and m.get("target") in (self._agent_id, "*")]
        if not for_us:
            self._last_pull = time.monotonic()
            return 0

        # Append to local inbox
        local: list[dict] = []
        if self._local_inbox.exists():
            try:
                raw = json.loads(self._local_inbox.read_text())
                if isinstance(raw, list):
                    local = raw
            except (json.JSONDecodeError, OSError):
                pass

        # Deduplicate by (source, timestamp)
        existing_keys = {(m.get("source", ""), m.get("timestamp", 0)) for m in local}
        new_msgs = [m for m in for_us if (m.get("source", ""), m.get("timestamp", 0)) not in existing_keys]

        if new_msgs:
            local.extend(new_msgs)
            self._local_inbox.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write: tmp → rename to prevent corruption on crash
            tmp = self._local_inbox.with_suffix(".tmp")
            tmp.write_text(json.dumps(local, indent=2))
            tmp.rename(self._local_inbox)
            logger.info("RELAY: pulled %d messages from hub → local inbox", len(new_msgs))

        self._last_pull = time.monotonic()
        self._pull_count += len(new_msgs)
        return len(new_msgs)

    def push_to_hub(self) -> int:
        """Push local outbox messages to hub's nadi_outbox.json.

        The hub is a shared message bus, not an agent — there is no
        inbox/outbox distinction at the hub level.  All agents push to
        nadi_outbox.json (the same file pull_from_hub reads from).
        Clears local outbox on success. Returns count pushed.
        """
        if not self._token:
            return 0

        now = time.monotonic()
        if (now - self._last_push) < MIN_RELAY_INTERVAL_S:
            return 0  # Throttled

        # Read local outbox
        if not self._local_outbox.exists():
            self._last_push = time.monotonic()
            return 0

        try:
            local_msgs = json.loads(self._local_outbox.read_text())
            if not isinstance(local_msgs, list) or not local_msgs:
                self._last_push = time.monotonic()
                return 0
        except (json.JSONDecodeError, OSError):
            self._last_push = time.monotonic()
            return 0

        # Read hub's current outbox (shared bus — same file pull reads from)
        hub_outbox, sha = self._get_file("nadi_outbox.json")
        if not sha:
            self._last_push = time.monotonic()
            self._errors += 1
            return 0

        # Append our messages to hub outbox
        hub_outbox.extend(local_msgs)

        # Cap at 144 messages (NADI_BUFFER_SIZE)
        if len(hub_outbox) > 144:
            hub_outbox = hub_outbox[-144:]

        # Write back to hub
        commit_msg = f"steward: relay {len(local_msgs)} messages to hub"
        if self._put_file("nadi_outbox.json", hub_outbox, sha, commit_msg):
            # Clear local outbox on success
            self._local_outbox.write_text("[]")
            self._last_push = time.monotonic()
            self._push_count += len(local_msgs)
            logger.info("RELAY: pushed %d messages to hub outbox", len(local_msgs))
            return len(local_msgs)

        self._last_push = time.monotonic()
        return 0

    def stats(self) -> dict:
        return {
            "available": self.available,
            "hub_repo": self._hub_repo,
            "pull_count": self._pull_count,
            "push_count": self._push_count,
            "errors": self._errors,
        }
