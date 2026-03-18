# Agent Runtime Design — The 6-Step Cognitive Loop

## The Problem

Agent-city has 39 agents. All of them are `cartridge.process(text)` — a
static function call that returns a dict. No perception loop. No learning.
No verification. No adaptation. The cartridge knows WHAT the agent is
(domain, capabilities, guardian). Nothing knows HOW the agent behaves.

The steward has the full loop: perceive → decide → act → verify → learn.
Agent-city agents have: receive input → return static dict.

## The Cost of Thinking

Research from OpenRouter pricing (2026-03-18):

| Model | Prompt/M tokens | Completion/M | Cost per micro-call (450 tok) |
|-------|-----------------|--------------|-------------------------------|
| liquid/lfm-2.2-6b | $0.01 | $0.02 | $0.000005 |
| mistral-nemo | $0.02 | $0.04 | $0.000011 |
| meta-llama/llama-3.1-8b | $0.02 | $0.05 | $0.000012 |
| deepseek/deepseek-v3.2 | $0.14 | $0.28 | $0.000077 |

A micro-cognition call = ~350 prompt + ~100 completion = 450 tokens.

**Budget for a living city:**
- 10 agents think per heartbeat (not all 39 — only those with tasks)
- 4 heartbeats per hour
- DeepSeek: $0.07/day. Mistral Nemo: $0.01/day.

A city where agents THINK costs less than a cent per day.

## The 6-Step Loop

```
1. PERCEIVE   What is this task? What context do I have?
              → Read the Discussion comment / Issue / NADI message
              → Optionally: open browser for external context

2. DECIDE     Can I handle this deterministically?
              → Check Hebbian confidence for this (agent, intent) pair
              → High confidence (>0.7): use deterministic handler (24 elements)
              → Low confidence or novel: invoke MicroBrain (25th element)

3. ACT        Execute the decision
              → Post a Discussion response
              → Create a Mission
              → Flag a bottleneck
              → Delegate to another agent

4. VERIFY     Did the action work?
              → Did the user ask a follow-up? (action failed to satisfy)
              → Did a mission get completed? (action led to outcome)
              → Was the response upvoted/ignored? (quality signal)

5. LEARN      Update Hebbian weights
              → Action succeeded → strengthen(agent:intent, handle)
              → Action failed → weaken(agent:intent, handle)
              → Below threshold → next time, use MicroBrain instead

6. ADAPT      Feed learning into next cycle
              → Weights change which path Step 2 takes next time
              → The agent's behavior EVOLVES based on outcomes
```

## Connecting Existing Pieces

Everything exists. Nothing is connected.

| Loop Step | Existing Code | What's Missing |
|-----------|--------------|----------------|
| PERCEIVE | `gateway.py` reads signals, `discussions_bridge.py` scans | Browser not available to agents |
| DECIDE | `attention.py` routes by fixed enum | No confidence gate (CityLearning not read) |
| ACT | `intent_executor.py` dispatches to handlers | Handlers are templates, not agent-specific |
| VERIFY | Nothing | KirtanLoop exists in steward, not in city |
| LEARN | `CityLearning` records outcomes | Nobody reads weights to change decisions |
| ADAPT | Nothing | No feedback from learning to decision |

The runtime WRAPS these into a loop. It doesn't replace them.

## AgentRuntime Class

```python
# city/agent_runtime.py

class AgentRuntime:
    """Cognitive loop for a city agent. The bridge between
    cartridge (identity) and action (behavior)."""

    def __init__(self, name: str, cartridge: object, learning: CityLearning,
                 micro_brain: MicroBrain | None = None):
        self.name = name
        self.cartridge = cartridge  # WHAT: domain, capabilities, guardian
        self.learning = learning    # HOW: Hebbian weights, outcomes
        self.micro_brain = micro_brain  # THINK: cheapest LLM for novel tasks

    def process(self, task_text: str, ctx: PhaseContext) -> dict:
        """The 6-step loop. Returns action result."""

        # 1. PERCEIVE
        perception = {
            "task": task_text,
            "agent": self.name,
            "domain": self.cartridge.domain,
            "capabilities": self.cartridge.capabilities,
        }

        # 2. DECIDE — confidence gate
        intent_key = f"{self.name}:response"
        confidence = self.learning.get_confidence(intent_key, "handle")

        if confidence > 0.7 and self.cartridge.handle:
            # Deterministic: the 24 elements
            result = self.cartridge.process(task_text)
            result["decision_mode"] = "deterministic"
        elif self.micro_brain is not None:
            # Novel or uncertain: the 25th element
            result = self.micro_brain.think(
                agent_name=self.name,
                agent_domain=self.cartridge.domain,
                task_text=task_text,
                capabilities=self.cartridge.capabilities,
            )
            result["decision_mode"] = "micro_brain"
        else:
            # No brain available: deterministic fallback
            result = self.cartridge.process(task_text)
            result["decision_mode"] = "fallback"

        return result

    def record_outcome(self, intent_key: str, success: bool) -> None:
        """Step 5+6: Learn and adapt."""
        self.learning.record_outcome(
            source=f"{self.name}:{intent_key}",
            action="handle",
            success=success,
        )
```

