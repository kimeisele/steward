"""Direct tests for the uncalled D2b transaction primitive."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import steward.context_publication as publication
from steward.context_contract import ConstitutionAttestation
from steward.context_publication import PublicationMode, PublicationState, publish_context
from steward.context_rendering import build_publication_candidates

GIT = "/usr/bin/git"
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
}


def git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        [GIT, *arguments],
        cwd=repository,
        env=GIT_ENV,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def initialize_repository(path: Path) -> Path:
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.name", "Context Publication Test")
    git(path, "config", "user.email", "context-publication@example.invalid")
    (path / ".steward").mkdir()
    (path / "README.md").write_text("fixture\n")
    return path


def commit_all(repository: Path) -> None:
    git(repository, "add", "-A")
    git(repository, "commit", "-qm", "fixture")


@pytest.fixture
def models():
    vectors = json.loads(Path("specs/context_bridge_evidence/FEATURE_04_HASH_VECTORS.json").read_text())
    return vectors["payload"]["model"], vectors["snapshot"]["model"]


@pytest.fixture
def candidates_and_attestation(models):
    payload, snapshot = models
    candidates = build_publication_candidates(payload, snapshot)
    constitution = json.loads(candidates.snapshot_artifact)["snapshot"]["constitution"]
    attestation = ConstitutionAttestation(
        c0_sha256=constitution["sha256"],
        source_blob=constitution["source_blob"],
        reviewed_at_commit=constitution["reviewed_at_commit"],
    )
    return payload, snapshot, candidates, attestation


def publish(repository, payload, snapshot, attestation):
    return publish_context(
        repository,
        payload,
        snapshot,
        attestation,
        mode=PublicationMode.CANONICAL,
        isolation_attested=True,
    )


def test_disabled_is_a_pure_no_write_gate(tmp_path, candidates_and_attestation):
    payload, snapshot, _, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    result = publish_context(repository, payload, snapshot, attestation)

    assert result.state is PublicationState.BLOCKED
    assert result.reason == "disabled"
    assert not (repository / ".steward" / ".context-publish-v1.lock").exists()


def test_preview_validates_without_transaction_paths(tmp_path, candidates_and_attestation):
    payload, snapshot, _, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)

    result = publish_context(repository, payload, snapshot, attestation, mode="preview")

    assert result.state is PublicationState.BLOCKED
    assert result.reason == "preview_only"
    assert not list(repository.glob(".context-publish-v1.*"))
    assert not list((repository / ".steward").glob(".context-publish-v1.*"))


def test_canonical_requires_explicit_isolated_worktree_attestation(tmp_path, candidates_and_attestation):
    payload, snapshot, _, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)

    result = publish_context(repository, payload, snapshot, attestation, mode="canonical")

    assert result.state is PublicationState.BLOCKED
    assert result.reason == "isolation_not_attested"
    assert not (repository / ".steward" / ".context-publish-v1.lock").exists()


def test_legacy_bootstrap_never_auto_overwritten(tmp_path, candidates_and_attestation):
    payload, snapshot, _, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_text("legacy\n")
    commit_all(repository)

    result = publish(repository, payload, snapshot, attestation)

    assert result.state is PublicationState.MANUAL_REVIEW
    assert result.reason == "baseline_legacy_bootstrap"
    assert (repository / "CLAUDE.md").read_text() == "legacy\n"
    assert not (repository / "AGENTS.md").exists()


def test_canonical_absent_baseline_publishes_four_targets(tmp_path, candidates_and_attestation):
    payload, snapshot, candidates, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)

    result = publish(repository, payload, snapshot, attestation)

    assert result.state is PublicationState.PUBLISHED
    assert result.transaction_id is not None
    assert (repository / "CLAUDE.md").read_bytes() == candidates.claude_md
    assert (repository / "AGENTS.md").read_bytes() == candidates.agents_md
    assert (repository / ".steward" / "context-snapshot.json").read_bytes() == candidates.snapshot_artifact
    assert (repository / ".steward" / "context-publication.json").read_bytes() == candidates.publication_artifact
    assert (repository / "CLAUDE.md").stat().st_mode & 0o777 == 0o644
    assert (repository / ".steward" / ".context-publish-v1.lock").exists()
    assert not list(repository.glob(".context-publish-v1.*.tmp"))
    assert not list((repository / ".steward").glob(".context-publish-v1.*.txn"))


def test_valid_head_bound_generation_is_no_op(tmp_path, candidates_and_attestation):
    payload, snapshot, candidates, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_bytes(candidates.claude_md)
    (repository / "AGENTS.md").write_bytes(candidates.agents_md)
    (repository / ".steward" / "context-snapshot.json").write_bytes(candidates.snapshot_artifact)
    (repository / ".steward" / "context-publication.json").write_bytes(candidates.publication_artifact)
    commit_all(repository)

    result = publish(repository, payload, snapshot, attestation)

    assert result.state is PublicationState.NO_OP
    assert result.transaction_id is None
    assert not list(repository.glob(".context-publish-v1.*.tmp"))
    assert not list((repository / ".steward").glob(".context-publish-v1.*.txn"))


def test_unknown_transaction_signal_fails_closed(tmp_path, candidates_and_attestation):
    payload, snapshot, _, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    (repository / ".context-publish-v1.foreign.signal").write_text("foreign\n")

    result = publish(repository, payload, snapshot, attestation)

    assert result.state is PublicationState.MANUAL_REVIEW
    assert result.reason == "transaction_namespace_ambiguous"
    assert (repository / ".context-publish-v1.foreign.signal").read_text() == "foreign\n"


def test_prepared_transaction_recovers_without_target_mutation(tmp_path, candidates_and_attestation, monkeypatch):
    payload, snapshot, _, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    original_replace = publication._replace_one

    def interrupt_before_replace(*_args, **_kwargs):
        raise ValueError("injected_prepare_crash")

    monkeypatch.setattr(publication, "_replace_one", interrupt_before_replace)
    first = publish(repository, payload, snapshot, attestation)
    assert first.state is PublicationState.MANUAL_REVIEW
    assert not (repository / "CLAUDE.md").exists()
    journals = list((repository / ".steward").glob(".context-publish-v1.*.txn"))
    assert len(journals) == 1

    monkeypatch.setattr(publication, "_replace_one", original_replace)
    recovered = publish(repository, payload, snapshot, attestation)
    assert recovered.state is PublicationState.BLOCKED
    assert recovered.reason == "recovered_prepared"
    assert not (repository / "CLAUDE.md").exists()
    assert not list(repository.glob(".context-publish-v1.*.tmp"))
    assert not list((repository / ".steward").glob(".context-publish-v1.*.txn"))


def test_partial_replace_never_auto_recovers_or_deletes_evidence(tmp_path, candidates_and_attestation, monkeypatch):
    payload, snapshot, candidates, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    original_replace = publication._replace_one
    calls = 0

    def interrupt_after_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("injected_partial_crash")
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(publication, "_replace_one", interrupt_after_first)
    first = publish(repository, payload, snapshot, attestation)
    assert first.state is PublicationState.MANUAL_REVIEW
    assert (repository / "CLAUDE.md").read_bytes() == candidates.claude_md

    monkeypatch.setattr(publication, "_replace_one", original_replace)
    second = publish(repository, payload, snapshot, attestation)
    assert second.state is PublicationState.MANUAL_REVIEW
    assert second.reason == "recovery_requires_review"
    assert (repository / "CLAUDE.md").read_bytes() == candidates.claude_md
    assert not (repository / "AGENTS.md").exists()
    assert list((repository / ".steward").glob(".context-publish-v1.*.txn"))


def test_foreign_candidate_binding_preserves_journal(tmp_path, candidates_and_attestation, monkeypatch):
    payload, snapshot, _, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    original_replace = publication._replace_one
    monkeypatch.setattr(
        publication, "_replace_one", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("injected"))
    )
    publish(repository, payload, snapshot, attestation)
    monkeypatch.setattr(publication, "_replace_one", original_replace)

    journal_path = next((repository / ".steward").glob(".context-publish-v1.*.txn"))
    journal = json.loads(journal_path.read_bytes())
    journal["payload_hash"] = "0" * 64
    journal_path.write_bytes(json.dumps(journal, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    result = publish(repository, payload, snapshot, attestation)
    assert result.state is PublicationState.MANUAL_REVIEW
    assert result.reason == "valueerror"
    assert journal_path.exists()


def test_transaction_module_has_no_registered_caller():
    source = Path("steward/context_publication.py").read_text()

    assert "context_publication" not in Path("steward/tool_providers.py").read_text()
    assert "publish_context(" in source
