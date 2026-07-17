# FEATURE 01 — SLICE D2b WRITER-BOUNDARY EVIDENCE

> **Status:** EVIDENCE PACKAGE 0.1 — INVENTORY RECORDED; POLICY DECISION OPEN; G1 OFF
>
> **Investigated main:** `kimeisele/steward@465d23b39423ddf0935483b9de3f6fc8900be1f2`
>
> **Parent D2b-preflight merge:** `f582e0d63876df8be61e8970a0fe065a2b2c034e`
>
> **Earlier writer scan pin:** `53bfae41afbaec4338966a93975975dccc20e36a`
>
> **Date:** 2026-07-17

This is a read-only evidence package for §7.1 of
`FEATURE_01_SLICE_D2B_PREFLIGHT.md`. It records a materially expanded set of **known**
write-capable surfaces, but completeness remains an open evidence gate; it does not
choose how those surfaces will be constrained. No writer, lock, journal, recovery,
workflow, delivery, bootstrap, or activation is implemented here.

## 1. Pin and scope

The inspected clone was fast-forwarded to the current `origin/main` and was clean before
the evidence branch was created. Since the earlier writer scan pin, only heartbeat-state
files changed; the final evidence pin is `465d23b3…`:

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

No Context Bridge module, test, feature spec, workflow, root contract, or repository
setting changed in that drift. PR existence is a separate live GitHub fact and is not
used as a runtime-authority signal by this package.

Permitted scope for this package is this file under
`specs/context_bridge_evidence/`. No product or workflow path is changed.

## 2. Method and trust boundary

The inventory below is based on positive symbol and call-site evidence at the pinned
commit. A path is classified as a writer surface when it can mutate a D2b target, mutate
the worktree/index used to prove a generation, or load another executable/tool that can
do so. Absence of a target filename in a module is not treated as proof of safety when
the module accepts arbitrary paths or shell text.

The D2b lock proposed in the parent preflight would protect only cooperating code. The
question in this package is therefore broader than “does a Context Publisher exist?”:

> Can any reachable Steward process, child agent, actuator, helper, or workflow mutate a
> target or its Git evidence without acquiring the same transaction boundary?

## 3. Standard tool surfaces

### 3.1 Built-in registry

`steward/tool_providers.py:38-76` constructs and registers, among others:

- `BashTool`;
- `WriteFileTool`;
- `EditTool`;
- `GitTool`;
- `SubAgentTool`.

`StewardAgent.__init__()` selects `BuiltinToolProvider()` and
`FileSystemToolProvider()` by default (`steward/agent.py:163-168`), then boots those
tools into the normal registry. This is an active execution surface, not documentation
about a hypothetical tool set.

### 3.2 Direct file tools

- `WriteFileTool.execute()` expands a caller-provided path and calls
  `Path.write_text()` (`steward/tools/write_file.py:52-73`). It has no repository-root
  allowlist and no D2b lock acquisition.
- `EditTool.execute()` reads and then writes a caller-provided path
  (`steward/tools/edit.py:61-119`). Its read-before-write rule is an agent-safety
  convention, not a filesystem transaction fence.

Both tools can address `CLAUDE.md`, `AGENTS.md`, `.steward/conventions.md`, any D2b JSON
target, a journal, a temp, or a lock path when given such a path.

### 3.3 Shell execution

`BashTool.execute()` runs `subprocess.run(["bash", "-c", command], cwd=self._cwd)` with
caller-controlled command text (`steward/tools/bash.py:67-88`). Shell redirection,
`mv`, `cp`, `rm`, `chmod`, helper programs, and arbitrary Git invocations are therefore
reachable through one tool.

The dispatch layer audits only calls named `bash` through Narasimha
(`steward/loop/tool_dispatch.py:63-74`). That threat audit does not prove target-path
exclusion, shared-lock participation, journal ownership, or safe Git evidence. The same
dispatch layer's file-operation map covers only `write_file` and `edit_file`
(`steward/loop/tool_dispatch.py:38-43`); shell and Git mutations are not represented in
its write dependency partition (`:127-168`).

