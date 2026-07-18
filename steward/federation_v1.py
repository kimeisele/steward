"""Production boundary for the first Federation Delegation V1 slice.

This module is intentionally small and additive.  It does not alter the legacy
``OP_DELEGATE_TASK`` path, does not execute work, and does not implement recovery.
"""

from __future__ import annotations

import base64
import contextlib
import datetime as _dt
import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DOMAIN_DELEGATION = "STEWARD-FEDERATION-DELEGATION-V1"
CONTRACT_VERSION = "federation-delegation-v1"
REQUEST_CARRIER_OPERATION = "federation_v1.delegate_task"
RECEIPT_CARRIER_OPERATION = "federation_v1.delegation_receipt"
FEATURE_GATE_ENV = "FEDERATION_V1_DELEGATION_ENABLED"
FEATURE_GATE_DEFAULT = False
MAX_WIRE_BYTES = 256 * 1024
MAX_CARRIER_B64 = 349528
NODE_RE = re.compile(r"^ag_[0-9a-f]{32}$")
KEY_RE = re.compile(r"^key_[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
TIME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
JsonValue = object

REQUEST_KEYS = {
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
RECEIPT_KEYS = REQUEST_KEYS | {"causation_message_id"}
DOMAIN_ROOT_ENROLLMENT = "STEWARD-FEDERATION-ROOT-ENROLLMENT-V1"
DOMAIN_SIGNING_KEY_AUTH = "STEWARD-FEDERATION-SIGNING-KEY-AUTH-V1"
ENROLLMENT_KEYS = {
    "enrollment_version",
    "identity_root_public_key",
    "node_id",
    "not_before",
    "provenance_digest",
    "registry_epoch",
    "root_signature",
}
CERTIFICATE_KEYS = {
    "activation_at",
    "activation_epoch",
    "certificate_epoch",
    "certificate_version",
    "identity_root_public_key",
    "key_id",
    "node_id",
    "not_after",
    "not_before",
    "registry_epoch",
    "revocation_ref",
    "rotation_kind",
    "signer_key",
    "root_signature",
}
_REGISTRY_TOKEN = object()
TARGET_RECORD_KEYS = {
    "delegation_id",
    "request_message_id",
    "request_message_hash",
    "origin_node_id",
    "target_node_id",
    "request_digest",
    "idempotency_key",
    "request_wire_bytes_b64",
    "request_carrier",
    "state",
    "reason_code",
    "target_work_id",
    "receipt_message_id",
    "receipt_id",
    "receipt_content_digest",
    "receipt_message_hash",
    "receipt_signature",
    "receipt_wire_bytes_b64",
    "receipt_send_status",
}
ORIGIN_RECORD_KEYS = {
    "delegation_id",
    "origin_task_id",
    "origin_node_id",
    "request_message_id",
    "correlation_id",
    "target_node_id",
    "request_digest",
    "idempotency_key",
    "request_message_hash",
    "request_wire_bytes_b64",
    "request_carrier",
    "request_send_status",
    "send_state",
    "target_work_id",
}


class V1Reject(ValueError):
    """A fail-closed V1 rejection with a stable machine code and phase."""

    def __init__(self, code: str, phase: str):
        super().__init__(code)
        self.code = code
        self.phase = phase


@dataclass(frozen=True)
class ValidatedFederationV1Key:
    key_id: str
    node_id: str
    public_key: bytes
    not_before: str
    not_after: str
    registry_epoch: int
    certificate_epoch: int
    activation_epoch: int
    revoked: bool = False


class ValidatedFederationV1KeyRegistry:
    """Immutable, provenance-validated key snapshot required by the envelope validator."""

    def __init__(self, records: Mapping[str, ValidatedFederationV1Key], _token: object | None = None):
        if _token is not _REGISTRY_TOKEN:
            raise V1Reject("registry_unvalidated", "registry")
        if (
            not isinstance(records, Mapping)
            or not records
            or not all(
                isinstance(key, str) and isinstance(value, ValidatedFederationV1Key) for key, value in records.items()
            )
        ):
            raise V1Reject("registry_unvalidated", "registry")
        self._records = dict(records)

    @classmethod
    def from_provenance(
        cls,
        enrollments: Iterable[Mapping[str, JsonValue]],
        certificates: Iterable[Mapping[str, JsonValue]],
        *,
        now: str,
    ) -> "ValidatedFederationV1KeyRegistry":
        current = _time(now)
        roots: dict[str, tuple[bytes, Mapping[str, JsonValue]]] = {}
        for enrollment in enrollments:
            if not isinstance(enrollment, Mapping) or set(enrollment) != ENROLLMENT_KEYS:
                raise V1Reject("provenance_schema", "provenance")
            try:
                root = _b64_decode(enrollment["identity_root_public_key"], 32)
                node_id = str(enrollment["node_id"])
                not_before = _time(enrollment["not_before"])
                epoch = enrollment["registry_epoch"]
                provenance_digest = enrollment["provenance_digest"]
                signature = _b64_decode(enrollment["root_signature"], 64)
            except (KeyError, TypeError):
                raise V1Reject("provenance_schema", "provenance")
            if (
                enrollment["enrollment_version"] != "federation-root-enrollment-v1"
                or not NODE_RE.fullmatch(node_id)
                or not isinstance(epoch, int)
                or epoch < 1
                or not HASH_RE.fullmatch(str(provenance_digest))
            ):
                raise V1Reject("provenance_schema", "provenance")
            if not_before > current or node_id != _derive_node_id(root):
                raise V1Reject("node_id_mismatch", "provenance")
            body = {key: value for key, value in enrollment.items() if key != "root_signature"}
            _verify_root_signature(root, DOMAIN_ROOT_ENROLLMENT, body, signature)
            if node_id in roots and roots[node_id][0] != root:
                raise V1Reject("provenance_conflict", "provenance")
            roots[node_id] = (root, enrollment)
        records: dict[str, ValidatedFederationV1Key] = {}
        for certificate in certificates:
            if not isinstance(certificate, Mapping) or set(certificate) != CERTIFICATE_KEYS:
                raise V1Reject("provenance_schema", "provenance")
            try:
                root = _b64_decode(certificate["identity_root_public_key"], 32)
                signer = _b64_decode(certificate["signer_key"], 32)
                signature = _b64_decode(certificate["root_signature"], 64)
                node_id = str(certificate["node_id"])
                key_id = str(certificate["key_id"])
                not_before = _time(certificate["not_before"])
                not_after = _time(certificate["not_after"])
                activation_at = _time(certificate["activation_at"])
                registry_epoch = certificate["registry_epoch"]
                certificate_epoch = certificate["certificate_epoch"]
                activation_epoch = certificate["activation_epoch"]
            except (KeyError, TypeError):
                raise V1Reject("provenance_schema", "provenance")
            root_node = _derive_node_id(root)
            if (
                certificate["certificate_version"] != "federation-signing-key-auth-v1"
                or certificate["rotation_kind"] not in {"regular", "emergency"}
                or node_id != root_node
                or not NODE_RE.fullmatch(node_id)
                or key_id != _derive_key_id(signer)
            ):
                raise V1Reject("certificate_key_binding", "provenance")
            if node_id not in roots or roots[node_id][0] != root:
                raise V1Reject("root_key_binding", "provenance")
            if any(
                not isinstance(epoch, int) or epoch < 1
                for epoch in (registry_epoch, certificate_epoch, activation_epoch)
            ):
                raise V1Reject("provenance_epoch", "provenance")
            if (
                registry_epoch != roots[node_id][1]["registry_epoch"]
                or activation_epoch < certificate_epoch
                or activation_at != not_before
                or not_after <= not_before
            ):
                raise V1Reject("certificate_time_window", "provenance")
            if not (not_before <= current < not_after) or activation_at > current:
                raise V1Reject("certificate_expired", "registry_time")
            body = {key: value for key, value in certificate.items() if key != "root_signature"}
            _verify_root_signature(root, DOMAIN_SIGNING_KEY_AUTH, body, signature)
            if key_id in records:
                raise V1Reject("provenance_conflict", "provenance")
            records[key_id] = ValidatedFederationV1Key(
                key_id=key_id,
                node_id=node_id,
                public_key=signer,
                not_before=certificate["not_before"],
                not_after=certificate["not_after"],
                registry_epoch=registry_epoch,
                certificate_epoch=certificate_epoch,
                activation_epoch=activation_epoch,
                revoked=certificate["revocation_ref"] is not None,
            )
        return cls(records, _REGISTRY_TOKEN)

    def lookup(self, key_id: str, *, at: str) -> ValidatedFederationV1Key:
        record = self._records.get(key_id)
        if record is None:
            raise V1Reject("key_not_authorized", "registry")
        moment = _time(at)
        if record.revoked:
            raise V1Reject("key_revoked", "registry_status")
        if not _time(record.not_before) <= moment < _time(record.not_after):
            raise V1Reject("certificate_expired", "registry_time")
        return record


def _string(value: str) -> str:
    if unicodedata.normalize("NFC", value) != value:
        raise V1Reject("rejected_noncanonical", "sfdj_nfc")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise V1Reject("invalid_unicode", "sfdj_nfc") from exc
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        .replace("\\b", "\\u0008")
        .replace("\\t", "\\u0009")
        .replace("\\n", "\\u000a")
        .replace("\\f", "\\u000c")
        .replace("\\r", "\\u000d")
    )


def _canonical(value: JsonValue, depth: int = 0) -> str:
    if depth > 16:
        raise V1Reject("max_depth", "sfdj_schema")
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int) and not isinstance(value, bool):
        if not -(2**63) <= value <= 2**63 - 1:
            raise V1Reject("integer_range", "sfdj_number")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise V1Reject("float_forbidden", "sfdj_number")
        raise V1Reject("float_forbidden", "sfdj_number")
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        if len(value) > 1024:
            raise V1Reject("array_limit", "sfdj_schema")
        return "[" + ",".join(_canonical(item, depth + 1) for item in value) + "]"
    if isinstance(value, dict):
        if len(value) > 1024:
            raise V1Reject("object_limit", "sfdj_schema")
        keys = []
        for key in value:
            if not isinstance(key, str) or unicodedata.normalize("NFC", key) != key:
                raise V1Reject("rejected_noncanonical", "sfdj_nfc")
            if len(key.encode("utf-8")) > 256:
                raise V1Reject("object_key_limit", "sfdj_schema")
            keys.append(key)
        keys.sort(key=lambda item: item.encode("utf-8"))
        return "{" + ",".join(_string(key) + ":" + _canonical(value[key], depth + 1) for key in keys) + "}"
    raise V1Reject("unsupported_type", "sfdj_schema")


