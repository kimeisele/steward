# FEATURE 01 — SLICE D2b WRITER-BOUNDARY POLICY PREFLIGHT

> **Status:** DRAFT 0.1 — READ-ONLY POLICY PROPOSAL; G1 OFF; IMPLEMENTATION LOCKED
>
> **Investigated main:** `kimeisele/steward@36b22ebbd2f31d8f660f434138572bea563dc418`
>
> **Investigated tree:** `8a7779381d141552b2f03642e2e3e79fd845d577`
>
> **D2b preflight parent:** `f582e0d63876df8be61e8970a0fe065a2b2c034e`
>
> **Writer-evidence merge:** `573908721fce10ad1783af4abaa360b34987d6a6`
>
> **Earlier policy scan pin:** `dd3824563fd074995fb71bd26255628f7eb2ef78`
>
> **Date:** 2026-07-17

This is a read-only policy proposal after the D2b writer-boundary evidence package. It
chooses a boundary for later adversarial specification; it does not claim that the
boundary is implemented or proven in production. No writer, lock, journal, recovery,
workflow, delivery, bootstrap, root file, setting, or activation is changed here.

## 1. Decision gate

The merged writer evidence established that a publisher lock would protect only
cooperating code. Built-in file tools, shell, Git, child registries, dynamically loaded
tools, actuators, healers, rollback paths, CLI export, and A2A task persistence remain
independently reachable. The inventory is materially expanded but explicitly not closed.

The policy decision proposed here is therefore a **hybrid default-deny and isolated-
publisher boundary**:

1. Canonical publication may run only in a dedicated publisher process and an isolated
   worktree/checkout that no normal Steward, child agent, workflow helper, or generic
   tool shares.
2. The publisher's repository transaction lock protects only that publisher worktree and
   its own transaction namespace. It is not represented as a universal lock for foreign
   processes.
3. Every known or unknown non-publisher path is forbidden from mutating the four
   canonical targets or the D2b transaction namespace. In-process callers must fail
   closed; an arbitrary shell or external process is treated as untrusted and cannot
   produce a trusted publication result.
4. The publisher must still perform the full Git, parent, target, journal, tempfile, and
   read-back fences required by the D2b preflight. Isolation reduces the race domain; it
   does not replace those proofs.
5. Remote delivery is a separate PR-only operation. A local publisher success never
   authorizes a direct push to `main` or a heartbeat state commit.

This is a policy contract, not an implementation shortcut. The implementation must
demonstrate the boundary with real process/worktree and adversarial tests before G1/G2
can advance.

## 2. Scope and non-goals

### 2.1 This preflight covers

- the trust boundary between the canonical publisher and all other writers;
- the exact protected target and transaction namespaces;
- default-deny behavior for known and not-yet-inventoried writers;
- the isolated publisher worktree/process contract;
- the required adversarial evidence for the later D2b code slices;
- the relationship between local publication, Git evidence, and remote delivery.

### 2.2 This preflight does not authorize

- a lock or `flock` implementation;
- a journal, tempfile, `fsync`, replace, recovery, or bootstrap implementation;
- a writer guard in `write_file`, `edit_file`, Bash, Git, CLI, A2A, or any other tool;
- a new checkout/worktree in production or CI;
- a workflow, repository setting, branch-protection, CODEOWNERS, or delivery change;
- creation or mutation of `CLAUDE.md`, `AGENTS.md`, or either JSON artifact;
- activation of `disabled`, `preview`, or `canonical` runtime behavior.

The existing D2b preflight, D2a observer, D1 read-back, Feature-00 trust contract, and
Feature-04 model/hash contract remain normative. Phase 1 remains read-only.

## 3. Pinned live evidence

### 3.1 Repository and target baseline

At the pinned `origin/main`:

| Path | HEAD/index | Worktree | Policy meaning |
|---|---|---|---|
| `CLAUDE.md` | regular `100644`, legacy blob `8146a15603c95e5aa1404c9eb7021e3008914b0c` | present | legacy bootstrap only |
| `AGENTS.md` | absent | absent | no second root consumer contract |
| `.steward/context-snapshot.json` | absent | absent | no V1 snapshot generation |
| `.steward/context-publication.json` | absent | absent | no V1 publication record |

The current `.steward/context.json` and `.steward/.context_hash` are legacy runtime
state, not D2b artifacts. The tracked `.steward/.atomic_*.tmp` files are unrelated
hygiene state and must not be adopted as transaction evidence. The baseline is
`legacy_bootstrap`; it is not eligible for automatic D2b recovery or overwrite.

Between the earlier policy scan pin and this final pin, the live heartbeat changed only
the following nine runtime/federation paths; no Context Bridge code, test, spec, root
contract, workflow, or setting changed:

```text
.steward/.context_hash
.steward/context.json
.steward/federation_health.json
.steward/marketplace.json
.steward/sessions.json
data/federation/nadi_outbox.json
data/federation/peers.json
data/federation/relay_seen_ids.json
data/federation/steward_health.json
```

