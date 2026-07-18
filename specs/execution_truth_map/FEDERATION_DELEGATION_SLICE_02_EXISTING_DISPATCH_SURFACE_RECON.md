# Federation Delegation Slice 02 — Existing Dispatch Surface Recon

**Status:** RECON COMPLETE — NO PRODUCT CODE

**Decision gate:** This document is a read-only inventory and decision proposal. It
does not authorize a handler, a worker invocation, a queue write, a `started` receipt,
feature-gate activation, or a new system-wide execution abstraction.

## 1. Evidence and live pins

The recon was performed against the following live trees on 2026-07-18:

| Repository / source | Pin | Meaning |
| --- | --- | --- |
| Steward remote `main` | `2dd7cd9288fb451b6172ee2bf78328772acb2716` | current remote head; commit subject is heartbeat state sync |
| Steward Slice 01A implementation merge | `9f6519d8d8713b81c6197217d61e3b1fcc144ea7` | authoritative product merge commit |
| Steward docs merge | `4c88c689cd4072f077a7145589f2ed7ca484e9d9` | docs-only descendant before later heartbeat state sync |
| Agent City remote `main` | `a854f590391f73da10b33f402c321fd68f3fd0b5` | current remote head after docs PR #2209 |
| Agent City Slice 01A implementation merge | `d16b7ffb1db0cd1f794bd6066b7978e6db86794b` | authoritative product merge commit |
| Steward Protocol working `main` | `c51196d9e906c2e993d3548db6ef891b184b0b24` | live provider of Task/Mission models used by both repositories |

Semantic history was reviewed with heartbeat commits excluded (`git log --grep
heartbeat --invert-grep`). Heartbeat state commits are retained as live-tree pins when
they are the current remote head, but are not treated as evidence of architectural
progress or implementation behavior.

The accepted Slice 01A smoke evidence remains:

- Steward V1/admission and fixtures: 65 passed.
- Agent City V1/admission, hardening and fixtures: 64 passed.
- Steward legacy gateway/quarantine: 61 passed.
- Agent City NADI/relay regression: 91 passed.
- Admission-only cross-repository crucible: 1 passed.
- Steward PR #829 CI: Python 3.11, Python 3.12, lint and security passed.

These tests prove the admission wire and ledger contract. They do not prove a work
assignment, worker ownership, execution start, or recovery contract.

## 2. Scope and non-goals

This recon answers which existing Agent City and Steward surfaces could be adapted for
the smallest Slice 02:

`accepted admission -> one durable local assignment -> no executor side effect -> one signed started receipt -> origin ID correlation`.

It covers MissionRouter, mission/task/work models, worker discovery and selection,
Sankalpa/Kirtan/TaskManager, persistence, queue/dispatch behavior, admission-to-work
boundaries, duplicate/crash behavior, existing status signals and authority gates.

Explicitly out of scope:

- worker or tool execution;
- Git, LLM, repair, PR or other external side effects;
- terminal or verification receipts;
- status query, lease/recovery automation or managed-task completion;
- Provider Failover, Context Bridge, Execution-Spine system specification;
- automatic merge authority or productive V1 activation.

## 3. Current V1 truth

### 3.1 Product boundary

Steward `steward/federation_v1.py:956-1041` defines `FederationV1Origin`; Agent City
`city/federation_v1.py:1062-1178` defines `FederationV1Admission`. The current factory
and service registries do not construct either V1 class in a runtime caller: the live
references are test imports (`tests/test_federation_v1_admission.py`,
`tests/test_federation_v1_cross_repo_crucible.py` in Steward and the corresponding
Agent City tests). The V1 feature gate defaults to `False`
(`steward/federation_v1.py:32-33`, `city/federation_v1.py:28-29` and constructor
defaults). This is an implemented, tested but disabled adapter boundary, not a live
dispatch path.

### 3.2 What an accepted admission currently creates

`FederationV1Admission.handle` validates the carrier, SFDJ-1 envelope, provenance,
authority and capability (`city/federation_v1.py:1098-1133`). For an accepted request it
derives a deterministic synthetic value:

`work_<sha256(delegation_id + target_node_id)[:32]>`

