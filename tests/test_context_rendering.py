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

from steward.context_contract import ContractViolation, consumer_output_hash
from steward.context_rendering import (
    PublicationCandidates,
    build_publication_candidates,
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
