# Context Bridge Slice E — Bootstrap and Publisher Isolation

**Status:** DRAFT 0.4 — E0 architecture decisions closed; implementation forbidden

**Parent contract:** `FEATURE_01_SLICE_D2B_WRITER_POLICY_PREFLIGHT.md`,
`FEATURE_01_SLICE_D2B_G2_PREFLIGHT.md`

**Recon pin:** `origin/main` at `8f996ac519830228fc8647a6d9256de1b242b9a8`

**Pinned tree:** `c83ba08a3414b47aecbcf9314368e940b14c5379`

**Pin drift:** Compared with the initial E0 base `9bc785337103d94dfe70c26510030ac05e618135`,
`origin/main` advanced only in runtime/federation state: `.steward/.context_hash`,
`.steward/context.json`, `.steward/federation_health.json`,
`.steward/marketplace.json`, `.steward/sessions.json`,
`data/federation/nadi_inbox.json`, `data/federation/nadi_outbox.json`,
`data/federation/peers.json`, `data/federation/quarantine/index.json`,
`data/federation/relay_seen_ids.json`, and `data/federation/steward_health.json`.
No E0 source, spec, or implementation path is overlapped by that drift.

**Pin semantics:** The commit and tree above are the immutable evidence point,
not a claim that the moving `main` alias will still equal them at review time.
Before review or merge, `pin..origin/main` must be queried and reported. Drift
limited to the eleven runtime/federation paths listed above does not require a
new documentation commit; any product, workflow, test, policy, or Context-
Bridge-spec drift invalidates the pin and requires a new comparison or repin.

**Related unmerged code:** PR #728, head `e280e199f111776c132713d4fec05fabe57041d5`

## 1. Purpose

Slice E defines the missing execution boundary required before the D2b local
transaction primitive can receive a G2 approval. It must create and attest a
dedicated publisher process and an ephemeral publisher worktree. It does not
change the normal Steward checkout, existing writers, heartbeat workflow,
remote delivery, or canonical activation.

The current D2b primitive consumes an isolation capability but does not create
one. This document specifies the capability issuer and the evidence required to
prove that the issuer is a real boundary rather than a structural Python
object.

## 2. Recon findings

### 2.1 Existing clone workspace is not Slice E

`steward/autonomy.py:534-580` implements `_cross_repo_workspace()`. It creates a
shallow clone under `/tmp`, swaps `pipeline._cwd` and the circuit-breaker cwd in
the current process, then removes the directory. It has no dedicated publisher
process, no capability issuance, no protected FD set, no source/delivery fence,
and no adversarial proof that the normal process cannot access the workspace.
It is therefore not an acceptable D2b bootstrap.

### 2.2 Existing child process is read-only evidence only

`steward/context_publisher.py:268-330` contains `_bounded_process()`. Its
allowlisted child is used for bounded Git observation with one passed FD. It
does not own a worktree, accept publication input, replace targets, recover a
journal, or issue a publisher capability. It cannot be reused as an implicit
write boundary without a separately reviewed contract.

### 2.3 Current D2b capability is consumer-side only

PR #728's `PublisherIsolation` binds a concrete object to a PID, root/.git/
`.steward` FDs, directory anchors, and the repository path. That closes
structural duck typing and path/FD mismatch, but its bootstrap issuer is absent.
The capability must not be treated as proof of isolation until Slice E produces
it from the dedicated process/worktree boundary and records the evidence.

## 3. Scope

Slice E may add only the following, on its own branch and PR:

1. An allowlisted publisher-process entrypoint.
2. Ephemeral isolated-worktree creation and destruction.
3. A non-forgeable capability issuance protocol bound to that process and
   worktree.
4. Structured supervisor/worker IPC for inputs, result, and failure state.
5. Direct adversarial tests and durable evidence for the gates in §8.

Slice E must not:

- wire a normal Steward caller to canonical publication;
- modify `CLAUDE.md`, `AGENTS.md`, runtime state, heartbeat staging, or delivery;
- add a second renderer, parser, source of truth, or writer registry;
- bypass the D2b journal, parent, target, Git, read-back, or recovery contract;
- push directly to `main` or create an automatic PR;
- treat a lock, a Python class, an environment flag, or a test-only marker as
  isolation evidence.

## 4. Required architecture

The following choices are normative for Slice E. There is no Clone-vs-worktree,
UID-vs-namespace, or transport fallback in this slice.

### 4.1 Bootstrap inputs

The issuer accepts one structured input object containing exactly:

- immutable source repository identity and reviewed commit;
- Constitution attestation and one explicit snapshot reference;
- delivery base identity (reference only; no delivery in Slice E);
- bounded transaction/deadline parameters from the approved D2b contract.

No arbitrary shell text, tool name, provider data, path override, environment
override, or caller-selected executable is accepted. The complete machine
contract is the `START` payload in §5.2; this prose list does not create a
second permissive input schema.

### 4.2 Dedicated process

The publisher worker runs on Linux inside a verified Bubblewrap executable with
a private user, mount, PID, IPC, UTS, and network namespace. Bubblewrap is a
required platform dependency, not an optional optimization; if the executable
or any required namespace is unavailable, the operation returns
`manual_review` before a lock or workspace is created. No alternate isolation
primitive is accepted by this slice.