(`city/federation_v1.py:1135-1141`). It then builds the signed admission receipt and
atomically stores the target record, request bytes, receipt bytes, hashes, IDs,
`target_work_id` and send status in `TargetAdmissionLedger`
(`city/federation_v1.py:776-843`). No mission, task, queue item, worker assignment or
started signal is created.

The Steward origin ledger stores the immutable request and later applies a signed
admission receipt with direct `delegation_id`, `correlation_id`, request-message and
causation checks (`steward/federation_v1.py:868-960`). The origin-side
`target_work_id` is therefore an admission correlation field, not yet a local work
record identifier.

### 3.3 Legacy paths remain separate

Steward's active legacy `FederationBridge` registers `OP_DELEGATE_TASK` and callback
operations (`steward/federation.py:298-315`). Its delegate handler obtains the
TaskManager, applies a peer trust floor, prefixes the title with `[FED:<source>]`, and
calls `task_mgr.add_task` (`steward/federation.py:729-778`). The callback handler finds
blocked tasks by `delegated:<task_title>` in the description
(`steward/federation.py:1343-1380`). This is title/description-based legacy behavior;
it neither consumes V1 carriers nor owns `delegation_id`/`target_work_id`.

## 4. Component inventory and reuse/gap matrix

| Surface | Live symbols / evidence | Current disposition | Reusable property | V1 gap or safety boundary |
| --- | --- | --- | --- | --- |
| V1 admission ledger | Agent City `TargetAdmissionLedger` `city/federation_v1.py:776-843` | Implemented, disabled caller | Atomic durable admission/dedupe and receipt bytes | `target_work_id` is synthetic; no assignment/dispatch state |
| V1 origin ledger | Steward `OriginDelegationLedger` `steward/federation_v1.py:846-960` | Implemented, disabled caller | Immutable request, receipt and ID correlation | No started stage or local work ownership |
| `SankalpaMission` | Protocol `types.py:213-229` | Productively used when governance is enabled | Durable purpose/status object with owner and timestamps | No delegation ID, target work ID, lease, worker or start evidence |
| `SankalpaRegistry` | Protocol `will.py:83-133,212-234` | Productively used | `.vibe/state/sankalpa.json`, mission lookup and status persistence | Atomic temp replace but no explicit inter-process lock; load failure falls back to defaults; no assignment transaction |
| Mission creators | Agent City `city/missions.py:17-55,288-312,463-486` | Productively used by legacy/governance paths | Existing mission creation and owner/status fields | IDs are heartbeat/directive-derived (`heal_`, `exec_`, `fed_`); not stable V1 work identity |
| MissionRouter module | `city/mission_router.py:5-10,140-285,295-336` | Productively used | Pure capability gate and scoring; supports `fed_` prefix | It is not a class or queue; no persistence, ownership, reservation or target binding |
| CityRouter | `city/router.py:37-121,153-178` | Productively used | O(1) in-memory capability/domain/tier lookup | Rebuildable in-memory index; no durable assignment or ownership epoch |
| AgentSpawner/Pokedex | `city/spawner.py:28-94,238-270` | Productively used | Agent lifecycle, cartridge binding and router registration | Agent registry is not a worker queue/lease registry; no per-work reservation |
| Sankalpa KARMA handler | `city/karma_handlers/sankalpa.py:22-99,196-269` | Productively used, governance-dependent | Existing route-to-cartridge seam | `exec_` missions call cartridge processing and `HealExecutor`; forbidden for Slice 02 |
| Legacy Federation Nadi | `city/hooks/genesis/federation.py:28-119` | Productively used | Existing directive ingress and mission adapters | Handles `create_mission`/`execute_code`, not V1 signed admission; must remain isolated |
| Steward Task model | Protocol `task_management/models.py:40-81` | Productively used by Steward | UUID task ID, status, assignee, metadata | No target-work/delegation contract; local Steward task, not Agent City target ownership |
| Steward TaskManager | Protocol `task_manager.py:38-104,225-304` | Productively used | `.vibe/state/tasks.json`, `FileLock`, atomic save, durable UUIDs | No V1 admission binding, lease or started receipt; adding a legacy task would violate Slice 02 isolation |
| Steward selection | Protocol `next_task_generator.py:61-102`; Steward `autonomy.py:194-317` | Productively used | Deterministic priority selection and status transitions | In-progress tasks are resumed; no owner/lease/fencing and side effects can follow a partial crash |
| Kirtan | Steward `steward/kirtan.py` (call/verify ledger) | Productively used as a verification primitive | Persistent call/outcome evidence | Not an Agent City assignment queue and not V1-ID bound; verification is out of Slice 02 |
| V1 factory/service wiring | Agent City `city/factory.py:175-207,258-315,560-585` | V1 absent/unwired | Existing service-definition mechanism | No `SVC_FEDERATION_V1`; `_build_federation` creates legacy `FederationRelay` |
| Started receipt | `city/federation_v1.py` has admission-only receipt construction/validation; no V1 `started` builder/handler | Missing | None in current V1 surface | Must be defined and tested in Plan 02 before product code |

