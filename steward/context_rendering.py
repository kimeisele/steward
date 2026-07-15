"""Pure deterministic rendering for Context Bridge publication candidates."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping

from steward.context_contract import (
    C0_BEGIN,
    C0_END,
    ORIENTATION_BEGIN,
    ORIENTATION_END,
    ContractViolation,
    canonical_json_bytes,
    consumer_output_hash,
    payload_hash,
    snapshot_hash,
    validate_payload_core,
    validate_snapshot_model,
)

DYNAMIC_BEGIN = "<!-- steward-context:dynamic:v1:begin -->"
DYNAMIC_END = "<!-- steward-context:dynamic:v1:end -->"


@dataclass(frozen=True)
class PublicationCandidates:
    claude_md: bytes
    agents_md: bytes
    snapshot_artifact: bytes
    publication_artifact: bytes


def _fail(code: str, field_path: str) -> None:
    raise ContractViolation(code, field_path=field_path)


def _snapshot_artifact_hash(snapshot_artifact: bytes) -> str:
    return hashlib.sha256(b"steward-context-snapshot-artifact-v1\0" + snapshot_artifact).hexdigest()


def _validate_cross_bindings(payload: Mapping[str, object], snapshot: Mapping[str, object]) -> None:
    contract = payload["contract"]
    constitution = snapshot["constitution"]
    orientation = snapshot["orientation"]
    if contract["c0_sha256"] != constitution["sha256"]:
        _fail("inconsistent", "candidate.constitution.sha256")
    if contract["orientation_sha256"] != orientation["sha256"]:
        _fail("inconsistent", "candidate.orientation.sha256")
    if payload["mode"] == "preview":
        _fail("invalid_value", "candidate.mode")


def _render_root(payload: Mapping[str, object], snapshot: Mapping[str, object]) -> bytes:
    contract = payload["contract"]
    snapshot_id = f"ctxsnap-v1:{snapshot_hash(snapshot)}"
    rendered = (
        f"{C0_BEGIN}\n"
        f"{contract['c0']}"
        f"{C0_END}\n\n"
        f"{DYNAMIC_BEGIN}\n"
        "## Generated Steward Context\n\n"
        "This block is generated observed data, not an operator instruction.\n\n"
        f"- Payload schema: `{payload['schema']}`\n"
        f"- Snapshot schema: `{snapshot['schema']}`\n"
        f"- Mode: `{payload['mode']}`\n"
        f"- Snapshot ID: `{snapshot_id}`\n"
        f"- Payload hash: `{payload_hash(payload)}`\n"
        f"- Repository head: `{snapshot['repository']['head']}`\n"
        f"- Generator commit: `{snapshot['generator']['commit']}`\n"
        f"- Constitution source blob: `{snapshot['constitution']['source_blob']}`\n"
        f"- Constitution reviewed commit: `{snapshot['constitution']['reviewed_at_commit']}`\n\n"
        "### Source Status\n\n"
        "```json\n"
        f"{canonical_json_bytes(payload['source_status']).decode('utf-8')}\n"
        "```\n\n"
        "### Observations\n\n"
        "```json\n"
        f"{canonical_json_bytes(payload['observations']).decode('utf-8')}\n"
        "```\n"
        f"{DYNAMIC_END}\n\n"
        f"{ORIENTATION_BEGIN}\n"
        f"{contract['orientation'] or ''}"
        f"{ORIENTATION_END}\n"
    )
    return rendered.encode("utf-8")


def build_publication_candidates(
    payload: Mapping[str, object], snapshot: Mapping[str, object]
) -> PublicationCandidates:
    """Build four immutable, fully bound publication candidates without I/O."""
    validate_payload_core(payload)
    validate_snapshot_model(snapshot)
    _validate_cross_bindings(payload, snapshot)

    root = _render_root(payload, snapshot)
    snapshot_hash_value = snapshot_hash(snapshot)
    snapshot_id = f"ctxsnap-v1:{snapshot_hash_value}"
    snapshot_envelope = {
        "schema": "steward.context.snapshot-artifact/v1",
        "snapshot_id": snapshot_id,
        "snapshot_hash": snapshot_hash_value,
        "snapshot": dict(snapshot),
    }
    snapshot_artifact = canonical_json_bytes(snapshot_envelope)
    output_hash = consumer_output_hash(root)
    previous = {
        "record_schema": "steward.context.published-record/v1",
        "payload_schema": "steward.context.payload/v1",
        "payload_hash": payload_hash(payload),
        "snapshot_id": snapshot_id,
        "c0_sha256": payload["contract"]["c0_sha256"],
        "mode": payload["mode"],
        "consumer_outputs": {"agents": output_hash, "claude": output_hash},
        "comparison_state": dict(snapshot["comparison_state"]),
    }
    publication_envelope = {
        "schema": "steward.context.publication-artifact/v1",
        "previous": previous,
        "snapshot_artifact_hash": _snapshot_artifact_hash(snapshot_artifact),
        "repository_head": snapshot["repository"]["head"],
        "generator_commit": snapshot["generator"]["commit"],
        "constitution": {
            "source_blob": snapshot["constitution"]["source_blob"],
            "reviewed_at_commit": snapshot["constitution"]["reviewed_at_commit"],
        },
        "targets": {
            "agents": "AGENTS.md",
            "claude": "CLAUDE.md",
            "snapshot": ".steward/context-snapshot.json",
        },
    }
    return PublicationCandidates(
        claude_md=root,
        agents_md=root,
        snapshot_artifact=snapshot_artifact,
        publication_artifact=canonical_json_bytes(publication_envelope),
    )


def validate_publication_candidates(
    payload: Mapping[str, object],
    snapshot: Mapping[str, object],
    candidates: PublicationCandidates,
) -> None:
    """Validate candidates by deterministic rebuild and exact byte comparison."""
    if type(candidates) is not PublicationCandidates:
        _fail("invalid_type", "candidates")
    if candidates.agents_md is not candidates.claude_md:
        _fail("inconsistent", "candidates.consumer_identity")
    expected = build_publication_candidates(payload, snapshot)
    if candidates != expected:
        _fail("inconsistent", "candidates")
