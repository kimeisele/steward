# AGENT B REVIEW PACKET — ADR DECISION SPRINT 1

> Status: REVIEW-VORLAGE — ADR-02/-06/-07/-08/-09 ACCEPTED im engen Federation-Delegation-V1-Scope; Agent-B-Review und Spec-Freeze offen
> Datum: 2026-07-18
> Scope: Federation Delegation Contract V1; keine universelle Execution Spine; kein Produktcode

Dieses Dokument ist vollständig eigenständig und enthält die technische Review-Unterlage.
Dateipfade und historische Pins dienen als Nachweis, sind aber keine Voraussetzung zum
Verständnis der Entscheidungen.

---

## 1. Arbeits- und Evidenzbasis

### Arbeitsstand

- Repository: kimeisele/steward
- Branch: adr/federation-delegation-sprint-1
- Dokumentations-Commit vor diesem Packet: 7a6480a645
- Branch-Basis: origin/main 110b933231ebdcd3fc43c04ee30afe5df88be513
- Branch lokal einen Commit vor origin/main; nicht gemergt und vor Erstellung dieses
  Packets nicht gepusht.

Für die historische Recon-Auswertung wurden Heartbeat- und Federation-Sync-Commits explizit
ausgeschlossen:

~~~text
git log --extended-regexp --invert-grep \
  --grep='(^|[^[:alpha:]])heartbeat([^[:alpha:]]|$)|steward: federation sync'
~~~

### Relevante Live-Pins

| Repository | Head | Tree | Rolle |
|---|---|---|---|
| Steward | 24f86ec0749a1eff919921a947189ee5c459a4c8 | 42abf088363f99f8eed32ca7b8c663cb6487a202 | Code-/Runtime-Basis |
| Agent City | e798bdbf7b3969beea577fe265657bbb7c142115 | 496a321f6b426122892cbbbeaa1e20e5f002167c | Cross-Repo-Livebasis |
| Steward Protocol | 34a8a0efc25c15ef7c07dd4fb50aeb2510c071e8 | 48897cf33b748855a3d84538357108083bb70d5c | Produktionsdependency |

Die Runtime-Symbole wurden gegen den aktuellen Checkout erneut geprüft. Dieses Packet
enthält ausschließlich Dokumentation.

### Sprint-Scope

Entschieden werden ausschließlich:

- ADR-02: Execution-, Correlation- und Message-ID
- ADR-06: Federation-Signaturvertrag
- ADR-07: Capability-Wiring-Definition
- ADR-08: Retry-, Recovery- und Idempotenzvertrag
- ADR-09: Receipt-Semantik

Nicht entschieden und nicht implementiert werden:

- universelle execution_id über Provider, Tool, Workflow und Federation
- Provider-Failover-Reparatur
- Context-Bridge-Aktivierung
- Workflow-/GitHub-Änderungen
- Agent-City-Handler
- Migration oder Rollout
- neue Runtime-Abstraktion

### Geänderte Dokumente

Der vorherige Dokumentations-Commit enthält:

- docs/PHASE2_BEFUND.md
- specs/FEDERATION_DELEGATION_CONTRACT_V1.md
- specs/execution_truth_map/EXECUTION_TRUTH_MAP_RECON.md
- specs/execution_truth_map/ADR_BACKLOG.md
- specs/execution_truth_map/ADR-02-ID-BOUNDARIES.md
- specs/execution_truth_map/ADR-06-FEDERATION-SIGNATURE.md
- specs/execution_truth_map/ADR-07-CAPABILITY-WIRING.md
- specs/execution_truth_map/ADR-08-RETRY-RECOVERY-IDEMPOTENZ.md
- specs/execution_truth_map/ADR-09-RECEIPT-SEMANTIK.md
- specs/execution_truth_map/ADR_DECISION_SPRINT_1_REVIEW.md

Dieses Packet ist die vollständige, eigenständige Review-Fassung und wird in einem eigenen
Commit ergänzt.

### Unveränderte Bereiche

- docs/PHASE1_BEFUND_steward.md blieb read-only.
- Context-Bridge-Code, PR #728, E1, D2b, G1, Publisher, Delivery und Aktivierung blieben
  unangetastet und gesperrt.
- Steward-, Agent-City- und Steward-Protocol-Produktcode wurden nicht geändert.
- Keine Workflow-, Secret-, Runtime- oder Produktionskonfiguration wurde geändert.

### Tests und Produktionsbelege

- Steward-Fokuslauf aus dem Recon über Federation, Provider, Agent, Autonomy und Health:
  349 passed.
- Aktueller Smoke-Test: pytest -q tests/test_moksha_health.py → 17 passed.
- Agent-City-Federation-/PR-Fokuslauf: 88 passed, 4 failed.
- Alle vier Agent-City-E2E-Fehler enden bei PR_VERDICT: Signature verification FAILED.
- Agent-City-Produktionsrun 29644618328: GH006 beim Protected-Branch-Push, Workflow dennoch
  success; .github/workflows/agent-city-heartbeat.yml:127 enthält git push || true.
- Steward-Heartbeat 29645810216: Cognition-State 3/3 nutzbare Provider, hard_down=false,
  degraded=false, skip_collapse=false, decode_error=null.

---

## 2. Relevante IST-Risse

### Identitätsverlust

- vibe_core/task_management/task_manager.py:TaskManager.add_task erzeugt lokale Task-UUIDs.
- steward/types.py:ToolUse besitzt eine lokale Tool-Call-ID.
- steward/a2a_adapter.py:A2ATask besitzt eine getrennte A2A-ID.
- steward/federation.py:BridgeEvent besitzt keine Correlation-ID.
- steward/federation.py:FederationBridge.flush_outbound setzt correlation_id="".
- steward/federation_transport.py ergänzt message_id nur auf bestimmten unsignierten
  Transportpfaden.
- Provider-Attempt-ID und universelle execution_id existieren nicht.

