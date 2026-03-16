# Steward — Agent Orientation
# This file is included verbatim in the generated CLAUDE.md.
# It is the ONLY non-dynamic section — everything else is derived from living code.
# Keep it sharp: this is what you read when you open this repo cold.

## What this is

Steward is an autonomous superagent engine built on Sankhya-25 architecture.
It executes software tasks through an LLM tool-use loop with a cognitive
pipeline modeled on 24 Vedic Prakriti elements + the LLM as 25th (Jiva/knower).

The cognitive pipeline (Antahkarana) works like this:
```
User message → Manas (perceive intent, zero LLM) → Buddhi (discriminate action)
  → Chitta (track impressions, derive phase) → Tool execution → Gandha (detect patterns)
  → Buddhi verdict → next round or complete
```

Execution phases (derived from Chitta impressions, not hardcoded rounds):
ORIENT (reading/searching) → EXECUTE (writing/editing) → VERIFY (running tests) → COMPLETE

The heartbeat (Cetana) runs a 4-phase MURALI cycle in daemon mode:
GENESIS (discover) → DHARMA (govern) → KARMA (execute) → MOKSHA (reflect)
Frequency adapts to health: 0.1Hz calm → 0.5Hz normal → 2Hz emergency.

## Key directories

- `steward/antahkarana/` — cognitive pipeline: manas, buddhi, chitta, gandha, vedana, ksetrajna
- `steward/senses/` — 5 Jnanendriyas: git, project, code, testing, health perception
- `steward/tools/` — tool implementations (bash, read, write, edit, glob, grep, think, etc.)
- `steward/hooks/` — MURALI phase hooks (genesis discovery, dharma health, moksha persistence)
- `steward/loop/engine.py` — core agent loop (LLM call → tool dispatch → repeat)
- `steward/provider/` — multi-LLM failover (ProviderChamber with circuit breakers)
- `steward/interfaces/` — telegram bot, HTTP API, agent-internet
- `data/federation/` — nadi protocol files (peer.json, inbox, outbox)

## Invariants

- `NORTH_STAR_TEXT` in services.py is a MahaCompression seed — modifying it breaks all alignment hashes
- Identity comes from `data/federation/peer.json` — never hardcode owner/org strings
- CBR (Constant Bitrate) on ALL external calls: 64 tokens/tick, floor=512, ceiling=1024
- `except: pass` is Anti-Buddhi — always log or propagate, never swallow silently
- Tools must inherit `vibe_core.tools.tool_protocol.Tool` and implement name/description/parameters_schema/validate/execute
- Safety gates: Narasimha (threat analysis on bash), Iron Dome (write protection), CBR (token quota)

## Development workflow

- `make check` runs everything: lint → security → tests
- `ruff check && ruff format` before every commit (line-length=120, py311)
- `python -m pytest tests/ -q --timeout=30` — asyncio_mode=strict
- `bandit -r steward/ -ll -q` for security
- CI runs tests on Python 3.11 + 3.12
