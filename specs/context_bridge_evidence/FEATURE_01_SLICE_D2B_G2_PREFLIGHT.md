# FEATURE 01 — SLICE D2b G2 PRE-FLIGHT

> **Status:** DRAFT 0.1 — READ-ONLY G2 CONTRACT; G1 OFF; IMPLEMENTATION LOCKED
>
> **Investigated main:** `kimeisele/steward@9621fafb5e3f2c96b9b77beb446e2197df60fc1a`
>
> **Investigated tree:** `b86446d7fc97ac0d943023c3d511f5d91c3dd85c`
>
> **D2b parent preflight:** `f582e0d63876df8be61e8970a0fe065a2b2c034e`
>
> **Writer-policy merge:** `0260c53950fbddbf037d607cca2031467744bcfa`
>
> **Earlier G2 scan pin:** `ad09f81c369309b576eaac5d9ccec9ecabee0298`
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

The pinned `origin/main` is clean. A live GitHub query at the pin listed exactly PR #707
(this preflight) and unrelated PR #693; there was no other open Context Bridge PR. PR #707
is therefore explicitly part of the evidence, not an omitted overlap. PR #693 is outside
this slice and changes neither the protected paths nor the D2b code surface.

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
data/federation/quarantine/index.json
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

### 4.3 `no_op` semantics

`no_op` is returned only when the existing state is already a complete, valid, attestable
four-artifact generation and all four separately read target bytes are byte-for-byte equal
to the one immutable candidate group. The current HEAD, index, target/parent identities,
source attestation, and policy fence must all match, and no lock, journal, tempfile, or
unknown transaction signal may exist. `no_op` creates, removes, or rewrites no target or
transaction path. `legacy_bootstrap`, absent, mixed, invalid, unattested, unbound, or
ambiguous states can never be reported as `no_op`.

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

### 5.3 Process, environment, CWD, FD, and input allowlist

The isolation policy is only implementable with a concrete allowlist. The future
publisher/helper process may use exactly:

- **Executables:** one absolute interpreter selected from
  `/usr/bin/python3`, `/bin/python3`, `/usr/bin/python3.11`, `/bin/python3.11`,
  `/usr/bin/python3.12`, or `/bin/python3.12`, plus Git at `/usr/bin/git` or
  `/bin/git`. The selected path and every symlink target/component must be regular or
  directory, root-owned, non-group/world-writable, cycle-free, and revalidated before
  spawn. No `PATH` search, shebang lookup, caller executable, shell, or arbitrary helper
  is allowed. If no listed path passes, the result is `blocked`.
