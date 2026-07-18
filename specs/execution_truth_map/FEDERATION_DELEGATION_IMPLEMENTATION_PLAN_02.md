# Federation Delegation Implementation Plan 02

**Version:** 0.1 — Plan for Agent-B review
**Status:** `PLAN ONLY — NO PRODUCT CODE AUTHORIZED`
**Date:** 2026-07-18
**Scope:** durable target assignment and `started` evidence only
**Feature gate:** `FEDERATION_V1_DELEGATION_ENABLED=false`
**Production activation:** forbidden in this plan

This is a self-contained implementation decision proposal. It does not implement a
handler, ledger migration, worker call, mission creation, receipt builder, or runtime
wiring. Product changes may begin only after Agent-B accepts this plan and a separate
implementation review gate is opened.

## 1. Evidence and live pins

| Repository / artifact | Pin | Evidence boundary |
| --- | --- | --- |
| Steward `main` after Recon PR #836 | `2f1ac917ff6f48a97839b0804cd201e1a2a8c030` | Merge commit of the accepted documentation-only Recon |
| Agent City `main` | `a854f590391f73da10b33f402c321fd68f3fd0b5` | Slice-01A implementation plus docs merge |
| Steward Protocol working `main` | `c51196d9e906c2e993d3548db6ef891b184b0b24` | live `Task`, `TaskManager`, `SankalpaMission` and registry models |
| Frozen wire contract | `specs/FEDERATION_DELEGATION_CONTRACT_V1_DRAFT_0_5.md` | `started` receipt already exists in the closed V1 receipt schema |
| Slice-02 Recon | `abe4624e269122bf0ef9000bbbafdcf8ff0235e8` | accepted Recon; no code changes |

The current Steward head was re-read after PR #836. Heartbeat commits are excluded from
semantic history review (`git log --grep=heartbeat --invert-grep`); a heartbeat head,
if it is the current remote pin, is live-state evidence only and never an architectural
progress signal.

The Recon established these concrete facts:

- Agent City `TargetAdmissionLedger` already owns admission, dedupe, request/receipt
  bytes, receipt send status and the synthetic `target_work_id` with inter-process lock,
  fail-closed corruption checks and atomic replacement (`city/federation_v1.py:776-843`).
- No existing Agent City mission, router, spawner, TaskManager or worker registry owns a
  V1 `delegation_id` plus durable assignment atomically.
- `SankalpaMission` has only mission identity, purpose, status, owner and timestamps
  (`steward-protocol/.../sankalpa/types.py:213-229`). `CityRouter` and MissionRouter are
  in-memory/pure routing surfaces, not assignment ledgers.
- No V1 `started` builder or handler exists. The frozen contract does, however, define
  `delegation_receipt` stage `started`, issuer role `target_scheduler`, status `started`,
  `target_work_id`, `started_at` and `attempt_count`.

## 2. Exact slice and non-goals

### 2.1 Authorized slice proposal

```text
validated ACCEPTED admission
  -> one target-owned durable assignment in the existing target ledger
  -> no MissionRouter mission, Sankalpa mission, TaskManager task, worker, cartridge,
     tool, LLM, Git or other external side effect
  -> complete signed delegation_receipt(stage=started) persisted in the same assignment
     commit
  -> closed receipt carrier
  -> Steward verifies and binds the receipt to the original delegation and the same
     target_work_id
```

`started` means only: a durable assignment snapshot and its signed start evidence were
committed. It does **not** mean code, a tool, an LLM, Git, a mission or any external side
effect was executed.

### 2.2 Explicit exclusions

- Mission creation or Sankalpa registry writes.
- Worker/cartridge invocation or WorkerRegistry creation.
- Tool, LLM, Git, filesystem-repair, PR or network side effects beyond receipt transport.
- Lease, timeout, ownership fencing, `RECOVERY_REQUIRED` automation or blind retry.
- Terminal or verification receipts, status query, managed-task completion or workflow
  escalation.
