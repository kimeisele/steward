# FEATURE 01 — SLICE D2b READ-ONLY PREFLIGHT

> **Status:** DRAFT 0.1 — EVIDENCE/SPEC ONLY; G1 OFF; IMPLEMENTATION AND ACTIVATION
> LOCKED
> **Investigated main:** `kimeisele/steward@3ad7b951039e1a3687206a03db64464c06474f6b`
> **D2a merge:** `ac9caba61c426086ba4c09a1ac02065cbd850f5a`
> **Date:** 2026-07-17

This document is the next isolated read-only work package after the merged D2a
generation observer. It does not authorize a writer, lock, journal, recovery routine,
workflow change, delivery change, bootstrap, or activation. The existing D2b guardrails
in `FEATURE_01_SLICE_D2_G2_PREFLIGHT.md` §6 remain binding; this document records the
current production reality and the evidence still required before any D2b code review.

## 1. Gate and scope

### 1.1 Current gate

- D2a is merged and pushed to `main`; its public API is observation only.
- D2b is **not** an automatic consequence of the D2a merge.
- No product code, workflow, repository setting, runtime state, or root contract is
  changed by this preflight.
- `docs/PHASE2_BEFUND.md`, `docs/PHASE2_CURRENT.md`, and the Phase-1 report remain
  external continuity material. They are not silently rewritten here and are not an
  automated operator-authority source.

### 1.2 Permitted scope for this work package

Only this file may be added or changed by the preflight branch. A later evidence update
must remain under `specs/context_bridge_evidence/` and must be separately reviewable.

### 1.3 Explicit non-goals

This preflight does not:

- implement `flock`, a thread lock, tempfiles, `fsync`, `replace`, a journal, or recovery;
- call `assemble_context()` for a canonical publish;
- create `AGENTS.md`, the two JSON generation artifacts, or any `.context-publish-v1.*`
  file;
- alter `write_file`, `edit_file`, the heartbeat workflow, GitHub settings, or staging;
- select a policy mode or introduce an environment/repository activation flag;
- infer a current human operator order from Issues, Tasks, `PHASE2_CURRENT`, or runtime
  state;
- use the existing `context.json` writer as a substitute for the four-artifact
  transaction.

## 2. Pinned current-state evidence

### 2.1 Remote and tree

The inspected clone was fast-forwarded to `origin/main` and is clean. Local `main` and
`origin/main` both resolve to:

```text
3ad7b951039e1a3687206a03db64464c06474f6b
```

The only files changed after the D2a merge are heartbeat/federation runtime state:

```text
.steward/.context_hash
.steward/context.json
.steward/federation_health.json
.steward/marketplace.json
.steward/sessions.json
data/federation/peers.json
data/federation/quarantine/index.json
data/federation/relay_seen_ids.json
data/federation/steward_health.json
```

No open PR exists at the time of this pin. The latest post-merge heartbeat completed
successfully, but that is evidence about the heartbeat run, not a D2b publication proof.

### 2.2 Four D2a/D2b target paths

At the pin:

| Path | HEAD/index | Worktree | Meaning |
|---|---|---|---|
| `CLAUDE.md` | regular `100644`, blob `8146a15603c95e5aa1404c9eb7021e3008914b0c` | present, unchanged legacy file | legacy bootstrap only |
| `AGENTS.md` | absent | absent | no Codex root contract yet |
| `.steward/context-snapshot.json` | absent | absent | no V1 snapshot generation |
| `.steward/context-publication.json` | absent | absent | no V1 publication record |

The current `.steward/context.json` is a different legacy state artifact and is not a
D2b candidate. The current `.steward/conventions.md` is tracked with blob
`f428d5856a5c525e002c301890777748effbeb4e`; it is the only existing Constitution
candidate, but it is not an attestable four-artifact publication baseline.

Two already tracked `.steward/.atomic_*.tmp` artifacts remain in the tree (blobs
`e69de29bb2d1d6434b8b29ae775ad8c2e48c5391` and
`e8176f82e7009127087fc7ab88cf491a8ae09005`). They are a separate hygiene finding. D2b
must neither delete nor reinterpret them as transaction evidence.

**Baseline decision:** the live state is `legacy_bootstrap`, not a valid V1 generation.
No D2b run may automatically overwrite this state. Bootstrap requires the separately
gated Slice E contract described by the D2a G2 document §6.6.

## 3. Positive product evidence

### 3.1 D2a has no write authority

The merged read-only implementation is confined to:

- `steward/context_contract.py`;
- `steward/context_rendering.py`;
- `steward/context_publisher.py`;
- their direct contract/rendering/publisher tests.

`context_publisher.py` opens and observes Git and worktree state. Its public entry point
returns a `RepositoryGenerationObservation`; it has no writer, caller, lock acquisition,
journal creation, candidate assembly, or activation path. Its purity tests reject write
syscalls, mutating Git, wall-clock use, network, and ServiceRegistry access during the
observation boundary.

### 3.2 Legacy and preview paths

