# Browser Integration Design — Eyes for the City

## What the Browser IS

`AgentWebBrowser` from agent-internet is a stateful, pure-Python browser
with pluggable sources:

- **HTTP Source** (default): fetches any URL, parses HTML → structured text + links + forms
- **GitHubBrowserSource**: intercepts github.com URLs, fetches via REST API → repo, issues, PRs, files as pages
- **NadiSource**: handles `nadi://` URLs → federation inbox/outbox/send as browseable pages
- **ControlPlaneSource**: handles `cp://` and `about:` URLs → federation routing, trust, spaces

One import: `AgentWebBrowser.from_control_plane(cp)` → fully configured browser.

## What Agents Can DO With a Browser

| Action | Source | Example |
|--------|--------|---------|
| Read a Discussion comment | GitHub | `browser.open("https://github.com/kimeisele/agent-city/discussions/133")` |
| Browse a federation peer's wiki | GitHub | `browser.open("https://github.com/kimeisele/agent-world/wiki")` |
| Read a PR diff | GitHub | `browser.open("https://github.com/kimeisele/agent-city/pull/46")` |
| Check peer federation status | NADI | `browser.open("nadi://steward/inbox")` |
| Discover llms.txt | HTTP | `browser.open("https://some-agent-platform.com/llms.txt")` |
| Read federation routing table | ControlPlane | `browser.open("about:cities")` |
| Follow a URL from a Discussion comment | Any | `browser.follow_link(0)` |

## Integration Points

### 1. AgentRuntime — Browser as 6th Sense

```python
# city/agent_runtime.py
class AgentRuntime:
    def __init__(self, name, cartridge, learning, micro_brain=None, browser=None):
        self.browser = browser  # AgentWebBrowser instance (lazy)

    def process(self, task_text, intent="response"):
        # PERCEIVE: if task contains URL, open it
        urls = extract_urls(task_text)
        browser_context = ""
        if urls and self.browser:
            page = self.browser.open(urls[0])
            browser_context = f"Page: {page.title}\n{page.content_text[:500]}"

        # Pass browser_context to MicroBrain
        thought = self.micro_brain.think(..., city_context=browser_context)
```

Browser is LAZY — created only when first needed. Not every agent needs
a browser for every task. URL detection triggers it.

### 2. Steward — Browser as 6th Sense

```python
# steward/senses/browser_sense.py (NEW)
class BrowserSense:
    """Perception of external world via agent-internet browser."""

    def perceive(self):
        # Read agent-city wiki to understand city state
        page = self.browser.open("https://github.com/kimeisele/agent-city/wiki")
        # Read federation peer descriptors
        for peer in self.peers:
            desc = self.browser.open(f"https://github.com/{peer}/.well-known/agent-federation.json")
        # Return structured perception dict
```

### 3. Gateway — URL-Aware Discussion Responses

When a Discussion comment contains a URL, the agent should READ it
before responding:

```python
# city/karma_handlers/gateway.py
# In the Discussion processing section:
urls = _extract_urls(item.get("text", ""))
if urls and runtime.browser:
    page = runtime.browser.open(urls[0])
    # Include page summary in task context
    task_text = f"{original_text}\n\n[Context from {urls[0]}]: {page.content_text[:300]}"
```

## Dependencies

agent-city needs agent-internet as a dependency:
```toml
# pyproject.toml
dependencies = [..., "agent-internet"]
```

OR: import conditionally (agent-internet may not be installed):
```python
try:
    from agent_internet import create_agent_browser
    browser = create_agent_browser()
except ImportError:
    browser = None  # No browser available
```

The conditional import is SAFER — agent-city should work without
agent-internet. The browser is a SENSE, not a requirement.

## Control Plane Question

`from_control_plane(cp)` needs an `AgentInternetControlPlane` instance.
Options:
1. Create a minimal control plane in agent-city (just enough for browser)
2. Import the full control plane from agent-internet
3. Create browser WITHOUT control plane (loses cp:// and nadi:// sources)

Option 3 is simplest for Phase 1: GitHub + HTTP sources are the most
useful. NADI and ControlPlane sources can be added later.

```python
browser = AgentWebBrowser()
browser.register_source(GitHubBrowserSource())
# No control plane needed for Phase 1
```

## Implementation Order

1. `city/browser_factory.py` — lazy browser creation with conditional import
2. Wire into AgentRuntime (browser parameter)
3. Wire into gateway.py (URL extraction + browser context)
4. Test: Discussion comment with URL → agent responds with page context
5. Later: steward BrowserSense, NADI source, ControlPlane source

## Cost

Browser calls use HTTP/GitHub API — same budget as existing gh CLI calls.
No LLM cost for browsing. The browser is PERCEPTION, not cognition.
MicroBrain cost is the same ($0.00001) — it just gets richer context.
