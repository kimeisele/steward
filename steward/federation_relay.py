"""
Federation Hub Relay — GitHub API bridge between local transport and hub repo.

The federation hub (steward-federation) uses per-peer mailbox files to
eliminate merge conflicts:

    nadi/steward_to_agent-city.json     # steward writes, agent-city reads
    nadi/agent-city_to_steward.json     # agent-city writes, steward reads

Each file has EXACTLY ONE writer. No two repos ever write to the same file.

Migration: also reads/writes old nadi_outbox.json + nadi_inbox.json for
backward compatibility until all repos migrate.

Integration:
    DHARMA phase: relay.pull_from_hub()   — fetch inbound messages
    MOKSHA phase: relay.push_to_hub()     — deliver outbound messages

Requires GITHUB_TOKEN or GH_TOKEN in environment.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import uuid
from pathlib import Path

logger = logging.getLogger("STEWARD.FEDERATION.RELAY")

DEFAULT_HUB_REPO = "kimeisele/steward-federation"
GITHUB_API = "https://api.github.com"
MIN_RELAY_INTERVAL_S = 60
NADI_BUFFER_SIZE = 144


class DeliveryReceipt:
    """Tracks a batch of messages pushed to the hub.

    agent-internet defines DeliveryReceipt types for end-to-end confirmation.
    This is steward's implementation: record what was sent, verify consumption.
    """

    __slots__ = ("batch_id", "target", "message_ids", "pushed_at", "confirmed")

    def __init__(self, batch_id: str, target: str, message_ids: list[str], pushed_at: float) -> None:
        self.batch_id = batch_id
        self.target = target
        self.message_ids = message_ids
        self.pushed_at = pushed_at
        self.confirmed = False

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "target": self.target,
            "message_ids": self.message_ids,
            "pushed_at": self.pushed_at,
            "confirmed": self.confirmed,
        }


# Maximum pending receipts before oldest are pruned
MAX_PENDING_RECEIPTS = 64


class GitHubFederationRelay:
    """Relay messages between local federation transport and GitHub hub repo.

    Uses per-peer mailbox files: nadi/{sender}_to_{target}.json
    Each file has exactly one writer → zero merge conflicts.

    Delivery receipts track what was pushed and whether peers consumed it.
    Unconfirmed receipts older than RECEIPT_TTL_S are escalated via stats().

    Broadcast resolution: when target="*", resolves actual peers from
    the HeartbeatReaper registry (ALIVE + SUSPECT). Falls back to a
    minimal default list on cold start when the reaper has no peers.
    """

    RECEIPT_TTL_S = 3600.0  # 1 hour before unconfirmed receipt is stale

    # Minimal fallback peers for cold start when reaper has no entries.
    _FALLBACK_BROADCAST_PEERS: tuple[str, ...] = ("agent-world", "agent-internet")

    def __init__(
        self,
        agent_id: str = "steward",
        hub_repo: str = DEFAULT_HUB_REPO,
        local_outbox: Path | None = None,
        local_inbox: Path | None = None,
        reaper: object | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._hub_repo = hub_repo
        self._local_outbox = local_outbox or Path("data/federation/nadi_outbox.json")
        self._local_inbox = local_inbox or Path("data/federation/nadi_inbox.json")
        self._reaper = reaper
        self._token = self._load_token()
        self._last_pull: float = 0.0
        self._last_push: float = 0.0
        self._pull_count: int = 0
        self._push_count: int = 0
        self._errors: int = 0
        self._seen_ids: set[str] = set()  # UUID dedup
        self._pending_receipts: list[DeliveryReceipt] = []  # unconfirmed deliveries

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
            "User-Agent": "steward-federation-relay/2.0",
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
        body = json.dumps({"message": message, "content": encoded, "sha": sha}).encode()
        req = urllib.request.Request(url, data=body, headers=self._headers(), method="PUT")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning("Hub write %s failed: %s", path, e)
            self._errors += 1
            return False

    # ── PULL (DHARMA) ─────────────────────────────────────────────────

    def pull_from_hub(self) -> int:
        """Fetch messages targeted at this agent from hub.

        Reads:
        1. Per-peer mailboxes: nadi/*_to_{self}.json (new format)
        2. Legacy: nadi_outbox.json filtered by target (migration)

        Deduplicates by message UUID.
        """
        if not self._token:
            return 0

        now = time.monotonic()
        if (now - self._last_pull) < MIN_RELAY_INTERVAL_S:
            return 0

        all_messages: list[dict] = []

        # 1. NEW: Read per-peer mailboxes targeted at us
        try:
            import urllib.request

            url = f"{GITHUB_API}/repos/{self._hub_repo}/contents/nadi"
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=15) as resp:
                files = json.loads(resp.read())
                suffix = f"_to_{self._agent_id}.json"
                matching_files = [f for f in files if f.get("name", "").endswith(suffix)]
                logger.info(
                    "RELAY: scanning %d mailboxes for target %s", 
                    len(matching_files), 
                    self._agent_id
                )
                
                for f in matching_files:
                    msgs, _ = self._get_file(f"nadi/{f['name']}")
                    if msgs:
                        logger.info(
                            "RELAY: mailbox %s has %d messages", 
                            f['name'], 
                            len(msgs)
                        )
                    else:
                        logger.debug(
                            "RELAY: mailbox %s exists but empty", 
                            f['name']
                        )
                    all_messages.extend(msgs)
        except Exception as e:
            logger.debug("Per-peer mailbox scan failed: %s", e)

        # 2. LEGACY: Read old shared outbox + inbox (migration period)
        legacy, _ = self._get_file("nadi_outbox.json")
        for m in legacy:
            if isinstance(m, dict) and m.get("target") in (self._agent_id, "*"):
                all_messages.append(m)

        # 3. LEGACY: Read hub inbox (agent-city convention — targets may use
        #    repo names like "steward-protocol" instead of bare agent IDs)
        inbox_legacy, _ = self._get_file("nadi_inbox.json")
        for m in inbox_legacy:
            if isinstance(m, dict):
                target = m.get("target", "")
                if target in (self._agent_id, "*") or self._agent_id in target:
                    all_messages.append(m)

        if not all_messages:
            self._last_pull = time.monotonic()
            return 0

        # Dedup by UUID, then by (source, timestamp) for legacy messages
        new_msgs: list[dict] = []
        local = self._read_local_inbox()
        existing_keys = {(m.get("source", ""), m.get("timestamp", 0)) for m in local}

        for m in all_messages:
            msg_id = m.get("id", "")
            if msg_id and msg_id in self._seen_ids:
                continue
            if msg_id:
                self._seen_ids.add(msg_id)

            key = (m.get("source", ""), m.get("timestamp", 0))
            if key in existing_keys:
                continue
            existing_keys.add(key)
            new_msgs.append(m)

        if new_msgs:
            local.extend(new_msgs)
            self._write_local_inbox(local)
            logger.info("RELAY: pulled %d messages from hub → local inbox", len(new_msgs))

            # Confirm delivery receipts: if we got a response from a peer,
            # that peer consumed our messages (implicit ack)
            responding_peers = {m.get("source", "") for m in new_msgs if m.get("source")}
            for receipt in self._pending_receipts:
                if not receipt.confirmed and receipt.target in responding_peers:
                    receipt.confirmed = True
                    logger.debug("RELAY: delivery confirmed for batch %s → %s", receipt.batch_id, receipt.target)

        self._last_pull = time.monotonic()
        self._pull_count += len(new_msgs)
        return len(new_msgs)

    # ── PUSH (MOKSHA) ─────────────────────────────────────────────────

    def push_to_hub(self) -> int:
        """Push local outbox messages to hub per-peer mailboxes.

        Groups messages by target, writes each group to
        nadi/{self}_to_{target}.json. Also writes to legacy
        nadi_outbox.json for backward compatibility.
        """
        if not self._token:
            return 0

        now = time.monotonic()
        if (now - self._last_push) < MIN_RELAY_INTERVAL_S:
            return 0

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

        # Add UUID to messages that don't have one
        for m in local_msgs:
            if not m.get("id"):
                m["id"] = str(uuid.uuid4())

        # Resolve broadcast targets from reaper peer registry
        broadcast_peers = self._resolve_broadcast_peers()

        # Group by target, expanding "*" → actual peer IDs
        by_target: dict[str, list[dict]] = {}
        for m in local_msgs:
            target = m.get("target", "*")
            if target == "*":
                for peer_id in broadcast_peers:
                    by_target.setdefault(peer_id, []).append(m)
            else:
                by_target.setdefault(target, []).append(m)

        pushed = 0

        # 1. NEW: Write per-peer mailboxes
        for target, msgs in by_target.items():
            mailbox = f"nadi/{self._agent_id}_to_{target}.json"
            existing, sha = self._get_file(mailbox)
            if not sha:
                # Mailbox might not exist yet for this peer
                logger.debug("RELAY: no mailbox %s, using legacy", mailbox)
                continue
            existing.extend(msgs)
            if len(existing) > NADI_BUFFER_SIZE:
                existing = existing[-NADI_BUFFER_SIZE:]
            if self._put_file(mailbox, existing, sha, f"steward: {len(msgs)} msg → {target}"):
                pushed += len(msgs)
                logger.info("RELAY: pushed %d messages → %s", len(msgs), mailbox)

        # 2. LEGACY: Also write to shared outbox (migration period)
        legacy_pushed = False
        hub_outbox, sha = self._get_file("nadi_outbox.json")
        if sha:
            hub_outbox.extend(local_msgs)
            if len(hub_outbox) > NADI_BUFFER_SIZE:
                hub_outbox = hub_outbox[-NADI_BUFFER_SIZE:]
            if self._put_file("nadi_outbox.json", hub_outbox, sha, f"steward: relay {len(local_msgs)} messages"):
                legacy_pushed = True
                logger.info("RELAY: pushed %d messages to legacy hub outbox", len(local_msgs))

        # Clear local outbox only if at least one transport succeeded
        if pushed > 0 or legacy_pushed:
            self._local_outbox.write_text("[]")
            self._push_count += len(local_msgs)

            # Record delivery receipts for tracking
            for target, msgs in by_target.items():
                if target == "*":
                    continue
                msg_ids = [m.get("id", "") for m in msgs if m.get("id")]
                if msg_ids:
                    receipt = DeliveryReceipt(
                        batch_id=str(uuid.uuid4()),
                        target=target,
                        message_ids=msg_ids,
                        pushed_at=time.time(),
                    )
                    self._pending_receipts.append(receipt)
            # Prune oldest receipts if over limit
            if len(self._pending_receipts) > MAX_PENDING_RECEIPTS:
                self._pending_receipts = self._pending_receipts[-MAX_PENDING_RECEIPTS:]

        self._last_push = time.monotonic()
        return pushed or len(local_msgs)

    # ── Helpers ───────────────────────────────────────────────────────

    def _resolve_broadcast_peers(self) -> list[str]:
        """Resolve broadcast targets from reaper peer registry.

        Returns ALIVE + SUSPECT peer IDs (excluding self). Falls back to
        _FALLBACK_BROADCAST_PEERS on cold start when the reaper is empty
        or unavailable.
        """
        reaper = self._reaper

        # Try to get reaper from ServiceRegistry if not injected
        if reaper is None:
            try:
                from steward.services import SVC_REAPER
                from vibe_core.di import ServiceRegistry

                reaper = ServiceRegistry.get(SVC_REAPER)
            except Exception:
                pass

        if reaper is not None:
            try:
                peers = []
                for p in reaper.alive_peers() + reaper.suspect_peers():
                    if p.agent_id != self._agent_id:
                        peers.append(p.agent_id)
                if peers:
                    return peers
            except Exception as e:
                logger.debug("Broadcast peer resolution failed: %s", e)

        # Cold start fallback — minimal known peers
        return [p for p in self._FALLBACK_BROADCAST_PEERS if p != self._agent_id]

    def _read_local_inbox(self) -> list[dict]:
        if not self._local_inbox.exists():
            return []
        try:
            raw = json.loads(self._local_inbox.read_text())
            return raw if isinstance(raw, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _write_local_inbox(self, messages: list[dict]) -> None:
        self._local_inbox.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._local_inbox.with_suffix(".tmp")
        tmp.write_text(json.dumps(messages, indent=2))
        tmp.rename(self._local_inbox)

    def pending_receipts(self) -> list[DeliveryReceipt]:
        """Unconfirmed delivery receipts (for escalation by DHARMA phase)."""
        now = time.time()
        return [r for r in self._pending_receipts if not r.confirmed and (now - r.pushed_at) < self.RECEIPT_TTL_S]

    def stale_receipts(self) -> list[DeliveryReceipt]:
        """Receipts that exceeded TTL without confirmation (delivery failure signals)."""
        now = time.time()
        return [r for r in self._pending_receipts if not r.confirmed and (now - r.pushed_at) >= self.RECEIPT_TTL_S]

    def stats(self) -> dict:
        pending = self.pending_receipts()
        stale = self.stale_receipts()
        return {
            "available": self.available,
            "hub_repo": self._hub_repo,
            "pull_count": self._pull_count,
            "push_count": self._push_count,
            "errors": self._errors,
            "seen_ids": len(self._seen_ids),
            "pending_receipts": len(pending),
            "stale_receipts": len(stale),
            "stale_targets": list({r.target for r in stale}),
        }
