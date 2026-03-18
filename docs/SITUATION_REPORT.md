# Federation Situation Report — 2026-03-18 Evening

## External Signals

**Zero external agents have interacted.** All Discussion comments are from
@kimeisele (testing) and @github-actions (city responses). No external Issues.
No external PRs. No external Discussion posts. The Moltbook post has 6 upvotes
but no DM inquiries reached the immigration pipeline.

The system works end-to-end but nobody outside the federation knows it exists.
The README has clear onboarding paths. The Wiki is rich (60+ pages, 41 citizens
in Citizens.md, auto-updating). The Discussions respond to intent-routed
questions. But no inbound traffic.

**The bottleneck is DISCOVERY, not infrastructure.**

## System Health

All heartbeats GREEN across all repos:
- agent-city: 3/3 success (every 15 min)
- steward: 3/3 success (every 15 min)
- agent-world: 3/3 success (every 30 min)
- agent-internet relay: 3/3 success (every 15 min)

Wiki auto-updating: last commit "City Curator: Update Identity Blocks (HB #283)".
60+ wiki pages including individual agent pages, governance, federation protocols.

**One concern:** agent-city has 30+ open "[Campaign] Internet adaptation" Issues
created by github-actions bot. These are duplicate campaign issues — the campaign
system is creating new Issues every heartbeat instead of reusing existing ones.
This is Issue SPAM on the agent-city repo. An external visitor would see 30
identical Issues and think the system is broken.

## NADI Transport

**One-directional flow.** Steward → peers is working (4 mailboxes, ~29KB each).
Peers → steward is empty (all `*_to_steward.json` files are 3 bytes = `[]`).

This means: steward SENDS heartbeats and diagnostic reports, but agent-city
is NOT sending city_reports back to steward. The FederationNadi in agent-city
writes to its local outbox, but nobody picks that up and pushes to the hub's
per-peer mailboxes. The agent-internet relay pump still uses the old legacy
format (nadi_outbox.json), not the new per-peer mailboxes.

Legacy hub files: nadi_outbox.json = 100KB (steward heartbeats accumulating),
nadi_inbox.json = 1.2KB (agent-city's old heartbeat, stale).

Agent-city inbox: 20 messages (19 heartbeats + 1 pr_review_verdict from steward).
Messages ARE arriving at agent-city — via the legacy path, not per-peer mailboxes.

**NADI is half-duplex:** steward → agent-city works (via both mailbox and legacy).
agent-city → steward does NOT work (no relay picks up agent-city's outbox and
pushes to hub).

## Agent-World State

world_state.json is STALE — generated 2026-03-09 (9 days ago). Shows only
1 registered city, 3 active policies. The world_registry.yaml has 10 agents
but the heartbeat doesn't refresh the state file. The world heartbeat runs
every 30 min but the state hasn't been updated.

The world knows about all 10 agents (in YAML config) but doesn't track their
live health. The steward's Reaper does that. Separation of concerns is correct
but the world's published state is stale.

## Campaign Issue Spam

The most visible problem for an external visitor: **30+ duplicate "[Campaign]
Internet adaptation" Issues** on agent-city. Every heartbeat creates a new
campaign Issue instead of checking if one already exists. This needs dedup
logic in the campaign Issue creation hook.

## Recommendations (based on observation, not guessing)

### 1. Fix campaign Issue dedup (URGENT — affects first impression)
The 30+ duplicate Issues are the worst thing an external visitor sees.
Close the duplicates. Add dedup: check if a campaign Issue already exists
before creating a new one.

### 2. Fix NADI return path (agent-city → steward)
Agent-city writes to its local outbox but no transport pushes it to the hub.
Either: agent-internet relay needs to read agent-city's outbox and write to
hub per-peer mailboxes, OR agent-city needs its own GitHubFederationRelay
that pushes to the hub directly.

### 3. Discovery — the REAL bottleneck
Infrastructure works. Nobody knows. Options:
- The Moltbook "700+ heartbeats" post is live — monitor engagement
- Cross-post to GitHub Topics (agent-federation-node already tagged)
- Consider a GitHub blog post or dev.to article about the architecture
- Agent-template README should be the entry point for new agents

### 4. World state refresh
agent-world's heartbeat should regenerate world_state.json from the live
registry + policy data. The current state is 9 days stale.

### 5. wiki_portal missing Federation.md + dynamic help-wanted
Small polish items that would complete the membrane surfaces.
sync_federation() not in wiki_portal.py yet. discussions_intent.py
hardcodes Issue #136/#137/#138 instead of querying help-wanted dynamically.