- **Environment:** exactly `LC_ALL=C`, `LANG=C`, `PATH=/usr/bin:/bin`,
  `GIT_OPTIONAL_LOCKS=0`, `GIT_NO_REPLACE_OBJECTS=1`, `GIT_PAGER=cat`,
  `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, and
  `GIT_CONFIG_SYSTEM=/dev/null`. `PYTHONPATH`, `PYTHONHOME`, `LD_*`, `GIT_DIR`,
  `GIT_WORK_TREE`, `GIT_INDEX_FILE`, object/replace/common-dir overrides, credentials,
  tokens, and every other inherited variable are absent.
- **CWD:** the helper starts at `/` and enters only the already opened repository or
  `.git` directory by descriptor (`fchdir`/dirfd). The publisher worktree is selected by
  a pinned directory FD; no path-based CWD change is trusted after the first fence.
- **File descriptors:** stdin is a read-only `/dev/null`; stdout and stderr are bounded
  pipes (stdout at most 16,384 bytes for metadata and target-limit-plus-one for a blob,
  stderr at most 4,096 bytes); only the pinned Git FD is passed intentionally, with all
  other descriptors `CLOEXEC`/closed. Processes are reaped and process groups killed on
  timeout.
- **Inputs:** fixed argv lists, exact target tuple, typed immutable snapshot/attestation,
  closed mode enum, one 32-lowercase-hex transaction ID, absolute validated repository
  FD, and journal JSON capped at 65,536 bytes. No free-form command, path, source prose,
  environment, or untyped mapping crosses the process boundary.

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
- per-target parent identity `{device, inode, type, link_count, mode}`;
- baseline absence or HEAD blob/mode/byte hash for every target;
- candidate byte hashes and sizes;
- snapshot ID, payload hash, C0 hash, source blob, reviewed commit;
- a closed status, replace cursor, fixed completed-target prefix, in-flight target, and
  installed-target `{device, inode, type, link_count, mode, size, candidate_sha256}`
  identities needed for deterministic recovery.

It contains no raw candidate bytes, environment, token, exception text, wall-clock or
MTime freshness, or foreign absolute path. Duplicate, malformed, oversized, or foreign
journals block recovery without mutation.

The journal schema is closed and its status transitions are durable and monotone:

```text
status = prepared | replacing | replaced | read_back_validated
prepared -> replacing -> replaced -> read_back_validated
```

`prepared` has cursor `0`, no completed targets, and no in-flight target. `replacing` has
an in-flight target equal to the next member of the fixed replace order; after a
successful dirfd-relative replace and fstat, that target's `{device, inode, mode,
candidate_sha256}` is durably recorded and the cursor advances. `replaced` has cursor
`4` and the complete four-target prefix. `read_back_validated` is allowed only after
the final D1/attestation/read-back and Git fence. Backward transitions, skipped targets,
unknown fields, duplicate target identities, or an installed target without its journal
identity are invalid and require `manual_review`.

The exact top-level key set is:

```text
schema, txid, repository, reviewed_head, replace_order, targets,
snapshot_id, payload_hash, c0_sha256, source_blob, status, cursor,
completed_targets, in_flight_target, installed_targets
```

`schema` is exactly `steward.context.transaction/v1`; `txid` is exactly 32 lowercase
hex characters; `reviewed_head` and `source_blob` are 40 lowercase hex characters;
`c0_sha256` and `payload_hash` are 64 lowercase hex characters; `snapshot_id` matches
`ctxsnap-v1:[0-9a-f]{64}`; and `replace_order` is exactly the JSON array
`["CLAUDE.md", "AGENTS.md", ".steward/context-snapshot.json", ".steward/context-publication.json"]`.
`repository` is exactly `{root, git, steward}`, each an identity object with exactly
`{device, inode, type, link_count, mode}`; `targets` is exactly that same four-key ordered
map in `replace_order`. Each target record has exactly
`parent`, `baseline`, `candidate`, and `installed`; `parent` is exactly
`{device, inode, type, link_count, mode}` with non-negative integer identities,
`type=directory`, and its observed safe mode; `baseline` has exactly
`{present, mode, blob, sha256, size}` where `present` is boolean and all other values are
null when it is false; when true, `mode` is a permission-bit integer, `blob` is 40
lowercase hex characters, `sha256` is 64 lowercase hex characters, and `size` is an
integer from zero through the target's exact Feature-04 limit (`CLAUDE.md`/`AGENTS.md`
65536, snapshot 131072, publication 16384). `candidate` has exactly `{sha256, size}`
with a 64-hex hash and the same per-target size bound; `installed` is null until the
target is replaced and otherwise
has exactly `{device, inode, type, link_count, mode, size, candidate_sha256}` with
`type=regular`, `link_count=1`, final mode `0644`, and a 64-hex candidate hash.

`cursor` is an integer `0..4`; `completed_targets` is exactly the ordered prefix of that
length; `in_flight_target` is null only for `prepared`, `replaced`, or
`read_back_validated`, and is exactly the next target for `replacing`; and
`installed_targets` contains exactly the durable prefix identities. The canonical
representation is UTF-8 without a BOM, uses the listed key order and compact JSON
separators, and rejects NaN, Infinity, duplicate keys, and non-ASCII control characters.
Its byte length is at most 65,536. Any extra key, wrong type, non-canonical encoding, or
over-limit field is invalid.

Recovery never calls a journal "stale" from age or MTime. After the lock is acquired,
an orphaned journal is classified only from its bound repository identity, reviewed HEAD,
closed status, transaction names, baseline/candidate byte hashes, target types, and
recorded inodes. A HEAD change, unsupported Git layout, missing/foreign inode, or any
byte state outside the journal's baseline/candidate set is `manual_review` with no
automatic mutation.

The serialized schema is bounded and typed: `schema` is one fixed ASCII identifier;
`txid`, `head`, source blob, C0 hash, payload hash, snapshot ID, and candidate hashes are
fixed lowercase-hex/ASCII identifiers of their contract lengths; `targets` is exactly the
four-key ordered map; every identity member is a non-negative integer except the closed
mode/type strings; `cursor` is an integer `0..4`; `completed_targets` is exactly the
ordered prefix of length `cursor`; `in_flight_target` is null only for `prepared`,
`replaced`, or `read_back_validated`, and is exactly the next target for `replacing`; and
`installed_targets` contains exactly the durable prefix identities. The canonical
representation is UTF-8 without a BOM, compact, ordered as specified, and at most 65,536
bytes; any extra key, wrong type, duplicate key, non-canonical encoding, or over-limit
field is invalid.

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

Success requires all four final bytes to be read back separately and to equal the already
generated immutable candidate bytes byte-for-byte. D1 and Constitution attestation validate
those bytes; the publisher performs no second renderer pass. The read-back must also pass
the per-target journalized expected state, parent/target fingerprints, Git HEAD/index, and
transaction-ID checks. Journal removal and final `.steward` `fsync` must complete before
`published` or `no_op` is returned.

### 7.2 Recovery state machine

Recovery runs only under the same exclusive lock and only for exactly one strict journal:

| Observed state | Allowed result |
|---|---|
| `status=replaced` or `read_back_validated`, `cursor=4`, all four completed targets and installed target/parent identities match the journal, all four final bytes equal the journalized candidates, and D1/attestation/Git fences pass | repeat/confirm final read-back if needed, then remove only own temps/journal |
| partial replace and all current bytes match the attestable four-file baseline | restore that baseline in fixed order, read back, then clean own transaction |
| `status=replacing`, cursor `1..3`, completed prefix and every installed candidate target's recorded parent/target identity and candidate hash/mode match, while the bound baseline is four-file absent and D1/attestation/Git fences pass | enter the isolated deletion fence in §7.3, unlink only journal-/candidate-bound target inodes, `fsync` each affected parent, remove own temps/journal, then prove all four targets absent in worktree, HEAD, and index |
| four-file-absent baseline but an installed target lacks a matching recorded inode, parent, mode, or candidate hash | `manual_review`/`blocked`; do not guess whether the target is publisher-owned |
| `legacy_bootstrap`, unknown/manual bytes, multiple journals, foreign temps, unsafe path | `manual_review`/`blocked`, no automatic mutation |
| cleanup or final fence fails | visible blocked/manual-review result; preserve evidence |

An existing Publication Record alone, an MTime, a self-consistent but unbound candidate,
or the historical `.atomic_*` files is never recovery authority. No second C0 copy may
be embedded in code or journal.

### 7.3 Fourfold-absent deletion fence

`fstat` followed by an unguarded name-based `unlink` is not sufficient. Before any
absent-baseline cleanup, the publisher must hold the positively attested isolated-worktree
lease, open each expected parent by its pinned dirfd, and compare its device, inode, type,
link-count, and mode with the journal. The lease is an enforceable exclusion boundary,
not a flag: it must prevent an untrusted process from renaming, replacing, linking, or
unlinking any protected parent or target for the entire check-to-unlink interval. If the
platform or deployment cannot enforce that boundary, recovery must return
`manual_review` without attempting deletion. It then opens each installed target with
`O_RDONLY | O_CLOEXEC | O_NOFOLLOW`, compares the complete journalized device/inode/type/
link-count/mode/size tuple and candidate hash, and rechecks the parent immediately before
the deletion fence. Any exchange, missing identity, extra link, or hash mismatch returns
`manual_review` before mutation.

The unlink operation is permitted only inside that positively attested private worktree
lease and is dirfd-relative. It is followed by parent `fsync`, fresh parent `fstat`, and
an `lstat` proving the exact target name is absent. If the parent or name changes at any
point, including an exchange observed by the lease monitor, the lease/fence is invalid
and the result is `manual_review` with no further mutation. Because POSIX has no portable
compare-and-unlink primitive, a check-to-unlink race that cannot be excluded is never
treated as recoverable after the fact. The fourfold-absent proof is complete only when
all four worktree names are absent and the bound HEAD/index still prove baseline absence.

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
