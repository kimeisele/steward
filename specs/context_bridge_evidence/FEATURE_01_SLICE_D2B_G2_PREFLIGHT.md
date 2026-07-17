# FEATURE 01 — SLICE D2b G2 PRE-FLIGHT

> **Status:** DRAFT 0.1 — READ-ONLY G2 CONTRACT; G1 OFF; IMPLEMENTATION LOCKED
>
> **Investigated main:** `kimeisele/steward@ad09f81c369309b576eaac5d9ccec9ecabee0298`
>
> **Investigated tree:** `ecee4b57fe0e6f3d65e9ddae096c261573dba99b`
>
> **D2b parent preflight:** `f582e0d63876df8be61e8970a0fe065a2b2c034e`
>
> **Writer-policy merge:** `0260c53950fbddbf037d607cca2031467744bcfa`
>
> **Earlier G2 scan pin:** `0260c53950fbddbf037d607cca2031467744bcfa`
>
> **Date:** 2026-07-17

This document is the next isolated read-only contract after the approved D2b
writer-boundary policy. It specifies the smallest future POSIX transaction primitive and
its evidence gates. It does not implement or activate a writer, lock, journal, recovery,
bootstrap, workflow, delivery, root file, setting, or caller.

## 1. Gate and decision

G1 remains **OFF**. This pre-flight may be reviewed as a proposed code contract, but no
implementation PR may begin until this document is independently approved and the human
operator explicitly authorizes the exact implementation head.

The future D2b code slice is limited to a pure local transaction primitive in a new,
separate module such as `steward/context_publication.py` and its direct tests and
fixtures. The existing read-only observer `steward/context_publisher.py` remains
read-only and is not turned into a writer. No existing caller imports the primitive in
this slice.

The primitive consumes explicit, already assembled and validated inputs from Feature 04,
Feature 00, the renderer, D1 read-back, and a Constitution attestation. It must never
call `assemble_context()` itself, invoke an LLM, read a clock for semantic truth, use
GitHub/network state, or infer an operator order.

## 2. Live baseline and protected state

### 2.1 Current repository

The pinned `origin/main` is clean and has no overlapping open Context Bridge PR. The
current open unrelated heartbeat-spec PR is not part of this slice and does not change
the protected paths.

At the pin:

| Path | HEAD/index | Worktree | Classification |
|---|---|---|---|
| `CLAUDE.md` | regular `100644`, blob `8146a15603c95e5aa1404c9eb7021e3008914b0c` | present and legacy | `legacy_bootstrap` only |
| `AGENTS.md` | absent | absent | no V1 baseline |
| `.steward/context-snapshot.json` | absent | absent | no V1 baseline |
| `.steward/context-publication.json` | absent | absent | no V1 baseline |
| `.steward/conventions.md` | blob `f428d5856a5c525e002c301890777748effbeb4e` | present | C0 source, not target |

The tracked `.steward/context.json`, `.steward/.context_hash`, federation state, and
historical `.steward/.atomic_*.tmp` files are outside the D2b generation and transaction
namespace. The initial state is `legacy_bootstrap`; D2b must not automatically overwrite,
repair, or reinterpret it as an absent four-artifact baseline.

Between the earlier G2 scan pin and this final pin, heartbeat state changed only these
runtime/federation paths; no Context Bridge code, test, spec, root contract, workflow, or
setting changed:

```text
.steward/.context_hash
.steward/context.json
.steward/federation_health.json
.steward/marketplace.json
.steward/memory.json
.steward/sessions.json
data/federation/kirtan_ledger.json
data/federation/nadi_inbox.json
data/federation/nadi_outbox.json
data/federation/peers.json
data/federation/relay_seen_ids.json
data/federation/steward_health.json
```

### 2.2 Exact transaction names

The implementation must use exactly the names already binding in the parent contract:

```text
.steward/.context-publish-v1.lock
.steward/.context-publish-v1.<32 lowercase hex>.txn
.context-publish-v1.<32 lowercase hex>.claude.tmp
.context-publish-v1.<32 lowercase hex>.agents.tmp
.steward/.context-publish-v1.<32 lowercase hex>.snapshot.tmp
.steward/.context-publish-v1.<32 lowercase hex>.publication.tmp
```

No `.journal`, alternate suffix, unscoped glob, or second transaction namespace is
allowed. Unknown names beginning with `.context-publish-` block classification and are
never silently removed.

## 3. Allowed implementation surface

### 3.1 Product paths

The future code PR may add or modify only:

- one dedicated local transaction module (`steward/context_publication.py`, or a
  different exact path justified before implementation);
- direct unit/contract tests for that module;
- small test fixtures required to exercise real temporary repositories and crash states.

The code PR must not modify `steward/context_publisher.py`'s observation semantics,
Feature-04/renderer contracts, existing writers, tool registries, hooks, callers,
workflow, `.gitignore`, root files, repository settings, delivery, or runtime state.