- Provider Failover, Context Bridge, Execution-Spine system specification and merge
  authority.
- Feature-gate activation or productive caller wiring.

## 3. Architecture decision: extend the existing TargetAdmissionLedger

### Decision

The preferred design is to extend the existing `TargetAdmissionLedger` record and its
existing inter-process read/modify/write critical section. No second independent work
store is introduced in Slice 02.

### Why this is the smallest truthful boundary

The current target ledger already provides:

- one durable owner for `delegation_id` and `target_work_id`;
- persistent request and receipt wire bytes;
- duplicate and digest-conflict checks;
- fail-closed handling of corrupt files;
- the repository's existing process lock and atomic `fsync`/replace writer.

A second assignment store would require a dual write between admission and assignment,
creating exactly the crash gap this slice is meant to close. Reusing generic Sankalpa,
TaskManager or CityRouter state would be worse: none carries the V1 identity, the target
ledger's lock or the frozen receipt evidence.

### Rejection condition

This decision may be revisited only if implementation inspection proves that the current
ledger cannot atomically persist the additional closed fields while preserving legacy
Slice-01A records. The burden of proof is a concrete code/test failure, not a preference
for a new abstraction. If the ledger cannot be extended, the plan returns to Agent-B
before any second store is created.

## 4. Assignment state model

The existing target record keeps `state=ACCEPTED|REJECTED`. Slice 02 adds a separate
`assignment_state` field.

| State | Durable meaning | Allowed fields | Receipt meaning |
| --- | --- | --- | --- |
| `ACCEPTED` | Admission is durable; no assignment has been committed | all assignment/started fields null/absent | no started receipt exists |
| `ASSIGNMENT_PENDING` | **Internal operation label only** while candidate selection and receipt construction occur | never serialized; never returned as a durable claim | none |
| `ASSIGNED` | **Internal pre-commit label only**; not serialized because it would split assignment from start evidence | never serialized | none |
| `STARTED` | Assignment snapshot, epoch and complete signed started-receipt bytes are durable in one commit | all required assignment/started fields populated | `receipt_stage=started`, `status=started` |

`ASSIGNMENT_PENDING` and `ASSIGNED` are intentionally not persisted states. Persisting an
intermediate state would create a second transaction between assignment and the signed
receipt, while the required invariant is one atomic assignment/start commit. A process
crash before that commit leaves the record `ACCEPTED`; it does not leave a phantom
assignment. The durable V1 state set for this slice is therefore `ACCEPTED`, `REJECTED`
and `STARTED`.

`assignment_epoch` is the positive integer `1` for the first and only assignment in this
slice. There is no increment, lease renewal or recovery epoch. Any future retry/recovery
semantics require a separate accepted plan.

## 5. Target-ledger schema diff

The current required target record fields remain unchanged. The following closed fields
are added for an `ACCEPTED` record; they are nullable until `assignment_state=STARTED`.
An authenticated `REJECTED` record has no assignment and all of these fields are null.

