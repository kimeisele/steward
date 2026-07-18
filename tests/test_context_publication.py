"""Direct tests for the uncalled D2b transaction primitive."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import steward.context_publication as publication
from steward.context_contract import ConstitutionAttestation
from steward.context_publication import (
    PublicationMode,
    PublicationState,
    acquire_publisher_lease,
    publish_context,
)
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

DARWIN_MUTATION_UNSUPPORTED = pytest.mark.skipif(
    sys.platform == "darwin",
    reason="D2b canonical mutation requires the reviewed Linux isolation contract",
)


class FixtureIsolation(publication.PublisherIsolation):
    def __init__(self, repository: Path):
        root_fd = publication.observer._open_repository_root(repository)
        steward_fd = publication._open_steward(root_fd)
        git_fd = publication._open_git(root_fd)
        try:
            super().__init__(
                publication._ISOLATION_TOKEN,
                repository,
                root_fd,
                git_fd,
                steward_fd,
            )
        except Exception:
            for descriptor in (git_fd, steward_fd, root_fd):
                os.close(descriptor)
            raise
        self._valid = True

    def verify(self) -> bool:
        return self._valid and super().verify()

    def close(self) -> None:
        super().close()


class UnforgeableIsolationAttempt:
    repository_root = Path("/tmp/forged")
    root_fd = -1
    git_fd = -1
    steward_fd = -1

    def verify(self) -> bool:
        return True


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
    isolation = FixtureIsolation(repository)
    lease = acquire_publisher_lease(isolation)
    try:
        return publish_context(repository, payload, snapshot, attestation, mode=PublicationMode.CANONICAL, lease=lease)
    finally:
        lease.close()
        isolation.close()


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

    if sys.platform == "darwin":
        assert result.state is PublicationState.MANUAL_REVIEW
        assert result.reason == "unsupported_platform"
    else:
        assert result.state is PublicationState.BLOCKED
        assert result.reason == "publisher_lease_required"
    assert not (repository / ".steward" / ".context-publish-v1.lock").exists()
    with pytest.raises(ValueError, match="publisher_isolation_required"):
        acquire_publisher_lease(repository)
    with pytest.raises(ValueError, match="publisher_isolation_required"):
        acquire_publisher_lease(UnforgeableIsolationAttempt())
    with pytest.raises(TypeError, match="isolation_constructor_private"):
        publication.PublisherIsolation(object(), repository, -1, -1, -1)


def test_canonical_is_blocked_on_unsupported_darwin(tmp_path, candidates_and_attestation, monkeypatch):
    payload, snapshot, _, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    monkeypatch.setattr(publication.sys, "platform", "darwin")

    result = publish_context(repository, payload, snapshot, attestation, mode=PublicationMode.CANONICAL)

    assert result.state is PublicationState.MANUAL_REVIEW
    assert result.reason == "unsupported_platform"
    assert not (repository / ".steward" / publication._LOCK).exists()


def test_closed_publisher_lease_cannot_publish(tmp_path, candidates_and_attestation):
    payload, snapshot, _, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    isolation = FixtureIsolation(repository)
    lease = acquire_publisher_lease(isolation)
    lease.close()

    result = publish_context(
        repository,
        payload,
        snapshot,
        attestation,
        mode=PublicationMode.CANONICAL,
        lease=lease,
    )

    if sys.platform == "darwin":
        assert result.state is PublicationState.MANUAL_REVIEW
        assert result.reason == "unsupported_platform"
    else:
        assert result.state is PublicationState.BLOCKED
        assert result.reason == "publisher_lease_invalid"
    assert (repository / ".steward" / ".context-publish-v1.lock").exists()
    isolation.close()


def test_lock_path_replacement_invalidates_lease(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    isolation = FixtureIsolation(repository)
    lease = acquire_publisher_lease(isolation)
    lock_path = repository / ".steward" / publication._LOCK
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; p=Path(sys.argv[1]); p.unlink(); p.touch(mode=0o600)",
            str(lock_path),
        ],
        check=True,
    )

    assert not lease.verify()
    lease.close()
    isolation.close()


def test_lock_owner_change_invalidates_lease(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    isolation = FixtureIsolation(repository)
    lease = acquire_publisher_lease(isolation)
    try:
        monkeypatch.setattr(publication.os, "geteuid", lambda: os.getuid() + 1)
        assert not lease.verify()
    finally:
        lease.close()
        isolation.close()


def test_external_isolation_capability_loss_invalidates_lease(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    isolation = FixtureIsolation(repository)
    lease = acquire_publisher_lease(isolation)
    isolation._valid = False
    try:
        assert not lease.verify()
    finally:
        lease.close()
        isolation.close()


@DARWIN_MUTATION_UNSUPPORTED
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


@DARWIN_MUTATION_UNSUPPORTED
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


@DARWIN_MUTATION_UNSUPPORTED
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


@DARWIN_MUTATION_UNSUPPORTED
def test_no_op_rechecks_git_and_namespace_before_return(tmp_path, candidates_and_attestation, monkeypatch):
    payload, snapshot, candidates, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_bytes(candidates.claude_md)
    (repository / "AGENTS.md").write_bytes(candidates.agents_md)
    (repository / ".steward" / "context-snapshot.json").write_bytes(candidates.snapshot_artifact)
    (repository / ".steward" / "context-publication.json").write_bytes(candidates.publication_artifact)
    commit_all(repository)
    original_view = publication._view
    calls = 0

    def mutate_on_final_view(*args, **kwargs):
        nonlocal calls
        calls += 1
        view = original_view(*args, **kwargs)
        if calls == 3:
            (repository / "README.md").write_text("no-op race\n")
            git(repository, "add", "README.md")
            git(repository, "commit", "-qm", "no-op race")
            view = original_view(*args, **kwargs)
        return view

    monkeypatch.setattr(publication, "_view", mutate_on_final_view)
    result = publish(repository, payload, snapshot, attestation)

    assert result.state is PublicationState.MANUAL_REVIEW
    assert result.reason == "no_op_fence_changed"


@DARWIN_MUTATION_UNSUPPORTED
def test_unexpected_baseline_mode_is_not_overwritten(tmp_path, candidates_and_attestation):
    payload, snapshot, candidates, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_bytes(candidates.claude_md)
    (repository / "AGENTS.md").write_bytes(candidates.agents_md)
    (repository / ".steward" / "context-snapshot.json").write_bytes(candidates.snapshot_artifact)
    (repository / ".steward" / "context-publication.json").write_bytes(candidates.publication_artifact)
    commit_all(repository)
    (repository / "CLAUDE.md").chmod(0o600)
    next_snapshot = copy.deepcopy(snapshot)
    next_snapshot["assembled_at"] = "2026-07-16T00:00:00Z"

    result = publish(repository, payload, next_snapshot, attestation)

    assert result.state is PublicationState.MANUAL_REVIEW
    assert result.reason == "baseline_mode_unexpected"
    assert (repository / "CLAUDE.md").stat().st_mode & 0o777 == 0o600
    assert not list((repository / ".steward").glob(".context-publish-v1.*.txn"))


@DARWIN_MUTATION_UNSUPPORTED
def test_unexpected_mode_is_not_reported_as_no_op(tmp_path, candidates_and_attestation):
    payload, snapshot, candidates, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_bytes(candidates.claude_md)
    (repository / "AGENTS.md").write_bytes(candidates.agents_md)
    (repository / ".steward" / "context-snapshot.json").write_bytes(candidates.snapshot_artifact)
    (repository / ".steward" / "context-publication.json").write_bytes(candidates.publication_artifact)
    commit_all(repository)
    (repository / "CLAUDE.md").chmod(0o600)

    result = publish(repository, payload, snapshot, attestation)

    assert result.state is PublicationState.MANUAL_REVIEW
    assert result.reason == "baseline_mode_unexpected"
    assert (repository / "CLAUDE.md").stat().st_mode & 0o777 == 0o600


@DARWIN_MUTATION_UNSUPPORTED
def test_unknown_transaction_signal_fails_closed(tmp_path, candidates_and_attestation):
    payload, snapshot, _, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    (repository / ".context-publish-v1.foreign.signal").write_text("foreign\n")

    result = publish(repository, payload, snapshot, attestation)

    assert result.state is PublicationState.MANUAL_REVIEW
    assert result.reason == "transaction_namespace_ambiguous"
    assert (repository / ".context-publish-v1.foreign.signal").read_text() == "foreign\n"


@DARWIN_MUTATION_UNSUPPORTED
def test_namespace_is_scanned_only_after_lease_lock(tmp_path, candidates_and_attestation, monkeypatch):
    payload, snapshot, _, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    original_scan = publication._scan_namespace
    lock_seen: list[bool] = []

    def scan_with_lock(root_fd, steward_fd):
        try:
            os.stat(publication._LOCK, dir_fd=steward_fd, follow_symlinks=False)
        except FileNotFoundError:
            lock_seen.append(False)
        else:
            lock_seen.append(True)
        return original_scan(root_fd, steward_fd)

    monkeypatch.setattr(publication, "_scan_namespace", scan_with_lock)
    result = publish(repository, payload, snapshot, attestation)

    assert result.state is PublicationState.PUBLISHED
    assert lock_seen and all(lock_seen)


def test_recovery_rejects_incoherent_git_state():
    view = type(
        "RecoveryView",
        (),
        {
            "tree": {"CLAUDE.md": "head"},
            "index": {},
            "reason": "index_differs_from_head",
            "state": publication.observer.GenerationState.MANUAL_REVIEW,
        },
    )()

    with pytest.raises(ValueError, match="recovery_git_state_untrusted"):
        publication._validate_recovery_view_state("replacing", view)


@DARWIN_MUTATION_UNSUPPORTED
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


@DARWIN_MUTATION_UNSUPPORTED
def test_partial_replace_recovers_four_file_absent_baseline(tmp_path, candidates_and_attestation, monkeypatch):
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
    assert second.state is PublicationState.BLOCKED
    assert second.reason == "recovered_rollback"
    assert not (repository / "CLAUDE.md").exists()
    assert not (repository / "AGENTS.md").exists()
    assert not list((repository / ".steward").glob(".context-publish-v1.*.txn"))


@DARWIN_MUTATION_UNSUPPORTED
def test_partial_replace_restores_present_baseline(tmp_path, candidates_and_attestation, monkeypatch):
    payload, snapshot, candidates, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_bytes(candidates.claude_md)
    (repository / "AGENTS.md").write_bytes(candidates.agents_md)
    (repository / ".steward" / "context-snapshot.json").write_bytes(candidates.snapshot_artifact)
    (repository / ".steward" / "context-publication.json").write_bytes(candidates.publication_artifact)
    commit_all(repository)
    next_snapshot = copy.deepcopy(snapshot)
    next_snapshot["assembled_at"] = "2026-07-16T00:00:00Z"
    original_replace = publication._replace_one
    calls = 0

    def interrupt_after_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("injected_present_baseline_crash")
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(publication, "_replace_one", interrupt_after_first)
    first = publish(repository, payload, next_snapshot, attestation)
    assert first.state is PublicationState.MANUAL_REVIEW
    monkeypatch.setattr(publication, "_replace_one", original_replace)
    recovered = publish(repository, payload, next_snapshot, attestation)
    assert recovered.state is PublicationState.BLOCKED
    assert recovered.reason == "recovered_rollback"
    assert (repository / "CLAUDE.md").read_bytes() == candidates.claude_md
    assert (repository / "AGENTS.md").read_bytes() == candidates.agents_md
    assert (repository / ".steward" / "context-snapshot.json").read_bytes() == candidates.snapshot_artifact
    assert (repository / ".steward" / "context-publication.json").read_bytes() == candidates.publication_artifact
    assert not list((repository / ".steward").glob(".context-publish-v1.*.txn"))


@DARWIN_MUTATION_UNSUPPORTED
def test_head_change_between_replacements_stops_transaction(tmp_path, candidates_and_attestation, monkeypatch):
    payload, snapshot, candidates, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    original_replace = publication._replace_one
    calls = 0

    def replace_then_commit(*args, **kwargs):
        nonlocal calls
        result = original_replace(*args, **kwargs)
        calls += 1
        if calls == 1:
            (repository / "README.md").write_text("head changed\n")
            git(repository, "add", "README.md")
            git(repository, "commit", "-qm", "head changed")
        return result

    monkeypatch.setattr(publication, "_replace_one", replace_then_commit)
    result = publish(repository, payload, snapshot, attestation)

    assert result.state is PublicationState.MANUAL_REVIEW
    assert (repository / "CLAUDE.md").read_bytes() == candidates.claude_md
    assert list((repository / ".steward").glob(".context-publish-v1.*.txn"))


@DARWIN_MUTATION_UNSUPPORTED
def test_external_target_writer_is_fenced(tmp_path, candidates_and_attestation, monkeypatch):
    payload, snapshot, _, attestation = candidates_and_attestation
    repository = initialize_repository(tmp_path / "repo")
    commit_all(repository)
    original_replace = publication._replace_one

    def replace_after_external_writer(*args, **kwargs):
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; Path(__import__('sys').argv[1]).write_bytes(b'foreign')",
                str(repository / "CLAUDE.md"),
            ],
            check=True,
        )
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(publication, "_replace_one", replace_after_external_writer)
    result = publish(repository, payload, snapshot, attestation)

    assert result.state is PublicationState.MANUAL_REVIEW
    assert (repository / "CLAUDE.md").read_bytes() == b"foreign"


@DARWIN_MUTATION_UNSUPPORTED
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