DelegateTool.execute sendet weder Ursprungstask-ID noch Correlation-ID. Der Inbound-Pfad
erzeugt mit TaskManager.add_task() eine neue lokale UUID. Die lokale Task ist damit nicht
belastbar an die ursprüngliche Delegation gebunden.

### Kein echtes Targeting

steward/tools/delegate.py:DelegateTool.execute schreibt target_agent in die Payload.
FederationBridge.flush_outbound routet jedoch über alle alive/suspect Peers. Die Payload-
Angabe steuert den Transport nicht. Das ist Broadcast, kein exaktes Targeting.

### Titel-Substring-Korrelation

FederationBridge._handle_task_callback sucht blockierte Tasks über
delegated:{task_title} als Description-Substring. Gleiche Titel, Retries, doppelte
Callbacks und konkurrierende Tasks sind nicht eindeutig trennbar.

Erfolgs- und Fehlercallback setzen den Ursprung beide von BLOCKED auf PENDING.
_execute_federated_task kann eine Task bei result is None zunächst als COMPLETED markieren
und danach task_failed emittieren.

### Inkompatibler Signaturvertrag

Steward:

- steward/federation.py:FederationBridge._sign_message_dict
- steward/federation_crypto.py:canonical_message_hash
- Hash-/Signatur-Scope unterscheidet sich vom Agent-City-Pfad.
- signer_key wird nicht zuverlässig im erwarteten Verdict-Wireobjekt übertragen.

Agent City:

- city/hooks/dharma/pr_verdict.py:PRVerdictHook.execute verlangt signature und signer_key
  und verifiziert eine innere Payload.
- city/node_identity.py:NodeIdentity.verify erwartet hex-codierte Signaturen.
- city/federation_nadi.py serialisiert outbound mit anderem Scope und Base64-Grenze.

Die vier roten E2E-Tests reproduzieren den Scope-/Encoding-/Key-Provenance-Konflikt.

### Unklare Receipt-Semantik

steward/federation_relay.py:DeliveryReceipt enthält nur Batch-ID, Ziel, Message-Liste,
Push-Zeit und boolesches confirmed. Die Receipts sind in-memory. Eine spätere beliebige
Nachricht desselben Peers bestätigt alle offenen Receipts dieses Peers. Das beweist weder
Message-spezifische Zustellung noch Admission, Start, terminale Wirkung oder Verification.

### Fehlende Idempotenz und Crash-Recovery

city/federation_nadi.py:FederationNadi.receive dedupliziert nur in-memory über
source:timestamp. Steward besitzt relay_seen_ids.json, aber keinen durablen Delegation-
Ledger für Admission, Work-Handle, Lease, terminales Resultat und Konflikte.

Es gibt keine belastbare Unterscheidung zwischen unbekannter Nachricht, angenommener
Nachricht, laufender Arbeit, Side Effect vor Crash, terminalem Resultat und Recovery-
pflichtigem Zwischenzustand.

### Unvollständiges Capability-Wiring

steward/federation.py:ALL_OPERATIONS deklariert 24 Operationen; der Bridge registriert nur
15 Inbound-Handler. Richtung, Target, Authority, Resultatpfad und Testvollständigkeit sind
nicht maschinenlesbar gekoppelt.

Für delegate_task gilt live:

- Steward-Emitter vorhanden.
- Steward-Transport vorhanden.
- target_agent wird nicht auf ein einzelnes Ziel geroutet.
- Agent City enthält am Pin keinen delegate_task-/OP_DELEGATE_TASK-Fachhandler in city/
  oder tests/.
- FederationNadiHook nimmt generisch auf.
- city/phases/dharma.py:execute konsumiert die Federation-Surface auch für unbekannte
  Operationen.
- MissionRouter und Worker sind nicht an einen Delegation-Admission-Pfad angeschlossen.

---

## 3. ADR-02 — Execution-, Correlation- und Message-ID

### Entscheidungsfrage

Sollen Execution-ID, Correlation-ID, Message-ID und lokale Task-IDs getrennt werden, und
welche Erzeugungs-, Persistenz- und Zuordnungsregeln gelten?

### Optionen

Option A: eine gemeinsame ID. Task-ID, correlation_id und message_id wären derselbe String.
Vorteil: minimale Änderung. Nachteile: Retry und Lifecycle nicht unterscheidbar; lokale IDs
würden global; Antwort-, Replay- und Recovery-Grenzen blieben vermischt.

Option B: getrennte Rollen mit expliziter V1-Beziehung — akzeptiert.

### Normative Entscheidung

| Feld | Erzeuger | Lebensdauer/Persistenz | Kardinalität |
|---|---|---|---|
| delegation_id | Steward-Origin vor dem ersten Send | Origin- und Ziel-Ledger | genau eine pro Delegations-Lifecycle |
| correlation_id | nicht separat zufällig erzeugt | in jeder V1-Message | exakt delegation_id; viele Messages → eine Delegation |
| message_id | Sender jeder logischen Message | Message-/Replay-Dedup | eine pro logischer Message |
| origin_task_id | Steward TaskManager | lokale Managed Task | lokal, nicht global |
| target_work_id | Agent City nach durabler Admission | Ziel-Work-Ledger | null oder genau eine pro Delegation |
| receipt_id | Receipt-Aussteller | Receipt-Ledger | eine pro Receipt |
| subject_message_id | Receipt-Aussteller | Receipt-Ledger | auslösende Message pro Receipt |
| idempotency_key | Origin | Request-Ledger | stabil über identische Retries |

Invarianten:

1. correlation_id == delegation_id bytegenau.
2. payload.delegation_id == top-level correlation_id bytegenau.
3. delegation_id bleibt über Request, Admission, Start, Result und Verification unverändert.
4. message_id wird vor Signierung erzeugt.
5. Retry derselben kanonischen Bytes behält dieselbe message_id.
6. Jede neue fachliche Antwort erhält eine neue message_id und dieselbe correlation_id.
7. target_work_id entsteht erst nach persistentem Admission-Commit.
8. Keine ID wird aus Titel, Timestamp, Listenposition oder Payload-Substring abgeleitet.
9. Eine Delegation erzeugt höchstens einen target_work_id.
10. Diese Entscheidung behauptet keine universelle execution_id.