### Worker selection finding

There is no `WorkerRegistry` class in the live Agent City tree. The effective registry
is the combination of `Pokedex`/`AgentSpawner` lifecycle, cartridge metadata and the
in-memory `CityRouter`. `mission_router.route_mission` scores active agents after the
capability gate. This can provide a candidate snapshot, but it cannot by itself
persist an assignment or prove ownership.

## 5. Existing persistence and failure behavior

### 5.1 V1 admission

The V1 target ledger uses a thread lock plus a repo-local process lock and atomic file
replacement for the full admission read/modify/write. Identical request replay returns
the stored receipt; a digest conflict or message-wire conflict is rejected. This is the
only currently proven exactly-once boundary. It does not extend to a mission or worker.

### 5.2 Sankalpa missions

`SankalpaRegistry._save` writes a temporary JSON file and replaces the state file
(`will.py:124-133`). It has no explicit process-wide lock. `add_mission` overwrites by
mission ID and saves (`will.py:212-215`). Mission factories deduplicate by heartbeat-
derived prefixes or names (`city/missions.py:31-54`), not by a V1 delegation identity.
On a load exception the registry logs and initializes defaults (`will.py:100-122`),
which is not a fail-closed recovery policy for a V1 assignment ledger.

The Moksha lifecycle collects completed/failed missions and purges duplicate or stale
active missions; mayor/dharma missions can be abandoned after a ten-heartbeat TTL
(`city/hooks/moksha/mission_lifecycle.py:64-103,236-304`). This is housekeeping, not a
lease, fencing token, or crash-safe dispatch protocol.

### 5.3 Steward tasks

`TaskManager` persists UUID tasks under `.vibe/state/tasks.json` with a `FileLock` and
atomic save (`task_manager.py:49-73,294-304`). `Task` has status, assignee and metadata
but no V1 fields (`models.py:40-81`). `NextTaskGenerator` deliberately selects
`IN_PROGRESS` tasks before `PENDING` tasks (`next_task_generator.py:61-102`), and
`AutonomyEngine._dispatch_next_task` marks a task `IN_PROGRESS` before dispatch and
marks failures afterward (`steward/autonomy.py:194-221,274-317`). A process crash after
that status write can leave an in-progress task to be resumed without a V1 ownership
epoch or proof of whether an external side effect already occurred. This is why the
legacy TaskManager must not be silently used as Slice 02's exactly-once assignment.

### 5.4 In-memory routing and agent lifecycle

`CityRouter.register/remove` maintains live indices in memory
(`city/router.py:69-129`). `AgentSpawner` registers agents and cartridges at lifecycle
events (`city/spawner.py:47-94,255-270`). A restart rebuilds these indices from agent
lifecycle state; no assignment record survives independently. A duplicate route can
therefore occur unless a durable V1 assignment decision is committed before any worker
or mission execution.

## 6. Actual current sequences

### 6.1 V1 admission-only sequence today

```text
Steward test/explicit caller (gate=false by default)
  -> FederationV1Origin.create()
  -> immutable signed request + closed request carrier
  -> Agent City FederationV1Admission.handle() [only when explicitly constructed]
  -> carrier/envelope/provenance/authority validation
  -> TargetAdmissionLedger.commit()
       state=ACCEPTED or REJECTED
       synthetic target_work_id only for ACCEPTED
       complete signed admission receipt bytes
  -> closed receipt carrier
  -> Steward FederationV1Origin.apply_receipt()
       direct delegation/correlation/request/causation checks
       origin target_work_id first-set or duplicate-match

No Sankalpa mission, TaskManager task, queue entry, worker selection, lease,
started receipt, tool call, terminal result or verification is present.
```

