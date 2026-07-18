# Context Bridge Slice E — Bootstrap and Publisher Isolation

**Status:** DRAFT 0.3 — E0 architecture decisions closed; implementation forbidden

**Parent contract:** `FEATURE_01_SLICE_D2B_WRITER_POLICY_PREFLIGHT.md`,
`FEATURE_01_SLICE_D2B_G2_PREFLIGHT.md`

**Recon pin:** `origin/main` at `a2d545774e10d59e02314f79dae043e1259ec98b`

**Pinned tree:** `78191a9cdf26085f8b966f4c9179dfceab313f13`

**Pin drift:** Compared with the initial E0 base `9bc785337103d94dfe70c26510030ac05e618135`,
`origin/main` advanced only in runtime/federation state: `.steward/.context_hash`,
`.steward/context.json`, `.steward/federation_health.json`,
`.steward/marketplace.json`, `.steward/sessions.json`,
`data/federation/nadi_inbox.json`, `data/federation/nadi_outbox.json`,
`data/federation/peers.json`, `data/federation/quarantine/index.json`,
`data/federation/relay_seen_ids.json`, and `data/federation/steward_health.json`.
No E0 source, spec, or implementation path is overlapped by that drift.

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
4. Structured parent/child IPC for inputs, result, and failure state.
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
override, or caller-selected executable is accepted.

### 4.2 Dedicated process

The publisher worker runs on Linux inside `/usr/bin/bwrap` with a private user,
mount, PID, IPC, UTS, and network namespace. Bubblewrap is a required platform
dependency, not an optional optimization; if the pinned executable is absent,
changed, or cannot create the required namespaces, the operation returns
`manual_review` before a lock or workspace is created. No alternate isolation
primitive is accepted by this slice.

The exact launch shape is:

```text
/usr/bin/bwrap
  --die-with-parent --new-session --unshare-all
  --uid 65532 --gid 65532
  --clearenv
  --preserve-fd 3 --preserve-fd 4
  --ro-bind <immutable-runtime-root> /
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
  -- <runtime-python> -I -S -m steward.publisher_worker --ipc-fd 3
```

FD 3 is the authenticated IPC socket and FD 4 is the parent-opened,
read-only source-export descriptor. `--preserve-fd 3` and
`--preserve-fd 4` are mandatory; a launch that cannot preserve both FDs is
unsupported and returns `manual_review` before any workspace or transaction
namespace is created. `--clearenv` is mandatory. The only worker environment
variables are the nine `LANG`/`LC_ALL`/`PATH`/`GIT_*` assignments shown above;
all other inherited variables, all `GIT_*` overrides not listed above, loader
variables, proxy variables, and credential variables are absent. The six
approved D2b Git variables (`GIT_OPTIONAL_LOCKS`, `GIT_NO_REPLACE_OBJECTS`,
`GIT_PAGER`, `GIT_CONFIG_NOSYSTEM`, `GIT_CONFIG_GLOBAL`,
and `GIT_CONFIG_SYSTEM`) are the complete Git allowlist; no other `GIT_*` name
is permitted. Network access and interactive credential acquisition are
unavailable inside the required namespaces; a command that would prompt is a
bounded failure, never a reason to add an unreviewed environment variable.

The worker creates a full clone with
`git clone --no-local --no-hardlinks /input/source.bundle /work/repo`, then
proves that the resulting worktree has an independent index and no `commondir`,
`gitdir`, or alternates redirection. The worktree exists only in the private
tmpfs namespace. No host path to `/work` is passed to the parent or any normal
Steward process.

The worker process is a separate process created from the fixed executable and
allowlisted environment. The contract records and enforces:

- absolute executable identity and immutable executable stat tuple;
- exact `argv`, CWD, environment allowlist, umask, UID/GID, and process group;
- `close_fds=True` semantics with an explicit passed-FD allowlist;
- no normal Steward registry, Bash, GitTool, child-agent, LLM, healer,
  actuator, or delivery callback in the worker;
- bounded startup, IPC, operation, shutdown, and process-reaping deadlines;
- kill-on-timeout and evidence-preserving failure behavior.