The current Constitution candidate remains `.steward/conventions.md`, blob
`f428d5856a5c525e002c301890777748effbeb4e`; it is source evidence only and is not a
publisher target.

### 3.2 Positive writer evidence

The merged writer package proves these independent mutation families on the inspected
code line:

- unrestricted `write_file` and `edit_file` paths;
- caller-controlled Bash and structured Git;
- dynamic `.steward/tools/*.py` discovery;
- child-agent registry inheritance and caller-supplied extra tools;
- Git actuators, FixPipeline, immune rollback, CircuitBreaker, healer and subprocess
  fallbacks;
- legacy Context and Git-NADI/heartbeat state writers;
- CLI `--export-report` (`steward/__main__.py:196-210`);
- `A2AAdapter.save_tasks(path)` (`steward/a2a_adapter.py:288-314`).

The package intentionally does not claim a closed inventory. Configured state writers,
future dynamic tools, and arbitrary subprocesses remain unknown until positive call-site
classification closes them.

### 3.3 Configured and workspace-path mutators requiring classification

The current code also contains state writers whose path is supplied by construction or
by a caller, rather than by the built-in file tools. They are not proven D2b-target callers
at this pin, but they are part of the policy surface and cannot be omitted from the final
matrix:

| Surface | Positive write evidence | Required classification |
|---|---|---|
| A2A discovery persistence | `A2APeerDiscovery.save_discovered(path)` creates a parent and renames a caller/default path (`steward/a2a_discovery.py:308-325`) | caller path and transaction-namespace exclusion |
| Reaper and marketplace state | `Reaper.save(path)` and `Marketplace.save(path)` write caller-provided paths via temp/replace (`steward/reaper.py:370-384`; `steward/marketplace.py:250-262`) | configured path provenance and target denial |
| Federation registries | configurable peer/verified-agent paths are temp-written and replaced (`steward/federation.py:337-377`) | federation-state allowlist versus Context targets |
| Federation transport/relay | inbox, outbox, quarantine, and seen-ID paths are created, replaced, or deleted (`steward/federation_transport.py:124-242`; `steward/federation_relay.py:340-433`) | shared worktree/index and parent-race boundary |
| Kirtan and federation crypto | ledger path is atomically replaced and key path is generated/written (`steward/kirtan.py:243-249`; `steward/federation_crypto.py:151-157`) | private-state paths and secret-leak boundary |
| Health and Dharma hooks | fixed `.steward/` and federation reports are written each cycle (`steward/hooks/moksha_health.py:39-57`; `steward/hooks/dharma.py:538-547`) | concurrent state writers and delivery scope |
| CircuitBreaker and FixPipeline | workspace paths are restored or escalation files are appended (`steward/tools/circuit_breaker.py:841-869`; `steward/fix_pipeline.py:628-640`) | arbitrary diagnosis path and target exclusion |

## 4. Protected namespaces

The later implementation must use an explicit, versioned path policy. The protected
canonical target set is exactly:

```text
CLAUDE.md
AGENTS.md
.steward/context-snapshot.json
.steward/context-publication.json
```

The protected transaction namespace is separate and equally deny-by-default:

```text
.steward/.context-publish-v1.lock
.steward/.context-publish-v1.journal
.steward/.context-publish-v1.*.tmp
```

The namespace is not a glob permission for arbitrary `.steward` files. Existing legacy
state, tracked atomic-temp hygiene files, Constitution source, and federation state keep
their existing contracts and are not silently absorbed into D2b.

Path policy requirements:

- exact relative names only; no traversal, absolute path, URI, backslash, or symlink
  alias;
- target and transaction parents must be the expected repository root or `.steward`;
- unknown names in the transaction namespace block rather than being cleaned up;
- a caller-provided path is never trusted merely because it is under `.steward`;
- any non-publisher attempt to write a protected name returns a visible blocked or
  `manual_review` result and must not be converted into an empty/no-op success.

## 5. Publisher isolation contract

### 5.1 Process boundary

The canonical publisher is a dedicated, allowlisted process entrypoint. It does not
inherit the normal Steward tool registry, child-agent registry, Bash command text,
caller-supplied extra tools, LLM providers, or healer/actuator callbacks. Its child
environment, executable paths, working directory, file descriptors, and input schema are
explicitly allowlisted by the later G2 spec.

The publisher process has no authority to execute arbitrary commands. Git plumbing is an
explicit read-only/evidence interface or a separately reviewed delivery interface; it is
not delegated to the generic `GitTool`.

### 5.2 Worktree boundary

Canonical candidate generation and local replacement occur only in a dedicated ephemeral
publisher worktree/checkout whose path and repository identity are pinned for the
transaction. The ordinary Steward checkout, heartbeat runner working tree, child-agent
worktree, and human working clone are not publisher targets.

The isolated worktree must have:

