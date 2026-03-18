# GitHub API Budget Analysis

## Measured 2026-03-18 (CORRECTED — passive observation, not per-trigger)

### Rate Limits (verified via `gh api rate_limit`)
- Core REST API: 5000/hr (per-token, NOT per-repo)
- GraphQL: 5000/hr (SEPARATE budget from Core)
- Total effective: 10,000 API calls/hr
- Search: 30/min (separate, very limited)

### REAL Hourly Burn Rate (passive 15-min observation, extrapolated)

**768 calls/hr** (548 core + 220 graphql) = **7.7% of total budget**

This is 4.5× higher than the initial per-trigger measurement (172/hr)
because ALL repos run scheduled workflows that burn API calls:

| Repo | Workflow | Schedule | Est. Calls/Run |
|------|----------|----------|---------------|
| agent-city | Heartbeat | every 15min | ~30 |
| agent-city | Manifest World Wiki | hourly | ~10 |
| steward | Heartbeat | every 15min | ~35 |
| steward | Self-Heal | on push | ~5 |
| agent-internet | Relay Pump | every 15min | ~20 |
| agent-internet | Publish Wiki | hourly | ~10 |
| agent-world | World Heartbeat | every 30min | ~15 |
| steward-protocol | Scheduled Agents | every 6hr | ~20 |

**16+ workflow runs per hour.** Each burns 5-35 API calls for checkout,
gh CLI, API queries, and state commits.

### Per-Heartbeat Burn Rate (measured per individual trigger)

| Repo | Cycles | Core Calls | GraphQL | Total | Notes |
|------|--------|-----------|---------|-------|-------|
| steward | 1 cycle | 24 | 11 | 35 | Genesis discovery (10 peers), NADI relay (4 mailbox writes) |
| agent-city | 4 cycles | 7 | 1 | 8 | GhRateLimiter (30/min) + cache very effective |

### Per-Hour Usage (4 heartbeat runs each, every 15 min)

| Repo | Calls/hr | Budget Share |
|------|----------|-------------|
| steward | 140 | 1.4% |
| agent-city | 32 | 0.3% |
| **Total federation** | **172** | **1.7%** |

### Remaining Budget
- Core: 4828/5000 remaining after measurement
- GraphQL: 4906/5000 remaining
- **Headroom: 98.3%**

### What Burns the Most (by code review)

**Steward (35 calls/cycle):**
- Genesis peer discovery: ~10 calls (1 per federation repo, checking descriptor)
- NADI relay push: ~8 calls (4 per-peer mailbox × 2 API calls each: GET sha + PUT content)
- NADI relay legacy push: ~2 calls (GET + PUT nadi_outbox.json)
- PR Gate diagnostic: ~4 calls (when triggered — gh pr diff, gh run list)
- Campaign signal evaluation: ~2 calls (CI status check)

**Agent-city (8 calls/4 cycles):**
- Discussions scan: ~2 GraphQL calls (discussion list + comments)
- Issue scan: ~1 REST call (registration issues)
- Moltbook: 0 (API calls go to moltbook.com, not GitHub)
- Wiki sync: ~2 calls (wiki content GET/PUT)
- Federation NADI: ~2 calls (relay read/write)

### Scaling Projections

| Scenario | Calls/hr | Budget % | Status |
|----------|----------|----------|--------|
| Current (2 active repos) | 172 | 1.7% | ✅ Comfortable |
| 5 active repos | ~430 | 4.3% | ✅ Fine |
| 10 active repos | ~860 | 8.6% | ✅ Fine |
| 50 active repos | ~4300 | 43% | ⚠️ Need optimization |
| 100 active repos | ~8600 | 86% | 🔴 Budget exceeded |

### repository_dispatch Impact

If we add repository_dispatch for urgent NADI messages:
- ~28 messages per steward heartbeat × 4 per hour = 112 calls/hr
- Additional 1.1% of budget
- **Verdict: easily affordable** at current scale

### Existing Rate Limiters

| Repo | Limiter | Config |
|------|---------|--------|
| steward | `OperationalQuota` in genesis.py | 10 RPM, 5-min cache |
| agent-city | `GhRateLimiter` in gh_rate.py | 30/min sliding window, exponential backoff |

Both already have caching. Agent-city's is particularly effective (8 calls for 4 cycles).

### Recommendations

1. **No optimization needed now.** 1.7% usage is negligible.
2. **Monitor don't enforce.** Add API usage to heartbeat reports (already tracked by both limiters).
3. **repository_dispatch is affordable.** Can implement for urgent messages without budget concern.
4. **Scaling concern at 50+ repos.** When federation grows, steward should become budget manager (Prana Budget system). Design below.

## Prana Budget System (Design — NOT implemented)

When federation scales beyond 10 active repos:

```
Each repo gets a prana allocation per hour:
  agent-city:     2000 prana (heaviest — Discussions, Issues, Wiki, PRs)
  steward:        1500 prana (PR diagnostics, CI checks, relay)
  agent-world:     500 prana (registry sync, policy checks)
  agent-internet:  500 prana (GitHub source browsing)
  reserve:         500 prana (burst capacity)

1 prana = 1 GitHub API call. 5000 prana/hr total.
```

Steward tracks usage (reported via NADI heartbeat) and adjusts allocations.
If a repo exceeds budget, steward sends `throttle` NADI message.
The repo's rate limiter reduces call rate.

This is CBR applied to API calls — compress usage to fit budget.

**Implementation trigger:** when federation reaches 10+ active repos
OR measured usage exceeds 30% of budget.

## Where Should API Budget Policy Live?

**Answer: agent-world ALREADY owns the policy.** `config/world_policies.yaml` has:

```yaml
- id: federation_bandwidth_quota
  rule: No city may consume more than 30% of shared federation message budget within one hour.
  enforcement: world_rate_limiter
  window_s: 3600
```

The separation of concerns is:
- **agent-world**: DECLARES the policy (30% per city max)
- **steward**: ENFORCES the policy (monitors usage via NADI heartbeats, sends throttle messages)
- **Each repo**: OBEYS the policy (GhRateLimiter respects throttle messages)

This is already the correct architecture. agent-world is the legislature, steward is the executive.
The policy exists. The enforcement mechanism (steward monitoring + NADI throttle) is designed but
not yet implemented. Implementation trigger: when usage exceeds 30% of budget (currently at 7.7%).

## Agent-World Registry Status (verified 2026-03-18)

All 10 federation members are registered in `config/world_registry.yaml`:

| Agent | Role | Status | Trust |
|-------|------|--------|-------|
| agent-city | city_runtime | active | founding |
| agent-world | world_architect | active | founding |
| steward | operator | active | observed |
| steward-protocol | substrate | active | observed |
| steward-federation | transport_hub | active | observed |
| agent-internet | projection_layer | active | observed |
| agent-template | scaffolding | active | observed |
| agent-research | research_faculty | active | observed |
| steward-test | operator | active | observed |
| steward-gateway | external_gateway | inactive | untrusted |