Begründung: Die getrennten Rollen verhindern die heutigen Titel-, Retry- und Local/Global-
Kopplungsfehler. Option A wurde verworfen, weil sie Mehrdeutigkeit nur verstecken würde.

Auswirkungen:

- Steward: DelegateTool, Bridge-Envelope, Origin-Ledger und Callback müssen alle IDs führen;
  Titelmatching ist kein V1-Fallback.
- Agent City: Ingress, Admission, Worker-State und Resultat persistieren die IDs.
- Steward Protocol: gemeinsame Wire-Modelle dürfen keine ID verlieren oder still erzeugen.
- Migration: Legacy-Nachrichten ohne V1-IDs werden nicht als V1 angenommen.
- Recovery: delegation_id ist Lifecycle-Key; message_id ist Message-Dedup-Key.
- Authority: IDs verleihen keine Berechtigung.
- Tests: gleiche Titel mit unterschiedlichen IDs, Replay, Konflikt-Duplicate, falsche
  Korrelation und doppelte Resultate.

Adversariales Gegenargument: Mehr IDs können auseinanderlaufen. Gegenmaßnahme: harte
Gleichheit von correlation_id und delegation_id, unveränderte Replay-Message-ID und
fail-closed Konfliktprüfung.

Restrisiken: Persistenzfehler, noch nicht festgelegtes ID-Stringformat und die bewusst offene
universelle Execution-ID.

Status: ACCEPTED für Federation Delegation V1; Implementierung nicht freigegeben.

---

## 4. ADR-06 — Federation-Signaturvertrag

### Entscheidungsfrage

Welche exakten Bytes werden signiert, wie werden Hash, Signatur und Public Key kodiert, und
wie werden Relay-/Hub-Mutationen verhindert?

### Optionen

Option A: bestehendes Steward-Format. Bestehenden Hash-Scope, implizite Registry-Key-
Auswahl und Legacy-Hub-Ausnahmen weiterführen. Migrationsärmer, aber die reproduzierte
Steward-/Agent-City-Inkompatibilität bliebe bestehen.

Option B: expliziter kanonischer V1-Envelope — akzeptiert.

### Normative Regeln

Pflichtfelder:

~~~text
contract_version
message_id
source_node_id
target_node_id
operation
correlation_id
payload
issued_at
expires_at
payload_hash
signature
signer_key
~~~

1. message_id wird vor dem Signieren erzeugt.
2. Der Signatur-Body enthält alle Envelope-Felder außer exakt payload_hash und signature.
3. signer_key bleibt im signierten Body.
4. payload ist ein JSON-Objekt.
5. Unbekannte Top-Level-Felder werden abgelehnt.
6. Canonical JSON ist UTF-8 mit sort_keys=true, ensure_ascii=false und
   separators=(",", ":").
7. Nicht serialisierbare Werte sind Schemafehler; default=str ist verboten.
8. payload_hash ist lowercase Hex-SHA-256 der kanonischen UTF-8-Bytes.
9. signature ist Base64 einer Ed25519-Signatur über die ASCII-Bytes des Hex-Hashes.
10. signer_key ist ein 32-Byte-Ed25519-Raw-Public-Key als 64-stelliger lowercase Hexstring.
11. source_node_id lautet exakt:

~~~text
ag_ + erste 16 lowercase Hex-Zeichen von SHA256(signer_key_hex_ascii)
~~~

12. Der Empfänger vergleicht die Ableitung mit der registrierten Node-Identity.
13. Relay/Hub darf keinen signierten Wert hinzufügen, entfernen oder ändern.
14. Relay-Metadaten werden nicht in den signierten Envelope eingefügt.
15. exclude_hub_id ist Legacy und im V1-Pfad verboten.
16. Unterschiedliche Signaturformate innerhalb derselben contract_version sind verboten.

### Verifikationsreihenfolge

1. JSON dekodieren und Top-Level-Schema prüfen.
2. Version und Pflichtfelder prüfen.
3. Typen, RFC-3339-Zeitwerte und Ablauf prüfen.
4. signer_key auf exakt 32 Raw-Bytes prüfen.
5. source_node_id aus dem Key ableiten und vergleichen.
6. Sender-Key gegen Trust-/Identity-Registry prüfen.
7. Canonical Bytes ohne payload_hash und signature bilden.
8. Hash neu berechnen und vergleichen.
9. Ed25519-Signatur über ASCII-Hash prüfen.
10. target_node_id gegen lokale Node-Identity prüfen.
11. Authority, Capability und Wiring prüfen.
12. Erst danach Admission und Fachdispatch.

Alle Fehler führen fail-closed zu Reject: fehlende/zusätzliche Felder, falsche Version,
nichtkanonische Bytes, falscher Hash, ungültige Kodierung, unbekannter Key, falsches Target,
Expiry, Hub-Mutation oder Authority-/Wiring-Fehler.

Auswirkungen:

- Steward: _sign_message_dict und Transport erzeugen message_id vor Signierung und
  übertragen signer_key.
- Agent City: NodeIdentity.verify und PR-Verdict-Grenze verwenden denselben Scope, Hash und
  Encoding.
- Steward Protocol: alle signierten Felder werden verlustfrei übertragen.
- Migration: Legacy und V1 sind strikt versioniert getrennt.
- Recovery: identische Bytes sind replaybar; veränderte Bytes mit gleicher Message-ID sind
  Integrity-Fehler.
- Authority: Signatur beweist Identität/Integrität, nicht fachliche Berechtigung.
- Tests: Golden Bytes, Unicode, falscher Key, falsches Target, Hub-Mutation, reale
  Steward→Agent-City-Verifikation.

Adversariales Gegenargument: Neues Format erzeugt Legacy-/V1-Koexistenz und blockiert alte
Nachrichten. Antwort: Ein stilles Mischformat würde die bereits reproduzierte Crypto-
Inkompatibilität sichern.

