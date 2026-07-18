# EXECUTION TRUTH MAP — RECON GATE

> **Status:** ACCEPTED RECON — IST-EVIDENZ, KEINE PRODUKT- ODER SYSTEM-SPEC
> **Datum:** 2026-07-18
> **Scope:** Steward, Agent City und die in Produktion geladene Steward-Protocol-Grenze
> **Nicht autorisiert:** Produktcode, Execution-Spine-System-Spec, Context-Bridge-Resume,
> E1, D2b, G1, Delivery oder Aktivierung

---

## 0. Zweck und Beweisregel

Dieses Dokument sichert den akzeptierten read-only Recon dauerhaft. Es beschreibt den
tatsächlichen Ausführungs-, Fehler-, Verifikations- und Federation-Pfad. Es definiert
keine neue Runtime-Abstraktion.

Beweisrang:

1. aktueller Live-Code und aktuelle Produktionsartefakte,
2. reproduzierbare repoübergreifende oder lokale Tests,
3. Dokumentprosa nur als historische Behauptung.

Jeder Soll-Vertrag liegt außerhalb dieses Dokuments. Der nächste Soll-Vertrag steht in
`specs/FEDERATION_DELEGATION_CONTRACT_V1.md`. Offene Architekturentscheidungen stehen
unbeantwortet in `specs/execution_truth_map/ADR_BACKLOG.md`.

## 1. Live-Pins und Recon-Isolation

| Repository | Head | Tree | Rolle |
|---|---|---|---|
| `kimeisele/steward` | `24f86ec0749a1eff919921a947189ee5c459a4c8` | `42abf088363f99f8eed32ca7b8c663cb6487a202` | Live-/Dokumentbasis |
| `kimeisele/agent-city` | `e798bdbf7b3969beea577fe265657bbb7c142115` | `496a321f6b426122892cbbbeaa1e20e5f002167c` | Cross-Repo-Livebasis |
| `kimeisele/steward-protocol` | `34a8a0efc25c15ef7c07dd4fb50aeb2510c071e8` | `48897cf33b748855a3d84538357108083bb70d5c` | Produktionsdependency-Pin |

Der Steward-Head bewegte sich während des Recons durch reine Runtime-State-Commits.
Die inhaltliche Historie wurde deshalb ausdrücklich mit folgendem Filter gelesen:

```text
git log --extended-regexp --invert-grep \
  --grep='(^|[^[:alpha:]])heartbeat([^[:alpha:]]|$)|steward: federation sync'
```

Letzter inhaltlicher Steward-Head unter diesem Filter:

```text
9ebaff3722c98b4cc53c3d921f8c8511c3eaf5b3
Merge pull request #797 from kimeisele/docs/phase2-context-bridge-park-finalize
```

Recon-Worktrees:

- Steward: `/Users/ss/projects/steward-execution-spine-recon`, Branch
  `recon/execution-spine-foundation`, kein Upstream.
- Agent City: `/Users/ss/projects/agent-city-execution-truth-recon`, detached am Pin.
- Beide Worktrees waren bei Abschluss sauber.

## 2. Tests und Produktionsbelege

### 2.1 Reproduzierbare Tests

| Gegenstand | Kommando/Scope | Ergebnis |
|---|---|---|
| Steward Federation, Provider, Agent, Autonomy, Health | fokussierter Lauf über acht Testmodule | `349 passed` |
| Schnitt A Cognition | `pytest -q tests/test_moksha_health.py` | `17 passed` |
| Agent City Federation/PR | fünf Federation-/PR-Testmodule | `88 passed, 4 failed` |

Die vier Agent-City-Fehler sind:

- `TestE2EPRGatePipeline.test_verdict_reads_from_real_nadi_inbox`
- `TestE2EPRGatePipeline.test_full_pipeline_scanner_to_verdict`
- `TestE2EPRGatePipeline.test_full_pipeline_core_file_escalation`
- `TestE2EPRGatePipeline.test_full_pipeline_rejection`

Alle vier enden an `PR_VERDICT: Signature verification FAILED`. Damit beweisen die als
E2E bezeichneten Tests den heutigen realen Wire-Vertrag nicht.