| Field | Type / nullability | Required when | Semantics |
| --- | --- | --- | --- |
| `assignment_state` | enum `ACCEPTED\|STARTED`; non-null for `state=ACCEPTED` | always on new accepted records | durable assignment lifecycle; no `ASSIGNMENT_PENDING`/`ASSIGNED` serialization |
| `assignment_epoch` | integer `1..2^63-1` or null | `STARTED` | always `1` in Slice 02 |
| `assigned_candidate_id` | `IdString` or null | `STARTED` | stable local Agent/Pokedex identity; explicitly not worker ownership |
| `assigned_candidate_snapshot` | closed object or null | `STARTED` | immutable candidate attributes used for selection |
| `worker_snapshot_digest` | lowercase SHA-256 hex or null | `STARTED` | digest of the canonical candidate snapshot |
| `assignment_authority_digest` | lowercase SHA-256 hex or null | `STARTED` | digest of the exact V1 authority/policy input |
| `assigned_at` | RFC-3339 `YYYY-MM-DDTHH:MM:SSZ` or null | `STARTED` | assignment evidence timestamp; equals `started_at` |
| `started_receipt_message_id` | `IdString` or null | `STARTED` | current receipt envelope identity |
| `started_receipt_id` | `IdString` or null | `STARTED` | business receipt identity |
| `started_receipt_content_digest` | lowercase SHA-256 hex or null | `STARTED` | semantic receipt-body digest |
| `started_receipt_message_hash` | lowercase SHA-256 hex or null | `STARTED` | envelope hash |
| `started_receipt_signature` | padded RFC-4648 Base64 or null | `STARTED` | Ed25519 signature over the frozen domain-separated input |
| `started_receipt_wire_bytes_b64` | padded RFC-4648 Base64 or null | `STARTED` | complete immutable signed receipt bytes |
| `started_receipt_carrier` | closed carrier object or null | `STARTED` | exact transport carrier derived from those bytes |
| `started_receipt_send_status` | enum `pending\|sent` or null | `STARTED` | transport bookkeeping only |

The existing admission fields remain authoritative: `delegation_id`, request root,
request digest, `target_work_id`, admission receipt fields and `state`. No field named
`owner`, `lease`, `worker_started` or `execution_status` is added.

### 5.1 Legacy-record compatibility

Slice-01A records predate the new assignment keys. The planned ledger reader must:

1. validate all existing Slice-01A required fields exactly as before;
2. treat a missing assignment block on a valid `ACCEPTED` record as an in-memory
   `assignment_state=ACCEPTED` with null assignment fields;
3. treat a missing assignment block on a valid `REJECTED` record as null assignment;
4. never rewrite or fabricate assignment evidence during read-only load;
5. write the new fields only when the explicit Slice-02 assignment operation commits;
6. reject malformed or partially populated assignment fields as `ledger_corrupt` or a
   deterministic assignment conflict, never silently repair them.

No top-level second database, automatic migration job or destructive rewrite is allowed.

## 6. Candidate selection contract

Candidate discovery is read-only and occurs before the assignment commit. It may consult
the existing `CityRouter` indices, `AgentSpawner`/Pokedex lifecycle and cartridge
metadata. It must not create a mission, reserve an agent, invoke a cartridge or call a
worker.

### 6.1 Stable candidate identity

`assigned_candidate_id` is the active local Agent/Pokedex identity string (`IdString`),
not a transient router index and not a claim of cryptographic worker ownership. The
snapshot records the currently bound cartridge identity and capability facts:

```json
{
  "candidate_id": "sys_example",
  "cartridge_id": "example",
  "capabilities": ["read", "test"],
  "capability_tier": "contributor",
  "domain": "engineering",
  "capability_protocol": "",
  "guardian": "",
  "snapshot_schema": "federation-assignment-candidate-v1"
}
```

The object is closed, sorted, contains no stacktrace, path, secret, prompt, free-form
task text or dynamic health value, and is persisted verbatim in the target ledger.
Empty optional strings are represented exactly as the source metadata provides them;
unknown metadata is not copied.

### 6.2 Qualification and deterministic selection

Before selection the adapter must verify:

1. the admission is `state=ACCEPTED` and its `target_work_id` is non-null;
2. local node identity and V1 provenance are still active;
3. the candidate is active in the local Agent/Pokedex view;
4. the candidate snapshot advertises the capability mapping authorized by the V1 wiring
   entry for `fix_repository`;
5. the V1 authority scope remains `agent-city` and does not include forbidden actions;
6. no worker/tool/mission function is called as part of this check.

If the existing capability vocabulary cannot prove the V1 `fix_repository` mapping, the
result is `assignment_unavailable`; no assignment and no started receipt are created.
The adapter may not infer authority from a title, mission prefix or generic `execute`
capability.

