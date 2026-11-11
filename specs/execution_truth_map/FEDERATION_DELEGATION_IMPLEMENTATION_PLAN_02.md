# Federation Delegation Implementation Plan 02

**Version:** 0.2 — Agent-B revision requested
**Status:** `PLAN ONLY — NO PRODUCT CODE AUTHORIZED`
**Date:** 2026-07-18
**Decision path:** Way A — target-local assignment evidence
**Feature gate:** `FEDERATION_V1_DELEGATION_ENABLED=false`

This plan deliberately stops at durable assignment. It does not redefine the frozen
`started` receipt and does not claim that a candidate has begun work.

## 1. Evidence and live pins

| Repository / artifact | Pin | Role |
| --- | --- | --- |
| Steward `main` after Recon PR #836 | `2f1ac917ff6f48a97839b0804cd201e1a2a8c030` | accepted documentation-only Recon merge |
| Agent City `main` | `a854f590391f73da10b33f402c321fd68f3fd0b5` | Slice-01A implementation and docs |
| Steward Protocol working `main` | `c51196d9e906c2e993d3548db6ef891b184b0b24` | live Task/Mission/registry models |
| Frozen wire contract | `specs/FEDERATION_DELEGATION_CONTRACT_V1_DRAFT_0_5.md` | V1 envelope and receipt contract |
| Slice-02 Recon | `abe4624e269122bf0ef9000bbbafdcf8ff0235e8` | accepted read-only dispatch-surface evidence |
| Prior Plan-02 revision | `91fc891e98c23db29f802e1094b5a200addf75ae` | superseded by this revision |

Heartbeat commits are excluded from semantic history review. They may be current live
heads, but they are not treated as architecture or implementation evidence.

The Recon proved that `TargetAdmissionLedger` already has the required process lock,
fail-closed corruption checks, atomic replacement, request/receipt bytes and admission
deduplication (`city/federation_v1.py:776-843`). It also proved that MissionRouter,
CityRouter, Sankalpa, TaskManager and AgentSpawner do not currently provide a V1-bound,
durable assignment owner.

## 2. Corrected slice boundary

### 2.1 The only proposed path

```text
validated ACCEPTED admission
  -> exactly one durable target-owned Candidate Assignment
  -> complete signed target-local Assignment Attestation
  -> no external receipt and no transport in Slice 02
  -> no mission, queue item, reservation, worker, cartridge, tool, LLM or Git action
```

`ASSIGNED` means only:

- an immutable candidate snapshot was selected;
- the snapshot was bound to the existing `target_work_id` and validated authority;
- the snapshot, digests, epoch and signed local attestation were atomically persisted;
- no reservation, mission, queue item, execution or continuing availability claim exists.

The frozen `receipt_stage=started` remains reserved for a later slice that creates at
least a durable local work item or a real scheduler reservation. Slice 02 does not use
`started` as a synonym for “assignment snapshot saved”.

### 2.2 Explicit decision: Way A

Draft 0.5 has no external `assignment` receipt stage. Reusing `started` would be a
semantic contract violation. Therefore this plan chooses Way A:

- assignment and its signed attestation remain target-local;
- no new Federation wire stage or carrier is introduced;
- Steward does not receive or apply assignment evidence in this slice;
- a later cross-repository slice must define and review an `assignment` receipt or a
  genuine `started` boundary before transporting this evidence;
- the current Steward truth remains the accepted admission and its `target_work_id`.

This is an intentional knowledge boundary, not an omitted feature.

### 2.3 Non-goals

- no `receipt_stage=started`;
- no external Assignment Receipt or new wire operation;
- no mission or Sankalpa record;
- no queue item, reservation or WorkerRegistry;
- no Worker/Cartridge/Tool/LLM/Git call;
- no lease, owner, timeout, recovery or blind retry;
- no terminal/verification receipt, status query or managed-task completion;
- no Provider Failover, Context Bridge, Execution Spine or activation.