- `steward/briefing.py:50-53` makes `write_claude_md()` fail closed with
  `LegacyBriefingWriteDisabled`. `generate_briefing()` is an in-memory preview.
- `steward/context_bridge.py:186-217` writes only the legacy
  `.steward/context.json` and `.steward/.context_hash`.
- `steward/context_bridge.py:525-541` uses the old local tempfile/rename helper. Its
  semantics are not the D2b four-target durability contract and must not be reused by
  assumption.
- `steward/hooks/moksha_bridge.py:44-70` invokes that legacy context writer per MOKSHA
  cycle and catches failures as non-fatal. It does not publish a root contract.
- `steward/tools/synthesize_briefing.py:72-165` is an LLM preview path. It accepts only
  `None` or `stdout` as `output_path`, returns `metadata.mode == "preview"` and
  `metadata.canonical == False`, and has no filesystem writer.

These facts prove that the D2a merge did not silently activate the Context Bridge. They
do not prove that every generic file tool is safe to run concurrently with a future
publisher.

## 4. Independent writer and delivery inventory

This is the central D2b preflight finding: a publisher lock protects only cooperating
writers. The repository currently exposes other write-capable paths that do not acquire
the proposed D2b lock.

| Path | Positive evidence on pinned main | D2b consequence |
|---|---|---|
| Generic `write_file` | `steward/tools/write_file.py:52-73` accepts an expanded arbitrary path and calls `Path.write_text()` | can write any root or `.steward` target without D2b lock |
| Generic `edit_file` | `steward/tools/edit.py:61-119` performs unrestricted `Path.write_text()` after an existence/read check | same race and governance surface; read-before-write is not a transaction fence |
| Tool registration | `steward/tool_providers.py:58-75` registers both tools in the normal Steward registry | available to autonomous Steward and child-agent registries |
| Legacy context bridge | `context_bridge.py:186-217,525-541` writes `context.json` and `.context_hash` | separate state writer; must not be mistaken for D2b publication |
| Git Nadi sync | `steward/git_nadi_sync.py:94-170` stages, commits, rebases, and pushes an allowlisted federation subtree | does not target the four files, but shares the repository/index and has no D2b lock |
| Heartbeat post-step | `.github/workflows/steward-heartbeat.yml:93-106` runs under `if: always()`, stages `.steward/` and `data/federation/`, then pushes directly | tracked `.steward/conventions.md` is in the staging surface; delivery is not PR-only |

`GitNadiSync` currently positively allowlists only `nadi_inbox.json`, `nadi_outbox.json`,
`peer.json`, and `reports/**`; it is therefore not evidence of a Context target writer.
It is nevertheless a concurrent Git/index actor and must be included in the D2b race
model.

**Required decision before D2b code:** either every writer capable of touching a D2b
target must enter the same repository transaction boundary, or those paths must be
explicitly prevented from touching the four targets. “One publisher” is not sufficient
while generic file tools remain unrestricted.

## 5. Concurrency and delivery reality

### 5.1 Workflow concurrency is not repository-wide locking

The heartbeat workflow uses group `steward-heartbeat` with
`cancel-in-progress: false` (`.github/workflows/steward-heartbeat.yml:17-20`). This
serializes matching GitHub Actions runs only. It does not serialize:

- local CLI/API/Telegram Steward processes;
- the daemon/Cetana thread against a manually dispatched phase loop;
- generic `write_file`/`edit_file` calls;
- Git Nadi sync or another process using the same checkout;
- a process that modifies a target outside the heartbeat workflow.

The workflow has `contents: write` and `pull-requests: write` permissions and its final
step pushes directly to `main`. Branch protection currently requires CI checks but no PR
review, and administrator enforcement is disabled. No active repository ruleset was
observed. This is a governance/delivery blocker, not a reason to add settings in this
preflight.

### 5.2 Two local replaces are not one filesystem transaction

The D2b contract must promise only per-file atomic replacement plus generation identity,
mixed-state detection, fail-closed success, and deterministic recovery. It must not claim
that an external reader can never observe the interval between two replaces. A shared
Git commit can be a remote delivery boundary, but it is not a substitute for local
read-back and recovery evidence.

### 5.3 Current stop surface

No D2b kill switch or publisher drain exists. The existing heartbeat can be disabled or
cancelled through GitHub, but `if: always()` and direct credentials mean that a complete
containment sequence must be proven separately. D2b may not invent or enable a workflow
flag as a side effect.

## 6. Binding D2b guardrails

The following are already decided in `FEATURE_01_SLICE_D2_G2_PREFLIGHT.md` §6 and are
repeated here as constraints, not implementation authorization:

1. Persistent `.steward/.context-publish-v1.lock`, safe open, owner/mode checks, one
   repository-root thread lock followed by exclusive POSIX `flock`, bounded monotone
   deadline, and a scope covering assembly through final read-back/reference/decision.
2. One strict, exclusive, durable transaction journal containing the baseline and one
   immutable candidate generation; no raw bytes, secrets, exception text, or foreign
   absolute paths.