The supervisor opens `/usr/bin/bwrap` once, dirfd-relative beneath a pinned
`/usr/bin` FD, with `openat2(RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|
RESOLVE_NO_MAGICLINKS)` and `O_RDONLY|O_CLOEXEC`. It hashes and executes that
same descriptor and verifies the regular-file, root-owned,
non-group/world-writable stat tuple and SHA-256 from the runtime manifest. It
never executes Bubblewrap by path. The reviewed native launch shim
calls `clone3(CLONE_PIDFD|CLONE_INTO_CGROUP|SIGCHLD)` with the pre-opened
per-request cgroup-v2 FD, so child creation, cgroup placement, and the supervisor
pidfd are one kernel operation. The child performs only async-signal-safe FD setup
and calls `execveat(bwrap_fd, "", argv, empty_env, AT_EMPTY_PATH)`. Failure of
`clone3`, pidfd creation, FD setup, or `execveat` is `manual_review` before a
workspace, lock, journal, tempfile, or target exists. `fork()` followed by
`pidfd_open()`, path-based `execve()`, and `subprocess.Popen()` are forbidden
launch paths.

The fixed cgroup-v2 subtree is
`/sys/fs/cgroup/steward-publisher.slice/context-publisher-v1`, delegated by the
service installation to supervisor UID/GID `65532` and not writable by a normal
Steward process. Before `clone3`, the supervisor creates and opens exactly the
`<request_id>` child cgroup dirfd, verifies its parent/identity/controllers, and
records its inode. `CLONE_INTO_CGROUP` is mandatory. Missing cgroup v2,
delegation, `cgroup.kill`, or an atomically usable cgroup FD is unsupported and
returns `manual_review` before spawn.

The exact `execveat` argv is:

```text
[FD 6: verified /usr/bin/bwrap; execveat(AT_EMPTY_PATH)]
  --die-with-parent --new-session --unshare-all
  --uid 65532 --gid 65532
  --clearenv
  --preserve-fd 3 --preserve-fd 4 --preserve-fd 5
  --ro-bind /proc/self/fd/5 /
  --dir /input
  --ro-bind /proc/self/fd/4 /input/source.bundle
  --tmpfs /work
  --proc /proc --dev /dev --tmpfs /tmp
  --chdir /work
  --setenv LANG C
  --setenv LC_ALL C
  --setenv PATH /usr/bin:/bin
  --setenv GIT_OPTIONAL_LOCKS 0
  --setenv GIT_NO_REPLACE_OBJECTS 1
  --setenv GIT_PAGER cat
  --setenv GIT_CONFIG_NOSYSTEM 1
  --setenv GIT_CONFIG_GLOBAL /dev/null
  --setenv GIT_CONFIG_SYSTEM /dev/null
  -- /usr/bin/python3.12 -I -S -m steward.publisher_worker --ipc-fd 3
```

FD 3 is the authenticated IPC socket, FD 4 is the read-only sealed source
bundle, FD 5 is the root-owned immutable runtime-root directory, and FD 6 is
the verified Bubblewrap executable consumed by `execveat`. Only FDs 3, 4, and
5 cross the Bubblewrap launch. All three `--preserve-fd` arguments are
mandatory. A launch that cannot preserve exactly those FDs is unsupported and
returns `manual_review` before any workspace or transaction namespace exists.
`--clearenv` is mandatory. The only worker environment variables are the nine
`LANG`/`LC_ALL`/`PATH`/`GIT_*` assignments shown above; every other inherited
variable, loader variable, proxy, credential, and unlisted `GIT_*` override is
absent. The six approved D2b Git variables (`GIT_OPTIONAL_LOCKS`,
`GIT_NO_REPLACE_OBJECTS`, `GIT_PAGER`, `GIT_CONFIG_NOSYSTEM`,
`GIT_CONFIG_GLOBAL`, and `GIT_CONFIG_SYSTEM`) are the complete Git allowlist.

The worker validates the mounted runtime manifest and closes FD 5. It creates a
full clone with
`git clone --no-local --no-hardlinks /input/source.bundle /work/repo`, performs
the source verification in §4.4, and closes FD 4 before opening the D2b
transaction namespace. The clone has an independent index and no `commondir`,
`gitdir`, alternates, or foreign-index redirection. The worktree exists only in
the private tmpfs namespace. No host path to `/work` is passed to the supervisor
or a normal Steward process.

The launch contract records and enforces the exact executable identities,
`argv`, empty host environment, worker environment, CWD, umask, UID/GID,
process group, FD allowlist, deadlines, timeout/reaping behavior, and terminal
wait status. The worker loads no normal Steward registry, Bash, GitTool,
child-agent, LLM, healer, actuator, or delivery callback. It may use only the
manifested Git executable, reviewed read-only Git plumbing, and D2b transaction
primitive. Generic subprocess execution is prohibited. Bubblewrap,
`/usr/bin/python3.12`, Git, native runtime files, Python files, and the worker
entrypoint are verified against §4.6 before launch.

### 4.3 Ephemeral publisher worktree

The bootstrap creates the private tmpfs workspace described in §4.2. It is not
a detached worktree in the human checkout and is never addressed by a host
filesystem path. The workspace must have:

- a distinct worktree path and independent index;
- a validated Git object relationship to the pinned source commit;
- no `commondir`, `gitdir`, alternates, symlink, hardlink, or foreign-index
  redirection;
- root and `.steward` parents owned by the worker identity, mode-checked, and
  pinned by FD before any journal or target read;
- namespace destruction tied to worker exit; no parent-side recursive delete;
- an evidence-preserving terminal decision before the worker exits;
- a source/delivery identity that is recorded but never inferred from a path.

The bootstrap must prove the source is a read-only bind and the destination is
tmpfs inside the worker namespace. A path under `/tmp` alone is not proof.

### 4.4 Source handoff and identity

