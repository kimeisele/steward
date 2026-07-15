# FEATURE 01 / SCHNITT B — IMPLEMENTIERUNGS- UND PRODUKTIONSBEWEIS

> **Status:** SCHNITT B ABGESCHLOSSEN — OFFLINE-CONTRACT UND RENDERER VERIFIZIERT
> **Datum:** 2026-07-15
> **G2-Preflight:** `specs/context_bridge_evidence/FEATURE_01_SLICE_B_G2_PREFLIGHT.md`
> **Preflight-PR / Merge:** `#541` / `9347f21f9e1a15e5cfd049c562e4db24957a2cac`
> **Implementierungs-PR / Merge:** `#547` / `a750e0f3826e0067656062e02c3b7c896db35cde`
> **Verifizierter Folge-Head:** `38f361318b39864628dca1329bc513475fec1c04`

## 1. Gelieferter Scope

Produktcode:

```text
steward/context_contract.py
steward/context_rendering.py
```

Tests:

```text
tests/test_context_contract.py
tests/test_context_rendering.py
```

Der First-Parent-Diff des Mergecommits enthält exakt diese vier Pfade. Root-Dateien,
`.steward/**`, Workflows, Feature-Specs und andere Produktcaller waren nicht Teil des PRs.

## 2. Commit-Kette und Red-First-Beweis

Die finale PR-Kette lautete:

```text
97ed714c test: define offline context rendering contract
fd275b25 feat: build offline context publication candidates
aa105993 test: scope renderer purity guards
```

Vor Produktcode scheiterten die neuen Tests an den fehlenden öffentlichen Validatoren und
dem fehlenden Modul `steward.context_rendering`. Der dritte Commit korrigierte
ausschließlich die Lebensdauer eines Test-Monkeypatchs; Produktcode änderte er nicht.

## 3. Wirkungsvertrag

- `validate_payload_core()` validiert materialisierte Feature-04-Payloads rekursiv und
  fail-closed.
- `validate_snapshot_model()` validiert materialisierte Snapshots einschließlich fester
  Source-/Trust-/Mode-Bindungen und erforderlicher Beobachtungszeit erfolgreicher
  Live-/Derived-Sources.
- `PublicationCandidates` ist frozen und enthält vier Bytes-Felder.
- `build_publication_candidates()` liest weder Filesystem, Uhr, Git, Netzwerk,
  Environment noch Registry.
- `CLAUDE.md`- und `AGENTS.md`-Kandidat referenzieren exakt dasselbe Bytes-Objekt.
- Preview-Payloads und Cross-Binding-Drift blockieren.
- Snapshot- und Publication-Envelopes sind kanonisch, domain-separiert und frei von
  Selbsthash-Zirkulation.
- Kein bestehender Produktcaller importiert oder ruft den Renderer auf.

## 4. Golden- und Testbeweis

Reproduzierte Goldenwerte:

```text
Root bytes:                 2318
Consumer output hash:       9519cfc5867580d041ef7d01c6007a35e7d98b51d559c08b6b941940fcbb6e9d
Snapshot artifact bytes:    4781
Snapshot artifact hash:     fb6320ea4e8dd3d2fd8c009d920396c9e5db73aa4403027b5fae2ca3d3719ac3
Publication artifact bytes: 1203
Payload hash:               d3a344af1700b88346695e13833ec5d6f81b66584ef8272542c64f7d4aa4d71a
Snapshot hash:              999ba49ddaea6300f3398159103491915a9b5ce3b7871a9cbd2f7b20b761ceba
```

Validierung:

- 78 gezielte Contract-/Renderer-Tests grün,
- gezielter Ruff-Format- und Lintcheck grün,
- Bandit für beide Produktmodule grün,
- lokale Vollsuite: 2.221 passed, 13 skipped und ein umgebungsabhängiger GitSense-Fehler,
- derselbe GitSense-Test nach Wiederherstellung zweier während der Suite veränderter
  State-Dateien und normalem Rebase isoliert grün,
- CI Python 3.11 und Python 3.12 grün,
- CI Lint und Security Scan grün,
- `git diff --check` grün.

