from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .reference import (
    DOMAIN_DELEGATION,
    DOMAIN_ROOT_ENROLLMENT,
    DOMAIN_SIGNING_KEY_AUTH,
    SFDJReject,
    assert_shape,
    canonical_bytes,
    derive_key_id,
    derive_node_id,
    digest_hex,
    parse_canonical,
    request_digest,
    verify_digest,
)

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "federation_v1"
MANIFEST = json.loads((ROOT / "manifest.json").read_bytes())
KEYS = json.loads((ROOT / "keys" / "test_keys.json").read_bytes())


def _public(label: str) -> bytes:
    return base64.b64decode(KEYS[label]["public_key_b64"], validate=True)


def _private(label: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(KEYS[label]["private_seed_hex"]))


def _classify_negative(raw: bytes) -> str:
    try:
        value = parse_canonical(raw)
    except SFDJReject as exc:
        return str(exc)
    if "certificate_version" in value:
        if value["revocation_ref"] is not None:
            return "key_revoked"
        if value["not_after"] < "2026-07-18T11:00:00Z":
            return "certificate_expired"
        return "unclassified"
    if "signature" in value:
        expected_hash = digest_hex(canonical_bytes({k: v for k, v in value.items() if k not in {"message_hash", "signature"}}))
        if expected_hash != value.get("message_hash"):
            return "message_hash_mismatch"
        if "-" in value["signature"] or "_" in value["signature"]:
            return "url_safe_base64_forbidden"
        try:
            signature = base64.b64decode(value["signature"], validate=True)
            signer = base64.b64decode(value["signer_key"], validate=True)
        except Exception:
            return "invalid_base64"
        if len(signature) != 64 or len(signer) != 32:
            return "invalid_base64"
        if value["target_node_id"] != MANIFEST["positive"]["request"]["target_node_id"]:
            return "wrong_target"
        if value["key_id"] in {
            MANIFEST["positive"]["request"]["origin_key_id"],
            MANIFEST["positive"]["root_enrollment"]["target"]["key_id"],
        } and not verify_digest(signer, DOMAIN_DELEGATION, value["message_hash"], value["signature"]):
            return "signature_invalid_wrong_key"
        if value["key_id"] not in {
            MANIFEST["positive"]["request"]["origin_key_id"],
            MANIFEST["positive"]["root_enrollment"]["target"]["key_id"],
        }:
            return "key_not_authorized"
        if value["message_id"] == "msg_req_golden_0001" and raw != (ROOT / "messages" / "delegate_task.json").read_bytes():
            return "message_id_conflict"
        positive_payload = parse_canonical((ROOT / "messages" / "delegate_task.json").read_bytes())["payload"]
        if value.get("payload", {}).get("delegation_id") == positive_payload["delegation_id"] and value.get("payload", {}).get("request_digest") != positive_payload["request_digest"]:
            return "duplicate_conflict"
    return "unclassified"


def test_manifest_hashes_are_reproducible() -> None:
    for relative, expected in MANIFEST["artifacts"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_provenance_records_are_canonical_and_root_signed() -> None:
    expected_keys = {
        "enrollment_version",
        "identity_root_public_key",
        "node_id",
        "not_before",
        "provenance_digest",
        "registry_epoch",
        "root_signature",
    }
    certificate_keys = {
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
    for label, root_label, signing_label, domain in (
        ("origin", "origin_identity_root", "origin_signing_key", DOMAIN_ROOT_ENROLLMENT),
        ("target", "target_identity_root", "target_signing_key", DOMAIN_ROOT_ENROLLMENT),
    ):
        enrollment_raw = (ROOT / f"provenance/{label}_root_enrollment.json").read_bytes()
        enrollment = parse_canonical(enrollment_raw)
        assert set(enrollment) == expected_keys
        root_public = _public(root_label)
        assert enrollment["node_id"] == derive_node_id(root_public)
        digest = digest_hex(canonical_bytes({k: v for k, v in enrollment.items() if k != "root_signature"}))
        assert verify_digest(root_public, domain, digest, enrollment["root_signature"])
        assert enrollment["root_signature"] == MANIFEST["positive"]["root_enrollment"][label]["enrollment_signature"]

        cert_raw = (ROOT / f"provenance/{label}_signing_key_certificate.json").read_bytes()
        certificate = parse_canonical(cert_raw)
        assert set(certificate) == certificate_keys
        cert_digest = digest_hex(canonical_bytes({k: v for k, v in certificate.items() if k != "root_signature"}))
        assert verify_digest(root_public, DOMAIN_SIGNING_KEY_AUTH, cert_digest, certificate["root_signature"])
        assert certificate["node_id"] == enrollment["node_id"]
        assert certificate["key_id"] == derive_key_id(base64.b64decode(certificate["signer_key"], validate=True))
        assert certificate["root_signature"] == MANIFEST["positive"]["root_enrollment"][label]["certificate_signature"]


def test_delegate_task_positive_is_exact_and_verifiable() -> None:
    raw = (ROOT / "messages" / "delegate_task.json").read_bytes()
    envelope = parse_canonical(raw)
    assert_shape(envelope)
    payload = envelope["payload"]
    assert request_digest(payload, envelope["source_node_id"], envelope["target_node_id"]) == payload["request_digest"]
    assert payload["idempotency_key"] == "fedv1:" + payload["request_digest"]
    expected_hash = digest_hex(canonical_bytes({k: v for k, v in envelope.items() if k not in {"message_hash", "signature"}}))
    assert expected_hash == envelope["message_hash"]
    public = _public("origin_signing_key")
    assert verify_digest(public, DOMAIN_DELEGATION, envelope["message_hash"], envelope["signature"])
    assert envelope["message_hash"] == MANIFEST["positive"]["request"]["message_hash"]
    assert envelope["signature"] == MANIFEST["positive"]["request"]["signature"]
    assert (ROOT / "messages" / "delegate_task.signature_input.hex").read_text() == (
        DOMAIN_DELEGATION.encode() + b"\x00" + bytes.fromhex(envelope["message_hash"])
    ).hex()


@pytest.mark.parametrize("case", MANIFEST["negative"])
def test_negative_fixture_has_expected_rejection(case: dict) -> None:
    raw = (ROOT / case["path"]).read_bytes()
    assert _classify_negative(raw) == case["expected_reject_code"], case["id"]