The supervisor never hands Bubblewrap a caller-controlled repository path. It
opens the source repository root and `.git` directory using the approved D2a
root-/Git-FD procedure: safe dirfd-relative opens, unsupported-layout rejection,
parent/layout fingerprints, `HEAD^{commit}`, `HEAD^{tree}`, complete target
tree/index evidence, and a second identical Git-evidence round after export.
Both rounds must bind the same repository/Git inodes, reviewed 40-lower-hex
commit, tree ID, index, target blobs, and layout fingerprint. For each of the
four Context targets, tree and index must either both be absent or contain the
same stage-0 `100644` blob. A one-sided absence, staged/unmerged entry, foreign
path, blob mismatch, or different mode is `manual_review`. This preserves the
approved `legacy_bootstrap` baseline instead of inventing four-file presence.

The source Git executable is opened and hash/stat-verified from the same closed
runtime manifest as §4.6 and executed from its FD with `execveat`, never by
`PATH` or a re-resolved absolute path. With the source `.git` FD passed and
bound exactly as in D2a, the sole export command is:

```text
git --git-dir=/proc/self/fd/<source-git-fd> bundle create - HEAD
```

Its host environment is exactly the nine-variable D2b allowlist, its stdout is
streamed directly into a private `memfd_create(MFD_ALLOW_SEALING)` descriptor,
stderr is capped at 4,096 bytes, the bundle is capped at 67,108,864 bytes, and
the existing five-second command/twenty-second total deadlines apply. Nonzero
exit, timeout, short write, output at limit plus one, source-FD drift, Git-layout
drift, or either Git-evidence-round mismatch is `manual_review`; no partial
bundle is launched.

After the second evidence round, the supervisor hashes the bundle and seals it
with `F_SEAL_WRITE|F_SEAL_SHRINK|F_SEAL_GROW|F_SEAL_SEAL`. It then runs the
same FD-executed Git binary with `bundle verify /proc/self/fd/<bundle-fd>` and
`bundle list-heads /proc/self/fd/<bundle-fd>`. Verification must succeed and
`list-heads` stdout must be byte-exact `<reviewed_head> HEAD\n`; each metadata
command has the same five-second deadline, 16,384-byte stdout cap, and
4,096-byte stderr cap. After sealing, the
supervisor reopens the memfd through its own `/proc/self/fd/<n>` entry with
`O_RDONLY|O_CLOEXEC`, closes the writable original, and retains that read-only
duplicate as FD 4. It records the source root/Git identities, both evidence
rounds, reviewed commit/tree, exact Git argv/environment, bundle stat/seal
tuple, bundle size, and SHA-256. No caller path or mutable directory is part of
the handoff.

Bubblewrap resolves `--ro-bind /proc/self/fd/4 /input/source.bundle` from that
sealed descriptor and receives no source path other than this proc-fd
reference. A platform or Bubblewrap build that cannot bind this descriptor
without falling back to a path lookup is unsupported and must return
`manual_review`. The supervisor verifies FD 4 with `fstat()`, its seal mask, and
its canonical bundle hash immediately before spawn, after the worker
handshake, and before terminal evidence; any change is impossible under the
seal contract and is nevertheless a `manual_review` result. FD 4 remains open
until the worker has sent terminal evidence and the supervisor has fsynced it. It
is then closed, allowing the ephemeral memfd to disappear. No source, root, or
mutation FD is sent with `SCM_RIGHTS`.

Inside the namespace, after cloning, the worker requires
`rev-parse --verify HEAD == rev-parse --verify HEAD^{commit} == reviewed_head`,
`rev-parse --verify HEAD^{tree} == reviewed_tree`, and the same four target
tree blobs/modes/absences as the source evidence. Any extra bundle head, prerequisite,
missing object, commit/tree mismatch, or clone redirection is `manual_review`
before the capability or transaction namespace exists.

### 4.5 Capability issuance

The capability is worker-local. No root, `.git`, `.steward`, target, journal, or
tempfile FD crosses the process boundary. The supervisor receives only a bounded
attestation/result record over the authenticated channel. The issuer returns an
opaque capability only inside the dedicated worker after all of these checks
pass:

- worker process-group identity and worker-start nonce are pinned; the worker
  PID is diagnostic metadata bound to that nonce, while the supervisor authority is
  the supervisor pidfd;
- root, `.git`, and `.steward` FDs are opened with safe flags and bound to the
  same repository root;
- the path-to-FD binding is proven twice around bootstrap handoff;
- the worktree identity, source commit, Git layout fingerprint, and workspace
  lease are recorded in the attestation;
- the capability cannot be constructed by a caller-provided class, boolean,
  path, or arbitrary token value;
- revocation/worker exit makes every later lease verification fail closed;
  `pidfd` HUP/exit is the revocation signal.

The D2b consumer must reject a capability with a missing bootstrap nonce,
worker-PID/start-identity mismatch against the authenticated handshake,
wrong namespace/worktree identity, changed parent, changed Git layout, or
expired/revoked lease. A numeric PID alone is never sufficient. A capability
is never reconstructed from JSON, a Python class, or a caller-provided path.

### 4.6 Worker-code provenance

Slice E uses exactly CPython 3.12 at `/usr/bin/python3.12`; no interpreter
selection or symlink resolution occurs at launch. A reviewed build produces one
content-addressed runtime directory beneath the fixed, root-owned
`/var/lib/steward/publisher-runtime-v1` anchor. The supervisor opens the anchor
and selected hash-named child dirfd-relatively with `openat2` and the same
no-symlink/no-magiclink constraints as §4.2, verifies owner `0`, directory mode
`0555`, and retains the child as FD 5. The normal Steward process cannot choose
the runtime path or manifest hash. Root/host compromise is outside this slice's
threat model; group/world-writable or non-root-owned runtime material is always
`manual_review`.

