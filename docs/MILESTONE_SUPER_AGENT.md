# Milestone: Super Agent — Federation-Ready Autonomous Daemon

**Steward v0.17.0** | **1382 tests green** | **Code frozen**

---

## Core Capabilities

### 1. Persistent Daemon (`--autonomous`)

```
python -m steward --autonomous
```

Boots once. Stays alive forever. Cetana heartbeat drives all work.

| Phase | Sanskrit | Action |
|-------|----------|--------|
| GENESIS | Discovery | Scan senses + Sankalpa → generate typed tasks |
| DHARMA | Governance | Federation pull, reaper, health hooks |
| KARMA | Execution | Dispatch next pending task (deterministic → LLM fallback) |
| MOKSHA | Reflection | Flush outbound federation, persist Hebbian weights |

**Zero boot overhead** between cycles. One `Event.wait()` between beats — no polling, no cron.

### 2. SAMADHI Idle (Health-Driven Frequency)

Cetana reads Vedana (agent health pulse, 5-component weighted signal) and adapts:

| State | Hz | Beat Interval | Condition |
|-------|----|---------------|-----------|
| SAMADHI | 0.1 | 10s | health > 0.8 — deep calm |
| SADHANA | 0.5 | 2s | health 0.5–0.8 — active |
| GAJENDRA | 2.0 | 0.5s | health < 0.5 — emergency |

Smooth EMA transitions. Near-zero CPU at SAMADHI (OS-level `Event.wait`).

### 3. Deterministic Task Dispatch (0 LLM Tokens)

```
Sankalpa → TaskIntent enum → Python method → 0 tokens
```

Title-prefix encoding persists intent to disk: `[HEALTH_CHECK]`, `[CI_CHECK]`, `[FED:peer-id]`.
LLM only wakes when deterministic logic can't solve the problem (real fixes, not busywork).

**Hebbian learning** prevents repeated failure: granular keys (`auto:CI_CHECK:api.py`), confidence < 0.2 escalates to `.steward/needs_attention.md` instead of burning tokens.

### 4. CBR Context Trimming

Constant Bitrate cognition. `CBR_TICK = 64 tokens`. DSP signal processor with:
- Logarithmic compression (graduated degradation, never cliff)
- Phase modulation (ORIENT 0.5x, EXECUTE 1.0x, VERIFY 0.5x)
- Cache gate: `gain *= 1.0 - cache_confidence * 0.5` (branchless)
- Conversation reset per task in daemon mode — context is ephemeral, learning is permanent

### 5. Workspace Isolation (Cross-Repo Federation)

Federated tasks (`[FED:source] title`) trigger isolated execution:
1. Clone target repo into temp directory
2. Override pipeline cwd to clone
3. Run guarded fix (4-gate verification: ruff → bandit → blast radius → pytest)
4. Emit callback (`OP_TASK_COMPLETED` / `OP_TASK_FAILED`)
5. Cleanup clone

No cross-contamination between repos. Each task gets a pristine workspace.

### 6. Outbound Delegation

`DelegateToPeerTool` — Karmendriya for federation command:
1. Query Reaper for alive peers (sorted by trust)
2. Emit `OP_DELEGATE_TASK` to FederationBridge outbox
3. Mark current task `BLOCKED` with metadata: `delegated:{title}|peer:{agent_id}`
4. Return to idle — **no polling, no blocking**

### 7. Async Callbacks

When peer completes delegated work:
1. `OP_TASK_COMPLETED` arrives via git pull (DHARMA phase)
2. Bridge finds matching BLOCKED task by title
3. Resumes task: `BLOCKED → PENDING` with result context (`peer_result:{pr_url}`)
4. KARMA phase picks it up on next beat

---

## Transport Layer: GitNadiSync Federation

```
NadiFederationTransport (file I/O) → GitNadiSync (git network) → GitHub Wiki Repo
```

### Wire Format

Two JSON files in the shared wiki repo:
- `nadi_inbox.json` — outbound messages (what WE write)
- `nadi_outbox.json` — inbound messages (what OTHERS write)

Each message:
```json
{
  "source": "steward-alpha",
  "target": "*",
  "operation": "delegate_task",
  "payload": {"title": "...", "priority": 70},
  "priority": 1,
  "correlation_id": "",
  "timestamp": 1710000000.0,
  "ttl_s": 900.0
}
```

### Operations