3. Four same-transaction-ID tempfiles, same-parent `O_EXCL` creation, complete
   short-write handling, file/parent durability, temp read-back, and a fixed replace
   order ending with `context-publication.json`.
4. Post-replace per-file read-back, D1 plus Constitution attestation, HEAD/index and
   parent/target re-fences, and durable journal cleanup before success.
5. Recovery only for one strict valid journal and bytes matching its baseline or
   candidate; unknown/multiple journals, foreign bytes, unsafe paths, or unbound legacy
   bootstrap remain `manual_review` without mutation.
6. `disabled | preview | canonical` publisher policy is distinct from content
   `OutputMode`; missing/unknown/invalid policy is `disabled`, and disabled/preview write
   no target or transaction file.

No future code PR may weaken these constraints by relying on timestamps, a record alone,
object identity, an advisory workflow lock, or a second assembly/render pass.

## 7. Evidence still required before D2b implementation

The following are open preflight gates. Each must be answered against a pinned commit or
an explicitly isolated drill and must state positive evidence, non-evidence, and the
fail-closed result.

### 7.1 Writer boundary

- Decide whether `write_file` and `edit_file` are forbidden for the four target paths,
  made lock-aware, or isolated from the canonical publisher by a separately reviewed
  boundary.
- Prove that the decision covers child agents, API/Telegram paths, and any dynamically
  discovered tools, not only the default registry.
- Prove that the LLM preview path cannot become a canonical writer through a new caller.

### 7.2 Baseline and bootstrap

- Reconfirm that no attestable four-artifact HEAD baseline exists on the then-current
  main.
- Define the separate human-reviewed Slice E bootstrap contract; no fresh assembly may
  stand in for it.
- Define the safe fallback shown to external engineering agents when the state is
  `legacy_bootstrap`, `mixed`, `manual_review`, or `invalid`.

### 7.3 Lock, journal, and crash recovery

The D2b code review must have direct tests for, at minimum:

- same-process thread contention and cross-process `flock` contention;
- timeout, interrupted acquire, release ordering, stale lock inode, hardlink, symlink,
  owner, mode, and unsafe-parent cases;
- crashes after journal creation, after each of four temp prepares, after each replace,
  after each parent `fsync`, after final read-back, and before journal removal;
- file/parent `fsync` errors, short writes, `EINTR`, disk-full simulation, temp cleanup,
  multiple journals, unknown temp names, foreign bytes, and journal schema errors;
- recovery idempotence and the rule that an unbound legacy baseline never auto-recovers.

### 7.4 Cross-process and Git races

- A generic writer must be injected during every D2b fence and replace boundary.
- Git Nadi and heartbeat staging must be tested against a held D2b transaction; a
  successful local replace is not enough if the index or remote push can interleave.
- External readers must observe and classify a mixed generation rather than receive a
  false positive.
- The final Git delivery contract must state whether publication is PR-only, direct push,
  or another explicitly governed mechanism. It cannot be inferred from the current
  heartbeat behavior.

### 7.5 Constitution and trust boundary

- `.steward/conventions.md` remains the only C0 source, but its current content is not
  yet a safe canonical constitution. Its hardening is a separate human-reviewed spec.
- The C0 block must remain byte-bound to its reviewed source and cannot be changed by the
  heartbeat, LLM, dynamic data, or a generic file tool.
- Dynamic Issues, Tasks, Senses, Sessions, Federation, and `PHASE2_CURRENT` content are
  data/continuity signals, never constitutional instructions.
- The actual current human operator order remains external runtime authority; the bridge
  must state when it is absent rather than reconstructing it.

### 7.6 Platform and durability proof

- Repeat the unmocked Ubuntu FD/Executable drill on the final D2b implementation head.
- Keep Darwin behavior fail-closed when the validated helper contract is unavailable.
- Document exactly which durability guarantees are proven on the runner filesystem and
  which remain non-portable assumptions.

## 8. Implementation order after all gates

No implementation starts from this document alone. The only permitted sequence is:

1. close §7 with small read-only evidence packages;
2. produce and adversarially review a D2b feature spec containing the final writer,
   lock, journal, recovery, baseline, and delivery contracts;
3. obtain the explicit human operator go for that reviewed spec;
4. implement the smallest local transaction primitive in a separate code PR, with no
   workflow, settings, caller, bootstrap, delivery, or activation change;
5. adversarially review and merge that code PR;
6. prove production non-activation and only then consider a separately gated delivery or
   bootstrap slice.

## 9. Decision

The D2b idea is technically plausible, but **G1 remains OFF**. The current main still
contains an unbound generic write surface, a legacy-only baseline, a direct-push
heartbeat, and no repository-wide publisher lock. These are not reasons for a rewrite;
they are the exact boundaries the next evidence packets must close.

Until then the safe state is intentional:

- D2a observes and fails closed;
- legacy `CLAUDE.md` remains untouched;
- `AGENTS.md` and both V1 JSON targets remain absent;
- no journal, lock, temp, publisher, recovery, workflow activation, or bootstrap is
  created by the Context Bridge.
