"""Production boundary for the first Federation Delegation V1 slice.

This module is intentionally small and additive.  It does not alter the legacy
``OP_DELEGATE_TASK`` path, does not execute work, and does not implement recovery.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import unicodedata
from pathlib import Path
from typing import Any, Mapping

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

REQUEST_KEYS = {
    "contract_version", "message_id", "request_message_id", "source_node_id",
    "target_node_id", "operation", "correlation_id", "payload", "issued_at",
    "expires_at", "message_hash", "signature", "signer_key", "key_id",
}
RECEIPT_KEYS = REQUEST_KEYS | {"causation_message_id"}


class V1Reject(ValueError):
    """A fail-closed V1 rejection with a stable machine code and phase."""

    def __init__(self, code: str, phase: str):
        super().__init__(code)
        self.code = code
        self.phase = phase


def _string(value: str) -> str:
    if unicodedata.normalize("NFC", value) != value:
        raise V1Reject("rejected_noncanonical", "sfdj_nfc")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise V1Reject("invalid_unicode", "sfdj_nfc") from exc
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace(
        "\\b", "\\u0008"
    ).replace("\\t", "\\u0009").replace("\\n", "\\u000a").replace("\\f", "\\u000c").replace("\\r", "\\u000d")


def _canonical(value: Any, depth: int = 0) -> str:
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


def canonical_bytes(value: Any) -> bytes:
    raw = _canonical(value).encode("utf-8")
    if len(raw) > MAX_WIRE_BYTES:
        raise V1Reject("envelope_limit", "sfdj_size")
    return raw


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise V1Reject("duplicate_json_key", "parse")
        result[key] = value
    return result


def parse_canonical(raw: bytes) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise V1Reject("bom_forbidden", "parse")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(V1Reject("float_forbidden", "sfdj_number")))
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
    if not isinstance(value, str) or len(value) % 4 or "-" in value or "_" in value or any(ch.isspace() for ch in value):
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


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _signature_input(digest: str) -> bytes:
    return DOMAIN_DELEGATION.encode("utf-8") + b"\x00" + bytes.fromhex(digest)


def request_digest(payload: Mapping[str, Any], source_node_id: str, target_node_id: str) -> str:
    fields = ("delegation_id", "origin_task_id", "capability", "intent", "task_description", "target_repo", "authority", "expected_outcome", "verification_contract", "deadline")
    semantic = {"contract_version": CONTRACT_VERSION, "operation": "delegate_task", "source_node_id": source_node_id, "target_node_id": target_node_id, "payload": {field: payload[field] for field in fields}}
    return _digest(semantic)


def build_request(*, payload: Mapping[str, Any], source_node_id: str, target_node_id: str, message_id: str, signing_key: Ed25519PrivateKey, signer_key_b64: str, key_id: str, issued_at: str, expires_at: str) -> bytes:
    body_payload = dict(payload)
    digest = request_digest(body_payload, source_node_id, target_node_id)
    body_payload["request_digest"] = digest
    body_payload["idempotency_key"] = "fedv1:" + digest
    envelope = {"contract_version": CONTRACT_VERSION, "message_id": message_id, "request_message_id": message_id, "source_node_id": source_node_id, "target_node_id": target_node_id, "operation": "delegate_task", "correlation_id": body_payload["delegation_id"], "payload": body_payload, "issued_at": issued_at, "expires_at": expires_at, "signer_key": signer_key_b64, "key_id": key_id}
    digest = _digest(envelope)
    envelope["message_hash"] = digest
    envelope["signature"] = _b64(signing_key.sign(_signature_input(digest)))
    return canonical_bytes(envelope)


def build_admission_receipt(*, request: Mapping[str, Any], target_node_id: str, origin_node_id: str, message_id: str, receipt_id: str, target_work_id: str | None, status: str, reason_code: str | None, signing_key: Ed25519PrivateKey, signer_key_b64: str, key_id: str, issued_at: str, expires_at: str) -> bytes:
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


def _registry_entry(registry: Mapping[str, Any], key_id: str) -> tuple[str, bytes, Mapping[str, Any]]:
    entry = registry.get(key_id)
    if not isinstance(entry, Mapping):
        raise V1Reject("key_not_authorized", "registry")
    public = entry.get("public_key")
    if isinstance(public, str):
        public = _b64_decode(public, 32)
    if not isinstance(public, bytes) or len(public) != 32:
        raise V1Reject("key_not_authorized", "registry")
    return str(entry.get("node_id", "")), public, entry


def validate_envelope(raw: bytes, *, registry: Mapping[str, Any], expected_target: str, expected_operation: str = "delegate_task", now: str | None = None) -> dict[str, Any]:
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
    node_id, authorized_public, entry = _registry_entry(registry, value["key_id"])
    if node_id != value["source_node_id"] or authorized_public != signer:
        raise V1Reject("key_not_authorized", "registry")
    if entry.get("revoked"):
        raise V1Reject("key_revoked", "registry_status")
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
        required = {"delegation_id", "origin_task_id", "capability", "intent", "task_description", "target_repo", "authority", "expected_outcome", "verification_contract", "deadline", "request_digest", "idempotency_key"}
        if not required <= set(payload) or set(payload) - required - {"display_title", "display_description"}:
            raise V1Reject("payload_schema", "schema")
        try:
            computed_request = request_digest(payload, value["source_node_id"], value["target_node_id"])
        except (KeyError, TypeError):
            raise V1Reject("request_digest_mismatch", "request_digest")
        if payload["request_digest"] != computed_request or payload["idempotency_key"] != "fedv1:" + computed_request:
            raise V1Reject("request_digest_mismatch", "request_digest")
    else:
        receipt_required = {"receipt_id", "delegation_id", "receipt_stage", "issuer_role", "status", "target_work_id", "reason_code", "evidence_refs", "receipt_content_digest"}
        if set(payload) != receipt_required or payload["receipt_stage"] != "admission" or payload["issuer_role"] != "target_node":
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


def build_carrier(raw: bytes) -> dict[str, Any]:
    inner = parse_canonical(raw)
    operation = _carrier_operation(str(inner["operation"]))
    encoded = _b64(raw)
    if len(encoded) > MAX_CARRIER_B64:
        raise V1Reject("carrier_size", "carrier")
    return {"operation": operation, "source": inner["source_node_id"], "target": inner["target_node_id"], "payload": {"wire_version": CONTRACT_VERSION, "wire_bytes_b64": encoded}}


def carrier_inner(carrier: Mapping[str, Any], *, expected_target: str) -> tuple[dict[str, Any], bytes]:
    if set(carrier) != {"operation", "source", "target", "payload"} or not isinstance(carrier.get("payload"), Mapping) or set(carrier["payload"]) != {"wire_version", "wire_bytes_b64"}:
        raise V1Reject("carrier_schema", "carrier")
    if carrier["target"] != expected_target or not NODE_RE.fullmatch(str(carrier["source"])) or not NODE_RE.fullmatch(str(carrier["target"])):
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


def _atomic_json(path: Path, data: Any) -> None:
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


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"delegations": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"delegations": {}}
    return value if isinstance(value, dict) and isinstance(value.get("delegations"), dict) else {"delegations": {}}


class TargetAdmissionLedger:
    """Durable target ledger; the single JSON replacement is the admission commit."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def get(self, delegation_id: str) -> dict[str, Any] | None:
        with self._lock:
            return _load_json(self.path)["delegations"].get(delegation_id)

    def commit(self, *, request: Mapping[str, Any], request_wire_bytes: bytes, request_carrier: Mapping[str, Any], receipt: Mapping[str, Any], receipt_wire_bytes: bytes, state: str, reason_code: str | None = None) -> tuple[str, dict[str, Any]]:
        delegation_id = str(request["payload"]["delegation_id"])
        request_digest_value = str(request["payload"]["request_digest"])
        with self._lock:
            document = _load_json(self.path)
            existing = document["delegations"].get(delegation_id)
            if existing is not None:
                if existing.get("request_digest") != request_digest_value:
                    return "duplicate_conflict", existing
                if existing.get("request_message_id") == request["message_id"] and existing.get("request_wire_bytes_b64") != _b64(request_wire_bytes):
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
        with self._lock:
            document = _load_json(self.path)
            if delegation_id in document["delegations"]:
                document["delegations"][delegation_id]["receipt_send_status"] = "sent"
                _atomic_json(self.path, document)