### 2.2 Produktionsbelege

| Beleg | Ergebnis |
|---|---|
| Steward Heartbeat Run `29645810216` | grün auf `3e7ac351…`; Cognition-Instrument aktiv |
| Agent City Heartbeat Run `29644618328` | grün trotz abgelehntem `git push` auf protected `main` |
| Steward PR `#759` | Schnitt A gemergt als `281c7112bb90d0fe1440d25bf8229dfe12980f17` |
| PR `#759` CI | Python 3.11/3.12, Lint und Security grün |
| Steward PR `#728` | offen, D2b, nicht freigegeben |

Agent City Run `29644618328` enthält gleichzeitig:

```text
remote: error: GH006: Protected branch update failed for refs/heads/main
error: failed to push some refs
```

und Workflow-Conclusion `success`. Der Fehler wird in
`.github/workflows/agent-city-heartbeat.yml:127` durch `git push || true` maskiert.

Der am Steward-Live-Pin persistierte Cognition-State lautet:

```json
{
  "providers_alive": 3,
  "providers_total": 3,
  "providers_usable": 3,
  "total_calls": 0,
  "total_failures": 0,
  "calls_delta": 0,
  "fail_delta": 0,
  "hard_down": false,
  "degraded": false,
  "skip_collapse": false,
  "decode_error": null,
  "consecutive_collapsed_cycles": 0
}
```

## 3. Execution- und Correlation-Identitäten

| Identität | Erzeuger | Lebensdauer/Persistenz | Übergabegrenze | Befund |
|---|---|---|---|---|
| Managed Task `id` | `TaskManager.add_task()` | UUID, Task-YAML | lokale TaskManager-Grenze | stabil lokal |
| `ToolUse.id` | Agent-/Provider-Adapter | Conversation Memory | `tool_use_id` im Tool Result | kein dauerhafter Execution-Bezug |
| Federation `correlation_id` | Wire-Modell | Nachricht | Bridge/Transport | Steward setzt outbound `""` |
| Federation `message_id` | `NadiFederationTransport` | Nachricht | Transport | nur bei dort neu signierten Nachrichten |
| Relay `id` | Federation Relay | Hub-Nachricht | Hub-Dedup | nach Signierung ergänzt; keine Execution-ID |
| A2A Task `id` | A2A Adapter | A2A-State-Datei | Adapter → TaskManager | interne Task erhält andere UUID |
| Kirtan `action_id` | Caller | Kirtan-Ledger | Caller/Kirtan | komponierter String, kein universeller Bezug |
| GitHub Run ID | GitHub Actions | GitHub | Workflow | nicht mit Task/Message korreliert |
| Provider Attempt ID | — | — | — | nicht vorhanden |
| universelle `execution_id` | — | — | — | nicht vorhanden |

### 3.1 Codeanker

- `vibe_core/task_management/task_manager.py:TaskManager.add_task` erzeugt die UUID und
  persistiert über `_save_tasks()`.
- `steward/types.py:ToolUse` führt die lokale Tool-Call-ID.
- `steward/tools/delegate.py:set_current_task` hält Task-ID und Titel als Modulglobale.
- `steward/federation.py:BridgeEvent` besitzt Operation, Agent, Payload und Timestamp, aber
  keine Correlation-ID.
- `steward/federation.py:FederationBridge.flush_outbound` setzt `correlation_id=""`.
- `city/federation_nadi.py:FederationNadi.receive` dedupliziert in-memory über
  `source:timestamp`.
- `steward/a2a_adapter.py:A2ATask` persistiert eine getrennte A2A-ID.

### 3.2 Belegter Identitätsverlust bei Delegation

1. `DelegateTool.execute` sendet weder lokale Task-ID noch Correlation-ID.
2. Der Steward-Inbound-Handler `FederationBridge._handle_delegate_task` erzeugt mit
   `TaskManager.add_task()` eine neue UUID.
3. Der Callback enthält nur `task_title`, `source_agent`, `pr_url` oder `error`.
4. `FederationBridge._handle_task_callback` sucht den ersten blockierten Task, dessen
   Description `delegated:{task_title}` als Substring enthält.

