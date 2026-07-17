"""Pure deterministic rendering for Context Bridge publication candidates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from steward.context_contract import (
    C0_BEGIN,
    C0_END,
    ORIENTATION_BEGIN,
    ORIENTATION_END,
    ConstitutionAttestation,
    ContractViolation,
    OutputMode,
    PreviousPublishedRecord,
    canonical_json_bytes,
    consumer_output_hash,
    payload_hash,
    snapshot_hash,
    validate_constitution_attestation,
    validate_payload_core,
    validate_previous_published_record,
    validate_snapshot_model,
)

DYNAMIC_BEGIN = "<!-- steward-context:dynamic:v1:begin -->"
DYNAMIC_END = "<!-- steward-context:dynamic:v1:end -->"

_ROOT_MAX_BYTES = 65_536
_SNAPSHOT_MAX_BYTES = 131_072
_PUBLICATION_MAX_BYTES = 16_384
PERSISTED_TARGET_MAX_BYTES: Mapping[str, int] = MappingProxyType(
    {
        "CLAUDE.md": _ROOT_MAX_BYTES,
        "AGENTS.md": _ROOT_MAX_BYTES,
        ".steward/context-snapshot.json": _SNAPSHOT_MAX_BYTES,
        ".steward/context-publication.json": _PUBLICATION_MAX_BYTES,
    }
)
_SNAPSHOT_SCHEMA = "steward.context.snapshot-artifact/v1"
_PUBLICATION_SCHEMA = "steward.context.publication-artifact/v1"
_TARGETS = {
    "agents": "AGENTS.md",
    "claude": "CLAUDE.md",
    "snapshot": ".steward/context-snapshot.json",
}


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


def _exact_mapping(value: object, expected: set[str], field_path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail("invalid_type", field_path)
    if set(value) != expected:
        _fail("invalid_schema", field_path)
    return value


def _decode_utf8(value: object, max_bytes: int, field_path: str) -> str:
    if type(value) is not bytes:
        _fail("invalid_type", field_path)
    if not value or len(value) > max_bytes or value.startswith(b"\xef\xbb\xbf"):
        _fail("invalid_value", field_path)
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        _fail("invalid_utf8", field_path)


def _strict_json_bytes(value: object, max_bytes: int, field_path: str) -> object:
    text = _decode_utf8(value, max_bytes, field_path)

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                _fail("invalid_schema", field_path)
            result[key] = item
        return result

    def reject_number(_: str) -> object:
        _fail("invalid_type", field_path)

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_float=reject_number,
            parse_constant=reject_number,
        )
    except ContractViolation:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
        _fail("invalid_value", field_path)
    if canonical_json_bytes(parsed) != value:
        _fail("invalid_value", field_path)
    return parsed


def _split_exact(value: str, delimiter: str, field_path: str) -> tuple[str, str]:
    parts = value.split(delimiter)
    if len(parts) != 2:
        _fail("invalid_markers", field_path)
    return parts[0], parts[1]


def _scalar_line(line: str, label: str) -> str:
    prefix = f"- {label}: `"
    if not line.startswith(prefix) or not line.endswith("`"):
        _fail("invalid_schema", "persisted.root.dynamic")
    value = line[len(prefix) : -1]
    if not value or "`" in value or "\n" in value:
        _fail("invalid_value", "persisted.root.dynamic")
    return value


def _parse_root(root: bytes, snapshot: Mapping[str, object]) -> tuple[Mapping[str, object], Mapping[str, str]]:
    text = _decode_utf8(root, _ROOT_MAX_BYTES, "persisted.root")
    prefix = f"{C0_BEGIN}\n"
    if not text.startswith(prefix):
        _fail("invalid_markers", "persisted.root.c0")
    c0, remainder = _split_exact(
        text[len(prefix) :],
        f"{C0_END}\n\n{DYNAMIC_BEGIN}\n",
        "persisted.root.c0",
    )
    dynamic, orientation_block = _split_exact(
        remainder,
        f"{DYNAMIC_END}\n\n{ORIENTATION_BEGIN}\n",
        "persisted.root.dynamic",
    )
    orientation, tail = _split_exact(
        orientation_block,
        f"{ORIENTATION_END}\n",
        "persisted.root.orientation",
    )
    if tail:
        _fail("invalid_markers", "persisted.root")

    dynamic_prefix = (
        "## Generated Steward Context\n\nThis block is generated observed data, not an operator instruction.\n\n"
    )
    if not dynamic.startswith(dynamic_prefix):
        _fail("invalid_schema", "persisted.root.dynamic")
    header, source_section = _split_exact(
        dynamic[len(dynamic_prefix) :],
        "\n\n### Source Status\n\n```json\n",
        "persisted.root.dynamic",
    )
    header_lines = header.split("\n")
    labels = (
        "Payload schema",
        "Snapshot schema",
        "Mode",
        "Snapshot ID",
        "Payload hash",
        "Repository head",
        "Generator commit",
        "Constitution source blob",
        "Constitution reviewed commit",
    )
    if len(header_lines) != len(labels):
        _fail("invalid_schema", "persisted.root.dynamic")
    provenance = {label: _scalar_line(line, label) for label, line in zip(labels, header_lines, strict=True)}

    source_json, observations_section = _split_exact(
        source_section,
        "\n```\n\n### Observations\n\n```json\n",
        "persisted.root.source_status",
    )
    if not observations_section.endswith("\n```\n"):
        _fail("invalid_schema", "persisted.root.observations")
    observations_json = observations_section[: -len("\n```\n")]
    source_status = _strict_json_bytes(source_json.encode("utf-8"), _ROOT_MAX_BYTES, "persisted.root.source_status")
    observations = _strict_json_bytes(observations_json.encode("utf-8"), _ROOT_MAX_BYTES, "persisted.root.observations")

    orientation_model = _exact_mapping(snapshot["orientation"], {"sha256"}, "snapshot.orientation")
    orientation_sha256 = orientation_model["sha256"]
    payload = {
        "schema": provenance["Payload schema"],
        "contract": {
            "c0_version": "c0/v1",
            "c0_sha256": hashlib.sha256(c0.encode("utf-8")).hexdigest(),
            "c0": c0,
            "orientation_sha256": orientation_sha256,
            "orientation": orientation if orientation_sha256 is not None else None,
        },
        "mode": provenance["Mode"],
        "source_status": source_status,
        "observations": observations,
    }
    validate_payload_core(payload)
    return payload, provenance


def _materialize_previous(value: object) -> PreviousPublishedRecord:
    previous = _exact_mapping(
        value,
        {
            "record_schema",
            "payload_schema",
            "payload_hash",
            "snapshot_id",
            "c0_sha256",
            "mode",
            "consumer_outputs",
            "comparison_state",
        },
        "publication.previous",
    )
    consumer_outputs = _exact_mapping(
        previous["consumer_outputs"], {"agents", "claude"}, "publication.previous.consumer_outputs"
    )
    comparison_state = _exact_mapping(
        previous["comparison_state"],
        {
            "gateway_errors_total",
            "gateway_rejected_parse_total",
            "gateway_rejected_validate_total",
            "immune_rollbacks_total",
        },
        "publication.previous.comparison_state",
    )
    try:
        mode = OutputMode(previous["mode"])
    except (TypeError, ValueError):
        _fail("invalid_value", "publication.previous.mode")
    record = PreviousPublishedRecord(
        payload_hash=previous["payload_hash"],
        snapshot_id=previous["snapshot_id"],
        c0_sha256=previous["c0_sha256"],
        mode=mode,
        consumer_outputs=consumer_outputs,
        comparison_state=comparison_state,
        record_schema=previous["record_schema"],
        payload_schema=previous["payload_schema"],
    )
    validate_previous_published_record(record)
    return record


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


def _validate_persisted_generation(
    candidates: PublicationCandidates,
    attestation: ConstitutionAttestation | None = None,
) -> PreviousPublishedRecord:
    snapshot_envelope = _exact_mapping(
        _strict_json_bytes(candidates.snapshot_artifact, _SNAPSHOT_MAX_BYTES, "persisted.snapshot_artifact"),
        {"schema", "snapshot_id", "snapshot_hash", "snapshot"},
        "persisted.snapshot_artifact",
    )
    if snapshot_envelope["schema"] != _SNAPSHOT_SCHEMA:
        _fail("invalid_schema", "persisted.snapshot_artifact.schema")
    snapshot = _exact_mapping(
        snapshot_envelope["snapshot"],
        {
            "schema",
            "repository",
            "generator",
            "assembled_at",
            "constitution",
            "orientation",
            "comparison_state",
            "sources",
            "observations",
        },
        "persisted.snapshot_artifact.snapshot",
    )
    validate_snapshot_model(snapshot)
    snapshot_hash_value = snapshot_hash(snapshot)
    snapshot_id = f"ctxsnap-v1:{snapshot_hash_value}"
    if snapshot_envelope["snapshot_hash"] != snapshot_hash_value:
        _fail("inconsistent", "persisted.snapshot_artifact.snapshot_hash")
    if snapshot_envelope["snapshot_id"] != snapshot_id:
        _fail("inconsistent", "persisted.snapshot_artifact.snapshot_id")

    publication = _exact_mapping(
        _strict_json_bytes(
            candidates.publication_artifact,
            _PUBLICATION_MAX_BYTES,
            "persisted.publication_artifact",
        ),
        {
            "schema",
            "previous",
            "snapshot_artifact_hash",
            "repository_head",
            "generator_commit",
            "constitution",
            "targets",
        },
        "persisted.publication_artifact",
    )
    if publication["schema"] != _PUBLICATION_SCHEMA:
        _fail("invalid_schema", "persisted.publication_artifact.schema")
    targets = _exact_mapping(publication["targets"], set(_TARGETS), "persisted.publication_artifact.targets")
    if dict(targets) != _TARGETS:
        _fail("inconsistent", "persisted.publication_artifact.targets")
    constitution = _exact_mapping(
        publication["constitution"],
        {"source_blob", "reviewed_at_commit"},
        "persisted.publication_artifact.constitution",
    )
    previous = _materialize_previous(publication["previous"])

    repository = _exact_mapping(snapshot["repository"], {"name", "head"}, "snapshot.repository")
    generator = _exact_mapping(snapshot["generator"], {"schema", "repository", "commit"}, "snapshot.generator")
    snapshot_constitution = _exact_mapping(
        snapshot["constitution"],
        {"version", "sha256", "source_blob", "reviewed_at_commit"},
        "snapshot.constitution",
    )
    snapshot_comparison = _exact_mapping(
        snapshot["comparison_state"],
        {
            "gateway_errors_total",
            "gateway_rejected_parse_total",
            "gateway_rejected_validate_total",
            "immune_rollbacks_total",
        },
        "snapshot.comparison_state",
    )
    if publication["snapshot_artifact_hash"] != _snapshot_artifact_hash(candidates.snapshot_artifact):
        _fail("inconsistent", "persisted.publication_artifact.snapshot_artifact_hash")
    if publication["repository_head"] != repository["head"]:
        _fail("inconsistent", "persisted.publication_artifact.repository_head")
    if publication["generator_commit"] != generator["commit"]:
        _fail("inconsistent", "persisted.publication_artifact.generator_commit")
    if constitution["source_blob"] != snapshot_constitution["source_blob"]:
        _fail("inconsistent", "persisted.publication_artifact.constitution.source_blob")
    if constitution["reviewed_at_commit"] != snapshot_constitution["reviewed_at_commit"]:
        _fail("inconsistent", "persisted.publication_artifact.constitution.reviewed_at_commit")
    if attestation is not None:
        if attestation.c0_sha256 != snapshot_constitution["sha256"]:
            _fail("inconsistent", "persisted.constitution_attestation.c0_sha256")
        if attestation.source_blob != snapshot_constitution["source_blob"]:
            _fail("inconsistent", "persisted.constitution_attestation.source_blob")
        if attestation.reviewed_at_commit != snapshot_constitution["reviewed_at_commit"]:
            _fail("inconsistent", "persisted.constitution_attestation.reviewed_at_commit")
    if previous.snapshot_id != snapshot_id:
        _fail("inconsistent", "persisted.publication_artifact.previous.snapshot_id")
    if previous.c0_sha256 != snapshot_constitution["sha256"]:
        _fail("inconsistent", "persisted.publication_artifact.previous.c0_sha256")
    if dict(previous.comparison_state) != dict(snapshot_comparison):
        _fail("inconsistent", "persisted.publication_artifact.previous.comparison_state")

    if candidates.claude_md != candidates.agents_md:
        _fail("inconsistent", "persisted.consumer_outputs")
    claude_payload, claude_provenance = _parse_root(candidates.claude_md, snapshot)
    agents_payload, agents_provenance = _parse_root(candidates.agents_md, snapshot)
    if claude_payload != agents_payload or claude_provenance != agents_provenance:
        _fail("inconsistent", "persisted.consumer_outputs")

    expected_provenance = {
        "Payload schema": claude_payload["schema"],
        "Snapshot schema": snapshot["schema"],
        "Mode": previous.mode.value,
        "Snapshot ID": snapshot_id,
        "Payload hash": payload_hash(claude_payload),
        "Repository head": repository["head"],
        "Generator commit": generator["commit"],
        "Constitution source blob": snapshot_constitution["source_blob"],
        "Constitution reviewed commit": snapshot_constitution["reviewed_at_commit"],
    }
    if dict(claude_provenance) != expected_provenance:
        _fail("inconsistent", "persisted.root.provenance")
    if previous.payload_hash != expected_provenance["Payload hash"]:
        _fail("inconsistent", "persisted.publication_artifact.previous.payload_hash")
    if previous.consumer_outputs["claude"] != consumer_output_hash(candidates.claude_md):
        _fail("inconsistent", "persisted.publication_artifact.previous.consumer_outputs.claude")
    if previous.consumer_outputs["agents"] != consumer_output_hash(candidates.agents_md):
        _fail("inconsistent", "persisted.publication_artifact.previous.consumer_outputs.agents")

    expected = build_publication_candidates(claude_payload, snapshot)
    if candidates != expected:
        _fail("inconsistent", "persisted.generation")
    return previous


def validate_persisted_generation(candidates: PublicationCandidates) -> PreviousPublishedRecord:
    """Validate four persisted artifact bytes as one generation and return its record."""
    if type(candidates) is not PublicationCandidates:
        _fail("invalid_type", "persisted")
    try:
        return _validate_persisted_generation(candidates)
    except ContractViolation:
        raise
    except (AttributeError, IndexError, KeyError, RecursionError, TypeError, UnicodeError, ValueError):
        _fail("invalid_type", "persisted")


def validate_constitution_bound_persisted_generation(
    candidates: PublicationCandidates,
    attestation: ConstitutionAttestation,
) -> PreviousPublishedRecord:
    """Validate one persisted generation against an external Constitution attestation."""
    if type(candidates) is not PublicationCandidates:
        _fail("invalid_type", "persisted")
    validate_constitution_attestation(attestation)
    try:
        return _validate_persisted_generation(candidates, attestation)
    except ContractViolation:
        raise
    except (AttributeError, IndexError, KeyError, RecursionError, TypeError, UnicodeError, ValueError):
        _fail("invalid_type", "persisted")