Restrisiken: contract_version-Literal, Key-Rotation, Registry-Lebensdauer und fachliche
Authority sind noch nicht vollständig festgelegt.

Status: ACCEPTED als V1-Kanonisierung; Golden-Byte-Fixtures vor Implementierung erforderlich.

---

## 5. ADR-07 — Capability-Wiring-Definition

### Entscheidungsfrage

Wann gilt eine Federation-Capability als tatsächlich implementiert?

### Optionen und Entscheidung

Option A: ALL_OPERATIONS und lokaler Handler genügen. Verworfen, weil Richtung, Target,
Authority, Resultat, Recovery und Cross-Repo-Tests fehlen können.

Option B: vollständiges Wiring-Manifest als Gate — akzeptiert.

Manifestfelder:

~~~text
operation
contract_version
direction
schema
canonical_bytes
emitter
transport
targeting
inbound_membrane
authority_gate
admission_handler
fachhandler
durable_state_owner
state_transition
idempotency_store
receipt_emitter
result_operations
failure_operations
correlation_rules
positive_tests
adversarial_tests
production_evidence
status
~~~

Vollständige Kette:

~~~text
Operation/Version
→ Richtung
→ Schema/Canonical Bytes
→ Emitter
→ Transport
→ exaktes Target
→ Ingress-Membran
→ Trust-/Authority-Gate
→ Fachhandler
→ persistenter State-Übergang
→ Idempotenzspeicher
→ Receipt-/Resultatpfad
→ Origin-Korrelation
→ positive Tests
→ adversariale Tests
→ Produktionsbeleg
~~~

Status:

- declared: nur bekannt/deklariert.
- partial/partially_wired: einzelne Kanten vorhanden, notwendige Kanten fehlen.
- unavailable: angeforderte Richtung besitzt keinen konkreten Handler-/Resultatpfad.
- legacy: historischer, separat markierter Pfad.
- implemented: alle Kanten, persistente Zustände, Authority, Idempotenz, Receipts,
  Resultate, positive/adversariale Cross-Repo-Tests und reproduzierbarer Produktionsbeleg
  vorhanden.

Aktueller delegate_task-Status:

- Steward-Emitter vorhanden.
- Steward-Transport vorhanden.
- exaktes Targeting fehlt.
- Agent-City-Fachhandler fehlt.
- Admission-/Dedupe-State fehlt.
- typed Receipt-Pfad fehlt.
- ID-basierte Origin-Korrelation fehlt.
- Produktionsbeleg fehlt.

delegate_task ist aktuell mindestens unavailable auf Agent-City-Seite und insgesamt
partially_wired, nicht implemented.

Auswirkungen:

- Steward: Richtung, Target, Handler und Resultat müssen explizit sein.
- Agent City: generisches Queue-Konsumieren zählt nicht als Fachhandler.
- Steward Protocol: Schema und Canonical Bytes werden als Manifestkante testbar.
- Migration: vorhandene Operationen als legacy, partial oder unavailable inventarisieren.
- Recovery: Handler ohne State-/Recovery-Owner ist nicht implementiert.
- Authority: Transport oder Signatur ersetzen kein Authority-Gate.
- Tests: reale Wire-Bytes und adversariale Cross-Repo-Tests.

Adversariales Gegenargument: Manifest wird zweites SSOT. Antwort: Es beschreibt nur
überprüfbare Wiring-Kanten und verweist auf Code-/Schema-Symbole.

Restrisiken: Manifest-Drift, veraltete Produktionsbelege, begrenzter Crucible-Scope.

Status: ACCEPTED als Implementierungs-/CI-Gate; keine Auditor-Implementierung in diesem Sprint.

---

## 6. ADR-08 — Retry, Recovery und Idempotenz

### Entscheidungsfrage

Wie werden Retries, doppelte Nachrichten, Timeout, Crash und partielle Side Effects behandelt?

### Optionen und Entscheidung

Option A: At-most-once ohne Recovery-Fortsetzung. Verworfen wegen möglichem Arbeitsverlust
und unbekanntem Side Effect.

Option B: At-least-once Transport mit durablem idempotentem Empfänger — akzeptiert.

Normative Regeln:

1. Transport darf mehrfach liefern.
2. delegation_id identifiziert den Lifecycle.
3. idempotency_key bindet den kanonischen Request-Body.
4. Vor lokaler Ausführung wird atomar ein persistenter Admission-/Dedupe-Eintrag angelegt.
5. Identischer Request erzeugt keine zweite Mission und liefert bekanntes Receipt/Resultat.
6. Gleiche Delegation mit verändertem Body wird duplicate_conflict, fail-closed und persistiert.
7. Retry derselben Bytes behält message_id.
8. Neue fachliche Antwort erhält neue message_id und dieselbe correlation_id.
9. Terminale identische Duplikate sind No-op; widersprüchliche werden Konflikt/Quarantäne.
10. Retry erweitert weder Authority noch Target noch Ablaufzeit.
11. EXECUTING besitzt Lease-/Heartbeat-Grenze.
12. Lease-Ablauf führt zu RECOVERY_REQUIRED, nicht automatisch zur Zweitausführung.
13. Nicht-idempotente Side Effects benötigen fachlichen Dedup-Key oder werden abgelehnt.
14. Titel, Timestamp und Listenposition sind niemals Dedup-Key.

Zustände:

~~~text
UNKNOWN
  → ACCEPTED
  → EXECUTING
  → RESULT_REPORTED
  → VERIFIED | FAILED_VERIFICATION

ACCEPTED/EXECUTING
  → RECOVERY_REQUIRED

UNKNOWN
  → REJECTED | DUPLICATE_CONFLICT | EXPIRED
~~~

Crash-/Timeout-Regeln:

- Crash vor Admission: Ohne durablen Admission-Eintrag darf derselbe Request erneut zur
  Admission angeboten werden.