The canonical `steward.publisher-runtime.v1` manifest has exactly these top
level keys: `schema`, `reviewed_commit`, `platform`, `python_abi`, `entries`,
and `host_executables`. `platform` is exactly `linux-x86_64`; `python_abi` is
exactly `cpython-312`. It uses the §5.1 canonical JSON rules, is at most
8,388,608 bytes, contains at most 65,535 entries, and describes at most
536,870,912 total regular-file bytes; any one regular file is at most
67,108,864 bytes. `entries` is sorted by UTF-8 relative path and contains
every node below the runtime root except the byte-identical
`usr/share/steward-publisher/runtime-manifest.json` copy. Each entry has exactly
`path`, `kind`, `mode`, `uid`, `gid`, `size`, `sha256`, `role`, and `git_blob`:

- `kind` is `directory` or `regular`; symlinks, hardlinks (`st_nlink != 1` for
  regular files), sockets, devices, and FIFOs are forbidden;
- directories are root-owned mode `0555`, with `size`, `sha256`, and
  `git_blob` set to `null`;
- regular files are root-owned mode `0444` or `0555`, have bounded integer
  `size`, lowercase-hex SHA-256, and `git_blob` only for repository-derived
  files;
- `role` is one of `python`, `python_stdlib`, `python_native`, `worker`,
  `git`, `git_core`, `git_template`, `elf_loader`, or `shared_library`.

The closed entry set contains `/usr/bin/python3.12`, the complete packaged
Python 3.12 standard library and `lib-dynload`, the worker entrypoint and every
importable Steward module in its reviewed static import closure, `/usr/bin/git`,
every invoked `git-core` helper, Git templates, the ELF loader, and the complete
transitive `DT_NEEDED` shared-library closure for all native executables and
modules. The build rejects dynamic imports outside this set. Runtime validation
walks FD 5 without following links and rejects any missing, extra, changed, or
unmanifested node; it does not infer dependencies from whatever happened to load
in one test run.

`host_executables` contains exactly the reviewed native launch shim,
`/usr/bin/bwrap`, and the source-export `/usr/bin/git`, each with absolute
install path, owner/mode/stat identity, size, SHA-256, ELF build ID, reviewed
build/source identity, and the exact root-owned non-writable loader/`DT_NEEDED`
host dependency identities. All three executables are opened once and later
executed only with `execveat(AT_EMPTY_PATH)`; host dependency drift is checked
immediately before launch and root compromise is outside the threat model. The canonical
manifest bytes contain no self-hash. Their SHA-256 is the
`runtime_manifest_sha256`; the runtime root contains a byte-identical manifest
copy, and the hash-named runtime directory name equals that digest. The supervisor
input, pre-spawn evidence, worker `HELLO`, and terminal result all bind this
digest.

The supervisor validates the complete manifest/tree and host executables before
`clone3`; the worker validates the mounted manifest copy and complete runtime
tree before importing the publisher entrypoint. A mismatch returns
`manual_review` before the worktree, capability, lock, or transaction namespace
exists. E1 must archive the manifest bytes and demonstrate both one missing-file
and one extra-file rejection; a mocked dependency set is not evidence.

## 5. IPC and lifecycle contract

Supervisor and worker communicate over one Unix `SOCK_SEQPACKET` socketpair
created before `clone3`, with `SO_PASSCRED` enabled before launch and inherited
only as FD 3. The supervisor pidfd returned atomically by `clone3` binds the
outer Bubblewrap process and closes PID-reuse ambiguity. The inner worker PID
is diagnostic metadata bound to the one-use worker-start nonce, peer
credentials, namespace inode, and process start ticks; it is never an
independent authority.

`SO_PEERCRED` and per-message `SCM_CREDENTIALS` authenticate the socket peer.
The namespace UID `65532` is not assumed to have the same host integer. The
worker `HELLO` reports exact `uid_map`, `gid_map`, effective UID/GID
`65532/65532`, PID-namespace inode, process group, and start ticks. The
supervisor derives the expected kernel-translated `(pid,uid,gid)` from that map
and the launched process identity and requires every message's credentials to
match. E1 must archive the real Ubuntu observations; a mocked credential or
numeric-PID-only test is not evidence.

### 5.1 Canonical encoding and envelope

Before the preflight evidence event, the supervisor generates an independent
16-byte `request_id` and 32-byte `bootstrap_nonce` and `worker_start_nonce`
values with `getrandom(2)` and records all three. The envelope `nonce` is the
bootstrap nonce; `START` carries the request ID and worker-start nonce and
`HELLO` must echo both. The worker generates each 16-byte transaction ID and
fence token with `getrandom(2)` inside the namespace.

IPC uses RFC 8785 JSON Canonicalization Scheme bytes with additional closed
constraints: UTF-8 without BOM, Unicode NFC strings, no duplicate keys, no
unpaired surrogates or C0/C1 controls, no floats, integers only in
`[-9007199254740991, 9007199254740991]`, maximum nesting depth 8, maximum key
length 64 UTF-8 bytes, and maximum string length 8,192 UTF-8 bytes unless a
field below has a smaller limit. Objects with unknown keys and noncanonical
bytes are rejected. `hex32`, `hex40`, and `hex64` mean exact lowercase ASCII
hex lengths; `nonce64` is 64 lowercase hex characters encoding 32 random bytes.

