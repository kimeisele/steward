"""Pure rendering and artifact contracts for Context Bridge Feature 01."""

from __future__ import annotations

import ast
import builtins
import hashlib
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from steward.context_contract import ContractViolation, OutputMode, canonical_json_bytes, consumer_output_hash
from steward.context_rendering import (
    PublicationCandidates,
    build_publication_candidates,
    validate_persisted_generation,
    validate_publication_candidates,
)


@pytest.fixture
def models():
    path = Path("specs/context_bridge_evidence/FEATURE_04_HASH_VECTORS.json")
    vector = json.loads(path.read_text())
    return vector["payload"]["model"], vector["snapshot"]["model"]


@pytest.fixture
def expected():
    path = Path("specs/context_bridge_evidence/FEATURE_01_PUBLICATION_VECTORS.json")
    return json.loads(path.read_text())


@pytest.fixture
def detached_candidates(models):
    payload, snapshot = models
    built = build_publication_candidates(payload, snapshot)
    return PublicationCandidates(
        claude_md=bytes(bytearray(built.claude_md)),
        agents_md=bytes(bytearray(built.agents_md)),
        snapshot_artifact=bytes(bytearray(built.snapshot_artifact)),
        publication_artifact=bytes(bytearray(built.publication_artifact)),
    )


def test_golden_generation_is_exact_and_byte_identical(models, expected):
    payload, snapshot = models
    candidates = build_publication_candidates(payload, snapshot)

    assert isinstance(candidates, PublicationCandidates)
    assert candidates.agents_md is candidates.claude_md
    assert len(candidates.claude_md) == expected["renderer"]["expected_utf8_bytes"]
    assert consumer_output_hash(candidates.claude_md) == expected["renderer"]["expected_consumer_output_sha256"]
    assert len(candidates.snapshot_artifact) == expected["snapshot_artifact"]["expected_canonical_utf8_bytes"]
    assert len(candidates.publication_artifact) == expected["publication_artifact"]["expected_canonical_utf8_bytes"]
    validate_publication_candidates(payload, snapshot, candidates)


def test_root_has_exact_structure_and_whitespace(models):
    payload, snapshot = models
    root = build_publication_candidates(payload, snapshot).claude_md
    text = root.decode("utf-8")

    assert root.endswith(b"\n") and not root.endswith(b"\n\n")
    assert b"\r" not in root and not root.startswith(b"\xef\xbb\xbf")
    assert all(not line.endswith(" ") for line in text.splitlines())
    for marker in (
        "<!-- steward-context:c0:v1:begin -->",
        "<!-- steward-context:c0:v1:end -->",
        "<!-- steward-context:dynamic:v1:begin -->",
        "<!-- steward-context:dynamic:v1:end -->",
        "<!-- steward-context:orientation:v1:begin -->",
        "<!-- steward-context:orientation:v1:end -->",
    ):
        assert text.count(marker) == 1
    assert "publication time" not in text.lower()
    assert "consumer output hash" not in text.lower()


def test_snapshot_and_publication_envelopes_are_bound(models, expected):
    payload, snapshot = models
    candidates = build_publication_candidates(payload, snapshot)
    snapshot_artifact = json.loads(candidates.snapshot_artifact)
    publication = json.loads(candidates.publication_artifact)

    assert not candidates.snapshot_artifact.endswith(b"\n")
    assert not candidates.publication_artifact.endswith(b"\n")
    assert snapshot_artifact["snapshot"] == snapshot
    assert snapshot_artifact["snapshot_id"] == expected["publication_artifact"]["expected_snapshot_id"]
    assert publication["previous"]["payload_hash"] == expected["publication_artifact"]["expected_payload_hash"]
    assert publication["previous"]["consumer_outputs"] == expected["publication_artifact"]["expected_consumer_outputs"]
    assert publication["targets"] == expected["publication_artifact"]["expected_targets"]
    artifact_hash = hashlib.sha256(b"steward-context-snapshot-artifact-v1\0" + candidates.snapshot_artifact).hexdigest()
    assert artifact_hash == expected["publication_artifact"]["expected_snapshot_artifact_hash"]
    assert publication["snapshot_artifact_hash"] == artifact_hash
    assert "publication_hash" not in publication


def test_nonempty_orientation_is_rendered_verbatim(models):
    payload, snapshot = models
    orientation = "## Code Map\n\nVerified orientation.\n"
    payload["contract"]["orientation"] = orientation
    payload["contract"]["orientation_sha256"] = hashlib.sha256(orientation.encode()).hexdigest()
    snapshot["orientation"]["sha256"] = payload["contract"]["orientation_sha256"]

    text = build_publication_candidates(payload, snapshot).claude_md.decode()

    assert f"<!-- steward-context:orientation:v1:begin -->\n{orientation}" in text


