"""Admission-only cross-repository crucible for Federation Delegation V1.

The test loads the two repo-local production adapters independently.  It is skipped when
the Agent City checkout is not available; CI can provide ``AGENT_CITY_REPO`` explicitly.
"""

from __future__ import annotations

import base64
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

from steward.federation_v1 import FederationV1Origin, OriginDelegationLedger

ROOT = Path(__file__).parent / "fixtures" / "federation_v1"
MANIFEST = json.loads((ROOT / "manifest.json").read_bytes())
KEYS = json.loads((ROOT / "keys" / "test_keys.json").read_bytes())
REQUEST = json.loads((ROOT / "messages" / "delegate_task.json").read_bytes())


def _private(label: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(KEYS[label]["private_seed_hex"]))


def _public(label: str) -> bytes:
    return base64.b64decode(KEYS[label]["public_key_b64"], validate=True)


@pytest.mark.skipif(not os.environ.get("AGENT_CITY_REPO"), reason="requires the separate Agent City checkout")
def test_admission_only_cross_repo_crucible(tmp_path: Path) -> None:
    city_root = Path(os.environ["AGENT_CITY_REPO"]).resolve()
    if not (city_root / "city" / "federation_v1.py").exists():
        pytest.skip("AGENT_CITY_REPO has no V1 adapter")
    sys.path.insert(0, str(city_root))
    city_v1 = importlib.import_module("city.federation_v1")
    try:
        origin_node = MANIFEST["positive"]["request"]["origin_node_id"]
        target_node = MANIFEST["positive"]["request"]["target_node_id"]
        origin_key_id = MANIFEST["positive"]["request"]["origin_key_id"]
        target_key_id = MANIFEST["positive"]["root_enrollment"]["target"]["key_id"]
        origin_registry = {origin_key_id: {"node_id": origin_node, "public_key": _public("origin_signing_key")}}
        target_registry = {target_key_id: {"node_id": target_node, "public_key": _public("target_signing_key")}}
        payload = {key: value for key, value in REQUEST["payload"].items() if key not in {"request_digest", "idempotency_key"}}
        origin = FederationV1Origin(ledger=OriginDelegationLedger(tmp_path / "origin.json"), node_id=origin_node, signing_key=_private("origin_signing_key"), signer_key_b64=KEYS["origin_signing_key"]["public_key_b64"], key_id=origin_key_id, enabled=True)
        target = city_v1.FederationV1Admission(ledger=city_v1.TargetAdmissionLedger(tmp_path / "target.json"), node_id=target_node, signing_key=_private("target_signing_key"), signer_key_b64=KEYS["target_signing_key"]["public_key_b64"], key_id=target_key_id, registry=origin_registry, enabled=True)
        request_wire, request_carrier = origin.create(payload=payload, target_node_id=target_node, message_id=REQUEST["message_id"], issued_at="2026-07-18T11:00:00Z", expires_at="2026-07-18T11:05:00Z")
        assert request_wire == (ROOT / "messages" / "delegate_task.json").read_bytes()
        receipt_carrier = target.handle(request_carrier, now="2026-07-18T11:01:00Z")
        assert receipt_carrier is not None
        applied = origin.apply_receipt(carrier=receipt_carrier, registry=target_registry, now="2026-07-18T11:01:00Z")
        assert applied["target_work_id"]
        assert target.ledger.get(REQUEST["payload"]["delegation_id"])["state"] == "ACCEPTED"
        assert target.handle(request_carrier, now="2026-07-18T11:01:00Z") == receipt_carrier
        assert target.ledger.get(REQUEST["payload"]["delegation_id"])["target_work_id"] == applied["target_work_id"]
    finally:
        sys.path.remove(str(city_root))
