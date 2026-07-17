"""Read-only repository observation contracts for Context Bridge D2a."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from steward.context_contract import ConstitutionAttestation
from steward.context_publisher import GenerationState, inspect_repository_generation
from steward.context_rendering import PublicationCandidates, build_publication_candidates

APPROVED_ATTESTATION = ConstitutionAttestation(
    c0_sha256="f23ab40415edf4947f12fd8ff98cf13aa8f4fbfffe029ae10aa6111fc04976a3",
    source_blob="f428d5856a5c525e002c301890777748effbeb4e",
    reviewed_at_commit="59169f2ca7822deeea068d206863d61b45e8401e",
)
GIT = "/usr/bin/git"
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
}


def git(repository: Path, *arguments: str, text: bool = True):
    return subprocess.run(
        [GIT, *arguments],
        cwd=repository,
        env=GIT_ENV,
        check=True,
        capture_output=True,
        text=text,
    ).stdout


def initialize_repository(path: Path) -> Path:
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.name", "Context Test")
    git(path, "config", "user.email", "context@example.invalid")
    (path / ".steward").mkdir()
    return path


def commit_all(repository: Path, message: str = "fixture") -> None:
    git(repository, "add", "-A")
    git(repository, "commit", "-qm", message)


def write_candidates(repository: Path, candidates: PublicationCandidates) -> None:
    (repository / "CLAUDE.md").write_bytes(candidates.claude_md)
    (repository / "AGENTS.md").write_bytes(candidates.agents_md)
    (repository / ".steward" / "context-snapshot.json").write_bytes(candidates.snapshot_artifact)
    (repository / ".steward" / "context-publication.json").write_bytes(candidates.publication_artifact)


@pytest.fixture
def models():
    vector = json.loads(Path("specs/context_bridge_evidence/FEATURE_04_HASH_VECTORS.json").read_text())
    return vector["payload"]["model"], vector["snapshot"]["model"]


@pytest.fixture
def candidates(models):
    payload, snapshot = models
    return build_publication_candidates(payload, snapshot)


@pytest.fixture
def candidate_attestation(candidates):
    constitution = json.loads(candidates.snapshot_artifact)["snapshot"]["constitution"]
    return ConstitutionAttestation(
        c0_sha256=constitution["sha256"],
        source_blob=constitution["source_blob"],
        reviewed_at_commit=constitution["reviewed_at_commit"],
    )


def test_real_checkout_is_legacy_bootstrap_without_previous_record():
    observation = inspect_repository_generation(Path.cwd(), APPROVED_ATTESTATION)

    assert observation.state is GenerationState.LEGACY_BOOTSTRAP
    assert observation.previous is None
    assert observation.head == git(Path.cwd(), "rev-parse", "HEAD").strip()


def test_clean_four_target_absence_is_distinct(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.ABSENT
    assert observation.previous is None


def test_head_bound_generation_is_valid_and_returns_previous(tmp_path, candidates, candidate_attestation):
    repository = initialize_repository(tmp_path / "repo")
    write_candidates(repository, candidates)
    commit_all(repository)

    observation = inspect_repository_generation(repository, candidate_attestation)

    assert observation.state is GenerationState.VALID
    assert observation.previous is not None
    assert observation.previous.payload_hash == json.loads(candidates.publication_artifact)["previous"]["payload_hash"]


def test_coherent_uncommitted_generation_is_unbound_without_previous(
    tmp_path,
    models,
    candidates,
    candidate_attestation,
):
    repository = initialize_repository(tmp_path / "repo")
    write_candidates(repository, candidates)
    commit_all(repository)
    payload, snapshot = models
    payload["observations"]["provider"] = "unknown"
    snapshot["observations"]["provider"] = "unknown"
    changed = build_publication_candidates(payload, snapshot)
    write_candidates(repository, changed)

    observation = inspect_repository_generation(repository, candidate_attestation)

    assert observation.state is GenerationState.UNBOUND
    assert observation.previous is None


def test_index_drift_is_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_text("legacy\n")
    commit_all(repository)
    (repository / "CLAUDE.md").write_text("staged\n")
    git(repository, "add", "CLAUDE.md")

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW
    assert observation.previous is None


def test_target_symlink_is_manual_review_without_reading_target(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    secret = tmp_path / "secret"
    secret.write_text("must-not-be-read\n")
    os.symlink(secret, repository / "CLAUDE.md")

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW
    assert observation.previous is None
    assert "must-not-be-read" not in observation.reason


def test_generated_partial_state_is_mixed(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_text("<!-- steward-context:dynamic:v1:begin -->\n")

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MIXED
    assert observation.previous is None
