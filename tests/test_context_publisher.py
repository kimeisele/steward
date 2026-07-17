"""Read-only repository observation contracts for Context Bridge D2a."""

from __future__ import annotations

import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

import steward.context_publisher as context_publisher
from steward.context_contract import ConstitutionAttestation
from steward.context_publisher import GenerationState, inspect_repository_generation
from steward.context_rendering import PublicationCandidates, build_publication_candidates

APPROVED_ATTESTATION = ConstitutionAttestation(
    c0_sha256="f23ab40415edf4947f12fd8ff98cf13aa8f4fbfffe029ae10aa6111fc04976a3",
    source_blob="f428d5856a5c525e002c301890777748effbeb4e",
    reviewed_at_commit="59169f2ca7822deeea068d206863d61b45e8401e",
)
GIT = "/usr/bin/git"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
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
    observation = inspect_repository_generation(REPOSITORY_ROOT, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.LEGACY_BOOTSTRAP
    assert observation.previous is None
    assert observation.head == git(REPOSITORY_ROOT, "rev-parse", "HEAD").strip()


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


def test_head_bound_generation_with_mismatched_attestation_is_unattested(tmp_path, candidates):
    repository = initialize_repository(tmp_path / "repo")
    write_candidates(repository, candidates)
    commit_all(repository)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.UNATTESTED
    assert observation.previous is None


def test_head_bound_malformed_generation_is_invalid(tmp_path, candidates, candidate_attestation):
    repository = initialize_repository(tmp_path / "repo")
    write_candidates(repository, candidates)
    publication = repository / ".steward" / "context-publication.json"
    publication.write_bytes(publication.read_bytes()[:-1] + b"]")
    commit_all(repository)

    observation = inspect_repository_generation(repository, candidate_attestation)

    assert observation.state is GenerationState.INVALID
    assert observation.previous is None


def test_coherent_uncommitted_generation_is_unbound_without_previous(
    tmp_path,
    models,
    candidates,
    candidate_attestation,
):
    repository = initialize_repository(tmp_path / "repo")
    write_candidates(repository, candidates)
    commit_all(repository)
    payload, snapshot = deepcopy(models)
    payload["observations"]["health"]["provider"] = "degraded"
    snapshot["observations"]["health"]["provider"] = "degraded"
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


def test_target_hardlink_is_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    source = tmp_path / "shared"
    source.write_text("shared\n")
    os.link(source, repository / "CLAUDE.md")

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


def test_repository_root_symlink_is_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    link = tmp_path / "repository-link"
    os.symlink(repository, link)

    observation = inspect_repository_generation(link, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


def test_exact_transaction_signal_is_mixed(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    (repository / ".context-publish-v1.00000000000000000000000000000000.claude.tmp").touch()

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MIXED
    assert observation.publisher_signal is True


def test_unknown_publisher_signal_is_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    (repository / ".context-publish-surprise").touch()

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW
    assert observation.previous is None


def test_caller_path_is_not_used_to_select_git(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "git").write_text("unexpected\n")
    monkeypatch.setenv("PATH", os.fspath(fake_bin))

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.ABSENT


def test_observation_does_not_change_git_state(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    before = git(repository, "status", "--porcelain=v1", "-z", text=False)

    inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert git(repository, "status", "--porcelain=v1", "-z", text=False) == before


def test_in_place_mutation_on_same_inode_is_detected(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    target = repository / "CLAUDE.md"
    target.write_text("original\n")
    commit_all(repository)
    inode = target.stat().st_ino
    original_read = context_publisher._read_worktree
    calls = 0

    def mutate_after_first_read(root_fd, steward_fd):
        nonlocal calls
        result = original_read(root_fd, steward_fd)
        calls += 1
        if calls == 1:
            target.write_text("mutated!\n")
            assert target.stat().st_ino == inode
        return result

    monkeypatch.setattr(context_publisher, "_read_worktree", mutate_after_first_read)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW
    assert observation.race_detected is True


def test_git_and_worktree_remain_bound_after_root_replacement(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_text("original\n")
    commit_all(repository, "original")
    original_head = git(repository, "rev-parse", "HEAD").strip()

    replacement = initialize_repository(tmp_path / "replacement")
    (replacement / "CLAUDE.md").write_text("replacement\n")
    commit_all(replacement, "replacement")
    assert git(replacement, "rev-parse", "HEAD").strip() != original_head

    displaced = tmp_path / "displaced"
    original_git_command = context_publisher._git_command
    replaced = False

    def replace_before_first_git(*args, **kwargs):
        nonlocal replaced
        if not replaced:
            repository.rename(displaced)
            replacement.rename(repository)
            replaced = True
        return original_git_command(*args, **kwargs)

    monkeypatch.setattr(context_publisher, "_git_command", replace_before_first_git)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.LEGACY_BOOTSTRAP
    assert observation.head == original_head


def test_generated_partial_state_is_mixed(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    (repository / "CLAUDE.md").write_text("<!-- steward-context:dynamic:v1:begin -->\n")

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MIXED
    assert observation.previous is None
