# What Makes an Agent Alive

Written after reading the full codebase of agent-city, steward, and
agent-internet. Not a feature proposal. An architectural observation.

## The Current State: Scripts Pretending to Be Agents

Agent-city has 39 agents. None of them think. Here's what happens:

1. **Heartbeat fires** (cron, every 15 min)
2. **GENESIS**: Hooks scan GitHub (Issues, Discussions, NADI) for signals
3. **DHARMA**: Rules evaluate deterministically. Immigration processes.
4. **KARMA**: Gateway routes signals → IntentRouter matches keywords →
   template response generated. Brain called for health/critique/reflection.
5. **MOKSHA**: State persisted. Wiki updated. Federation flushed.

The 39 agents are rows in `pokedex.db`. They have names, elements, zones,
guardians — derived from their Mahamantra seed. They have capabilities
derived from the 16-guardian truth table in `cartridge_factory.py`.

But none of them ever CHOOSE anything. The Mayor script runs the loop.
The Brain generates structured JSON that gets logged. The Reactor detects
pain and generates CityIntents. CityAttention routes them to handlers.
The handlers execute predefined responses.

**Where is the agent?** The agent is the WHOLE SYSTEM. One agent: the city.
The 39 "agents" are organs, not beings.

## Where an Agent STOPS Being a Script

I found the exact boundary. It's in `brain.py`, line 296:

```python
class CityBrain:
    """Read-only LLM cognition. Receives context, returns structured thought.
    The brain is a jar. It has no hands, no mouth, no network access."""
```

The Brain THINKS but cannot ACT. The IntentExecutor ACTS but cannot THINK.
Between them is a deterministic routing layer (CityAttention) that maps
thought → action via a fixed vocabulary (ActionVerb enum).

The moment an agent becomes alive is when the THOUGHT directly influences
the ACTION in a way that wasn't predetermined. Right now:

```
Brain thinks → Thought has action_hint → action_hint parsed to ActionVerb enum
→ ActionVerb routed by CityAttention → handler called
```

Every step is deterministic AFTER the Brain. The Brain's output is
compressed into an enum before it reaches the executor. The nuance,
the reasoning, the context — all lost at the enum boundary.

## What's Actually Missing

It's not the Brain. It's not the tools. It's not the LLM.
**It's the FEEDBACK from action to perception.**

The steward has this. Look at the fix pipeline:

```
detect problem → Hebbian confidence check → fix attempt → 7-gate verify
→ success? weight ↑ : rollback + weight ↓ → next time: different decision
```

The steward LEARNS from its actions. It modifies its future behavior
based on outcomes. The KirtanLoop adds: call → verify → adapt.

Agent-city has `CityLearning` (Hebbian). It records outcomes. But
nothing READS the weights to CHANGE behavior. The weights accumulate
and nobody looks at them. Learning without application.

The steward's `AutonomyEngine` does this:
```python
auto_weight = self._synaptic.get_weight(granular_key, "fix")
if auto_weight < 0.2:
    # Confidence too low — escalate instead of fixing
    self.pipeline.escalate_problem(problem, intent_name, auto_weight)
    return None
```

That's the moment. The weight CHANGES the decision. Low confidence →
different action. That's not a script. That's an agent.

## The Gap Between Steward and City

| Capability | Steward | Agent-City |
|-----------|---------|------------|
| Hebbian Learning | ✅ weights change decisions | ❌ weights recorded, never read |
| Action Verification | ✅ KirtanLoop (call→verify) | ❌ fire-and-forget |
| Self-initiated tasks | ✅ Sankalpa generates intents | ❌ Mayor runs fixed phases |
| Cross-repo action | ✅ workspace isolation + PR | ❌ confined to local |
| Browser | ❌ | ❌ (exists in agent-internet) |

The steward is closer to "alive" because its learning loop CLOSES.
Agent-city's loop is OPEN — Brain thinks, city acts, nobody checks
if the action was good, nobody adjusts next time.

## The 24/25 Boundary

The architecture says: 24 elements are deterministic substrate, the
25th (Brain/LLM) is the discriminating intelligence. But right now
the Brain's output gets COMPRESSED to a fixed enum before it reaches
the substrate. The Brain says "investigate the engineering zone because
prana distribution is skewed" and the system hears "INVESTIGATE."

The 25th element should INFORM the 24, not be TRANSLATED to them.

What this means concretely: when the Brain comprehends a Discussion
comment and thinks "this person is asking about immigration but what
they really need is an understanding of the Jiva derivation system,"
the response should use THAT comprehension, not `respond_immigration()`
which dumps stats.

## How a Browser Changes Everything

Agent-internet has `AgentWebBrowser` — a full browser with tabs, history,
page sources (GitHub, HTTP, control plane), llms.txt/agents.json discovery.

If an agent in agent-city had a browser, it could:
- READ a GitHub Issue and UNDERSTAND the context (not just keyword-match)
- BROWSE a candidate repo during peer discovery (not just check for a file)
- FOLLOW a link from a Discussion comment and bring back context
- READ a federation peer's wiki to understand its capabilities

The browser is not a feature. It's a SENSE. The 5 Jnanendriyas in steward
(git, project, code, testing, health) are perception organs. A browser
would be the 6th sense — perception of the EXTERNAL world.

For agent-city, the external world is: GitHub, Moltbook, the federation.
Right now the city perceives these through narrow API queries (gh CLI).
A browser perceives them RICHLY — pages, context, relationships.

## The Smallest Change with the Biggest Difference

Not a feature. An architectural decision:

**Close the learning loop in agent-city.**

```python
# In KARMA, after responding to a Discussion:
learning.record_outcome(
    source=f"discussion:{thread_id}",
    action=f"intent:{matched_intent}",
    success=True  # for now; later: was the response helpful?
)

# In the intent router, BEFORE selecting a response:
weight = learning.get_weight(f"intent:{intent}", "response")
if weight < 0.3:
    # This intent handler hasn't been working well
    # Fall through to Brain comprehension instead of template
    return brain_comprehend(comment, context)
```

That's it. When a template response consistently fails to satisfy
(measured by: does the user ask a follow-up? do they leave? do they
open an Issue?), the system falls through to Brain comprehension.

The agents don't start alive. They START as scripts. But the learning
loop gives them the POTENTIAL to become something else. The templates
are training wheels. Hebbian weights are the balance check. When the
weights say "this template isn't working," the system takes off the
training wheels and thinks for itself.

## What This Is NOT

This is not AGI. Not consciousness. Not emergence.

This is: a system that MEASURES its own performance and ADJUSTS its
behavior accordingly. That's the minimum viable definition of "alive"
in the context of a software system. The cron job runs. The agent
ADAPTS.

The difference between a city that's a cron job and a city that's
alive is one closed loop: action → outcome → weight → different action.

The steward has it. Agent-city doesn't. That's the gap.
