# Steward — steward

## Status


## Environment Perception
Git: main, 1 dirty, ci=success, 0 open PRs
Project: python
Code: 168 files, 589 cls, 263 fn, 10 low-cohesion cls (worst: DummyHook LCOM4=5)
Tests: pytest, 70 files, last=unknown
Health: 168 source files, clean

## Federation
Peers: 0, Reaps: 0

## Open Issues
- #21: [review-request] The Wire-Crash-Fallback-Abandon Pattern: Why Decentralized Systems Silently Fail
- #20: [review-request] Test Research Result
- #19: [review-request] How do agents coordinate?
- #18: Test fixture dedup: 39 duplicate Fake classes across 11+ files
- #17: Deeper MahaMantra substrate integration — steward cognition layer
- #16: Siksastakam cache cleansing after immune heals
- #6: Campaigns system: dynamic North Star + mission config

## Recent Sessions
- [clean] [autonomous] HEALTH_CHECK
- [clean] [autonomous] HEALTH_CHECK
- [clean] [autonomous] HEALTH_CHECK

## Architecture
North Star: execute tasks with minimal tokens by making the architecture itself intelligent

### Services (31)
| Service | Description |
|---------|-------------|
| `SVC_ANTARANGA` | AntarangaRegistry — 512-slot O(1) contiguous state chamber (16 KB). |
| `SVC_ATTENTION` | MahaAttention — O(1) tool routing. |
| `SVC_CACHE` | EphemeralStorage — TTL cache to avoid redundant work (protocol: playbook). |
| `SVC_COMPRESSION` | MahaCompression — deterministic seed extraction for cache + learning. |
| `SVC_DIAMOND` | NagaDiamondProtocol — TDD enforcement with RED/GREEN gates (protocol: naga). |
| `SVC_EVENT_BUS` | EventBus — real-time event stream with Sudarshana rate limiting. |
| `SVC_FEDERATION` | FederationBridge — cross-agent message routing. |
| `SVC_FEDERATION_TRANSPORT` | FederationTransport — pluggable transport for cross-agent messaging. |
| `SVC_FEEDBACK` | FeedbackProtocol — pain/pleasure signals for outcome learning. |
| `SVC_GIT_NADI_SYNC` | GitNadiSync — git pull/push for federation nadi files. |
| `SVC_IMMUNE` | StewardImmune — unified self-healing system. diagnose() → heal() → verify → Hebb |
| `SVC_INTEGRITY` | IntegrityChecker — boot-time validation of all services. |
| `SVC_KNOWLEDGE_GRAPH` | UnifiedKnowledgeGraph — 4-dimensional codebase understanding (zero tokens). |
| `SVC_MAHA_LLM` | MahaLLMKernel — deterministic semantic engine (L0 zero-cost intent). |
| `SVC_MARKETPLACE` | Marketplace — slot conflict resolution for federation peers. |
| `SVC_MEMORY` | MemoryProtocol — persistent agent memory (Chitta). |
| `SVC_NARASIMHA` | NarasimhaProtocol — hypervisor-level emergency killswitch. |
| `SVC_NORTH_STAR` | North Star — infrastructure-level goal seed (not LLM prompt). The north_star is  |
| `SVC_OUROBOROS` | OuroborosLoopOrchestrator — self-healing pipeline (detect → verify → heal). |
| `SVC_PHASE_HOOKS` | PhaseHookRegistry — composable phase dispatch for MURALI. |
| `SVC_PROMPT_CONTEXT` | PromptContext — dynamic context resolvers for system prompt. |
| `SVC_PROVIDER` | ProviderChamber — multi-LLM failover. |
| `SVC_REAPER` | HeartbeatReaper — network garbage collection for federation peers. |
| `SVC_SAFETY_GUARD` | ToolSafetyGuard — Iron Dome protection. |
| `SVC_SANKALPA` | SankalpaOrchestrator — autonomous mission planning and intent generation. |
| `SVC_SIGNAL_BUS` | SignalBus — agent event communication. |
| `SVC_SIKSASTAKAM` | SiksastakamSynth — 7-beat cache lifecycle from Verse 1. |
| `SVC_SYNAPSE_STORE` | SynapseStore — persistent Hebbian weights across sessions. |
| `SVC_TASK_MANAGER` | TaskManager — persistent task tracking with priority selection. |
| `SVC_TOOL_REGISTRY` | ToolRegistry — tool lookup and execution. |
| `SVC_VENU` | VenuOrchestrator — O(1) 19-bit DIW rhythm driving execution cycle. |

### MURALI Phases
- **genesis**: Discover — run senses, scan environment → [—]
- **dharma**: Govern — check invariants, validate health → [—]
- **karma**: Execute — work on highest-priority task → [—]
- **moksha**: Reflect — persist state, log stats, learn → [—]

### Kshetra (25 tattvas)
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