- Crash nach Admission: target_work_id bleibt; keine zweite Mission.
- Crash während Execution: vorhandenen Work-Handle fortsetzen oder RECOVERY_REQUIRED.
- Crash nach Terminalresultat: Resultat erneut liefern, am Ursprung nur einmal anwenden.
- Timeout beweist weder Nichtausführung noch Ausführung.
- Statusabfrage unterscheidet UNKNOWN, ACCEPTED, EXECUTING, RECOVERY_REQUIRED, terminale
  und Konfliktzustände.
- Partielle externe Tool-Ausführung benötigt Dedup-Key, Read-back oder explizite Recovery.
- Blindes erneutes Tool- oder Delegationsausführen ist verboten.

Auswirkungen:

- Steward: Origin-Ledger wendet Terminalresultate nur einmal an.
- Agent City: durable Admission, target_work_id, Lease und Recovery sind Pflicht.
- Steward Protocol: Retry verändert signierte Bytes nicht.
- Migration: Titel-/Timestamp-Dedup ist kein V1-Fallback.
- Recovery: Unsicherheit bleibt sichtbarer Zustand.
- Authority: Retry reproduziert exakt ursprüngliche Authority und Target.
- Tests: Replay, Konflikt-Replay, Crash-Fenster, Lease, Doppelresultat und partial Side Effect.

Adversariales Gegenargument: Ein Ledger garantiert keine Exactly-Once-Wirkung bei externen
Tools. Das wird ausdrücklich nicht behauptet. Ohne fachliche Deduplizierung bleibt
RECOVERY_REQUIRED.

Restrisiken: Lease-Entscheidungen, externe Systeme ohne Dedup-Unterstützung und Operator-
Recovery.

Status: ACCEPTED für V1; Ledger, Lease und Recovery nicht implementiert.

---

## 7. ADR-09 — Receipt-Semantik

### Entscheidungsfrage

Welche Receipt-Stufen existieren, wer darf sie ausstellen und was beweist jede Stufe?

### Optionen und Entscheidung

Option A: einzelner boolescher Delivery-Receipt. Verworfen, weil Transport, Annahme, Start,
Wirkung und Verification vermischt würden.

Option B: typisierte, gestufte, rollenbegrenzte Receipts — akzeptiert.

Jede Receipt enthält:

~~~text
receipt_id
receipt_stage
delegation_id
correlation_id (= delegation_id)
message_id (eigene Receipt-Envelope-ID)
subject_message_id (auslösende Message)
issuer_node_id
issuer_role
target_node_id
target_work_id
issued_at
status
evidence_ref/evidence_refs
signature
~~~

Die drei IDs bedeuten:

- message_id: Identität des Receipt-Envelopes.
- subject_message_id: Message, deren Verarbeitung die Receipt auslöste.
- receipt_id: fachliche Identität des Receipt-Datensatzes.

### Receipt-Stufen

| Stufe | Aussteller | Vorheriger Zustand | Beweist | Beweist nicht |
|---|---|---|---|---|
| transport_committed | relay/hub | SENT/Outbox-Commit | signierte Bytes in Ziel-Mailbox/Transportgrenze committed | Lesen, Admission, Start, Erfolg, Verification |
| admission | target_node | SENT oder optional transport_committed | Request geprüft; accepted/rejected; bei Annahme target_work_id | Worker-Start oder Erfolg |
| started | target_scheduler | admission=accepted | genau eine lokale Arbeit gestartet | Erfolg oder Postcondition |
| terminal | target_worker/target_node | normalerweise started | Zielarbeit completed oder failed mit Evidence | unabhängige Origin-Wirkung |
| verification | origin_node | terminales Resultat | unabhängige Postcondition VERIFIED oder FAILED_VERIFICATION | neue Zielausführung |

Invarianten:

1. Jede Receipt referenziert genau eine delegation_id.
2. correlation_id darf nicht fehlen.
3. target_work_id ist ab akzeptierter Admission Pflicht; bei Transport oder Reject null.
4. Identisches Receipt-Duplikat ist No-op oder Re-Emission.
5. Widersprüchliche Receipts gleicher Stufe werden als Konflikt persistiert.
6. Receipt-Stufen sind monoton.
7. Transport-Commit wird niemals zu Admission oder Verification hochgestuft.
8. Terminale Resultate tragen selbst receipt_stage=terminal.
9. Verification erst nach unabhängiger Beobachtung gemäß verification_contract.
10. Jede Wire-Receipt ist eine kanonisch signierte V1-Message; lokale Verification wird
    prüfbar im Origin-State persistiert.

Auswirkungen:

- Steward: nur Origin-Verification darf fachliche Completion bestätigen.
- Agent City: Admission, Start und Terminal werden von klar benannten Rollen ausgestellt.
- Steward Protocol: Receipt-Schema, Signatur und Deduplizierung sind gemeinsam wire-stabil.
- Migration: heutiges DeliveryReceipt.confirmed wird Legacy-Transportbeobachtung.
- Recovery: fehlende Folgestufe bedeutet Unknown/Expired/Recovery, nie Erfolg.
- Authority: Relay nur Transport-Commit; Origin allein Verification.
- Tests: Stufenreihenfolge, falscher Aussteller, falsche IDs, Duplicate, Conflict und
  grüner Target-Workflow ohne Postcondition.

Adversariales Gegenargument: Mehr Stufen erzeugen State-Bloat und Scheinsicherheit. Die
Stufen begrenzen aber explizit, was jede Receipt nicht beweist.

Restrisiken: Retention, Out-of-Order-Eingänge und Receipt-Conflict-Persistenz.

Status: ACCEPTED für V1; Receipt-Ledger und Crucible nicht implementiert.

---

## 8. Konkreter Wire-Vertrag

### IDs und Bindung

~~~text
delegation_id       = Origin-Lifecycle, vor erstem Send erzeugt
correlation_id      = exakt delegation_id
message_id          = Identität einer logischen Message, vor Signatur erzeugt
origin_task_id      = lokale Steward-Task
target_work_id      = lokale Agent-City-Arbeit nach durabler Admission
receipt_id          = fachliche Receipt-Identität
subject_message_id  = auslösende Message des Receipt
idempotency_key     = kanonischer Request-Dedup-Key
~~~