Damit ist eine eindeutige Rückkorrelation bei gleichen Titeln, Retries oder doppelten
Callbacks nicht gewährleistet.

## 4. Statusmodelle

| Bereich | Zustände | Quelle/Symbol |
|---|---|---|
| Managed Task | `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `BLOCKED`, `TIMEOUT`, `ARCHIVED` | `vibe_core.protocols.mahajanas.janaka.types.task_types.TaskStatus` |
| A2A | `submitted`, `working`, `input-required`, `completed`, `failed`, `canceled` | `steward/a2a_adapter.py` |
| Sankalpa Mission | `active`, `paused`, `completed`, `abandoned` | `vibe_core.mahamantra.protocols.sankalpa.types.MissionStatus` |
| Chitta | `ORIENT`, `EXECUTE`, `VERIFY`, `COMPLETE` | `steward/antahkarana/chitta.py:ExecutionPhase` |
| Federation Peer | `ALIVE`, `SUSPECT`, `DEAD`, `EVICTED` | `steward/reaper.py:PeerState` |
| Cetana | `GENESIS`, `DHARMA`, `KARMA`, `MOKSHA` | `steward/cetana.py:CetanaPhase` |
| Context Source | `valid`, `empty`, `not_configured`, `unavailable`, `invalid`, `stale`, `unsafe`, `unsupported` | `steward/context_contract.py:SourceStatus` |

### 4.1 Konflikte

- A2A `working` und Task `IN_PROGRESS` besitzen keinen formalen Adaptervertrag.
- A2A- und interne Task-ID werden nicht gebunden; der Completion-Hook verwendet dennoch
  die interne Task-ID für A2A-Lookup.
- Sankalpa besitzt kein `FAILED`, sondern `ABANDONED`.
- Chitta-Phasen werden aus flüchtigen Tool-Impressions abgeleitet, nicht aus dem
  persistenten Task-Lifecycle.
- `AutonomyEngine._dispatch_next_task` markiert einen unbekannten Intent als `COMPLETED`.
- Deterministische Handler können den Task vor dem nachfolgenden LLM-/Fix-Schritt als
  `COMPLETED` markieren.
- `_execute_federated_task` markiert die lokale Task auch bei `result is None` zuerst
  `COMPLETED` und emittiert danach `task_failed`.
- Erfolgs- und Fehlercallback setzen den Ursprungstask beide von `BLOCKED` auf `PENDING`.

## 5. Fehlerkanäle

| Kanal | Producer | Listener/Konsum | Persistenz | sichtbares Ende |
|---|---|---|---|---|
| Exception | Handler/Hook/Workflow | lokale `except Exception` | meist Log | häufig Exit 0 |
| `None`/leerer Stream | `ProviderChamber` | `AgentLoop` | Provider-Metrik | `AgentEvent.ERROR` |
| `AgentEvent.ERROR` | `AgentLoop` | `Agent.run`/AgentBus | flüchtig | Fehlertext/Signal |
| `agent_error` | AgentBus | kein produktiver Listener belegt | nein | verwaist |
| `ToolResult(success=False)` | Tool Dispatch | AgentLoop | Conversation | lokaler Toolfehler |
| Federation Handler `False` | Bridge | `process_inbound` | Bridge-Counter teilweise | kein Outcome/Receipt |
| `hook_error:*` | Agent City `PhaseHookRegistry` | Operations-Liste | Run-State teilweise | Heartbeat läuft weiter |
| Workflow stderr | Git/Shell | GitHub Log | GitHub | kann grün bleiben |
| Finding | Diagnostic Sense | Report-Caller | nicht verbindlich | keine ID/Lifecycle-Korrelation |

### 5.1 Provider-Erschöpfung

- `steward/provider/chamber.py:ProviderChamber.invoke` dokumentiert und liefert bei totaler
  Erschöpfung `None`.
- `ProviderChamber.invoke_stream` beendet nach totaler Erschöpfung ohne terminales
  Response-Objekt.
- `steward/loop/engine.py:AgentLoop._call_llm_streaming` erzeugt daraus
  `AgentEvent(type=ERROR)` und kehrt normal zurück.
- Die Chamber klassifiziert transient/non-transient, erzeugt aber keine Request- oder
  Attempt-ID.
- Der Workflow-Harness in `.github/workflows/steward-heartbeat.yml` fängt jede Phase,
  loggt und läuft weiter.

### 5.2 Agent City

- `city/phase_hook.py:PhaseHookRegistry.dispatch` fängt jeden Hookfehler und hängt
  `hook_error:{hook}:{error}` an.
- `.github/workflows/agent-city-heartbeat.yml:127` maskiert den State-Push.
- Derselbe Workflow toleriert `git pull --rebase ... || true` und leert anschließend die
  Outbox unabhängig davon, ob einer der drei Pushversuche erfolgreich war.
- Der Produktionslog meldet außerdem `MicroBrain: ProviderChamber not available: No module
  named 'steward'`; der übrige OpenRouter-Pfad läuft weiter.

## 6. Verification, Outcomes und Receipts

| Struktur | Was sie tatsächlich belegt | Was sie nicht belegt |
|---|---|---|
| `ToolResult` | Tool kehrte mit success/error zurück | fachliche Postcondition |
| `GateResult`/`FixResult` | Lint/Security/Test-/Blast-Radius-Vergleich | Ursprungsdefekt unabhängig behoben |
| Kirtan Ledger | callerdefinierter Versuch/Status | echte Peer-Ausführung |
| `DeliveryReceipt` | Batch wurde zum Hub geschrieben; Peer später gesehen | Annahme, Konsum, Ausführung, konkrete Ack-ID |
| A2A Result | A2A-Task besitzt Resultat | Mapping zur internen Task |
| PR-Polling | GitHub-PR-Zustand | Zusammenhang zu allgemeiner Execution |
| Cognition Health | Provider-Kapazität/Failure-Delta über Zyklen | Workflow-Exit oder konkrete Taskwirkung |

`steward/federation_relay.py:DeliveryReceipt` ist in-memory. Eine beliebige spätere
Nachricht desselben Peers bestätigt alle offenen Receipts dieses Peers; es gibt keine
message-id-spezifische Bestätigung.

Der Delegations-Karma-Hook prüft `hasattr(kirtan, "get_status")`. `KirtanLoop` besitzt
keine solche Methode; der vorgesehene Kirtan-Resume-Pfad läuft daher nicht. Der direkte
Bridge-Callback ist der wirksame Pfad.

## 7. Federation-Wiring

### 7.1 Steward Operations-Registry

`steward/federation.py:ALL_OPERATIONS` deklariert 24 Operationen. Die Dispatch-Tabelle
registriert 15 davon. Ohne Steward-Inbound-Handler sind am Pin:

- `eviction`
- `claim_outcome`
- `diagnostic_request`
- `diagnostic_report`
- `merge_occurred`
- `pr_created`
- `ci_status`
- `pr_review_verdict`
- `bottleneck_resolution`

Ein Teil kann absichtlich outbound-only sein; `ALL_OPERATIONS` kodiert diese Richtung
jedoch nicht. Der Code kann deshalb „deklariert“, „sendbar“ und „inbound implementiert“
nicht maschinenlesbar unterscheiden.

### 7.2 Capability-Matrix

| Operation | Emitter | Transport | Zielhandler | Resultatpfad | Urteil |
|---|---:|---:|---:|---:|---|
| `heartbeat` | ja | ja | Steward ja | Health/Registry | produktiv aktiv |
| `delegate_task` | Steward ja | ja | Agent City nein | Titelcallback nur im Steward | gebrochen |
| `task_completed/failed` | Steward ja | ja | Steward ja | Titel-Substring | mehrdeutig |
| `pr_review_request` | Agent City ja | ja | Steward ja | Verdict | teilweise |
| `pr_review_verdict` | Steward ja | ja | Agent City ja | PR-Aktion | Crypto-Vertrag inkompatibel |
| `diagnostic_request/report` | deklariert | ja | kein kompletter Fachpfad | keiner | unverkabelt |
| `bottleneck_resolution` | ja | ja | Agent City ja | Dedup-Key/Mission | stärkster vorhandener Pfad |
| `compliance_report` | ja | ja | Agent City ja | Report/Event | teilweise |

### 7.3 `delegate_task` repoübergreifend

Steward:

- `steward/tools/delegate.py:DelegateTool.execute` wählt den Peer mit höchstem Trust.
- Payload enthält `target_agent`, aber keine Task-/Correlation-ID.
- `FederationBridge.flush_outbound` ignoriert `payload.target_agent` und erzeugt je eine
  Nachricht für jeden alive/suspect Peer.
- Tool-Erfolg bedeutet nur „lokal in Bridge-Outbox eingereiht“.

Agent City:

- Vollständige Suche in `city/` und `tests/` ergibt keinen Treffer für
  `delegate_task` oder `OP_DELEGATE_TASK`.
- `city/hooks/genesis/federation.py:FederationNadiHook` stellt jede Operation generisch in
  die Gateway-Queue.
- Fachhandler existieren für PR-Verdict, Compliance und Bottleneck Resolution, nicht für
  Delegation.
- `city/phases/dharma.py:execute` entfernt anschließend alle Federation-Surface-Items.

Folge: Die Nachricht erreicht die City, aber weder MissionRouter noch einen konkreten
Worker. Sie wird ohne Failure-Receipt konsumiert.

### 7.4 PR-Verdict-Signatur

Steward `FederationBridge._sign_message_dict`:

- Hash über den vollständigen kanonischen Envelope,
- Ed25519-Signatur über den Hashtext,
- base64-codierte Signatur,
- kein kompatibler `signer_key` im Verdict-Wireobjekt.

Agent City `PRVerdictHook.execute`:

- liest `signature` und `signer_key`,
- verlangt beide,
- verifiziert die innere `federation_payload`,
- `NodeIdentity.verify` erwartet eine hex-codierte Signatur.

Die Scope-, Encoding- und Key-Provenance-Verträge sind damit inkompatibel. Die vier roten
Agent-City-E2E-Tests reproduzieren die Ablehnung.

### 7.5 Ist-Sequenz

```mermaid
sequenceDiagram
    participant T as Steward TaskManager
    participant D as DelegateTool
    participant B as FederationBridge
    participant H as Federation Hub
    participant C as Agent City Federation Ingress
    participant W as Agent City Worker
    participant R as Steward Callback Handler

    T->>D: lokale task_id + title
    D->>B: delegate_task(title, target_agent)
    Note over B: correlation_id=""; target_agent nicht geroutet
    B->>H: je eine Nachricht an alle alive/suspect Peers
    H->>C: generischer Federation-Ingress
    C--xW: kein delegate_task-Fachhandler
    Note over C: DHARMA konsumiert Federation-Surface
    W--xR: kein Acceptance-/Failure-/Result-Receipt

    alt Steward empfängt Delegate von einem anderen Peer
        B->>T: neue lokale Task mit neuer UUID
        T->>R: callback nur mit task_title
        R->>T: erster BLOCKED-Task per Titel-Substring
    end