If multiple candidates qualify, sort the closed tuple
`(candidate_id, cartridge_id)` ascending and choose the first. This is deterministic,
read-only selection, not a reservation. If no candidate qualifies, the target record
stays `ACCEPTED`; a local finding may record `assignment_unavailable`, but no network
receipt is emitted by this slice.

### 6.3 Candidate snapshot digest

Let `C` be the SFDJ-1 canonical UTF-8 bytes of the closed snapshot object. Define:

```text
worker_snapshot_digest =
  lowercase_hex(SHA256(
    UTF8("STEWARD-FEDERATION-ASSIGNMENT-CANDIDATE-V1\0") || C
  ))
```

The digest is persisted with the full snapshot and is referenced in the started receipt.
It is not a worker identity and does not prove that the candidate executed anything.

### 6.4 Assignment-authority digest

Let `A` be the closed canonical object:

```json
{
  "assignment_policy": "federation-delegation-assignment-v1",
  "assignment_epoch": 1,
  "authority": {"allowed_actions": [], "denied_actions": [], "repo_scope": "agent-city"},
  "capability": "fix_repository",
  "candidate_id": "sys_example",
  "delegation_id": "<delegation_id>",
  "target_node_id": "<local_target_node_id>",
  "target_work_id": "<target_work_id>",
  "worker_snapshot_digest": "<64 lowercase hex>"
}
```

Arrays are SFDJ-sorted only where the frozen authority schema requires uniqueness;
semantic values are copied from the validated request and selected snapshot, never
from display text. Define:

```text
assignment_authority_digest =
  lowercase_hex(SHA256(
    UTF8("STEWARD-FEDERATION-ASSIGNMENT-AUTHORITY-V1\0") || SFDJ-1(A)
  ))
```

The digest binds policy, candidate, work ID and epoch. It does not authorize an action
outside the already validated V1 authority.

## 7. Atomic assignment algorithm

The exact implementation boundary is one existing target-ledger critical section.

1. Load and validate the target record under the existing thread/process lock. If the
   ledger is corrupt, fail closed with `ledger_corrupt`; do not select a candidate or
   emit a receipt.
2. Require `state=ACCEPTED`. A rejected record cannot enter assignment.
3. If `assignment_state=STARTED`, return the stored immutable carrier; do not select a
   new candidate or generate a new receipt.
4. Read the candidate set through MissionRouter/CityRouter/Spawner metadata only. Mark
   the operation internally `ASSIGNMENT_PENDING`; do not serialize that label.
5. If no candidate or authority-qualified snapshot exists, record only a local finding
   and leave the record unchanged at `ACCEPTED`.
6. Build the immutable candidate snapshot, its digest, `assignment_epoch=1`, authority
   digest and the complete `started` receipt bytes before changing the ledger.
7. Re-enter the target-ledger lock and re-read the record. If another process has
   already committed `STARTED`, compare all assignment and receipt digests and replay
   the stored bytes. If the existing candidate/digest/epoch differs, fail closed with
   `assignment_conflict` and do not overwrite.
8. For an unchanged `ACCEPTED` record, atomically persist the complete assignment
   fields, `assignment_state=STARTED`, complete signed receipt bytes, carrier and
   `started_receipt_send_status=pending` using the existing fsync/replace writer.
9. Only after the commit succeeds may the transport send the stored carrier. A send
   failure changes only `started_receipt_send_status`; it never rebuilds the receipt.
10. No step calls a mission, worker, cartridge, tool, LLM, Git operation or external
    side effect.

### Atomic invariant

After a successful assignment commit, the same durable target-ledger record contains:

- the original `target_work_id` unchanged;
- exactly one `assignment_epoch=1`;
- exactly one immutable `assigned_candidate_snapshot`;
- matching `worker_snapshot_digest` and `assignment_authority_digest`;
- `assigned_at`;
- complete signed started-receipt bytes, message hash, signature, receipt ID and
  content digest;
- the exact receipt carrier and send status.

There is no durable state in which a candidate is assigned but its signed started
evidence is absent.

## 8. Started receipt contract