The worker may use only the reviewed read-only Git plumbing and the D2b
transaction primitive. Generic subprocess execution is prohibited. The
Bubblewrap executable, runtime interpreter, and worker module are all verified
against the manifest in §4.6 before launch.

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

The parent never hands Bubblewrap a caller-controlled repository path. Before
spawn it builds a complete Git bundle for the pinned reviewed commit in a
private host-side `memfd` created with `MFD_ALLOW_SEALING`. The bundle is
written, hashed, and sealed with `F_SEAL_WRITE|F_SEAL_SHRINK|F_SEAL_GROW|
F_SEAL_SEAL`; failure to establish every seal is `manual_review`. After
sealing, the parent reopens the memfd through its own `/proc/self/fd/<n>` entry
with `O_RDONLY|O_CLOEXEC`, closes the writable original, and retains that
read-only duplicate as FD 4. It records the resulting regular-file
device/inode/type/link/size/mtime/ctime tuple, seal mask, bundle hash, and
reviewed commit in the launch evidence. No caller path or mutable directory is
part of the handoff.

Bubblewrap resolves `--ro-bind /proc/self/fd/4 /input/source.bundle` from that
sealed descriptor and receives no source path other than this proc-fd
reference. A platform or Bubblewrap build that cannot bind this descriptor
without falling back to a path lookup is unsupported and must return
`manual_review`. The parent verifies FD 4 with `fstat()`, its seal mask, and
its canonical bundle hash immediately before spawn, after the worker
handshake, and before terminal evidence; any change is impossible under the
seal contract and is nevertheless a `manual_review` result. FD 4 remains open
until the worker has sent terminal evidence and the parent has fsynced it. It
is then closed, allowing the ephemeral memfd to disappear. No source, root, or
mutation FD is sent with `SCM_RIGHTS`.

### 4.5 Capability issuance

The capability is worker-local. No root, `.git`, `.steward`, target, journal, or
tempfile FD crosses the process boundary. The parent receives only a bounded
attestation/result record over the authenticated channel. The issuer returns an
opaque capability only inside the dedicated worker after all of these checks
pass:

- worker process-group identity and worker-start nonce are pinned; the worker
  PID is diagnostic metadata bound to that nonce, while the parent authority is
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

The bootstrap builds an immutable runtime root from the reviewed worker source
commit before launching Bubblewrap. It computes a canonical manifest containing
sorted relative paths, file sizes, and SHA-256 values for:

- `/usr/bin/bwrap`;
- the Python interpreter and its loader/runtime files;
- every worker `.py`, native module, and dependency file loaded by the entrypoint;
- the worker entrypoint module and its reviewed Git blob.

The manifest itself is canonical JSON and its SHA-256 is part of the parent
input and worker handshake. The runtime root is mounted read-only. A mismatch
between the expected reviewed commit, manifest hash, executable stat/hash, or
worker handshake returns `manual_review` before the worker opens the worktree.

## 5. IPC and lifecycle contract

Parent and worker communicate over one Unix `SOCK_SEQPACKET` socketpair created
before launch, with `SO_PASSCRED` enabled before spawn, and inherited only as
FD 3. The parent records a `pidfd`
immediately for the **host-side Bubblewrap supervisor PID**. The pidfd is the
lifetime and PID-reuse binding; a numeric PID reported by the worker is never a
security anchor. The worker PID inside the private PID namespace is recorded
only as diagnostic metadata and is bound to the launch by its one-use
`worker_start_nonce` and namespace inode in the first handshake.

`SO_PEERCRED` and per-message `SCM_CREDENTIALS` authenticate the socket peer to
the Bubblewrap child. The parent does not pretend that the namespace UID
`65532` is necessarily represented by the same host integer: the expected
peer credential tuple is the kernel-translated `(uid,gid,pid)` proven by the
E1 Linux drill from the exact `uid_map`/`gid_map` and launch PID. The worker
handshake must report the exact `uid_map`, `gid_map`, PID-namespace inode, and
effective namespace UID/GID `65532/65532`; the parent records the translated
peer tuple and rejects any later `SO_PEERCRED` or `SCM_CREDENTIALS` mismatch.
This binds credentials, namespace, and the supervisor pidfd without relying on
an unverified caller-supplied UID.