### 3.4 Structured Git execution

`GitTool` exposes `checkout`, `branch_create`, `commit`, `push`, and related operations
(`steward/tools/git.py:53-67,110-128`). Its checkout path performs `git checkout` after
an auto-stash (`:218-231`); the protected-branch check applies to commit/push, not to
checkout or stash. Its commit path stages all files when no explicit file list is given
(`:247-253`). All calls use the agent worktree without the D2b lock.

Consequences:

- checkout or stash can replace a target inode during a D2b fence or replace;
- Git index changes can invalidate a previously observed HEAD/index relation;
- commit/push can deliver unrelated staged target changes even when the Context Bridge
  itself did not write them.

## 4. Dynamic and inherited tool surfaces

### 4.1 Filesystem tool discovery

`FileSystemToolProvider.provide()` scans every non-private `.steward/tools/*.py` file and
imports it (`steward/tool_providers.py:79-121`). It registers every discovered subclass
of the generic `Tool` protocol (`:123-148`). The directory is absent in the pinned tree,
but the provider is a runtime extension mechanism. Current absence is not a closed
inventory and does not constrain a future checkout or runtime-created module.

### 4.2 Child agents and caller-supplied extras

`SubAgentTool._build_child_registry()` copies every parent tool except `sub_agent`
(`steward/tools/sub_agent.py:164-175`). A child agent therefore inherits `bash`, `git`,
direct file tools, and any dynamic writer.

`collect_tools()` accepts `extra_tools` from its caller
(`steward/tool_providers.py:151-183`), and `StewardAgent` passes its `tools` argument
into that parameter (`steward/agent.py:163-168`). API/Telegram or another embedding can
therefore add a write-capable tool without changing the built-in provider list.

No current D2b lock is acquired by any of these registry or inheritance paths.

## 5. Programmatic Steward mutators

The writer boundary is not limited to LLM tool calls.

### 5.1 Git actuators and autonomy

`StewardAgent` constructs `GitActuator`/`GitHubActuator` and injects them into
`AutonomyEngine` (`steward/agent.py:196-218`). `GitActuator` performs local checkout,
commit, push, and branch cleanup through raw Git subprocesses
(`steward/actuators.py:97-170`). The protected-branch rule blocks some commit/push
operations but does not create a repository-wide transaction lock.

`FixPipeline` uses the actuator when present and has raw-subprocess fallbacks otherwise
(`steward/fix_pipeline.py:253-277,357-380`). Its proactive path runs branch creation,
LLM changes, rollback, commit, push, and PR creation in the same mutable worktree
(`steward/fix_pipeline.py:280-345`). This is a second programmatic mutation family that
does not participate in D2b.

### 5.2 Circuit breaker and immune rollback

`CircuitBreaker` is constructed by `StewardAgent` (`steward/agent.py:190-192`) and is
used by the fix pipeline to roll back changed files. `StewardImmune._rollback_file()`
directly runs `git checkout HEAD -- <file>` with a diagnosis-provided path
(`steward/immune.py:421-438`). The AST fixer path receives a diagnosis file path and
invokes registered fixers against the active workspace (`:357-385`). These paths can
alter Git evidence or a target whenever the diagnosed path resolves there; no D2b lock
or target allowlist is present.

### 5.3 Healer and subprocess fallbacks

`RepoHealer` and its deterministic/compound fixers are reachable from the autonomy
engine. They accept a workspace and apply file changes; compound repair can invoke
`ruff --fix` and other subprocesses (`steward/healer/pipeline.py:22-31,67-145`;
`steward/healer/compound.py:121-145`). A future evidence drill must classify these
paths by positive call-site reachability rather than assuming that “healer” means a
separate clone.

### 5.4 Arbitrary-path CLI and task-state writers