class OriginDelegationLedger:
    """Origin ledger with immutable request bytes and first-set target work ID."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def get(self, delegation_id: str) -> dict[str, Any] | None:
        with self._lock:
            return _load_json(self.path)["delegations"].get(delegation_id)

    def mark_request_sent(self, delegation_id: str) -> None:
        with self._lock:
            document = _load_json(self.path)
            if delegation_id in document["delegations"]:
                document["delegations"][delegation_id]["request_send_status"] = "sent"
                document["delegations"][delegation_id]["send_state"] = "sent"
                _atomic_json(self.path, document)

    def create_request(self, *, request_wire_bytes: bytes, request_carrier: Mapping[str, Any]) -> dict[str, Any]:
        request = parse_canonical(request_wire_bytes)
        delegation_id = request["payload"]["delegation_id"]
        with self._lock:
            document = _load_json(self.path)
            if delegation_id in document["delegations"]:
                return document["delegations"][delegation_id]
            record = {
                "delegation_id": delegation_id,
                "origin_task_id": request["payload"]["origin_task_id"],
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

    def apply_receipt(self, *, receipt: Mapping[str, Any], receipt_wire_bytes: bytes, receipt_carrier: Mapping[str, Any]) -> dict[str, Any]:
        delegation_id = receipt["payload"]["delegation_id"]
        with self._lock:
            document = _load_json(self.path)
            record = document["delegations"].get(delegation_id)
            if record is None:
                raise V1Reject("unknown_delegation", "origin_correlation")
            if receipt["request_message_id"] != record["request_message_id"]:
                raise V1Reject("receipt_correlation_conflict", "origin_correlation")
            work_id = receipt["payload"].get("target_work_id")
            if receipt["payload"]["status"] == "accepted" and record.get("target_work_id") is not None and record["target_work_id"] != work_id:
                raise V1Reject("receipt_ledger_conflict", "origin_correlation")
            if record.get("admission_receipt_id") is not None:
                if record["admission_receipt_id"] != receipt["payload"]["receipt_id"] or record["admission_receipt_content_digest"] != receipt["payload"]["receipt_content_digest"]:
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
            record.update({
                "admission_receipt_message_id": receipt["message_id"],
                "admission_receipt_id": receipt["payload"]["receipt_id"],
                "admission_receipt_content_digest": receipt["payload"]["receipt_content_digest"],
                "admission_receipt_message_hash": receipt["message_hash"],
                "admission_receipt_signature": receipt["signature"],
                "admission_receipt_wire_bytes_b64": _b64(receipt_wire_bytes),
                "admission_receipt_carrier": dict(receipt_carrier),
            })
            document["delegations"][delegation_id] = record
            _atomic_json(self.path, document)
            return record


class FederationV1Origin:
    """Origin boundary: immutable request storage plus carrier creation."""

    def __init__(self, *, ledger: OriginDelegationLedger, node_id: str, signing_key: Ed25519PrivateKey, signer_key_b64: str, key_id: str, enabled: bool = FEATURE_GATE_DEFAULT):
        self.ledger = ledger
        self.node_id = node_id
        self.signing_key = signing_key
        self.signer_key_b64 = signer_key_b64
        self.key_id = key_id
        self.enabled = enabled

    def create(self, *, payload: Mapping[str, Any], target_node_id: str, message_id: str, issued_at: str, expires_at: str) -> tuple[bytes, dict[str, Any]]:
        if not self.enabled:
            raise V1Reject("feature_disabled", "feature_gate")
        wire = build_request(payload=payload, source_node_id=self.node_id, target_node_id=target_node_id, message_id=message_id, signing_key=self.signing_key, signer_key_b64=self.signer_key_b64, key_id=self.key_id, issued_at=issued_at, expires_at=expires_at)
        carrier = build_carrier(wire)
        self.ledger.create_request(request_wire_bytes=wire, request_carrier=carrier)
        return wire, carrier

    def retransmit(self, delegation_id: str) -> dict[str, Any]:
        record = self.ledger.get(delegation_id)
        if record is None:
            raise V1Reject("unknown_delegation", "origin_ledger")
        return dict(record["request_carrier"])

    def apply_receipt(self, *, carrier: Mapping[str, Any], registry: Mapping[str, Any], now: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise V1Reject("feature_disabled", "feature_gate")
        inner, raw = carrier_inner(carrier, expected_target=self.node_id)
        receipt = validate_envelope(raw, registry=registry, expected_target=self.node_id, expected_operation="delegation_receipt", now=now)
        return self.ledger.apply_receipt(receipt=receipt, receipt_wire_bytes=raw, receipt_carrier=carrier)


class FederationV1Admission:
    """Target boundary: validate, atomically admit/reject, and return a carrier."""

    def __init__(self, *, ledger: TargetAdmissionLedger, node_id: str, signing_key: Ed25519PrivateKey, signer_key_b64: str, key_id: str, registry: Mapping[str, Any], enabled: bool = FEATURE_GATE_DEFAULT):
        self.ledger = ledger
        self.node_id = node_id
        self.signing_key = signing_key
        self.signer_key_b64 = signer_key_b64
        self.key_id = key_id
        self.registry = registry
        self.enabled = enabled

    @staticmethod
    def _policy_allows(payload: Mapping[str, Any]) -> bool:
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

    def handle(self, carrier: Mapping[str, Any], *, now: str, origin_authorized: bool = True, capability_available: bool = True) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        try:
            inner, raw = carrier_inner(carrier, expected_target=self.node_id)
            request = validate_envelope(raw, registry=self.registry, expected_target=self.node_id, expected_operation="delegate_task", now=now)
        except V1Reject:
            return None
        if not origin_authorized:
            status, reason, work_id = "rejected", "authority_denied", None
        elif not self._policy_allows(request["payload"]):
            status, reason, work_id = "rejected", "authority_denied", None
        elif not capability_available:
            status, reason, work_id = "rejected", "capability_unavailable", None
        else:
            status, reason, work_id = "accepted", None, f"work_{hashlib.sha256((request['payload']['delegation_id'] + self.node_id).encode()).hexdigest()[:32]}"
        existing = self.ledger.get(request["payload"]["delegation_id"])
        if existing is not None:
            if existing["request_digest"] != request["payload"]["request_digest"]:
                return None
            if existing["request_message_id"] == request["message_id"] and existing["request_wire_bytes_b64"] != _b64(raw):
                return None
            return build_carrier(base64.b64decode(existing["receipt_wire_bytes_b64"]))
        receipt_wire = build_admission_receipt(request=request, target_node_id=self.node_id, origin_node_id=request["source_node_id"], message_id=f"rcpt_{request['message_id']}", receipt_id=f"receipt_{request['payload']['delegation_id']}", target_work_id=work_id, status=status, reason_code=reason, signing_key=self.signing_key, signer_key_b64=self.signer_key_b64, key_id=self.key_id, issued_at=now, expires_at=_expires_after(now))
        receipt = parse_canonical(receipt_wire)
        result, _ = self.ledger.commit(request=request, request_wire_bytes=raw, request_carrier=carrier, receipt=receipt, receipt_wire_bytes=receipt_wire, state="ACCEPTED" if status == "accepted" else "REJECTED", reason_code=reason)
        if result == "duplicate":
            stored = self.ledger.get(request["payload"]["delegation_id"])
            return build_carrier(base64.b64decode(stored["receipt_wire_bytes_b64"]))
        if result != "created":
            return None
        return build_carrier(receipt_wire)