The E1 drill must execute this exact launch shape on the pinned Ubuntu image,
capture the parent-side `SO_PEERCRED` tuple and every message's
`SCM_CREDENTIALS`, and archive the worker's `uid_map`, `gid_map`, effective
IDs, PID-namespace inode, and supervisor PID/start identity. The expected
translated tuple is derived from those kernel observations and the reviewed
launch identity, not supplied by the caller or guessed from `65532`. A
different tuple, map, namespace inode, or start identity is an immediate
`manual_review`; a mocked credential object is not evidence.

The parent generates a fresh 32-byte random `bootstrap_nonce` and a distinct
`worker_start_nonce` for every launch. The exact envelope for **every** message
is:

```json
{
  "schema": "slice-e.ipc.v1",
  "direction": "parent->worker | worker->parent",
  "nonce": "32-byte bootstrap nonce",
  "sequence": 0,
  "message_type": "...",
  "payload_hash": "sha256(canonical-json(payload))",
  "payload": {}
}
```

`sequence` is a strictly monotone, gap-free counter beginning at zero **per
direction**; the parent and worker maintain independent counters and the
`direction` value is covered by the authenticated envelope. `payload_hash`
always hashes the canonical payload only, excluding the envelope and the hash
field itself. The first worker message is `HELLO` and echoes the bootstrap and
worker-start nonces, runtime/source manifest hashes, namespace identity, and
credential map. A nonce is single-use and a socket is never reused. A replay,
duplicate, stale/gapped sequence, credential mismatch, nonce mismatch, hash
mismatch, or unexpected message type returns `manual_review` and terminates the
worker.

Only bounded canonical JSON messages cross the channel. No target, journal,
tempfile, root, `.git`, or `.steward` FD is sent with `SCM_RIGHTS`; all mutation
FDs remain inside the worker namespace. The read-only source FD 4 is the sole
launch input exception and is inherited by Bubblewrap, never sent after the
worker starts. Apart from the required `HELLO`, barrier, and shutdown control
messages, the parent receives only an attestation, terminal result, and
evidence digest.

The barrier messages are ordinary envelopes, not an undocumented exception:

```json
{
  "schema": "slice-e.ipc.v1", "direction": "worker->parent",
  "nonce": "...", "sequence": 7, "message_type": "FENCE_READY",
  "payload_hash": "sha256(canonical-json(payload))",
  "payload": {"txid": "...", "target_index": 0, "fence_hash": "..."}
}
```

```json
{
  "schema": "slice-e.ipc.v1", "direction": "parent->worker",
  "nonce": "...", "sequence": 4, "message_type": "RELEASE",
  "payload_hash": "sha256(canonical-json(payload))",
  "payload": {"txid": "...", "target_index": 0}
}
```

The worker verifies the complete envelope and its per-direction sequence before
continuing.

### 5.1 Crash-surviving evidence channel

Before spawning Bubblewrap, the parent creates a private host-side evidence
directory (mode `0700`) beneath a trusted evidence root, opens an append-only
launch record with dirfd-relative
`O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC|O_NOFOLLOW` and mode `0600`, and writes
the launch nonce, worker-start nonce, source identity, runtime manifest hash,
Bubblewrap executable hash/stat, expected credential map, and exact launch
argv/environment.
Each event is a bounded length-prefixed canonical JSON record (maximum 65,536
bytes) with a record sequence, previous-record hash, event hash, and stage.
The parent fsyncs the record and its parent directory before `exec`/spawn. This
record is outside the worker tmpfs and is therefore not destroyed when the
worker or its namespace exits.

For every accepted IPC envelope, the parent appends the bounded envelope,
credential observation, and receipt stage to that host record and fsyncs the
record. The parent must not acknowledge a terminal result until the terminal
envelope and its payload hash are durable. If the Bubblewrap supervisor or
worker exits before terminal evidence, the parent waits on the supervisor
pidfd, appends `worker_crashed_before_terminal` with the observed wait status
and last valid sequence, fsyncs it and its parent, and returns `manual_review`.
The vanished tmpfs journal, temps, and worktree are never treated as recovery
authority and are not replaced by a host-side workspace cleanup. The external
record, its final SHA-256, and the crash classification are the durable E3
evidence. A later evidence commit may copy that record; the runtime root and
normal checkout remain uninvolved.