- its own index and worktree path;
- no shared writable process namespace with the normal agent/tool registry;
- a validated Git object/database relationship and no unverified `commondir` or alternates
  redirection;
- a cleanup/recovery contract that never deletes another process's checkout or files;
- explicit destruction only after durable delivery or a fail-closed terminal result.

Isolation does not permit a second source of truth. The source, Constitution attestation,
snapshot inputs, and delivery base remain bound to the pinned repository objects. The
worktree is an execution boundary, not a new authority.

### 5.3 Transaction boundary

Inside the isolated publisher worktree, D2b still requires the already-decided sequence:

```text
open and pin repository
  -> acquire thread/process lock
  -> read and validate Constitution attestation
  -> read one explicit snapshot
  -> validate previous generation
  -> prepare four candidates and one journal
  -> fence Git, parents, targets, journal, and temps
  -> replace per file, record last
  -> durable read-back and classify
  -> fence delivery separately
```

The lock proves exclusivity only for this sequence in this worktree. It never proves that
an arbitrary external process respected the lock.

## 6. Non-publisher writer contract

### 6.1 In-process surfaces

The following paths must be centrally default-deny for the protected namespaces before
any canonical publisher can be enabled:

| Surface | Required result for protected path |
|---|---|
| `write_file`, `edit_file` | blocked before filesystem mutation |
| Bash and arbitrary helper subprocess | cannot be used by publisher; external attempt is untrusted and cannot yield publication success |
| structured Git checkout/stash/commit/push | blocked or isolated from publisher worktree; no shared-index claim |
| dynamic `.steward/tools/*.py` | not loaded by publisher; target writer remains blocked outside it |
| child agents and extra tools | no access to publisher worktree or protected names |
| actuators, FixPipeline, immune/CircuitBreaker, healer | excluded from publisher process; target mutation is manual review |
| `--export-report`, `save_tasks(path)` | arbitrary path is not a D2b authorization; protected target is blocked/manual review |
| legacy Context/Git-NADI/heartbeat writers | separate state contract; no publisher-worktree access and no Context delivery authority |

Unknown or newly discovered mutators inherit the same default-deny treatment. They do
not become trusted merely because the inventory has not yet named them.

### 6.2 External processes

The policy does not claim that a normal POSIX advisory lock can stop a hostile or
uncooperating process. Instead, the publisher worktree is private to the publisher
transaction and the final read-back/delivery fence must reject any identity, path, Git,
or byte mismatch. A process that can write the publisher worktree is an isolation failure,
not a valid competing writer.

An external process may continue to update unrelated runtime/federation state in its own
checkout under its own contract. That does not authorize it to stage, commit, or deliver
the four Context paths.

## 7. Required future evidence

The policy is not G1-ready until a separately reviewed D2b preflight proves all of the
following with real fixtures and no production activation:

1. publisher process and worktree identity cannot be replaced between open, prepare,
   replace, read-back, cleanup, and delivery fence;
2. an ordinary Steward process, child agent, Bash helper, Git checkout/stash, dynamic tool,
   actuator, healer, CLI export, and A2A save attempt cannot mutate a protected target in
   the publisher worktree;
3. unknown target names, symlinks, hardlinks, parent replacement, `commondir`, alternates,
   foreign Git indexes, and foreign transaction artifacts fail closed;
4. a mutation in a separate non-publisher checkout cannot be mistaken for the publisher's
   local generation or Git evidence;
5. publisher success requires the D1 read-back, exact target/transaction namespace,
   parent/target fingerprints, and delivery fence; no lock-held success is enough;
6. disabled and preview modes create no protected target or transaction artifact;
7. an unbound legacy baseline remains `legacy_bootstrap` and never auto-recovers;
8. process crashes, timeout, partial replace, cleanup failure, and delivery interruption
   produce visible blocked/manual-review states with a safe fallback;
9. the complete writer inventory is either closed by positive call-site evidence or the
   unknown class remains an explicit permanent fail-closed category;
10. the runner proves no direct `main` push or heartbeat staging can turn local publication
    into unreviewed delivery.

Required adversarial matrix includes every family in the merged writer evidence plus
configured path writers discovered during the final inventory. Each test records the
pinned commit, fixture repository, target bytes before/after, Git evidence, result class,
and whether any protected byte was read or written.

## 8. G1 decision

This proposal makes the policy choice explicit but does not prove its implementation.
The following remain open and block G1:

- complete positive inventory of configured and dynamic mutators;
- exact process/worktree construction and cleanup contract;
- executable/environment allowlist;
- enforcement mechanism for in-process default-deny;
- Linux/macOS isolation and durability drills;
- crash/recovery and delivery-fence evidence;
- final required-check and governance contract.

Therefore:

- G1 remains **OFF**;
- D2b writer, lock, journal, recovery, bootstrap, delivery, workflow, and activation
  remain **forbidden**;
- this document authorizes only a further read-only adversarial review and a later,
  separately scoped D2b G2 preflight.
