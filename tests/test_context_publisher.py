"""Read-only repository observation contracts for Context Bridge D2a."""

from __future__ import annotations

import builtins
import fcntl
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

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


def raw_git(repository: Path, *arguments: str) -> bytes:
    return git(repository, *arguments, text=False)


def bounded_python(program: str, *, stdout_limit: int, timeout: float = 2.0) -> bytes:
    descriptor = os.open("/", os.O_RDONLY)
    try:
        return context_publisher._bounded_process(
            [sys.executable, "-c", program],
            pass_fd=descriptor,
            stdout_limit=stdout_limit,
            deadline=time.monotonic() + timeout,
        )
    finally:
        os.close(descriptor)


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


@pytest.mark.parametrize("operation", ["add", "delete"])
def test_staged_add_or_delete_is_manual_review(tmp_path, operation):
    repository = initialize_repository(tmp_path / "repo")
    if operation == "delete":
        (repository / "CLAUDE.md").write_text("legacy\n")
    else:
        (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    if operation == "delete":
        git(repository, "rm", "-q", "CLAUDE.md")
    else:
        (repository / "CLAUDE.md").write_text("staged add\n")
        git(repository, "add", "CLAUDE.md")

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


def test_unmerged_index_stages_are_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_text("legacy\n")
    commit_all(repository)
    blob = git(repository, "rev-parse", "HEAD:CLAUDE.md").strip()
    git(repository, "rm", "--cached", "-q", "CLAUDE.md")
    index_info = "".join(f"100644 {blob} {stage}\tCLAUDE.md\n" for stage in (1, 2, 3))
    subprocess.run(
        [GIT, "update-index", "--index-info"],
        cwd=repository,
        env=GIT_ENV,
        input=index_info,
        check=True,
        text=True,
    )

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


def test_unexpected_index_mode_is_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_text("legacy\n")
    commit_all(repository)
    blob = git(repository, "rev-parse", "HEAD:CLAUDE.md").strip()
    index_info = f"120000 {blob}\tCLAUDE.md\n"
    subprocess.run(
        [GIT, "update-index", "--index-info"],
        cwd=repository,
        env=GIT_ENV,
        input=index_info,
        check=True,
        text=True,
    )

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


@pytest.mark.parametrize("parser", [context_publisher._parse_tree, context_publisher._parse_index])
@pytest.mark.parametrize("shape", ["foreign", "duplicate"])
def test_plumbing_parser_rejects_foreign_and_duplicate_paths(parser, shape):
    if parser is context_publisher._parse_tree:
        prefix = b"100644 blob " + b"a" * 40 + b"\t"
    else:
        prefix = b"100644 " + b"a" * 40 + b" 0\t"
    if shape == "foreign":
        value = prefix + b"README.md\0"
    else:
        value = prefix + b"CLAUDE.md\0" + prefix + b"CLAUDE.md\0"

    with pytest.raises(context_publisher._ObservationFailure):
        parser(value)


def test_target_symlink_is_manual_review_without_reading_target(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    secret = tmp_path / "secret"
    secret.write_text("must-not-be-read\n")
    secret_stat = secret.stat()
    os.symlink(secret, repository / "CLAUDE.md")
    original_read = context_publisher.os.read

    def reject_secret_descriptor(descriptor, count):
        value = os.fstat(descriptor)
        assert (value.st_dev, value.st_ino) != (secret_stat.st_dev, secret_stat.st_ino)
        return original_read(descriptor, count)

    monkeypatch.setattr(context_publisher.os, "read", reject_secret_descriptor)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW
    assert observation.previous is None
    assert "must-not-be-read" not in observation.reason


def test_target_hardlink_is_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    source = tmp_path / "shared"
    source.write_text("shared\n")
    os.link(source, repository / "CLAUDE.md")

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


@pytest.mark.parametrize("kind", ["directory", "fifo", "socket"])
def test_non_regular_target_types_are_manual_review(tmp_path, kind):
    cleanup_root = None
    if kind == "socket":
        cleanup_root = Path(tempfile.mkdtemp(prefix="d2a-", dir="/tmp"))
        repository = initialize_repository(cleanup_root / "repo")
    else:
        repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    target = repository / "CLAUDE.md"
    bound_socket = None
    if kind == "directory":
        target.mkdir()
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        bound_socket = socket.socket(socket.AF_UNIX)
        bound_socket.bind(os.fspath(target))
    try:
        observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)
    finally:
        if bound_socket is not None:
            bound_socket.close()
        if cleanup_root is not None:
            shutil.rmtree(cleanup_root)

    assert observation.state is GenerationState.MANUAL_REVIEW


def test_device_target_is_rejected_before_open():
    parent_fd = os.open("/dev", context_publisher._OPEN_DIRECTORY)
    try:
        with pytest.raises(context_publisher._ObservationFailure):
            context_publisher._read_target(parent_fd, "null", 1024)
    finally:
        os.close(parent_fd)


def test_steward_parent_symlink_is_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    (repository / ".steward").rmdir()
    foreign = tmp_path / "foreign-steward"
    foreign.mkdir()
    os.symlink(foreign, repository / ".steward")

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


def test_steward_parent_swap_during_observation_is_detected(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    foreign = tmp_path / "foreign-steward"
    foreign.mkdir()
    (foreign / "context-snapshot.json").write_text("must-not-be-read\n")
    displaced = repository / ".steward-original"
    original_read_worktree = context_publisher._read_worktree
    swapped = False

    def swap_parent_after_read(root_fd, steward_fd):
        nonlocal swapped
        result = original_read_worktree(root_fd, steward_fd)
        if not swapped:
            (repository / ".steward").rename(displaced)
            os.symlink(foreign, repository / ".steward")
            swapped = True
        return result

    monkeypatch.setattr(context_publisher, "_read_worktree", swap_parent_after_read)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW
    assert observation.race_detected is True
    assert "must-not-be-read" not in observation.reason


def test_oversized_target_is_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    limit = context_publisher.PERSISTED_TARGET_MAX_BYTES["CLAUDE.md"]
    (repository / "CLAUDE.md").write_bytes(b"x" * (limit + 1))

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


def test_short_read_is_rejected(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    target = repository / "CLAUDE.md"
    target.write_bytes(b"complete")
    parent_fd = os.open(repository, context_publisher._OPEN_DIRECTORY)
    monkeypatch.setattr(context_publisher.os, "read", lambda descriptor, count: b"")
    try:
        with pytest.raises(context_publisher._ObservationFailure):
            context_publisher._read_target(parent_fd, "CLAUDE.md", 1024)
    finally:
        os.close(parent_fd)


def test_growth_during_read_is_rejected(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    target = repository / "CLAUDE.md"
    target.write_bytes(b"original")
    parent_fd = os.open(repository, context_publisher._OPEN_DIRECTORY)
    original_read = context_publisher.os.read
    grown = False

    def grow_after_read(descriptor, count):
        nonlocal grown
        chunk = original_read(descriptor, count)
        if not grown and chunk:
            with target.open("ab") as stream:
                stream.write(b"growth")
            grown = True
        return chunk

    monkeypatch.setattr(context_publisher.os, "read", grow_after_read)
    try:
        with pytest.raises(context_publisher._ObservationFailure):
            context_publisher._read_target(parent_fd, "CLAUDE.md", 1024)
    finally:
        os.close(parent_fd)


def test_read_error_blocks(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_bytes(b"content")
    parent_fd = os.open(repository, context_publisher._OPEN_DIRECTORY)

    def fail_read(descriptor, count):
        raise OSError("injected")

    monkeypatch.setattr(context_publisher.os, "read", fail_read)
    try:
        with pytest.raises(OSError):
            context_publisher._read_target(parent_fd, "CLAUDE.md", 1024)
    finally:
        os.close(parent_fd)


def test_public_observer_fail_closes_read_error_without_leaking_bytes(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)

    def fail_read(root_fd, steward_fd):
        raise OSError("secret-target-bytes")

    monkeypatch.setattr(context_publisher, "_read_worktree", fail_read)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW
    assert "secret-target-bytes" not in observation.reason


def test_target_swap_between_lstat_and_open_is_rejected(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    target = repository / "CLAUDE.md"
    target.write_bytes(b"original")
    parent_fd = os.open(repository, context_publisher._OPEN_DIRECTORY)
    original_open = context_publisher.os.open
    swapped = False

    def swap_before_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "CLAUDE.md" and kwargs.get("dir_fd") == parent_fd and not swapped:
            target.rename(repository / "displaced")
            target.write_bytes(b"replacement")
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(context_publisher.os, "open", swap_before_open)
    try:
        with pytest.raises(context_publisher._ObservationFailure):
            context_publisher._read_target(parent_fd, "CLAUDE.md", 1024)
    finally:
        os.close(parent_fd)


def test_repository_root_symlink_is_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    link = tmp_path / "repository-link"
    os.symlink(repository, link)

    observation = inspect_repository_generation(link, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_unsafe_dot_git_shape_is_manual_review(tmp_path, kind):
    repository = tmp_path / "repo"
    repository.mkdir()
    dot_git = repository / ".git"
    if kind == "file":
        dot_git.write_text("gitdir: ../foreign\n")
    else:
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        os.symlink(foreign, dot_git)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


@pytest.mark.parametrize("relative", ["commondir", "gitdir", "objects/info/alternates"])
def test_static_git_redirection_is_manual_review(tmp_path, relative):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    redirection = repository / ".git" / relative
    redirection.parent.mkdir(parents=True, exist_ok=True)
    redirection.write_text("../foreign\n")

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


def test_exact_transaction_signal_is_mixed(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    (repository / ".context-publish-v1.00000000000000000000000000000000.claude.tmp").touch()

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MIXED
    assert observation.publisher_signal is True


def test_complete_valid_generation_with_transaction_signal_is_mixed(
    tmp_path,
    candidates,
    candidate_attestation,
):
    repository = initialize_repository(tmp_path / "repo")
    write_candidates(repository, candidates)
    commit_all(repository)
    (repository / ".steward" / ".context-publish-v1.00000000000000000000000000000000.txn").touch()

    observation = inspect_repository_generation(repository, candidate_attestation)

    assert observation.state is GenerationState.MIXED
    assert observation.previous is None


def test_unknown_publisher_signal_is_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    (repository / ".context-publish-surprise").touch()

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW
    assert observation.previous is None


def test_multiple_publisher_signals_are_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    (repository / ".context-publish-v1.00000000000000000000000000000000.claude.tmp").touch()
    (repository / ".context-publish-v1.11111111111111111111111111111111.agents.tmp").touch()

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


def test_malformed_publisher_signal_is_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    (repository / ".context-publish-v1.not-hex.txn").touch()

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


def test_historical_atomic_file_is_ignored(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    (repository / ".atomic_historical.tmp").touch()

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.ABSENT


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


def test_child_environment_is_an_exact_allowlist(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    captured_environments = []
    original_popen = context_publisher.subprocess.Popen

    def capture_environment(*args, **kwargs):
        captured_environments.append(kwargs["env"])
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(context_publisher.subprocess, "Popen", capture_environment)
    monkeypatch.setenv("HOME", "/untrusted")
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", "/untrusted")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", "/untrusted")

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.ABSENT
    assert captured_environments
    assert all(environment == context_publisher._CHILD_ENV for environment in captured_environments)


def test_unsafe_executable_path_is_rejected(tmp_path):
    executable = tmp_path / "git"
    executable.write_text("not trusted\n")
    executable.chmod(0o777)

    with pytest.raises(context_publisher._ObservationFailure):
        context_publisher._safe_executable((os.fspath(executable),))


def test_unsafe_fixed_system_git_is_fail_closed(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    original_lstat = context_publisher.os.lstat

    def unsafe_git(path):
        value = original_lstat(path)
        if os.fspath(path) in {"/usr/bin/git", "/bin/git"} and stat.S_ISREG(value.st_mode):
            fields = list(value)
            fields[0] |= stat.S_IWGRP
            return os.stat_result(fields)
        return value

    monkeypatch.setattr(context_publisher.os, "lstat", unsafe_git)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW


@pytest.mark.parametrize("executable", ["/usr/bin/git", "/usr/bin/python3"])
@pytest.mark.parametrize("defect", ["symlink", "owner", "writable"])
def test_system_executable_defects_are_rejected(monkeypatch, executable, defect):
    original_lstat = context_publisher.os.lstat
    baseline = original_lstat("/usr/bin/git")

    def defective_lstat(path):
        if os.fspath(path) != executable:
            return original_lstat(path)
        mode = baseline.st_mode
        owner = 0
        if defect == "symlink":
            mode = stat.S_IFLNK | 0o777
        elif defect == "owner":
            owner = 1
        else:
            mode |= stat.S_IWGRP
        return SimpleNamespace(st_mode=mode, st_uid=owner)

    monkeypatch.setattr(context_publisher.os, "lstat", defective_lstat)

    with pytest.raises(context_publisher._ObservationFailure):
        context_publisher._safe_executable((executable,))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux direct Git contract")
def test_linux_never_selects_python_helper(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    selected = []
    original_safe_executable = context_publisher._safe_executable

    def record_selection(candidates):
        selected.append(candidates)
        return original_safe_executable(candidates)

    monkeypatch.setattr(context_publisher, "_safe_executable", record_selection)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.ABSENT
    assert selected
    assert all(not any("python" in candidate for candidate in candidates) for candidates in selected)


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin fixed helper contract")
def test_darwin_ignores_path_python_and_blocks_unsafe_fixed_helper(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text("not executable\n")
    monkeypatch.setenv("PATH", os.fspath(fake_bin))

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)
    assert observation.state is GenerationState.ABSENT

    original_lstat = context_publisher.os.lstat

    def unsafe_python(path):
        value = original_lstat(path)
        if os.fspath(path) == "/usr/bin/python3":
            fields = list(value)
            fields[0] |= stat.S_IWGRP
            return os.stat_result(fields)
        return value

    monkeypatch.setattr(context_publisher.os, "lstat", unsafe_python)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)
    assert observation.state is GenerationState.MANUAL_REVIEW


@pytest.mark.parametrize(
    "value",
    [
        b"100644 blob " + b"a" * 40 + b"\tCLAUDE.md",
        b"100644 blob " + b"a" * 40 + b"\tCLAUDE.md\0\0",
    ],
)
def test_tree_parser_rejects_malformed_nul_termination(value):
    with pytest.raises(context_publisher._ObservationFailure):
        context_publisher._parse_tree(value)


@pytest.mark.parametrize(
    "value",
    [
        b"100644 " + b"a" * 40 + b" 0\tCLAUDE.md",
        b"100644 " + b"a" * 40 + b" 0\tCLAUDE.md\0\0",
    ],
)
def test_index_parser_rejects_malformed_nul_termination(value):
    with pytest.raises(context_publisher._ObservationFailure):
        context_publisher._parse_index(value)


def test_worktree_mode_is_observed_not_invented(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    target = repository / "CLAUDE.md"
    target.write_text("untracked\n")
    target.chmod(0o755)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.targets["CLAUDE.md"].worktree_mode == "100755"


def test_head_pointing_at_annotated_tag_is_manual_review(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_text("legacy\n")
    commit_all(repository)
    git(repository, "tag", "-a", "fixture-tag", "-m", "fixture")
    tag_object = git(repository, "rev-parse", "fixture-tag^{tag}").strip()
    (repository / ".git" / "HEAD").write_text(f"{tag_object}\n")

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW
    assert observation.previous is None


@pytest.mark.parametrize("relative", ["commondir", "objects/info/alternates"])
def test_transient_git_redirection_file_is_detected(tmp_path, monkeypatch, relative):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    foreign = initialize_repository(tmp_path / "foreign")
    (foreign / "README.md").write_text("foreign\n")
    commit_all(foreign)
    original_git_command = context_publisher._git_command
    injected = False

    def insert_and_remove_redirection(*args, **kwargs):
        nonlocal injected
        if not injected:
            redirection = repository / ".git" / relative
            redirection.parent.mkdir(parents=True, exist_ok=True)
            injected = True
            content = ".\n" if relative == "commondir" else f"{foreign / '.git' / 'objects'}\n"
            redirection.write_text(content)
            try:
                return original_git_command(*args, **kwargs)
            finally:
                redirection.unlink()
        return original_git_command(*args, **kwargs)

    monkeypatch.setattr(context_publisher, "_git_command", insert_and_remove_redirection)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW
    assert observation.race_detected is True


def test_head_change_between_git_rounds_is_manual_review(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("one\n")
    commit_all(repository, "one")
    original_read_git_evidence = context_publisher._read_git_evidence
    calls = 0

    def commit_after_first_round(*args, **kwargs):
        nonlocal calls
        evidence = original_read_git_evidence(*args, **kwargs)
        calls += 1
        if calls == 1:
            (repository / "README.md").write_text("two\n")
            commit_all(repository, "two")
        return evidence

    monkeypatch.setattr(context_publisher, "_read_git_evidence", commit_after_first_round)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW
    assert observation.race_detected is True


def test_observation_does_not_change_git_state(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    before = git(repository, "status", "--porcelain=v1", "-z", text=False)

    inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert git(repository, "status", "--porcelain=v1", "-z", text=False) == before


def test_observation_never_calls_forbidden_write_syscalls(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    original_open = context_publisher.os.open
    forbidden_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

    def read_only_open(path, flags, *args, **kwargs):
        assert flags & forbidden_flags == 0
        return original_open(path, flags, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("read-only observer invoked a forbidden write syscall")

    original_git_command = context_publisher._git_command
    original_import = builtins.__import__

    def read_only_git(git_path, git_fd, arguments, **kwargs):
        assert arguments[0] in {"cat-file", "ls-files", "ls-tree", "rev-parse"}
        return original_git_command(git_path, git_fd, arguments, **kwargs)

    def reject_service_registry(name, *args, **kwargs):
        if "service_registry" in name:
            pytest.fail("read-only observer imported ServiceRegistry")
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as guarded:
        guarded.setattr(context_publisher.os, "open", read_only_open)
        for name in (
            "chmod",
            "fsync",
            "link",
            "mkdir",
            "remove",
            "rename",
            "replace",
            "symlink",
            "unlink",
            "write",
        ):
            guarded.setattr(context_publisher.os, name, forbidden)
        guarded.setattr(Path, "write_bytes", forbidden)
        guarded.setattr(Path, "write_text", forbidden)
        guarded.setattr(tempfile, "mkdtemp", forbidden)
        guarded.setattr(tempfile, "mkstemp", forbidden)
        guarded.setattr(tempfile, "NamedTemporaryFile", forbidden)
        guarded.setattr(fcntl, "flock", forbidden)
        guarded.setattr(socket, "socket", forbidden)
        guarded.setattr(context_publisher.time, "time", forbidden)
        guarded.setattr(context_publisher, "_git_command", read_only_git)
        guarded.setattr(builtins, "__import__", reject_service_registry)

        observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.ABSENT


@pytest.mark.parametrize(
    ("program", "stdout_limit", "timeout"),
    [
        ("import time;time.sleep(5)", 16, 0.1),
        ("import os;os.write(1,b'x'*17)", 16, 2.0),
        ("import os;os.write(2,b'x'*4097)", 16, 2.0),
    ],
)
def test_timeout_and_output_limits_kill_and_reap_child(program, stdout_limit, timeout, monkeypatch):
    child_pid = None
    original_popen = context_publisher.subprocess.Popen

    def capture_child(*args, **kwargs):
        nonlocal child_pid
        process = original_popen(*args, **kwargs)
        child_pid = process.pid
        return process

    monkeypatch.setattr(context_publisher.subprocess, "Popen", capture_child)
    descriptor = os.open("/", os.O_RDONLY)
    try:
        with pytest.raises(context_publisher._ObservationFailure):
            context_publisher._bounded_process(
                [sys.executable, "-c", program],
                pass_fd=descriptor,
                stdout_limit=stdout_limit,
                deadline=time.monotonic() + timeout,
            )
    finally:
        os.close(descriptor)

    assert child_pid is not None
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


@pytest.mark.parametrize(
    ("program", "stdout_limit", "expected"),
    [
        ("import os;os.write(1,b'x'*16)", 16, b"x" * 16),
        ("import os;os.write(2,b'x'*4096)", 16, b""),
    ],
)
def test_stdout_and_stderr_exact_limits_are_accepted(program, stdout_limit, expected):
    assert bounded_python(program, stdout_limit=stdout_limit) == expected


def test_command_timeout_is_exactly_five_seconds():
    started = time.monotonic()
    with pytest.raises(context_publisher._ObservationFailure):
        bounded_python("import time;time.sleep(10)", stdout_limit=16, timeout=20.0)
    elapsed = time.monotonic() - started

    assert 4.5 <= elapsed <= 7.0


def test_repository_deadline_is_exactly_twenty_seconds(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    observed_deadline = None
    monkeypatch.setattr(context_publisher.time, "monotonic", lambda: 100.0)

    def capture_deadline(git_path, git_fd, deadline):
        nonlocal observed_deadline
        observed_deadline = deadline
        raise context_publisher._ObservationFailure

    monkeypatch.setattr(context_publisher, "_read_git_evidence", capture_deadline)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW
    assert observed_deadline == 120.0


def test_nonzero_process_exit_is_reaped(monkeypatch):
    child_pid = None
    original_popen = context_publisher.subprocess.Popen

    def capture_child(*args, **kwargs):
        nonlocal child_pid
        process = original_popen(*args, **kwargs)
        child_pid = process.pid
        return process

    monkeypatch.setattr(context_publisher.subprocess, "Popen", capture_child)

    with pytest.raises(context_publisher._ObservationFailure):
        bounded_python("raise SystemExit(7)", stdout_limit=16)

    assert child_pid is not None
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_nonzero_git_exit_blocks(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    git_fd = os.open(repository / ".git", context_publisher._OPEN_DIRECTORY)
    try:
        with pytest.raises(context_publisher._ObservationFailure):
            context_publisher._git_command(
                "/usr/bin/git",
                git_fd,
                ["not-a-real-plumbing-command"],
                stdout_limit=4096,
                deadline=time.monotonic() + 5,
            )
    finally:
        os.close(git_fd)


def test_git_plumbing_argv_is_exact_and_blobs_use_cat_file(monkeypatch):
    head = "a" * 40
    blob = "b" * 40
    calls = []

    def fake_git(git_path, git_fd, arguments, **kwargs):
        calls.append(arguments)
        if arguments[:3] in (["rev-parse", "--verify", "HEAD"], ["rev-parse", "--verify", "HEAD^{commit}"]):
            return f"{head}\n".encode()
        if arguments[0] == "ls-tree":
            return f"100644 blob {blob}\tCLAUDE.md\0".encode()
        if arguments[0] == "ls-files":
            return f"100644 {blob} 0\tCLAUDE.md\0".encode()
        if arguments[0] == "cat-file":
            return b"legacy\n"
        raise AssertionError(arguments)

    monkeypatch.setattr(context_publisher, "_git_command", fake_git)

    observed_head, tree, index, head_blobs = context_publisher._read_git_evidence(
        "/usr/bin/git", 7, time.monotonic() + 20
    )

    assert observed_head == head
    assert tree["CLAUDE.md"].blob == blob
    assert index["CLAUDE.md"].blob == blob
    assert head_blobs["CLAUDE.md"] == b"legacy\n"
    assert calls[2] == ["ls-tree", "-z", "--full-tree", head, "--", *context_publisher._TARGETS]
    assert calls[-1] == ["cat-file", "blob", blob]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux inherited FD contract")
def test_linux_git_uses_proc_fd_directly_without_helper(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    git_fd = os.open(repository / ".git", context_publisher._OPEN_DIRECTORY)
    captured = {}
    observed_proc_paths = []
    observed_proc_stats = []
    original_stat = context_publisher.os.stat

    def capture_stat(path, *args, **kwargs):
        if os.fspath(path).startswith("/proc/self/fd/"):
            observed_proc_paths.append(os.fspath(path))
            observed_proc_stats.append(original_stat(path, *args, **kwargs))
            return observed_proc_stats[-1]
        return original_stat(path, *args, **kwargs)

    def capture_command(arguments, **kwargs):
        captured["arguments"] = arguments
        captured.update(kwargs)
        return b""

    monkeypatch.setattr(context_publisher.os, "stat", capture_stat)
    monkeypatch.setattr(context_publisher, "_bounded_process", capture_command)
    try:
        expected = os.fstat(git_fd)
        context_publisher._git_command(
            "/usr/bin/git",
            git_fd,
            ["rev-parse", "--verify", "HEAD"],
            stdout_limit=4096,
            deadline=time.monotonic() + 5,
        )
    finally:
        os.close(git_fd)

    proc_path = f"/proc/self/fd/{git_fd}"
    assert observed_proc_paths == [proc_path]
    proc_stat = observed_proc_stats[0]
    assert (proc_stat.st_dev, proc_stat.st_ino) == (expected.st_dev, expected.st_ino)
    assert captured["arguments"] == [
        "/usr/bin/git",
        f"--git-dir={proc_path}",
        "rev-parse",
        "--verify",
        "HEAD",
    ]
    assert all("python" not in argument for argument in captured["arguments"])
    assert captured["pass_fd"] == git_fd


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin helper contract")
def test_darwin_helper_binds_expected_fd_and_has_no_repository_path(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    git_fd = os.open(repository / ".git", context_publisher._OPEN_DIRECTORY)
    captured = {}

    def capture_command(arguments, **kwargs):
        captured["arguments"] = arguments
        captured.update(kwargs)
        return b""

    monkeypatch.setattr(context_publisher, "_bounded_process", capture_command)
    adversarial = "HEAD;ignore-contract\n--git-dir=/foreign"
    try:
        context_publisher._git_command(
            "/usr/bin/git",
            git_fd,
            ["rev-parse", "--verify", adversarial],
            stdout_limit=4096,
            deadline=time.monotonic() + 5,
        )
        git_stat = os.fstat(git_fd)
    finally:
        os.close(git_fd)

    arguments = captured["arguments"]
    assert arguments[:5] == ["/usr/bin/python3", "-I", "-S", "-c", context_publisher._DARWIN_HELPER]
    assert arguments[5:8] == [str(git_fd), str(git_stat.st_dev), str(git_stat.st_ino)]
    assert arguments[8:] == ["/usr/bin/git", "rev-parse", "--verify", adversarial]
    assert os.fspath(repository) not in "\0".join(arguments)
    assert captured["pass_fd"] == git_fd


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


def test_mutation_after_final_git_reference_is_detected_by_second_read(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    target = repository / "CLAUDE.md"
    target.write_text("original\n")
    commit_all(repository)
    original_read = context_publisher._read_worktree
    calls = 0

    def mutate_before_second_read(root_fd, steward_fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            target.write_text("mutated!\n")
        return original_read(root_fd, steward_fd)

    monkeypatch.setattr(context_publisher, "_read_worktree", mutate_before_second_read)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MANUAL_REVIEW
    assert observation.race_detected is True


def test_git_and_worktree_remain_bound_after_root_replacement(tmp_path, monkeypatch):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "CLAUDE.md").write_text("original\n")
    commit_all(repository, "original")
    original_head = git(repository, "rev-parse", "HEAD").strip()
    original_blob = git(repository, "rev-parse", "HEAD:CLAUDE.md").strip()

    replacement = initialize_repository(tmp_path / "replacement")
    (replacement / "CLAUDE.md").write_text("replacement\n")
    commit_all(replacement, "replacement")
    replacement_head = git(replacement, "rev-parse", "HEAD").strip()
    replacement_blob = git(replacement, "rev-parse", "HEAD:CLAUDE.md").strip()
    assert replacement_head != original_head
    assert replacement_blob != original_blob

    pathspec = ("--", *context_publisher._TARGETS)
    original_tree = raw_git(repository, "ls-tree", "-z", "--full-tree", original_head, *pathspec)
    replacement_tree = raw_git(replacement, "ls-tree", "-z", "--full-tree", replacement_head, *pathspec)
    original_index = raw_git(repository, "ls-files", "--stage", "-z", *pathspec)
    replacement_index = raw_git(replacement, "ls-files", "--stage", "-z", *pathspec)
    assert original_tree != replacement_tree
    assert original_index != replacement_index

    displaced = tmp_path / "displaced"
    original_git_command = context_publisher._git_command
    original_popen = context_publisher.subprocess.Popen
    captured_tree = []
    captured_index = []
    captured_outputs = []

    def fail_parent_cwd_mutation(*args, **kwargs):
        pytest.fail("Steward parent process changed cwd")

    def reject_preexec(*args, **kwargs):
        assert "preexec_fn" not in kwargs
        return original_popen(*args, **kwargs)

    def replace_during_every_git(*args, **kwargs):
        repository.rename(displaced)
        replacement.rename(repository)
        try:
            output = original_git_command(*args, **kwargs)
        finally:
            repository.rename(replacement)
            displaced.rename(repository)
        arguments = args[2]
        captured_outputs.append(output)
        if arguments[0] == "ls-tree":
            captured_tree.append(output)
        elif arguments[0] == "ls-files":
            captured_index.append(output)
        return output

    monkeypatch.setattr(context_publisher.os, "chdir", fail_parent_cwd_mutation)
    monkeypatch.setattr(context_publisher.os, "fchdir", fail_parent_cwd_mutation)
    monkeypatch.setattr(context_publisher.subprocess, "Popen", reject_preexec)
    monkeypatch.setattr(context_publisher, "_git_command", replace_during_every_git)

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.LEGACY_BOOTSTRAP
    assert observation.head == original_head
    assert captured_tree == [original_tree, original_tree]
    assert captured_index == [original_index, original_index]
    assert all(value != replacement_tree for value in captured_tree)
    assert all(value != replacement_index for value in captured_index)
    assert all(replacement_head.encode("ascii") not in output for output in captured_outputs)
    assert repository.exists() and replacement.exists() and not displaced.exists()


def test_generated_partial_state_is_mixed(tmp_path):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    (repository / "CLAUDE.md").write_text("<!-- steward-context:dynamic:v1:begin -->\n")

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state is GenerationState.MIXED
    assert observation.previous is None


@pytest.mark.parametrize(
    "selected",
    [
        ("CLAUDE.md",),
        (".steward/context-snapshot.json",),
        (".steward/context-publication.json",),
        (".steward/context-snapshot.json", ".steward/context-publication.json"),
        ("CLAUDE.md", "AGENTS.md", ".steward/context-snapshot.json"),
    ],
)
def test_each_partial_generated_combination_is_never_absent_or_legacy(tmp_path, candidates, selected):
    repository = initialize_repository(tmp_path / "repo")
    (repository / "README.md").write_text("fixture\n")
    commit_all(repository)
    values = {
        "CLAUDE.md": candidates.claude_md,
        "AGENTS.md": candidates.agents_md,
        ".steward/context-snapshot.json": candidates.snapshot_artifact,
        ".steward/context-publication.json": candidates.publication_artifact,
    }
    for relative in selected:
        (repository / relative).write_bytes(values[relative])

    observation = inspect_repository_generation(repository, APPROVED_ATTESTATION)

    assert observation.state in {GenerationState.MIXED, GenerationState.MANUAL_REVIEW}
    assert observation.previous is None