## 3. Architecture decision: extend TargetAdmissionLedger

The existing target ledger remains the single target-owned persistence boundary. A
second assignment store is forbidden unless implementation proves a concrete inability to
extend the current record while preserving Slice-01A compatibility. A preference for a
new abstraction is not sufficient.

The existing lock and atomic writer must cover the complete transition from valid
`ACCEPTED` record to `ASSIGNED` record and the local signed attestation. No dual-write
between admission ledger and mission/task/queue state is permitted.

## 4. Durable state model

The existing target `state` remains `ACCEPTED|REJECTED`. A new field
`assignment_state` is added only to accepted records:

| `assignment_state` | Durable meaning | Receipt meaning |
| --- | --- | --- |
| `ACCEPTED` | Admission exists; no assignment commit exists | no external assignment/started receipt |
| `ASSIGNED` | Candidate snapshot, authority binding, epoch and signed local attestation are durable | no external receipt; no execution claim |

`ASSIGNMENT_PENDING` and `STARTED` are not Slice-02 ledger states. An in-memory
selection operation may be labelled pending, but it must never be serialized. A future
slice may introduce `started` only with a reviewed scheduler/work-item contract.

`assignment_epoch` is the positive integer `1` for the first assignment. There is no
lease or recovery epoch and no second assignment epoch in this slice.

## 5. Target-ledger schema diff

Existing Slice-01A admission fields remain authoritative. New fields are closed and
nullable until `assignment_state=ASSIGNED`:

| Field | Type / nullability | Required at `ASSIGNED` | Meaning |
| --- | --- | ---: | --- |
| `assignment_state` | enum `ACCEPTED|ASSIGNED` | yes | target-local assignment lifecycle |
| `assignment_epoch` | integer `1..2^63-1` or null | yes | always `1` here |
| `assigned_candidate_id` | `IdString` or null | yes | local Agent/Pokedex identity; not ownership |
| `observed_candidate_snapshot` | closed object or null | yes | immutable observed candidate facts |
| `worker_snapshot_digest` | lowercase SHA-256 hex or null | yes | digest of snapshot object |
| `assignment_authority_digest` | lowercase SHA-256 hex or null | yes | digest of policy/authority binding |
| `assigned_at` | RFC-3339 UTC timestamp or null | yes | time of assignment commit |
| `assignment_attestation_id` | `IdString` or null | yes | target-local attestation identity |
| `assignment_content_digest` | lowercase SHA-256 hex or null | yes | semantic attestation-body digest |
| `assignment_message_hash` | lowercase SHA-256 hex or null | yes | local attestation envelope/body hash |
| `assignment_signature` | padded RFC-4648 Base64 or null | yes | target signing-key signature |
| `assignment_wire_bytes_b64` | padded RFC-4648 Base64 or null | yes | complete signed local attestation bytes |

There are deliberately no `started_receipt_*`, `receipt_send_status`, `owner`, `lease`
or `worker_started` fields in this slice. The local attestation is not a Federation
message and has no transport status.

### 5.1 Local Assignment Attestation

The attestation is a target-local, signed, content-addressed evidence object. It is not
an external receipt and is not independently verifiable by Steward in Slice 02.

Its closed semantic body is:

```json
{
  "assignment_attestation_version": "federation-assignment-attestation-v1",
  "assignment_authority_digest": "<64 lowercase hex>",
  "assignment_epoch": 1,
  "assignment_state": "ASSIGNED",
  "delegation_id": "<delegation_id>",
  "observed_at": "YYYY-MM-DDTHH:MM:SSZ",
  "target_node_id": "<local target node>",
  "target_work_id": "<admission target_work_id>",
  "worker_snapshot_digest": "<64 lowercase hex>"
}
```

The full `observed_candidate_snapshot` remains in the target ledger; its digest and the
authority digest are bound in the attestation body. Canonical bytes use the frozen
SFDJ-1 profile. The local signature input is:

```text
UTF8("STEWARD-FEDERATION-ASSIGNMENT-ATTESTATION-V1\0")
|| SHA256(SFDJ-1(canonical attestation body))
```

The attestation proves only the target's signed claim that it committed the stated
assignment record. It is not a verification receipt and does not prove work, execution,
reservation or candidate availability after `observed_at`.

### 5.2 Legacy records

Valid Slice-01A records without assignment fields are loaded as in-memory
`assignment_state=ACCEPTED` with null assignment fields. Reads do not rewrite them.
Only an explicit Slice-02 assignment commit adds the new fields. Malformed partial
assignment blocks fail closed as `ledger_corrupt` or a deterministic assignment conflict;
they are never auto-repaired or copied into a second store.

## 6. Candidate snapshot and staleness contract

Candidate discovery may read `CityRouter`, `AgentSpawner`/Pokedex and cartridge metadata.
It must not create a mission, reserve an agent, invoke a cartridge or call a worker.

### 6.1 Snapshot shape

`observed_candidate_snapshot` is the honest name because the current systems do not
expose an authoritative worker reservation or stable ownership generation. Its closed
shape is:

```json
{
  "candidate_id": "sys_example",
  "capabilities": ["read", "test"],
  "capability_protocol": "",
  "capability_tier": "contributor",
  "cartridge_id": "example",
  "domain": "engineering",
  "guardian": "",
  "observed_at": "YYYY-MM-DDTHH:MM:SSZ",
  "snapshot_schema": "federation-assignment-candidate-v1",
  "source_generation": "obs_<64 lowercase hex>"
}
```

`source_generation` is a derived observation token, not a registry reservation or
worker-ownership claim. It is the domain-separated SHA-256 of the canonical source view
used to construct the snapshot. If a future Pokedex/registry exposes a real stable
generation, that value may replace the derived token under a separately reviewed schema
change. No secrets, paths, prompts, stacktraces, dynamic health or free task text enter
the snapshot.

The source view is a closed, sorted list of the candidate IDs, cartridge IDs and
capability facts observed in the local registry/router read. Its token is:

```text
source_generation = "obs_" + lowercase_hex(SHA256(
  UTF8("STEWARD-FEDERATION-ASSIGNMENT-SOURCE-V1\0") || SFDJ-1(source_view)
))
```

This token identifies the observed input set only. It is not a registry version, a
reservation fence or proof that the candidate remains available after the commit.

### 6.2 Generation and stale check

Immediately before the assignment commit, the adapter must read the candidate source a
second time and recompute the source-generation token. The commit is allowed only when:

- the source-generation token is unchanged;
- the selected candidate's ID, cartridge ID and capability facts are unchanged;
- the candidate still satisfies the validated V1 authority/capability policy.

If the source token or candidate facts changed, the operation returns
`candidate_snapshot_stale`, leaves the ledger `ACCEPTED`, and creates no attestation.
If no candidate qualifies, it returns `assignment_unavailable`, leaves the ledger
`ACCEPTED`, and creates no attestation. Neither result claims that a candidate remains
available after the observation.

### 6.3 Candidate digest

For canonical snapshot bytes `C`:

```text
worker_snapshot_digest = lowercase_hex(SHA256(
  UTF8("STEWARD-FEDERATION-ASSIGNMENT-CANDIDATE-V1\0") || C
))
```

If multiple candidates qualify, select the ascending `(candidate_id, cartridge_id)`
tuple. This is deterministic observation, not reservation.

### 6.4 Authority digest

The closed authority input binds the validated request, target work, candidate digest and
epoch:

```json
{
  "assignment_policy": "federation-delegation-assignment-v1",
  "assignment_epoch": 1,
  "authority": {"allowed_actions": [], "denied_actions": [], "repo_scope": "agent-city"},
  "candidate_id": "sys_example",
  "capability": "fix_repository",
  "delegation_id": "<delegation_id>",
  "target_node_id": "<local target node>",
  "target_work_id": "<target_work_id>",
  "worker_snapshot_digest": "<64 lowercase hex>"
}
```

