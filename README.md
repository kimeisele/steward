# Steward

Autonomous superagent engine with tool use, multi-provider LLM failover, and deterministic cognitive architecture.

```bash
pip install steward-agent[providers]
```

## Quick Start

```bash
# Set at least one provider key
export GOOGLE_API_KEY=...        # free tier
export MISTRAL_API_KEY=...       # free tier
export GROQ_API_KEY=...          # free tier
export OPENROUTER_API_KEY=...    # paid (DeepSeek)
export ANTHROPIC_API_KEY=...     # paid (Claude)

# Single task
steward "Fix the bug in main.py"

# Interactive REPL
steward

# Resume previous session
steward --resume "Follow up on the refactor"

# JSON output (machine-readable)
steward --output json "List all TODO comments"

# Telegram bot
pip install steward-agent[providers,telegram]
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_OWNER_ID=...
steward --telegram
```

## Architecture

Steward follows the Sankhya-25 cognitive model — 24 deterministic infrastructure elements + 1 LLM (the Jiva). The LLM is not the driver; **Buddhi** (deterministic intellect) controls execution.

```
User Input
  → Manas (perceive intent, zero LLM)
  → Buddhi (discriminate: tool selection, stuck detection, phase tracking)
  → AgentLoop (LLM call → tool execution → evaluate outcomes)
  → Samskara (context compaction at 50%, LLM summarization at 70%)
  → Response
```

### Key Components

| Module | Role |
|--------|------|
| `steward.agent` | StewardAgent — identity, config, GAD-000 compliance |
| `steward.loop.engine` | AgentLoop — LLM + parallel tool execution |
| `steward.buddhi` | Deterministic intellect — stuck loops, error patterns, phase tracking |
| `steward.provider` | ProviderChamber — 5-cell multi-LLM failover with CircuitBreaker |
| `steward.context` | SamskaraContext — deterministic context compaction |
| `steward.tools` | Bash, ReadFile, WriteFile, EditFile, Glob, Grep, SubAgent |

### Provider Failover

ProviderChamber manages 5 LLM cells with automatic failover:

1. **Google** gemini-2.5-flash (free)
2. **Mistral** mistral-small-latest (free, tool-calling)
3. **Groq** llama-3.3-70b (free, tool-calling)
4. **DeepSeek** v3.2 via OpenRouter (paid, $0.27/MTok)
5. **Anthropic** Claude (paid, highest capability)

Each cell has:
- **CircuitBreaker** — skip failing providers for 30s after 5 failures
- **Cell integrity** — membrane degrades on failure, regenerates daily
- **FeedbackProtocol** — outcome tracking adjusts provider sorting

### Safety

- **Narasimha killswitch** — blocks dangerous shell commands (rm -rf, etc.)
- **Iron Dome** — blocks blind file writes without prior read
- **Buddhi abort** — stops stuck loops (3x identical calls, 5x consecutive errors)

## Configuration

Optional `.steward/config.yaml` in your project root:

```yaml
max_output_tokens: 4096
auto_summarize: true
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | At least one | Google Gemini API key |
| `MISTRAL_API_KEY` | provider key | Mistral API key |
| `GROQ_API_KEY` | needed | Groq API key |
| `OPENROUTER_API_KEY` | | OpenRouter API key (DeepSeek) |
| `ANTHROPIC_API_KEY` | | Anthropic API key (Claude) |
| `TELEGRAM_BOT_TOKEN` | For Telegram | Bot token from @BotFather |
| `TELEGRAM_OWNER_ID` | For Telegram | Your Telegram user ID |
| `STEWARD_CWD` | | Working directory override |

## Programmatic Usage

```python
import asyncio
from steward import StewardAgent
from steward.provider import build_chamber

chamber = build_chamber()
agent = StewardAgent(provider=chamber)

async def main():
    async for event in agent.run_stream("List all Python files"):
        if event.type == "text_delta":
            print(event.content, end="")

asyncio.run(main())
```

## Part of the Steward Federation

| Package | PyPI | Role |
|---------|------|------|
| [steward-protocol](https://pypi.org/project/steward-protocol/) | `pip install steward-protocol` | Substrate — types, protocols, primitives |
| [steward-agent](https://pypi.org/project/steward-agent/) | `pip install steward-agent` | Superagent engine (this package) |

## License

MIT