### 6.2 Existing legacy Agent City path (not V1)

```text
Legacy Federation Nadi directive or local governance signal
  -> city/hooks/genesis/federation.py
  -> city.missions.create_*_mission()
  -> SankalpaRegistry.add_mission()
  -> KARMA SankalpaHandler
  -> authorize_mission()/MissionRouter + CityRouter candidate selection
  -> cartridge.process() / HealExecutor / PR path
  -> mission status COMPLETED or remains ACTIVE
  -> Moksha collection/purge and outbound city_report
```

This path has real side effects and no V1 `delegation_id` or `target_work_id` binding.
It is not a safe adapter by mere renaming.

### 6.3 Existing legacy Steward path (not V1)

```text
Legacy OP_DELEGATE_TASK or city_report bottleneck
  -> Steward FederationBridge
  -> title/description dedup and TaskManager.add_task()
  -> AutonomyEngine selects UUID Task
  -> title intent / [FED:source] parsing
  -> isolated federated execution and callback
```

The callback correlation is based on `task_title` embedded in a description
(`steward/federation.py:1343-1380`), exactly the class of title matching excluded from
the V1 contract.

## 7. Answers to the eight recon questions

1. **Which components exist?**
   Durable V1 target/origin admission ledgers, Sankalpa missions/registry, pure
   MissionRouter, in-memory CityRouter, AgentSpawner/Pokedex/cartridges, legacy Nadi
   and Steward TaskManager/AutonomyEngine all exist. No V1 service registration, V1
   work assignment record, WorkerRegistry, started receipt builder or started handler
   exists.

2. **Which are active, inactive or unwired?**
   Legacy Federation Nadi, Sankalpa/KARMA, CityRouter/Spawner and Steward TaskManager/
   Autonomy are active in their configured paths. V1 adapter classes and ledgers are
   tested and merged but default-disabled and only explicitly constructed by tests at
   present. The V1-to-mission/worker boundary is unwired. The docs wiring manifest is
   not runtime wiring (see §9).

3. **Which model should own `target_work_id`?**
   No existing model is presently suitable. Sankalpa mission IDs are heartbeat/directive
   identities; Task IDs are Steward-local UUIDs; CityRouter has no durable records. The
   V1 target ledger currently owns the synthetic admission value. Slice 02 must choose
   an explicit Agent City target-owned assignment record (or an explicitly extended V1
   target ledger) that stores `delegation_id`, `target_work_id`, assignment state and
   ownership. It must not overload a mission ID.

4. **Can ACCEPTED be atomically bound to an existing Work structure?**
   Not with the current structures. `TargetAdmissionLedger.commit` atomically commits
   admission and receipt, but no mission/task/work row. Sankalpa has no process lock or
   V1 fields; MissionRouter and CityRouter are not persistence layers. A new narrow
   atomic boundary or an explicit extension of the V1 target ledger is required before
   a started receipt can be truthful.

5. **Where can a second dispatch arise after duplicate or crash?**
   A duplicate admission currently returns the stored receipt, so Slice 01A itself does
   not create a second admission. A second dispatch would arise if a future handler
   creates a mission on every accepted receipt, uses heartbeat-derived mission IDs, or
   writes an assignment after a crash without a durable first-set marker. Sankalpa's
   unlocked temp-replace save, CityRouter's in-memory state and TaskManager's resume of
   `IN_PROGRESS` tasks are the concrete risk surfaces.

6. **What can trigger a `started` receipt?**
   Nothing in the current V1 product path. Mission status, heartbeat operations,
   cartridge processing and A2A/legacy reports are not bound to the V1 delegation and
   cannot be promoted to `started` evidence without a new explicit adapter boundary.