### Exakter Envelope

Top-Level-Felder:

~~~text
contract_version
message_id
source_node_id
target_node_id
operation
correlation_id
payload
issued_at
expires_at
payload_hash
signature
signer_key
~~~

payload ist immer ein JSON-Objekt. Unbekannte Top-Level-Felder werden abgelehnt.
Structured Payload-Felder wie intent, authority, expected_outcome und
verification_contract benötigen noch eigene Schemas und dürfen nicht still als freie Prosa
interpretiert werden.

### Request-Payload

~~~text
delegation_id
origin_task_id
capability
intent
task_title
task_description
target_repo
authority
expected_outcome
verification_contract
deadline
idempotency_key
~~~

task_title ist Darstellung, niemals Korrelation. Authority und Postcondition werden
explizit übertragen; es gibt keine impliziten Berechtigungen.

### Kanonisierung und Signatur

Der zu hashende Body enthält alle Pflichtfelder außer exakt payload_hash und signature.
Er enthält insbesondere message_id, source_node_id, target_node_id, operation,
correlation_id, payload, issued_at, expires_at und signer_key.

~~~text
JSON UTF-8
sort_keys=true
ensure_ascii=false
separators=(",", ":")
kein default=str

payload_hash = lowercase_hex(SHA256(canonical_utf8_bytes))
signature    = Base64(Ed25519_sign(ASCII(payload_hash)))
~~~

Relay-/Hub-Regel: Kein signiertes Feld darf verändert werden. Hub-Metadaten gehören nicht in
den signierten V1-Envelope. Ein Hub-Commit ist Transport-Evidence, keine Annahme.

### Exemplarischer Request-Envelope

Die Werte <computed> sind zu berechnende Fixture-Werte und keine gültigen Produktions-
signaturen. Feldform und Algorithmen sind normativ.

~~~json
{
  "contract_version": "delegation-v1",
  "message_id": "msg-delegation-0001",
  "source_node_id": "ag_3138bb9bc78df27c",
  "target_node_id": "ag_target_city_001",
  "operation": "delegate_task",
  "correlation_id": "del-0001",
  "payload": {
    "delegation_id": "del-0001",
    "origin_task_id": "task-steward-0042",
    "capability": "fix_repository",
    "intent": {"name": "repair", "version": "v1"},
    "task_title": "Repair federation handler",
    "task_description": "Implement only the authorized handler contract.",
    "target_repo": "kimeisele/agent-city",
    "authority": {
      "allowed_actions": ["read", "test", "branch", "commit"],
      "denied_actions": ["merge", "secret_access", "context_bridge_activation"]
    },
    "expected_outcome": {"type": "verified_test_and_runtime_observation"},
    "verification_contract": {
      "postcondition": "handler accepts exactly one valid delegation"
    },
    "deadline": "2026-07-18T18:00:00Z",
    "idempotency_key": "idem-del-0001"
  },
  "issued_at": "2026-07-18T16:00:00Z",
  "expires_at": "2026-07-18T18:00:00Z",
  "payload_hash": "<64 lowercase hex SHA-256>",
  "signature": "<Base64 Ed25519 over ASCII payload_hash>",
  "signer_key": "1111111111111111111111111111111111111111111111111111111111111111"
}
~~~

Für den illustrativen Key ist die Node-ID nach dem beschlossenen Verfahren
ag_3138bb9bc78df27c.

### Exemplarisches Admission-Receipt

~~~json
{
  "contract_version": "delegation-v1",
  "message_id": "msg-receipt-admission-0001",
  "source_node_id": "ag_target_city_001",
  "target_node_id": "ag_3138bb9bc78df27c",
  "operation": "delegation_receipt",
  "correlation_id": "del-0001",
  "payload": {
    "receipt_id": "receipt-0001",
    "receipt_stage": "admission",
    "delegation_id": "del-0001",
    "subject_message_id": "msg-delegation-0001",
    "origin_task_id": "task-steward-0042",
    "target_work_id": "work-city-0042",
    "status": "accepted",
    "issuer_role": "target_node",
    "evidence_ref": "city-ledger://del-0001/admission"
  },
  "issued_at": "2026-07-18T16:00:04Z",
  "expires_at": "2026-07-18T18:00:00Z",
  "payload_hash": "<computed>",
  "signature": "<computed>",
  "signer_key": "<target-node-public-key-64-hex>"
}
~~~

Bei admission=rejected ist target_work_id ausdrücklich null; kein stilles Weglassen.

### Exemplarisches terminales Resultat

~~~json
{
  "contract_version": "delegation-v1",
  "message_id": "msg-result-0001",
  "source_node_id": "ag_target_city_001",
  "target_node_id": "ag_3138bb9bc78df27c",
  "operation": "task_completed",
  "correlation_id": "del-0001",
  "payload": {
    "receipt_id": "receipt-terminal-0001",
    "receipt_stage": "terminal",
    "delegation_id": "del-0001",
    "subject_message_id": "msg-receipt-started-0001",
    "origin_task_id": "task-steward-0042",
    "target_work_id": "work-city-0042",
    "terminal_status": "completed",
    "outcome": {"tests": "passed", "runtime_observation": "example-only"},
    "evidence_refs": ["city-test://run/example"],
    "started_at": "2026-07-18T16:00:05Z",
    "ended_at": "2026-07-18T16:04:00Z",
    "attempt_count": 1,
    "issuer_role": "target_worker"
  },
  "issued_at": "2026-07-18T16:04:01Z",
  "expires_at": "2026-07-19T16:04:01Z",
  "payload_hash": "<computed>",
  "signature": "<computed>",
  "signer_key": "<target-node-public-key-64-hex>"
}
~~~

### Fail-closed-Verifikation