Every datagram has exactly these seven top-level keys and no others:

```json
{
  "schema": "steward.publisher.ipc/v1",
  "direction": "supervisor_to_worker",
  "nonce": "nonce64",
  "sequence": 0,
  "message_type": "START",
  "payload_hash": "hex64",
  "payload": {}
}
```

`payload_hash` is SHA-256 over the independently canonicalized `payload` object
only. The complete envelope is then canonicalized again. Sequence is a
gap-free unsigned integer beginning at zero per direction; supervisor and
worker maintain independent counters. The `direction` is exactly
`supervisor_to_worker` or `worker_to_supervisor`. A nonce, socket, and sequence
space are single-launch and never reused. Hash, nonce, credential, direction,
sequence, schema, type, size, or ordering failure is terminal
`protocol_error`, followed by evidence-preserving `manual_review` and worker
termination.

### 5.2 Closed messages and payloads

The positive message order is `START`, `HELLO`, `ATTESTATION`, zero or more
`FENCE_READY`/`RELEASE` pairs, `RESULT`, `SHUTDOWN`, and `SHUTDOWN_ACK`.
`ERROR` may replace the next expected worker message at any stage after a valid
`START` and is terminal before `SHUTDOWN`; it may not follow `RESULT` or another
`ERROR`. No other type or transition exists. Payloads contain exactly the
following keys:

| Type | Direction | Maximum envelope | Exact payload keys |
|---|---|---:|---|
| `HELLO` | worker → supervisor | 16,384 | `request_id`, `worker_start_nonce`, `runtime_manifest_sha256`, `source_bundle_sha256`, `uid_map`, `gid_map`, `effective_uid`, `effective_gid`, `peer_pid`, `process_group`, `process_start_ticks`, `pid_namespace_inode` |
| `START` | supervisor → worker | 196,608 | `request_id`, `worker_start_nonce`, `reviewed_head`, `reviewed_tree`, `source_bundle_sha256`, `runtime_manifest_sha256`, `constitution`, `snapshot_id`, `snapshot`, `delivery_base`, `deadlines_ms` |
| `ATTESTATION` | worker → supervisor | 32,768 | `request_id`, `reviewed_head`, `reviewed_tree`, `runtime_manifest_sha256`, `source_bundle_sha256`, `worktree_identity`, `git_layout_hash`, `capability_hash` |
| `FENCE_READY` | worker → supervisor | 4,096 | `request_id`, `txid`, `target_index`, `fence_token`, `fence_hash` |
| `RELEASE` | supervisor → worker | 2,048 | `request_id`, `txid`, `target_index`, `fence_token` |
| `RESULT` | worker → supervisor | 65,536 | `request_id`, `result_class`, `failure_class`, `txid`, `reviewed_head`, `reviewed_tree`, `snapshot_id`, `payload_hash`, `target_hashes`, `attestation_hash`, `evidence_hash` |
| `ERROR` | worker → supervisor | 8,192 | `request_id`, `failure_class`, `stage`, `evidence_hash` |
| `SHUTDOWN` | supervisor → worker | 1,024 | `request_id`, `terminal_evidence_hash` |
| `SHUTDOWN_ACK` | worker → supervisor | 1,024 | `request_id`, `terminal_evidence_hash` |

`request_id`, `txid`, and `fence_token` are `hex32`; `worker_start_nonce` is
`nonce64`; hashes and snapshot IDs are `hex64`; Git commit/tree IDs are
`hex40`; `target_index` is integer `0..3`.
`uid_map` and `gid_map` are arrays of exactly three bounded integers, not free
text. `worktree_identity` contains exact integer `device`, `inode`, `mode`,
`uid`, `gid`, `link_count`, `mount_namespace_inode`, and
`pid_namespace_inode`. `target_hashes` has exactly `claude`, `agents`,
`snapshot`, and `publication` `hex64` keys or is `null` before candidates
exist.

The `START.constitution` object contains exactly `reviewed_commit` (`hex40`),
`source_blob` (`hex40`), and `c0_sha256` (`hex64`). `START.snapshot` is the
already validated Feature-04 `steward.context.snapshot/v1` object and its own
canonical bytes may not exceed 131,072. `START.delivery_base` contains exactly
`repository_id` (1..128 lowercase ASCII `[a-z0-9._/-]`) and `reviewed_head`
(`hex40`); it is reference-only. `START.deadlines_ms` contains exactly
`startup=5000`, `operation=20000`, and `shutdown=5000`. The worker recomputes
the snapshot ID, requires the snapshot repository head and Constitution fields
to equal the separate reviewed head/attestation fields, and rejects a mismatch
before rendering. No candidate bytes,
path, environment, exception text, secret, or untyped mapping crosses IPC.

`result_class` is exactly one of `published`, `no_op`, `blocked`, or
`manual_review`. `failure_class` is `null` for a positive result or exactly one
of `invalid_input`, `unsupported_platform`, `runtime_mismatch`,
`source_mismatch`, `spawn_failure`, `credential_mismatch`, `protocol_error`,
`timeout`, `isolation_breach`, `d2b_blocked`, `d2b_manual_review`,
`worker_crash`, `supervisor_crash`, `evidence_failure`, or `shutdown_failure`. `stage` is one of
`preflight`, `spawn`, `handshake`, `source`, `workspace`, `attestation`,
`transaction`, `read_back`, `cleanup`, or `shutdown`. No raw exception text or
caller-selected detail field is allowed.

