from __future__ import annotations

import base64
import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from steward.federation_v1 import (
    FederationV1Admission,
    FederationV1Origin,
    OriginDelegationLedger,
    TargetAdmissionLedger,
    V1Reject,
    ValidatedFederationV1KeyRegistry,
    build_admission_receipt,
    build_carrier,
    canonical_bytes,
    parse_canonical,
    validate_envelope,
)

FIXTURES = Path(__file__).parent / "fixtures" / "federation_v1"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_bytes())
KEYS = json.loads((FIXTURES / "keys" / "test_keys.json").read_bytes())
REQUEST = parse_canonical((FIXTURES / "messages" / "delegate_task.json").read_bytes())


def private(label: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(KEYS[label]["private_seed_hex"]))


def semantic_payload() -> dict:
    return {key: value for key, value in REQUEST["payload"].items() if key not in {"request_digest", "idempotency_key"}}


def registries() -> tuple[ValidatedFederationV1KeyRegistry, ValidatedFederationV1KeyRegistry]:
    provenance = FIXTURES / "provenance"
    origin = ValidatedFederationV1KeyRegistry.from_provenance(
        [json.loads((provenance / "origin_root_enrollment.json").read_bytes())],
        [json.loads((provenance / "origin_signing_key_certificate.json").read_bytes())],
        now="2026-07-18T11:00:00Z",
    )
    target = ValidatedFederationV1KeyRegistry.from_provenance(
        [json.loads((provenance / "target_root_enrollment.json").read_bytes())],
        [json.loads((provenance / "target_signing_key_certificate.json").read_bytes())],
        now="2026-07-18T11:00:00Z",
    )
    return origin, target


def services(tmp_path: Path):
    origin_registry, target_registry = registries()
    origin_ledger = OriginDelegationLedger(tmp_path / "origin.json")
    target_ledger = TargetAdmissionLedger(tmp_path / "target.json")
    origin = FederationV1Origin(
        ledger=origin_ledger,
        node_id=MANIFEST["positive"]["request"]["origin_node_id"],
        signing_key=private("origin_signing_key"),
        signer_key_b64=KEYS["origin_signing_key"]["public_key_b64"],
        key_id=MANIFEST["positive"]["request"]["origin_key_id"],
        enabled=True,
    )
    target = FederationV1Admission(
        ledger=target_ledger,
        node_id=MANIFEST["positive"]["request"]["target_node_id"],
        signing_key=private("target_signing_key"),
        signer_key_b64=KEYS["target_signing_key"]["public_key_b64"],
        key_id=MANIFEST["positive"]["root_enrollment"]["target"]["key_id"],
        registry=origin_registry,
        enabled=True,
    )
    return origin, target, origin_registry, target_registry, origin_ledger, target_ledger


def combined_registry() -> ValidatedFederationV1KeyRegistry:
    provenance = FIXTURES / "provenance"
    return ValidatedFederationV1KeyRegistry.from_provenance(
        [
            json.loads((provenance / "origin_root_enrollment.json").read_bytes()),
            json.loads((provenance / "target_root_enrollment.json").read_bytes()),
        ],
        [
            json.loads((provenance / "origin_signing_key_certificate.json").read_bytes()),
            json.loads((provenance / "target_signing_key_certificate.json").read_bytes()),
        ],
        now="2026-07-18T11:00:00Z",
    )


def resign(envelope: dict, key: Ed25519PrivateKey) -> bytes:
    body = {key_name: value for key_name, value in envelope.items() if key_name not in {"message_hash", "signature"}}
    message_hash = hashlib.sha256(canonical_bytes(body)).hexdigest()
    envelope = {**body, "message_hash": message_hash}
    signature_input = b"STEWARD-FEDERATION-DELEGATION-V1\x00" + bytes.fromhex(message_hash)
    envelope["signature"] = base64.b64encode(key.sign(signature_input)).decode("ascii")
    return canonical_bytes(envelope)


