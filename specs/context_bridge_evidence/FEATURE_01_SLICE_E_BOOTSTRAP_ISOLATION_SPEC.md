# Context Bridge Slice E — Bootstrap and Publisher Isolation

**Status:** DRAFT 0.2 — E0 architecture decisions closed; implementation forbidden

**Parent contract:** `FEATURE_01_SLICE_D2B_WRITER_POLICY_PREFLIGHT.md`,
`FEATURE_01_SLICE_D2B_G2_PREFLIGHT.md`

**Recon pin:** `origin/main` at `9bc785337103d94dfe70c26510030ac05e618135`

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
  --ro-bind <immutable-runtime-root> /
  --ro-bind <source-export> /input
  --tmpfs /work
  --proc /proc --dev /dev --tmpfs /tmp
  --chdir /work
  --setenv LANG C --setenv LC_ALL C --setenv PATH /bin
  -- <runtime-python> -I -S -m steward.publisher_worker --ipc-fd 3
```

The worker creates a full clone with `git clone --no-local --no-hardlinks`
from `/input` into `/work/repo`, then proves that the resulting worktree has an
independent index and no `commondir`, `gitdir`, or alternates redirection. The
worktree exists only in the private tmpfs namespace. No host path to `/work`
is passed to the parent or any normal Steward process.

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
against the manifest in §4.5 before launch.

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

### 4.4 Capability issuance

The capability is worker-local. No root, `.git`, `.steward`, target, journal, or
tempfile FD crosses the process boundary. The parent receives only a bounded
attestation/result record over the authenticated channel. The issuer returns an
opaque capability only inside the dedicated worker after all of these checks
pass:

- worker PID and process-group identity are pinned;
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
wrong worker PID, wrong namespace/worktree identity, changed parent, changed
Git layout, or expired/revoked lease. A capability is never reconstructed from
JSON, a Python class, or a caller-provided path.

### 4.5 Worker-code provenance

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
before launch and inherited only as FD 3. The parent records the worker's
`pidfd` immediately after spawn. `SO_PEERCRED` and `SCM_CREDENTIALS` must match
the expected worker UID; the `pidfd` rather than a numeric PID is the lifetime
and PID-reuse binding.

The parent generates a fresh 32-byte random `bootstrap_nonce` for every launch.
The first worker message must echo that nonce and the expected runtime/source
manifest hashes. Every message contains `(nonce, sequence, message_type,
payload_hash)` and sequence numbers are strictly monotone from zero. A nonce is
single-use and a socket is never reused. A replay, duplicate, stale sequence,
credential mismatch, or unexpected message type returns `manual_review` and
terminates the worker.

Only bounded canonical JSON messages cross the channel. No target, journal,
tempfile, root, `.git`, or `.steward` FD is sent with `SCM_RIGHTS`; all mutation
FDs remain inside the worker namespace. The parent receives an attestation,
terminal result, and evidence digest only.

Lifecycle:

```text
validate structured input
  -> create private workspace
  -> pin source commit and Git layout
  -> create pidfd and authenticated IPC nonce
  -> spawn allowlisted worker
  -> worker opens/binds root, .git, .steward, and transaction namespace
  -> issue worker-local opaque capability
  -> run D2b primitive under the capability
  -> return bounded result and provenance
  -> durable terminal evidence
  -> worker exits; tmpfs namespace is destroyed by the kernel
```

Any malformed IPC, worker exit, timeout, unexpected FD, path replacement,
cleanup failure, or attestation mismatch returns `manual_review` without
claiming publication success. Before releasing the `pidfd`, the parent writes a
canonical terminal evidence record containing the nonce, worker pidfd status,
runtime/source manifest hashes, namespace/worktree identity, D2b result, and
all observed failure classes. The record is fsynced to the private evidence
directory and its SHA-256 is retained for the evidence PR described in §8.

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
before the real `os.replace()`, the worker sends:

```text
FENCE_READY { nonce, sequence, txid, target_index, fence_hash }
```

and blocks. The harness then performs the adversarial action and sends:

```text
RELEASE { nonce, sequence, txid, target_index }
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

1. worker completes D2b read-back/recovery and writes its terminal message;
2. parent verifies the message nonce, sequence, pidfd state, result, and
   evidence digest;
3. parent fsyncs the canonical evidence record and atomically records its hash;
4. parent sends `SHUTDOWN` and waits on the pidfd;
5. kernel namespace teardown destroys tmpfs; parent verifies worker exit and
   closes the IPC/pidfd descriptors.

If any step fails, the parent does not claim success and retains the evidence
record as `manual_review`. A worker crash before terminal evidence is durable
also yields `manual_review`; there is no host-side workspace cleanup fallback.
The read-only source bind and immutable runtime root are never deleted by the
publisher.

For every E2/E3 drill, the canonical evidence JSON is uploaded as a CI artifact
and copied, with its SHA-256, into a later `specs/context_bridge_evidence/`
evidence commit. The artifact digest, implementation commit, runner image, and
result record are the durable evidence anchor. No runtime or production root
file is used as an evidence store in Slice E.

## 8. Mandatory evidence gates

No implementation PR may claim Slice E complete without direct, pinned evidence
for all of the following:

1. Linux worker executable/environment/CWD/FD allowlist and process reaping.
2. Darwin and unsupported-platform behavior: canonical is blocked before lock,
   workspace, journal, tempfile, or target creation.
3. Real isolated workspace creation from a pinned source commit; independent
   index and rejected Git redirections.
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
8. Worker crash before/after capability issue, journal write, each replace,
   read-back, cleanup, and workspace destruction preserves evidence and returns
   a deterministic terminal class.
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
3. **Capability:** worker-local opaque capability only; no mutation FD crosses
   IPC. Parent/worker authentication is `SOCK_SEQPACKET` + `SO_PEERCRED`/
   `SCM_CREDENTIALS` + one-use 32-byte nonce + monotone sequence + pidfd
   revocation. Numeric PID alone is never accepted.
4. **Worker provenance:** Bubblewrap, interpreter, runtime, worker entrypoint,
   and dependencies are bound to a canonical SHA-256 manifest built from the
   reviewed source commit before launch.
5. **Race synchronization:** E2 uses the exact `FENCE_READY`/`RELEASE` barrier
   immediately around `os.replace()`; sleeps, polling, and pre-fence writes are
   invalid evidence.
6. **Cleanup:** the worker writes terminal evidence first; the parent fsyncs and
   records its hash, then waits on pidfd; kernel namespace teardown destroys the
   tmpfs. No parent-side recursive cleanup or success claim after an evidence
   failure is permitted.
7. **Evidence:** canonical evidence JSON is CI-artifacted and later pinned by
   SHA-256 in a dedicated evidence commit; production runtime files are not an
   evidence store in Slice E.

E0 may still reject the spec for an internal inconsistency or insufficient
evidence schema, but it must not reopen these architecture choices without a
new, explicitly reviewed amendment.