For `published` or `no_op`, `failure_class` is `null` and `txid`, snapshot ID,
payload hash, all four target hashes, attestation hash, and evidence hash are
non-null and validated. For `blocked` or `manual_review`, `failure_class` is
non-null; `txid`, payload/target hashes, and attestation hash may be `null` only
if their stage was never reached. `reviewed_head`, `reviewed_tree`, snapshot ID,
and evidence hash are always non-null. `ERROR` is terminal and semantically
equivalent to `manual_review`; it exists only for failure before a complete
`RESULT` can be constructed.

FD 4 and FD 5 are launch-only read-only inputs described in §4.2. No target,
journal, tempfile, root, `.git`, `.steward`, or other FD is sent with
`SCM_RIGHTS`; all mutation FDs remain inside the worker namespace.

### 5.3 Crash-surviving evidence channel

The evidence root is exactly
`/var/lib/steward/context-publisher/evidence-v1`. Installation creates
`/var/lib/steward/context-publisher` as `root:65532` mode `0750` and
`evidence-v1` as host UID/GID `65532:65532` mode `0700`. The Slice-E supervisor
runs as dedicated host UID/GID `65532:65532`; a normal Steward process must not
run as or gain write capability for that identity. The supervisor opens the
root from a pinned `/var/lib/steward/context-publisher` directory FD with
`openat2` no-symlink/no-magiclink constraints and validates device, inode,
type, owner, mode, and link count before accepting a request and before every
evidence mutation. A missing, replaced, multiply linked, differently owned, or
writable evidence root is `manual_review` before worker spawn. Root/supervisor-
UID compromise remains outside the declared threat model.

Each request gets exactly one `request_id` directory, created dirfd-relatively
with mode `0700` and `mkdirat`; preexistence is `manual_review`. Evidence is a
hash chain of immutable event files, not an append stream. Event `N` is RFC-8785
canonical JSON with exactly `schema`, `request_id`, `event_sequence`,
`previous_event_hash`, `stage`, `ipc_envelope_hash`, `credentials`, `pidfd_state`,
`failure_class`, and `facts`. It is at most 262,144 bytes. The supervisor writes
it to `.<8-digit-sequence>.tmp` with
`O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW` mode `0600`, fsyncs the file,
installs `<8-digit-sequence>.event` with `renameat2(RENAME_NOREPLACE)`, and
fsyncs the request directory. The preflight event at sequence zero binds the
bootstrap/worker-start nonces, source and runtime identities, exact intended argv/environment,
and credential expectation and is durable **before** `clone3`. The spawn event
at sequence one binds the returned supervisor pidfd identity and actual
`clone3`/`execveat` outcome and is durable before
the worker receives `START`.

Evidence `stage` is exactly `preflight`, `spawn`, `ipc`, `wait`, or `recovery`.
`credentials` is either `null` or exactly `{pid,uid,gid}`; `pidfd_state` is
exactly `{status,code,signal}` with status `running` or `exited` and nullable
bounded integers. `facts` is closed by stage: preflight has exactly both nonces,
source/runtime/argv/environment hashes and reviewed head/tree; spawn has exactly
clone flags, pidfd identity, cgroup identity, and executable hashes; IPC has
exactly direction, sequence, message type, and payload/envelope hashes; wait has
exactly terminal result class and wait status; recovery has exactly prior final
sequence/hash, cgroup identity, `cgroup.kill` result, and populated state. Fields
not defined for the selected stage are forbidden.

Every accepted IPC envelope produces the next event before the supervisor sends
an acknowledgement or proceeds. The terminal `RESULT`/`ERROR` event and its
hash are durable before `SHUTDOWN`; the `SHUTDOWN_ACK` and pidfd wait status are
then recorded as the final event. Unknown files, sequence gaps, hash-chain
mismatch, replacement, failed fsync/rename, or any `.tmp` left by a crash are
preserved and classified `evidence_failure`; they are never deleted or silently
repaired.

If the worker exits before a terminal envelope, the live supervisor waits on
the atomic pidfd, records `worker_crash` and the last valid IPC/evidence
sequences, fsyncs the event and directory, and returns `manual_review`. If the
supervisor itself crashes or the host loses power, Bubblewrap's parent-death
contract destroys the private namespace while the already fsynced event files
remain. Before accepting any request after restart, the dedicated supervisor
scans the evidence root and the recorded per-request cgroup. For any incomplete
request it writes `1` to that exact cgroup's `cgroup.kill`, waits for
`cgroup.events` to report `populated 0`, and verifies the recorded cgroup inode
before classifying `supervisor_crash`. It adds one new recovery event only when
the existing evidence chain and empty recorded cgroup are both proven.
Ambiguous/partial evidence, a changed cgroup identity, or a nonempty/unavailable
cgroup remains untouched as `evidence_failure`. No branch recovers, cleans, or
republishes vanished tmpfs targets.

The final ordered event bytes and aggregate SHA-256 are the durable E3 evidence
and are copied into the later evidence commit. Runtime files, normal checkout
files, and the ephemeral worker journal are never evidence stores.

Lifecycle:

```text
validate structured input
  -> create nonces, socket, sealed source FD 4, and verified runtime FD 5
  -> pin evidence-root FD and create durable preflight event
  -> clone3(CLONE_PIDFD|CLONE_INTO_CGROUP) and execveat Bubblewrap FD 6
  -> send START; validate HELLO credentials and runtime/source hashes
  -> worker creates private tmpfs workspace and clones the sealed bundle
  -> worker pins source commit and Git layout
  -> worker opens/binds root, .git, .steward, and transaction namespace
  -> issue worker-local opaque capability
  -> run D2b primitive under the capability
  -> return bounded result and provenance
  -> durable terminal evidence
  -> worker exits; tmpfs namespace is destroyed by the kernel
```