Lifecycle:

```text
validate structured input
  -> create private host evidence record and source FD 4
  -> create socket, authenticated IPC nonce, and launch manifest
  -> spawn allowlisted worker
  -> create supervisor pidfd immediately after spawn
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
claiming publication success. Before sending `SHUTDOWN` or releasing the
supervisor `pidfd`, the parent appends a canonical terminal evidence record to
the already durable host-side channel. It contains the nonce, supervisor
pidfd wait status, namespace/worker identity, runtime/source manifest hashes,
D2b result, all observed failure classes, and the final evidence digest. The
parent fsyncs that record and its parent directory, then sends `SHUTDOWN`, waits
on the pidfd, and only then closes FD 4 and the IPC descriptors.

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

E2 uses a test-only, reviewed `before_replace_barrier` seam in the worker. The
seam is not a monkeypatch and is unreachable in production mode. Immediately
after the complete per-target Git/parent/target/lease fence and immediately
before the real `os.replace()`, the worker sends the `FENCE_READY` envelope
defined in §5. Its payload contains `txid`, `target_index`, and `fence_hash`,
and the envelope therefore has a mandatory `payload_hash`; the abbreviated
wire notation is:

```text
FENCE_READY { nonce, direction, sequence, payload_hash,
              payload={txid, target_index, fence_hash} }
```

and blocks. The harness then performs the adversarial action and sends the
`RELEASE` envelope defined in §5, also with its mandatory `payload_hash`; its
abbreviated wire notation is:

```text
RELEASE { nonce, direction, sequence, payload_hash,
          payload={txid, target_index} }