```

## 8. Gap-/Conflict-Matrix

| Klasse | Riss | Beleg |
|---|---|---|
| G0 | grüner Workflow trotz funktionalem Fehler | Agent City Run `29644618328`; Workflow `git push || true` |
| G0 | `delegate_task` ohne Agent-City-Handler | Nulltreffer in `city/` und `tests/`; DHARMA-Consume |
| G0 | PR-Verdict-Signatur inkompatibel | Wire-Code + vier reproduzierbare E2E-Testfehler |
| G0 | Delegationsziel nicht gebunden | `DelegateTool`-Payload vs. `flush_outbound` Peer-Loop |
| G1 | keine durchgehende Ausführungsidentität | Identitätsinventar §3 |
| G1 | Callback per Titel-Substring | `FederationBridge._handle_task_callback` |
| G1 | Completion vor Wirkung/Verifikation | `AutonomyEngine`; `_execute_federated_task` |
| G1 | Provider-Erschöpfung kein terminaler Workflow-Outcome | Chamber → Event → Harness |
| G1 | unbekannte Federation-Operation verschwindet | Dispatch-Lücke + Agent-City-DHARMA-Consume |
| G1 | Receipt beweist keine Wirkung | `DeliveryReceipt`-Semantik |
| G2 | Statusmodelle ohne formale Übersetzung | §4 |
| G2 | Agent City optionaler Steward-Providerpfad fehlt in Produktion | Produktionslog `No module named 'steward'` |
| G2 | Steward-Protocol wird beweglich aus `main` installiert | Heartbeat-Workflow-Checkout |
| G2 | Heartbeat-Masterstatus war gegenüber Schnitt A veraltet | PR `#759`, Code, Tests, Live-Artefakt |