The frozen `delegation_receipt` operation is reused; no new carrier operation and no
new top-level envelope keys are introduced.

### 8.1 Envelope and payload

The signed receipt envelope has the existing V1 fields and these values:

| Field | Required value |
| --- | --- |
| `operation` | `delegation_receipt` |
| `source_node_id` | local Agent City target node |
| `target_node_id` | original Steward origin node |
| `correlation_id` | original `delegation_id` |
| `request_message_id` | first/original `delegate_task` message ID |
| `causation_message_id` | original request message ID; no new assignment message exists |
| `message_id` | new immutable receipt-envelope ID |
| payload `receipt_id` | new ID for this started receipt, e.g. `receipt_started_<delegation_id>` |
| payload `delegation_id` | original delegation ID |
| payload `receipt_stage` | `started` |
| payload `issuer_role` | `target_scheduler` |
| payload `status` | `started` |
| payload `target_work_id` | exactly the admission `target_work_id` |
| payload `started_at` | `assigned_at`, exact UTC timestamp |
| payload `attempt_count` | integer `1` |
| payload `evidence_refs` | closed URI references defined below |

Draft 0.5 intentionally has a closed `started` payload and does not list arbitrary
`assignment_epoch` or candidate fields. Therefore Plan 02 does **not** silently add
unknown payload keys. The typed `assignment_epoch` and candidate snapshot are carried by
content-addressed `evidence_refs`, which are already permitted for the `started` stage
and are included in `receipt_content_digest`:

```text
urn:steward:federation-v1:assignment-epoch:1
urn:steward:federation-v1:candidate-snapshot-sha256:<worker_snapshot_digest>
urn:steward:federation-v1:assignment-authority-sha256:<assignment_authority_digest>
```

At most these three refs are emitted; each is an ASCII URI within the frozen 256-byte
limit, contains no secret or free prose, and resolves only to evidence already stored in
the target ledger. This is the candidate-snapshot reference and epoch binding without a
wire-contract break. The full snapshot is not embedded in the receipt.

### 8.2 Meaning and non-meaning

The receipt proves that the target ledger durably committed one assignment snapshot and
bound it to one `target_work_id`, epoch and candidate digest. It explicitly does not
prove:

- that a worker was reserved or owns the work;
- that a mission was created;
- that any code, tool, LLM, Git or network side effect occurred;
- that a terminal result or postcondition exists;
- that the candidate is still alive after the commit.

### 8.3 Receipt replay and reissue

- Transport retransmission uses the exact persisted receipt bytes, same `message_id`,
  `receipt_id`, content digest and signature.
- An application reissue, if ever needed by a later approved transport design, may use a
  new envelope `message_id`/time/hash/signature but must retain the same
  `receipt_id`, semantic body and content digest. It cannot create a new assignment or
  epoch.
- Same `receipt_id` with changed candidate digest, authority digest, epoch, target work
  ID or semantic body is `receipt_id_conflict`.
- A duplicate with identical stored values returns the stored carrier and performs no
  second candidate selection.

## 9. Steward origin correlation

The origin adapter applies a started receipt only after validating the closed carrier,
provenance, signature and V1 receipt schema. It then requires:

1. receipt source equals the original `target_node_id`;
2. receipt target equals the origin node;
3. payload `delegation_id` and `correlation_id` equal the origin record;
4. `request_message_id` equals the first request root;
5. `causation_message_id` equals that same request root;
6. receipt stage/status/issuer are `started`/`started`/`target_scheduler`;
7. receipt `target_work_id` equals the admission receipt's already stored
   `target_work_id`;
8. the epoch and candidate/authority evidence references match the target's signed
   receipt content and the persisted assignment evidence.

The origin record receives these additional fields:

```text
started_receipt_message_id
started_receipt_id
started_receipt_content_digest
started_receipt_message_hash
started_receipt_signature
started_receipt_wire_bytes_b64
started_receipt_carrier
started_receipt_send_status (local transport bookkeeping if re-emitted)
started_assignment_epoch
started_candidate_snapshot_digest
started_assignment_authority_digest
```