def test_cross_model_mismatch_and_preview_block(models):
    payload, snapshot = models
    mismatched = deepcopy(snapshot)
    mismatched["constitution"]["sha256"] = "0" * 64
    with pytest.raises(ContractViolation):
        build_publication_candidates(payload, mismatched)

    payload["mode"] = "preview"
    with pytest.raises(ContractViolation) as exc_info:
        build_publication_candidates(payload, snapshot)
    assert exc_info.value.code == "invalid_value"


def test_candidate_mutation_is_detected_and_container_is_frozen(models):
    payload, snapshot = models
    candidates = build_publication_candidates(payload, snapshot)
    mutated = replace(candidates, agents_md=b"tampered")

    class CandidateSubclass(PublicationCandidates):
        pass

    with pytest.raises(ContractViolation):
        validate_publication_candidates(payload, snapshot, mutated)
    with pytest.raises(ContractViolation) as exc_info:
        validate_publication_candidates(payload, snapshot, CandidateSubclass(**candidates.__dict__))
    assert exc_info.value.code == "invalid_type"
    with pytest.raises(FrozenInstanceError):
        candidates.claude_md = b"tampered"  # type: ignore[misc]


def test_build_is_pure(models, monkeypatch):
    payload, snapshot = models

    def forbidden(*args, **kwargs):
        raise AssertionError("I/O or clock access is forbidden")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr("pathlib.Path.open", forbidden)
        patch.setattr("subprocess.run", forbidden)
        patch.setattr("time.time", forbidden)

        build_publication_candidates(payload, snapshot)


def test_module_imports_are_pure_and_fixture_free():
    source = Path("steward/context_rendering.py").read_text()
    tree = ast.parse(source)
    imported_names = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    imported_modules = {
        node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not (imported_names | imported_modules) & {"datetime", "os", "pathlib", "socket", "subprocess", "time"}
    assert "ServiceRegistry" not in source
    assert "assemble_context" not in source
    assert "specs/" not in source


def test_persisted_generation_accepts_separately_read_equal_roots(detached_candidates, expected):
    assert detached_candidates.claude_md == detached_candidates.agents_md
    assert detached_candidates.claude_md is not detached_candidates.agents_md

    previous = validate_persisted_generation(detached_candidates)

    assert previous.payload_hash == expected["publication_artifact"]["expected_payload_hash"]
    assert previous.snapshot_id == expected["publication_artifact"]["expected_snapshot_id"]
    assert previous.mode is OutputMode.CANONICAL


def test_persisted_generation_accepts_nullable_comparison_state(models):
    payload, snapshot = models
    snapshot["comparison_state"] = {
        "gateway_errors_total": None,
        "gateway_rejected_parse_total": 1,
        "gateway_rejected_validate_total": None,
        "immune_rollbacks_total": 2,
    }
    built = build_publication_candidates(payload, snapshot)
    detached = PublicationCandidates(
        claude_md=bytes(bytearray(built.claude_md)),
        agents_md=bytes(bytearray(built.agents_md)),
        snapshot_artifact=bytes(bytearray(built.snapshot_artifact)),
        publication_artifact=bytes(bytearray(built.publication_artifact)),
    )

    previous = validate_persisted_generation(detached)

    assert dict(previous.comparison_state) == snapshot["comparison_state"]


def test_publication_artifact_bytes_alone_are_not_a_trusted_record(detached_candidates):
    with pytest.raises(ContractViolation) as exc_info:
        validate_persisted_generation(detached_candidates.publication_artifact)  # type: ignore[arg-type]
    assert exc_info.value.code == "invalid_type"


@pytest.mark.parametrize("field", PublicationCandidates.__dataclass_fields__)
def test_each_persisted_artifact_tamper_blocks(detached_candidates, field):
    tampered = replace(detached_candidates, **{field: getattr(detached_candidates, field) + b"x"})
    with pytest.raises(ContractViolation):
        validate_persisted_generation(tampered)


def test_distinct_root_bytes_block(detached_candidates):
    tampered = replace(detached_candidates, agents_md=detached_candidates.agents_md.replace(b"Steward", b"steward", 1))
    with pytest.raises(ContractViolation) as exc_info:
        validate_persisted_generation(tampered)
    assert exc_info.value.code == "inconsistent"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda root: b"prefix\n" + root,
        lambda root: root + b"\n",
        lambda root: root.replace(b"<!-- steward-context:dynamic:v1:end -->", b"", 1),
        lambda root: root.replace(b"### Observations", b"### Injected\n\n### Observations", 1),
        lambda root: root[:-1],
    ],
)
def test_root_structure_tamper_blocks(detached_candidates, mutation):
    root = mutation(detached_candidates.claude_md)
    tampered = replace(detached_candidates, claude_md=root, agents_md=bytes(bytearray(root)))
    with pytest.raises(ContractViolation):
        validate_persisted_generation(tampered)


