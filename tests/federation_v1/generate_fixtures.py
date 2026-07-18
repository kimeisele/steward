"""Generate federation-delegation-v1 Golden Wire Fixtures 01.

This module is test-only. It contains deterministic, non-production Ed25519 seeds and
writes reproducible fixture bytes. It does not import or modify runtime federation code.
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .reference import (
    DOMAIN_DELEGATION,
    DOMAIN_ROOT_ENROLLMENT,
    DOMAIN_SIGNING_KEY_AUTH,
    build_envelope,
    canonical_bytes,
    derive_key_id,
    derive_node_id,
    digest_hex,
    sign_digest,
)

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "federation_v1"
SPEC_COMMIT = "ddf170d10a5d546af4b012a2d2335c37fcb44508"
FIXTURE_VERSION = "federation-v1-golden-01"
ZERO_SIG = base64.b64encode(bytes(64)).decode("ascii")

SEEDS = {
    "origin_identity_root": bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"),
    "origin_signing_key": bytes.fromhex("202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f"),
    "target_identity_root": bytes.fromhex("404142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f"),
    "target_signing_key": bytes.fromhex("606162636465666768696a6b6c6d6e6f707172737475767778797a7b7c7d7e7f"),
    "unregistered_signing_key": bytes.fromhex("808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9f"),
}


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def material(label: str) -> dict:
    private = Ed25519PrivateKey.from_private_bytes(SEEDS[label])
    public = private.public_key().public_bytes_raw()
    return {
        "label": label,
        "private_seed_hex": SEEDS[label].hex(),
        "private_key_non_production": True,
        "public_key_b64": b64(public),
        "public_key_hex": public.hex(),
        "private": private,
        "public": public,
    }


def write_bytes(relative: str, data: bytes, artifacts: dict) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    artifacts[relative] = hashlib.sha256(data).hexdigest()


def write_canonical(relative: str, value: object, artifacts: dict) -> bytes:
    data = canonical_bytes(value)
    write_bytes(relative, data, artifacts)
    return data


def signed_record(body: dict, private: Ed25519PrivateKey, domain: str) -> tuple[dict, str, str]:
    body_bytes = canonical_bytes(body)
    body_digest = digest_hex(body_bytes)
    signature_input = domain.encode("utf-8") + b"\x00" + bytes.fromhex(body_digest)
    signature = sign_digest(private, domain, body_digest)
    record = {**body, "root_signature": signature}
    return record, body_digest, signature_input.hex()


def build_provenance(label: str, root: dict, signing: dict, artifacts: dict) -> dict:
    node_id = derive_node_id(root["public"])
    key_id = derive_key_id(signing["public"])
    provenance_digest = hashlib.sha256(
        ("golden-wire-provenance-v1:" + label).encode("utf-8")
    ).hexdigest()

    enrollment_body = {
        "enrollment_version": "federation-root-enrollment-v1",
        "identity_root_public_key": root["public_key_b64"],
        "node_id": node_id,
        "not_before": "2026-07-18T00:00:00Z",
        "provenance_digest": provenance_digest,
        "registry_epoch": 1,
    }
    enrollment, enrollment_digest, enrollment_input = signed_record(
        enrollment_body, root["private"], DOMAIN_ROOT_ENROLLMENT
    )
    write_canonical(f"provenance/{label}_root_enrollment.json", enrollment, artifacts)
    write_bytes(f"provenance/{label}_root_enrollment.signature_input.hex",
                enrollment_input.encode("ascii"), artifacts)

    certificate_body = {
        "activation_at": "2026-07-18T00:05:00Z",
        "activation_epoch": 1,
        "certificate_epoch": 1,
        "certificate_version": "federation-signing-key-auth-v1",
        "identity_root_public_key": root["public_key_b64"],
        "key_id": key_id,
        "node_id": node_id,
        "not_after": "2027-07-18T00:00:00Z",
        "not_before": "2026-07-18T00:05:00Z",
        "registry_epoch": 1,
        "revocation_ref": None,
        "rotation_kind": "regular",
        "signer_key": signing["public_key_b64"],
    }
    certificate, certificate_digest, certificate_input = signed_record(
        certificate_body, root["private"], DOMAIN_SIGNING_KEY_AUTH
    )
    write_canonical(f"provenance/{label}_signing_key_certificate.json", certificate, artifacts)
    write_bytes(f"provenance/{label}_signing_key_certificate.signature_input.hex",
                certificate_input.encode("ascii"), artifacts)

    return {
        "node_id": node_id,
        "key_id": key_id,
        "enrollment_digest": enrollment_digest,
        "enrollment_signature": enrollment["root_signature"],
        "certificate_digest": certificate_digest,
        "certificate_signature": certificate["root_signature"],
    }


def request_payload(origin: dict, target: dict, description: str = "Repair the bounded federation defect.") -> dict:
    payload = {
        "delegation_id": "del_golden_0001",
        "origin_task_id": "task_golden_0001",
        "capability": "fix_repository",
        "intent": {"kind": "repair", "version": "v1"},
        "task_description": description,
        "target_repo": "agent-city",
        "authority": {
            "allowed_actions": ["branch", "commit", "read", "test"],
            "denied_actions": ["context_bridge_activation", "merge", "secret_access"],
            "repo_scope": "agent-city",
        },
        "expected_outcome": {"kind": "verified_tests_and_observation"},
        "verification_contract": {
            "postcondition_kind": "tests_and_runtime_observation",
            "required_evidence": ["runtime_observation", "test_result"],
        },
        "deadline": "2026-07-18T12:00:00Z",
    }
    semantic = {
        "contract_version": "federation-delegation-v1",
        "operation": "delegate_task",
        "source_node_id": origin["node_id"],
        "target_node_id": target["node_id"],
        "payload": payload,
    }
    request_digest = digest_hex(canonical_bytes(semantic))
    return {
        **payload,
        "request_digest": request_digest,
        "idempotency_key": "fedv1:" + request_digest,
    }


def make_fixtures() -> None:
    if ROOT.exists():
        for child in ROOT.iterdir():
            if child.name != "README.md":
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
    ROOT.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}

    origin_root = material("origin_identity_root")
    origin_signing = material("origin_signing_key")
    target_root = material("target_identity_root")
    target_signing = material("target_signing_key")
    unregistered = material("unregistered_signing_key")

    keys = {}
    for key in (origin_root, origin_signing, target_root, target_signing, unregistered):
        keys[key["label"]] = {
            "private_seed_hex": key["private_seed_hex"],
            "private_key_non_production": True,
            "public_key_b64": key["public_key_b64"],
            "public_key_hex": key["public_key_hex"],
        }
    write_canonical("keys/test_keys.json", keys, artifacts)

    origin_identity = build_provenance("origin", origin_root, origin_signing, artifacts)
    target_identity = build_provenance("target", target_root, target_signing, artifacts)
    unregistered_node = derive_node_id(unregistered["public"])
    unregistered_key_id = derive_key_id(unregistered["public"])

    origin_signing["node_id"] = origin_identity["node_id"]
    origin_signing["key_id"] = origin_identity["key_id"]
    target_signing["node_id"] = target_identity["node_id"]
    target_signing["key_id"] = target_identity["key_id"]

    payload = request_payload(origin_identity, target_identity)
    envelope = build_envelope(
        payload=payload,
        source_node_id=origin_identity["node_id"],
        target_node_id=target_identity["node_id"],
        message_id="msg_req_golden_0001",
        request_message_id="msg_req_golden_0001",
        signing_key=origin_signing["private"],
        signer_key_b64=origin_signing["public_key_b64"],
        key_id=origin_identity["key_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    envelope_bytes = write_canonical("messages/delegate_task.json", envelope, artifacts)
    request_digest = payload["request_digest"]
    message_hash = envelope["message_hash"]
    write_bytes(
        "messages/delegate_task.signature_input.hex",
        (DOMAIN_DELEGATION.encode("utf-8") + b"\x00" + bytes.fromhex(message_hash)).hex().encode("ascii"),
        artifacts,
    )

    negative: list[dict] = []

    def write_negative(name: str, data: bytes, expected: str, phase: str) -> None:
        relative = f"negative/{name}.bin"
        write_bytes(relative, data, artifacts)
        negative.append({
            "id": name,
            "path": relative,
            "expected_reject_code": expected,
            "validation_phase": phase,
        })

    write_negative("non_nfc", b'{"x":"e\\u0301"}', "rejected_noncanonical", "sfdj_nfc")
    write_negative("wrong_key_order", b'{"b":1,"a":2}', "rejected_noncanonical", "sfdj_key_order")
    write_negative("duplicate_json_key", b'{"a":1,"a":2}', "duplicate_json_key", "parse")
    write_negative("float", b'{"n":1.0}', "float_forbidden", "number")
    write_negative("negative_zero", b'{"n":-0}', "rejected_noncanonical", "number")
    write_negative("missing_base64_padding", canonical_bytes({**envelope, "signature": envelope["signature"][:-1]}),
                   "invalid_base64", "base64")
    write_negative("url_safe_base64", canonical_bytes({**envelope, "signature": "-" + envelope["signature"][1:]}),
                   "url_safe_base64_forbidden", "base64")
    write_negative("wrong_message_hash", canonical_bytes({**envelope, "message_hash": "0" * 64}),
                   "message_hash_mismatch", "message_hash")
    mutated_payload = {**envelope, "payload": {**envelope["payload"], "task_description": "mutated"}}
    write_negative("mutated_payload", canonical_bytes(mutated_payload),
                   "message_hash_mismatch", "message_hash")
    mutated_target = {**envelope, "target_node_id": origin_identity["node_id"]}
    write_negative("mutated_target_node_id", canonical_bytes(mutated_target),
                   "message_hash_mismatch", "message_hash")
    wrong_key_envelope = build_envelope(
        payload=payload,
        source_node_id=origin_identity["node_id"],
        target_node_id=target_identity["node_id"],
        message_id="msg_negative_wrong_key",
        request_message_id="msg_negative_wrong_key",
        signing_key=origin_signing["private"],
        signer_key_b64=target_signing["public_key_b64"],
        key_id=target_identity["key_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    write_negative("wrong_signing_key", canonical_bytes(wrong_key_envelope),
                   "signature_invalid_wrong_key", "signature")
    unregistered_envelope = build_envelope(
        payload=payload,
        source_node_id=origin_identity["node_id"],
        target_node_id=target_identity["node_id"],
        message_id="msg_negative_unregistered",
        request_message_id="msg_negative_unregistered",
        signing_key=unregistered["private"],
        signer_key_b64=unregistered["public_key_b64"],
        key_id=unregistered_key_id,
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    write_negative("unregistered_signing_key", canonical_bytes(unregistered_envelope),
                   "key_not_authorized", "registry")
    wrong_target_envelope = build_envelope(
        payload=request_payload(origin_identity, {"node_id": "ag_" + "3" * 32}),
        source_node_id=origin_identity["node_id"],
        target_node_id="ag_" + "3" * 32,
        message_id="msg_negative_wrong_target",
        request_message_id="msg_negative_wrong_target",
        signing_key=origin_signing["private"],
        signer_key_b64=origin_signing["public_key_b64"],
        key_id=origin_identity["key_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    write_negative("wrong_target_resigned", canonical_bytes(wrong_target_envelope),
                   "wrong_target", "target_match")

    duplicate_payload = request_payload(origin_identity, target_identity, "Different request body.")
    duplicate_envelope = build_envelope(
        payload=duplicate_payload,
        source_node_id=origin_identity["node_id"],
        target_node_id=target_identity["node_id"],
        message_id="msg_negative_duplicate_delegation",
        request_message_id="msg_negative_duplicate_delegation",
        signing_key=origin_signing["private"],
        signer_key_b64=origin_signing["public_key_b64"],
        key_id=origin_identity["key_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    write_negative("same_delegation_different_digest", canonical_bytes(duplicate_envelope),
                   "duplicate_conflict", "target_dedupe")

    same_message_envelope = build_envelope(
        payload=duplicate_payload,
        source_node_id=origin_identity["node_id"],
        target_node_id=target_identity["node_id"],
        message_id="msg_req_golden_0001",
        request_message_id="msg_req_golden_0001",
        signing_key=origin_signing["private"],
        signer_key_b64=origin_signing["public_key_b64"],
        key_id=origin_identity["key_id"],
        issued_at="2026-07-18T11:01:00Z",
        expires_at="2026-07-18T11:06:00Z",
    )
    write_negative("same_message_id_different_bytes", canonical_bytes(same_message_envelope),
                   "message_id_conflict", "message_dedupe")

    expired_body = {
        **{
            "activation_at": "2025-01-01T00:00:00Z",
            "activation_epoch": 0,
            "certificate_epoch": 0,
            "certificate_version": "federation-signing-key-auth-v1",
            "identity_root_public_key": origin_root["public_key_b64"],
            "key_id": origin_identity["key_id"],
            "node_id": origin_identity["node_id"],
            "not_after": "2025-12-31T23:59:59Z",
            "not_before": "2025-01-01T00:00:00Z",
            "registry_epoch": 0,
            "revocation_ref": None,
            "rotation_kind": "regular",
            "signer_key": origin_signing["public_key_b64"],
        }
    }
    expired_record, _, _ = signed_record(expired_body, origin_root["private"], DOMAIN_SIGNING_KEY_AUTH)
    write_canonical("negative/expired_certificate.json", expired_record, artifacts)
    negative.append({
        "id": "expired_certificate",
        "path": "negative/expired_certificate.json",
        "expected_reject_code": "certificate_expired",
        "validation_phase": "registry_time",
    })

    revoked_body = {**expired_body, "not_after": "2027-12-31T23:59:59Z",
                    "revocation_ref": "f" * 64}
    revoked_record, _, _ = signed_record(revoked_body, origin_root["private"], DOMAIN_SIGNING_KEY_AUTH)
    write_canonical("negative/revoked_certificate.json", revoked_record, artifacts)
    negative.append({
        "id": "revoked_certificate",
        "path": "negative/revoked_certificate.json",
        "expected_reject_code": "key_revoked",
        "validation_phase": "registry_status",
    })

    positive = {
        "root_enrollment": {
            "origin": {k: v for k, v in origin_identity.items()},
            "target": {k: v for k, v in target_identity.items()},
        },
        "request": {
            "path": "messages/delegate_task.json",
            "request_digest": request_digest,
            "idempotency_key": payload["idempotency_key"],
            "message_hash": message_hash,
            "signature": envelope["signature"],
            "signature_input_hex": (DOMAIN_DELEGATION.encode("utf-8") + b"\x00" + bytes.fromhex(message_hash)).hex(),
            "origin_node_id": origin_identity["node_id"],
            "target_node_id": target_identity["node_id"],
            "origin_key_id": origin_identity["key_id"],
        },
    }
    manifest = {
        "fixture_version": FIXTURE_VERSION,
        "spec_commit": SPEC_COMMIT,
        "private_keys": "test-only deterministic seeds; never production",
        "manifest_excludes_self": True,
        "artifacts": artifacts,
        "positive": positive,
        "negative": negative,
    }
    write_bytes(
        "README.md",
        (
            "# Federation V1 Golden Wire Fixtures 01\n\n"
            "Deterministic test-only Ed25519 seeds and SFDJ-1 bytes. Private seeds are synthetic "
            "and must never be used outside tests. The manifest records SHA-256 for every fixture "
            "artifact except itself.\n"
        ).encode("utf-8"),
        artifacts,
    )
    write_canonical("manifest.json", manifest, artifacts={})


if __name__ == "__main__":
    make_fixtures()
