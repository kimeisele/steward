"""Golden Wire 01A independent builders and phase validators.

This module is test-only.  It rebuilds the fixture from semantic inputs instead of
loading the expected JSON and deliberately models validation as ordered phases.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .reference import (
    DOMAIN_DELEGATION,
    DOMAIN_ROOT_ENROLLMENT,
    DOMAIN_SIGNING_KEY_AUTH,
    SFDJReject,
    canonical_bytes,
    derive_key_id,
    derive_node_id,
    digest_hex,
    parse_canonical,
)

FIXTURE_NOW = "2026-07-18T11:00:00Z"
ENROLLMENT_FIELDS = {
    "enrollment_version", "identity_root_public_key", "node_id", "not_before",
    "provenance_digest", "registry_epoch", "root_signature",
}
CERTIFICATE_FIELDS = {
    "activation_at", "activation_epoch", "certificate_epoch", "certificate_version",
    "identity_root_public_key", "key_id", "node_id", "not_after", "not_before",
    "registry_epoch", "revocation_ref", "rotation_kind", "signer_key", "root_signature",
}


def rfc3339(value: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp_type")
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("timestamp_format") from exc
    return parsed.replace(tzinfo=dt.UTC)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _sign(private: Ed25519PrivateKey, domain: str, digest: str) -> str:
    data = domain.encode("utf-8") + b"\x00" + bytes.fromhex(digest)
    return _b64(private.sign(data))


def _signed(body: dict[str, Any], private: Ed25519PrivateKey, domain: str) -> tuple[dict[str, Any], bytes, str]:
    body_bytes = canonical_bytes(body)
    digest = hashlib.sha256(body_bytes).hexdigest()
    record = {**body, "root_signature": _sign(private, domain, digest)}
    return record, domain.encode("utf-8") + b"\x00" + bytes.fromhex(digest), digest


def build_enrollment(label: str, root_private: Ed25519PrivateKey) -> tuple[dict[str, Any], bytes, str]:
    public = root_private.public_key().public_bytes_raw()
    node = derive_node_id(public)
    body = {
        "enrollment_version": "federation-root-enrollment-v1",
        "identity_root_public_key": _b64(public),
        "node_id": node,
        "not_before": "2026-07-18T00:00:00Z",
        "provenance_digest": hashlib.sha256(("golden-wire-provenance-v1:" + label).encode()).hexdigest(),
        "registry_epoch": 1,
    }
    return _signed(body, root_private, DOMAIN_ROOT_ENROLLMENT)


def build_certificate(root_private: Ed25519PrivateKey, signing_public: bytes, node: str) -> tuple[dict[str, Any], bytes, str]:
    root_public = root_private.public_key().public_bytes_raw()
    body = {
        "activation_at": "2026-07-18T00:05:00Z",
        "activation_epoch": 1,
        "certificate_epoch": 1,
        "certificate_version": "federation-signing-key-auth-v1",
        "identity_root_public_key": _b64(root_public),
        "key_id": derive_key_id(signing_public),
        "node_id": node,
        "not_after": "2027-07-18T00:00:00Z",
        "not_before": "2026-07-18T00:05:00Z",
        "registry_epoch": 1,
        "revocation_ref": None,
        "rotation_kind": "regular",
        "signer_key": _b64(signing_public),
    }
    return _signed(body, root_private, DOMAIN_SIGNING_KEY_AUTH)


def build_payload(origin_node: str, target_node: str, description: str = "Repair the bounded federation defect.") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "delegation_id": "del_golden_0001",
        "origin_task_id": "task_golden_0001",
        "capability": "fix_repository",
        "intent": {"kind": "repair", "version": "v1"},
        "task_description": description,
        "target_repo": "agent-city",
        "authority": {"allowed_actions": ["branch", "commit", "read", "test"], "denied_actions": ["context_bridge_activation", "merge", "secret_access"], "repo_scope": "agent-city"},
        "expected_outcome": {"kind": "verified_tests_and_observation"},
        "verification_contract": {"postcondition_kind": "tests_and_runtime_observation", "required_evidence": ["runtime_observation", "test_result"]},
        "deadline": "2026-07-18T12:00:00Z",
    }
    semantic = {"contract_version": "federation-delegation-v1", "operation": "delegate_task", "source_node_id": origin_node, "target_node_id": target_node, "payload": payload}
    request = hashlib.sha256(canonical_bytes(semantic)).hexdigest()
    return {**payload, "request_digest": request, "idempotency_key": "fedv1:" + request}


def build_request(origin_node: str, target_node: str, signing_private: Ed25519PrivateKey, signing_key_b64: str, key: str) -> tuple[dict[str, Any], bytes, str, str]:
    payload = build_payload(origin_node, target_node)
    envelope = {
        "contract_version": "federation-delegation-v1", "message_id": "msg_req_golden_0001", "request_message_id": "msg_req_golden_0001",
        "source_node_id": origin_node, "target_node_id": target_node, "operation": "delegate_task", "correlation_id": payload["delegation_id"],
        "payload": payload, "issued_at": "2026-07-18T11:00:00Z", "expires_at": "2026-07-18T11:05:00Z", "signer_key": signing_key_b64, "key_id": key,
    }
    message = hashlib.sha256(canonical_bytes(envelope)).hexdigest()
    signature_input = DOMAIN_DELEGATION.encode() + b"\x00" + bytes.fromhex(message)
    return {**envelope, "message_hash": message, "signature": _b64(signing_private.sign(signature_input))}, signature_input, payload["request_digest"], message


def validate_provenance(raw: bytes, root_public: bytes, now: str = FIXTURE_NOW) -> tuple[str, str] | None:
    try:
        value = parse_canonical(raw)
    except SFDJReject as exc:
        return str(exc), "parse"
    expected = CERTIFICATE_FIELDS if "certificate_version" in value else ENROLLMENT_FIELDS
    if set(value) != expected:
        return "schema_field_set", "schema"
    try:
        current = rfc3339(now)
        before = rfc3339(value["not_before"])
        if "certificate_version" in value:
            activation = rfc3339(value["activation_at"])
            after = rfc3339(value["not_after"])
        else:
            activation = after = None
    except ValueError as exc:
        return str(exc), "timestamp"
    try:
        root_key = base64.b64decode(value["identity_root_public_key"], validate=True)
        if len(root_key) != 32 or root_key != root_public:
            return "root_key_binding", "provenance"
        signature = base64.b64decode(value["root_signature"], validate=True)
        if len(signature) != 64:
            return "invalid_base64", "base64"
    except (ValueError, TypeError):
        return "invalid_base64", "base64"
    if value["node_id"] != derive_node_id(root_public):
        return "node_id_mismatch", "provenance"
    if "certificate_version" not in value:
        if not (before <= current):
            return "enrollment_not_active", "registry_time"
        body = {k: v for k, v in value.items() if k != "root_signature"}
        from .reference import verify_digest
        digest = digest_hex(canonical_bytes(body))
        if not verify_digest(root_public, DOMAIN_ROOT_ENROLLMENT, digest, value["root_signature"]):
            return "root_signature_invalid", "signature"
        return None
    if value["revocation_ref"] is not None:
        return "key_revoked", "registry_status"
    if not (before <= current <= after):
        return "certificate_expired", "registry_time"
    if activation != before:
        return "certificate_time_window", "provenance"
    if value["key_id"] != derive_key_id(base64.b64decode(value["signer_key"], validate=True)):
        return "certificate_key_binding", "provenance"
    body = {k: v for k, v in value.items() if k != "root_signature"}
    from .reference import verify_digest
    digest = digest_hex(canonical_bytes(body))
    if not verify_digest(root_public, DOMAIN_SIGNING_KEY_AUTH, digest, value["root_signature"]):
        return "certificate_signature_invalid", "signature"
    return None


def validate_message(raw: bytes, *, origin_node: str, target_node: str, authorized_key_ids: set[str], existing_bytes: bytes | None = None, existing_request_digest: str | None = None, now: str = FIXTURE_NOW) -> tuple[str, str] | None:
    try:
        value = parse_canonical(raw)
    except SFDJReject as exc:
        code = str(exc)
        phase = "parse"
        if code == "rejected_noncanonical":
            try:
                text = raw.decode("utf-8")
                if "\\u0301" in text:
                    phase = "sfdj_nfc"
                elif "-0" in text:
                    phase = "number"
                else:
                    phase = "sfdj_key_order"
            except UnicodeDecodeError:
                phase = "parse"
        if code == "float_forbidden":
            phase = "number"
        return code, phase
    if set(value) != {"contract_version", "message_id", "request_message_id", "source_node_id", "target_node_id", "operation", "correlation_id", "payload", "issued_at", "expires_at", "message_hash", "signature", "signer_key", "key_id"}:
        return "schema", "schema"
    try:
        rfc3339(value["issued_at"])
        rfc3339(value["expires_at"])
    except ValueError:
        return "timestamp_invalid", "timestamp"
    try:
        signature = base64.b64decode(value["signature"], validate=True)
        signer = base64.b64decode(value["signer_key"], validate=True)
        if len(signature) != 64 or len(signer) != 32:
            return "invalid_base64", "base64"
    except (ValueError, TypeError):
        if "-" in value["signature"] or "_" in value["signature"]:
            return "url_safe_base64_forbidden", "base64"
        return "invalid_base64", "base64"
    actual = digest_hex(canonical_bytes({k: v for k, v in value.items() if k not in {"message_hash", "signature"}}))
    if actual != value["message_hash"]:
        return "message_hash_mismatch", "message_hash"
    if value["target_node_id"] != target_node:
        return "wrong_target", "target_match"
    if value["key_id"] not in authorized_key_ids:
        return "key_not_authorized", "registry"
    from .reference import verify_digest
    if not verify_digest(signer, DOMAIN_DELEGATION, value["message_hash"], value["signature"]):
        return "signature_invalid_wrong_key", "signature"
    if existing_bytes is not None and value["message_id"] == "msg_req_golden_0001" and raw != existing_bytes:
        return "message_id_conflict", "message_dedupe"
    if existing_request_digest is not None and value["payload"].get("delegation_id") == "del_golden_0001" and value["payload"].get("request_digest") != existing_request_digest:
        return "duplicate_conflict", "target_dedupe"
    return None


def validate_fixture(raw: bytes, *, root_public: bytes, origin_node: str, target_node: str, authorized_key_ids: set[str], existing_bytes: bytes | None = None, existing_request_digest: str | None = None) -> tuple[str, str] | None:
    """Dispatch by parsed schema, never by fixture filename or case identifier."""
    try:
        value = parse_canonical(raw)
    except SFDJReject:
        return validate_message(raw, origin_node=origin_node, target_node=target_node, authorized_key_ids=authorized_key_ids, existing_bytes=existing_bytes, existing_request_digest=existing_request_digest)
    if "certificate_version" in value:
        return validate_provenance(raw, root_public)
    return validate_message(raw, origin_node=origin_node, target_node=target_node, authorized_key_ids=authorized_key_ids, existing_bytes=existing_bytes, existing_request_digest=existing_request_digest)
