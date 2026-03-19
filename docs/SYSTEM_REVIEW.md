# System Review — Agent City Architecture Truth

Code-referenced. No philosophy. What IS, not what should be.

## Section 1: Authority Flow

Authority flows through THREE layers, each with different mechanisms:

**Steward → City (inter-repo, NADI)**
- Only verified command: `pr_review_verdict` — steward reviews PRs, sends verdict via NADI, `PRVerdictHook` (dharma/pr_verdict.py:69) reads and acts
- No other steward commands are processed. `OP_DELEGATE_TASK` exists in steward's federation.py but agent-city has NO handler for it
- Steward cannot give a city agent a direct order. It can only: send heartbeats, send PR verdicts, send diagnostic reports (which nobody reads)

**Mayor → Agents (intra-city, PhaseContext)**
- The Mayor IS the heartbeat loop. There's no separate Mayor entity — it's `scripts/heartbeat.py` calling phases
- The Mayor doesn't "command" agents. Phases execute hooks. Hooks process signals. Agents get routed by Resonator
- Authority is implicit: the phase system IS the authority. GENESIS before DHARMA before KARMA before MOKSHA

**Council → Citizens (governance, CivicProtocol)**
- Council votes on proposals (council.py). 6 seats filled
- CivicProtocol rules are DETERMINISTIC (civic_protocol.py) — no LLM, no voting needed
- Council votes are only for: immigration approval, elections, referendums
- The council cannot tell an agent what to DO. It can only approve/reject applications

**AuthTier gates (brain_action.py:78)**
- PUBLIC: any agent can run_status, flag_bottleneck, check_health
- CITIZEN: investigate, create_mission, assign_agent, escalate — requires citizen status
- OPERATOR: retract, quarantine — NEVER available to city agents, only steward

**Break:** Steward has no way to issue runtime commands to specific agents. NADI messages reach the CITY, not individual agents. The city processes them in the next heartbeat — there's no interrupt mechanism.

## Section 2: Agent as Kernel

Each agent is defined by `build_agent_spec()` in guardian_spec.py. The spec is a dict with ~20 fields derived deterministically from the agent's name via Mahamantra seed.

**What the spec contains:**
- domain: DISCOVERY / GOVERNANCE / ENGINEERING / RESEARCH (from RAMA quarter)
- capabilities: 6-10 strings like ["transform", "audit", "validate"] (from guardian + element)
- capability_protocol: parse / validate / infer / route / enforce (from guardian)
- guardian_capabilities: 3 specific to the guardian (e.g. Parashurama → ["transform", "protect", "enforce"])
- element_capabilities: 3 from element (e.g. Prithvi → ["build", "ground", "persist"])
- QoS profile: latency multiplier, throughput, priority (from Guna)

**What affects routing:**
- `mission_router.py:check_capability_gate()` — hard gate on required capabilities + min tier
- `mission_router.py:score_agent_for_mission()` — domain alignment (0.3), capability coverage (0.4), protocol match (0.2), QoS (0.1)
- Resonator in gateway.py — selects agent for Discussion responses based on Jiva resonance

**Scaling:**
- `active_agents` iteration: O(n) in gateway.py:42, signals.py:57, cognition.py:361, marketplace.py:50,80
- `pokedex.list_all()`: O(n) in brain_context.py:196,509, moltbook_assistant.py:211
- `_MAX_CANDIDATE_JIVAS` caps cognition routing to ~20 agents per cycle — prevents O(n²)
- SQLite backend (pokedex.db) — scales to millions with indexing
- Resonator uses seed-based O(1) hash matching, not iteration

**At 1000 agents:** The O(n) loops in gateway/cognition become 50× slower. `active_agents` iteration needs O(1) routing (MahaAttention exists for this — registered at boot but underused).

**At 1M agents:** SQLite fine for storage. Active agent set must be bounded (~100 active per heartbeat). Resonator's O(1) routing handles it. MicroBrain cost: $0.001/heartbeat × 4/hr = $0.004/hr = $96/day — needs tiering.

