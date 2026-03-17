# Steward Feature Status

Honest. Updated 2026-03-17. Verified by reading code AND checking CI logs.

| Feature | Status | Evidence |
|---------|--------|----------|
| Substrate Primitives | WORKING | HebbianSynaptic, SynapseStore, MahaAttention, MahaCompression, Antaranga — all registered at boot, used by multiple services |
| KirtanLoop | WORKING | Call/Response primitive. Integration tested: call→verify→close/escalate. Persisted to kirtan_ledger.json. 2 consumers (Reaper, FixPipeline). |
| Reaper / Peer Health | WORKING | 10 peers tracked. 3-strike state machine (ALIVE→SUSPECT→DEAD→EVICTED). Trust decay. Loaded from .steward/peers.json. |
| Escalation → GitHub Issues | WORKING | escalate_problem() creates real GitHub Issues via gh CLI. Replaces needs_attention.md deadend. Fallback to local file if gh unavailable. |
| Immune System | WORKING | DharmaImmuneHook in default hooks. CytokineBreaker with 11 record_rollback() call sites. ShuddhiEngine with 17 remedies. 0 heals in production (no pathogens found yet). |
| Federation Bridge | WORKING | FederationBridge routes inbound by operation (O(1) dispatch). Heartbeat, claim, release, delegation, diagnostic handlers wired. |
| NADI Local Transport | WORKING | emit→flush→outbox verified locally. NadiFederationTransport reads inbox, writes outbox. Atomic write (tmp→rename). |
| NADI Cross-Repo Delivery | UNVERIFIED | Relay workflow (agent-internet) pumps outboxes. GitHub API Transport for remote peers. End-to-end CI delivery not yet confirmed — testing now. |
| Hub Relay (Fallback) | WORKING | GitHubFederationRelay push_to_hub/pull_from_hub via GitHub Contents API. Writes to nadi_outbox.json (shared bus). |
| Cetana Heartbeat | PARTIAL | 4-phase MURALI runs via CI cron every 15min. Adaptive frequency (SAMADHI/SADHANA/GAJENDRA) coded but not proven in production — CI restarts reset frequency state. |
| Provider Chamber | WORKING | 3 providers: Google Flash, Mistral, Groq. Prana-ordered failover. MahaCellUnified lifecycle. |
| Senses | WORKING | 5 active: git, project, code, testing, health. Perception aggregation. |
| Tools | WORKING | 17 builtin tools including bash, read/write/edit file, grep, git, http, web_search, sub_agent, delegate_to_peer, think. |
| Campaign Signals | WORKING | federation_healthy, immune_clean, ci_green, active_missions_at_most. Evaluated each GENESIS. Failing signals boost relevant intent priorities. |
| Sankalpa | WORKING | Generates typed intents (HEALTH_CHECK, CI_CHECK, FEDERATION_HEALTH etc). Campaign-driven priority adjustment. |
| AutonomyEngine | WORKING | Deterministic detection (0 tokens) → Hebbian confidence gate → LLM fix only when confident. Federated task execution with isolated workspace. |
| Circuit Breaker | WORKING | Multi-gate verification (lint, security, blast radius, test integrity, API surface, test suite). Rollback on any gate failure. |
| BrainVoice | NOT HERE | Lives in agent-city repo. Steward doesn't generate content. |
| Moltbook Integration | NOT HERE | Lives in agent-city repo. Steward doesn't post on Moltbook. |

## What "WORKING" means

Registered at boot, has test coverage, code path verified by reading source.
Does NOT mean "battle-tested in production for months." The steward heartbeat
runs every 15 minutes in CI — most features are exercised every cycle but
edge cases (actual dead peers, actual immune heals) haven't occurred yet
because the federation is young and mostly healthy.

## What's NOT here

- Content generation (agent-city)
- Moltbook posting (agent-city)
- GitHub onboarding pipeline (agent-city)
- World governance (agent-world)
- Relay pump (agent-internet)
