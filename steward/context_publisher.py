"""Read-only repository observation for Context Bridge generations."""

from __future__ import annotations

import errno
import hashlib
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from steward.context_contract import ConstitutionAttestation, ContractViolation, PreviousPublishedRecord
from steward.context_rendering import (
    PERSISTED_TARGET_MAX_BYTES,
    PublicationCandidates,
    validate_constitution_bound_persisted_generation,
    validate_persisted_generation,
)

_TARGETS = tuple(PERSISTED_TARGET_MAX_BYTES)
_ROOT_TARGETS = frozenset({"CLAUDE.md", "AGENTS.md"})
_HEX40 = re.compile(rb"[0-9a-f]{40}")
_TRANSACTION = re.compile(r"\.context-publish-v1\.[0-9a-f]{32}\.txn")
_ROOT_TEMP = re.compile(r"\.context-publish-v1\.[0-9a-f]{32}\.(?:claude|agents)\.tmp")
_STEWARD_TEMP = re.compile(r"\.context-publish-v1\.[0-9a-f]{32}\.(?:snapshot|publication)\.tmp")
_LOCK = ".context-publish-v1.lock"
_CHILD_ENV = {
    "LC_ALL": "C",
    "LANG": "C",
    "PATH": "/usr/bin:/bin",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_PAGER": "cat",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}
_DARWIN_HELPER = (
    "import os,stat,sys;"
    "fd=int(sys.argv[1]);dev=int(sys.argv[2]);ino=int(sys.argv[3]);s=os.fstat(fd);"
    "sys.exit(70) if (s.st_dev!=dev or s.st_ino!=ino or not stat.S_ISDIR(s.st_mode)) else None;"
    "os.fchdir(fd);git=sys.argv[4];os.execve(git,[git,'--git-dir=.',*sys.argv[5:]],dict(os.environ))"
)
_OPEN_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
_OPEN_FILE = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW


class GenerationState(str, Enum):
    LEGACY_BOOTSTRAP = "legacy_bootstrap"
    ABSENT = "absent"
    VALID = "valid"
    UNATTESTED = "unattested"
    UNBOUND = "unbound"
    MIXED = "mixed"
    INVALID = "invalid"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class TargetEvidence:
    head_present: bool
    head_mode: str | None = None
    head_blob: str | None = None
    index_present: bool = False
    index_mode: str | None = None
    index_blob: str | None = None
    worktree_present: bool = False
    worktree_mode: str | None = None
    worktree_sha256: str | None = None


@dataclass(frozen=True)
class RepositoryGenerationObservation:
    state: GenerationState
    reason: str
    repository_root: Path
    head: str | None
    targets: Mapping[str, TargetEvidence]
    previous: PreviousPublishedRecord | None = None
    publisher_signal: bool = False
    race_detected: bool = False


@dataclass(frozen=True)
class _GitTarget:
    mode: str
    blob: str


@dataclass(frozen=True)
class _WorktreeTarget:
    data: bytes
    sha256: str
    stat_key: tuple[int, ...]


@dataclass(frozen=True)
class _RepositoryEvidence:
    head: str
    tree: Mapping[str, _GitTarget]
    index: Mapping[str, _GitTarget]
    head_blobs: Mapping[str, bytes]
    worktree: Mapping[str, _WorktreeTarget | None]
    publisher_signal: bool
    multiple_or_unknown_signal: bool


class _ObservationFailure(Exception):
    pass


def _safe_executable(candidates: tuple[str, ...]) -> tuple[str, tuple[int, ...]]:
    for candidate in candidates:
        try:
            current = Path("/")
            for component in Path(candidate).parts[1:]:
                current /= component
                value = os.lstat(current)
                if stat.S_ISLNK(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022:
                    raise _ObservationFailure
                if component == Path(candidate).name:
                    if not stat.S_ISREG(value.st_mode):
                        raise _ObservationFailure
                elif not stat.S_ISDIR(value.st_mode):
                    raise _ObservationFailure
            value = os.lstat(candidate)
            return candidate, _stat_identity(value)
        except (OSError, _ObservationFailure):
            continue
    raise _ObservationFailure


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_uid,
        stat.S_IMODE(value.st_mode),
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _file_stat_key(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _open_repository_root(repository_root: Path) -> int:
    if not isinstance(repository_root, Path) or not repository_root.is_absolute():
        raise _ObservationFailure
    lexical = os.path.normpath(os.fspath(repository_root))
    if lexical != os.fspath(repository_root):
        raise _ObservationFailure
    descriptor = os.open("/", _OPEN_DIRECTORY)
    try:
        for component in repository_root.parts[1:]:
            if component in {"", ".", ".."}:
                raise _ObservationFailure
            child = os.open(component, _OPEN_DIRECTORY, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except (OSError, _ObservationFailure):
        os.close(descriptor)
        raise _ObservationFailure


def _optional_directory(parent_fd: int, name: str) -> int | None:
    try:
        return os.open(name, _OPEN_DIRECTORY, dir_fd=parent_fd)
    except FileNotFoundError:
        return None
    except OSError as error:
        if error.errno == errno.ENOENT:
            return None
        raise _ObservationFailure from None


def _reject_unsupported_git_layout(root_fd: int, git_fd: int) -> None:
    root_git = os.stat(".git", dir_fd=root_fd, follow_symlinks=False)
    opened_git = os.fstat(git_fd)
    if not stat.S_ISDIR(root_git.st_mode) or (root_git.st_dev, root_git.st_ino) != (
        opened_git.st_dev,
        opened_git.st_ino,
    ):
        raise _ObservationFailure
    for relative in ("commondir", "gitdir"):
        try:
            os.stat(relative, dir_fd=git_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise _ObservationFailure
    objects_fd = _optional_directory(git_fd, "objects")
    if objects_fd is None:
        raise _ObservationFailure
    try:
        info_fd = _optional_directory(objects_fd, "info")
        if info_fd is not None:
            try:
                try:
                    os.stat("alternates", dir_fd=info_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise _ObservationFailure
            finally:
                os.close(info_fd)
    finally:
        os.close(objects_fd)


def _bounded_process(
    arguments: list[str],
    *,
    pass_fd: int,
    stdout_limit: int,
    deadline: float,
) -> bytes:
    remaining = min(5.0, deadline - time.monotonic())
    if remaining <= 0:
        raise _ObservationFailure
    process = subprocess.Popen(
        arguments,
        cwd="/",
        env=_CHILD_ENV,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        pass_fds=(pass_fd,),
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    stdout_fd = process.stdout.fileno()
    streams = {stdout_fd: (process.stdout, stdout_limit), process.stderr.fileno(): (process.stderr, 4096)}
    output = {descriptor: bytearray() for descriptor in streams}
    selector = selectors.DefaultSelector()
    try:
        for descriptor in streams:
            os.set_blocking(descriptor, False)
            selector.register(descriptor, selectors.EVENT_READ)
        end = time.monotonic() + remaining
        while selector.get_map():
            timeout = end - time.monotonic()
            if timeout <= 0:
                raise _ObservationFailure
            events = selector.select(timeout)
            if not events:
                raise _ObservationFailure
            for key, _ in events:
                descriptor = key.fd
                chunk = os.read(descriptor, min(8192, streams[descriptor][1] + 1 - len(output[descriptor])))
                if not chunk:
                    selector.unregister(descriptor)
                    continue
                output[descriptor].extend(chunk)
                if len(output[descriptor]) > streams[descriptor][1]:
                    raise _ObservationFailure
        process.wait(timeout=max(0.01, end - time.monotonic()))
    except (OSError, subprocess.SubprocessError, _ObservationFailure):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        process.wait()
        raise _ObservationFailure from None
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
    if process.returncode != 0:
        raise _ObservationFailure
    return bytes(output[stdout_fd])


def _git_command(
    git: str,
    git_fd: int,
    arguments: list[str],
    *,
    stdout_limit: int,
    deadline: float,
) -> bytes:
    git_stat = os.fstat(git_fd)
    if sys.platform.startswith("linux"):
        proc_path = f"/proc/self/fd/{git_fd}"
        proc_stat = os.stat(proc_path)
        if (proc_stat.st_dev, proc_stat.st_ino) != (git_stat.st_dev, git_stat.st_ino):
            raise _ObservationFailure
        command = [git, f"--git-dir={proc_path}", *arguments]
    elif sys.platform == "darwin":
        python, _ = _safe_executable(("/usr/bin/python3",))
        command = [
            python,
            "-I",
            "-S",
            "-c",
            _DARWIN_HELPER,
            str(git_fd),
            str(git_stat.st_dev),
            str(git_stat.st_ino),
            git,
            *arguments,
        ]
    else:
        raise _ObservationFailure
    return _bounded_process(command, pass_fd=git_fd, stdout_limit=stdout_limit, deadline=deadline)


def _parse_head(value: bytes) -> str:
    stripped = value.rstrip(b"\n")
    if not _HEX40.fullmatch(stripped) or value not in {stripped, stripped + b"\n"}:
        raise _ObservationFailure
    return stripped.decode("ascii")


def _parse_tree(value: bytes) -> Mapping[str, _GitTarget]:
    result: dict[str, _GitTarget] = {}
    for record in value.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, blob = metadata.split(b" ")
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            raise _ObservationFailure from None
        if path not in _TARGETS or path in result or kind != b"blob" or mode != b"100644" or not _HEX40.fullmatch(blob):
            raise _ObservationFailure
        result[path] = _GitTarget(mode.decode("ascii"), blob.decode("ascii"))
    return MappingProxyType(result)


def _parse_index(value: bytes) -> Mapping[str, _GitTarget]:
    result: dict[str, _GitTarget] = {}
    for record in value.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, blob, stage = metadata.split(b" ")
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            raise _ObservationFailure from None
        if path not in _TARGETS or path in result or stage != b"0" or mode != b"100644" or not _HEX40.fullmatch(blob):
            raise _ObservationFailure
        result[path] = _GitTarget(mode.decode("ascii"), blob.decode("ascii"))
    return MappingProxyType(result)


def _read_git_evidence(
    git: str, git_fd: int, deadline: float
) -> tuple[str, Mapping[str, _GitTarget], Mapping[str, _GitTarget], Mapping[str, bytes]]:
    pathspec = ["--", *_TARGETS]
    head = _parse_head(
        _git_command(git, git_fd, ["rev-parse", "--verify", "HEAD"], stdout_limit=4096, deadline=deadline)
    )
    tree = _parse_tree(
        _git_command(git, git_fd, ["ls-tree", "-rz", head, *pathspec], stdout_limit=16384, deadline=deadline)
    )
    index = _parse_index(
        _git_command(git, git_fd, ["ls-files", "--stage", "-z", *pathspec], stdout_limit=16384, deadline=deadline)
    )
    head_blobs = {
        path: _git_command(
            git,
            git_fd,
            ["cat-file", "blob", target.blob],
            stdout_limit=PERSISTED_TARGET_MAX_BYTES[path] + 1,
            deadline=deadline,
        )
        for path, target in tree.items()
    }
    return head, tree, index, MappingProxyType(head_blobs)


def _read_target(parent_fd: int, name: str, limit: int) -> _WorktreeTarget | None:
    try:
        lstat_value = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(lstat_value.st_mode) or lstat_value.st_nlink != 1 or lstat_value.st_size > limit:
        raise _ObservationFailure
    try:
        descriptor = os.open(name, _OPEN_FILE, dir_fd=parent_fd)
    except OSError:
        raise _ObservationFailure from None
    try:
        before = os.fstat(descriptor)
        if _file_stat_key(before) != _file_stat_key(lstat_value):
            raise _ObservationFailure
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(descriptor, min(8192, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) != before.st_size or len(data) > limit or os.read(descriptor, 1):
            raise _ObservationFailure
        after = os.fstat(descriptor)
        final_lstat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        key = _file_stat_key(before)
        if _file_stat_key(after) != key or _file_stat_key(final_lstat) != key:
            raise _ObservationFailure
        raw = bytes(data)
        return _WorktreeTarget(raw, hashlib.sha256(raw).hexdigest(), key)
    finally:
        os.close(descriptor)


def _read_worktree(root_fd: int, steward_fd: int | None) -> Mapping[str, _WorktreeTarget | None]:
    result: dict[str, _WorktreeTarget | None] = {}
    for path, limit in PERSISTED_TARGET_MAX_BYTES.items():
        if path in _ROOT_TARGETS:
            result[path] = _read_target(root_fd, path, limit)
        elif steward_fd is None:
            result[path] = None
        else:
            result[path] = _read_target(steward_fd, path.removeprefix(".steward/"), limit)
    return MappingProxyType(result)


def _scan_signals(root_fd: int, steward_fd: int | None) -> tuple[bool, bool]:
    exact = 0
    unknown = False
    for name in os.listdir(root_fd):
        if _ROOT_TEMP.fullmatch(name):
            exact += 1
        elif name.startswith(".context-publish-"):
            unknown = True
    if steward_fd is not None:
        for name in os.listdir(steward_fd):
            if name == _LOCK:
                unknown = True
            elif _TRANSACTION.fullmatch(name) or _STEWARD_TEMP.fullmatch(name):
                exact += 1
            elif name.startswith(".context-publish-"):
                unknown = True
    return exact == 1, unknown or exact > 1


def _target_evidence(evidence: _RepositoryEvidence) -> Mapping[str, TargetEvidence]:
    result: dict[str, TargetEvidence] = {}
    for path in _TARGETS:
        head = evidence.tree.get(path)
        index = evidence.index.get(path)
        worktree = evidence.worktree[path]
        result[path] = TargetEvidence(
            head_present=head is not None,
            head_mode=head.mode if head else None,
            head_blob=head.blob if head else None,
            index_present=index is not None,
            index_mode=index.mode if index else None,
            index_blob=index.blob if index else None,
            worktree_present=worktree is not None,
            worktree_mode="100644" if worktree else None,
            worktree_sha256=worktree.sha256 if worktree else None,
        )
    return MappingProxyType(result)


def _candidates(worktree: Mapping[str, _WorktreeTarget | None]) -> PublicationCandidates:
    if any(worktree[path] is None for path in _TARGETS):
        raise _ObservationFailure
    return PublicationCandidates(
        claude_md=worktree["CLAUDE.md"].data,  # type: ignore[union-attr]
        agents_md=worktree["AGENTS.md"].data,  # type: ignore[union-attr]
        snapshot_artifact=worktree[".steward/context-snapshot.json"].data,  # type: ignore[union-attr]
        publication_artifact=worktree[".steward/context-publication.json"].data,  # type: ignore[union-attr]
    )


def _head_bound(evidence: _RepositoryEvidence) -> bool:
    for path in _TARGETS:
        if not _path_head_bound(evidence, path):
            return False
    return True


def _path_head_bound(
    evidence: _RepositoryEvidence,
    path: str,
) -> bool:
    target = evidence.tree.get(path)
    worktree = evidence.worktree[path]
    if target is None or worktree is None:
        return False
    return evidence.head_blobs.get(path) == worktree.data


def _classify(
    evidence: _RepositoryEvidence,
    attestation: ConstitutionAttestation,
) -> tuple[GenerationState, str, PreviousPublishedRecord | None]:
    if evidence.multiple_or_unknown_signal:
        return GenerationState.MANUAL_REVIEW, "publisher_signal_ambiguous", None
    if evidence.tree != evidence.index:
        return GenerationState.MANUAL_REVIEW, "index_differs_from_head", None
    present = {path for path, value in evidence.worktree.items() if value is not None}
    if evidence.publisher_signal and len(present) < len(_TARGETS):
        return GenerationState.MIXED, "transaction_partial_generation", None
    if len(present) == len(_TARGETS):
        candidates = _candidates(evidence.worktree)
        try:
            validate_persisted_generation(candidates)
        except ContractViolation:
            return GenerationState.INVALID, "generation_contract_invalid", None
        if not _head_bound(evidence):
            return GenerationState.UNBOUND, "generation_not_head_bound", None
        try:
            previous = validate_constitution_bound_persisted_generation(candidates, attestation)
        except ContractViolation:
            return GenerationState.UNATTESTED, "constitution_not_attested", None
        return GenerationState.VALID, "head_bound_generation_valid", previous
    generated = evidence.publisher_signal or any(
        path not in _ROOT_TARGETS or b"<!-- steward-context:" in evidence.worktree[path].data for path in present
    )
    if generated:
        return GenerationState.MIXED, "partial_generated_state", None
    if not present and not evidence.tree and not evidence.index:
        return GenerationState.ABSENT, "all_targets_absent", None
    legacy = {"CLAUDE.md"}
    if present == legacy and set(evidence.tree) == legacy and set(evidence.index) == legacy:
        if _path_head_bound(evidence, "CLAUDE.md"):
            return GenerationState.LEGACY_BOOTSTRAP, "legacy_claude_only", None
    return GenerationState.MANUAL_REVIEW, "state_not_safely_classified", None


def _manual(
    repository_root: Path, reason: str, *, head: str | None = None, race: bool = False
) -> RepositoryGenerationObservation:
    return RepositoryGenerationObservation(
        state=GenerationState.MANUAL_REVIEW,
        reason=reason,
        repository_root=repository_root,
        head=head,
        targets=MappingProxyType({}),
        race_detected=race,
    )


def inspect_repository_generation(
    repository_root: Path,
    attestation: ConstitutionAttestation,
) -> RepositoryGenerationObservation:
    """Observe and classify the four fixed V1 targets without mutating the repository."""
    deadline = time.monotonic() + 20.0
    root_fd: int | None = None
    git_fd: int | None = None
    steward_fd: int | None = None
    head: str | None = None
    try:
        git, git_identity = _safe_executable(("/usr/bin/git", "/bin/git"))
        root_fd = _open_repository_root(repository_root)
        git_fd = os.open(".git", _OPEN_DIRECTORY, dir_fd=root_fd)
        _reject_unsupported_git_layout(root_fd, git_fd)
        steward_fd = _optional_directory(root_fd, ".steward")
        head, tree, index, head_blobs = _read_git_evidence(git, git_fd, deadline)
        worktree = _read_worktree(root_fd, steward_fd)
        publisher_signal, ambiguous_signal = _scan_signals(root_fd, steward_fd)
        second_head, second_tree, second_index, second_head_blobs = _read_git_evidence(git, git_fd, deadline)
        second_worktree = _read_worktree(root_fd, steward_fd)
        second_signals = _scan_signals(root_fd, steward_fd)
        if (head, tree, index, head_blobs, worktree, publisher_signal, ambiguous_signal) != (
            second_head,
            second_tree,
            second_index,
            second_head_blobs,
            second_worktree,
            *second_signals,
        ):
            return _manual(repository_root, "repository_changed_during_observation", head=head, race=True)
        if _safe_executable((git,))[1] != git_identity:
            return _manual(repository_root, "git_executable_changed", head=head, race=True)
        evidence = _RepositoryEvidence(
            head=head,
            tree=tree,
            index=index,
            head_blobs=head_blobs,
            worktree=worktree,
            publisher_signal=publisher_signal,
            multiple_or_unknown_signal=ambiguous_signal,
        )
        state, reason, previous = _classify(evidence, attestation)
        return RepositoryGenerationObservation(
            state=state,
            reason=reason,
            repository_root=repository_root,
            head=head,
            targets=_target_evidence(evidence),
            previous=previous,
            publisher_signal=publisher_signal,
        )
    except (ContractViolation, OSError, ValueError, _ObservationFailure):
        return _manual(repository_root, "repository_observation_failed", head=head)
    finally:
        if steward_fd is not None:
            os.close(steward_fd)
        if git_fd is not None:
            os.close(git_fd)
        if root_fd is not None:
            os.close(root_fd)
