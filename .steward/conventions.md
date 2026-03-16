# Steward Conventions — system invariants for agent orientation
# Each line becomes a rule in the CLAUDE.md briefing.
# Lines starting with # are comments and ignored.

- NEVER modify `NORTH_STAR_TEXT` — it is a MahaCompression seed; changing it breaks all alignment hashes
- Identity comes from `data/federation/peer.json` (nadi protocol) — no hardcoded owner/org strings
- CBR (`OperationalQuota`) on ALL external calls — API, LLM, subprocess
- `except: pass` is Anti-Buddhi — always log or propagate, never swallow silently
- Read before edit, test after change — this is the base system prompt invariant
- Federation relay pump lives in `agent-internet` repo — steward pushes nadi, relay distributes
