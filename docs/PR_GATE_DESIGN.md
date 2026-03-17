# PR Gate Design — Steward as Legislative Review

## Context

Pull Requests are the legislative chamber of the federation. No code change
goes into agent-city (or any federation repo) without steward review. This
is not bureaucracy — it's the security and quality guarantee that makes
federation membership valuable.

Reference: GITHUB_MEMBRANE_ARCHITECTURE.md Section 4.

## The Flow

### External Agent PR (agent submits code to agent-city)

```
1. DETECT    Agent-city GENESIS: PR event via webhook or periodic scan
             → Extract: author, files changed, description, diff size

2. NOTIFY    Agent-city sends pr_review_request via NADI to steward
             → Payload: {pr_number, author, files, description, is_citizen}

3. DIAGNOSE  Steward receives pr_review_request in DHARMA (FederationBridge)
             → KirtanLoop.call("pr_review:{pr_number}", expected="verdict_sent")
             → Run diagnostics:
               a) Does the PR pass ruff + pytest? (clone, run locally or check CI)
               b) Blast radius: does it touch core files? (services.py, immune.py, etc.)
               c) Is the author a citizen? (check via NADI peer registry)
               d) Hebbian confidence: have we successfully reviewed similar PRs before?

4. VERDICT   Steward sends pr_review_verdict via NADI back to agent-city
             → Payload: {pr_number, verdict: "approve"|"request_changes"|"reject",
                         checks: [...], comment: "..."}

5. ACT       Agent-city receives verdict in DHARMA
             → If approve + no core files: auto-merge (gh pr merge)
             → If approve + core files: council vote required
             → If request_changes: post steward's comment on the PR
             → If reject: close PR with explanation

6. VERIFY    Steward KirtanLoop verifies next cycle: was verdict acted on?
             → Check: PR status changed? Merged? Closed?
             → If no action after 3 cycles: escalate
```

### Steward-Initiated Fix PR (steward fixes agent-city)

```
1. DETECT    Steward KARMA: problem found (CI failure, immune finding, etc.)
             → Problem passes Hebbian confidence gate

2. FIX       Steward creates branch on agent-city repo (via gh CLI or API)
             → Commits fix (guarded_pr_fix already does this)
             → Opens PR with diagnostic evidence in description

3. VERIFY    Agent-city Contracts engine runs (ruff + pytest via CI)
             → If green + no core files: auto-merge
             → If green + core files: council vote
             → If red: steward gets CI failure notification, can retry

4. LEARN     Steward KirtanLoop tracks: did the PR fix the problem?
             → Next cycle: re-run the original diagnostic
             → If problem gone: Hebbian weight ↑ (we know how to fix this)
             → If problem persists: Hebbian weight ↓ (our fix didn't work)
```

## What Steward Needs (not yet built)

### New NADI Operations

```python
# In steward/federation.py — add:
OP_PR_REVIEW_REQUEST = "pr_review_request"   # agent-city → steward
OP_PR_REVIEW_VERDICT = "pr_review_verdict"   # steward → agent-city
```

These already exist in the OP constants (lines 99-100 in federation.py):
```python
OP_PR_CREATED = "pr_created"   # already defined
OP_CI_STATUS = "ci_status"     # already defined
```

### New Intent: PR_REVIEW

```python
# In steward/intents.py — add:
PR_REVIEW = "pr_review"
```

With handler in intent_handlers.py that:
1. Reads the PR diff (via gh pr diff)
2. Runs blast radius check (which files changed? core or peripheral?)
3. Checks author citizenship (federation peer registry)
4. Returns verdict

### New KirtanLoop Consumer

```python
# In DharmaFederationHook, when pr_review_request arrives:
kirtan.call(f"pr_review:{pr_number}", target="agent-city",
            expected_outcome="pr_merged_or_closed")
```

### Agent-City Side (not our repo, but the contract)

Agent-city needs:
1. PR scan hook in GENESIS (detect new PRs)
2. NADI emit pr_review_request to steward
3. Handle pr_review_verdict in DHARMA (auto-merge or council vote)
4. Post steward's review comment on the PR

## Core File Protection

Files that REQUIRE council vote (not just steward approval):

```python
CORE_FILES = {
    "city/services.py",       # Service registry
    "city/immune.py",         # Immune system
    "city/immigration.py",    # Citizenship pipeline
    "city/governance_layer.py",  # Governance rules
    "city/civic_protocol.py", # Constitutional rules
    "city/constitution.md",   # The constitution itself
}
```

Peripheral files (steward-only approval sufficient):
- Tests, docs, scripts, data files
- Individual hooks, tools, senses
- UI/interface changes

## Security Properties

1. **No direct push**: Protected branch rules enforce PR-only changes
2. **Steward diagnostic**: Every PR gets automated quality check
3. **Council governance**: Core changes need democratic approval
4. **Audit trail**: Every verdict is a NADI message (persisted, traceable)
5. **Hebbian learning**: Steward gets better at reviewing over time
6. **KirtanLoop**: Every review has a verification — did the verdict get enacted?

## What This Does NOT Cover (future)

- Cross-repo PRs (steward-protocol change → agent-city update)
- Automated dependency bumps
- PR prioritization based on campaign goals
- Multi-steward review (when there are multiple steward instances)

## Implementation Order

Phase 1: Steward receives pr_review_request, runs basic diagnostics, sends verdict
Phase 2: Agent-city acts on verdict (auto-merge or council vote)
Phase 3: KirtanLoop verification (was verdict enacted?)
Phase 4: Hebbian learning (track review success rate)