Der erste CI-Lauf fand einen echten Testharness-Fehler: `time.time` war global bis zum
Pytest-Fixture-Teardown gepatcht, sodass Pytest selbst den verbotenen Clock-Stub traf. Der
Patch wurde mit `monkeypatch.context()` exakt auf den Renderer-Aufruf begrenzt. Danach
liefen beide vollständigen CI-Matrizen grün. Das war keine Produktcodekorrektur.

Der repositoryweite lokale Ruff-Baseline-Check bleibt außerhalb des Slice rot an bereits
auf Main vorhandenen Skripten: drei Formatkandidaten und zwei Importsortierungsfehler in
`scripts/needs_refinement/federation_crawler_v8.py`. Diese Fremdpfade wurden nicht geändert.

## 5. Produktionsbeweis der Nicht-Aktivierung

Der bereits nach dem Merge gestartete `workflow_dispatch`-Run `29436703996` lief auf dem
exakten Merge-Head `a750e0f3826e0067656062e02c3b7c896db35cde` und endete in 3m54s erfolgreich. Ein
redundant zusätzlich gestarteter Run `29436735960` wurde noch im Pending-Zustand
abgebrochen, um paralleles Heartbeat-Rauschen zu vermeiden.

Der einzige Folgecommit war:

```text
38f361318b39864628dca1329bc513475fec1c04
chore: heartbeat #5502 state sync
```

Er änderte ausschließlich elf bekannte `.steward/`- und `data/federation/`-State-Pfade.
Kein Root-, Produkt-, Test-, Spec- oder Workflowpfad änderte sich.

Blob-Beweis:

```text
CLAUDE.md @ Merge:                    8146a15603c95e5aa1404c9eb7021e3008914b0c
CLAUDE.md @ Folgeheartbeat:           8146a15603c95e5aa1404c9eb7021e3008914b0c
AGENTS.md @ Merge/Folgeheartbeat:     absent
context-snapshot/publication:         absent
context_contract.py @ beide Heads:    5bd37a576ab476739fd37dd613c2e4630791a7e1
context_rendering.py @ beide Heads:   9b603bfbed853ed4cdcda4b8939c2926777fbc20
```

Logsignale:

```text
GIT_NADI: narrow staging failed: 0
pre-index refusal:                0
CLAUDE generation failed:        0
LegacyBriefingWriteDisabled:     0
context_rendering:               0
AGENTS.md:                       0
Runtime-Traceback:               0
```

Die Zeichenfolge `Traceback` kam zweimal ausschließlich in den vom Runner eingeblendeten
Python-Quellzeilen `import logging, traceback` und `traceback.print_exc()` vor; es gab
keinen ausgeführten Runtime-Traceback.

## 6. Ehrlich offene Produktionsbefunde

Der grüne Workflow war nicht providergesund:

- Groq antwortete zweimal 401 wegen ungültigem API-Key,
- Gemini endete nach Retries mit 429 Quota,
- Mistral antwortete zunächst 200, danach beim Streaming-Fallback 400,
- schließlich meldete die Chamber `ALL providers exhausted for streaming`,
- ein `agent_error`-Signal wurde an null Listener verteilt.

Damit beweist `workflow=success` nicht, dass der autonome Task erfolgreich abgeschlossen
wurde. Dieser neue Live-Beweis verschärft den bereits offenen Auftrag zur Heartbeat-
Fehlerklassifikation und -propagation; er wird nicht in Slice B mitrepariert.

Der Workflow-Post-Step pushte den Runtime-State weiterhin direkt auf `main` und GitHub
meldete den bekannten Bypass der erwarteten Required Checks. Das bleibt Schnitt H/I und
ist kein Grund, den Offline-Renderer vorzeitig zu verdrahten.

## 7. Nächster Gate

Der nächste erlaubte Schritt ist ausschließlich ein separater read-only G2-Preflight für
Feature 01 / Schnitt C. Er muss die exakte Constitution-Migration und vor allem die reale
separate menschliche Review-Precondition beweisen. Im belegten Ein-Collaborator-Zustand
darf kein Self-Approval, Admin-Bypass oder erfundener Reviewer diese Gate-Anforderung
ersetzen.

Bis dahin bleiben `.steward/conventions.md`, Root-Dateien, Publisher, Recovery, Caller,
Workflow, Delivery, Governance und Aktivierung unverändert.