Version, Schema, Zeit, Key-Format, Node-ID-Ableitung, Registry, Canonical Bytes, Hash,
Signatur, Target, Authority und Wiring werden vor Fachdispatch geprüft. Jede fehlende,
manipulierte, abgelaufene, nichtkanonische oder nicht autorisierte Message wird verworfen
und erhält einen strukturierten Failure-/Finding-Pfad; sie wird nicht still konsumiert.

---

## 9. Idempotenz- und Recovery-Fälle

- Identische Wiederholung: gleicher Request-Hash und message_id; ein Work-Handle, kein zweiter Side Effect.
- Gleiche delegation_id mit verändertem Payload: duplicate_conflict, fail-closed.
- Crash vor Admission: Retry zur Admission zulässig.
- Crash nach Admission: target_work_id bleibt; keine zweite Mission.
- Crash während Execution: Work-Handle fortsetzen oder RECOVERY_REQUIRED.
- Crash nach Terminalresultat: Resultat wiedergeben; Ursprung nur einmal ändern.
- Timeout: weder Nichtausführung noch Ausführung inferieren.
- Statusabfrage: UNKNOWN, ACCEPTED, EXECUTING, RECOVERY_REQUIRED, terminal und Konflikt unterscheiden.
- Lease-Ablauf: kein blinder Retry.
- Partielle Tool-Ausführung: Dedup-Key, Read-back oder explizite Recovery erforderlich.
- Retry erweitert keine Authority und kein Target.
- Nicht-idempotente Side Effects ohne fachliche Deduplizierung sind in V1 abzulehnen.

Exactly-once transport und Exactly-once external side effect werden nicht behauptet.

---

## 10. Capability-Wiring und späterer Crucible

Ein Manifest-Eintrag für delegate_task muss mindestens enthalten:

| Kante | V1-Anforderung |
|---|---|
| Operation | delegate_task, konkrete Vertragsversion |
| Richtung | Steward-Origin → Agent-City-Target |
| Emitter | DelegateTool.execute/Bridge |
| Target | exakter target_node_id, kein Broadcast |
| Transport | signierter V1-Transport ohne Hub-Mutation |
| Admission Handler | konkreter Agent-City-Handler |
| Authority Gate | Sender-Key, Trust, erlaubte Aktionen, Repo-Grenze |
| Fachhandler | Mission-/Worker-Erzeugung nach durabler Admission |
| Idempotenzspeicher | Delegation-/Request-Hash-/Message-Dedup-Ledger |
| Receipt Emitter | Admission, Started, Terminal |
| Result Operations | task_completed, task_failed |
| Failure Operations | Reject, Conflict, Recovery |
| Origin Correlation | IDs ohne Titelmatching |
| E2E-Test | reale Steward-Bytes durch Transport und Agent-City-Ingress |
| Produktionsbeweis | Annahme, genau eine Arbeit, Resultat, Verification |

Positiver Crucible:

~~~text
Steward erzeugt Delegation und signiert Request
→ optionaler Transport-Commit
→ Agent City validiert und nimmt exakt einmal an
→ target_work_id entsteht
→ Started-Receipt
→ genau eine lokale Mission
→ terminal task_completed/task_failed
→ Steward dedupliziert und korreliert
→ unabhängige Postcondition
→ origin verification
~~~

Adversariale Pfade:

- identisches Replay → ein Work-Handle, kein zweiter Side Effect
- gleiche Delegation mit verändertem Body → duplicate_conflict
- falsche Signatur/Key → fail-closed
- falsches Target/Broadcast → wrong_target
- fehlender Handler → capability_unavailable
- Crash nach Acceptance/Lease-Ablauf → RECOVERY_REQUIRED
- doppeltes/widersprüchliches Terminalresultat → No-op/Konflikt
- grüner Zielworkflow ohne Postcondition → FAILED_VERIFICATION

---

## 11. Draft 0.1 → Draft 0.2

Draft 0.1 enthielt einen vorbereitenden Mindestfeld- und Ablaufrahmen. Draft 0.2 ergänzt
normativ:

1. getrennte ID-Rollen und correlation_id == delegation_id
2. eigene Message-, Receipt- und Subject-Message-IDs
3. exakte Top-Level-Envelope-Feldmenge
4. Canonical-JSON-, Hash-, Signatur- und Key-Provenance-Regeln
5. exakte Target-Prüfung und Broadcast-Verbot
6. Admission vor jeder lokalen Ausführung
7. typisierte Receipt-Stufen und Ausstellerrollen
8. terminale Resultate als receipt_stage=terminal
9. durable Deduplizierung und duplicate_conflict
10. Lease und RECOVERY_REQUIRED
11. Authority- und Safety-Grenzen
12. Wiring-Manifest als Implementierungs-Gate
13. strukturierte Failure-Klassen
14. Golden-Wire-, Recovery- und repoübergreifende Crucible-Anforderungen

Aufgelöst durch diesen Sprint:

- ADR-02
- ADR-06
- ADR-07
- ADR-08
- ADR-09

Weiterhin offen:

- ADR-01
- ADR-03
- ADR-04
- ADR-05
- ADR-10

Der Contract bleibt DRAFT 0.2 und NOT IMPLEMENTATION-READY, weil Agent-City-Handler,
exaktes Targeting, V1-Crypto, Ledger, typed Receipts, Wiring-Manifest, Golden Fixtures,
Recovery-Crucible und Agent-B-Review fehlen.

Explizite Spec-Freeze-Fragen ohne stillen Default:

- exakter Literalwert von contract_version
- vollständige Subschemas für intent, authority, expected_outcome und verification_contract
- Lease-Dauer, Recovery-Owner und Receipt-Retention
- Key-Rotation und Registry-Lebensdauer
- Managed-Task-/A2A-/Sankalpa-Adapter
- Workflow-Wahrheit und Providerfehler außerhalb des Federation-Wire-Vertrags

---

## 12. Offene ADRs und Abhängigkeiten

### ADR-01 — Kanonische Ausführungsidentität

Frage: Welche Identität verbindet Managed Task, Provider Attempt, Tool Call, Federation,
Workflow und Verification?

Status: OPEN.