## MicroBrain — Per-Agent Cognition

NOT the CityBrain. The CityBrain is the shared city organ for critical
decisions (health evaluation, reflection, comprehension). It uses DeepSeek
v3.2, costs $0.077/call, and has the full city context.

MicroBrain is per-agent, per-task. Uses the cheapest available model.
Short context. One decision per call.

```python
# city/micro_brain.py

class MicroBrain:
    """Per-agent micro-cognition. ~$0.00001/call."""

    def __init__(self, model: str = "mistralai/mistral-nemo"):
        self.model = model
        self.max_tokens = 256

    def think(self, agent_name, agent_domain, task_text, capabilities):
        """One thought. One decision. Returns action dict."""
        # Uses the same OpenRouter provider as the CityBrain
        # but with a much cheaper model and tiny context
        pass
```

### When MicroBrain vs CityBrain?

| Situation | Use | Why |
|-----------|-----|-----|
| Agent responding to Discussion comment | MicroBrain | Per-agent, cheap, specific |
| City-wide health evaluation | CityBrain | Needs full city context |
| Agent taking a mission | MicroBrain | Agent-specific decision |
| End-of-cycle reflection | CityBrain | City-level insight |
| Novel situation, no precedent | MicroBrain | Agent tries, learns |
| Critical governance decision | CityBrain | High stakes, needs depth |

## Browser as Perception

`create_agent_browser()` from agent-internet gives an agent:
- HTTP page fetching with CBR compression
- GitHub source browsing (repos, files, PRs, Issues)
- llms.txt native discovery
- Control plane queries (federation routing, trust, spaces)
- NADI source (read federation messages as browseable pages)

The browser is NOT a feature. It's a SENSE. When an agent processes a
Discussion comment that contains a URL, it can FOLLOW the URL and bring
back context. When processing a federation message, it can browse the
source repo.

Integration point: `AgentRuntime.__init__` accepts an optional `browser`.
During `process()`, if the task contains a URL or references an external
resource, the runtime opens the browser. The browser page content becomes
part of the perception dict.

## Verification: Simplified KirtanLoop

The steward's KirtanLoop is heavy (persisted to disk, escalation to
GitHub Issues). For agent-city agents, verification is simpler:

- Did the user ask a follow-up in the same thread? → action didn't satisfy
- Was the response a duplicate of a previous response? → stale behavior
- Did a created mission get completed? → action led to outcome

These signals are already available in `DiscussionsBridge` (comment tracking)
and `Missions` (completion tracking). The runtime reads them in the NEXT
heartbeat and feeds them to `record_outcome()`.

## Implementation Order

1. **`city/micro_brain.py`** — MicroBrain class, cheapest model, JSON output
2. **`city/agent_runtime.py`** — AgentRuntime with 6-step loop
3. **Wire into `karma_handlers/gateway.py`** — replace `cartridge.process()` with `runtime.process()`
4. **Add outcome recording** — after Discussion responses, record success/failure
5. **Add confidence gate** — in runtime.process(), check weight before deciding
6. **Add browser** — optional, for tasks that reference external resources

Steps 1-3 are the foundation. Steps 4-5 close the loop. Step 6 expands perception.

## What Changes for a Visitor

Before: "I asked a question. I got a template response. The wiki has hash-named pages."
After: "I asked a question. sys_analyst thought about it and gave me a specific answer
based on actual immigration data. When I asked a follow-up, the response was DIFFERENT
because the agent learned that the first answer wasn't enough."

The visitor doesn't see the architecture. They see: the city RESPONDS to me
like it's paying attention. Not like a form letter. Like a place where
something is actually happening.