```text
assignment_authority_digest = lowercase_hex(SHA256(
  UTF8("STEWARD-FEDERATION-ASSIGNMENT-AUTHORITY-V1\0") || SFDJ-1(A)
))
```

The digest binds authority evidence; it does not grant new authority.

## 7. Atomic assignment algorithm

1. Under the existing target-ledger lock, load and validate the record. Corruption
   yields `ledger_corrupt`; no candidate read or attestation occurs.
2. Require `state=ACCEPTED` and a non-null admission `target_work_id`.
3. If `assignment_state=ASSIGNED`, return the stored local attestation bytes and compare
   any supplied candidate snapshot/digests. An identical duplicate is a no-op; a changed
   candidate, authority digest, epoch or bytes is `assignment_conflict`.
4. Read candidate metadata without invoking any mission/router execution path, construct
   the observed snapshot and source-generation token, and mark the operation internally
   pending only.
5. Re-read the source view immediately. If generation, candidate facts or authority
   qualification changed, stop with `candidate_snapshot_stale` and leave `ACCEPTED`.
6. Build canonical attestation bytes, content digest, message hash and target signature
   before changing the ledger.
7. Re-enter the target-ledger lock and re-read the record. If another process won, apply
   the duplicate/conflict rules; never overwrite its assignment.
8. For unchanged `ACCEPTED`, atomically persist `assignment_state=ASSIGNED`, epoch,
   observed snapshot, both digests, timestamp and complete signed attestation bytes.
9. Return the local attestation/result to the target caller. Do not construct a
   Federation carrier or send a network response for assignment evidence.
10. No step invokes MissionRouter execution, Sankalpa, TaskManager, Worker/Cartridge,
    HealExecutor, Tool, LLM, Git or a recovery engine.

### Atomic invariant

After a successful assignment commit, one target-ledger record contains exactly one
unchanged `target_work_id`, epoch `1`, one immutable observed snapshot, matching
candidate/authority digests and complete signed local attestation bytes. There is no
durable assignment without its signed local evidence and no second store to reconcile.

## 8. Steward knowledge boundary

There is no external assignment receipt in Way A. Steward therefore does **not** apply
or independently verify an assignment in Slice 02. Steward may continue to verify the
existing admission receipt and retain the following binding facts:

- valid target signature and provenance;
- source/target, delegation, correlation, request-root and causation IDs;
- admission `target_work_id` first-set/duplicate equality;
- if a future signed assignment attestation is delivered, its digest URI and ID shapes
  can be syntax-checked under a later contract.

Steward cannot prove from an opaque digest URI that the target ledger contains the full
candidate or authority snapshot. The correct terminology is **signed target attestation**
once such evidence is transported, not independent verification. In Plan 02 the
attestation is target-local and not transported at all. No origin task state changes.

## 9. Crash, duplicate and negative matrix

| Scenario | Required result |
| --- | --- |
| duplicate identical assignment after `ASSIGNED` | same local attestation bytes; no second assignment |
| same delegation with changed candidate snapshot | `assignment_conflict`; ledger unchanged |
| changed authority digest or epoch | `assignment_conflict`; ledger unchanged |
| crash before candidate selection | remains `ACCEPTED`; no assignment/evidence |
| crash after first observation, before stale re-check | remains `ACCEPTED`; no assignment/evidence |
| stale source generation at re-check | `candidate_snapshot_stale`; no assignment/evidence |
| crash after attestation construction, before commit | remains `ACCEPTED`; no persisted/sent evidence |
| crash after atomic assignment commit | `ASSIGNED` with complete local attestation; no network receipt |
| no candidate | `assignment_unavailable`; remains `ACCEPTED` |
| capability/authority mismatch | local finding; no assignment and no network response |
| wrong target work ID in a supplied duplicate | local conflict; no mutation |
| corrupted target ledger | `ledger_corrupt`; fail closed |
| concurrent identical calls | exactly one `ASSIGNED` record; identical local bytes returned |
| concurrent changed candidate calls | one first-set winner; conflicting caller fails closed |
| legacy Nadi/TaskManager/MissionRouter/HealExecutor path | unchanged and regression-green |

