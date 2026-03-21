# Federation Wire Status

Last verified: 2026-03-21

## What Flows

### agent-city → steward (WORKING)

| Field | Value |
|-------|-------|
| Hub mailbox | `nadi/agent-city_to_steward.json` |
| Operation | `city_report` |
| Frequency | Every heartbeat (~75s cycle) |
| First successful delivery | 2026-03-21, HB 53 |
| Verified E2E | Yes — 4 messages received after routing fix |

**Payload fields** (verified from agent-city source + live data):
- `heartbeat`: int — monotonic counter
- `population` / `alive`: int — agent census
- `chain_valid`: bool — blockchain integrity
- `mission_results`: list of `{id, name, status, owner}`
- `pr_results`: list of PR outcomes
- `active_campaigns`: list of campaign summaries

**Steward handler** (`_handle_city_report` in `federation.py`):
1. Records heartbeat as reaper liveness signal
2. Extracts missions matching `"Brain bottleneck: {target}"` prefix
3. Creates `[FED:agent-city] Fix bottleneck: {target}` tasks (priority 70)
4. Dedup: skips if active task with same target exists
5. KARMA phase dispatches the task

**Mission types observed in production** (from 144 messages in old mailbox):
- `Brain bottleneck: code_health` — handled
- `Brain bottleneck: technical_debt_and_engagement` — handled
- `IssueHeal: #NNN` (~185 unique) — ignored (not a bottleneck)
- `Heal: ruff_clean`, `Heal: tests_pass` — ignored (not a bottleneck)
- `Discussion: #0` — ignored

### steward → all peers (WORKING)

| Field | Value |
|-------|-------|
| Hub mailboxes | `steward_to_agent-city.json`, `steward_to_agent-internet.json`, `steward_to_agent-world.json`, `steward_to_steward-protocol.json` |
| Operation | `heartbeat` |
| Content | health score, capabilities, version, fingerprint |

Steward already emits heartbeats to all known peers via `flush_outbound()`.
Outbound events also include: `claim_outcome`, `pr_review_verdict`, `merge_occurred`.

### agent-city `pr_review_request` → steward (ROUTING FIXED, NOT YET SEEN IN PROD)

agent-city's `PRScannerHook` emits `operation="pr_review_request"` when new PRs
are detected. Previously routed to steward-protocol (wrong). Now routes to steward.
Handler exists in `FederationBridge._handle_pr_review_request`.

Will appear in production next time agent-city detects a new PR.

## What Doesn't Flow

### agent-world → steward

agent-world has **zero NADI code**. No federation emission. No `nadi_outbox`.
Hub mailbox `agent-world_to_steward.json` is empty.

### agent-internet → steward

agent-internet has federation infrastructure (`steward_federation.py`,
`git_federation.py`, `federation_descriptor.py`) but **no NADI outbox emission**.
The code is about web content publishing, not inter-agent messaging.
Hub mailbox `agent-internet_to_steward.json` is empty.

### steward-protocol → steward

steward-protocol is the **upstream library provider** (`vibe_core` pip package).
It defines `FederationMessage`, `CityReport`, `FederationDirective` types but
has **zero inbound NADI handlers** and **zero outbound emission code**.
Its MOKSHA hooks (`samskara_service.py`) don't emit federation messages.
Hub mailbox `steward-protocol_to_steward.json` is empty.

## Bugs Fixed This Session

### Routing Bug (Critical)

**agent-city PR #511** — merged 2026-03-21

`city/federation_nadi.py` had `_default_target = "steward-protocol"` (hardcoded).
All NADI messages went to `agent-city_to_steward-protocol.json` where nobody reads
them. 144 city_reports accumulated at the wrong address.

Fix: `_default_target = "steward"`. Verified E2E: heartbeat 53+ arrives in
`agent-city_to_steward.json`.

### Handler Gap (Fixed)

steward had no `city_report` handler. Added `_handle_city_report` to
`FederationBridge` with `Brain bottleneck:` mission extraction.

## Architecture Notes

```
agent-city MOKSHA
  → FederationNadi.emit(source="moksha", operation="city_report")
  → FederationNadi.flush() → data/federation/nadi_outbox.json
  → FederationRelayPushHook → FederationRelay.push_to_hub()
  → GitHub API → steward-federation Hub
  → nadi/agent-city_to_steward.json

steward DHARMA
  → GitNadiSync reads steward-federation Hub
  → FederationBridge.process_inbound(transport)
  → _handle_city_report() → TaskManager.add_task()

steward KARMA
  → TaskManager.get_next_task() → [FED:agent-city] Fix bottleneck: X
  → AutonomyEngine._execute_federated_task()
  → FixPipeline.guarded_llm_fix() or guarded_pr_fix()
  → bridge.emit(OP_TASK_COMPLETED or OP_TASK_FAILED)

steward MOKSHA
  → FederationBridge.flush_outbound(transport)
  → steward_to_agent-city.json on Hub
```

## What's Missing (Honest)

1. **No bottleneck missions in current heartbeats.** The 4 verified messages
   all contain `IssueHeal` missions. `Brain bottleneck:` was seen in historical
   data (HB 382+) but not in HB 53-56. The handler is ready and tested — it
   will activate when agent-city's Brain creates bottleneck missions.

2. **Steward doesn't read from Hub yet in daemon mode.** The `GitNadiSync`
   service needs to be wired into DHARMA phase to pull from the Hub. Currently
   only works when triggered manually or via CI.

3. **No bi-directional handshake.** Steward emits heartbeats but agent-city
   doesn't yet consume steward's heartbeat from `steward_to_agent-city.json`.
   Agent-city has `FederationRelayPullHook` in genesis phase but it reads from
   the legacy `nadi_outbox.json`, not per-peer mailboxes.

4. **IssueHeal missions are ignored.** ~185 unique `IssueHeal: #NNN` missions
   flow through but steward doesn't act on them. Could be wired as federated
   tasks if desired.

5. **agent-world and agent-internet are passive.** They exist in the federation
   registry but don't participate in NADI messaging.
