"""
Federation Bridge — Routes cross-agent messages to local services.

Steward's Reaper and Marketplace are local in-process services. The
federation bridge connects them to the outside world:

    INBOUND:  FederationMessage → route by operation → Reaper/Marketplace
    OUTBOUND: local events → FederationMessage → any transport

The bridge is transport-agnostic. Any transport implementing the
FederationTransport protocol (agent-internet's FilesystemTransport,
wiki sync, HTTP, MCP) can plug in. No hardcoded repos.

Integration:
    DHARMA phase: bridge.process_inbound(transport)
    MOKSHA phase: bridge.flush_outbound(transport)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from steward.federation_crypto import derive_node_id, sign_payload_hash
from vibe_core.mahamantra.federation.types import FederationMessage

logger = logging.getLogger("STEWARD.FEDERATION")

# ── Protocols ──────────────────────────────────────────────────────

# These protocols define what the bridge needs. Any transport or
# service that matches can plug in — no imports required.


@runtime_checkable
class FederationTransport(Protocol):
    """Transport layer for federation messages.

    Matches agent-internet's FederationTransport interface.
    Implementations: FilesystemFederationTransport, wiki sync, HTTP.
    """

    def read_outbox(self) -> list[dict]: ...
    def append_to_inbox(self, messages: list[object]) -> int: ...


@runtime_checkable
class ReaperLike(Protocol):
    """Anything that accepts heartbeats and reaps dead peers."""

    def record_heartbeat(
        self,
        agent_id: str,
        timestamp: float | None = None,
        source: str = "",
    ) -> None: ...

    def reap(self, now: float | None = None) -> list: ...

    def alive_peers(self) -> list: ...

    def suspect_peers(self) -> list: ...

    def dead_peers(self) -> list: ...

    def get_peer(self, agent_id: str) -> object | None: ...


@runtime_checkable
class MarketplaceLike(Protocol):
    """Anything that handles slot claims."""

    def claim(
        self,
        slot_id: str,
        agent_id: str,
        trust: float = 0.0,
        ttl_s: float | None = None,
    ) -> object: ...

    def release(self, slot_id: str, agent_id: str) -> bool: ...


# ── Wire Format ───────────────────────────────────────────────────

# Operations the bridge understands. Aligned with steward-protocol's
# FederationMessage.operation field.

OP_HEARTBEAT = "heartbeat"
OP_CLAIM_SLOT = "claim_slot"
OP_RELEASE_SLOT = "release_slot"
OP_EVICTION = "eviction"
OP_CLAIM_OUTCOME = "claim_outcome"
OP_DELEGATE_TASK = "delegate_task"
OP_TASK_COMPLETED = "task_completed"
OP_TASK_FAILED = "task_failed"
OP_DIAGNOSTIC_REQUEST = "diagnostic_request"
OP_DIAGNOSTIC_REPORT = "diagnostic_report"
OP_MERGE_OCCURRED = "merge_occurred"
OP_PR_CREATED = "pr_created"
OP_CI_STATUS = "ci_status"
OP_PR_REVIEW_REQUEST = "pr_review_request"
OP_PR_REVIEW_VERDICT = "pr_review_verdict"
OP_WORLD_STATE_UPDATE = "world_state_update"
OP_POLICY_UPDATE = "policy_update"
OP_CITY_REPORT = "city_report"
OP_BOTTLENECK_ESCALATION = "bottleneck_escalation"
OP_BOTTLENECK_RESOLUTION = "bottleneck_resolution"
OP_COMPLIANCE_REPORT = "compliance_report"
OP_GOVERNANCE_BOUNTY = "governance_bounty"
OP_AGENT_CLAIM = "federation.agent_claim"
OP_FEDERATION_NODE_HEALTH = "federation.node_health"
NODE_HEALTH_PROTOCOL_VERSION = "1.0"

ALL_OPERATIONS = {
    OP_HEARTBEAT,
    OP_CLAIM_SLOT,
    OP_RELEASE_SLOT,
    OP_EVICTION,
    OP_CLAIM_OUTCOME,
    OP_DELEGATE_TASK,
    OP_TASK_COMPLETED,
    OP_TASK_FAILED,
    OP_DIAGNOSTIC_REQUEST,
    OP_DIAGNOSTIC_REPORT,
    OP_MERGE_OCCURRED,
    OP_PR_CREATED,
    OP_CI_STATUS,
    OP_PR_REVIEW_REQUEST,
    OP_PR_REVIEW_VERDICT,
    OP_WORLD_STATE_UPDATE,
    OP_POLICY_UPDATE,
    OP_CITY_REPORT,
    OP_BOTTLENECK_ESCALATION,
    OP_BOTTLENECK_RESOLUTION,
    OP_COMPLIANCE_REPORT,
    OP_GOVERNANCE_BOUNTY,
    OP_AGENT_CLAIM,
    OP_FEDERATION_NODE_HEALTH,
}
PUBLIC_OPERATIONS = {OP_AGENT_CLAIM, OP_FEDERATION_NODE_HEALTH}
PROTECTED_OPERATIONS = ALL_OPERATIONS - PUBLIC_OPERATIONS

# Mission name prefixes emitted by agent-city's create_brain_mission().
# Verified from kimeisele/agent-city city/missions.py — Brain {verb}: {target[:50]}
CITY_BOTTLENECK_PREFIX = "Brain bottleneck: "
CITY_ESCALATION_PREFIX = "Brain escalation: "

# Minimum trust level to accept inbound delegations
DEFAULT_DELEGATION_TRUST_FLOOR: float = 0.3

# Module-level stores for world authority messages.
# Other components can query these for current world state and policies.
_latest_world_state: dict | None = None
_latest_policies: dict | None = None
_latest_city_reports: dict[str, dict] = {}


def get_world_state() -> dict | None:
    """Return the latest world state received from agent-world."""
    return _latest_world_state


def get_policies() -> dict | None:
    """Return the latest policies received from agent-world."""
    return _latest_policies


def get_city_reports() -> dict[str, dict]:
    """Return the latest city reports keyed by source agent."""
    return dict(_latest_city_reports)


def _normalize_bottleneck_contract(value: str) -> str:
    lowered = value.lower().strip()
    if "ruff" in lowered:
        return "ruff_clean"
    if "tests_pass" in lowered or "test_pass" in lowered or "tests" in lowered:
        return "tests_pass"
    if "integrity" in lowered:
        return "integrity"
    if "code_health" in lowered:
        return "code_health"
    token = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return token[:80] or "unknown"


def _bottleneck_dedup_key(
    payload: dict,
    *,
    source_agent: str = "agent-city",
    fallback_target: str = "",
) -> str:
    issue_key = str(payload.get("issue_key", "")).strip()
    if issue_key:
        return issue_key[:160]

    target_repo = str(payload.get("target_repo", source_agent)).strip() or source_agent
    contract_name = str(payload.get("contract_name", "")).strip()
    if not contract_name:
        contract_name = _normalize_bottleneck_contract(
            str(payload.get("target", fallback_target))
        )
    return f"{target_repo}:{contract_name}"[:160]


def _normalize_governance_policy(value: str) -> str:
    lowered = value.lower().strip()
    if not lowered:
        return ""
    segments = [segment.strip() for segment in lowered.split(":") if segment.strip()]
    if len(segments) >= 2 and segments[0] in {"fix", "policy", "violation"}:
        lowered = segments[1]
    token = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return token[:80]


def _governance_dedup_key(payload: dict) -> str:
    violation_id = str(payload.get("violation_id", "")).strip()
    if violation_id:
        return violation_id[:160]

    policy_name = str(payload.get("policy_name", "")).strip()
    if not policy_name:
        policy_name = _normalize_governance_policy(str(payload.get("target", "")))
    target_repo = str(payload.get("target_repo", "")).strip()

    if target_repo and policy_name:
        return f"{target_repo}:{policy_name}"[:160]
    if target_repo:
        return target_repo[:160]
    if policy_name:
        return policy_name[:160]
    return "governance:unknown"


def _task_has_dedup_key(task: object, dedup_key: str) -> bool:
    title = getattr(task, "title", "") or ""
    description = getattr(task, "description", "") or ""
    return dedup_key in title or dedup_key in description


@dataclass(frozen=True)
class BridgeEvent:
    """Outbound event produced by local services for federation broadcast."""

    operation: str
    agent_id: str
    payload: dict
    timestamp: float


# ── Bridge ────────────────────────────────────────────────────────


@dataclass
class FederationBridge:
    """Routes federation messages to local Reaper + Marketplace.

    Usage:
        bridge = FederationBridge(reaper=reaper, marketplace=marketplace)

        # DHARMA phase — consume inbound messages
        bridge.process_inbound(transport)

        # MOKSHA phase — publish outbound events
        bridge.flush_outbound(transport)

    The bridge is stateless except for the outbound queue. It doesn't
    care where messages come from — any FederationTransport works.
    """

    reaper: ReaperLike | None = None
    marketplace: MarketplaceLike | None = None
    agent_id: str = "steward"  # our identity in federation messages
    delegation_trust_floor: float = DEFAULT_DELEGATION_TRUST_FLOOR
    peer_registry_path: str | Path | None = None
    verified_agents_path: str | Path | None = None

    _outbound: list[BridgeEvent] = field(default_factory=list)
    _inbound_count: int = field(default=0, init=False)
    _outbound_count: int = field(default=0, init=False)
    _errors: int = field(default=0, init=False)
    _delegations_rejected: int = field(default=0, init=False)
    _op_dispatch: dict = field(default=None, init=False, repr=False)

    # Outbound-signing identity — lazy-loaded from NODE_PRIVATE_KEY env on
    # first flush_outbound. None means no signing (legacy fallback, logs WARNING).
    _node_identity_cache: dict | None = field(default=None, init=False, repr=False)
    _node_identity_loaded: bool = field(default=False, init=False, repr=False)
    _self_claim_done: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._op_dispatch = {
            OP_HEARTBEAT: self._handle_heartbeat,
            OP_CLAIM_SLOT: self._handle_claim,
            OP_RELEASE_SLOT: self._handle_release,
            OP_DELEGATE_TASK: self._handle_delegate_task,
            OP_TASK_COMPLETED: self._handle_task_callback,
            OP_TASK_FAILED: self._handle_task_callback,
            OP_PR_REVIEW_REQUEST: self._handle_pr_review_request,
            OP_WORLD_STATE_UPDATE: self._handle_world_state_update,
            OP_POLICY_UPDATE: self._handle_policy_update,
            OP_CITY_REPORT: self._handle_city_report,
            OP_BOTTLENECK_ESCALATION: self._handle_bottleneck_escalation,
            OP_COMPLIANCE_REPORT: self._handle_compliance_report,
            OP_GOVERNANCE_BOUNTY: self._handle_governance_bounty,
            OP_AGENT_CLAIM: self._handle_agent_claim,
            OP_FEDERATION_NODE_HEALTH: self._handle_node_health,
        }

    def _peer_registry_file(self) -> Path:
        if self.peer_registry_path is not None:
            return Path(self.peer_registry_path)
        return Path("data") / "federation" / "peer_registry.json"

    def _verified_agents_file(self) -> Path:
        if self.verified_agents_path is not None:
            return Path(self.verified_agents_path)
        return Path("data") / "federation" / "verified_agents.json"

    def _load_peer_registry(self) -> dict[str, dict]:
        path = self._peer_registry_file()
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_peer_registry(self, registry: dict[str, dict]) -> None:
        path = self._peer_registry_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(registry, indent=2, sort_keys=True))
        tmp.replace(path)

    def _load_verified_agents(self) -> dict[str, dict]:
        path = self._verified_agents_file()
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_verified_agents(self, registry: dict[str, dict]) -> None:
        """Persist registry to disk with byte-level idempotency.

        Skips the write entirely when the on-disk content is byte-identical to
        what we would write. This keeps the steward heartbeat workflow from
        producing spurious "chore: update verified_agents" commits when claim
        messages arrive but carry no new information.
        """
        path = self._verified_agents_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(registry, indent=2, sort_keys=True)
        if path.exists():
            try:
                if path.read_text() == content:
                    logger.debug(
                        "FEDERATION: verified_agents unchanged (%d entries) — skip write",
                        len(registry),
                    )
                    return
            except OSError:
                pass
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(content)
        tmp.replace(path)
        logger.info("FEDERATION: saved verified_agents (%d entries) to %s", len(registry), path.resolve())

    def is_verified_agent(self, agent_name: str) -> bool:
        agent_id = str(agent_name or "").strip()
        if not agent_id:
            return False
        registry = self._load_verified_agents()
        return isinstance(registry.get(agent_id), dict)

    def get_verified_agent(self, agent_name: str) -> dict[str, object] | None:
        agent_id = str(agent_name or "").strip()
        if not agent_id:
            return None
        registry = self._load_verified_agents()
        record = registry.get(agent_id)
        return record if isinstance(record, dict) else None

    def _protocol_major(self, value: object) -> int | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        token = raw[1:] if raw.lower().startswith("v") else raw
        major = token.split(".", 1)[0].strip()
        return int(major) if major.isdigit() else None

    def _circuit_breaker_reason(self, target: str, operation: str, registry: dict[str, dict]) -> str:
        if operation == OP_FEDERATION_NODE_HEALTH:
            return ""
        peer = registry.get(target)
        if not isinstance(peer, dict):
            return ""
        status = str(peer.get("status", "")).strip().upper()
        if status == "CRITICAL":
            return "circuit_breaker_peer_critical"
        peer_major = self._protocol_major(peer.get("protocol_version", ""))
        local_major = self._protocol_major(NODE_HEALTH_PROTOCOL_VERSION)
        if peer_major is not None and local_major is not None and peer_major != local_major:
            return "circuit_breaker_protocol_mismatch"
        return ""

    def ingest(self, operation: str, payload: dict) -> bool:
        """Route inbound message via O(1) dispatch table."""
        self._inbound_count += 1
        handler = self._op_dispatch.get(operation)
        if handler is None:
            logger.debug("BRIDGE: unknown operation '%s'", operation)
            return False
        return handler(payload)

    def process_inbound(self, transport: FederationTransport) -> int:
        """Read all pending messages from transport and route them.

        Returns count of messages processed.
        """
        try:
            messages = transport.read_outbox()
        except Exception as e:
            logger.warning("BRIDGE: read_outbox failed: %s", e)
            self._errors += 1
            return 0

        processed = 0
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            op = msg.get("operation", "")
            payload = msg.get("payload", {})
            # Inject source from message envelope so handlers can identify the sender.
            # agent-city's FederationNadi overrides source to city_id from peer.json.
            if "source_agent" not in payload and "source" in msg:
                payload["source_agent"] = msg["source"]

            # Record heartbeat for peer — ANY inbound message proves peer is alive
            source_agent = payload.get("source_agent") or msg.get("source")
            if source_agent and self.reaper is not None:
                self.reaper.record_heartbeat(
                    agent_id=source_agent,
                    source="federation_inbound",
                )

            if self.ingest(op, payload):
                processed += 1
        return processed

    def _load_node_identity(self) -> dict | None:
        """Lazy-load NODE_PRIVATE_KEY env into a node-identity dict.

        Returns {node_id, public_key, private_key} or None if env is unset
        or malformed. Cached after first call.
        """
        if self._node_identity_loaded:
            return self._node_identity_cache
        self._node_identity_loaded = True

        env_key = (os.environ.get("NODE_PRIVATE_KEY") or "").strip()
        if not env_key:
            logger.warning(
                "BRIDGE: NODE_PRIVATE_KEY env unset — outbound messages will be unsigned"
            )
            return None

        # NODE_PRIVATE_KEY is the raw 32-byte seed (hex) OR a JSON node-keys
        # blob (Genesis-Hook stores the latter). Accept both.
        priv_hex = env_key
        try:
            blob = json.loads(env_key)
            if isinstance(blob, dict) and blob.get("private_key"):
                priv_hex = str(blob["private_key"]).strip()
        except (json.JSONDecodeError, TypeError):
            pass

        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            raw = bytes.fromhex(priv_hex)
            if len(raw) != 32:
                raise ValueError(f"expected 32 raw bytes, got {len(raw)}")
            sk = Ed25519PrivateKey.from_private_bytes(raw)
            pub_hex = sk.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            ).hex()
            self._node_identity_cache = {
                "private_key": priv_hex,
                "public_key": pub_hex,
                "node_id": derive_node_id(pub_hex),
            }
            logger.info(
                "BRIDGE: NODE_PRIVATE_KEY loaded — node_id=%s public_key=%s",
                self._node_identity_cache["node_id"], pub_hex,
            )
            return self._node_identity_cache
        except (ValueError, TypeError, ImportError) as e:
            logger.error("BRIDGE: failed to parse NODE_PRIVATE_KEY: %s", e)
            return None

    def _sign_message_dict(self, msg: dict, identity: dict) -> dict:
        """Attach canonical sha256 payload_hash + base64 ed25519 signature.

        Same convention as agent-city's FederationRelay._sign_payload and
        steward-federation/nadi_kit's _sign_message — wire format compatible
        with steward.federation_crypto.verify_payload_signature.
        """
        canonical = {k: v for k, v in msg.items() if k not in ("payload_hash", "signature")}
        payload_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True).encode("utf-8")
        ).hexdigest()
        signature = sign_payload_hash(identity["private_key"], payload_hash)
        return {**canonical, "payload_hash": payload_hash, "signature": signature}

    def _ensure_self_registered(self) -> None:
        """Register steward's own identity in verified_agents.json (idempotent).

        Dogfooding: steward is a federation node like any other. Its outbound
        messages now carry source=node_id and a signature, so receivers (and
        steward's own gateway via the NADI loop-back) need a verified_agents
        entry to authenticate them. The self-claim goes through the same
        _handle_agent_claim path that every other node uses, including the
        derive_node_id consistency check.

        Sentinel-bound: a fresh sentinel per public_key digest means a key
        rotation triggers a fresh self-claim automatically.
        """
        if self._self_claim_done:
            return
        identity = self._load_node_identity()
        if identity is None:
            self._self_claim_done = True
            return
        token = hashlib.sha256(identity["public_key"].encode("utf-8")).hexdigest()[:16]
        sentinel_dir = self._verified_agents_file().parent
        sentinel_dir.mkdir(parents=True, exist_ok=True)
        sentinel = sentinel_dir / f".self_claim_sent_{token}"
        if sentinel.exists():
            self._self_claim_done = True
            return
        capabilities = ["operator", "federation_gateway", "registry_authority"]
        ok = self._handle_agent_claim({
            "node_id": identity["node_id"],
            "agent_name": self.agent_id,
            "public_key": identity["public_key"],
            "capabilities": capabilities,
        })
        if ok:
            try:
                sentinel.write_text("")
            except OSError as e:
                logger.warning("BRIDGE: self-claim sentinel write failed: %s", e)
        self._self_claim_done = True
        logger.info(
            "BRIDGE: self-claim done — node_id=%s pubkey_token=%s ok=%s",
            identity["node_id"], token, ok,
        )

    def flush_outbound(self, transport: FederationTransport) -> int:
        """Publish all pending outbound events via transport.

        Returns count of messages published. Each message is signed with
        steward's NODE_PRIVATE_KEY (loaded once, cached) before transport
        delivery. If the env is unset, messages go out unsigned and
        downstream receivers with hard crypto gates will reject them —
        WARNING is logged on first call.
        """
        self._ensure_self_registered()
        if not self._outbound:
            return 0
        identity = self._load_node_identity()

        # Get known peer IDs for targeted delivery (not broadcast *)
        peer_ids = []
        if self.reaper is not None:
            for p in self.reaper.alive_peers() + self.reaper.suspect_peers():
                if p.agent_id != self.agent_id:
                    peer_ids.append(p.agent_id)

        messages = []
        blocked_messages = []
        registry = self._load_peer_registry()
        # source on the wire is the cryptographic node_id when available, so
        # downstream verified_agents.json lookups (keyed by node_id) succeed.
        # Falls back to agent_id when env is unset — keeps legacy behaviour.
        source_id = identity["node_id"] if identity else self.agent_id
        for event in self._outbound:
            targets = peer_ids if peer_ids else ["*"]
            for target in targets:
                msg = FederationMessage(
                    source=source_id,
                    target=target,
                    operation=event.operation,
                    payload=event.payload,
                    timestamp=event.timestamp,
                    priority=1,
                    correlation_id="",
                    ttl_s=900.0,
                )
                payload = msg.to_dict()
                reason = self._circuit_breaker_reason(target, event.operation, registry)
                if reason:
                    blocked_messages.append((payload, reason))
                    continue
                if identity is not None:
                    payload = self._sign_message_dict(payload, identity)
                messages.append(payload)

        if blocked_messages and hasattr(transport, "quarantine_messages"):
            for payload, reason in blocked_messages:
                transport.quarantine_messages(
                    [payload],
                    reason=reason,
                    stage="routing_outbound",
                    metadata={"target": payload.get("target", ""), "operation": payload.get("operation", "")},
                )

        try:
            count = transport.append_to_inbox(messages)
            self._outbound_count += len(self._outbound)
            self._outbound.clear()
            return count if isinstance(count, int) else len(messages)
        except Exception as e:
            logger.warning("BRIDGE: append_to_inbox failed: %s", e)
            self._errors += 1
            return 0

    # Max outbound events queued before oldest are dropped.
    # Matches NADI_BUFFER_SIZE from federation_transport.py.
    _MAX_OUTBOUND = 144

    def emit(self, operation: str, payload: dict) -> None:
        """Queue an outbound event for federation broadcast."""
        self._outbound.append(
            BridgeEvent(
                operation=operation,
                agent_id=self.agent_id,
                payload=payload,
                timestamp=time.time(),
            )
        )
        # Cap queue — drop oldest if over limit
        if len(self._outbound) > self._MAX_OUTBOUND:
            self._outbound = self._outbound[-self._MAX_OUTBOUND :]

    def stats(self) -> dict:
        return {
            "inbound_processed": self._inbound_count,
            "outbound_published": self._outbound_count,
            "outbound_pending": len(self._outbound),
            "errors": self._errors,
            "delegations_rejected": self._delegations_rejected,
        }

    # ── Private Handlers ──────────────────────────────────────────

    def _handle_heartbeat(self, payload: dict) -> bool:
        if self.reaper is None:
            return False
        agent_id = payload.get("agent_id")
        if not agent_id:
            return False
        ts = payload.get("timestamp")
        source = payload.get("source", "federation")
        capabilities = payload.get("capabilities")
        fingerprint = payload.get("fingerprint", "")
        caps = tuple(capabilities) if isinstance(capabilities, list) else ()
        self.reaper.record_heartbeat(
            agent_id,
            timestamp=ts,
            source=source,
            capabilities=caps,
            fingerprint=fingerprint,
        )
        return True

    def _handle_claim(self, payload: dict) -> bool:
        if self.marketplace is None:
            return False
        slot_id = payload.get("slot_id")
        agent_id = payload.get("agent_id")
        if not slot_id or not agent_id:
            return False
        trust = payload.get("trust", 0.0)
        outcome = self.marketplace.claim(slot_id, agent_id, trust=trust)
        # Emit outcome for federation peers to observe
        self.emit(
            OP_CLAIM_OUTCOME,
            {
                "slot_id": slot_id,
                "agent_id": agent_id,
                "granted": getattr(outcome, "granted", False),
                "holder": getattr(outcome, "holder", ""),
                "reason": getattr(outcome, "reason", ""),
            },
        )
        return True

    def _handle_release(self, payload: dict) -> bool:
        if self.marketplace is None:
            return False
        slot_id = payload.get("slot_id")
        agent_id = payload.get("agent_id")
        if not slot_id or not agent_id:
            return False
        self.marketplace.release(slot_id, agent_id)
        return True

    def _handle_delegate_task(self, payload: dict) -> bool:
        """Inbound task delegation from a peer agent.

        Trust-gated: rejects delegations from peers below trust floor.
        Pushes the task into the local TaskManager queue. KARMA phase
        will pick it up and dispatch it like any other autonomous task.

        Payload:
            title: str — task title (should include [INTENT] prefix)
            priority: int — 0-100
            source_agent: str — who delegated
            repo: str — target repo URL (optional, for cross-repo work)
        """
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            logger.warning("BRIDGE: delegate_task but no TaskManager registered")
            return False

        title = payload.get("title")
        if not title:
            return False

        source = payload.get("source_agent", "unknown")
        priority = payload.get("priority", 50)
        repo = payload.get("repo", "")

        # Trust gate: reject delegations from untrusted peers
        if self.reaper is not None and source != "unknown":
            peer = self.reaper.get_peer(source) if hasattr(self.reaper, "get_peer") else None
            if peer is not None and peer.trust < self.delegation_trust_floor:
                self._delegations_rejected += 1
                logger.warning(
                    "BRIDGE: delegation REJECTED from %s (trust=%.2f < floor=%.2f): '%s'",
                    source,
                    peer.trust,
                    self.delegation_trust_floor,
                    title,
                )
                return False

        # Prefix with source for traceability
        full_title = f"[FED:{source}] {title}"
        description = f"repo:{repo}" if repo else ""
        task_mgr.add_task(title=full_title, priority=priority, description=description)
        logger.info(
            "BRIDGE: delegated task from %s → '%s' (priority=%d)",
            source,
            title,
            priority,
        )
        return True

    def _handle_pr_review_request(self, payload: dict) -> bool:
        """Inbound PR review request from a federation peer.

        Runs diagnostic pipeline, registers KirtanLoop call, emits verdict.

        Payload:
            repo: str — repository (e.g. "kimeisele/agent-city")
            pr_number: int — pull request number
            author: str — PR author
            files: list[str] — files changed
            description: str — PR description
            source_agent: str — who sent the request
        """
        from steward.pr_gate import diagnose_pr
        from steward.services import SVC_KIRTAN

        repo = payload.get("repo", "")
        pr_number = payload.get("pr_number")
        if not repo or not pr_number:
            logger.warning("BRIDGE: pr_review_request missing repo or pr_number")
            return False

        source_agent = payload.get("source_agent", "unknown")
        logger.info(
            "BRIDGE: pr_review_request from %s for %s#%s",
            source_agent,
            repo,
            pr_number,
        )

        # 1. KirtanLoop — track that we expect verdict to be enacted
        kirtan = None
        try:
            kirtan = __import__("vibe_core.di", fromlist=["ServiceRegistry"]).ServiceRegistry.get(SVC_KIRTAN)
        except Exception:
            pass
        if kirtan is not None:
            kirtan.call(
                f"pr_review:{repo}:{pr_number}",
                target=repo,
                expected_outcome="verdict_sent",
            )

        # 2. Diagnostic pipeline
        diagnostics = diagnose_pr(
            repo=repo,
            pr_number=pr_number,
            author=payload.get("author", ""),
            files=payload.get("files", []),
            reaper=self.reaper,
        )

        # 3. Derive verdict
        verdict = "approve"
        reasons = []

        if diagnostics.get("ci_failing"):
            verdict = "request_changes"
            reasons.append("CI is failing")
        if diagnostics.get("has_core_files"):
            if verdict == "approve":
                verdict = "approve"  # still approve, but flag for council
            reasons.append("core files modified — council vote required")
        if not diagnostics.get("author_is_peer"):
            verdict = "request_changes"
            reasons.append(f"author '{payload.get('author', '')}' not in federation peer registry")
        if diagnostics.get("blast_radius", 0) > 20:
            if verdict == "approve":
                verdict = "request_changes"
            reasons.append(f"high blast radius ({diagnostics['blast_radius']} files)")

        reason = "; ".join(reasons) if reasons else "all checks passed"

        # 4. Emit verdict
        self.emit(
            OP_PR_REVIEW_VERDICT,
            {
                "pr_number": pr_number,
                "repo": repo,
                "verdict": verdict,
                "reason": reason,
                "diagnostics": diagnostics,
                "source_agent": self.agent_id,
            },
        )

        # 5. Close KirtanLoop — verdict sent
        if kirtan is not None:
            kirtan.close(f"pr_review:{repo}:{pr_number}", success=True)

        logger.info(
            "BRIDGE: pr_review_verdict for %s#%s: %s (%s)",
            repo,
            pr_number,
            verdict,
            reason,
        )
        return True

    def _handle_city_report(self, payload: dict) -> bool:
        """Inbound city_report from agent-city (MOKSHA federation report).

        Verified from kimeisele/agent-city city/hooks/moksha/outbound.py:
            FederationReportHook emits operation="city_report" with payload:
                heartbeat: int
                population: int
                alive: int
                chain_valid: bool
                pr_results: list[dict]
                mission_results: list[dict]  — {id, name, status, owner}
                active_campaigns: list[dict]

        Bottleneck missions have name="Brain bottleneck: {target}"
        (from city/missions.py create_brain_mission with verb="bottleneck").

        This handler:
        1. Records heartbeat as liveness signal for the reaper
        2. Extracts "Brain bottleneck:" missions → delegate_task to TaskManager
        """
        source_agent = payload.get("source_agent", "agent-city")

        # Liveness: the report itself is proof the peer is alive
        if self.reaper is not None:
            self.reaper.record_heartbeat(
                source_agent,
                timestamp=time.time(),
                source="city_report",
            )

        mission_results = payload.get("mission_results", [])
        if not isinstance(mission_results, list):
            return True  # Valid report, just no missions

        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            return True  # Report accepted, but no task manager to act on bottlenecks

        from vibe_core.task_types import TaskStatus

        delegated = 0
        for mission in mission_results:
            if not isinstance(mission, dict):
                continue
            name = mission.get("name", "")

            # Only act on bottleneck missions — exact prefix from agent-city source
            if not name.startswith(CITY_BOTTLENECK_PREFIX):
                continue

            target = name[len(CITY_BOTTLENECK_PREFIX) :].strip()
            if not target:
                continue

            target_repo = str(mission.get("target_repo", source_agent)).strip() or source_agent
            dedup_key = _bottleneck_dedup_key(
                {
                    "issue_key": mission.get("issue_key", ""),
                    "target_repo": target_repo,
                    "contract_name": mission.get("contract_name", ""),
                    "target": target,
                },
                source_agent=source_agent,
                fallback_target=target,
            )

            # Dedup: skip if an active task with same target already exists
            active = task_mgr.list_tasks(status=TaskStatus.IN_PROGRESS) + task_mgr.list_tasks(status=TaskStatus.PENDING)
            if any(_task_has_dedup_key(t, dedup_key) for t in active):
                logger.info("BRIDGE: city_report bottleneck dedup — '%s' already active", dedup_key)
                continue

            # Delegate as a standard federated task — KARMA phase will dispatch
            title = f"[FED:{source_agent}] Fix bottleneck: {target}"
            description_lines = [
                f"city_report:{mission.get('id', '')}",
                f"dedup_key:{dedup_key}",
            ]
            if "/" in target_repo:
                description_lines.insert(0, f"target_repo:{target_repo}")
            task_mgr.add_task(title=title, priority=70, description="\n".join(description_lines))
            delegated += 1
            logger.info("BRIDGE: city_report bottleneck → task '%s'", title)

        if delegated:
            logger.info("BRIDGE: city_report from %s — created %d bottleneck tasks", source_agent, delegated)

        # Store latest report for other components to query
        if source_agent:
            _latest_city_reports[source_agent] = payload

        return True

    def _handle_world_state_update(self, payload: dict) -> bool:
        """Inbound world state from agent-world.

        Refreshes peer liveness for any agents mentioned in the world state
        and stores the latest state for other components to query.

        Payload:
            version: int — world state version number
            timestamp: float — when the state was generated
            cities: dict — city agent states (keyed by agent_id)
            agents: dict — all agent states (optional, keyed by agent_id)
        """
        global _latest_world_state

        version = payload.get("version", 0)
        ts = payload.get("timestamp", 0)
        logger.info(
            "BRIDGE: world_state_update v%s (ts=%.0f)",
            version,
            ts,
        )

        _latest_world_state = payload

        # Refresh reaper liveness for known peers mentioned in the world state
        if self.reaper is not None:
            # cities/agents may be lists of dicts or dicts — normalize to {id: data}
            agents: dict = {}
            for collection in (payload.get("cities", []), payload.get("agents", [])):
                if isinstance(collection, dict):
                    agents.update(collection)
                elif isinstance(collection, list):
                    for item in collection:
                        if isinstance(item, dict):
                            aid = item.get("agent_id", item.get("node_id", ""))
                            if aid:
                                agents[aid] = item
            for agent_id, agent_data in agents.items():
                if agent_id == self.agent_id:
                    continue
                peer = self.reaper.get_peer(agent_id)
                if peer is not None:
                    # Known peer — refresh heartbeat from world authority
                    self.reaper.record_heartbeat(
                        agent_id,
                        timestamp=ts or None,
                        source="world_state",
                    )

        return True

    def _handle_policy_update(self, payload: dict) -> bool:
        """Inbound policy update from agent-world.

        Stores policies for governance compliance checks by other components.

        Payload:
            policies: list[dict] — active policy definitions
            version: int — policy version
            timestamp: float — when policies were issued
            issuer: str — who issued (usually agent-world)
        """
        global _latest_policies

        version = payload.get("version", 0)
        issuer = payload.get("issuer", "unknown")
        policies = payload.get("policies", [])
        logger.info(
            "BRIDGE: policy_update v%s from %s (%d policies)",
            version,
            issuer,
            len(policies),
        )

        _latest_policies = payload

        return True

    def _handle_bottleneck_escalation(self, payload: dict) -> bool:
        """Inbound bottleneck_escalation from agent-city.

        Agent-city's scope gate rejects code-fix missions (ruff, tests, etc.)
        and escalates them to steward via NADI. This handler creates a task
        for the AutonomyEngine to dispatch in KARMA phase.

        Payload (from agent-city brain_health.py _escalate_bottleneck_to_steward):
            target: str — what needs fixing (e.g. "ruff_clean contract / tests_pass failing")
            source: str — origin within agent-city (brain_health | brain_critique)
            evidence: str — why this was escalated
            requested_action: str — "fix"
            heartbeat: int — agent-city's heartbeat count when escalated
        """
        target = payload.get("target", "unknown")
        source = payload.get("source", "unknown")
        heartbeat = payload.get("heartbeat", "?")
        evidence = payload.get("evidence", "")
        dedup_key = _bottleneck_dedup_key(payload, fallback_target=target)
        target_repo = str(payload.get("target_repo", "")).strip()

        logger.info(
            "BRIDGE: bottleneck_escalation from agent-city (hb=%s, source=%s): %s",
            heartbeat,
            source,
            target[:80],
        )

        # Liveness: escalation is proof agent-city is alive
        if self.reaper is not None:
            self.reaper.record_heartbeat(
                "agent-city",
                timestamp=time.time(),
                source="bottleneck_escalation",
            )

        # Create task for KARMA phase dispatch
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            logger.warning("BRIDGE: bottleneck_escalation — no TaskManager to create task")
            return True

        from vibe_core.task_types import TaskStatus

        # Dedup: skip if active task already exists for this target
        active = task_mgr.list_tasks(status=TaskStatus.IN_PROGRESS) + task_mgr.list_tasks(status=TaskStatus.PENDING)
        if any(_task_has_dedup_key(t, dedup_key) for t in active):
            logger.info("BRIDGE: bottleneck_escalation dedup — '%s' already active", dedup_key)
            return True

        title = f"[BOTTLENECK_ESCALATION] {target[:80]}"
        description_lines = [
            f"Escalated from agent-city (hb={heartbeat}, source={source}): {evidence}",
            f"dedup_key:{dedup_key}",
        ]
        if "/" in target_repo:
            description_lines.append(f"target_repo:{target_repo}")
        description = "\n".join(description_lines)
        task_mgr.add_task(title=title, priority=70, description=description)
        logger.info("BRIDGE: bottleneck_escalation → task '%s'", title)

        return True

    def _handle_compliance_report(self, payload: dict) -> bool:
        """Inbound compliance report from agent-world Legislator.

        Updates reaper trust based on compliance status.
        Compliant nodes get a trust bonus (+0.05, capped at 1.0).
        Non-compliant nodes get a trust penalty (-0.1 per violation).

        Payload:
            node_id: str — the peer being evaluated
            compliant: bool — whether the node is compliant
            violations: list[str] — policy IDs violated
            trust_score: float — Legislator-computed trust score
            compliance_ratio: float — federation-wide compliance ratio
            issuer: str — who issued (legislator)
        """
        node_id = payload.get("node_id", "")
        compliant = payload.get("compliant", True)
        violations = payload.get("violations", [])

        if not node_id:
            return True

        logger.info(
            "BRIDGE: compliance_report for %s: compliant=%s violations=%s",
            node_id,
            compliant,
            violations,
        )

        # Update reaper trust directly on PeerRecord
        if self.reaper is not None:
            peer = self.reaper.get_peer(node_id)
            if peer is not None:
                old_trust = peer.trust
                if compliant:
                    # Trust bonus for compliance (+0.05, capped at 1.0)
                    peer.trust = min(1.0, peer.trust + 0.05)
                else:
                    # Trust penalty per violation (-0.1 each)
                    penalty = len(violations) * 0.1
                    peer.trust = max(0.0, peer.trust - penalty)
                logger.info(
                    "BRIDGE: trust update for %s: %.2f → %.2f (%s)",
                    node_id,
                    old_trust,
                    peer.trust,
                    "compliant" if compliant else f"{len(violations)} violations",
                )

        return True

    def _handle_node_health(self, payload: dict) -> bool:
        node_id = str(payload.get("node_id", "")).strip()
        protocol_version = str(payload.get("protocol_version", "")).strip()
        status = str(payload.get("status", "")).strip()
        timestamp = payload.get("timestamp", 0.0)
        quarantine_metrics = payload.get("quarantine_metrics", {})

        if not node_id or not protocol_version or not status:
            return False
        if not isinstance(quarantine_metrics, dict):
            return False

        registry = self._load_peer_registry()
        registry[node_id] = {
            "node_id": node_id,
            "protocol_version": protocol_version,
            "status": status,
            "timestamp": timestamp,
            "quarantine_metrics": quarantine_metrics,
            "updated_at": time.time(),
        }
        self._save_peer_registry(registry)
        logger.info(
            "BRIDGE: node_health upsert node_id=%s status=%s protocol=%s",
            node_id,
            status,
            protocol_version,
        )
        return True

    def _handle_agent_claim(self, payload: dict) -> bool:
        """Upsert a federation node into verified_agents.json.

        Defence-in-depth: the gateway already enforces
        derive_node_id(public_key) == node_id at the boundary, but we re-check
        here so the registry can never grow an inconsistent entry through a
        different code path (test fixtures, manual ingest, future inputs).

        Idempotency: if the existing entry is semantically identical (same
        public_key, agent_name, capabilities), updated_at is preserved and the
        save short-circuits — no spurious commits in steward's heartbeat repo.
        """
        agent_name = str(payload.get("agent_name", "")).strip()
        public_key = str(payload.get("public_key", "")).strip()
        node_id = str(payload.get("node_id", "")).strip()
        capabilities = payload.get("capabilities", [])

        if not agent_name or not public_key or not node_id:
            return False
        if not isinstance(capabilities, list):
            return False
        if derive_node_id(public_key) != node_id:
            logger.warning(
                "BRIDGE: agent_claim REJECTED — node_id %s does not derive from public_key %s",
                node_id, public_key[:16],
            )
            return False

        normalized_caps = sorted({str(item) for item in capabilities})
        registry = self._load_verified_agents()
        existing = registry.get(node_id) if isinstance(registry.get(node_id), dict) else None
        existing_caps = (
            sorted({str(item) for item in existing.get("capabilities", [])})
            if existing else None
        )
        unchanged = (
            existing is not None
            and existing.get("public_key") == public_key
            and existing.get("agent_name") == agent_name
            and existing_caps == normalized_caps
        )
        if unchanged:
            logger.info(
                "BRIDGE: agent_claim identical — node_id=%s skipped (no registry write)",
                node_id,
            )
            return True

        registry[node_id] = {
            "node_id": node_id,
            "agent_name": agent_name,
            "public_key": public_key,
            "capabilities": normalized_caps,
            "updated_at": time.time(),
        }
        self._save_verified_agents(registry)
        logger.info(
            "BRIDGE: agent_claim upsert node_id=%s capabilities=%d",
            node_id,
            len(normalized_caps),
        )
        return True

    def _handle_governance_bounty(self, payload: dict) -> bool:
        """Inbound governance bounty from agent-world Legislator.

        Violations become economic incentives: the Legislator emits a bounty
        for each policy violation, and steward creates a task for AutonomyEngine
        to dispatch in KARMA phase.

        Payload:
            target: str — bounty target (e.g. "fix:federation_ci_required:agent-internet")
            severity: str — "low", "medium", "high"
            reward: int — prana reward (108 = MALA for high severity)
            description: str — human-readable description
            issuer: str — who issued (legislator)
        """
        target = payload.get("target", "")
        severity = payload.get("severity", "medium")
        reward = payload.get("reward", 0)
        description = payload.get("description", "")
        violation_id = str(payload.get("violation_id", "")).strip()
        policy_name = str(payload.get("policy_name", "")).strip()
        target_repo = str(payload.get("target_repo", "")).strip()

        if not target:
            return True

        dedup_key = _governance_dedup_key(payload)
        if not policy_name:
            policy_name = _normalize_governance_policy(target)

        logger.info(
            "BRIDGE: governance_bounty target='%s' severity=%s reward=%d",
            target[:80],
            severity,
            reward,
        )

        # Create task for KARMA phase dispatch
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            logger.warning("BRIDGE: governance_bounty — no TaskManager to create task")
            return True

        from vibe_core.task_types import TaskStatus

        # Dedup: skip if active task already exists for this target
        active = task_mgr.list_tasks(status=TaskStatus.IN_PROGRESS) + task_mgr.list_tasks(status=TaskStatus.PENDING)
        if any(_task_has_dedup_key(t, dedup_key) for t in active):
            logger.info("BRIDGE: governance_bounty dedup — '%s' already active", dedup_key)
            return True

        title = f"[GOV_BOUNTY] {target[:80]}"
        task_desc_lines = [
            f"governance_bounty: {description} (severity={severity}, reward={reward})",
            f"dedup_key:{dedup_key}",
        ]
        if violation_id:
            task_desc_lines.append(f"violation_id:{violation_id}")
        if policy_name:
            task_desc_lines.append(f"policy_name:{policy_name}")
        if "/" in target_repo:
            task_desc_lines.append(f"target_repo:{target_repo}")
        task_desc = "\n".join(task_desc_lines)
        task_mgr.add_task(title=title, priority=75, description=task_desc)
        logger.info("BRIDGE: governance_bounty → task '%s'", title)

        return True

    def _handle_task_callback(self, payload: dict) -> bool:
        """Inbound task completion/failure callback from a peer.

        When we delegated a task to a peer, this is their response.
        Wakes up BLOCKED tasks in TaskManager that match the callback.

        Payload:
            task_title: str — the original task title we delegated
            source_agent: str — who completed it (should match target_agent)
            pr_url: str — PR link if applicable (task_completed only)
            error: str — error message (task_failed only)
        """
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        if task_mgr is None:
            return False

        task_title = payload.get("task_title", "")
        source_agent = payload.get("source_agent", "unknown")
        pr_url = payload.get("pr_url", "")
        error = payload.get("error", "")

        if not task_title:
            return False

        from vibe_core.task_types import TaskStatus

        # Find BLOCKED tasks that match this callback
        blocked = task_mgr.list_tasks(status=TaskStatus.BLOCKED)
        matched = None
        for task in blocked:
            desc = getattr(task, "description", "") or ""
            # Match by delegated task title stored in description
            if f"delegated:{task_title}" in desc:
                matched = task
                break

        if matched is None:
            logger.debug(
                "BRIDGE: callback for '%s' from %s — no matching BLOCKED task",
                task_title,
                source_agent,
            )
            return False

        # Resume the task: BLOCKED → PENDING with result context
        result_context = f"peer_result:{pr_url}" if pr_url else f"peer_error:{error}" if error else "peer_result:done"
        task_mgr.update_task(
            matched.id,
            status=TaskStatus.PENDING,
            description=result_context,
        )
        logger.info(
            "BRIDGE: callback from %s resumed task '%s' (result=%s)",
            source_agent,
            matched.title,
            result_context[:80],
        )
        return True