The first valid started receipt sets these fields once. An identical duplicate is a
no-op/replay match. A different `target_work_id`, epoch, candidate digest, authority
digest, receipt ID or bytes produces a stable local `started_receipt_conflict` and does
not mutate the origin ledger. A started receipt arriving before a correlated admission
receipt is held as local out-of-order evidence/quarantine and is not applied; this slice
does not invent a target work ID.

No origin task is marked completed, verified or otherwise terminal.

## 10. Crash, duplicate and negative matrix

| Scenario | Required target result | Receipt / origin result |
| --- | --- | --- |
| duplicate identical request before assignment | existing `ACCEPTED` record | no assignment or started receipt created |
| first assignment with one candidate | one atomic `STARTED` record, epoch 1 | one stored started carrier; origin binds same work ID |
| identical assignment call after `STARTED` | stored snapshot/epoch/digests match | exact stored bytes retransmitted; no second candidate selection |
| same delegation with another candidate snapshot | `assignment_conflict`; ledger unchanged | no new receipt; local finding |
| crash before candidate selection | record remains `ACCEPTED` | no assignment, no receipt |
| crash after candidate selection, before receipt construction | record remains `ACCEPTED` | no assignment, no receipt |
| crash after receipt construction, before atomic commit | record remains `ACCEPTED` | no receipt transport; a later explicit call may rebuild deterministically, but no bytes were persisted or sent |
| crash after atomic commit, before transport | record is `STARTED` with complete bytes | retransmit exact stored bytes; no new receipt/epoch |
| no available candidate | record remains `ACCEPTED`, local `assignment_unavailable` finding | no false started receipt |
| capability/authority mismatch | no assignment | local finding/quarantine; no network response |
| wrong `target_work_id` at origin | origin conflict, no mutation | no task completion |
| wrong `assignment_epoch` or candidate digest | origin conflict, no mutation | no task completion |
| valid signed receipt from another registered node | origin correlation conflict | no mutation |
| carrier source/target/operation mutation | local quarantine | no ledger change and no response |
| corrupted target/origin ledger | `ledger_corrupt`, fail closed | no assignment, no receipt, no send |
| concurrent identical assignment calls | one atomic winner | all duplicates return the same persisted bytes |
| concurrent different candidate snapshots | one first-set winner; others conflict | no lost update or overwrite |

The matrix deliberately contains no blind retry, lease expiry or recovery engine. Any
future recovery behavior is a separate contract and cannot be inferred from `STARTED`.

## 11. Wiring and migration diff

### 11.1 V1 wiring changes

No new wire operation is introduced. The existing `federation_v1.delegation_receipt`
entry is extended in the manifest/implementation plan with:

- target assignment adapter at the existing `TargetAdmissionLedger` boundary;
- read-only candidate snapshot source (`CityRouter`/Spawner metadata);
- assignment authority gate;
- started receipt emitter using the existing receipt carrier;
- target assignment idempotency/conflict store (the same target ledger);
- Steward started-receipt validator and origin first-set correlation;
- positive, duplicate, crash-before/after-commit and adversarial cross-repo tests.

`delegate_task` remains admission-only at ingress. `delegation_status_query` and
`delegation_status` remain `declared`/`unavailable`; they are not added as a recovery
escape hatch.

Lifecycle maturity and disposition remain separate: the assignment path may be
`code_complete` or `crucible_verified` only after its own tests, but disposition remains
`disabled` and the feature gate remains `false` until an explicit activation review.
The docs wiring manifest remains documentation-only; no runtime module imports it.

### 11.2 Legacy isolation

The implementation must not modify or call:

- legacy Agent City Federation Nadi directive handling;
- `OP_DELEGATE_TASK` or title/substring correlation in Steward;
- `TaskManager.add_task`, `AutonomyEngine`, `SankalpaRegistry.add_mission` or
  `SankalpaHandler` for a V1 accepted request;