### 3.2 Existing pure APIs to consume

The primitive may call the existing pure boundaries, without duplicating their languages:

- `build_publication_candidates()` and `validate_publication_candidates()` from
  `steward/context_rendering.py`;
- `validate_persisted_generation()` and the Constitution-bound validator from the same
  module;
- Feature-04 snapshot/payload/decision functions from `steward/context_contract.py`;
- the read-only D1 observation/read-back boundary from `steward/context_publisher.py`.

It must not create a second marker parser, JSON grammar, hash domain, attestation
validator, or publication classifier.

## 4. Public transaction contract

The future primitive returns an explicit immutable result such as:

```text
published | no_op | blocked | manual_review
```

It must not return a Boolean that turns a partial write or swallowed exception into
success. Every result carries a bounded machine-readable reason and the transaction ID
only when a valid own transaction exists. Raw bytes, secrets, exception text, absolute
foreign paths, or untrusted source prose never enter the journal or result.

### 4.1 Policy modes

`disabled | preview | canonical` is separate from Feature-04 content `OutputMode`.
Missing, unknown, or invalid policy is `disabled`.

- `disabled`: no target, lock, journal, tempfile, or cleanup mutation;
- `preview`: pure candidate construction/validation only; no target or transaction-file
  mutation;
- `canonical`: may enter the transaction only after an explicit, already reviewed policy
  decision and all fences pass.

This slice may implement the local mode gate as an injected value, but it may not add an
environment variable, repository policy file, workflow activation, or caller wiring.

### 4.2 Single snapshot and candidate group

Under the acquired transaction boundary, exactly one explicit snapshot is normalized and
exactly one immutable `PublicationCandidates` group is rendered. A second
`assemble_context()`, second source read, second renderer pass, or candidate mutation is
forbidden. The four bytes are bound to one transaction ID, snapshot ID, payload hash,
Constitution attestation, reviewed commit, and source blob.

## 5. Lock and path-fence contract

### 5.1 Lock

The lock implementation must obey the parent contract exactly:

- open `.steward/.context-publish-v1.lock` relative to a safely pinned `.steward` FD;
- flags `O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW`, mode `0600`;
- verify regular file, one hardlink, effective-UID ownership, safe parent, and unchanged
  lock inode after open;
- retain the lock inode; never unlink/recreate it as an unlock operation;
- acquire one per-real-repository process/thread lock, then exclusive POSIX `flock`;
- use one monotonic bounded deadline and reverse the acquisition order on release;
- hold the scope from the first repository/target fence through final read-back, final
  Git reference fence, and the result decision.

The lock is local to the isolated publisher worktree. It is not evidence that Bash,
Git, editors, child agents, or foreign processes cooperated.

### 5.2 Path and repository fences

Before every mutation, the primitive must prove:

- repository root, `.git`, and `.steward` are the pinned real directories;
- no relevant parent or target is a symlink, hardlink, replacement inode, or unsupported
  Git `commondir`/`gitdir`/alternates layout;
- all target names are the exact four allowed names;
- all transaction names match their one transaction ID and correct parent;
- HEAD, index, tree, target modes, target bytes, and parent fingerprints match the
  preceding fence;
- the publisher process/worktree identity remains the one selected at open.

Any mismatch is `manual_review`/`blocked` before the next write. It is never repaired by
trusting a newer path lookup or by silently adopting foreign bytes.

## 6. Journal and prepare contract

### 6.1 Journal

Exactly one journal is created exclusively at:

```text
.steward/.context-publish-v1.<txid>.txn
```

It is strict canonical JSON, mode `0600`, file- and parent-`fsync`ed before any target
tempfile or target replace. It binds only:

- schema version and 32-lowercase-hex transaction ID;
- repository root identity and reviewed HEAD commit;
- the exact four target paths and fixed replace order;
- baseline absence or HEAD blob/mode/byte hash for every target;
- candidate byte hashes and sizes;
- snapshot ID, payload hash, C0 hash, source blob, reviewed commit;
- bounded status needed for deterministic recovery.

It contains no raw candidate bytes, environment, token, exception text, wall-clock
freshness, or foreign absolute path. Duplicate, malformed, oversized, stale, or foreign
journals block recovery without mutation.

### 6.2 Four tempfiles

Each candidate is created with exclusive creation in the target's own parent, using the
exact transaction ID and the parent names in §2.2. The write loop must handle `EINTR`,
short writes, size overflow, and disk-full errors. Each tempfile is:

- opened with `O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW`, mode `0600`;
- fully written, file-`fsync`ed, read back, size/hash checked, and parent-`fsync`ed;
- rejected if the inode, parent, bytes, or mode changes before replace.

All four temps must be prepared and validated before the first target replace. A missing,
extra, unknown, or foreign temp is fail-closed.

## 7. Replace, read-back, and recovery

### 7.1 Replace order and durability

The only replace order is:

1. `CLAUDE.md`;
2. `AGENTS.md`;
3. `.steward/context-snapshot.json`;
4. `.steward/context-publication.json` last.

Each replace is dirfd-relative and preceded by a complete target/parent/Git fence. The
prepared inode is installed with deterministic final mode `0644`; the target parent is
`fsync`ed after each replace. This promises per-file atomic replacement, not impossible
two-file filesystem atomicity.

Success requires all four final bytes to be read back separately and to pass D1,
Constitution attestation, exact renderer reproduction, target/parent fingerprints, Git
HEAD/index, and transaction-ID checks. Journal removal and final `.steward` `fsync` must
complete before `published` or `no_op` is returned.

### 7.2 Recovery state machine

Recovery runs only under the same exclusive lock and only for exactly one strict journal:

| Observed state | Allowed result |
|---|---|
| all four candidate bytes match the journal | repeat final read-back/fence, then remove own temps/journal |
| partial replace and all current bytes match the attestable four-file baseline | restore that baseline in fixed order, read back, then clean own transaction |
| partial replace on a clean four-file-absent ephemeral baseline | remove only own journal-bound candidate temps and prove absence |
| `legacy_bootstrap`, unknown/manual bytes, multiple journals, foreign temps, unsafe path | `manual_review`/`blocked`, no automatic mutation |
| cleanup or final fence fails | visible blocked/manual-review result; preserve evidence |

An existing Publication Record alone, an MTime, a self-consistent but unbound candidate,
or the historical `.atomic_*` files is never recovery authority. No second C0 copy may
be embedded in code or journal.

## 8. Isolation and writer-boundary proof

The approved policy requires canonical publication in a dedicated process and isolated
publisher worktree. The G2 code review must prove, with real fixtures:

- normal Steward, child-agent, Bash, GitTool, dynamic-tool, actuator, healer,
  CircuitBreaker, CLI export, A2A persistence, and heartbeat processes cannot share the
  publisher worktree or write its protected names;
- an external writer in a separate checkout cannot alter the publisher's target bytes or
  Git evidence;
- a foreign process that is deliberately injected into the publisher worktree causes a
  fence/manual-review result and never a positive publication claim;
- unknown writer names and transaction artifacts fail closed;
- remote delivery is not performed by this local primitive.

The lock is not a substitute for this isolation proof.

## 9. Mandatory adversarial tests before code approval

The later code PR must include direct tests, not source-string assertions, for:

- thread and cross-process lock contention, deadline, interruption, stale inode,
  unlink/recreate, symlink, hardlink, owner, mode, unsafe parent, and release order;
- root, `.steward`, lock, journal, target, and tempfile replacement during every fence;
- `commondir`, `gitdir`, alternates, foreign index, HEAD change, unmerged index, staged
  delete, unexpected mode, duplicate/foreign target, and unsupported Git objects;
- short write, `EINTR`, overflow, disk-full, file-/parent-`fsync` failure, read-back
  mutation, process crash after journal/temp/replace/read-back, and cleanup failure;
- malformed/duplicate/foreign journal and temp names, wrong transaction ID, wrong parent,
  extra file, and unknown `.context-publish-*` signal;
- legacy bootstrap, absent baseline, valid baseline, mixed generation, invalid schema,
  unattested generation, and manual target edits;
- disabled and preview modes proving zero target and transaction-file writes;
- exact process executable/environment/worktree isolation and no direct delivery to `main`;
- every writer family from the approved writer policy, including configured path mutators;
- real Ubuntu CI durability/platform drill and fail-closed behavior on unsupported Darwin
  or other platforms.

Every adversarial result records pinned commit, fixture tree, bytes before/after, Git
evidence, result class, and whether a protected byte was read or written. A green unit
test without this evidence is not G2 proof.

## 10. Forbidden scope and rollback

The implementation PR must be rejected if it changes any of:

- existing writer/tool/agent/actuator/healer callers;
- `CLAUDE.md`, `AGENTS.md`, Constitution source, `.gitignore`, or runtime state;
- workflow, branch protection, CODEOWNERS, repository settings, delivery, or activation;
- Feature-04 schemas, hashes, marker parsers, or D1 read-back semantics;
- a second publisher, parser, candidate factory, or source of truth.

Rollback for a failed code PR is a normal revert of that isolated module/test diff. No
production runner, heartbeat, policy key, or root artifact may need cleanup because the
slice is required to remain uncalled and default-disabled.

## 11. Gate result

This is a complete read-only contract proposal, not an implementation authorization.
G1 remains **OFF** until adversarial review confirms the exact namespace, isolation
boundary, crash/recovery state machine, and test matrix. After G1, a separate operator
go is still required before any code PR.

Until then:

- D2b writer, lock, journal, recovery, bootstrap, delivery, workflow, and activation
  remain forbidden;
- the current `legacy_bootstrap` state remains untouched;
- D2a remains observation-only and fails closed;
- no automatic Context publication is enabled.
