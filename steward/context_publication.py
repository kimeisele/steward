"""Isolated, default-disabled D2b Context Bridge transaction primitive.

This module is deliberately uncalled.  It owns the local lock, journal, tempfile,
replace, read-back, and crash-recovery mechanics, while the existing read-only observer
and renderer remain the only sources for Git and generation semantics.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

import steward.context_publisher as observer
from steward.context_contract import ConstitutionAttestation, ContractViolation
from steward.context_rendering import (
    PERSISTED_TARGET_MAX_BYTES,
    PublicationCandidates,
    build_publication_candidates,
    validate_constitution_bound_persisted_generation,
)

_TARGETS = (
    "CLAUDE.md",
    "AGENTS.md",
    ".steward/context-snapshot.json",
    ".steward/context-publication.json",
)
_ROOT_TARGETS = frozenset(_TARGETS[:2])
_SCHEMA = "steward.context.transaction/v1"
_TXID = re.compile(r"^[0-9a-f]{32}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT_ID = re.compile(r"^ctxsnap-v1:[0-9a-f]{64}$")
_LOCK = observer._LOCK
_REPLACE_ORDER = list(_TARGETS)
_JOURNAL_MAX_BYTES = 65_536
_DEADLINE_SECONDS = 20.0
_LOCK_TIMEOUT_SECONDS = 5.0
_IDENTITY_KEYS = ("device", "inode", "type", "link_count", "mode")
_TARGET_IDENTITY_KEYS = (*_IDENTITY_KEYS, "size")
_TEMP_IDENTITY_KEYS = (*_TARGET_IDENTITY_KEYS, "candidate_sha256")
_TOP_LEVEL_KEYS = (
    "schema",
    "txid",
    "journal",
    "repository",
    "reviewed_head",
    "replace_order",
    "targets",
    "temps",
    "snapshot_id",
    "payload_hash",
    "c0_sha256",
    "source_blob",
    "status",
    "cursor",
    "completed_targets",
    "in_flight_target",
    "installed_targets",
)
_TARGET_RECORD_KEYS = ("parent", "baseline", "candidate", "installed")
_BASELINE_KEYS = ("parent", "target", "present", "mode", "blob", "sha256", "size")
_CANDIDATE_KEYS = ("sha256", "size")
_STATUS_VALUES = {"prepared", "replacing", "replaced", "read_back_validated"}
_OPEN_DIRECTORY = observer._OPEN_DIRECTORY
_OPEN_FILE = observer._OPEN_FILE

_THREAD_LOCK_GUARD = threading.Lock()
_THREAD_LOCKS: dict[tuple[int, int], threading.Lock] = {}
_LEASE_TOKEN = object()
_ISOLATION_TOKEN = object()


class PublisherIsolation:
    """Opaque process/worktree attestation issued by the isolated bootstrap."""

    __slots__ = (
        "repository_root",
        "root_fd",
        "git_fd",
        "steward_fd",
        "_pid",
        "_root_anchor",
        "_git_anchor",
        "_steward_anchor",
        "_closed",
    )

    def __init__(
        self,
        token: object,
        repository_root: Path,
        root_fd: int,
        git_fd: int,
        steward_fd: int,
    ) -> None:
        if token is not _ISOLATION_TOKEN:
            raise TypeError("isolation_constructor_private")
        if not isinstance(repository_root, Path) or not repository_root.is_absolute():
            raise ValueError("repository_path_invalid")
        self.repository_root = repository_root
        self.root_fd = root_fd
        self.git_fd = git_fd
        self.steward_fd = steward_fd
        self._pid = os.getpid()
        self._root_anchor = _directory_anchor(root_fd)
        self._git_anchor = _directory_anchor(git_fd)
        self._steward_anchor = _directory_anchor(steward_fd)
        if not _directory_child_matches(root_fd, ".git", self._git_anchor):
            raise ValueError("isolation_repository_binding")
        if not _directory_child_matches(root_fd, ".steward", self._steward_anchor):
            raise ValueError("isolation_repository_binding")
        self._closed = False

    @classmethod
    def _from_bootstrap(
        cls,
        token: object,
        repository_root: Path,
        root_fd: int,
        git_fd: int,
        steward_fd: int,
    ) -> "PublisherIsolation":
        return cls(token, repository_root, root_fd, git_fd, steward_fd)

    def verify(self) -> bool:
        if self._closed or os.getpid() != self._pid:
            return False
        fresh_root: int | None = None
        try:
            if _directory_anchor(self.root_fd) != self._root_anchor:
                return False
            if _directory_anchor(self.git_fd) != self._git_anchor:
                return False
            if _directory_anchor(self.steward_fd) != self._steward_anchor:
                return False
            fresh_root = observer._open_repository_root(self.repository_root)
            return _directory_anchor(fresh_root) == self._root_anchor
        except (OSError, ValueError, observer._ObservationFailure):
            return False
        finally:
            if fresh_root is not None:
                os.close(fresh_root)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in (self.git_fd, self.steward_fd, self.root_fd):
            try:
                os.close(descriptor)
            except OSError:
                pass


class PublicationMode(str, Enum):
    DISABLED = "disabled"
    PREVIEW = "preview"
    CANONICAL = "canonical"


class PublicationState(str, Enum):
    PUBLISHED = "published"
    NO_OP = "no_op"
    BLOCKED = "blocked"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class PublicationResult:
    state: PublicationState
    reason: str
    transaction_id: str | None = None


@dataclass(frozen=True)
class _FileState:
    data: bytes
    identity: Mapping[str, int | str]
    stat_key: tuple[int, ...]


@dataclass(frozen=True)
class _View:
    head: str
    tree: Mapping[str, observer._GitTarget]
    index: Mapping[str, observer._GitTarget]
    head_blobs: Mapping[str, bytes]
    worktree: Mapping[str, observer._WorktreeTarget | None]
    layout: tuple[tuple[int, ...], ...]
    parents: tuple[tuple[int, ...], ...]
    state: observer.GenerationState
    reason: str


@dataclass
class _HeldLock:
    descriptor: int
    identity: Mapping[str, int | str]
    thread_lock: threading.Lock
    key: tuple[int, int]

    def close(self) -> None:
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.descriptor)
            self.thread_lock.release()


class PublisherLease:
    """Private-worktree capability required for canonical publication."""

    __slots__ = (
        "_repository_root",
        "_isolation",
        "_root_fd",
        "_git_fd",
        "_steward_fd",
        "_lock",
        "_root_anchor",
        "_git_anchor",
        "_steward_anchor",
        "_pid",
        "_deadline",
        "_closed",
        "_token",
    )

    def __init__(
        self,
        token: object,
        isolation: PublisherIsolation,
        root_fd: int,
        git_fd: int,
        steward_fd: int,
        lock: _HeldLock,
        anchors: tuple[tuple[int, int, int, int], tuple[int, int, int, int], tuple[int, int, int, int]],
        deadline: float,
    ) -> None:
        if token is not _LEASE_TOKEN:
            raise TypeError("lease_constructor_private")
        self._token = token
        self._isolation = isolation
        self._repository_root = isolation.repository_root
        self._root_fd = root_fd
        self._git_fd = git_fd
        self._steward_fd = steward_fd
        self._lock = lock
        self._root_anchor, self._git_anchor, self._steward_anchor = anchors
        self._pid = os.getpid()
        self._deadline = deadline
        self._closed = False

    @property
    def repository_root(self) -> Path:
        return self._repository_root

    @property
    def root_fd(self) -> int:
        return self._root_fd

    @property
    def git_fd(self) -> int:
        return self._git_fd

    @property
    def steward_fd(self) -> int:
        return self._steward_fd

    @property
    def deadline(self) -> float:
        return self._deadline

    def verify(self) -> bool:
        if self._closed or os.getpid() != self._pid or time.monotonic() >= self._deadline:
            return False
        try:
            if not isinstance(self._isolation, PublisherIsolation) or not self._isolation.verify():
                return False
            if _directory_anchor(self._root_fd) != self._root_anchor:
                return False
            if _directory_anchor(self._git_fd) != self._git_anchor:
                return False
            if _directory_anchor(self._steward_fd) != self._steward_anchor:
                return False
            lock_stat = os.fstat(self._lock.descriptor)
            path_stat = os.stat(_LOCK, dir_fd=self._steward_fd, follow_symlinks=False)
            lock_identity = _identity(lock_stat)
            path_identity = _identity(path_stat)
            owner = os.geteuid()
            return (
                lock_stat.st_uid == owner
                and path_stat.st_uid == owner
                and _same_identity(self._lock.identity, lock_identity)
                and _same_identity(lock_identity, path_identity)
            )
        except (OSError, ValueError):
            return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._lock.close()
        for descriptor in (self._git_fd, self._steward_fd, self._root_fd):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _result(state: PublicationState, reason: str, txid: str | None = None) -> PublicationResult:
    return PublicationResult(state, reason[:160], txid)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _stat_key(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_nlink,
        value.st_uid,
        stat.S_IMODE(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _identity(value: os.stat_result, *, include_size: bool = False) -> dict[str, int | str]:
    result: dict[str, int | str] = {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "type": "regular" if stat.S_ISREG(value.st_mode) else "directory" if stat.S_ISDIR(value.st_mode) else "other",
        "link_count": int(value.st_nlink),
        "mode": int(stat.S_IMODE(value.st_mode)),
    }
    if include_size:
        result["size"] = int(value.st_size)
    return result


def _directory_anchor(descriptor: int) -> tuple[int, int, int, int]:
    value = os.fstat(descriptor)
    if not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid() or value.st_mode & 0o022:
        raise ValueError("unsafe_directory_anchor")
    return (value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode), stat.S_IMODE(value.st_mode))


def _same_identity(expected: Mapping[str, object], actual: Mapping[str, object]) -> bool:
    return dict(expected) == dict(actual)


_STAT_IDENTITY_KEYS = frozenset({"device", "inode", "type", "link_count", "mode", "size"})


def _same_stat_identity(expected: Mapping[str, object], actual: Mapping[str, object]) -> bool:
    expected_identity = {key: expected.get(key) for key in _STAT_IDENTITY_KEYS if key in expected}
    actual_identity = {key: actual.get(key) for key in _STAT_IDENTITY_KEYS if key in actual}
    return expected_identity == actual_identity


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_identity(
    value: object,
    *,
    keys: tuple[str, ...],
    kind: str,
    mode: int | None = None,
    size_limit: int | None = None,
) -> None:
    if not isinstance(value, Mapping) or tuple(value) != keys:
        raise ValueError("journal_identity_schema")
    for key in ("device", "inode", "link_count", "mode"):
        member = value[key]
        if not _is_int(member) or member < 0:
            raise ValueError("journal_identity_value")
    if value["type"] != kind or (kind == "regular" and value["link_count"] != 1):
        raise ValueError("journal_identity_type")
    if mode is not None and value["mode"] != mode:
        raise ValueError("journal_identity_mode")
    if "size" in keys:
        size = value["size"]
        if not _is_int(size) or size < 0 or (size_limit is not None and size > size_limit):
            raise ValueError("journal_identity_size")
    if "candidate_sha256" in keys and (
        not isinstance(value["candidate_sha256"], str) or not _HEX64.fullmatch(value["candidate_sha256"])
    ):
        raise ValueError("journal_candidate_hash")


def _validate_candidate_descriptor(value: object, path: str) -> None:
    if not isinstance(value, Mapping) or tuple(value) != _CANDIDATE_KEYS:
        raise ValueError("journal_candidate_schema")
    digest = value["sha256"]
    if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
        raise ValueError("journal_candidate_hash")
    size = value["size"]
    if not _is_int(size) or size < 0 or size > PERSISTED_TARGET_MAX_BYTES[path]:
        raise ValueError("journal_candidate_size")


def _write_all(descriptor: int, value: bytes) -> None:
    offset = 0
    while offset < len(value):
        try:
            count = os.write(descriptor, value[offset:])
        except InterruptedError:
            continue
        if count <= 0:
            raise OSError(errno.EIO, "short write")
        offset += count


def _read_descriptor(descriptor: int, limit: int) -> bytes:
    chunks = bytearray()
    while len(chunks) <= limit:
        try:
            chunk = os.read(descriptor, min(8192, limit + 1 - len(chunks)))
        except InterruptedError:
            continue
        if not chunk:
            break
        chunks.extend(chunk)
    if len(chunks) > limit:
        raise ValueError("size_limit")
    return bytes(chunks)


def _require_owned_file(parent_fd: int, name: str) -> None:
    try:
        value = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as error:
        raise ValueError("transaction_file_missing") from error
    if value.st_uid != os.geteuid():
        raise ValueError("transaction_file_owner")


def _open_steward(root_fd: int) -> int:
    return os.open(".steward", _OPEN_DIRECTORY, dir_fd=root_fd)


def _open_git(root_fd: int) -> int:
    return os.open(".git", _OPEN_DIRECTORY, dir_fd=root_fd)


def _directory_child_matches(root_fd: int, name: str, expected: tuple[int, int, int, int]) -> bool:
    descriptor: int | None = None
    try:
        descriptor = os.open(name, _OPEN_DIRECTORY, dir_fd=root_fd)
        return _directory_anchor(descriptor) == expected
    except (OSError, ValueError):
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _parent_fd(root_fd: int, steward_fd: int, path: str) -> tuple[int, str]:
    if path in _ROOT_TARGETS:
        return root_fd, path
    return steward_fd, path.removeprefix(".steward/")


def _safe_file_state(parent_fd: int, name: str, limit: int) -> _FileState | None:
    try:
        listed = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(listed.st_mode) or listed.st_nlink != 1 or listed.st_size > limit:
        raise ValueError("unsafe_target")
    descriptor = os.open(name, _OPEN_FILE, dir_fd=parent_fd)
    try:
        before = os.fstat(descriptor)
        if _stat_key(before) != _stat_key(listed):
            raise ValueError("target_race")
        data = _read_descriptor(descriptor, limit)
        if len(data) != before.st_size:
            raise ValueError("short_read")
        after = os.fstat(descriptor)
        final = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if _stat_key(after) != _stat_key(before) or _stat_key(final) != _stat_key(before):
            raise ValueError("target_race")
        return _FileState(data, _identity(before, include_size=True), _stat_key(before))
    finally:
        os.close(descriptor)


def _parent_identity(descriptor: int) -> dict[str, int | str]:
    value = os.fstat(descriptor)
    if not stat.S_ISDIR(value.st_mode) or value.st_nlink < 1 or value.st_uid != os.geteuid() or value.st_mode & 0o022:
        raise ValueError("unsafe_parent")
    return _identity(value)


def _open_thread_lock(key: tuple[int, int]) -> threading.Lock:
    with _THREAD_LOCK_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[key] = lock
        return lock


def _acquire_lock(steward_fd: int, deadline: float) -> _HeldLock:
    descriptor = os.open(
        _LOCK,
        os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
        dir_fd=steward_fd,
    )
    value = os.fstat(descriptor)
    identity = _identity(value)
    if (
        identity["type"] != "regular"
        or identity["link_count"] != 1
        or identity["mode"] != 0o600
        or value.st_uid != os.geteuid()
    ):
        os.close(descriptor)
        raise ValueError("unsafe_lock")
    key = (int(value.st_dev), int(value.st_ino))
    thread_lock = _open_thread_lock(key)
    remaining = min(_LOCK_TIMEOUT_SECONDS, deadline - time.monotonic())
    if remaining <= 0 or not thread_lock.acquire(timeout=remaining):
        os.close(descriptor)
        raise TimeoutError("thread_lock_timeout")
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("flock_timeout")
                time.sleep(min(0.02, max(0.001, deadline - time.monotonic())))
        if _identity(os.fstat(descriptor)) != identity:
            raise ValueError("lock_replaced")
        return _HeldLock(descriptor, identity, thread_lock, key)
    except Exception:
        thread_lock.release()
        os.close(descriptor)
        raise


def acquire_publisher_lease(isolation: PublisherIsolation) -> PublisherLease:
    """Consume an externally attested isolated worktree; never open a caller path."""
    if not isinstance(isolation, PublisherIsolation) or not isolation.verify():
        raise ValueError("publisher_isolation_required")
    repository_root = isolation.repository_root
    if not isinstance(repository_root, Path) or not repository_root.is_absolute():
        raise ValueError("repository_path_invalid")
    root_fd = steward_fd = git_fd = None
    lock: _HeldLock | None = None
    deadline = time.monotonic() + _DEADLINE_SECONDS
    try:
        root_fd = os.dup(isolation.root_fd)
        steward_fd = os.dup(isolation.steward_fd)
        git_fd = os.dup(isolation.git_fd)
        for descriptor in (root_fd, steward_fd, git_fd):
            os.set_inheritable(descriptor, False)
        _directory_anchor(root_fd)
        _directory_anchor(steward_fd)
        _directory_anchor(git_fd)
        _safe_git()
        lock = _acquire_lock(steward_fd, deadline)
        if not isolation.verify():
            raise ValueError("publisher_isolation_changed")
        anchors = (
            _directory_anchor(root_fd),
            _directory_anchor(git_fd),
            _directory_anchor(steward_fd),
        )
        return PublisherLease(_LEASE_TOKEN, isolation, root_fd, git_fd, steward_fd, lock, anchors, deadline)
    except Exception:
        if lock is not None:
            lock.close()
        for descriptor in (git_fd, steward_fd, root_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        raise


def _scan_namespace(root_fd: int, steward_fd: int) -> tuple[list[str], list[str], bool]:
    journals: list[str] = []
    temps: list[str] = []
    unknown = False
    for name in os.listdir(root_fd):
        if observer._ROOT_TEMP.fullmatch(name):
            temps.append(name)
        elif name.startswith(".context-publish-"):
            unknown = True
    for name in os.listdir(steward_fd):
        if name == _LOCK:
            continue
        if observer._TRANSACTION.fullmatch(name):
            journals.append(name)
        elif observer._STEWARD_TEMP.fullmatch(name):
            temps.append(name)
        elif name.startswith(".context-publish-"):
            unknown = True
    return journals, temps, unknown


def _view(
    root_fd: int,
    git_fd: int,
    steward_fd: int,
    attestation: ConstitutionAttestation,
    git: str,
    deadline: float,
) -> _View:
    layout = observer._git_layout_fingerprint(root_fd, git_fd)
    head, tree, index, head_blobs = observer._read_git_evidence(git, git_fd, deadline)
    worktree = observer._read_worktree(root_fd, steward_fd)
    parents = observer._target_parent_fingerprint(root_fd, steward_fd)
    evidence = observer._RepositoryEvidence(
        head=head,
        tree=tree,
        index=index,
        head_blobs=head_blobs,
        worktree=worktree,
        publisher_signal=False,
        multiple_or_unknown_signal=False,
    )
    state, reason, _ = observer._classify(evidence, attestation)
    if observer._git_layout_fingerprint(root_fd, git_fd) != layout:
        raise ValueError("git_layout_changed")
    return _View(head, tree, index, head_blobs, worktree, layout, parents, state, reason)


def _same_view(left: _View, right: _View) -> bool:
    return (
        left.head == right.head
        and left.tree == right.tree
        and left.index == right.index
        and left.head_blobs == right.head_blobs
        and left.worktree == right.worktree
        and left.layout == right.layout
        and left.parents == right.parents
    )


def _same_git_view(left: _View, right: _View) -> bool:
    return (
        left.head == right.head
        and left.tree == right.tree
        and left.index == right.index
        and left.head_blobs == right.head_blobs
        and left.layout == right.layout
    )


def _final_no_op_fence(
    root_fd: int,
    git_fd: int,
    steward_fd: int,
    attestation: ConstitutionAttestation,
    git: str,
    deadline: float,
    baseline: _View,
    candidates: PublicationCandidates,
    lease: PublisherLease,
) -> None:
    if not lease.verify():
        raise ValueError("publisher_lease_changed")
    journals, temps, unknown = _scan_namespace(root_fd, steward_fd)
    if journals or temps or unknown:
        raise ValueError("transaction_namespace_changed")
    final = _view(root_fd, git_fd, steward_fd, attestation, git, deadline)
    if final.state is not observer.GenerationState.VALID or not _same_view(baseline, final):
        raise ValueError("no_op_fence_changed")
    for path in _TARGETS:
        parent_fd, name = _parent_fd(root_fd, steward_fd, path)
        state = _safe_file_state(parent_fd, name, PERSISTED_TARGET_MAX_BYTES[path])
        if state is None or state.data != _candidate_bytes(candidates, path):
            raise ValueError("no_op_target_changed")
    if not lease.verify():
        raise ValueError("publisher_lease_changed")


def _candidate_metadata(candidates: PublicationCandidates) -> tuple[str, str, str]:
    snapshot = json.loads(candidates.snapshot_artifact.decode("utf-8"))
    publication = json.loads(candidates.publication_artifact.decode("utf-8"))
    snapshot_id = snapshot["snapshot_id"]
    payload_hash = publication["previous"]["payload_hash"]
    if not _SNAPSHOT_ID.fullmatch(snapshot_id) or not _HEX64.fullmatch(payload_hash):
        raise ValueError("candidate_metadata")
    return snapshot_id, payload_hash, hashlib.sha256(candidates.claude_md).hexdigest()


def _target_baseline(
    path: str,
    parent_fd: int,
    parent_identity: Mapping[str, int | str],
    view: _View,
) -> dict[str, object]:
    current = _safe_file_state(parent_fd, path.removeprefix(".steward/"), PERSISTED_TARGET_MAX_BYTES[path])
    tree_target = view.tree.get(path)
    head_bytes = view.head_blobs.get(path)
    if current is None:
        if tree_target is not None or path in view.index:
            raise ValueError("worktree_git_mismatch")
        return {
            "parent": dict(parent_identity),
            "target": None,
            "present": False,
            "mode": None,
            "blob": None,
            "sha256": None,
            "size": None,
        }
    if tree_target is None or head_bytes is None or current.data != head_bytes:
        raise ValueError("baseline_unbound")
    expected_mode = int(tree_target.mode, 8) & 0o777
    if current.identity["mode"] != expected_mode:
        raise ValueError("baseline_mode_unexpected")
    return {
        "parent": dict(parent_identity),
        "target": dict(current.identity),
        "present": True,
        "mode": int(current.identity["mode"]),
        "blob": tree_target.blob,
        "sha256": hashlib.sha256(current.data).hexdigest(),
        "size": len(current.data),
    }


def _journal_template(
    txid: str,
    journal_identity: Mapping[str, int | str],
    root_fd: int,
    git_fd: int,
    steward_fd: int,
    view: _View,
    candidates: PublicationCandidates,
    attestation: ConstitutionAttestation,
) -> dict[str, object]:
    snapshot_id, payload_hash, _ = _candidate_metadata(candidates)
    root_identity = _parent_identity(root_fd)
    git_identity = _parent_identity(git_fd)
    steward_identity = _parent_identity(steward_fd)
    targets: dict[str, object] = {}
    for path in _TARGETS:
        parent_fd, name = _parent_fd(root_fd, steward_fd, path)
        parent_identity = _parent_identity(parent_fd)
        baseline = _target_baseline(path, parent_fd, parent_identity, view)
        data = getattr(
            candidates,
            {
                "CLAUDE.md": "claude_md",
                "AGENTS.md": "agents_md",
                ".steward/context-snapshot.json": "snapshot_artifact",
                ".steward/context-publication.json": "publication_artifact",
            }[path],
        )
        targets[path] = {
            "parent": dict(parent_identity),
            "baseline": baseline,
            "candidate": {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)},
            "installed": None,
        }
    return {
        "schema": _SCHEMA,
        "txid": txid,
        "journal": dict(journal_identity),
        "repository": {"root": root_identity, "git": git_identity, "steward": steward_identity},
        "reviewed_head": view.head,
        "replace_order": list(_REPLACE_ORDER),
        "targets": targets,
        "temps": {path: None for path in _TARGETS},
        "snapshot_id": snapshot_id,
        "payload_hash": payload_hash,
        "c0_sha256": attestation.c0_sha256,
        "source_blob": attestation.source_blob,
        "status": "prepared",
        "cursor": 0,
        "completed_targets": [],
        "in_flight_target": None,
        "installed_targets": {},
    }


def _write_journal(
    descriptor: int,
    steward_fd: int,
    journal: Mapping[str, object],
    lease: PublisherLease,
) -> None:
    txid = journal.get("txid")
    if not isinstance(txid, str):
        raise ValueError("journal_txid")
    _validate_journal_schema(dict(journal), f".context-publish-v1.{txid}.txn")
    value = _canonical_json(journal)
    if len(value) > _JOURNAL_MAX_BYTES:
        raise ValueError("journal_size")
    if not lease.verify():
        raise ValueError("publisher_lease_changed")
    expected = journal["journal"]
    if not isinstance(expected, Mapping) or not _same_identity(expected, _identity(os.fstat(descriptor))):
        raise ValueError("journal_replaced")
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    _write_all(descriptor, value)
    os.fsync(descriptor)
    os.fsync(steward_fd)
    if not lease.verify():
        raise ValueError("publisher_lease_changed")


def _validate_journal_schema(parsed: object, journal_name: str) -> dict[str, object]:
    if not isinstance(parsed, dict) or tuple(parsed) != _TOP_LEVEL_KEYS:
        raise ValueError("journal_schema")
    if parsed["schema"] != _SCHEMA:
        raise ValueError("journal_schema")
    txid = parsed["txid"]
    if not isinstance(txid, str) or not _TXID.fullmatch(txid):
        raise ValueError("journal_txid")
    if journal_name != f".context-publish-v1.{txid}.txn":
        raise ValueError("journal_name")

    _validate_identity(parsed["journal"], keys=_IDENTITY_KEYS, kind="regular", mode=0o600)
    repository = parsed["repository"]
    if not isinstance(repository, Mapping) or tuple(repository) != ("root", "git", "steward"):
        raise ValueError("journal_repository")
    for value in repository.values():
        _validate_identity(value, keys=_IDENTITY_KEYS, kind="directory")

    reviewed_head = parsed["reviewed_head"]
    if not isinstance(reviewed_head, str) or not _HEX40.fullmatch(reviewed_head):
        raise ValueError("journal_head")
    if parsed["replace_order"] != list(_REPLACE_ORDER):
        raise ValueError("journal_order")
    for field in ("source_blob",):
        value = parsed[field]
        if not isinstance(value, str) or not _HEX40.fullmatch(value):
            raise ValueError("journal_attestation")
    for field in ("c0_sha256", "payload_hash"):
        value = parsed[field]
        if not isinstance(value, str) or not _HEX64.fullmatch(value):
            raise ValueError("journal_attestation")
    snapshot_id = parsed["snapshot_id"]
    if not isinstance(snapshot_id, str) or not _SNAPSHOT_ID.fullmatch(snapshot_id):
        raise ValueError("journal_snapshot")

    targets = parsed["targets"]
    temps = parsed["temps"]
    if not isinstance(targets, Mapping) or tuple(targets) != _TARGETS:
        raise ValueError("journal_targets")
    if not isinstance(temps, Mapping) or tuple(temps) != _TARGETS:
        raise ValueError("journal_temps")
    for path in _TARGETS:
        record = targets[path]
        if not isinstance(record, Mapping) or tuple(record) != _TARGET_RECORD_KEYS:
            raise ValueError("journal_target_record")
        parent = record["parent"]
        _validate_identity(parent, keys=_IDENTITY_KEYS, kind="directory")
        baseline = record["baseline"]
        if not isinstance(baseline, Mapping) or tuple(baseline) != _BASELINE_KEYS:
            raise ValueError("journal_baseline")
        _validate_identity(baseline["parent"], keys=_IDENTITY_KEYS, kind="directory")
        if baseline["parent"] != parent:
            raise ValueError("journal_baseline_parent")
        present = baseline["present"]
        if not isinstance(present, bool):
            raise ValueError("journal_baseline_present")
        if present:
            _validate_identity(
                baseline["target"],
                keys=_TARGET_IDENTITY_KEYS,
                kind="regular",
                size_limit=PERSISTED_TARGET_MAX_BYTES[path],
            )
            if baseline["mode"] != baseline["target"]["mode"]:
                raise ValueError("journal_baseline_mode")
            if not isinstance(baseline["blob"], str) or not _HEX40.fullmatch(baseline["blob"]):
                raise ValueError("journal_baseline_blob")
            if not isinstance(baseline["sha256"], str) or not _HEX64.fullmatch(baseline["sha256"]):
                raise ValueError("journal_baseline_hash")
            if not _is_int(baseline["size"]) or baseline["size"] != baseline["target"]["size"]:
                raise ValueError("journal_baseline_size")
        elif any(baseline[field] is not None for field in ("target", "mode", "blob", "sha256", "size")):
            raise ValueError("journal_absent_baseline")
        _validate_candidate_descriptor(record["candidate"], path)
        installed = record["installed"]
        if installed is not None:
            _validate_identity(
                installed,
                keys=_TEMP_IDENTITY_KEYS,
                kind="regular",
                mode=0o644,
                size_limit=PERSISTED_TARGET_MAX_BYTES[path],
            )
            if (
                installed["candidate_sha256"] != record["candidate"]["sha256"]
                or installed["size"] != record["candidate"]["size"]
            ):
                raise ValueError("journal_installed_candidate")
        temp = temps[path]
        if temp is not None:
            _validate_identity(
                temp,
                keys=_TEMP_IDENTITY_KEYS,
                kind="regular",
                mode=0o600,
                size_limit=PERSISTED_TARGET_MAX_BYTES[path],
            )
            if temp["candidate_sha256"] != record["candidate"]["sha256"] or temp["size"] != record["candidate"]["size"]:
                raise ValueError("journal_temp_candidate")

    status = parsed["status"]
    cursor = parsed["cursor"]
    if status not in _STATUS_VALUES or not _is_int(cursor) or not 0 <= cursor <= len(_TARGETS):
        raise ValueError("journal_state")
    completed = parsed["completed_targets"]
    if completed != list(_TARGETS[:cursor]):
        raise ValueError("journal_completed")
    in_flight = parsed["in_flight_target"]
    if status == "prepared" and (cursor != 0 or in_flight is not None):
        raise ValueError("journal_prepared_state")
    if status == "replacing" and (cursor not in (1, 2, 3) or in_flight != _TARGETS[cursor]):
        raise ValueError("journal_replacing_state")
    if status in {"replaced", "read_back_validated"} and (cursor != 4 or in_flight is not None):
        raise ValueError("journal_complete_state")
    installed_targets = parsed["installed_targets"]
    if not isinstance(installed_targets, Mapping) or tuple(installed_targets) != _TARGETS[:cursor]:
        raise ValueError("journal_installed_targets")
    for path in _TARGETS[:cursor]:
        if targets[path]["installed"] != installed_targets[path]:
            raise ValueError("journal_installed_binding")
    for path in _TARGETS[cursor:]:
        if targets[path]["installed"] is not None:
            raise ValueError("journal_installed_suffix")
    return parsed


def _open_journal(steward_fd: int, name: str) -> tuple[int, dict[str, object]]:
    _require_owned_file(steward_fd, name)
    descriptor = os.open(name, _OPEN_FILE, dir_fd=steward_fd)
    try:
        identity = _identity(os.fstat(descriptor))
        if os.fstat(descriptor).st_uid != os.geteuid():
            raise ValueError("journal_owner")
        raw = _read_descriptor(descriptor, _JOURNAL_MAX_BYTES)
    except Exception:
        os.close(descriptor)
        raise
    try:
        parsed = json.loads(raw.decode("utf-8"))
        if _canonical_json(parsed) != raw or not isinstance(parsed, dict):
            raise ValueError("journal_encoding")
        parsed = _validate_journal_schema(parsed, name)
        if not _same_identity(parsed["journal"], identity):
            raise ValueError("journal_identity")
        return descriptor, parsed
    except Exception:
        os.close(descriptor)
        raise


def _temp_name(path: str, txid: str) -> tuple[int, str]:
    if path == "CLAUDE.md":
        return 0, f".context-publish-v1.{txid}.claude.tmp"
    if path == "AGENTS.md":
        return 0, f".context-publish-v1.{txid}.agents.tmp"
    if path.endswith("context-snapshot.json"):
        return 1, f".context-publish-v1.{txid}.snapshot.tmp"
    return 1, f".context-publish-v1.{txid}.publication.tmp"


def _candidate_bytes(candidates: PublicationCandidates, path: str) -> bytes:
    return {
        "CLAUDE.md": candidates.claude_md,
        "AGENTS.md": candidates.agents_md,
        ".steward/context-snapshot.json": candidates.snapshot_artifact,
        ".steward/context-publication.json": candidates.publication_artifact,
    }[path]


def _prepare_temp(
    root_fd: int,
    steward_fd: int,
    journal_fd: int,
    journal: dict[str, object],
    path: str,
    data: bytes,
    lease: PublisherLease,
) -> None:
    parent_kind, name = _temp_name(path, journal["txid"])
    parent_fd = root_fd if parent_kind == 0 else steward_fd
    prior_parent = _parent_identity(parent_fd)
    if not lease.verify():
        raise ValueError("publisher_lease_changed")
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
        dir_fd=parent_fd,
    )
    try:
        _write_all(descriptor, data)
        os.fsync(descriptor)
        value = os.fstat(descriptor)
        if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or stat.S_IMODE(value.st_mode) != 0o600:
            raise ValueError("unsafe_temp")
        temp_identity = _identity(value, include_size=True)
    finally:
        os.close(descriptor)
    check = _safe_file_state(parent_fd, name, PERSISTED_TARGET_MAX_BYTES[path])
    if check is None or check.data != data or check.identity != temp_identity:
        raise ValueError("temp_changed")
    os.fsync(parent_fd)
    journal["temps"][path] = {**temp_identity, "candidate_sha256": hashlib.sha256(data).hexdigest()}
    _verify_parent_unchanged_after_own_mutation(journal, root_fd, steward_fd, parent_fd, prior_parent)
    _write_journal(journal_fd, steward_fd, journal, lease)


def _verify_parent_unchanged_after_own_mutation(
    journal: dict[str, object],
    root_fd: int,
    steward_fd: int,
    parent_fd: int,
    prior_parent: Mapping[str, int | str],
) -> None:
    current_parent = _parent_identity(parent_fd)
    if not _same_identity(dict(prior_parent), current_parent):
        raise ValueError("parent_changed")
    targets = journal["targets"]
    for target_path in _TARGETS:
        target_parent_fd, _ = _parent_fd(root_fd, steward_fd, target_path)
        if target_parent_fd == parent_fd:
            if not _same_identity(targets[target_path]["parent"], prior_parent):
                raise ValueError("parent_changed")
    if parent_fd == root_fd:
        if not _same_identity(journal["repository"]["root"], prior_parent):
            raise ValueError("parent_changed")
    elif parent_fd == steward_fd:
        if not _same_identity(journal["repository"]["steward"], prior_parent):
            raise ValueError("parent_changed")


def _fence_parent(root_fd: int, steward_fd: int, path: str, expected: Mapping[str, object]) -> int:
    parent_fd, _ = _parent_fd(root_fd, steward_fd, path)
    current = _parent_identity(parent_fd)
    if not _same_identity(expected, current):
        raise ValueError("parent_changed")
    return parent_fd


def _fence_targets(
    root_fd: int,
    steward_fd: int,
    journal: Mapping[str, object],
    candidates: PublicationCandidates,
    cursor: int,
) -> None:
    targets = journal["targets"]
    for index, path in enumerate(_TARGETS):
        record = targets[path]
        parent_fd = _fence_parent(root_fd, steward_fd, path, record["parent"])
        baseline = record["baseline"]
        if index < cursor:
            expected = record["installed"]
            expected_data = _candidate_bytes(candidates, path)
        else:
            expected = baseline["target"]
            expected_data = None
        state = _safe_file_state(parent_fd, path.removeprefix(".steward/"), PERSISTED_TARGET_MAX_BYTES[path])
        if index < cursor:
            if state is None or not _same_stat_identity(expected, state.identity) or state.data != expected_data:
                raise ValueError("target_changed")
        elif baseline["present"]:
            if (
                state is None
                or not _same_stat_identity(expected, state.identity)
                or hashlib.sha256(state.data).hexdigest() != baseline["sha256"]
            ):
                raise ValueError("baseline_changed")
        elif state is not None:
            raise ValueError("unexpected_target")


def _replace_one(
    root_fd: int,
    steward_fd: int,
    journal_fd: int,
    journal: dict[str, object],
    candidates: PublicationCandidates,
    index: int,
    lease: PublisherLease,
    git_fd: int,
    attestation: ConstitutionAttestation,
    expected_git_view: _View,
) -> None:
    path = _TARGETS[index]
    txid = journal["txid"]
    parent_kind, temp_name = _temp_name(path, txid)
    parent_fd = root_fd if parent_kind == 0 else steward_fd
    record = journal["targets"][path]
    _fence_targets(root_fd, steward_fd, journal, candidates, index)
    _fence_parent(root_fd, steward_fd, path, record["parent"])
    temp = _safe_file_state(parent_fd, temp_name, PERSISTED_TARGET_MAX_BYTES[path])
    expected_temp = journal["temps"][path]
    if (
        temp is None
        or expected_temp is None
        or not _same_stat_identity(expected_temp, temp.identity)
        or temp.data != _candidate_bytes(candidates, path)
    ):
        raise ValueError("temp_changed")
    _fence_parent(root_fd, steward_fd, path, record["parent"])
    prior_parent = _parent_identity(parent_fd)
    current_git = _view(root_fd, git_fd, steward_fd, attestation, _safe_git()[0], lease.deadline)
    if not _same_git_view(expected_git_view, current_git):
        raise ValueError("git_changed_before_replace")
    if not lease.verify():
        raise ValueError("publisher_lease_changed")
    target_name = path.removeprefix(".steward/")
    os.replace(temp_name, target_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    descriptor = os.open(target_name, _OPEN_FILE, dir_fd=parent_fd)
    try:
        os.fchmod(descriptor, 0o644)
        os.fsync(descriptor)
        installed = _safe_file_state(parent_fd, target_name, PERSISTED_TARGET_MAX_BYTES[path])
    finally:
        os.close(descriptor)
    if installed is None or installed.data != _candidate_bytes(candidates, path):
        raise ValueError("readback_failed")
    os.fsync(parent_fd)
    _verify_parent_unchanged_after_own_mutation(journal, root_fd, steward_fd, parent_fd, prior_parent)
    if not lease.verify():
        raise ValueError("publisher_lease_changed")
    record["installed"] = {**installed.identity, "candidate_sha256": hashlib.sha256(installed.data).hexdigest()}
    journal["installed_targets"][path] = record["installed"]
    journal["cursor"] = index + 1
    journal["completed_targets"] = list(_TARGETS[: index + 1])
    if index + 1 < len(_TARGETS):
        journal["status"] = "replacing"
        journal["in_flight_target"] = _TARGETS[index + 1]
    else:
        journal["status"] = "replaced"
        journal["in_flight_target"] = None
    _write_journal(journal_fd, steward_fd, journal, lease)


def _cleanup_transaction(
    root_fd: int,
    steward_fd: int,
    journal_fd: int,
    journal: Mapping[str, object],
    parent_fences: Mapping[int, Mapping[str, int | str]] | None = None,
    *,
    lease: PublisherLease,
) -> None:
    if not lease.verify():
        raise ValueError("publisher_lease_changed")
    _validate_transaction_namespace(root_fd, steward_fd, journal)
    txid = journal["txid"]
    active_parent_fences: dict[int, dict[str, int | str]] = {
        int(key): dict(value) for key, value in (parent_fences or {}).items()
    }
    for path in _TARGETS:
        parent_kind, name = _temp_name(path, txid)
        parent_fd = root_fd if parent_kind == 0 else steward_fd
        expected = journal["temps"][path]
        if expected is None:
            continue
        current_parent = _parent_identity(parent_fd)
        parent_key = int(parent_fd)
        if parent_key not in active_parent_fences:
            if not _same_identity(current_parent, journal["targets"][path]["parent"]):
                raise ValueError("parent_changed")
        elif not _same_identity(current_parent, active_parent_fences[parent_key]):
            raise ValueError("parent_changed")
        state = _safe_file_state(parent_fd, name, PERSISTED_TARGET_MAX_BYTES[path])
        if state is None and path in journal["installed_targets"]:
            active_parent_fences[parent_key] = current_parent
            continue
        _require_owned_file(parent_fd, name)
        if state is None or not _same_stat_identity(expected, state.identity):
            raise ValueError("temp_cleanup_identity")
        if not lease.verify():
            raise ValueError("publisher_lease_changed")
        os.unlink(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        if not lease.verify():
            raise ValueError("publisher_lease_changed")
        active_parent_fences[parent_key] = _parent_identity(parent_fd)
    identity = journal["journal"]
    if not _same_identity(identity, _identity(os.fstat(journal_fd))):
        raise ValueError("journal_cleanup_identity")
    if int(steward_fd) not in active_parent_fences:
        active_parent_fences[int(steward_fd)] = _parent_identity(steward_fd)
    if not _same_identity(_parent_identity(steward_fd), active_parent_fences[int(steward_fd)]):
        raise ValueError("repository_parent_changed")
    if not lease.verify():
        raise ValueError("publisher_lease_changed")
    os.unlink(f".context-publish-v1.{txid}.txn", dir_fd=steward_fd)
    os.fsync(steward_fd)
    if not lease.verify():
        raise ValueError("publisher_lease_changed")


def _create_transaction(
    root_fd: int,
    git_fd: int,
    steward_fd: int,
    view: _View,
    candidates: PublicationCandidates,
    attestation: ConstitutionAttestation,
    lease: PublisherLease,
) -> PublicationResult:
    txid = secrets.token_hex(16)
    if not lease.verify():
        raise ValueError("publisher_lease_changed")
    journals, temps, unknown = _scan_namespace(root_fd, steward_fd)
    if journals or temps or unknown:
        raise ValueError("transaction_namespace_ambiguous")
    name = f".context-publish-v1.{txid}.txn"
    if not lease.verify():
        raise ValueError("publisher_lease_changed")
    journal_fd = os.open(
        name,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
        dir_fd=steward_fd,
    )
    try:
        if not lease.verify():
            raise ValueError("publisher_lease_changed")
        journal_identity = _identity(os.fstat(journal_fd))
        journal = _journal_template(txid, journal_identity, root_fd, git_fd, steward_fd, view, candidates, attestation)
        _write_journal(journal_fd, steward_fd, journal, lease)
        for path in _TARGETS:
            _prepare_temp(root_fd, steward_fd, journal_fd, journal, path, _candidate_bytes(candidates, path), lease)
        _validate_transaction_namespace(root_fd, steward_fd, journal)
        for index in range(len(_TARGETS)):
            if not lease.verify():
                raise ValueError("publisher_lease_changed")
            _validate_transaction_namespace(root_fd, steward_fd, journal)
            _fence_targets(root_fd, steward_fd, journal, candidates, index)
            _replace_one(
                root_fd,
                steward_fd,
                journal_fd,
                journal,
                candidates,
                index,
                lease,
                git_fd,
                attestation,
                view,
            )
            current = _view(root_fd, git_fd, steward_fd, attestation, _safe_git()[0], lease.deadline)
            if not _same_git_view(view, current):
                raise ValueError("git_changed_during_transaction")
        _validate_transaction_namespace(root_fd, steward_fd, journal)
        _fence_targets(root_fd, steward_fd, journal, candidates, len(_TARGETS))
        current = _view(root_fd, git_fd, steward_fd, attestation, _safe_git()[0], lease.deadline)
        if not _same_git_view(view, current) or not lease.verify():
            raise ValueError("final_transaction_fence")
        journal["status"] = "read_back_validated"
        _write_journal(journal_fd, steward_fd, journal, lease)
        _cleanup_transaction(root_fd, steward_fd, journal_fd, journal, lease=lease)
        return _result(PublicationState.PUBLISHED, "published", txid)
    except (OSError, ValueError, ContractViolation, TimeoutError, observer._ObservationFailure) as error:
        return _result(PublicationState.MANUAL_REVIEW, type(error).__name__.lower(), txid)
    finally:
        os.close(journal_fd)


def _transaction_temp_names(txid: str) -> frozenset[str]:
    return frozenset(_temp_name(path, txid)[1] for path in _TARGETS)


def _validate_transaction_namespace(root_fd: int, steward_fd: int, journal: Mapping[str, object]) -> None:
    journal_name = f".context-publish-v1.{journal['txid']}.txn"
    journals, temps, unknown = _scan_namespace(root_fd, steward_fd)
    if unknown or journals != [journal_name]:
        raise ValueError("transaction_namespace_ambiguous")
    present_temps = set(temps)
    expected_temps = _transaction_temp_names(journal["txid"])
    if present_temps - expected_temps:
        raise ValueError("transaction_namespace_ambiguous")
    cursor = journal["cursor"]
    for index, path in enumerate(_TARGETS):
        name = _temp_name(path, journal["txid"])[1]
        if index < cursor:
            if name in present_temps:
                raise ValueError("installed_temp_present")
        elif journal["temps"][path] is None:
            if name in present_temps:
                raise ValueError("unexpected_temp")
        elif name not in present_temps:
            raise ValueError("temp_missing")


def _validate_transaction_files(root_fd: int, steward_fd: int, journal: Mapping[str, object]) -> None:
    txid = journal["txid"]
    cursor = journal["cursor"]
    for index, path in enumerate(_TARGETS):
        parent_kind, name = _temp_name(path, txid)
        parent_fd = root_fd if parent_kind == 0 else steward_fd
        expected = journal["temps"][path]
        state = _safe_file_state(parent_fd, name, PERSISTED_TARGET_MAX_BYTES[path])
        if index < cursor:
            if state is not None:
                raise ValueError("installed_temp_present")
            continue
        if expected is None:
            if state is not None:
                raise ValueError("unexpected_temp")
            continue
        _require_owned_file(parent_fd, name)
        candidate = journal["targets"][path]["candidate"]
        if (
            state is None
            or not _same_stat_identity(expected, state.identity)
            or hashlib.sha256(state.data).hexdigest() != candidate["sha256"]
            or len(state.data) != candidate["size"]
        ):
            raise ValueError("temp_foreign")


def _parent_state_matches(
    root_fd: int,
    steward_fd: int,
    path: str,
    expected: Mapping[str, int | str],
) -> int:
    parent_fd, _ = _parent_fd(root_fd, steward_fd, path)
    if not _same_identity(_parent_identity(parent_fd), expected):
        raise ValueError("recovery_parent_changed")
    return parent_fd


def _baseline_bytes(view: _View, journal: Mapping[str, object], path: str) -> bytes | None:
    baseline = journal["targets"][path]["baseline"]
    if not baseline["present"]:
        return None
    data = view.head_blobs.get(path)
    if data is None or hashlib.sha256(data).hexdigest() != baseline["sha256"] or len(data) != baseline["size"]:
        raise ValueError("recovery_baseline_unavailable")
    return data


def _fence_recovery_state(
    root_fd: int,
    steward_fd: int,
    journal: Mapping[str, object],
    candidates: PublicationCandidates,
    view: _View,
    cursor: int,
    restored: set[str],
    parent_states: Mapping[int, Mapping[str, int | str]],
) -> None:
    for index, path in enumerate(_TARGETS):
        record = journal["targets"][path]
        parent_fd, _ = _parent_fd(root_fd, steward_fd, path)
        parent_key = int(parent_fd)
        expected_parent = parent_states.get(parent_key, record["parent"])
        _parent_state_matches(root_fd, steward_fd, path, expected_parent)
        baseline = record["baseline"]
        state = _safe_file_state(parent_fd, path.removeprefix(".steward/"), PERSISTED_TARGET_MAX_BYTES[path])
        if path in restored:
            expected_data = _baseline_bytes(view, journal, path)
            if expected_data is None:
                if state is not None:
                    raise ValueError("recovery_target_present")
            elif state is None or state.data != expected_data or state.identity["mode"] != baseline["mode"]:
                raise ValueError("recovery_baseline_changed")
        elif index < cursor:
            installed = record["installed"]
            if (
                state is None
                or installed is None
                or not _same_stat_identity(installed, state.identity)
                or state.data != _candidate_bytes(candidates, path)
            ):
                raise ValueError("recovery_candidate_changed")
        elif baseline["present"]:
            if (
                state is None
                or not _same_stat_identity(baseline["target"], state.identity)
                or hashlib.sha256(state.data).hexdigest() != baseline["sha256"]
            ):
                raise ValueError("recovery_suffix_changed")
        elif state is not None:
            raise ValueError("recovery_suffix_present")


def _prepare_recovery_temp(
    root_fd: int,
    steward_fd: int,
    journal: Mapping[str, object],
    path: str,
    data: bytes,
    lease: PublisherLease,
) -> tuple[int, str]:
    parent_kind, name = _temp_name(path, journal["txid"])
    parent_fd = root_fd if parent_kind == 0 else steward_fd
    prior_parent = _parent_identity(parent_fd)
    if not lease.verify():
        raise ValueError("publisher_lease_changed")
    if _safe_file_state(parent_fd, name, PERSISTED_TARGET_MAX_BYTES[path]) is not None:
        raise ValueError("recovery_temp_present")
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
        dir_fd=parent_fd,
    )
    try:
        _write_all(descriptor, data)
        os.fsync(descriptor)
        value = os.fstat(descriptor)
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_nlink != 1
            or stat.S_IMODE(value.st_mode) != 0o600
            or value.st_uid != os.geteuid()
            or value.st_size != len(data)
        ):
            raise ValueError("recovery_temp_unsafe")
        identity = _identity(value, include_size=True)
    finally:
        os.close(descriptor)
    check = _safe_file_state(parent_fd, name, PERSISTED_TARGET_MAX_BYTES[path])
    if check is None or check.data != data or check.identity != identity:
        raise ValueError("recovery_temp_changed")
    os.fsync(parent_fd)
    if not _same_identity(prior_parent, _parent_identity(parent_fd)):
        raise ValueError("recovery_parent_changed")
    if not lease.verify():
        raise ValueError("publisher_lease_changed")
    return parent_fd, name


def _rollback_partial_transaction(
    root_fd: int,
    git_fd: int,
    steward_fd: int,
    journal_fd: int,
    journal: Mapping[str, object],
    candidates: PublicationCandidates,
    attestation: ConstitutionAttestation,
    view: _View,
    lease: PublisherLease,
    deadline: float,
) -> PublicationResult:
    cursor = journal["cursor"]
    _fence_targets(root_fd, steward_fd, journal, candidates, cursor)
    restored: set[str] = set()
    parent_states = {
        int(root_fd): _parent_identity(root_fd),
        int(steward_fd): _parent_identity(steward_fd),
    }
    for index in reversed(range(cursor)):
        if not lease.verify():
            raise ValueError("publisher_lease_changed")
        _fence_recovery_state(root_fd, steward_fd, journal, candidates, view, cursor, restored, parent_states)
        path = _TARGETS[index]
        baseline = journal["targets"][path]["baseline"]
        data = _baseline_bytes(view, journal, path)
        parent_fd, target_name = _parent_fd(root_fd, steward_fd, path)
        if data is None:
            if not lease.verify():
                raise ValueError("publisher_lease_changed")
            os.unlink(target_name, dir_fd=parent_fd)
            os.fsync(parent_fd)
            if not lease.verify():
                raise ValueError("publisher_lease_changed")
            if _safe_file_state(parent_fd, target_name, PERSISTED_TARGET_MAX_BYTES[path]) is not None:
                raise ValueError("recovery_unlink_failed")
            if not _same_identity(parent_states[int(parent_fd)], _parent_identity(parent_fd)):
                raise ValueError("recovery_parent_changed")
        else:
            _, temp_name = _prepare_recovery_temp(root_fd, steward_fd, journal, path, data, lease)
            _fence_recovery_state(root_fd, steward_fd, journal, candidates, view, cursor, restored, parent_states)
            if not lease.verify():
                raise ValueError("publisher_lease_changed")
            prior_parent = _parent_identity(parent_fd)
            os.replace(temp_name, target_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            descriptor = os.open(target_name, _OPEN_FILE, dir_fd=parent_fd)
            try:
                os.fchmod(descriptor, baseline["mode"])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            restored_state = _safe_file_state(parent_fd, target_name, PERSISTED_TARGET_MAX_BYTES[path])
            if (
                restored_state is None
                or restored_state.data != data
                or restored_state.identity["mode"] != baseline["mode"]
            ):
                raise ValueError("recovery_readback_failed")
            os.fsync(parent_fd)
            if not lease.verify():
                raise ValueError("publisher_lease_changed")
            if not _same_identity(prior_parent, _parent_identity(parent_fd)):
                raise ValueError("recovery_parent_changed")
        restored.add(path)
        current = _view(root_fd, git_fd, steward_fd, attestation, _safe_git()[0], deadline)
        if not _same_git_view(view, current) or not lease.verify():
            raise ValueError("git_changed_during_recovery")
    _fence_recovery_state(root_fd, steward_fd, journal, candidates, view, cursor, restored, parent_states)
    _cleanup_transaction(root_fd, steward_fd, journal_fd, journal, parent_states, lease=lease)
    return _result(PublicationState.BLOCKED, "recovered_rollback", journal["txid"])


def _validate_recovery_view_state(status: object, view: _View) -> None:
    if status == "replacing":
        if view.tree != view.index:
            raise ValueError("recovery_git_state_untrusted")
        if view.reason not in {
            "partial_generated_state",
            "generation_contract_invalid",
            "generation_not_head_bound",
            "head_bound_generation_valid",
            "all_targets_absent",
            "transaction_generation_present",
        }:
            raise ValueError("recovery_state_untrusted")
        return
    allowed = {
        "prepared": {observer.GenerationState.ABSENT, observer.GenerationState.VALID},
        "replaced": {observer.GenerationState.VALID, observer.GenerationState.UNBOUND},
        "read_back_validated": {observer.GenerationState.VALID, observer.GenerationState.UNBOUND},
    }
    if view.state not in allowed.get(status, set()):
        raise ValueError("recovery_state_untrusted")


def _validate_journal_binding(
    root_fd: int,
    git_fd: int,
    steward_fd: int,
    journal: Mapping[str, object],
    candidates: PublicationCandidates,
    attestation: ConstitutionAttestation,
    view: _View,
) -> None:
    snapshot_id, payload_hash, _ = _candidate_metadata(candidates)
    if (
        journal["reviewed_head"] != view.head
        or journal["snapshot_id"] != snapshot_id
        or journal["payload_hash"] != payload_hash
        or journal["c0_sha256"] != attestation.c0_sha256
        or journal["source_blob"] != attestation.source_blob
    ):
        raise ValueError("journal_binding")
    current_repository = {
        "root": _parent_identity(root_fd),
        "git": _parent_identity(git_fd),
        "steward": _parent_identity(steward_fd),
    }
    if any(not _same_identity(journal["repository"][key], current_repository[key]) for key in current_repository):
        raise ValueError("repository_binding")
    for path in _TARGETS:
        data = _candidate_bytes(candidates, path)
        descriptor = journal["targets"][path]["candidate"]
        if descriptor["sha256"] != hashlib.sha256(data).hexdigest() or descriptor["size"] != len(data):
            raise ValueError("candidate_binding")


def _recover_existing(
    root_fd: int,
    git_fd: int,
    steward_fd: int,
    journal_name: str,
    attestation: ConstitutionAttestation,
    candidates: PublicationCandidates,
    deadline: float,
    lease: PublisherLease,
) -> PublicationResult:
    journals, temps, unknown = _scan_namespace(root_fd, steward_fd)
    if unknown or journals != [journal_name]:
        return _result(PublicationState.MANUAL_REVIEW, "transaction_namespace_ambiguous")
    try:
        journal_fd, journal = _open_journal(steward_fd, journal_name)
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        return _result(PublicationState.MANUAL_REVIEW, "journal_invalid")
    try:
        _validate_transaction_namespace(root_fd, steward_fd, journal)
        git, _ = _safe_git()
        view = _view(root_fd, git_fd, steward_fd, attestation, git, deadline)
        _validate_recovery_view_state(journal["status"], view)
        _validate_journal_binding(root_fd, git_fd, steward_fd, journal, candidates, attestation, view)
        _validate_transaction_files(root_fd, steward_fd, journal)
        status = journal.get("status")
        cursor = journal.get("cursor")
        if status == "prepared" and cursor == 0:
            _fence_targets(root_fd, steward_fd, journal, candidates, 0)
            current = _view(root_fd, git_fd, steward_fd, attestation, _safe_git()[0], deadline)
            if not _same_git_view(view, current) or not lease.verify():
                raise ValueError("git_changed_during_recovery")
            _cleanup_transaction(root_fd, steward_fd, journal_fd, journal, lease=lease)
            return _result(PublicationState.BLOCKED, "recovered_prepared", journal["txid"])
        if status in {"replaced", "read_back_validated"} and cursor == 4:
            _fence_targets(root_fd, steward_fd, journal, candidates, 4)
            current = _view(root_fd, git_fd, steward_fd, attestation, _safe_git()[0], deadline)
            if not _same_git_view(view, current) or not lease.verify():
                raise ValueError("git_changed_during_recovery")
            _cleanup_transaction(root_fd, steward_fd, journal_fd, journal, lease=lease)
            return _result(PublicationState.PUBLISHED, "recovered_generation", journal["txid"])
        if status == "replacing" and isinstance(cursor, int) and 1 <= cursor <= 3:
            return _rollback_partial_transaction(
                root_fd,
                git_fd,
                steward_fd,
                journal_fd,
                journal,
                candidates,
                attestation,
                view,
                lease,
                deadline,
            )
        return _result(PublicationState.MANUAL_REVIEW, "recovery_state_invalid", journal["txid"])
    except (OSError, ValueError, ContractViolation, TimeoutError, observer._ObservationFailure) as error:
        return _result(PublicationState.MANUAL_REVIEW, type(error).__name__.lower(), journal.get("txid"))
    finally:
        os.close(journal_fd)


def _safe_git() -> tuple[str, tuple[int, ...]]:
    return observer._safe_executable(("/usr/bin/git", "/bin/git"))


def publish_context(
    repository_root: Path,
    payload: Mapping[str, object],
    snapshot: Mapping[str, object],
    attestation: ConstitutionAttestation,
    *,
    mode: PublicationMode | str = PublicationMode.DISABLED,
    lease: PublisherLease | None = None,
) -> PublicationResult:
    """Publish one validated generation; canonical mode is never caller-wired."""
    try:
        selected_mode = mode if isinstance(mode, PublicationMode) else PublicationMode(mode)
    except (TypeError, ValueError):
        selected_mode = PublicationMode.DISABLED
    try:
        candidates = build_publication_candidates(payload, snapshot)
        validate_constitution_bound_persisted_generation(candidates, attestation)
    except (ContractViolation, TypeError, ValueError, KeyError, UnicodeError):
        return _result(PublicationState.BLOCKED, "candidate_invalid")
    if selected_mode is PublicationMode.DISABLED:
        return _result(PublicationState.BLOCKED, "disabled")
    if selected_mode is PublicationMode.PREVIEW:
        return _result(PublicationState.BLOCKED, "preview_only")
    if selected_mode is PublicationMode.CANONICAL and sys.platform == "darwin":
        return _result(PublicationState.MANUAL_REVIEW, "unsupported_platform")
    if not isinstance(repository_root, Path) or not repository_root.is_absolute():
        return _result(PublicationState.BLOCKED, "repository_path_invalid")
    if not isinstance(lease, PublisherLease):
        return _result(PublicationState.BLOCKED, "publisher_lease_required")
    if lease.repository_root != repository_root or not lease.verify():
        return _result(PublicationState.BLOCKED, "publisher_lease_invalid")
    root_fd = lease.root_fd
    git_fd = lease.git_fd
    steward_fd = lease.steward_fd
    deadline = lease.deadline
    try:
        if not lease.verify():
            return _result(PublicationState.MANUAL_REVIEW, "publisher_lease_changed")
        git, _ = _safe_git()
        # Namespace state is read only after the exclusive lease exists.
        journals, temps, unknown = _scan_namespace(root_fd, steward_fd)
        if unknown or len(journals) > 1:
            return _result(PublicationState.MANUAL_REVIEW, "transaction_namespace_ambiguous")
        if journals or temps:
            if len(journals) != 1:
                return _result(PublicationState.MANUAL_REVIEW, "transaction_journal_missing")
            result = _recover_existing(
                root_fd, git_fd, steward_fd, journals[0], attestation, candidates, deadline, lease
            )
            if result.state in {PublicationState.PUBLISHED, PublicationState.NO_OP} and not lease.verify():
                return _result(PublicationState.MANUAL_REVIEW, "publisher_lease_changed", result.transaction_id)
            return result
        before = _view(root_fd, git_fd, steward_fd, attestation, git, deadline)
        if before.state not in {observer.GenerationState.ABSENT, observer.GenerationState.VALID}:
            return _result(PublicationState.MANUAL_REVIEW, f"baseline_{before.state.value}")
        after = _view(root_fd, git_fd, steward_fd, attestation, git, deadline)
        if not _same_view(before, after):
            return _result(PublicationState.MANUAL_REVIEW, "repository_changed_before_transaction")
        if before.state is observer.GenerationState.VALID:
            current_states = {}
            for path in _TARGETS:
                parent_fd, name = _parent_fd(root_fd, steward_fd, path)
                current_states[path] = _safe_file_state(parent_fd, name, PERSISTED_TARGET_MAX_BYTES[path])
                current = current_states[path]
                tree_target = before.tree.get(path)
                if (
                    current is not None
                    and tree_target is not None
                    and current.identity["mode"] != int(tree_target.mode, 8) & 0o777
                ):
                    return _result(PublicationState.MANUAL_REVIEW, "baseline_mode_unexpected")
            if all(
                current_states[path] is not None and current_states[path].data == _candidate_bytes(candidates, path)
                for path in _TARGETS
            ):
                try:
                    _final_no_op_fence(
                        root_fd,
                        git_fd,
                        steward_fd,
                        attestation,
                        git,
                        deadline,
                        before,
                        candidates,
                        lease,
                    )
                except (OSError, ValueError, ContractViolation, TimeoutError, observer._ObservationFailure) as error:
                    return _result(PublicationState.MANUAL_REVIEW, str(error) or type(error).__name__.lower())
                return _result(PublicationState.NO_OP, "already_published")
        result = _create_transaction(root_fd, git_fd, steward_fd, after, candidates, attestation, lease)
        if result.state in {PublicationState.PUBLISHED, PublicationState.NO_OP} and not lease.verify():
            return _result(PublicationState.MANUAL_REVIEW, "publisher_lease_changed", result.transaction_id)
        return result
    except (OSError, ValueError, ContractViolation, TimeoutError, observer._ObservationFailure) as error:
        return _result(PublicationState.MANUAL_REVIEW, type(error).__name__.lower())
