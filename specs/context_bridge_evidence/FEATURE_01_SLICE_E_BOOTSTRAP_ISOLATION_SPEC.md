# Context Bridge Slice E — Bootstrap and Publisher Isolation

**Status:** DRAFT 0.1 — read-only recon complete; implementation forbidden

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

### 4.1 Bootstrap inputs

The issuer accepts one structured input object containing exactly:

- immutable source repository identity and reviewed commit;
- Constitution attestation and one explicit snapshot reference;
- delivery base identity (reference only; no delivery in Slice E);
- bounded transaction/deadline parameters from the approved D2b contract.

No arbitrary shell text, tool name, provider data, path override, environment
override, or caller-selected executable is accepted.

### 4.2 Dedicated process

The publisher worker is a separate process created from a fixed executable and
allowlisted environment. The contract must record and enforce:

- absolute executable identity and immutable executable stat tuple;
- exact `argv`, CWD, environment allowlist, umask, UID/GID, and process group;
- `close_fds=True` semantics with an explicit passed-FD allowlist;
- no normal Steward registry, Bash, GitTool, child-agent, LLM, healer,
  actuator, or delivery callback in the worker;
- bounded startup, IPC, operation, shutdown, and process-reaping deadlines;
- kill-on-timeout and evidence-preserving failure behavior.

The worker may use only the reviewed read-only Git plumbing and the D2b
transaction primitive. Generic subprocess execution is prohibited.

### 4.3 Ephemeral publisher worktree

The bootstrap creates a private, uniquely named workspace outside the human and
heartbeat checkout. The workspace must have:

- a distinct worktree path and independent index;
- a validated Git object relationship to the pinned source commit;
- no `commondir`, `gitdir`, alternates, symlink, hardlink, or foreign-index
  redirection;
- root and `.steward` parents owned by the worker identity, mode-checked, and
  pinned by FD before any journal or target read;
- a cleanup lease that can destroy only this workspace and only after durable
  success or an evidence-preserving terminal failure;
- a source/delivery identity that is recorded but never inferred from a path.

The bootstrap must prove the workspace is not the normal Steward checkout and
cannot be reached through an inherited mutable process path. A path under `/tmp`
alone is not proof.

### 4.4 Capability issuance

The issuer returns an opaque capability only from the dedicated worker after all
of these checks pass:

- worker PID and process-group identity are pinned;
- root, `.git`, and `.steward` FDs are opened with safe flags and bound to the
  same repository root;
- the path-to-FD binding is proven twice around bootstrap handoff;
- the worktree identity, source commit, Git layout fingerprint, and workspace
  lease are recorded in the attestation;
- the capability cannot be constructed by a caller-provided class, boolean,
  path, or arbitrary token value;
- revocation/worker exit makes every later lease verification fail closed.

The D2b consumer must reject a capability with a missing issuer signature,
wrong worker PID, wrong workspace identity, changed parent, changed Git layout,
or expired/revoked lease.

## 5. IPC and lifecycle contract

Parent and worker communicate over one authenticated, close-on-exec channel.
Messages are bounded canonical JSON values with an explicit schema version and
maximum size. The worker never receives a caller-selected file descriptor except
the reviewed source/delivery descriptors needed for the current operation.

Lifecycle:

```text
validate structured input
  -> create private workspace
  -> pin source commit and Git layout
  -> spawn allowlisted worker
  -> worker opens/binds root, .git, .steward, and transaction namespace
  -> issue opaque capability
  -> run D2b primitive under the capability
  -> return bounded result and provenance
  -> durable terminal evidence
  -> destroy workspace only after the terminal decision
```

Any malformed IPC, worker exit, timeout, unexpected FD, path replacement,
cleanup failure, or attestation mismatch returns `manual_review` without
claiming publication success. The parent must retain the worker transcript and
workspace path/identity as evidence until the terminal decision is durable.

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

## 7. Delivery boundary

Slice E does not deliver generated files to the human checkout or `main`. It
returns a bounded, provenance-bearing result and an isolated-worktree evidence
record. A later delivery slice must separately define PR-only delivery,
reviewed-base binding, required checks, rollback, and prevention of heartbeat
direct pushes.

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
7. A writer injected at the controlled point between the last fence and
   `os.replace()` yields no positive publication result; the exact byte and
   identity outcome is recorded.
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

## 10. Open questions before E0 approval

1. Is the worker allowed to create a full clone, or must it use a detached
   worktree with a separately pinned object database?
2. Which exact Linux isolation primitive is supported in CI and production:
   private filesystem namespace, dedicated UID, or an equivalent deployment
   boundary?
3. What is the authenticated capability transport and revocation mechanism?
4. Which source/delivery descriptors may cross the worker boundary, and who owns
   their close/fsync lifecycle?
5. What safe fallback is persisted when workspace destruction or delivery cannot
   complete?
6. Which evidence is durable in Git and which remains private runner evidence?
7. How is the final fence-to-replace drill synchronized without granting the
   adversarial writer normal publisher access?

No implementation decision is implied by these questions. They must be closed
with pinned evidence or remain explicit blockers.