- `MissionRouter.route_mission` as an execution trigger;
- `HealExecutor`, cartridges, Git or PR code.

The only permitted use of MissionRouter/CityRouter/Spawner is a read-only candidate
metadata snapshot before the atomic target-ledger commit.

## 12. Test and Crucible plan (still no implementation)

The future implementation branch must add repo-local tests and one admission-to-start
cross-repo crucible without importing a shared runtime library. At minimum:

### Positive

- accepted Slice-01A record produces one deterministic candidate snapshot and epoch 1;
- complete started receipt bytes are persisted before a send call;
- Steward and Agent City independently validate the same started receipt;
- origin binds the started receipt to the exact admission `target_work_id` and request
  root;
- identical duplicate returns byte-identical receipt and snapshot;
- transport retransmission uses stored bytes only.

### Negative/adversarial

- altered candidate snapshot digest;
- altered authority digest;
- altered assignment epoch evidence URI;
- wrong target work ID;
- wrong request root, causation or correlation ID;
- wrong issuer role or receipt stage/status;
- valid signature from another registered target node;
- changed candidate on duplicate;
- no candidate and authority/capability mismatch;
- corrupt ledger and concurrent identical/conflicting calls;
- legacy Nadi/TaskManager/MissionRouter/HealExecutor regression remains green.

All negative cases must identify the first validation boundary and must not use the case
filename as a validator shortcut. Test-only builders and keys remain outside product
code.

## 13. Definition of Done for Implementation Slice 02

Implementation is not complete until all of the following are true:

1. A validated accepted admission can be converted into exactly one target-ledger
   `STARTED` assignment without creating a mission, task, queue item or worker call.
2. The complete candidate snapshot, its digest, authority digest, epoch and complete
   signed started-receipt bytes are persisted in one atomic target-ledger commit.
3. Duplicate and concurrent calls return the same bytes or a stable conflict; no second
   assignment or epoch is possible.
4. Crashes before the commit leave no assignment or receipt; crashes after the commit
   replay the stored bytes exactly.
5. No-candidate and authority/capability failure produce no started receipt.
6. Steward accepts only a started receipt bound to the original target, delegation,
   correlation, request root, causation and admission `target_work_id`.
7. The frozen Draft-0.5 receipt schema is reused without unknown payload fields; epoch
   and candidate references use bounded `evidence_refs` URIs whose digests are persisted
   in the target ledger.
8. Legacy Nadi, `OP_DELEGATE_TASK`, title matching, TaskManager, Sankalpa, HealExecutor
   and all existing regression suites remain unchanged and green.
9. Feature gate is `false`, disposition is `disabled`, no production caller is connected,
   and no terminal/verification/status/recovery behavior is present.
10. A cross-repo Crucible and a self-contained Agent-B implementation review packet
    document exact SHAs, diffs, tests, crash gates and final feature-gate state.

## 14. Agent-B decision gate

Agent B should review this plan before any product commit and answer:

- Is extending `TargetAdmissionLedger` sufficient to preserve atomicity and legacy
  record compatibility, or is a concrete code blocker demonstrated?
- Is the decision to keep `ASSIGNMENT_PENDING` and `ASSIGNED` non-durable necessary to
  preserve the one-commit assignment/start invariant?
- Are the candidate snapshot closed fields, identity, selection ordering and digest
  rules sufficient without claiming worker ownership?
- Are the three `evidence_refs` a contract-safe representation of epoch, candidate and
  authority binding under the frozen started schema?
- Are origin first-set, duplicate, wrong-target and out-of-order rules complete and
  testable?
- Does any step accidentally invoke MissionRouter execution, Sankalpa, TaskManager,
  Worker/Cartridge, HealExecutor, Tool, LLM, Git or a recovery path?
- Are the crash/concurrency gates sufficient to prove no dual write or second dispatch?

**Until this gate is accepted, this document authorizes no product code.**
