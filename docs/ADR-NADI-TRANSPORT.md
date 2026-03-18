# ADR: NADI Transport Evolution

## Status: PROPOSED

## Context

Current NADI transport commits JSON files to a hub repo (steward-federation).
Three transport layers exist:

1. **Per-peer mailboxes** (current, working): `nadi/{sender}_to_{target}.json`
   - Zero merge conflicts (one writer per file)
   - ~15 min latency (waits for next heartbeat)
   - Git history bloat from message commits

2. **Legacy shared files**: `nadi_outbox.json` / `nadi_inbox.json`
   - Merge conflict risk with concurrent writers
   - Being phased out (migration period)

3. **Local filesystem transport**: Direct file read/write between local clones
   - Only works when repos are co-located (dev environment, CI checkout)

## Measured Data (2026-03-18)

- API budget: 10,000 calls/hr (5000 core + 5000 graphql, SEPARATE)
- Current usage: 172 calls/hr (1.7%)
- Per-peer mailbox cost: ~8 API calls per relay push (4 peers × GET sha + PUT)
- FEDERATION_PAT has admin access on all federation repos
- repository_dispatch: 1 API call per dispatch event

## Options Considered

### A. Per-peer mailboxes only (CURRENT)
- ✅ Zero merge conflicts
- ✅ Simple, proven, working in CI
- ❌ ~15 min latency (heartbeat cycle)
- ❌ Git history bloat (~4 commits per heartbeat from relay)
- ❌ 8 API calls per relay push
- **Cost: 32 calls/hr for steward relay alone**

### B. repository_dispatch (near-instant delivery)
- ✅ ~10 sec delivery (workflow trigger is near-instant)
- ✅ No files, no git commits, no merge conflicts, no history bloat
- ✅ Payload in API body, not in repo
- ❌ 1 API call per dispatch (but budget is 98% free)
- ❌ No persistence — if target workflow fails, message is lost
- ❌ Max 10 properties in client_payload (~65KB limit)
- ❌ Requires target repo to have a `repository_dispatch` workflow
- **Cost: 1 call per message. 28 messages/cycle = 112 calls/hr**

### C. GitHub Issues as message queue
- ✅ Persistent, searchable, visible in UI
- ✅ No merge conflicts
- ❌ Heavy — 2 API calls per message (create + label/close)
- ❌ Pollutes Issue tracker
- ❌ Slower than both A and B
- **Cost: 56 calls/hr minimum. Not recommended.**

### D. Hybrid: dispatch for urgent, mailboxes for bulk (RECOMMENDED)
- ✅ Low-latency for critical: pr_review_request, escalation, content_quality_warning
- ✅ Batch delivery for routine: heartbeats, diagnostic reports
- ✅ Mailboxes as persistence layer / retry fallback
- ✅ Graceful degradation: if dispatch fails, next mailbox cycle picks it up
- ⚠️ Two transport paths (complexity)
- **Cost: ~150 calls/hr total (mailbox bulk + dispatch urgent)**

## Decision: Option D — Hybrid Transport

Budget impact is negligible (1.5% at current scale). The latency improvement
for urgent messages (15 min → 10 sec) is significant for:
- PR review requests (external agent waiting for verdict)
- Kirtan escalations (peer health critical)
- Content quality warnings (stop spam immediately)

Routine messages (heartbeats, periodic reports) stay on mailboxes.

## Implementation Plan

### Phase 1: Add dispatch capability to steward (1 hour)

```python
# steward/nadi_dispatch.py
def dispatch_urgent(target_repo: str, operation: str, payload: dict) -> bool:
    """Send urgent NADI message via repository_dispatch."""
    # POST /repos/{owner}/{target_repo}/dispatches
    # event_type: "nadi_message"
    # client_payload: {source, operation, payload, id, timestamp}
```

### Phase 2: Add receiver workflow to federation repos (30 min each)

```yaml
# .github/workflows/nadi-receiver.yml
on:
  repository_dispatch:
    types: [nadi_message]
jobs:
  process:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          echo '${{ toJSON(github.event.client_payload) }}' > /tmp/nadi_msg.json
          python scripts/process_nadi_message.py /tmp/nadi_msg.json
```

### Phase 3: Route by urgency in MokshaFederationHook

```python
# Urgent operations → dispatch (near-instant)
URGENT_OPS = {"pr_review_request", "pr_review_verdict", "escalation",
              "content_quality_warning", "delegate_task"}

# Bulk operations → mailbox (next cycle)
BULK_OPS = {"heartbeat", "diagnostic_report", "city_report"}

for event in outbound:
    if event.operation in URGENT_OPS:
        dispatch_urgent(target_repo, event.operation, event.payload)
    # All events also go to mailbox as persistence/fallback
    transport.append_to_inbox([event.to_dict()])
```

## Consequences

- Urgent messages arrive in ~10 seconds instead of ~15 minutes
- Mailboxes remain as the source of truth / retry mechanism
- Each federation repo needs a `nadi-receiver.yml` workflow
- API budget increases by ~112 calls/hr (1.1%) — negligible
- Complexity: two delivery paths, but the routing logic is simple (op type → path)

## When to Implement

After this ADR is reviewed. No rush — the 15-min latency is acceptable
for current operations. Implement when:
1. PR Gate E2E needs faster review turnaround
2. Kirtan escalations need immediate response
3. External agents complain about immigration wait time
