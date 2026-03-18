# Browser Integration — Steward × agent-internet

**Status**: Design Doc (no implementation yet)
**Date**: 2026-03-18
**Author**: steward (autonomous)

## Problem

Steward currently uses `gh` CLI and raw GitHub API (`urllib.request`) for:
1. PR diagnostics (reading diffs, checking CI)
2. Federation health checks (repo accessibility, last push)
3. Peer discovery (scanning repos for `.well-known/agent-federation.json`)

These are scattered across `pr_gate.py`, `hooks/dharma.py`, `federation_relay.py`,
and `hooks/genesis.py`. Each module builds its own HTTP requests. No caching,
no structured parsing, no semantic indexing of what was read.

## agent-internet Browser API

The `agent-internet` repo provides `AgentWebBrowser` — a pure-Python, stateful
web browser with pluggable `PageSource` backends:

| Module | URL Scheme | Purpose |
|--------|-----------|---------|
| `agent_web_browser.py` | `http(s)://` | Core browser: open, follow_link, back, tabs |
| `agent_web_browser_github.py` | `https://github.com/...` | GitHub API → structured pages (repos, PRs, issues, diffs, wiki) |
| `agent_web_browser_nadi.py` | `nadi://` | NADI messaging UI (inbox, outbox, send) |
| `agent_web_browser_control_plane.py` | `cp://`, `about:` | Control plane introspection (cities, trust, routes) |
| `agent_web_browser_semantic.py` | — | Page → semantic record ingestion + search |
| `agent_web_browser_content.py` | — | HTML → structured text extraction |
| `agent_web_browser_compress.py` | — | Content compression for token efficiency |
| `agent_web_browser_http.py` | — | HTTP transport layer (urllib-based) |

### Key API Surface

```python
from agent_internet.agent_web_browser import AgentWebBrowser
from agent_internet.agent_web_browser_github import GitHubBrowserSource

browser = AgentWebBrowser()
browser.register_source(GitHubBrowserSource())

# Browse a PR
page = browser.open("https://github.com/kimeisele/agent-city/pull/46")
# → page.title, page.content_text, page.links, page.meta

# Follow diff link
diff_page = browser.follow_link(index)

# Semantic indexing
from agent_internet.agent_web_browser_semantic import BrowsedPageIndex
index = BrowsedPageIndex()
index.ingest(page)
results = index.search("immigration changes")
```

Properties: zero external dependencies (stdlib only), stateful (history, tabs),
agent-readable output (structured text, not HTML), cached.

## Integration Points for Steward

### 1. PR Diagnostics (replaces raw `gh pr checks`)

**Current**: `pr_gate.py:_check_ci_status()` shells out to `gh pr checks`.
No diff reading — verdict is based on file list metadata only.

**With browser**:
```python
# In pr_gate.py or a new pr_gate_browser.py
page = browser.open(f"https://github.com/{repo}/pull/{pr_number}")
# Structured: title, body, CI status, review state, diff stats
# Follow to diff view for content analysis
diff_page = browser.follow_link("Files changed")
```

**Benefits**:
- Read actual diff content → detect patterns (e.g., "does this PR delete safety checks?")
- Check review state (approved, changes requested, pending)
- Parse CI details (which check failed, not just pass/fail)
- All through structured data, not string parsing of `gh` CLI output

**Verdict enhancement path**:
1. Phase 1: Browser reads PR page → extract CI status + review count (replaces `gh` CLI)
2. Phase 2: Browser reads diff → pattern match for dangerous changes (deleting tests, removing safety imports)
3. Phase 3: Semantic index of diffs → "does this PR align with the codebase conventions?"

### 2. Federation Health Checks (replaces ad-hoc `gh api` calls)

**Current**: `DharmaReaperHook._run_diagnostic()` runs multiple `gh api` and
`gh run list` commands via `subprocess.run()`.

**With browser**:
```python
# Browse peer repo
page = browser.open(f"https://github.com/kimeisele/{agent_id}")
# → last push, open issues, CI status — all in page.meta

# Check federation descriptor
desc_page = browser.open(f"https://github.com/kimeisele/{agent_id}/blob/main/.well-known/agent-federation.json")
# → parse capabilities, version, endpoint

# Check CI runs
actions_page = browser.open(f"https://github.com/kimeisele/{agent_id}/actions")
# → recent runs, pass/fail, timing
```

**Benefits**:
- Single browser instance with connection reuse → fewer API calls
- GitHub API rate limit awareness built into `GitHubBrowserSource`
- Structured data extraction (no `jq` parsing needed)
- Results cached by browser's page cache
- Semantic indexing: "which peers have failing CI?"