No row creates a `started` receipt, lease, recovery decision or worker claim.

## 10. Wiring and migration boundary

No new Federation operation is wired. The existing `delegation_receipt` remains
admission-only in this slice; its `started` stage is untouched and reserved for a later
work-item/scheduler slice.

The only proposed target wiring is a feature-gated, target-local assignment method at
the existing ledger boundary, with:

- read-only candidate snapshot source;
- authority/capability gate;
- target-ledger assignment fields and local attestation writer;
- assignment idempotency/conflict checks;
- local tests for stale snapshots, concurrency and crash points.

Steward receives no new assignment handler or receipt application path in Way A. The
docs wiring manifest remains documentation-only. Lifecycle maturity may progress only
after tests, but disposition stays `disabled` and the feature gate stays `false`.

Legacy `OP_DELEGATE_TASK`, title matching, NADI, Sankalpa, TaskManager, MissionRouter
execution, cartridges and HealExecutor are not called or modified.

## 11. Test gates for the eventual implementation

### Target-local positive tests

- one accepted admission becomes one `ASSIGNED` record;
- local attestation bytes, signature, content digest, snapshot and authority digest are
  persisted in the same atomic write;
- exact duplicate returns byte-identical local evidence;
- target work ID and assignment epoch remain unchanged;
- stale-check passes only when both source observations are identical;
- no mission, queue, worker or tool call is observed.

### Target-local negative/crash tests

- changed candidate snapshot, source generation, authority digest or epoch;
- no candidate and capability/authority mismatch;
- crash before/after each pre-commit phase;
- crash after commit proves durable local evidence but no external receipt;
- corrupt ledger and process-concurrent identical/conflicting writers;
- legacy NADI, TaskManager, MissionRouter and HealExecutor regressions remain green.

### Deferred cross-repository gate

There is no cross-repository assignment assertion in Slice 02 because no external
assignment receipt exists. The later slice that introduces a reviewed `assignment`
receipt or a genuine scheduler/work-item `started` boundary must add:

- independent Steward/Agent-City parsing and signature tests;
- signed target-attestation correlation;
- proof of the target work item or reservation that `started` is supposed to mean.

## 12. Definition of Done

Plan 02 implementation may be proposed for review only when:

1. `ACCEPTED -> ASSIGNED` is a single target-ledger atomic transition.
2. The target persists one immutable observed candidate snapshot with source token and
   observation time, and rejects stale changes before commit.
3. Assignment epoch, target work ID and authority/candidate digests are first-set and
   duplicate-stable.
4. Complete signed local assignment-attestation bytes are in the same commit.
5. No external receipt, `started` claim, mission, queue item, reservation, worker or
   side effect exists.
6. Steward makes no independent target-evidence or assignment-verification claim.
7. Legacy paths and the default-disabled feature gate remain unchanged.
8. The target-local crash/duplicate/concurrency tests are green and a self-contained
   implementation review packet records exact SHAs and measured results.

## 13. Agent-B review gate

Agent B should confirm:

- Way A is the correct choice while Draft 0.5 lacks an assignment receipt;
- `ASSIGNED` is not being used as a hidden worker/reservation claim;
- `observed_candidate_snapshot`, source token and pre-commit re-check are sufficient to
  make staleness honest without inventing a registry generation;
- the local signed attestation is narrowly scoped and cannot be mistaken for a V1
  receipt or independent verification;
- the target-ledger extension preserves valid Slice-01A records and atomicity;
- no Steward correlation or evidence claim exceeds the origin's actual knowledge;
- the deferred `started`/cross-repo gate is explicit and testable;
- no forbidden mission, queue, worker, tool, recovery or activation path is implied.

**No product implementation is authorized until this revision is accepted.**