| Operation | Direction | Handler |
|-----------|-----------|---------|
| `heartbeat` | IN | Reaper.record_heartbeat() |
| `delegate_task` | IN/OUT | TaskManager.add_task() / emit via bridge |
| `task_completed` | IN/OUT | Resume BLOCKED task / emit via bridge |
| `task_failed` | IN/OUT | Resume BLOCKED task with error / emit |
| `claim_slot` | IN | Marketplace.claim() |
| `release_slot` | IN | Marketplace.release() |
| `claim_outcome` | OUT | Broadcast claim result |

### Pull-Rebase-Push Retry Loop

```
DHARMA:  git fetch origin --prune → git rebase origin/HEAD
MOKSHA:  git add nadi_*.json → git commit → git push
         ↓ rejected (non-fast-forward)?
         git pull --rebase → retry push (max 3 attempts)
         ↓ conflict?
         git rebase --abort → give up gracefully
```

### Throttling

Default: **5-minute minimum** between git operations. Prevents:
- 8640 commits/day at 0.1Hz SAMADHI
- Git history bloat on shared wiki repo
- GitHub API rate limits

Configurable: `sync_interval_s=0` for tests.

---

## Local Swarm: Async Task Engine

### Task Lifecycle

```
PENDING → IN_PROGRESS → COMPLETED
                ↓
           BLOCKED (delegated to peer)
                ↓
           PENDING (callback received)
```

### Sub-Agent Spawning (`sub_agent` tool)

LLM can spawn isolated sub-agents for independent work:
- Fresh AgentLoop with clean 50k-token context window
- Inherits all tools **except** `sub_agent` (prevents recursion)
- 5-minute timeout per sub-agent
- Shares parent's safety guard, attention, and memory
- Returns text result + metadata (round count)

### Task Blocking + Resume

1. AutonomyEngine sets `set_current_task(id, title)` before LLM dispatch
2. If LLM calls `delegate_to_peer` → task marked BLOCKED
3. Agent returns to idle, picks up next PENDING task
4. Federation callback (DHARMA phase) finds BLOCKED task by title match
5. Resumes to PENDING with `peer_result:{pr_url}` or `peer_error:{msg}`

No busy-waiting. No polling loops. Event-driven via Cetana heartbeat.

---

## Deployment

### Systemd (Bare Metal)

```bash
sudo bash deploy/setup-node.sh git@github.com:org/repo.wiki.git
sudo nano /opt/steward/.env    # API keys
sudo systemctl enable --now steward
```

### GitHub Actions (CI)

```bash
python -m steward --autonomous  # In workflow step
```

### Verification

```bash
python scripts/test_two_nodes.py  # Full round-trip crucible
```

Proves: Alpha delegates → git push → hub → git pull → Beta dispatches → Beta completes → git push → hub → git pull → Alpha receives callback.

---

## Architecture Invariants

1. **LLM is the 25th sense, not the CEO.** Deterministic dispatch first, LLM fallback only for real fixes.
2. **Context is ephemeral, learning is permanent.** Conversation resets per task. Hebbian weights persist across sessions.
3. **Git is the network, not the message broker.** Retry + throttle compensate. FederationNadi handles file I/O.
4. **No death spirals.** Minimum budget = 2x CBR. Confidence < 0.2 escalates instead of burning tokens.
5. **No learned helplessness.** Granular Hebbian keys. Failing on `api.py` doesn't poison `utils.py`.
6. **Transport-agnostic.** Any `FederationTransport` implementation plugs in. Git, HTTP, MCP — bridge doesn't care.

---

## File Map

| File | Role |
|------|------|
| `steward/agent.py` | StewardAgent + run_daemon() |
| `steward/cetana.py` | Heartbeat daemon (4-phase MURALI, adaptive Hz) |
| `steward/autonomy.py` | AutonomyEngine (deterministic dispatch + guarded fixes) |
| `steward/federation.py` | FederationBridge (O(1) operation routing) |
| `steward/federation_transport.py` | NadiFederationTransport (FederationNadi adapter) |
| `steward/git_nadi_sync.py` | Git network layer (retry, throttle) |
| `steward/tools/delegate.py` | DelegateToPeerTool (outbound delegation) |
| `steward/tools/sub_agent.py` | Sub-agent spawning (local swarm) |
| `steward/hooks/dharma.py` | DHARMA phase hooks (federation pull + reaper) |
| `steward/hooks/moksha.py` | MOKSHA phase hooks (federation flush + push) |
| `deploy/steward.service` | Systemd unit file |
| `deploy/setup-node.sh` | One-command node provisioning |
| `deploy/env.example` | Environment template |
| `scripts/test_two_nodes.py` | Two-node federation crucible |