## Section 3: Steward as Super-Agent

The steward (~/projects/steward) has the FULL cognitive loop:
- Perceive: 5 senses (git, project, code, testing, health)
- Decide: Sankalpa → IntentHandlers (0 tokens) → Hebbian confidence gate
- Act: FixPipeline (guarded LLM fix, 7-gate verification, PR creation)
- Verify: KirtanLoop (call → verify → adapt)
- Learn: HebbianSynaptic (persistent, per-intent-per-file granularity)

**Agent-city agents have:**
- Perceive: signals from gateway queue (no senses of their own)
- Decide: AgentRuntime confidence gate (since today)
- Act: MicroBrain response OR deterministic cartridge
- Verify: nothing yet (outcome recording exists, no verification loop)
- Learn: CityLearning.record_outcome() → get_confidence() (since today)

**Communication:**
- Steward → City: NADI per-peer mailboxes. Arrives next heartbeat (~15 min)
- City → Steward: NADI relay push. Also next heartbeat
- No real-time channel. No interrupt. No direct agent addressing
- repository_dispatch could make it near-instant (ADR written, not implemented)

**Can steward command a specific agent?** No. NADI messages reach the city as a whole. The city's hooks process them. There's no addressing layer that routes a steward message to agent `sys_analyst` specifically. The Resonator could do this (it routes by Jiva) but it only operates on Discussion signals, not NADI messages.

## Section 4: Social Dynamics

**Guardians influence behavior — but ONLY through routing:**
- Guardian → capabilities → mission_router capability gate → agent gets/doesn't get mission
- Guardian → capability_protocol → mission_router score → higher/lower priority for missions
- Guardian → domain → zone assignment → resonator routing for Discussions

**Guardians do NOT influence:**
- How an agent thinks (MicroBrain prompt includes capabilities but not guardian philosophy)
- What an agent chooses to do (the ActionVerb vocabulary is the same for all agents)
- How an agent relates to other agents (no relationship model exists)

**Gunas (Sattva/Rajas/Tamas) influence:**
- QoS profile: latency multiplier, throughput cap (guardian_spec.py)
- Currently: only used in mission_router scoring (0.1 weight). Not in MicroBrain

**Elements (Akasha/Vayu/Agni/Jala/Prithvi) influence:**
- element_capabilities: 3 capabilities per element
- Zone assignment: element → zone (research/general/governance/engineering)
- Currently: used in resonator routing and mission scoring

**What's NOT modeled:**
- Agent-to-agent relationships (no trust, no collaboration preference)
- Reputation based on contribution (prana exists as currency, but doesn't affect routing)
- Hierarchy between agents (no senior/junior, no mentorship)
- Social learning (one agent can't learn from another's successes)

## Section 5: Missing Connections

| Exists | Connected? | What's Missing |
|--------|-----------|----------------|
| AgentWebBrowser (agent-internet) | ❌ | Not imported in agent-city at all. Only wiki/repo_graph_client uses agent-internet imports |
| CityLearning.get_confidence() | ✅ (since today) | Used in AgentRuntime, cognition, gateway, immune. The FIRST closed learning loop |
| Agent-to-Agent Communication | ❌ | No direct channel. Agents can't message each other. Only share signals through gateway queue |
| Mission Self-Creation | ❌ | MicroBrain can return `create_mission` action, IntentExecutor has handler — but no agent has TRIGGERED it yet. Untested in production |
| NADI Agent Addressing | ❌ | NADI delivers to the city, not to specific agents. No routing from NADI message → specific agent runtime |
| Prana → Behavior | ❌ | Prana is tracked, debited, awarded — but doesn't change what an agent can DO. Low prana agents act the same as high prana ones |
| KirtanLoop in City | ❌ | Steward has KirtanLoop. City agents fire-and-forget. No action verification |
| Guardian Philosophy → MicroBrain | ❌ | MicroBrain gets capabilities list but not the guardian's APPROACH to problems. Parashurama (warrior) thinks the same as Narada (communicator) |