def test_admission_only_cross_repo_boundary_and_full_persistence(tmp_path: Path) -> None:
    origin, target, origin_registry, target_registry, origin_ledger, target_ledger = services(tmp_path)
    request_wire, request_carrier = origin.create(
        payload=semantic_payload(),
        target_node_id=MANIFEST["positive"]["request"]["target_node_id"],
        message_id=REQUEST["message_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    assert request_wire == (FIXTURES / "messages" / "delegate_task.json").read_bytes()
    receipt_carrier = target.handle(request_carrier, now="2026-07-18T11:01:00Z")
    assert receipt_carrier is not None
    receipt_record = target_ledger.get(REQUEST["payload"]["delegation_id"])
    assert receipt_record is not None
    for field in (
        "target_work_id",
        "receipt_message_id",
        "receipt_id",
        "receipt_content_digest",
        "receipt_message_hash",
        "receipt_signature",
        "receipt_wire_bytes_b64",
        "receipt_send_status",
    ):
        assert field in receipt_record
    assert receipt_record["state"] == "ACCEPTED"
    target_ledger.mark_receipt_sent(REQUEST["payload"]["delegation_id"])
    assert target_ledger.get(REQUEST["payload"]["delegation_id"])["receipt_send_status"] == "sent"
    applied = origin.apply_receipt(carrier=receipt_carrier, registry=target_registry, now="2026-07-18T11:01:00Z")
    assert applied["target_work_id"] == receipt_record["target_work_id"]
    assert (
        origin_ledger.get(REQUEST["payload"]["delegation_id"])["request_wire_bytes_b64"]
        == base64.b64encode(request_wire).decode()
    )
    assert origin.retransmit(REQUEST["payload"]["delegation_id"]) == request_carrier


def test_feature_gate_is_fail_closed_by_default(tmp_path: Path) -> None:
    origin, target, *_ = services(tmp_path)
    origin.enabled = False
    target.enabled = False
    with pytest.raises(V1Reject, match="feature_disabled"):
        origin.create(
            payload=semantic_payload(),
            target_node_id=REQUEST["target_node_id"],
            message_id=REQUEST["message_id"],
            issued_at="2026-07-18T11:00:00Z",
            expires_at="2026-07-18T11:05:00Z",
        )
    assert target.handle({}, now="2026-07-18T11:01:00Z") is None


def test_origin_create_is_idempotent_and_conflicts_are_persisted(tmp_path: Path) -> None:
    origin, *_ = services(tmp_path)
    first_wire, first_carrier = origin.create(
        payload=semantic_payload(),
        target_node_id=REQUEST["target_node_id"],
        message_id=REQUEST["message_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    second_wire, second_carrier = origin.create(
        payload=semantic_payload(),
        target_node_id=REQUEST["target_node_id"],
        message_id=REQUEST["message_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    assert (second_wire, second_carrier) == (first_wire, first_carrier)
    changed = copy.deepcopy(semantic_payload())
    changed["task_description"] = "different bounded repair"
    with pytest.raises(V1Reject, match="origin_request_conflict"):
        origin.create(
            payload=changed,
            target_node_id=REQUEST["target_node_id"],
            message_id=REQUEST["message_id"],
            issued_at="2026-07-18T11:00:00Z",
            expires_at="2026-07-18T11:05:00Z",
        )
    with pytest.raises(V1Reject, match="origin_request_conflict"):
        origin.create(
            payload=semantic_payload(),
            target_node_id=REQUEST["target_node_id"],
            message_id="msg_req_other",
            issued_at="2026-07-18T11:00:00Z",
            expires_at="2026-07-18T11:05:00Z",
        )
    record = origin.ledger.get(REQUEST["payload"]["delegation_id"])
    assert record["request_wire_bytes_b64"] == base64.b64encode(first_wire).decode()
    assert origin.ledger.path.read_text().count("origin_request_conflict") >= 1


@pytest.mark.parametrize("mutation", ["wrong_source", "correlation", "causation", "record_target"])
def test_receipt_binding_conflicts_are_id_based_and_persist_nothing(tmp_path: Path, mutation: str) -> None:
    origin, target, _, target_registry, origin_ledger, _ = services(tmp_path)
    _, request_carrier = origin.create(
        payload=semantic_payload(),
        target_node_id=REQUEST["target_node_id"],
        message_id=REQUEST["message_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    receipt_carrier = target.handle(request_carrier, now="2026-07-18T11:01:00Z")
    original = parse_canonical(base64.b64decode(receipt_carrier["payload"]["wire_bytes_b64"]))
    if mutation == "wrong_source":
        wrong = build_admission_receipt(
            request=REQUEST,
            target_node_id=REQUEST["source_node_id"],
            origin_node_id=REQUEST["source_node_id"],
            message_id="rcpt_wrong_source",
            receipt_id="receipt_wrong_source",
            target_work_id="work_wrong",
            status="accepted",
            reason_code=None,
            signing_key=private("origin_signing_key"),
            signer_key_b64=KEYS["origin_signing_key"]["public_key_b64"],
            key_id=MANIFEST["positive"]["request"]["origin_key_id"],
            issued_at="2026-07-18T11:01:00Z",
            expires_at="2026-07-18T11:06:00Z",
        )
    else:
        wrong = dict(original)
        if mutation == "correlation":
            wrong["correlation_id"] = "del_other"
        elif mutation == "causation":
            wrong["causation_message_id"] = "msg_other"
        else:
            record = json.loads(origin_ledger.path.read_text())
            record["delegations"][REQUEST["payload"]["delegation_id"]]["target_node_id"] = REQUEST["source_node_id"]
            origin_ledger.path.write_text(json.dumps(record))
        wrong = (
            resign(wrong, private("target_signing_key"))
            if mutation != "record_target"
            else receipt_carrier["payload"]["wire_bytes_b64"]
        )
    wrong_carrier = build_carrier(wrong) if mutation != "record_target" else receipt_carrier
    with pytest.raises(V1Reject, match="receipt_correlation_conflict"):
        origin.apply_receipt(carrier=wrong_carrier, registry=combined_registry(), now="2026-07-18T11:01:00Z")
    if mutation != "record_target":
        assert origin_ledger.get(REQUEST["payload"]["delegation_id"]).get("target_work_id") is None


def test_unvalidated_registry_and_provenance_mutations_fail_closed(tmp_path: Path) -> None:
    origin, target, origin_registry, *_ = services(tmp_path)
    with pytest.raises(V1Reject, match="registry_unvalidated"):
        validate_envelope(
            (FIXTURES / "messages" / "delegate_task.json").read_bytes(),
            registry={},
            expected_target=REQUEST["target_node_id"],
            now="2026-07-18T11:01:00Z",
        )
    provenance = FIXTURES / "provenance"
    enrollment = json.loads((provenance / "origin_root_enrollment.json").read_bytes())
    certificate = json.loads((provenance / "origin_signing_key_certificate.json").read_bytes())
    broken = copy.deepcopy(certificate)
    broken["key_id"] = "key_" + "0" * 64
    with pytest.raises(V1Reject, match="certificate_key_binding"):
        ValidatedFederationV1KeyRegistry.from_provenance([enrollment], [broken], now="2026-07-18T11:00:00Z")


@pytest.mark.parametrize(
    "mutation, expected",
    [
        ("wrong_node", "certificate_key_binding"),
        ("not_active", "certificate_time_window"),
        ("expired", "certificate_expired"),
    ],
)
def test_provenance_time_and_node_bindings_are_enforced(mutation: str, expected: str) -> None:
    provenance = FIXTURES / "provenance"
    enrollment = json.loads((provenance / "origin_root_enrollment.json").read_bytes())
    certificate = json.loads((provenance / "origin_signing_key_certificate.json").read_bytes())
    if mutation == "wrong_node":
        certificate["node_id"] = "ag_" + "0" * 32
    elif mutation == "not_active":
        certificate["not_before"] = "2027-07-18T00:05:00Z"
        certificate["activation_at"] = certificate["not_before"]
    else:
        certificate["not_after"] = "2026-07-18T10:00:00Z"
    with pytest.raises(V1Reject, match=expected):
        ValidatedFederationV1KeyRegistry.from_provenance([enrollment], [certificate], now="2026-07-18T11:00:00Z")


def test_revoked_key_is_rejected_at_message_validation_time() -> None:
    provenance = FIXTURES / "provenance"
    enrollment = json.loads((provenance / "origin_root_enrollment.json").read_bytes())
    certificate = json.loads((provenance / "origin_signing_key_certificate.json").read_bytes())
    certificate["revocation_ref"] = "operator-revocation-1"
    body = {key: value for key, value in certificate.items() if key != "root_signature"}
    digest = hashlib.sha256(canonical_bytes(body)).hexdigest()
    certificate["root_signature"] = base64.b64encode(
        private("origin_identity_root").sign(b"STEWARD-FEDERATION-SIGNING-KEY-AUTH-V1\x00" + bytes.fromhex(digest))
    ).decode()
    registry = ValidatedFederationV1KeyRegistry.from_provenance([enrollment], [certificate], now="2026-07-18T11:00:00Z")
    with pytest.raises(V1Reject, match="key_revoked"):
        registry.lookup(certificate["key_id"], at="2026-07-18T11:00:00Z")
    broken = copy.deepcopy(certificate)
    broken["root_signature"] = base64.b64encode(b"0" * 64).decode()
    with pytest.raises(V1Reject, match="provenance_signature_invalid"):
        ValidatedFederationV1KeyRegistry.from_provenance([enrollment], [broken], now="2026-07-18T11:00:00Z")


def test_corrupt_ledger_is_not_reset(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.json"
    path.write_text("{not-json")
    with pytest.raises(V1Reject, match="ledger_corrupt"):
        TargetAdmissionLedger(path).get("del_any")
    path.write_text(json.dumps({"delegations": {"del_any": {}}}))
    with pytest.raises(V1Reject, match="ledger_corrupt"):
        TargetAdmissionLedger(path).get("del_any")


def test_independent_ledger_instances_are_process_safe(tmp_path: Path) -> None:
    origin, target, *_ = services(tmp_path)
    _, carrier = origin.create(
        payload=semantic_payload(),
        target_node_id=REQUEST["target_node_id"],
        message_id=REQUEST["message_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    target_a = FederationV1Admission(
        ledger=TargetAdmissionLedger(tmp_path / "target.json"),
        node_id=target.node_id,
        signing_key=private("target_signing_key"),
        signer_key_b64=KEYS["target_signing_key"]["public_key_b64"],
        key_id=target.key_id,
        registry=target.registry,
        enabled=True,
    )
    target_b = FederationV1Admission(
        ledger=TargetAdmissionLedger(tmp_path / "target.json"),
        node_id=target.node_id,
        signing_key=private("target_signing_key"),
        signer_key_b64=KEYS["target_signing_key"]["public_key_b64"],
        key_id=target.key_id,
        registry=target.registry,
        enabled=True,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda service: service.handle(carrier, now="2026-07-18T11:01:00Z"), (target_a, target_b))
        )
    assert results[0] == results[1]
    assert len(target_a.ledger.path.read_text()) > 0
    assert len(target_a.ledger.get(REQUEST["payload"]["delegation_id"])) == len(
        target_b.ledger.get(REQUEST["payload"]["delegation_id"])
    )


def test_parallel_distinct_delegations_and_send_updates_do_not_overwrite(tmp_path: Path) -> None:
    origin, target, *_ = services(tmp_path)
    first_payload = semantic_payload()
    second_payload = copy.deepcopy(first_payload)
    second_payload["delegation_id"] = "del_parallel_0002"
    second_payload["origin_task_id"] = "task_parallel_0002"
    _, first_carrier = origin.create(
        payload=first_payload,
        target_node_id=REQUEST["target_node_id"],
        message_id=REQUEST["message_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    _, second_carrier = origin.create(
        payload=second_payload,
        target_node_id=REQUEST["target_node_id"],
        message_id="msg_req_parallel_0002",
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    targets = [
        FederationV1Admission(
            ledger=TargetAdmissionLedger(tmp_path / "target.json"),
            node_id=target.node_id,
            signing_key=private("target_signing_key"),
            signer_key_b64=KEYS["target_signing_key"]["public_key_b64"],
            key_id=target.key_id,
            registry=target.registry,
            enabled=True,
        )
        for _ in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                lambda pair: pair[0].handle(pair[1], now="2026-07-18T11:01:00Z"),
                zip(targets, (first_carrier, second_carrier)),
            )
        )
    ledger_a, ledger_b = (
        TargetAdmissionLedger(tmp_path / "target.json"),
        TargetAdmissionLedger(tmp_path / "target.json"),
    )
    ledger_a.mark_receipt_sent(first_payload["delegation_id"])
    ledger_b.mark_receipt_sent(second_payload["delegation_id"])
    assert ledger_a.get(first_payload["delegation_id"])["receipt_send_status"] == "sent"
    assert ledger_b.get(second_payload["delegation_id"])["receipt_send_status"] == "sent"


def test_crash_after_admission_commit_retransmits_identical_receipt(tmp_path: Path) -> None:
    origin, target, *_ = services(tmp_path)
    _, carrier = origin.create(
        payload=semantic_payload(),
        target_node_id=REQUEST["target_node_id"],
        message_id=REQUEST["message_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    first = target.handle(carrier, now="2026-07-18T11:01:00Z")
    second = target.handle(carrier, now="2026-07-18T11:01:00Z")
    assert first == second
    assert target.ledger.get(REQUEST["payload"]["delegation_id"])["target_work_id"]


def test_rejected_admission_is_durable_and_idempotent(tmp_path: Path) -> None:
    origin, target, *_ = services(tmp_path)
    _, carrier = origin.create(
        payload=semantic_payload(),
        target_node_id=REQUEST["target_node_id"],
        message_id=REQUEST["message_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    first = target.handle(carrier, now="2026-07-18T11:01:00Z", origin_authorized=False)
    second = target.handle(carrier, now="2026-07-18T11:01:00Z", origin_authorized=False)
    assert first == second
    record = target.ledger.get(REQUEST["payload"]["delegation_id"])
    assert record["state"] == "REJECTED" and record["target_work_id"] is None
    assert record["reason_code"] == "authority_denied"


def test_crash_before_admission_commit_leaves_no_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    origin, target, *_ = services(tmp_path)
    _, carrier = origin.create(
        payload=semantic_payload(),
        target_node_id=REQUEST["target_node_id"],
        message_id=REQUEST["message_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )

    def crash_before_commit(**_: object) -> tuple[str, dict]:
        raise RuntimeError("simulated crash before admission commit")

    monkeypatch.setattr(target.ledger, "commit", crash_before_commit)
    with pytest.raises(RuntimeError, match="before admission commit"):
        target.handle(carrier, now="2026-07-18T11:01:00Z")
    assert target.ledger.get(REQUEST["payload"]["delegation_id"]) is None


@pytest.mark.parametrize(
    "field, value", [("source", "ag_" + "1" * 32), ("target", "ag_" + "2" * 32), ("operation", "federation_v1.wrong")]
)
def test_carrier_mutation_is_quarantined_without_response(tmp_path: Path, field: str, value: str) -> None:
    origin, target, *_ = services(tmp_path)
    _, carrier = origin.create(
        payload=semantic_payload(),
        target_node_id=REQUEST["target_node_id"],
        message_id=REQUEST["message_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    mutated = dict(carrier)
    mutated[field] = value
    assert target.handle(mutated, now="2026-07-18T11:01:00Z") is None
    assert target.ledger.get(REQUEST["payload"]["delegation_id"]) is None


@pytest.mark.parametrize(
    "kind", ["unknown_top_level", "unknown_payload", "wrong_version", "invalid_b64", "wildcard_target"]
)
def test_closed_carrier_shape_mutations_are_quarantined(tmp_path: Path, kind: str) -> None:
    origin, target, *_ = services(tmp_path)
    _, carrier = origin.create(
        payload=semantic_payload(),
        target_node_id=REQUEST["target_node_id"],
        message_id=REQUEST["message_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    mutated = dict(carrier)
    if kind == "unknown_top_level":
        mutated["extra"] = "forbidden"
    elif kind == "unknown_payload":
        mutated["payload"] = {**carrier["payload"], "extra": "forbidden"}
    elif kind == "wrong_version":
        mutated["payload"] = {**carrier["payload"], "wire_version": "legacy"}
    elif kind == "invalid_b64":
        mutated["payload"] = {**carrier["payload"], "wire_bytes_b64": "!!!="}
    else:
        mutated["target"] = "ag_" + "0" * 32
    assert target.handle(mutated, now="2026-07-18T11:01:00Z") is None
    assert target.ledger.get(REQUEST["payload"]["delegation_id"]) is None


def test_first_set_target_work_id_and_conflict(tmp_path: Path) -> None:
    origin, target, _, target_registry, origin_ledger, _ = services(tmp_path)
    _, carrier = origin.create(
        payload=semantic_payload(),
        target_node_id=REQUEST["target_node_id"],
        message_id=REQUEST["message_id"],
        issued_at="2026-07-18T11:00:00Z",
        expires_at="2026-07-18T11:05:00Z",
    )
    receipt_carrier = target.handle(carrier, now="2026-07-18T11:01:00Z")
    origin.apply_receipt(carrier=receipt_carrier, registry=target_registry, now="2026-07-18T11:01:00Z")
    conflict_wire = build_admission_receipt(
        request=REQUEST,
        target_node_id=REQUEST["target_node_id"],
        origin_node_id=REQUEST["source_node_id"],
        message_id="rcpt_conflict_0001",
        receipt_id="receipt_conflict_0001",
        target_work_id="work_other",
        status="accepted",
        reason_code=None,
        signing_key=private("target_signing_key"),
        signer_key_b64=KEYS["target_signing_key"]["public_key_b64"],
        key_id=MANIFEST["positive"]["root_enrollment"]["target"]["key_id"],
        issued_at="2026-07-18T11:01:00Z",
        expires_at="2026-07-18T11:06:00Z",
    )
    with pytest.raises(V1Reject) as exc:
        origin.apply_receipt(carrier=build_carrier(conflict_wire), registry=target_registry, now="2026-07-18T11:01:00Z")
    assert exc.value.code == "receipt_ledger_conflict"


@pytest.mark.parametrize(
    "case",
    [case for case in MANIFEST["negative"] if case["id"] not in {"expired_certificate", "revoked_certificate"}],
    ids=lambda case: case["id"],
)
def test_all_negative_request_boundaries_are_quarantined(case: dict, tmp_path: Path) -> None:
    origin, target, *_ = services(tmp_path)
    if case["id"] in {"same_delegation_different_digest", "same_message_id_different_bytes"}:
        _, positive_carrier = origin.create(
            payload=semantic_payload(),
            target_node_id=REQUEST["target_node_id"],
            message_id=REQUEST["message_id"],
            issued_at="2026-07-18T11:00:00Z",
            expires_at="2026-07-18T11:05:00Z",
        )
        assert target.handle(positive_carrier, now="2026-07-18T11:01:00Z") is not None
    raw = (FIXTURES / case["path"]).read_bytes()
    carrier = {
        "operation": "federation_v1.delegate_task",
        "source": REQUEST["source_node_id"],
        "target": REQUEST["target_node_id"],
        "payload": {
            "wire_version": "federation-delegation-v1",
            "wire_bytes_b64": base64.b64encode(raw).decode("ascii"),
        },
    }
    assert target.handle(carrier, now="2026-07-18T11:01:00Z") is None
    if case["id"] in {"same_delegation_different_digest", "same_message_id_different_bytes"}:
        assert target.ledger.get(REQUEST["payload"]["delegation_id"]) is not None
    else:
        assert target.ledger.get(REQUEST["payload"]["delegation_id"]) is None