def canonical_bytes(value: JsonValue) -> bytes:
    raw = _canonical(value).encode("utf-8")
    if len(raw) > MAX_WIRE_BYTES:
        raise V1Reject("envelope_limit", "sfdj_size")
    return raw


def _pairs(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise V1Reject("duplicate_json_key", "parse")
        result[key] = value
    return result


def parse_canonical(raw: bytes) -> dict[str, JsonValue]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise V1Reject("bom_forbidden", "parse")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(V1Reject("float_forbidden", "sfdj_number")),
        )
    except V1Reject:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V1Reject("invalid_json", "parse") from exc
    if canonical_bytes(value) != raw:
        raise V1Reject("rejected_noncanonical", "sfdj_key_order")
    if not isinstance(value, dict):
        raise V1Reject("envelope_object_required", "sfdj_schema")
    return value


def _time(value: str) -> _dt.datetime:
    if not TIME_RE.fullmatch(value):
        raise V1Reject("timestamp_invalid", "timestamp")
    try:
        return _dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.UTC)
    except ValueError as exc:
        raise V1Reject("timestamp_invalid", "timestamp") from exc


def _expires_after(value: str, seconds: int = 300) -> str:
    return (_time(value) + _dt.timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _b64_decode(value: object, expected: int, code: str = "invalid_base64") -> bytes:
    if (
        not isinstance(value, str)
        or len(value) % 4
        or "-" in value
        or "_" in value
        or any(ch.isspace() for ch in value)
    ):
        raise V1Reject(code, "base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise V1Reject(code, "base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value or len(decoded) != expected:
        raise V1Reject(code, "base64")
    return decoded


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _digest(value: JsonValue) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _derive_node_id(public_key: bytes) -> str:
    return "ag_" + hashlib.sha256(public_key.hex().encode("ascii")).hexdigest()[:32]


def _derive_key_id(public_key: bytes) -> str:
    return "key_" + hashlib.sha256(public_key).hexdigest()


def _verify_root_signature(public_key: bytes, domain: str, body: Mapping[str, JsonValue], signature: bytes) -> None:
    digest = _digest(body)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, domain.encode("utf-8") + b"\x00" + bytes.fromhex(digest)
        )
    except (InvalidSignature, ValueError) as exc:
        raise V1Reject("provenance_signature_invalid", "signature") from exc


def _signature_input(digest: str) -> bytes:
    return DOMAIN_DELEGATION.encode("utf-8") + b"\x00" + bytes.fromhex(digest)


def request_digest(payload: Mapping[str, JsonValue], source_node_id: str, target_node_id: str) -> str:
    fields = (
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
    semantic = {
        "contract_version": CONTRACT_VERSION,
        "operation": "delegate_task",
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "payload": {field: payload[field] for field in fields},
    }
    return _digest(semantic)


def build_request(
    *,
    payload: Mapping[str, JsonValue],
    source_node_id: str,
    target_node_id: str,
    message_id: str,
    signing_key: Ed25519PrivateKey,
    signer_key_b64: str,
    key_id: str,
    issued_at: str,
    expires_at: str,
) -> bytes:
    body_payload = dict(payload)
    digest = request_digest(body_payload, source_node_id, target_node_id)
    body_payload["request_digest"] = digest
    body_payload["idempotency_key"] = "fedv1:" + digest
    envelope = {
        "contract_version": CONTRACT_VERSION,
        "message_id": message_id,
        "request_message_id": message_id,
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "operation": "delegate_task",
        "correlation_id": body_payload["delegation_id"],
        "payload": body_payload,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "signer_key": signer_key_b64,
        "key_id": key_id,
    }
    digest = _digest(envelope)
    envelope["message_hash"] = digest
    envelope["signature"] = _b64(signing_key.sign(_signature_input(digest)))
    return canonical_bytes(envelope)


def build_admission_receipt(
    *,
    request: Mapping[str, JsonValue],
    target_node_id: str,
    origin_node_id: str,
    message_id: str,
    receipt_id: str,
    target_work_id: str | None,
    status: str,
    reason_code: str | None,
    signing_key: Ed25519PrivateKey,
    signer_key_b64: str,
    key_id: str,
    issued_at: str,
    expires_at: str,
) -> bytes:
    if status not in {"accepted", "rejected"}:
        raise ValueError("unsupported admission status")
    if status == "accepted" and not target_work_id:
        raise ValueError("accepted requires target_work_id")
    if status == "rejected" and target_work_id is not None:
        raise ValueError("rejected forbids target_work_id")
    content = {
        "receipt_id": receipt_id,
        "delegation_id": request["payload"]["delegation_id"],
        "receipt_stage": "admission",
        "issuer_role": "target_node",
        "status": status,
        "target_work_id": target_work_id,
        "reason_code": reason_code,
        "evidence_refs": [],
    }
    content_digest = _digest(content)
    payload = {**content, "receipt_content_digest": content_digest}
    envelope = {
        "contract_version": CONTRACT_VERSION,
        "message_id": message_id,
        "request_message_id": request["request_message_id"],
        "causation_message_id": request["message_id"],
        "source_node_id": target_node_id,
        "target_node_id": origin_node_id,
        "operation": "delegation_receipt",
        "correlation_id": request["correlation_id"],
        "payload": payload,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "signer_key": signer_key_b64,
        "key_id": key_id,
    }
    message = _digest(envelope)
    envelope["message_hash"] = message
    envelope["signature"] = _b64(signing_key.sign(_signature_input(message)))
    return canonical_bytes(envelope)


def _registry_entry(
    registry: ValidatedFederationV1KeyRegistry, key_id: str, *, at: str
) -> tuple[str, bytes, ValidatedFederationV1Key]:
    if not isinstance(registry, ValidatedFederationV1KeyRegistry):
        raise V1Reject("registry_unvalidated", "registry")
    entry = registry.lookup(key_id, at=at)
    return entry.node_id, entry.public_key, entry


def validate_envelope(
    raw: bytes,
    *,
    registry: ValidatedFederationV1KeyRegistry,
    expected_target: str,
    expected_operation: str = "delegate_task",
    now: str | None = None,
) -> dict[str, JsonValue]:
    value = parse_canonical(raw)
    expected_keys = REQUEST_KEYS if expected_operation == "delegate_task" else RECEIPT_KEYS
    if set(value) != expected_keys:
        raise V1Reject("schema_field_set", "schema")
    if value["contract_version"] != CONTRACT_VERSION or value["operation"] != expected_operation:
        raise V1Reject("unsupported_contract", "schema")
    if not NODE_RE.fullmatch(str(value["source_node_id"])) or not NODE_RE.fullmatch(str(value["target_node_id"])):
        raise V1Reject("node_id_invalid", "schema")
    if value["target_node_id"] != expected_target:
        raise V1Reject("wrong_target", "target_match")
    if not ID_RE.fullmatch(str(value["message_id"])) or not ID_RE.fullmatch(str(value["request_message_id"])):
        raise V1Reject("id_invalid", "schema")
    if value["request_message_id"] != value["message_id"] and "causation_message_id" not in value:
        raise V1Reject("request_root_invalid", "schema")
    issued = _time(value["issued_at"])
    expires = _time(value["expires_at"])
    if expires <= issued:
        raise V1Reject("timestamp_window_invalid", "timestamp")
    current = _time(now) if now is not None else _dt.datetime.now(_dt.UTC)
    if not issued <= current < expires:
        raise V1Reject("expired", "registry_time")
    signer = _b64_decode(value["signer_key"], 32)
    signature = _b64_decode(value["signature"], 64)
    if not KEY_RE.fullmatch(str(value["key_id"])):
        raise V1Reject("key_id_invalid", "schema")
    node_id, authorized_public, entry = _registry_entry(registry, value["key_id"], at=value["issued_at"])
    if node_id != value["source_node_id"] or authorized_public != signer:
        raise V1Reject("key_not_authorized", "registry")
    expected_hash = _digest({key: item for key, item in value.items() if key not in {"message_hash", "signature"}})
    if value["message_hash"] != expected_hash:
        raise V1Reject("message_hash_mismatch", "message_hash")
    try:
        Ed25519PublicKey.from_public_bytes(signer).verify(signature, _signature_input(value["message_hash"]))
    except (InvalidSignature, ValueError) as exc:
        raise V1Reject("signature_invalid", "signature") from exc
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise V1Reject("payload_schema", "schema")
    if expected_operation == "delegate_task":
        required = {
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
        if not required <= set(payload) or set(payload) - required - {"display_title", "display_description"}:
            raise V1Reject("payload_schema", "schema")
        try:
            computed_request = request_digest(payload, value["source_node_id"], value["target_node_id"])
        except (KeyError, TypeError):
            raise V1Reject("request_digest_mismatch", "request_digest")
        if payload["request_digest"] != computed_request or payload["idempotency_key"] != "fedv1:" + computed_request:
            raise V1Reject("request_digest_mismatch", "request_digest")
    else:
        receipt_required = {
            "receipt_id",
            "delegation_id",
            "receipt_stage",
            "issuer_role",
            "status",
            "target_work_id",
            "reason_code",
            "evidence_refs",
            "receipt_content_digest",
        }
        if (
            set(payload) != receipt_required
            or payload["receipt_stage"] != "admission"
            or payload["issuer_role"] != "target_node"
        ):
            raise V1Reject("receipt_schema", "schema")
        if payload["status"] == "accepted" and not payload["target_work_id"]:
            raise V1Reject("receipt_schema", "schema")
        if payload["status"] == "rejected" and payload["target_work_id"] is not None:
            raise V1Reject("receipt_schema", "schema")
        content = {key: item for key, item in payload.items() if key != "receipt_content_digest"}
        if payload["receipt_content_digest"] != _digest(content):
            raise V1Reject("receipt_content_digest_mismatch", "receipt_digest")
    return value


def _carrier_operation(inner_operation: str) -> str:
    if inner_operation == "delegate_task":
        return REQUEST_CARRIER_OPERATION
    if inner_operation == "delegation_receipt":
        return RECEIPT_CARRIER_OPERATION
    raise V1Reject("unsupported_contract", "carrier_operation")


def build_carrier(raw: bytes) -> dict[str, JsonValue]:
    inner = parse_canonical(raw)
    operation = _carrier_operation(str(inner["operation"]))
    encoded = _b64(raw)
    if len(encoded) > MAX_CARRIER_B64:
        raise V1Reject("carrier_size", "carrier")
    return {
        "operation": operation,
        "source": inner["source_node_id"],
        "target": inner["target_node_id"],
        "payload": {"wire_version": CONTRACT_VERSION, "wire_bytes_b64": encoded},
    }


def carrier_inner(carrier: Mapping[str, JsonValue], *, expected_target: str) -> tuple[dict[str, JsonValue], bytes]:
    if (
        set(carrier) != {"operation", "source", "target", "payload"}
        or not isinstance(carrier.get("payload"), Mapping)
        or set(carrier["payload"]) != {"wire_version", "wire_bytes_b64"}
    ):
        raise V1Reject("carrier_schema", "carrier")
    if (
        carrier["target"] != expected_target
        or not NODE_RE.fullmatch(str(carrier["source"]))
        or not NODE_RE.fullmatch(str(carrier["target"]))
    ):
        raise V1Reject("wrong_target", "carrier_target")
    if carrier["payload"]["wire_version"] != CONTRACT_VERSION:
        raise V1Reject("unsupported_contract", "carrier_schema")
    encoded = carrier["payload"]["wire_bytes_b64"]
    if not isinstance(encoded, str) or len(encoded) > MAX_CARRIER_B64 or len(encoded) % 4:
        raise V1Reject("invalid_base64", "carrier")
    try:
        expected_length = len(base64.b64decode(encoded, validate=True))
    except (ValueError, TypeError) as exc:
        raise V1Reject("invalid_base64", "carrier") from exc
    raw = _b64_decode(encoded, expected_length)
    inner = parse_canonical(raw)
    if carrier["source"] != inner.get("source_node_id") or carrier["target"] != inner.get("target_node_id"):
        raise V1Reject("carrier_identity_mismatch", "carrier_binding")
    if carrier["operation"] != _carrier_operation(str(inner.get("operation"))):
        raise V1Reject("carrier_operation_mismatch", "carrier_binding")
    return inner, raw


@contextlib.contextmanager
def _process_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".lock").open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _atomic_json(path: Path, data: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_json(path: Path, required_record_keys: set[str]) -> dict[str, JsonValue]:
    if not path.exists():
        return {"delegations": {}, "findings": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V1Reject("ledger_corrupt", "ledger") from exc
    if (
        not isinstance(value, dict)
        or set(value) - {"delegations", "findings"}
        or not isinstance(value.get("delegations"), dict)
    ):
        raise V1Reject("ledger_corrupt", "ledger")
    findings = value.setdefault("findings", [])
    if not isinstance(findings, list):
        raise V1Reject("ledger_corrupt", "ledger")
    for delegation_id, record in value["delegations"].items():
        if (
            not isinstance(delegation_id, str)
            or not isinstance(record, dict)
            or not required_record_keys <= set(record)
            or record.get("delegation_id") != delegation_id
        ):
            raise V1Reject("ledger_corrupt", "ledger")
        if required_record_keys is TARGET_RECORD_KEYS:
            if record.get("state") not in {"ACCEPTED", "REJECTED"} or record.get("receipt_send_status") not in {
                "pending",
                "sent",
            }:
                raise V1Reject("ledger_corrupt", "ledger")
        elif record.get("request_send_status") not in {"created", "sent"} or record.get("send_state") not in {
            "created",
            "sent",
            "admission_received",
            "admission_rejected",
        }:
            raise V1Reject("ledger_corrupt", "ledger")
    if any(not isinstance(item, dict) or not isinstance(item.get("code"), str) for item in findings):
        raise V1Reject("ledger_corrupt", "ledger")
    return value


class TargetAdmissionLedger:
    """Durable target ledger; the single JSON replacement is the admission commit."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def get(self, delegation_id: str) -> dict[str, JsonValue] | None:
        with self._lock, _process_lock(self.path):
            return _load_json(self.path, TARGET_RECORD_KEYS)["delegations"].get(delegation_id)

    def record_finding(self, code: str, delegation_id: str | None = None) -> None:
        with self._lock, _process_lock(self.path):
            document = _load_json(self.path, TARGET_RECORD_KEYS)
            document["findings"].append({"code": code, "delegation_id": delegation_id})
            _atomic_json(self.path, document)

    def commit(
        self,
        *,
        request: Mapping[str, JsonValue],
        request_wire_bytes: bytes,
        request_carrier: Mapping[str, JsonValue],
        receipt: Mapping[str, JsonValue],
        receipt_wire_bytes: bytes,
        state: str,
        reason_code: str | None = None,
    ) -> tuple[str, dict[str, JsonValue]]:
        delegation_id = str(request["payload"]["delegation_id"])
        request_digest_value = str(request["payload"]["request_digest"])
        with self._lock, _process_lock(self.path):
            document = _load_json(self.path, TARGET_RECORD_KEYS)
            existing = document["delegations"].get(delegation_id)
            if existing is not None:
                if existing.get("request_digest") != request_digest_value:
                    return "duplicate_conflict", existing
                if existing.get("request_message_id") == request["message_id"] and existing.get(
                    "request_wire_bytes_b64"
                ) != _b64(request_wire_bytes):
                    return "message_id_conflict", existing
                return "duplicate", existing
            record = {
                "delegation_id": delegation_id,
                "request_message_id": request["request_message_id"],
                "request_message_hash": request["message_hash"],
                "origin_node_id": request["source_node_id"],
                "target_node_id": request["target_node_id"],
                "request_digest": request_digest_value,
                "idempotency_key": request["payload"]["idempotency_key"],
                "request_wire_bytes_b64": _b64(request_wire_bytes),
                "request_carrier": dict(request_carrier),
                "state": state,
                "reason_code": reason_code,
                "target_work_id": receipt["payload"].get("target_work_id"),
                "receipt_message_id": receipt["message_id"],
                "receipt_id": receipt["payload"]["receipt_id"],
                "receipt_content_digest": receipt["payload"]["receipt_content_digest"],
                "receipt_message_hash": receipt["message_hash"],
                "receipt_signature": receipt["signature"],
                "receipt_wire_bytes_b64": _b64(receipt_wire_bytes),
                "receipt_send_status": "pending",
            }
            document["delegations"][delegation_id] = record
            _atomic_json(self.path, document)
            return "created", record

    def mark_receipt_sent(self, delegation_id: str) -> None:
        with self._lock, _process_lock(self.path):
            document = _load_json(self.path, TARGET_RECORD_KEYS)
            if delegation_id in document["delegations"]:
                document["delegations"][delegation_id]["receipt_send_status"] = "sent"
                _atomic_json(self.path, document)


class OriginDelegationLedger:
    """Origin ledger with immutable request bytes and first-set target work ID."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def get(self, delegation_id: str) -> dict[str, JsonValue] | None:
        with self._lock, _process_lock(self.path):
            return _load_json(self.path, ORIGIN_RECORD_KEYS)["delegations"].get(delegation_id)

    def record_finding(self, code: str, delegation_id: str | None = None) -> None:
        with self._lock, _process_lock(self.path):
            document = _load_json(self.path, ORIGIN_RECORD_KEYS)
            document["findings"].append({"code": code, "delegation_id": delegation_id})
            _atomic_json(self.path, document)

    def mark_request_sent(self, delegation_id: str) -> None:
        with self._lock, _process_lock(self.path):
            document = _load_json(self.path, ORIGIN_RECORD_KEYS)
            if delegation_id in document["delegations"]:
                document["delegations"][delegation_id]["request_send_status"] = "sent"
                document["delegations"][delegation_id]["send_state"] = "sent"
                _atomic_json(self.path, document)

    def create_request(
        self, *, request_wire_bytes: bytes, request_carrier: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        request = parse_canonical(request_wire_bytes)
        delegation_id = request["payload"]["delegation_id"]
        with self._lock, _process_lock(self.path):
            document = _load_json(self.path, ORIGIN_RECORD_KEYS)
            if delegation_id in document["delegations"]:
                return document["delegations"][delegation_id]
            record = {
                "delegation_id": delegation_id,
                "origin_task_id": request["payload"]["origin_task_id"],
                "origin_node_id": request["source_node_id"],
                "request_message_id": request["request_message_id"],
                "correlation_id": request["correlation_id"],
                "target_node_id": request["target_node_id"],
                "request_digest": request["payload"]["request_digest"],
                "idempotency_key": request["payload"]["idempotency_key"],
                "request_message_hash": request["message_hash"],
                "request_wire_bytes_b64": _b64(request_wire_bytes),
                "request_carrier": dict(request_carrier),
                "request_send_status": "created",
                "send_state": "created",
                "target_work_id": None,
            }
            document["delegations"][delegation_id] = record
            _atomic_json(self.path, document)
            return record

    def apply_receipt(
        self, *, receipt: Mapping[str, JsonValue], receipt_wire_bytes: bytes, receipt_carrier: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        delegation_id = receipt["payload"]["delegation_id"]
        with self._lock, _process_lock(self.path):
            document = _load_json(self.path, ORIGIN_RECORD_KEYS)
            record = document["delegations"].get(delegation_id)
            if record is None:
                raise V1Reject("unknown_delegation", "origin_correlation")
            if (
                receipt["source_node_id"] != record["target_node_id"]
                or receipt["target_node_id"] != record["origin_node_id"]
                or receipt["payload"]["delegation_id"] != record["delegation_id"]
                or receipt["correlation_id"] != record["delegation_id"]
                or receipt["request_message_id"] != record["request_message_id"]
                or receipt.get("causation_message_id") != record["request_message_id"]
            ):
                document["findings"].append({"code": "receipt_correlation_conflict", "delegation_id": delegation_id})
                _atomic_json(self.path, document)
                raise V1Reject("receipt_correlation_conflict", "origin_correlation")
            work_id = receipt["payload"].get("target_work_id")
            if (
                receipt["payload"]["status"] == "accepted"
                and record.get("target_work_id") is not None
                and record["target_work_id"] != work_id
            ):
                raise V1Reject("receipt_ledger_conflict", "origin_correlation")
            if record.get("admission_receipt_id") is not None:
                if (
                    record["admission_receipt_id"] != receipt["payload"]["receipt_id"]
                    or record["admission_receipt_content_digest"] != receipt["payload"]["receipt_content_digest"]
                ):
                    raise V1Reject("receipt_id_conflict", "origin_correlation")
                if record["admission_receipt_wire_bytes_b64"] != _b64(receipt_wire_bytes):
                    raise V1Reject("receipt_id_conflict", "origin_correlation")
                return record
            if receipt["payload"]["status"] == "accepted":
                if record["target_work_id"] is None:
                    record["target_work_id"] = work_id
                elif record["target_work_id"] != work_id:
                    raise V1Reject("receipt_ledger_conflict", "origin_correlation")
                record["send_state"] = "admission_received"
            else:
                if work_id is not None:
                    raise V1Reject("receipt_schema", "origin_correlation")
                record["send_state"] = "admission_rejected"
            record.update(
                {
                    "admission_receipt_message_id": receipt["message_id"],
                    "admission_receipt_id": receipt["payload"]["receipt_id"],
                    "admission_receipt_content_digest": receipt["payload"]["receipt_content_digest"],
                    "admission_receipt_message_hash": receipt["message_hash"],
                    "admission_receipt_signature": receipt["signature"],
                    "admission_receipt_wire_bytes_b64": _b64(receipt_wire_bytes),
                    "admission_receipt_carrier": dict(receipt_carrier),
                }
            )
            document["delegations"][delegation_id] = record
            _atomic_json(self.path, document)
            return record


class FederationV1Origin:
    """Origin boundary: immutable request storage plus carrier creation."""

    def __init__(
        self,
        *,
        ledger: OriginDelegationLedger,
        node_id: str,
        signing_key: Ed25519PrivateKey,
        signer_key_b64: str,
        key_id: str,
        enabled: bool = FEATURE_GATE_DEFAULT,
    ):
        self.ledger = ledger
        self.node_id = node_id
        self.signing_key = signing_key
        self.signer_key_b64 = signer_key_b64
        self.key_id = key_id
        self.enabled = enabled

    def create(
        self, *, payload: Mapping[str, JsonValue], target_node_id: str, message_id: str, issued_at: str, expires_at: str
    ) -> tuple[bytes, dict[str, JsonValue]]:
        if not self.enabled:
            raise V1Reject("feature_disabled", "feature_gate")
        delegation_id = str(payload.get("delegation_id", ""))
        existing = self.ledger.get(delegation_id)
        if existing is not None:
            expected_payload = dict(payload)
            expected_digest = request_digest(expected_payload, self.node_id, target_node_id)
            expected_payload["request_digest"] = expected_digest
            expected_payload["idempotency_key"] = "fedv1:" + expected_digest
            stored_wire = base64.b64decode(existing["request_wire_bytes_b64"])
            stored = parse_canonical(stored_wire)
            same_request = (
                existing["request_digest"] == expected_digest
                and stored.get("source_node_id") == self.node_id
                and stored.get("target_node_id") == target_node_id
                and stored.get("message_id") == message_id
                and stored.get("request_message_id") == message_id
                and stored.get("issued_at") == issued_at
                and stored.get("expires_at") == expires_at
                and stored.get("signer_key") == self.signer_key_b64
                and stored.get("key_id") == self.key_id
                and stored.get("payload") == expected_payload
            )
            if same_request:
                return stored_wire, dict(existing["request_carrier"])
            self.ledger.record_finding("origin_request_conflict", delegation_id)
            raise V1Reject("origin_request_conflict", "origin_ledger")
        wire = build_request(
            payload=payload,
            source_node_id=self.node_id,
            target_node_id=target_node_id,
            message_id=message_id,
            signing_key=self.signing_key,
            signer_key_b64=self.signer_key_b64,
            key_id=self.key_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        carrier = build_carrier(wire)
        stored_record = self.ledger.create_request(request_wire_bytes=wire, request_carrier=carrier)
        stored_wire = base64.b64decode(stored_record["request_wire_bytes_b64"])
        stored_carrier = dict(stored_record["request_carrier"])
        if stored_wire != wire or stored_carrier != carrier:
            self.ledger.record_finding("origin_request_conflict", delegation_id)
            raise V1Reject("origin_request_conflict", "origin_ledger")
        return stored_wire, stored_carrier

    def retransmit(self, delegation_id: str) -> dict[str, JsonValue]:
        record = self.ledger.get(delegation_id)
        if record is None:
            raise V1Reject("unknown_delegation", "origin_ledger")
        return dict(record["request_carrier"])

    def apply_receipt(
        self, *, carrier: Mapping[str, JsonValue], registry: ValidatedFederationV1KeyRegistry, now: str | None = None
    ) -> dict[str, JsonValue]:
        if not self.enabled:
            raise V1Reject("feature_disabled", "feature_gate")
        inner, raw = carrier_inner(carrier, expected_target=self.node_id)
        receipt = validate_envelope(
            raw, registry=registry, expected_target=self.node_id, expected_operation="delegation_receipt", now=now
        )
        return self.ledger.apply_receipt(receipt=receipt, receipt_wire_bytes=raw, receipt_carrier=carrier)


class FederationV1Admission:
    """Target boundary: validate, atomically admit/reject, and return a carrier."""

    def __init__(
        self,
        *,
        ledger: TargetAdmissionLedger,
        node_id: str,
        signing_key: Ed25519PrivateKey,
        signer_key_b64: str,
        key_id: str,
        registry: ValidatedFederationV1KeyRegistry,
        enabled: bool = FEATURE_GATE_DEFAULT,
    ):
        self.ledger = ledger
        self.node_id = node_id
        self.signing_key = signing_key
        self.signer_key_b64 = signer_key_b64
        self.key_id = key_id
        self.registry = registry
        self.enabled = enabled

    @staticmethod
    def _policy_allows(payload: Mapping[str, JsonValue]) -> bool:
        """Admission-only policy: validate the V1 capability envelope, never execute it."""
        authority = payload.get("authority")
        return (
            payload.get("capability") == "fix_repository"
            and payload.get("target_repo") == "agent-city"
            and isinstance(authority, Mapping)
            and authority.get("repo_scope") == "agent-city"
            and isinstance(authority.get("allowed_actions"), list)
            and set(authority["allowed_actions"]) <= {"branch", "commit", "read", "test"}
            and isinstance(authority.get("denied_actions"), list)
            and "merge" in authority["denied_actions"]
        )

    def handle(
        self,
        carrier: Mapping[str, JsonValue],
        *,
        now: str,
        origin_authorized: bool = True,
        capability_available: bool = True,
    ) -> dict[str, JsonValue] | None:
        if not self.enabled:
            return None
        try:
            inner, raw = carrier_inner(carrier, expected_target=self.node_id)
            request = validate_envelope(
                raw, registry=self.registry, expected_target=self.node_id, expected_operation="delegate_task", now=now
            )
        except V1Reject:
            return None
        if not origin_authorized:
            status, reason, work_id = "rejected", "authority_denied", None
        elif not self._policy_allows(request["payload"]):
            status, reason, work_id = "rejected", "authority_denied", None
        elif not capability_available:
            status, reason, work_id = "rejected", "capability_unavailable", None
        else:
            status, reason, work_id = (
                "accepted",
                None,
                f"work_{hashlib.sha256((request['payload']['delegation_id'] + self.node_id).encode()).hexdigest()[:32]}",
            )
        existing = self.ledger.get(request["payload"]["delegation_id"])
        if existing is not None:
            if existing["request_digest"] != request["payload"]["request_digest"]:
                return None
            if existing["request_message_id"] == request["message_id"] and existing["request_wire_bytes_b64"] != _b64(
                raw
            ):
                return None
            return build_carrier(base64.b64decode(existing["receipt_wire_bytes_b64"]))
        receipt_wire = build_admission_receipt(
            request=request,
            target_node_id=self.node_id,
            origin_node_id=request["source_node_id"],
            message_id=f"rcpt_{request['message_id']}",
            receipt_id=f"receipt_{request['payload']['delegation_id']}",
            target_work_id=work_id,
            status=status,
            reason_code=reason,
            signing_key=self.signing_key,
            signer_key_b64=self.signer_key_b64,
            key_id=self.key_id,
            issued_at=now,
            expires_at=_expires_after(now),
        )
        receipt = parse_canonical(receipt_wire)
        result, _ = self.ledger.commit(
            request=request,
            request_wire_bytes=raw,
            request_carrier=carrier,
            receipt=receipt,
            receipt_wire_bytes=receipt_wire,
            state="ACCEPTED" if status == "accepted" else "REJECTED",
            reason_code=reason,
        )
        if result == "duplicate":
            stored = self.ledger.get(request["payload"]["delegation_id"])
            return build_carrier(base64.b64decode(stored["receipt_wire_bytes_b64"]))
        if result != "created":
            return None
        return build_carrier(receipt_wire)