Any malformed IPC, worker exit, timeout, unexpected FD, path replacement,
cleanup failure, or attestation mismatch returns `manual_review` without
claiming publication success. Before `SHUTDOWN`, the supervisor persists the
terminal IPC envelope and evidence hash. It then sends `SHUTDOWN`, waits on the
atomic pidfd, persists the final wait-status event, and only then closes FD 4,
FD 5 if still open, and the IPC/pidfd descriptors.

## 6. Race and isolation model

The design must not claim that `flock`, repeated `stat`, or a final read-back
prevents an uncooperating writer. The prevention boundary is the private
publisher worktree/process. The D2b fences remain detection and recovery
contracts inside that boundary.

The implementation must therefore make the following distinction explicit:

- a writer in the normal checkout is unrelated to the publisher worktree and
  cannot affect its bytes or Git evidence;
- a writer that can access the publisher worktree is an isolation failure and
  must prevent a positive result;
- a writer injected exactly between the final Git/lease fence and `os.replace()`
  is a required adversarial drill, not a monkeypatch before the fence;
- if the platform cannot enforce the private-worktree boundary, the operation is
  unsupported and returns `manual_review` before any target mutation.

### 6.1 Deterministic fence barrier

E2 uses a test-only, reviewed `before_final_refence_barrier` seam in the worker.
The seam is not a monkeypatch and is unreachable in production mode. After a
complete preliminary per-target Git/index/layout, namespace, lock, journal,
temp, parent, target, candidate, and lease fence, the worker creates a fresh
`fence_token`, sends the closed `FENCE_READY` envelope from §5, and blocks:

```text
FENCE_READY { nonce, direction, sequence, payload_hash,
              payload={request_id, txid, target_index, fence_token, fence_hash} }
```

and blocks. The harness then performs the adversarial action and sends the
`RELEASE` envelope defined in §5, also with its mandatory `payload_hash`:

```text
RELEASE { nonce, direction, sequence, payload_hash,
          payload={request_id, txid, target_index, fence_token} }
```

After validating the complete release envelope, the worker performs the entire
per-target fence a second time and requires the same Git/index/layout,
namespace, lease, lock/journal/temp, parent, target, candidate identity/bytes,
and expected cursor state. This **post-RELEASE fence**, not the preliminary
fence, authorizes mutation. On success, the next filesystem operation is the
dirfd-relative `renameat2`/`os.replace` itself: no IPC, callback, Python hook,
path resolution, allocation, or test seam may run between the final fence and
the replace syscall. Any final-fence or replace failure is `manual_review`; the
normal D2b post-replace identity check and final four-file read-back still
apply.

There are two mandatory drills:

1. A writer in the normal checkout and a writer in a separate Bubblewrap
   namespace attempt the target replacement while the worker is blocked. They
   must receive `ENOENT`/`EACCES` or otherwise prove that no publisher FD/path
   is reachable; the publisher worktree bytes and Git evidence remain stable.
2. A test-only deliberate FD-leak fixture gives an adversary one writable
   target FD. While the worker is blocked at `FENCE_READY`, the adversary
   mutates and fsyncs the target, records the changed stat/bytes, closes its FD,
   and exits before the harness sends `RELEASE`. The mandatory post-RELEASE
   fence must detect the mutation and return `manual_review` without calling
   replace. A fixture that keeps an adversary alive after `RELEASE` is an
   invalid isolation setup, not a positive publication case.

The evidence records both fence hashes, the token, release sequence,
adversarial process credentials/lifetime, attempt result, target identity/bytes
before and after, whether replace was entered, and terminal result. Sleeping,
polling without the barrier, a pre-preliminary-fence mutation, or omitting the
post-RELEASE refence is not valid E2 evidence.

## 7. Delivery boundary

Slice E does not deliver generated files to the human checkout or `main`. It
returns a bounded, provenance-bearing result and an isolated-worktree evidence
record. A later delivery slice must separately define PR-only delivery,
reviewed-base binding, required checks, rollback, and prevention of heartbeat
direct pushes.

### 7.1 Cleanup and evidence lifecycle

The publisher worktree is a tmpfs mount inside the Bubblewrap namespace. The
supervisor never recursively deletes a host workspace path. Normal terminal
cleanup is:

1. worker completes D2b read-back/recovery and sends its terminal envelope;
2. supervisor verifies nonce, sequence, credentials, pidfd/cgroup state, result,
   and evidence digest and installs/fsyncs the corresponding event file;
3. supervisor sends `SHUTDOWN` carrying that terminal evidence hash;
4. worker echoes it in `SHUTDOWN_ACK`; supervisor persists the ACK event;
5. supervisor waits on the atomic pidfd, requires the exact terminal wait
   status and `cgroup.events populated 0`, and persists the final wait event;
6. kernel namespace teardown destroys tmpfs; supervisor closes IPC/pidfd and
   source/runtime descriptors and leaves the evidence directory intact.

If any step fails, the supervisor never claims success and records or preserves
`manual_review` evidence according to §5.3. There is no host-side workspace
cleanup fallback and no recovery from the vanished tmpfs journal. Source and
runtime descriptors are released only after terminal evidence is durable or a
failure event has been persisted.