## 9. Alte Behauptungen: bestätigt, widerlegt, ungeklärt

| Behauptung | Urteil | Beleg |
|---|---|---|
| Steward besitzt `OP_DELEGATE_TASK`, Agent City keinen Handler | bestätigt | §7.3 |
| Diagnostikoperationen besitzen keinen vollständigen Leser-/Resultatpfad | bestätigt | Registry/Dispatch-Matrix |
| NADI erreicht die City, nicht einen bestimmten Worker | bestätigt | Agent-City-Ingress/DHARMA |
| relevante Fehler können bei grünem Workflow enden | live bestätigt | Run `29644618328` |
| PR-Verdicts sind end-to-end funktionsfähig | widerlegt | Crypto-Vertrag + vier rote Tests |
| Kirtan verifiziert Delegationscallbacks | widerlegt/inaktiver Pfad | fehlendes `KirtanLoop.get_status` |
| Delivery Receipts beweisen Remote-Ausführung | widerlegt | Receipt-Implementierung |
| alle deklarierten Federation-Operationen sind bidirektional | ungeklärt/unmodelliert | Registry kodiert keine Richtung |

## 10. Wiederzuverwendende Bausteine

- persistente Managed Tasks und kanonischer `TaskStatus`,
- `ToolUse.id`/`tool_use_id` für lokale Toolkorrelation,
- ProviderChamber mit Fallback, Breaker, Quota und Cognition-Instrument,
- Federation-Gateway, canonical hash, Signatur- und Replay-Prüfung,
- FixPipeline `GateResult`/`FixResult`,
- Kirtan-Ledger als Versuchshistorie,
- A2A Task/Result-Persistenz,
- Chitta-Impressions und ExecutionPhase als lokales Beobachtungsmodell,
- Federation `DeliveryReceipt` als Transportbaustein, nicht als Execution-Receipt,
- Bottleneck-Dedup-Key als besseres bestehendes Korrelationsmuster,
- Context-Contract Source-/Degradationsstatus — nur bei späterem Resume.

## 11. Context-Bridge-Grenze

Die Context Bridge bleibt geparkt. PR `#728` ist offen und nicht freigegeben. Dieses Recon
autorisiert weder E1 noch D2b noch Publisher, Delivery, G1 oder Canonical-Aktivierung.

Bei einem späteren, separat freigegebenen Resume müsste sie ausschließlich belegte
Runtime-Wahrheiten konsumieren: aktive korrelierte Ausführungen, terminale Outcomes,
offene Findings, degradierte Komponenten, Verification Receipts und Source-Provenance.
Sie ist kein Reparaturpfad für die hier belegten Lücken.

## 12. Gate-Entscheidung

Eine spätere Execution Spine ist als Abstraktionsziel plausibel, aber jetzt nicht
spec-bereit. Zuerst gelten zwei engere Gates:

1. vorhandene Heartbeat-Failure-Dokumentation mit dem implementierten Beobachtungs-
   Schnitt A und dem Produktionszustand reconciliieren; B/C bleiben separat gegated,
2. Federation Delegation Contract V1 entscheiden und adversarial reviewen.

Erst aus diesen belegten Verträgen darf später abstrahiert werden. Dieses Dokument selbst
ist abgeschlossenes IST und kein Implementierungsauftrag.