def test_snapshot_and_publication_cross_binding_tamper_blocks(detached_candidates):
    snapshot_artifact = json.loads(detached_candidates.snapshot_artifact)
    snapshot_artifact["snapshot"]["comparison_state"]["gateway_errors_total"] = None
    tampered_snapshot = canonical_json_bytes(snapshot_artifact)
    with pytest.raises(ContractViolation):
        validate_persisted_generation(replace(detached_candidates, snapshot_artifact=tampered_snapshot))

    publication = json.loads(detached_candidates.publication_artifact)
    publication["previous"]["comparison_state"]["gateway_errors_total"] = None
    tampered_publication = canonical_json_bytes(publication)
    with pytest.raises(ContractViolation):
        validate_persisted_generation(replace(detached_candidates, publication_artifact=tampered_publication))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unknown": True}),
        lambda value: value["previous"].update({"unknown": True}),
        lambda value: value["targets"].update({"agents": "agents.md"}),
        lambda value: value["previous"].update({"payload_hash": "0" * 64}),
        lambda value: value["previous"].update({"c0_sha256": "0" * 64}),
        lambda value: value["previous"]["consumer_outputs"].update({"agents": "0" * 64}),
        lambda value: value["previous"].update({"mode": 1}),
        lambda value: value.update({"repository_head": "0" * 40}),
        lambda value: value.update({"generator_commit": "0" * 40}),
        lambda value: value["constitution"].update({"source_blob": "0" * 40}),
    ],
)
def test_publication_schema_provenance_and_hash_tamper_blocks(detached_candidates, mutation):
    publication = json.loads(detached_candidates.publication_artifact)
    mutation(publication)
    tampered = canonical_json_bytes(publication)

    with pytest.raises(ContractViolation):
        validate_persisted_generation(replace(detached_candidates, publication_artifact=tampered))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unknown": True}),
        lambda value: value.update({"snapshot_id": "ctxsnap-v1:" + ("0" * 64)}),
        lambda value: value.update({"snapshot_hash": "0" * 64}),
        lambda value: value["snapshot"]["orientation"].update({"sha256": "0" * 64}),
    ],
)
def test_snapshot_schema_and_hash_tamper_blocks(detached_candidates, mutation):
    snapshot = json.loads(detached_candidates.snapshot_artifact)
    mutation(snapshot)
    tampered = canonical_json_bytes(snapshot)

    with pytest.raises(ContractViolation):
        validate_persisted_generation(replace(detached_candidates, snapshot_artifact=tampered))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"Repository head: `1111111111111111111111111111111111111111`", b"Repository head: `" + b"0" * 40 + b"`"),
        (b'"provider":"healthy"', b'"provider":"unknown"'),
        (b'"status":"empty"', b'"status":"valid"'),
    ],
)
def test_dynamic_provenance_and_observation_tamper_blocks(detached_candidates, old, new):
    assert old in detached_candidates.claude_md
    root = detached_candidates.claude_md.replace(old, new, 1)
    tampered = replace(detached_candidates, claude_md=root, agents_md=bytes(bytearray(root)))

    with pytest.raises(ContractViolation):
        validate_persisted_generation(tampered)


@pytest.mark.parametrize(
    ("field", "bad_bytes"),
    [
        ("claude_md", b"x" * 65_537),
        ("agents_md", b"x" * 65_537),
        ("snapshot_artifact", b"x" * 131_073),
        ("publication_artifact", b"x" * 16_385),
        ("snapshot_artifact", b"\xef\xbb\xbf{}"),
        ("snapshot_artifact", b"\xff"),
        ("snapshot_artifact", b'{"schema":NaN}'),
        ("snapshot_artifact", b'{"schema":"x","schema":"x"}'),
        ("snapshot_artifact", b'{ "schema": "x" }'),
    ],
)
def test_persisted_input_boundaries_and_noncanonical_json_block(detached_candidates, field, bad_bytes):
    with pytest.raises(ContractViolation):
        validate_persisted_generation(replace(detached_candidates, **{field: bad_bytes}))
