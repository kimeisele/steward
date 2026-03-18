# Plan: Federation Context + Agent-Internet + Pilot Mode

## Problem

Die Federation wird zu komplex um sie manuell zu managen. Drei Dinge fehlen:

1. **Substrat ist dumm bei Federation-Kontext** — das LLM bekommt entweder nichts oder einen Raw-Dump. Das Substrat muss deterministisch (zero LLM) selektieren was relevant ist.
2. **Agent-Internet Tool exposed nur 3 Actions** — der Browser ist gebaut, die HTTP-Client-Funktionen existieren alle in `interfaces/agent_internet.py`, aber das Tool (`tools/agent_internet.py`) bietet nur `capabilities`, `contracts`, `call` an. Die bereits implementierten Funktionen `fetch_repo_graph_snapshot`, `fetch_repo_graph_neighbors`, `fetch_repo_graph_context`, `search_index`, `search_federated_index`, `fetch_public_graph` sind unsichtbar fürs LLM.
3. **Kein Pilot Mode** — ein externer Controller (Claude Code) kann Steward nicht fernsteuern.

## Prinzip

80% Substrat, 20% LLM. LLM-Kontext wird NICHT aufgeblasen. Das Substrat wird schlauer.

---

## Workstream 1: Agent-Internet Tool erweitern (Bestehendes exponieren)

**Was existiert:** `interfaces/agent_internet.py` hat bereits:
- `fetch_repo_graph_snapshot(root, node_type, domain, query, limit)`
- `fetch_repo_graph_neighbors(root, node_id, relation, depth, limit)`
- `fetch_repo_graph_context(root, concept)`
- `fetch_public_graph(root, city_id, assistant_id, heartbeat_source)`
- `search_index(root, query, limit, ...)`
- `search_federated_index(query, limit, index_path, ...)`

**Was fehlt:** Das Tool `tools/agent_internet.py` hat nur `_ACTION_DISPATCH` mit 3 Einträgen.

**Änderungen:**

Datei: `steward/tools/agent_internet.py`
- 6 neue Handler-Funktionen (je ~5 Zeilen, delegieren an existierende Client-Funktionen)
- `_ACTION_DISPATCH` erweitern um: `repo_graph`, `repo_neighbors`, `repo_context`, `browse`, `web_search`, `federated_search`
- `parameters_schema` erweitern: `root`, `node_id`, `query`, `concept`, `limit`
- `validate()` erweitern für neue Actions

Keine neuen Dateien. Kein neuer Code im HTTP-Client. Nur das Tool wird an die existierende API angeschlossen.

---

## Workstream 2: Pilot Mode CLI (Power Ranger)

**Protokoll:** NDJSON über stdin/stdout. Kein HTTP, keine Dependencies.

Controller → Steward (stdin):
```json
{"type": "task", "content": "Fix the bug in main.py"}
{"type": "tool_call", "tool": "read_file", "params": {"path": "main.py"}}
{"type": "state", "query": "vedana"}
{"type": "discover"}
{"type": "reset"}
{"type": "exit"}
```

Steward → Controller (stdout):
```json
{"type": "ready"}
{"type": "tool_result", "success": true, "output": "...", "call_id": "..."}
{"type": "text_delta", "content": "..."}
{"type": "done", "usage": {...}}
{"type": "error", "content": "..."}
```

**Key: `tool_call` umgeht das LLM.** Der externe Controller nutzt Stewards Tools direkt — durch alle Safety Gates (Narasimha + Iron Dome). Das LLM wird nur bei `task` gebraucht.

**Änderungen:**

Neue Datei: `steward/interfaces/pilot.py`
- `PilotInterface(agent: StewardAgent)` mit O(1) dispatch table
- `async run()` — liest stdin, dispatched, schreibt stdout
- Tool-Calls: MahaAttention routing → Narasimha check → Iron Dome → execute
- Provider optional (wie `--autonomous` mode)

Datei: `steward/__main__.py`
- `--pilot` Flag (Pattern wie `--telegram`, `--api`, `--autonomous`)

---

## Workstream 3: Deterministische Federation-Kontext-Selektion

**Problem:** Wenn das LLM Federation-Kontext braucht, kriegt es entweder nichts oder muss alles laden.

**Lösung:** `FederationDigest` — ein reines Substrat-Modul (zero LLM) das MahaCompression nutzt um per Seed-Distance nur relevante Peers/Claims/Delegations zu selektieren.

**Änderungen:**

Neue Datei: `steward/federation_digest.py`
- Input: task_seed (int), Reaper, Marketplace, Bridge
- Logik: XOR-Distance zwischen task_seed und peer fingerprints → top-3 relevante Peers
- Output: ~200 Token String für den System-Prompt

Datei: `steward/agent.py` (run_stream, Zeilen 384-408)
- Federation digest als `context_parts` einfügen (Pattern wie `sense_context`, `gap_context`, `ledger_context`)

---

## Reihenfolge

1. Workstream 1 (agent-internet) — rein additiv, nur Tool erweitern
2. Workstream 2 (pilot mode) — neue Dateien, minimale Änderungen an bestehenden
3. Workstream 3 (federation digest) — baut auf 1+2 auf

## Tests

- `test_agent_internet_browse.py` — mock HTTP, teste neue Actions
- `test_pilot_interface.py` — stdin/stdout Simulation
- `test_federation_digest.py` — pure Functions, kein I/O