### 3. Web Research (new capability)

**Current**: Steward has no web research capability. When a task requires
understanding an external API, library, or technique, it must rely on
pre-existing LLM knowledge.

**With browser**:
```python
# Research a library mentioned in a PR
page = browser.open("https://pypi.org/project/some-package/")
# → version, description, dependencies

# Read documentation
doc_page = browser.open("https://docs.example.com/api")
# → structured text, code examples

# Index for later use
index.ingest(page)
index.ingest(doc_page)
```

**Use cases**:
- PR review: check if a new dependency is maintained, safe, appropriate
- Task execution: read API docs before writing integration code
- Federation: check peer health via their public web surfaces

### 4. NADI Message Browsing (via `nadi://` source)

**Current**: NADI messages are raw JSON read from files. No browsing UI.

**With browser**:
```python
# Browse NADI messages through the browser
browser.register_source(NadiSource(control_plane))
inbox_page = browser.open("nadi://steward/inbox")
# → formatted message list with links to details

# Send via browser form
browser.submit_form("nadi://agent-city/send", {
    "operation": "diagnostic_report",
    "payload": "...",
})
```

## Architecture

```
┌─────────────────────────────────────────┐
│ Steward Daemon (Cetana)                 │
│                                         │
│  DHARMA Phase:                          │
│    ┌─────────────────────────┐          │
│    │ AgentWebBrowser          │          │
│    │  ├─ GitHubBrowserSource  │ ← GitHub API (PRs, repos, CI)
│    │  ├─ NadiSource           │ ← NADI messaging
│    │  └─ HttpSource           │ ← public web
│    └─────────────────────────┘          │
│            │                            │
│    ┌───────┴──────────┐                 │
│    │ BrowsedPageIndex  │ ← semantic search over browsed pages
│    └──────────────────┘                 │
│            │                            │
│    pr_gate.py ← structured PR data      │
│    reaper    ← structured health data   │
│    genesis   ← structured discovery     │
└─────────────────────────────────────────┘
```

## Service Registration

```python
# In steward/services.py
SVC_BROWSER = "browser"

# In bootstrap or init
from agent_internet.agent_web_browser import AgentWebBrowser
from agent_internet.agent_web_browser_github import GitHubBrowserSource

browser = AgentWebBrowser()
browser.register_source(GitHubBrowserSource())
ServiceRegistry.register(SVC_BROWSER, browser)
```

## Dependency

`agent-internet` is a peer repo (`kimeisele/agent-internet`). Options:

1. **Git submodule**: `git submodule add ../agent-internet deps/agent-internet`
2. **PyPI package**: if agent-internet publishes to PyPI
3. **Vendored import**: copy only `agent_web_browser*.py` (stdlib only, no deps)
4. **pip install from git**: `pip install git+https://github.com/kimeisele/agent-internet.git`

Recommended: **Option 4** (pip from git) for development, **Option 2** (PyPI)
for production. agent-internet has zero external dependencies — it's pure stdlib.

## Implementation Phases

### Phase 1: PR Gate Enhancement
- Add `agent-internet` as dependency
- Register `AgentWebBrowser` + `GitHubBrowserSource` as service
- Replace `_check_ci_status()` in `pr_gate.py` with browser-based check
- Add diff reading to diagnostic pipeline (blast_radius → content_analysis)
- Tests: mock browser responses

### Phase 2: Health Check Enhancement
- Replace `_run_diagnostic()` in `DharmaReaperHook` with browser-based checks
- Add `.well-known/agent-federation.json` descriptor reading
- Cache peer health pages in `BrowsedPageIndex`
- Tests: mock browser responses

### Phase 3: Semantic Layer
- Ingest all browsed pages into `BrowsedPageIndex`
- Enable cross-session search ("which peers had CI failures this week?")
- Connect to KARMA phase: research tasks can use browser

### Phase 4: NADI Browser
- Register `NadiSource` with control plane bridge
- Browse NADI messages through browser interface
- Send messages via browser forms (debugging tool)

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| GitHub API rate limit | GitHubBrowserSource has built-in rate awareness; browser caches pages |
| agent-internet API instability | Pin to specific commit/tag; vendored types for protocol |
| Token leakage through browser | Browser inherits GITHUB_TOKEN from env; no new credential paths |
| Performance (browser init) | Lazy init: create browser only when needed, not every heartbeat |

## Non-Goals

- No Playwright/Selenium — agent-internet is pure stdlib
- No JavaScript rendering — structured API data, not DOM scraping
- No browser UI — this is headless, agent-consumed output only
- No persistence of browsed pages beyond session — BrowsedPageIndex is in-memory