7. **What must be built versus adapted?**
   Adaptable: the existing V1 admission ledger and receipt/carrier primitives; the
   provenance validator; the capability gate as a pre-assignment policy input; and
   repo-local service/test wiring. Not safely adaptable without explicit new fields and
   atomicity: generic Sankalpa mission IDs, MissionRouter, CityRouter, legacy Nadi,
   legacy `OP_DELEGATE_TASK`, HealExecutor and the Steward TaskManager. Worker/tool
   execution must not be called by Slice 02.

8. **Is Slice 02 the right next step?**
   Yes, but only as a narrow plan-first slice. The recon finds a tighter prerequisite:
   decide the owner and atomic persistence boundary for a V1 assignment before adding
   any mission or worker adapter. No existing path can be wired directly without
   violating ID, duplicate and crash guarantees.

## 8. Maximum-five open architecture questions

1. **Assignment owner:** Should the target-owned assignment record be a strictly
   extended `TargetAdmissionLedger` record or a separate adjacent V1 work-assignment
   store, and which one is authoritative for `target_work_id`?
2. **Atomic boundary:** Which exact commit makes admission-to-assignment durable, and
   how is the signed `started` receipt generated from that commit without a second
   assignment transaction?
3. **State and crash contract:** What minimal states and ownership/fencing fields are
   needed for `ASSIGNMENT_PENDING`, `ASSIGNED` and `STARTED`, and what is the explicit
   behavior after a crash before/after each write?
4. **Worker snapshot:** What stable worker identity and authority snapshot may be
   recorded without invoking a worker or treating a transient CityRouter candidate as
   an ownership proof?
5. **Adapter boundary:** Is an accepted V1 assignment allowed to create a dormant
   Sankalpa mission record, or must mission creation wait for a later slice? The choice
   must not activate `exec_`, `HealExecutor`, legacy Nadi or TaskManager paths.

These are questions for the Slice 02 implementation plan, not implicit defaults.

## 9. Wiring-manifest truth boundary

`docs/FEDERATION_DELEGATION_WIRING_MANIFEST_01.json` is versioned capability/audit
documentation only. A repository-wide search on the pinned Steward and Agent City
trees found no runtime import or use of the file, its path, or its capability status
keys outside the document itself. No runtime code was changed.

The manually maintained values (`crucible_verified`, `disabled`, test counts and merge
pins) are historical, evidence-bound milestone assertions. They are not a live health
database. Dynamic Provider health, node health, heartbeat health, ledger health and
current capability availability must come from measured probes, persistent runtime
state or reproducible runtime evidence. They must not be written into this manifest as
manual current truth. If a future runtime import is discovered, that is an architecture
break requiring an explicit stop and review; this recon found none.

## 10. Recommendation for the smallest Slice-02 plan

Prepare one narrow, reviewable plan with this boundary:

```text
validated ACCEPTED admission
  -> target-owned durable assignment record (first-set, one target_work_id)
  -> no mission execution, no cartridge, no tool, no Git, no external side effect
  -> deterministic signed started receipt from durable assignment evidence
  -> Steward validates IDs and binds started evidence to the same target_work_id
```

The plan should first decide whether the assignment record extends the existing
`TargetAdmissionLedger` or sits beside it. It must specify atomic write ordering,
duplicate replay, crash-before/after-assignment behavior, stable worker/candidate
metadata, authority checks and a disabled service boundary. Existing MissionRouter and
CityRouter may be consulted as a capability/availability snapshot only; they must not be
treated as durable ownership. Existing mission/task execution paths remain untouched.

**Recommendation:** Slice 02 is justified, but product implementation must wait for an
Agent-B-reviewed Plan 02 that resolves the five questions above. The smallest truthful
implementation is an admission-to-assignment-and-start-evidence adapter, not a mission
runner and not a general Execution Spine.

## 11. Handoff / acceptance gate

Before implementation, require:

- current Steward and Agent City main pins re-read;
- explicit choice of target-owned assignment persistence and atomic boundary;
- closed duplicate/crash/start receipt tests derived from that choice;
- proof that legacy NADI, `OP_DELEGATE_TASK`, title matching, TaskManager execution,
  HealExecutor and the feature gate remain unchanged;
- a self-contained Plan 02 review packet.

No product code, runtime handler, worker dispatch, status query, recovery automation,
terminal/verification receipt, Context Bridge work or activation is authorized by this
recon.