```

The worker verifies the same nonce, sequence, transaction, and target before
continuing. There are two mandatory drills:

1. A writer in the normal checkout and a writer in a separate Bubblewrap
   namespace attempt the target replacement while the worker is blocked. They
   must receive `ENOENT`/`EACCES` or otherwise prove that no publisher FD/path
   is reachable; the publisher worktree bytes and Git evidence remain stable.
2. A test-only deliberate FD-leak fixture gives an adversary one target FD.
   The worker must detect the identity/byte change after `RELEASE` and return
   `manual_review`, never `published`. This fixture proves the detection fence;
   it is not an accepted isolation mechanism.

The evidence records the barrier event, adversarial process credentials,
attempt result, target identity/bytes before and after, and terminal result.
Sleeping, polling without the barrier, or mutating before `FENCE_READY` is not
valid E2 evidence.

## 7. Delivery boundary

Slice E does not deliver generated files to the human checkout or `main`. It
returns a bounded, provenance-bearing result and an isolated-worktree evidence
record. A later delivery slice must separately define PR-only delivery,
reviewed-base binding, required checks, rollback, and prevention of heartbeat
direct pushes.

### 7.1 Cleanup and evidence lifecycle

The publisher worktree is a tmpfs mount inside the Bubblewrap namespace. The
parent never recursively deletes a host path. Normal terminal cleanup is:

1. worker completes D2b read-back/recovery and sends its terminal envelope;
2. parent verifies the envelope nonce, direction/sequence, credentials, pidfd
   state, result, and evidence digest, and appends that observation to the
   host-side evidence channel;
3. parent fsyncs the complete canonical evidence record and its parent
   directory, retaining the final record hash;
4. parent sends `SHUTDOWN` and waits on the supervisor pidfd;
5. kernel namespace teardown destroys tmpfs; parent verifies supervisor exit,
   closes IPC/pidfd descriptors, and only then releases FD 4.

If any step fails, the parent does not claim success and retains the external
evidence record as `manual_review`. A worker or supervisor crash before
terminal evidence is durable appends the crash status to that same external
record before returning. There is no host-side workspace cleanup fallback and
no attempt to recover from the vanished tmpfs journal. The read-only source
bind and immutable runtime root are released only after the terminal record is
durable.

For every E2/E3 drill, the canonical evidence JSON is uploaded as a CI artifact
and copied, with its SHA-256, into a later `specs/context_bridge_evidence/`
evidence commit. The artifact digest, implementation commit, runner image, and
result record are the durable evidence anchor. No runtime or production root
file is used as an evidence store in Slice E.

## 8. Mandatory evidence gates

No implementation PR may claim Slice E complete without direct, pinned evidence
for all of the following:

1. Linux worker executable/environment/CWD/FD allowlist and process reaping,
   including `--clearenv`, exact D2b Git variables, and both
   `--preserve-fd 3`/`--preserve-fd 4` launch arguments.
2. Darwin and unsupported-platform behavior: canonical is blocked before lock,
   workspace, journal, tempfile, or target creation.
3. Real isolated workspace creation from a pinned source commit; independent
   index and rejected Git redirections. The sealed FD-4 Git bundle cannot be
   rewritten or replaced between launch, handshake, and terminal evidence.
4. Capability issuance rejects arbitrary classes, tokens, path-only claims,
   mismatched root/.git/.steward FDs, changed PID, changed path, and changed
   worktree identity.
5. A normal Steward process, child agent, Bash helper, GitTool, dynamic tool,
   actuator, healer, CLI export, A2A persistence, and heartbeat process cannot
   access or mutate the publisher worktree.
6. A separate-checkout writer cannot alter publisher bytes or Git evidence.
7. The controlled `FENCE_READY` point is exercised twice: an inaccessible
   external writer is proven unable to reach the namespace, while the deliberate
   FD-leak breach yields no positive publication result; exact byte and identity
   outcomes are recorded for both.
8. The host-side evidence channel is pre-persisted before spawn; every IPC
   envelope carries the required payload hash and per-direction sequence; the
   credential/uid-map and supervisor-pidfd bindings are recorded. Worker
   crash before/after capability issue, journal write, each replace, read-back,
   cleanup, and workspace destruction preserves that external evidence and
   returns a deterministic terminal class.
9. Workspace destruction cannot remove a foreign or replaced path, inode, or
   parent; failed identity checks leave evidence untouched.
10. The result binds source commit, worker identity, worktree identity, Git
    layout, snapshot, attestation, transaction ID, and final state.

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
2. **Linux boundary:** `/usr/bin/bwrap` with `--unshare-all`, private user/mount/
   PID/IPC/UTS/network namespaces, worker UID/GID `65532`, `--die-with-parent`,
   and an immutable runtime root. Missing or unsafe Bubblewrap is unsupported;
   there is no lock-only fallback.
3. **Capability and IPC:** worker-local opaque capability only; no mutation FD
   crosses IPC. Parent/worker authentication is `SOCK_SEQPACKET` with exact
   envelope fields, per-direction monotone sequences, `SO_PEERCRED`/
   `SCM_CREDENTIALS` bound to the verified UID/GID maps, one-use 32-byte
   bootstrap and worker-start nonces, and supervisor-pidfd revocation. Numeric
   PID alone is never accepted; the namespace worker UID/GID is explicitly
   `65532/65532` while the kernel-translated host peer tuple is recorded.
4. **Worker provenance:** Bubblewrap, interpreter, runtime, worker entrypoint,
   and dependencies are bound to a canonical SHA-256 manifest built from the
   reviewed source commit before launch.
5. **Race synchronization:** E2 uses the exact `FENCE_READY`/`RELEASE` barrier
   immediately around `os.replace()`; sleeps, polling, and pre-fence writes are
   invalid evidence.
6. **Cleanup and crash evidence:** the parent pre-persists a host-side launch
   record before spawn, fsyncs every accepted envelope and the terminal/crash
   decision, then waits on the supervisor pidfd; kernel namespace teardown
   destroys the tmpfs. No parent-side recursive cleanup or success claim after
   an evidence failure is permitted.
7. **Evidence:** canonical evidence JSON is CI-artifacted and later pinned by
   SHA-256 in a dedicated evidence commit; production runtime files are not an
   evidence store in Slice E.

E0 may still reject the spec for an internal inconsistency or insufficient
evidence schema, but it must not reopen these architecture choices without a
new, explicitly reviewed amendment.