`_handle_list_quarantine()` accepts the caller-provided `--export-report` path and
creates its parent before writing JSON with `Path.write_text()`
(`steward/__main__.py:196-210`). The option is not restricted to a quarantine-owned
directory and has no D2b lock or target exclusion. A caller can therefore direct this
writer at a Context target, journal, or temporary path; its normal use is not evidence
that such a call is currently made.

`A2AAdapter.save_tasks(path)` likewise accepts an arbitrary caller-provided path,
creates its parent, and writes serialized in-flight tasks
(`steward/a2a_adapter.py:288-314`). It has no D2b lock or target allowlist. This is a
programmatic state writer that must be included in the later injection and call-site
classification matrix, even though the current inventory does not establish a caller
that targets the four canonical files.

## 6. Existing state and delivery writers

- `steward/context_bridge.py:186-217,525-541` writes legacy `.steward/context.json`
  and `.steward/.context_hash` through its own tempfile/rename helper. It does not
  write the D2b four targets, but its filesystem activity shares `.steward` with a
  future journal and temp namespace.
- `steward/git_nadi_sync.py:65-170,183-240` pulls/rebases, stages an allowlisted
  federation subtree, commits, and pushes using a separate subprocess path. It does not
  target the four Context files by allowlist, but it can race the shared Git index and
  checkout.
- The heartbeat workflow has its own `if: always()` staging/commit/push step. Its
  workflow concurrency serializes matching Actions runs only; it is not a process lock
  for the writer families above.

## 7. Findings

1. **The reachable writer set is materially larger than the default file tools, but this
   inventory is not closed.** Bash, structured Git, dynamic tools, inherited child
   registries, actuators, fix pipelines, immune rollback, workflow/state writers,
   `--export-report`, and `A2AAdapter.save_tasks(path)` all require explicit
   classification. Additional arbitrary-path mutators must be found and classified
   before any completeness claim or D2b implementation gate can close.
2. **Current safety gates are not a D2b exclusion boundary.** Narasimha, Iron Dome,
   branch protection, auto-stash, marketplace slots, and dependency waves provide
   observability or local policy. None proves shared lock ownership and target-path
   exclusion across processes.
3. **No positive evidence supports a single writer today.** D2a remains read-only; the
   proposed D2b lock and journal do not exist; generic and programmatic mutation paths
   remain independently reachable.
4. **The pinned four-target baseline remains legacy-only.** This package does not alter
   the rule that `CLAUDE.md` alone is not a D2b bootstrap baseline.

## 8. Required policy decision before D2b code

The next feature spec must choose and prove one boundary, rather than merely list tools:

- every path capable of touching a D2b target enters the same lock/journal transaction;
- or all non-publisher paths fail closed for the four targets while canonical publishing
  is active;
- or the canonical publisher runs in a process/worktree isolation boundary that
  positively excludes the other mutation families and proves delivery separately.

For any chosen boundary, the adversarial test contract must inject:

- `write_file` and `edit_file` direct writes;
- Bash redirection and an arbitrary helper subprocess;
- Git checkout/stash/index mutation and actuator fallback;
- a dynamically loaded `.steward/tools/*.py` writer;
- the `--export-report` arbitrary-path CLI writer;
- the `A2AAdapter.save_tasks(path)` arbitrary-path state writer;
- child-agent and caller-supplied extra tools;
- immune/healer/circuit-breaker rollback paths;
- Git Nadi and heartbeat staging during lock, fence, temp, replace, read-back, and
  recovery phases.

Each injection must produce either a transaction-bound result or a fail-closed
`manual_review`/blocked result, never a positive publication claim from mixed evidence.

## 9. Gate result

The writer inventory is materially expanded but not complete, and the policy boundary is unresolved.
Therefore:

- G1 remains **OFF**;
- D2b writer, lock, journal, recovery, bootstrap, delivery, workflow, and activation
  remain **forbidden**;
- this package authorizes only the next read-only policy/spec decision.