For every E2/E3 drill, the ordered canonical event files are uploaded as one CI
artifact and copied, with per-event and aggregate SHA-256 values, into a later
`specs/context_bridge_evidence/` evidence commit. The artifact digest,
implementation commit, runtime-manifest hash, runner image, and terminal event
are the durable evidence anchor. No runtime or production root file is used as
an evidence store in Slice E.

## 8. Mandatory evidence gates

No implementation PR may claim Slice E complete without direct, pinned evidence
for all of the following:

1. Linux launch uses the verified launch shim, atomic
   `clone3(CLONE_PIDFD|CLONE_INTO_CGROUP)`, Bubblewrap `execveat` from FD 6,
   exact argv/environment/CWD, `--clearenv`, exact D2b Git variables, and only
   preserved FDs 3/4/5; path-exec and post-spawn `pidfd_open` fail closed.
2. Darwin and unsupported-platform behavior: canonical is blocked before lock,
   workspace, journal, tempfile, or target creation.
3. The complete runtime manifest/tree is archived and both missing/extra files,
   wrong executable hash, symlink, unmanifested import, and changed FD 5 fail
   before workspace creation.
4. Bundle creation is performed from the pinned source/Git FDs with the exact
   Git command, two identical D2a evidence rounds, commit/tree/index checks,
   strict limits, bundle verify/list-heads, seals, and worker clone verification.
   The sealed FD-4 bundle cannot be rewritten or replaced.
5. Capability issuance rejects arbitrary classes, tokens, path-only claims,
   mismatched root/.git/.steward FDs, changed PID, changed path, and changed
   worktree identity.
6. A normal Steward process, child agent, Bash helper, GitTool, dynamic tool,
   actuator, healer, CLI export, A2A persistence, and heartbeat process cannot
   access or mutate the publisher worktree.
7. A separate-checkout writer cannot alter publisher bytes or Git evidence.
8. The controlled `FENCE_READY` point is exercised twice: an inaccessible
   external writer is proven unable to reach the namespace, while the deliberate
   FD-leak mutation is caught by the post-RELEASE full refence before replace;
   both fence hashes and whether replace was entered are recorded.
9. Every IPC type, order, payload, size, canonical byte vector, hash vector,
   failure class, credential/uid-map, and sequence rule has positive and
   adversarial tests; unknown or over-limit data fails before mutation.
10. The fixed evidence root and preflight event are durable before atomic
   spawn. Worker crash before/after capability issue, journal write, each
   replace, read-back,
   cleanup, and workspace destruction preserves the event chain. Supervisor
   crash/restart uses the recorded cgroup, `cgroup.kill`, and `populated 0` and
   never guesses at partial evidence.
11. Workspace destruction cannot remove a foreign or replaced path, inode, or
   parent; failed identity checks leave evidence untouched.
12. The result binds source commit/tree, runtime and bundle hashes, supervisor
    pidfd/cgroup, worker identity, worktree identity, Git layout, snapshot,
    attestation, transaction ID, and final state.

Every evidence record must include the pinned implementation commit, fixture
tree, platform/image, exact process/environment facts, target bytes before and
after, Git evidence, result class, and whether any protected byte was read or
written by a foreign process.

## 9. Gates and sequencing

- **E0:** this spec reviewed adversarially; no code.
- **E1:** bootstrap implementation and unit tests; no D2b caller wiring.
- **E2:** real Linux process/worktree drill and controlled race evidence.
- **E3:** recovery/cleanup crash matrix and durable provenance evidence.
- **E4:** separate delivery spec; only then consider a human-reviewed activation
  proposal.

Until E2 and E3 pass, G1 remains OFF, PR #728 remains unmerged, and canonical
publication remains unavailable in production.

## 10. Decisions closed for E0

The following architecture choices are closed and are not implementation-time
options:

1. **Workspace:** a full `--no-local --no-hardlinks` clone inside a Bubblewrap
   tmpfs namespace; no detached worktree in a shared checkout.
2. **Linux boundary:** verified Bubblewrap FD execution via `execveat`, atomic
   `clone3(CLONE_PIDFD|CLONE_INTO_CGROUP)`, private namespaces, worker UID/GID
   `65532`, `--die-with-parent`, and no lock-only or path-exec fallback.
3. **Runtime:** exact CPython 3.12, Git, worker/import, ELF, stdlib, and host
   executable sets are enumerated by the closed content-addressed runtime
   manifest and mounted from FD 5.
4. **Source:** an exact FD-bound Git command creates a size-bounded bundle only
   between two identical D2a evidence rounds; commit/tree/index, bundle heads,
   seals, and worker clone are all verified.
5. **Capability and IPC:** worker-local opaque capability only; closed RFC-8785
   messages over `SOCK_SEQPACKET`, peer credentials, per-direction sequences,
   one-use nonces, exact payload hashes, and atomic supervisor-pidfd revocation.
6. **Race synchronization:** E2 pauses after a preliminary fence, then requires
   a complete post-RELEASE refence immediately before replace; sleeps, polling,
   and pre-fence writes are invalid evidence.
7. **Cleanup and crash evidence:** the fixed dedicated evidence root receives
   fsynced hash-chained event files before spawn and at every transition.
   Worker/supervisor crashes are resolved only with pidfd and recorded cgroup
   evidence; kernel namespace teardown destroys tmpfs and no host workspace is
   recursively cleaned.
8. **Evidence publication:** ordered canonical event files are CI-artifacted and
   later pinned by aggregate and per-event SHA-256 in a dedicated evidence
   commit; production runtime files are not an evidence store.

E0 may still reject the spec for an internal inconsistency or insufficient
evidence schema, but it must not reopen these architecture choices without a
new, explicitly reviewed amendment.
