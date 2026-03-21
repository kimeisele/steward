# Federation Wire Status

Last verified: 2026-03-21

## What Flows

### agent-city → steward: `city_report` (WORKING)

| Field | Value |
|-------|-------|
| Hub mailbox | `nadi/agent-city_to_steward.json` |
| Operation | `city_report` |
| Frequency | Every heartbeat (~75s cycle) |
| First successful delivery | 2026-03-21, HB 53 |

**Payload**: heartbeat, population, alive, chain_valid, mission_results, pr_results, active_campaigns

**Handler** (`_handle_city_report`): Records reaper liveness, extracts `Brain bottleneck:` missions → creates `[FED:agent-city]` tasks.

### agent-city → steward: `bottleneck_escalation` (WIRED)

| Field | Value |
|-------|-------|
| Hub mailbox | `nadi/agent-city_to_steward.json` |
| Operation | `bottleneck_escalation` |
| Trigger | Brain scope gate rejects code-fix mission |

**Payload**: target, source (brain_health|brain_critique), evidence, requested_action, heartbeat

**Handler** (`_handle_bottleneck_escalation`): Creates `[BOTTLENECK_ESCALATION] {target}` task (priority 70), dedup by active tasks. KARMA dispatches to AutonomyEngine.

### agent-city → steward: `pr_review_request` (WIRED)

Previously routed to steward-protocol (wrong). Now routes to steward (PR #511).
Handler exists in `FederationBridge._handle_pr_review_request`.

### steward → all peers: `heartbeat` (WORKING)

| Field | Value |
|-------|-------|
| Hub mailboxes | `steward_to_{peer}.json` per-peer |
| Operation | `heartbeat` |
| Targets | Dynamic from reaper registry (ALIVE + SUSPECT peers) |

Also emits: `claim_outcome`, `pr_review_verdict`, `diagnostic_report`.

### agent-world → all peers: `world_state_update` + `heartbeat` (NEW)

| Field | Value |
|-------|-------|
| Code | `agent_world/federation.py` + `nadi_kit.py` |
| Trigger | After `run_world_heartbeat()` aggregation |
| Operations | `world_state_update`, `heartbeat` |

**Payload**: version, cities, agents, policies_hash, federation_health.
**Steward handler** (`_handle_world_state_update`): Refreshes reaper liveness, stores state.

### agent-world → all peers: `policy_update` (NEW)

Emitted on governance policy changes. Steward handler stores for compliance checks.

### agent-internet → all peers: `heartbeat` (NEW)

| Field | Value |
|-------|-------|
| Code | `agent_internet/own_heartbeat.py` + `nadi_kit.py` |
| Trigger | End of relay pump cycle |

Control plane now announces its own existence to the federation.

## What Doesn't Flow Yet

### `bottleneck_resolution` (steward → agent-city)

Steward can FIX bottlenecks (AutonomyEngine) but has no way to tell agent-city
"I fixed your bottleneck, unblock yourself." Agent-city's scope gate will keep
escalating the same bottleneck until it resolves organically.

**Needed**: `task_completed` or `bottleneck_resolution` message from steward → agent-city
after AutonomyEngine successfully fixes the issue.

### Cross-repo workspace isolation

Steward can heal its own repo but cannot yet clone agent-city's repo, fix code
there, and create PRs. The `[BOTTLENECK_ESCALATION]` tasks will create tasks
but AutonomyEngine's `_execute_federated_task` needs cross-repo checkout support.

### steward-protocol → steward

steward-protocol is the upstream library provider (vibe_core). It has zero NADI
emission. Hub mailbox empty. Low priority — it's a library, not an agent.

## Shared Infrastructure: nadi_kit

`nadi_kit.py` is the shared NADI SDK vendored across federation repos.
Canonical source: `kimeisele/steward-federation/nadi_kit.py`

| Repo | Has nadi_kit | Emits | Receives |
|------|-------------|-------|----------|
| steward | No (own impl) | heartbeat, verdict, diagnostic | city_report, bottleneck_escalation, world_state_update, policy_update |
| agent-city | No (own impl) | city_report, bottleneck_escalation, pr_review_request | heartbeat, pr_review_verdict |
| agent-world | Yes | world_state_update, policy_update, heartbeat | city_report, heartbeat |
| agent-internet | Yes | heartbeat | heartbeat |
| agent-template | Yes | heartbeat | heartbeat |

## Architecture

```
agent-city MOKSHA
  → FederationNadi.emit("city_report" | "bottleneck_escalation")
  → push_to_hub() → nadi/agent-city_to_steward.json

agent-world heartbeat
  → nadi_kit NadiNode.emit("world_state_update")
  → node.sync() → nadi/agent-world_to_*.json

agent-internet relay pump
  → own_heartbeat.emit_control_plane_heartbeat()
  → node.sync() → nadi/agent-internet_to_*.json

steward DHARMA
  → GitHubFederationRelay.pull_from_hub()
  → FederationBridge.process_inbound()
  → dispatch: city_report | bottleneck_escalation | world_state_update | ...

steward KARMA
  → TaskManager picks [BOTTLENECK_ESCALATION] or [FED:*] tasks
  → AutonomyEngine dispatches fix pipeline

steward MOKSHA
  → FederationBridge.flush_outbound()
  → GitHubFederationRelay.push_to_hub()
  → Dynamic targets from reaper (not hardcoded)
```
