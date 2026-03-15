# Steward Briefing
Project: 
Path: .


## Environment Perception
Git: main, 3 dirty, ci=success, 0 open PRs
Project: python
Code: 168 files, 589 cls, 263 fn, 10 low-cohesion cls (worst: DummyHook LCOM4=5)
Tests: pytest, 70 files, last=unknown
Health: 168 source files, clean

## Recent Sessions
Previous sessions in this project:
  [2026-03-13] clean: [autonomous] HEALTH_CHECK (0 tokens, 0 rounds, files: none)
  [2026-03-13] clean: [autonomous] HEALTH_CHECK (0 tokens, 0 rounds, files: none)

## CRITICAL NOW
CI status: success.
Health: `rajas` (moderate), `provider_only` source.
Project status: 2 dirty files.
Recent autonomous HEALTH_CHECK tasks are consistently `clean`.
No active `gaps` or `immune` heal attempts recently.
Several critical open issues, including test fixture deduplication, deeper MahaMantra integration, and cache cleansing.

## RULES (non-negotiable)
- ruff format before every commit
- NEVER change NORTH_STAR_TEXT (it's a MahaCompression seed — breaks all alignment)
- Identity comes from data/federation/peer.json (nadi protocol)
- No hardcoded owner/org strings — use _get_federation_owner()
- CBR (OperationalQuota) on ALL external calls — API, LLM, subprocess
- Test suite baseline: ~3 minutes, ~1570 tests. Regression = your fault.
- except pass is Anti-Buddhi — log or propagate, never swallow silently

## ARCHITECTURE (compact)

### Services
| Service Name | Description | Protocol |
| :----------- | :---------- | :------- |
| `SVC_ANTARANGA` | 512-slot O(1) contiguous state chamber (16 KB). | |
| `SVC_ATTENTION` | O(1) tool routing. | |
| `SVC_CACHE` | TTL cache to avoid redundant work. | playbook |
| `SVC_COMPRESSION` | Deterministic seed extraction for cache + learning. | |
| `SVC_DIAMOND` | TDD enforcement with RED/GREEN gates. | naga |
| `SVC_EVENT_BUS` | Real-time event stream with Sudarshana rate limiting. | |
| `SVC_FEDERATION` | Cross-agent message routing. | |
| `SVC_FEDERATION_TRANSPORT` | Pluggable transport for cross-agent messaging. | |
| `SVC_FEEDBACK` | Pain/pleasure signals for outcome learning. | |
| `SVC_GIT_NADI_SYNC` | Git pull/push for federation nadi files. | |
| `SVC_IMMUNE` | Unified self-healing system (diagnose → heal → verify → Hebbian learn). CytokineBreaker prevents autoimmune cascades. | |
| `SVC_INTEGRITY` | Boot-time validation of all services. | |
| `SVC_KNOWLEDGE_GRAPH` | 4-dimensional codebase understanding (zero tokens). | |
| `SVC_MAHA_LLM` | Deterministic semantic engine (L0 zero-cost intent). | |
| `SVC_MARKETPLACE` | Slot conflict resolution for federation peers. | |
| `SVC_MEMORY` | Persistent agent memory. | Chitta |
| `SVC_NARASIMHA` | Hypervisor-level emergency killswitch. | |
| `SVC_NORTH_STAR` | Infrastructure-level goal seed (not LLM prompt), MahaCompression seed, never sent to LLM as text. | |
| `SVC_OUROBOROS` | Self-healing pipeline (detect → verify → heal). | |
| `SVC_PHASE_HOOKS` | Composable phase dispatch for MURALI. | |
| `SVC_PROMPT_CONTEXT` | Dynamic context resolvers for system prompt. | |
| `SVC_PROVIDER` | Multi-LLM failover. | |
| `SVC_REAPER` | Network garbage collection for federation peers. | |
| `SVC_SAFETY_GUARD` | Iron Dome protection. | |
| `SVC_SANKALPA` | Autonomous mission planning and intent generation. | |
| `SVC_SIGNAL_BUS` | Agent event communication. | |
| `SVC_SIKSASTAKAM` | 7-beat cache lifecycle from Verse 1. | |
| `SVC_SYNAPSE_STORE` | Persistent Hebbian weights across sessions. | |
| `SVC_TASK_MANAGER` | Persistent task tracking with priority selection. | |
| `SVC_TOOL_REGISTRY` | Tool lookup and execution. | |
| `SVC_VENU` | O(1) 19-bit DIW rhythm driving execution cycle. | |

### MURALI Phases and Hooks
| Phase | Role | Hooks (Priority, Description) |
| :---- | :--- | :-------------------------- |
| **genesis** | Discover — run senses, scan environment | [20] `genesis_discovery` — Actively discover federation peers and register them in the reaper. |
| **dharma** | Govern — check invariants, validate health | [10] `dharma_health` — Monitor vedana health — set anomaly flag when critical. <br/> [30] `dharma_reaper` — Run HeartbeatReaper to detect and manage dead peers. <br/> [40] `dharma_marketplace` — Purge expired marketplace claims. <br/> [50] `dharma_federation` — Broadcast heartbeat and process inbound federation messages. <br/> [60] `dharma_immune` — Run immune self-diagnostics during DHARMA phase (every 4th cycle). |
| **karma** | Execute — work on highest-priority task | |
| **moksha** | Reflect — persist state, log stats, learn | [20] `moksha_synapse` — Persist Hebbian learning weights. <br/> [40] `moksha_health_report` — Write federation health snapshot after each MURALI cycle. <br/> [50] `moksha_persistence` — Persist reaper peer state and marketplace claims to disk. <br/> [80] `moksha_federation` — Flush outbound federation events via transport. |

### Kshetra (25-Tattva Architecture Map)
| # | Element | Category | Role |
|---|---------|----------|------|
| 1 | MANAS | antahkarana | Perceive and classify user intent (zero LLM) |
| 2 | BUDDHI | antahkarana | Discriminate: tool selection, verdicts, token budget |
| 3 | AHANKARA | antahkarana | Agent identity, GAD-000 compliance, capabilities |
| 4 | CITTA | antahkarana | Store tool execution impressions (awareness/state) |
| 5 | SHABDA | tanmatra | Event signals between components |
| 6 | SPARSHA | tanmatra | Parse input from LLM responses |
| 7 | RUPA | tanmatra | Display output to user |
| 8 | RASA | tanmatra | Validate and sanitize tool parameters |
| 9 | GANDHA | tanmatra | Detect failure patterns in tool history |
| 10 | SHROTRA | jnanendriya | Hear project history via git (branch, commits, upstream) |
| 11 | TVAK | jnanendriya | Feel project structure via filesystem (language, dirs, config) |
| 12 | CHAKSHUS | jnanendriya | See code structure via AST (modules, classes, functions) |
| 13 | RASANA | jnanendriya | Taste code quality via test framework (results, coverage) |
| 14 | GHRANA | jnanendriya | Smell code entropy via file metrics (staleness, size, smells) |
| 15 | VAK | karmendriya | Speak to LLM, compose prompts |
| 16 | PANI | karmendriya | Execute tool calls (hands) |
| 17 | PADA | karmendriya | Route tool calls via O(1) Lotus (navigation) |
| 18 | PAYU | karmendriya | Compact and clean context (cleanup/GC) |
| 19 | UPASTHA | karmendriya | Create and wire services (genesis) |
| 20 | AKASHA | mahabhuta | Inter-agent communication field (ether/network) |
| 21 | VAYU | mahabhuta | The agent loop process flow (air/process) |
| 22 | TEJAS | mahabhuta | LLM computation and transformation (fire/compute) |
| 23 | APAS | mahabhuta | Cross-session memory state (water/memory) |
| 24 | PRITHVI | mahabhuta | Persistent storage on disk (earth/storage) |
| 25 | JIVA | para_prakriti | The living entity — infinitely potent but tiny (1/25th) |

## FEDERATION
-   **Services**: `SVC_FEDERATION` for message routing, `SVC_FEDERATION_TRANSPORT` for pluggable transport, `SVC_GIT_NADI_SYNC` for `nadi` file synchronization, `SVC_REAPER` for network garbage collection, `SVC_MARKETPLACE` for slot conflict resolution.
-   **MURALI Hooks**: `genesis_discovery` actively finds peers; `dharma_reaper` manages dead peers; `dharma_marketplace` purges claims; `dharma_federation` broadcasts heartbeats and processes inbound messages; `moksha_federation` flushes outbound events.
-   **State**: 0 total peers detected. Reaper has performed 126 reaps and 9 evictions. Marketplace has 0 active claims.

## OPEN ISSUES
-   #18: Test fixture dedup: 39 duplicate Fake classes across 11+ files
-   #17: Deeper MahaMantra substrate integration — steward cognition layer
-   #16: Siksastakam cache cleansing after immune heals
-   #15: Known slop in v0.20.0 — critical self-audit
-   #6: Campaigns system: dynamic North Star + mission config