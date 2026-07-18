"""Independent SFDJ-1 reference helpers for Golden Wire Fixtures 01.

Test-only module. Runtime federation code is deliberately not imported.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import unicodedata
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DOMAIN_DELEGATION = "STEWARD-FEDERATION-DELEGATION-V1"
DOMAIN_ROOT_ENROLLMENT = "STEWARD-FEDERATION-ROOT-ENROLLMENT-V1"
DOMAIN_SIGNING_KEY_AUTH = "STEWARD-FEDERATION-SIGNING-KEY-AUTH-V1"
NODE_RE = re.compile(r"^ag_[0-9a-f]{32}$")
KEY_RE = re.compile(r"^key_[0-9a-f]{64}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
TIME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")


class SFDJReject(ValueError):
    """Machine-readable SFDJ-1 rejection."""


def _string_json(value: str) -> str:
    if unicodedata.normalize("NFC", value) != value:
        raise SFDJReject("rejected_noncanonical")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SFDJReject("invalid_unicode") from exc
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return (
        encoded.replace("\\b", "\\u0008")
        .replace("\\t", "\\u0009")
        .replace("\\n", "\\u000a")
        .replace("\\f", "\\u000c")
        .replace("\\r", "\\u000d")
    )


def _canonical(value: Any, depth: int = 0) -> str:
    if depth > 16:
        raise SFDJReject("max_depth")
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if not -(2**63) <= value <= 2**63 - 1:
            raise SFDJReject("integer_range")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SFDJReject("float_forbidden")
        raise SFDJReject("float_forbidden")
    if isinstance(value, str):
        return _string_json(value)
    if isinstance(value, list):
        if len(value) > 1024:
            raise SFDJReject("array_limit")
        return "[" + ",".join(_canonical(item, depth + 1) for item in value) + "]"
    if isinstance(value, dict):
        if len(value) > 1024:
            raise SFDJReject("object_limit")
        keys = []
        for key in value:
            if not isinstance(key, str):
                raise SFDJReject("object_key_type")
            if unicodedata.normalize("NFC", key) != key:
                raise SFDJReject("rejected_noncanonical")
            if len(key.encode("utf-8")) > 256:
                raise SFDJReject("object_key_limit")
            keys.append(key)
        keys.sort(key=lambda item: item.encode("utf-8"))
        members = ",".join(_string_json(key) + ":" + _canonical(value[key], depth + 1) for key in keys)
        return "{" + members + "}"
    raise SFDJReject("unsupported_type")


def canonical_bytes(value: Any) -> bytes:
    encoded = _canonical(value)
    if len(encoded.encode("utf-8")) > 256 * 1024:
        raise SFDJReject("envelope_limit")
    return encoded.encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SFDJReject("duplicate_json_key")
        result[key] = value
    return result


def parse_canonical(raw: bytes) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SFDJReject("bom_forbidden")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SFDJReject("invalid_utf8") from exc
    value = json.loads(
        text,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda _: (_ for _ in ()).throw(SFDJReject("float_forbidden")),
    )
    canonical = canonical_bytes(value)
    if canonical != raw:
        raise SFDJReject("rejected_noncanonical")
    if not isinstance(value, dict):
        raise SFDJReject("envelope_object_required")
    return value


def digest_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def derive_node_id(identity_root_public_key: bytes) -> str:
    return "ag_" + hashlib.sha256(identity_root_public_key.hex().encode("ascii")).hexdigest()[:32]


def derive_key_id(signing_public_key: bytes) -> str:
    return "key_" + hashlib.sha256(signing_public_key).hexdigest()


def sign_digest(private_key: Ed25519PrivateKey, domain: str, digest: str) -> str:
    signature_input = domain.encode("utf-8") + b"\x00" + bytes.fromhex(digest)
    return base64.b64encode(private_key.sign(signature_input)).decode("ascii")


def verify_digest(public_key: bytes, domain: str, digest: str, signature: str) -> bool:
    try:
        raw_sig = base64.b64decode(signature, validate=True)
        if len(raw_sig) != 64:
            return False
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            raw_sig, domain.encode("utf-8") + b"\x00" + bytes.fromhex(digest)
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def request_digest(payload: dict[str, Any], source_node_id: str, target_node_id: str) -> str:
    semantic_payload = {
        key: payload[key]
        for key in (
            "delegation_id",
            "origin_task_id",
            "capability",
            "intent",
            "task_description",
            "target_repo",
            "authority",
            "expected_outcome",
            "verification_contract",
            "deadline",
        )
    }
    semantic = {
        "contract_version": "federation-delegation-v1",
        "operation": "delegate_task",
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "payload": semantic_payload,
    }
    return digest_hex(canonical_bytes(semantic))


def message_hash(envelope_without_hash_signature: dict[str, Any]) -> str:
    return digest_hex(canonical_bytes(envelope_without_hash_signature))


def build_envelope(
    *,
    payload: dict[str, Any],
    source_node_id: str,
    target_node_id: str,
    message_id: str,
    request_message_id: str,
    signing_key: Ed25519PrivateKey,
    signer_key_b64: str,
    key_id: str,
    issued_at: str,
    expires_at: str,
    causation_message_id: str | None = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "contract_version": "federation-delegation-v1",
        "message_id": message_id,
        "request_message_id": request_message_id,
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "operation": "delegate_task",
        "correlation_id": payload["delegation_id"],
        "payload": payload,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "signer_key": signer_key_b64,
        "key_id": key_id,
    }
    if causation_message_id is not None:
        envelope["causation_message_id"] = causation_message_id
    digest = message_hash(envelope)
    return {
        **envelope,
        "message_hash": digest,
        "signature": sign_digest(signing_key, DOMAIN_DELEGATION, digest),
    }


def assert_shape(envelope: dict[str, Any]) -> None:
    required = {
        "contract_version",
        "message_id",
        "request_message_id",
        "source_node_id",
        "target_node_id",
        "operation",
        "correlation_id",
        "payload",
        "issued_at",
        "expires_at",
        "message_hash",
        "signature",
        "signer_key",
        "key_id",
    }
    if set(envelope) not in (required, required | {"causation_message_id"}):
        raise AssertionError("top_level_schema")
    if envelope["contract_version"] != "federation-delegation-v1":
        raise AssertionError("contract_version")
    if not NODE_RE.fullmatch(envelope["source_node_id"]):
        raise AssertionError("source_node_id")
    if not NODE_RE.fullmatch(envelope["target_node_id"]):
        raise AssertionError("target_node_id")
    if not ID_RE.fullmatch(envelope["message_id"]):
        raise AssertionError("message_id")
    if not ID_RE.fullmatch(envelope["request_message_id"]):
        raise AssertionError("request_message_id")
    if envelope.get("causation_message_id") is None and envelope["message_id"] != envelope["request_message_id"]:
        raise AssertionError("request_root")
    if not TIME_RE.fullmatch(envelope["issued_at"]) or not TIME_RE.fullmatch(envelope["expires_at"]):
        raise AssertionError("timestamp")
    if not HASH_RE.fullmatch(envelope["message_hash"]):
        raise AssertionError("message_hash")
    if not KEY_RE.fullmatch(envelope["key_id"]):
        raise AssertionError("key_id")
    raw_key = base64.b64decode(envelope["signer_key"], validate=True)
    raw_signature = base64.b64decode(envelope["signature"], validate=True)
    if len(raw_key) != 32 or len(raw_signature) != 64:
        raise AssertionError("key_encoding")
    payload = envelope["payload"]
    required_payload = {
        "delegation_id",
        "origin_task_id",
        "capability",
        "intent",
        "task_description",
        "target_repo",
        "authority",
        "expected_outcome",
        "verification_contract",
        "deadline",
        "request_digest",
        "idempotency_key",
    }
    if set(payload) - required_payload - {"display_title", "display_description"}:
        raise AssertionError("payload_unknown")
    if not required_payload <= set(payload):
        raise AssertionError("payload_required")
    if payload["capability"] != "fix_repository":
        raise AssertionError("capability")
    if payload["intent"] != {"kind": "repair", "version": "v1"}:
        raise AssertionError("intent")
    if payload["expected_outcome"] != {"kind": "verified_tests_and_observation"}:
        raise AssertionError("expected_outcome")
    if payload["verification_contract"] != {
        "postcondition_kind": "tests_and_runtime_observation",
        "required_evidence": ["runtime_observation", "test_result"],
    }:
        raise AssertionError("verification_contract")
    if not HASH_RE.fullmatch(payload["request_digest"]):
        raise AssertionError("request_digest")
    if payload["idempotency_key"] != "fedv1:" + payload["request_digest"]:
        raise AssertionError("idempotency_key")