Federation V1: nicht zwingend für den engen Delegations-Wire-Vertrag, aber zwingend für eine
spätere universelle Execution-Spine.

Nicht implizit entscheiden: delegation_id ist keine universelle execution_id.

### ADR-03 — Terminale Completion

Frage: Wann darf eine Managed Task COMPLETED werden?

Status: OPEN.

Federation V1: Zielresultat und Origin-Verification sind definiert; Übersetzung zu Managed-
Task-COMPLETED bleibt offen.

Nicht implizit entscheiden: task_completed bedeutet nicht automatisch Managed-Task-COMPLETED.

### ADR-04 — Totale Provider-Erschöpfung

Frage: Exception, strukturiertes Outcome, Health-Signal oder Kombination?

Status: OPEN.

Federation V1: außerhalb des engen Wire-Vertrags; relevant, sobald ein delegierter Handler
Provider verwendet.

Nicht implizit entscheiden: Provider-None, Stream-Abbruch oder AgentEvent.ERROR wird nicht
automatisch als Federation-Erfolg oder -Fehler gewertet.

### ADR-05 — Workflow-Wahrheit

Frage: Welche relevanten Fehler machen einen Workflow rot, welche dürfen degraded bleiben?

Status: OPEN.

Federation V1: harter Produktions- und Crucible-Blocker, weil ein grüner Workflow trotz
fehlgeschlagenem Git-Push kein gültiger Produktionsbeleg ist.

Nicht implizit entscheiden: git push || true, Workflow-Conclusion oder Logzeile allein sind
kein terminales Erfolgsresultat.

### ADR-10 — Statusmodell und Adapter

Frage: Wie werden Federation-Zustände zu Managed Task, A2A, Sankalpa und Chitta übersetzt?

Status: OPEN.

Federation V1: harter Blocker für vollständige Integration, nicht für isolierte Wire-Semantik.

Nicht implizit entscheiden: ACCEPTED, EXECUTING, RESULT_REPORTED, VERIFIED und
FAILED_VERIFICATION dürfen nicht still auf vorhandene Enums gemappt werden.

---

## 13. Widerspruchs- und Implementierungsreife-Review

Geprüfte Schnittstellen:

- ADR-02 ↔ ADR-06: message_id vor Signierung, Replay unverändert — kein Widerspruch.
- ADR-02 ↔ ADR-08: Lifecycle-Key und Message-Dedup getrennt — kein Widerspruch.
- ADR-02 ↔ ADR-09: message_id, subject_message_id und receipt_id getrennt — kein Widerspruch.
- ADR-06 ↔ ADR-07: Manifest referenziert dieselbe Version und Canonical-Byte-Regel — kein Widerspruch.
- ADR-06 ↔ ADR-09: Receipts sind signierte V1-Messages mit rollenpassendem Issuer-Key — kein Widerspruch.
- ADR-07 ↔ ADR-08: State-/Dedupe-/Recovery-Owner sind Wiring-Kanten — kein Widerspruch.
- ADR-07 ↔ ADR-09: Result-/Receipt-Pfade müssen im Manifest stehen — kein Widerspruch.

Gemeinsame Invariante:

~~~text
signierte Message-ID ≠ Delegations-Lifecycle-ID ≠ lokale Task-ID;
Receipt/Result referenziert die Delegation explizit;
kein Transport- oder Admission-Receipt behauptet Verification.
~~~

Implementierungsreife: NOT IMPLEMENTATION-READY.

Vor Code erforderlich:

1. Agent-B-Review jeder ADR.
2. Entscheidung von ADR-05 und ADR-10.
3. Golden-Wire-Fixtures mit exakt denselben Bytes, Hashes und Signaturen in beiden Repositories.
4. Wiring-Manifest mit aktuellem delegate_task-Riss ausdrücklich als unavailable.
5. Durable Admission-/Dedupe-Ledger, Lease, Conflict- und Recovery-Tests.
6. Receipt-Schema, Issuer-Key-Bindung, Retention und monotone Zustandsprüfungen.
7. Echter Steward→Agent-City-Crucible mit positiven und adversarialen Pfaden.

---

## 14. Präziser Review-Auftrag an Agent B

Bitte explizit beantworten:

1. Sind ADR-02, -06, -07, -08 und -09 logisch widerspruchsfrei?
2. Sind delegation_id, correlation_id, message_id, receipt_id und subject_message_id
   vollständig und implementierbar getrennt?
3. Ist die Signaturdefinition inklusive signer_key, Node-ID-Ableitung, Canonical JSON, Hash,
   Base64 und Verifikationsreihenfolge vollständig für Golden-Wire-Fixtures?
4. Fehlt eine Crypto-, Replay-, Key-Rotation- oder Hub-Mutationsregel?
5. Sind Receipt-Stufen, Aussteller, Vorzustände, Duplicate-/Conflict-Semantik und Persistenz
   auch bei Out-of-Order-Eingängen eindeutig?
6. Sind Crash vor Admission, Crash nach Admission, Crash während Execution, Lease-Ablauf,
   Timeout und partielle Tool-Ausführung ausreichend geregelt?
7. Ist das Wiring-Manifest streng genug, damit eine Capability nicht bloß deklariert,
   sondern tatsächlich end-to-end verdrahtet ist?
8. Fehlt ein Nachweis zwischen Agent-City-Admission, MissionRouter, Worker, Terminalresultat
   und Origin-Verification?
9. Müssen ADR-01, -03 oder -04 entgegen der aktuellen Abgrenzung bereits vor Federation V1
   entschieden werden?
10. Ist Draft 0.2 bereit für Golden-Wire-Fixtures und Crucible-Design, oder muss er in einen
    weiteren ADR-Sprint zurück?

Vorläufiger Status:

~~~text
ADR-02/-06/-07/-08/-09: ACCEPTED im engen Federation-Delegation-V1-Scope
Contract: DRAFT 0.2
Implementierungsreife: NOT IMPLEMENTATION-READY
Produktcode: unverändert
Phase 1: unverändert/read-only
Context Bridge: unverändert/geparkt
~~~
