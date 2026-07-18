# FEDERATION DELEGATION CONTRACT V1 — DRAFT 0.2 (SUPERSEDED)

> **Superseded:** Diese Draft-0.2-Fassung ist historisch und nicht mehr normative Wire-,
> Fixture- oder Crucible-Basis. Die normative Revision steht in
> `specs/FEDERATION_DELEGATION_CONTRACT_V1_DRAFT_0_3.md`.

> **Status:** DRAFT 0.2 — ADR DECISION SPRINT 1 ACCEPTED; ADVERSARIAL-/READINESS-REVIEW
> PENDING; NOT IMPLEMENTATION-READY
> **Datum:** 2026-07-18
> **IST-Basis:** `specs/execution_truth_map/EXECUTION_TRUTH_MAP_RECON.md`
> **ADR-Basis:** `specs/execution_truth_map/ADR_BACKLOG.md`
> **Sperre:** Kein Produktcode, keine Aktivierung und kein Cross-Repo-Implementierungsmerge
> aus dieser Fassung.

---

## 0. Dokumentrolle

Diese Spec bereitet ausschließlich den Vertrag für eine gezielte, korrelierbare und
verifizierbare Delegation zwischen Steward und Agent City vor. Sie ist keine
Execution-Spine-Spec und führt kein universelles Execution-Modell ein.

Die Abschnitte sind bewusst getrennt:

- §1–2: belegtes IST,
- §3–9: SOLL-Vertrag für Federation Delegation V1 auf Basis ADR-02/-06/-07/-08/-09,
- §10: verbleibende ADR-Blocker,
- §11–13: Tests, Rollout und Definition of Ready.

## 1. Belegtes IST

### 1.1 Steward

- `steward/tools/delegate.py:DelegateTool.execute` wählt den alive Peer mit höchstem Trust.
- Die Payload enthält Titel, Priority, Capability, Repo, Source und `target_agent`, aber
  weder Ursprungstask-ID noch Correlation-ID.
- `steward/federation.py:FederationBridge.flush_outbound` setzt `correlation_id=""` und
  sendet jedes Event an jeden alive/suspect Peer; `payload.target_agent` steuert das Routing
  nicht.
- Der Ursprungstask wird `BLOCKED`; seine Description speichert
  `delegated:{title}|peer:{agent_id}`.
- `_handle_task_callback` korreliert per Titel-Substring und setzt sowohl Success als auch
  Failure zurück auf `PENDING`.

### 1.2 Agent City

- Am Pin `e798bdbf7b3969beea577fe265657bbb7c142115` existiert kein `delegate_task`-Handler.
- `FederationNadiHook` stellt die Nachricht generisch in die Federation-Surface.
- `city/phases/dharma.py:execute` konsumiert danach alle Federation-Surface-Nachrichten.
- `MissionRouter` und konkrete Worker sind an diesen Ingress nicht angeschlossen.

### 1.3 Folge

Der heutige Pfad kann weder genaue Zustellung noch Annahme, Worker-Dispatch, Ergebnis oder
Postcondition repoübergreifend beweisen. Ein grüner Emitter-Test ist kein End-to-End-Beleg.

## 2. Zweck und Nicht-Ziele

### 2.1 Zweck

V1 muss genau einen vertikalen Pfad definieren:

```text
Steward Managed Task
→ gezielte Federation-Delegation
→ Agent City Admission
→ genau eine lokale Mission/Worker-Zuweisung
→ terminales Resultat
→ eindeutige Rückkorrelation
→ Ursprungsverifikation
```

### 2.2 Nicht-Ziele

- keine universelle Execution Spine,
- keine allgemeine Workflow-Engine,
- keine neuen Agentenrollen,
- kein Plugin-/Marketplace-System,
- keine Context-Bridge-Aktivierung,
- kein Provider-Failover-Umbau,
- keine automatische Merge-Autorität,
- keine Abwärtskompatibilität durch Titelmatching,
- kein Broadcast als Ersatz für Targeting.

## 3. Vertragsobjekte und Wire-Objekte

### 3.1 Delegation Request

Ein V1-Request benötigt exakt die folgenden semantischen Felder. Die Wire-Serialisierung
folgt ADR-06; unbekannte Pflichtfelder, fehlende Pflichtfelder oder nicht kanonische Bytes
sind kein V1-Request.

| Feld | Typ | Vertrag |
|---|---|---|
| `contract_version` | Envelope-String | exakt unterstützte Delegation-Version |
| `message_id` | Envelope-String | pro logischer Federation-Message eindeutig; bei Retry derselben Bytes unverändert |
| `correlation_id` | Envelope-String | in V1 exakt derselbe Wert wie `delegation_id`; viele Messages → eine Delegation |
| `source_node_id` | Envelope-String | kryptographisch gebundener Sender |
| `target_node_id` | Envelope-String | exakter kryptographischer Zielknoten |
| `payload.delegation_id` | Payload-String | Origin-erzeugt, über den gesamten Delegationspfad unverändert; V1-lokal, keine universelle Execution-ID-Behauptung |
| `payload.origin_task_id` | Payload-String | exakte persistente Task-ID beim Ursprung |
| `payload.capability` | Payload-String | verlangte Fähigkeit, nicht freier Rollentitel |
| `payload.intent` | Payload-Struktur | erlaubter, versionierter Intent; keine reine Prosa als Dispatchschlüssel |
| `payload.task_title` | Payload-String | nur Darstellung; niemals Korrelation oder Idempotenz |
| `payload.task_description` | Payload-String | begrenzter Arbeitskontext |
| `payload.target_repo` | Payload-String/Null | kanonischer Repository-Identifier |
| `payload.authority` | Payload-Struktur | erlaubte Aktionen und ausdrücklich verbotene Aktionen |
| `payload.expected_outcome` | Payload-Struktur | fachliche Zielbedingung |
| `payload.verification_contract` | Payload-Struktur | vom Ursprung prüfbare Postcondition/Evidence-Anforderung |
| `payload.deadline` | Payload-Timestamp/Null | Annahme-/Ausführungsgrenze |
| `payload.idempotency_key` | Payload-String | bindet den kanonischen Request-Body; widersprüchliche Wiederverwendung wird abgelehnt |

`delegation_id` beantwortet ADR-01 nicht. Es ist nur die zwingende Lifecycle-Identität
dieses Federation-Vertrags. ADR-02 ist für V1 akzeptiert: `correlation_id` referenziert
deterministisch die Delegation, während `message_id`, `origin_task_id` und `target_work_id`
eigene Identitätsrollen behalten.

Die Tabelle markiert die kanonische Lage: Envelope-IDs stehen top-level; fachliche
Delegationsfelder stehen in `payload`. `payload.delegation_id` muss bytegleich zum
top-level `correlation_id` sein. `target_work_id` entsteht erst im Admission-Resultat und
steht daher nicht im initialen Request.

Eine V1-Message muss außerdem `payload_hash`, `signature` und `signer_key` gemäß ADR-06
tragen. `message_id` wird vor der Signatur erzeugt; Relay/Hub darf signierte Felder nicht
mutieren.

### 3.2 Admission- und Receipt-Message

Agent City muss den Request vor jeder Ausführung entweder annehmen oder ablehnen. Die
Admission wird als `delegation_receipt` mit `receipt_stage=admission` übermittelt. Eine
Transport-Commit-Receipt kann davor als `receipt_stage=transport_committed` vom Relay/Hub
existieren; sie ist keine Annahme.

Die Wire-Lage bleibt auch hier eindeutig: Envelope-Felder stehen top-level; die folgenden
Felder stehen im `payload` der `delegation_receipt`.

| Feld | Pflicht | Vertrag |
|---|---:|---|
| `receipt_id` | ja | eindeutige, unveränderliche Identität genau dieses Receipts |
| `receipt_stage` | ja | exakt `transport_committed`, `admission`, `started` oder `verification`; `terminal` wird ausschließlich am Resultat geführt |
| `delegation_id` | ja | muss bytegleich zum top-level `correlation_id` sein |
| `subject_message_id` | ja | Message-ID, deren Verarbeitung diese Receipt-Stufe auslöste; nicht die eigene Receipt-Message-ID |
| `origin_task_id` | ja | Ursprungstask aus dem Request |
| `target_work_id` | ja | persistenter Zielarbeits-Handle; `null` ist nur für `transport_committed` und `admission=rejected` erlaubt, sonst Pflicht |
| `status` | ja | stufenspezifischer positiver oder negativer Status |
| `reason_code` | bei negativem Status | maschinenlesbarer Fehlergrund; kein freier Logtext als Primärgrund |
| `evidence_ref` | falls vorhanden | reproduzierbare Evidence-Referenz |
| `issuer_role` | ja | muss zur Receipt-Stufe gemäß ADR-09 passen |

Zusätzlich müssen die top-level Envelope-Felder `message_id` (eigene Receipt-Message), `correlation_id`,
`source_node_id`, `target_node_id`, `issued_at`, `expires_at`, `payload_hash`, `signature`
und `signer_key` gemäß §3.4 vorhanden sein. Ein Receipt darf keine stillen Null-/Bool-
Defaults für Pflichtfelder einführen.

Ein Start-Receipt verwendet dieselbe `delegation_receipt`-Operation mit
`receipt_stage=started`. Das terminale `task_completed`/`task_failed`-Resultat ist selbst
das `receipt_stage=terminal`-Receipt und trägt daher eine eigene `receipt_id`. Stille
Annahme oder stiller Start ist verboten.

Der verbindliche V1-Operationsatz für Delegation lautet:

| Operation | Richtung | Zweck |
|---|---|---|
| `delegate_task` | Origin → Target | Request |
| `delegation_receipt` | Relay/Target → Origin | `transport_committed`, `admission`, `started` oder `verification`-Receipt |
| `task_completed` | Target → Origin | terminales positives Resultat |
| `task_failed` | Target → Origin | terminales negatives Resultat |

`verification` wird primär als Origin-State/Receipt ausgestellt. Eine externe Attestation
verwendet `delegation_receipt` mit `receipt_stage=verification`; ein neues ungebundenes
Operationstoken ist nicht zulässig.

### 3.3 Terminal Result

V1 verwendet weiterhin die fachlichen Ausgänge `task_completed` und `task_failed`. Deren
Payload muss mindestens enthalten:

| Feld | Pflicht | Vertrag |
|---|---:|---|
| `delegation_id` | ja | muss bytegleich zum top-level `correlation_id` sein |
| `origin_task_id` | ja | Ursprungstask aus dem Request |
| `target_work_id` | ja | derselbe persistente Handle aus der Admission |
| `receipt_stage` | ja | exakt `terminal` für `task_completed` und `task_failed` |
| `terminal_status` | ja | `completed` oder `failed`; kein boolescher Delivery-Ersatz |
| `outcome` oder `failure` | genau eines | strukturierte fachliche Aussage passend zum Terminalstatus |
| `evidence_refs` | ja | Liste reproduzierbarer Belege; leer nur mit explizitem Failure-Code |
| `started_at` / `ended_at` | ja | RFC-3339-UTC-Zeitpunkte |
| `attempt_count` | ja | Zielseitiger Zähler dieses Delegations-Handles |
| `receipt_id` | ja | terminales Receipt, das dieses Resultat attestiert |
| `subject_message_id` | ja | Message-ID, deren Verarbeitung zum terminalen Resultat führte |
| `issuer_role` | ja | exakt `target_worker` oder `target_node` gemäß ADR-09 |

Zusätzlich trägt der Envelope die unveränderlichen IDs, Ziel-/Senderbindung, Zeit- und
Signaturfelder aus §3.4. Seine top-level `message_id` ist die Message-ID dieses terminalen
Ergebnisses; `correlation_id` bleibt `delegation_id`.

Titel, Branchname und PR-URL dürfen Zusatzfelder sein, niemals Primärkorrelation.

Die Ursprungsverifikation ist kein Ziel-Resultat. Sie wird im Origin-State als
`verification`-Receipt mit eigener `receipt_id` und `issuer_role=origin` geführt; eine
separate Outbound-Operation ist nur erforderlich, wenn ein anderer Peer diese Attestation
benötigt.

### 3.4 Kanonischer V1-Envelope und Signaturbytes

Jede V1-Message besitzt genau diese Pflichtfelder:

```text
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
```

`payload` ist ein JSON-Objekt; unbekannte Top-Level-Felder sind vor Spec-Freeze abzulehnen.
Eine spätere Extension muss eine neue `contract_version` oder einen ausdrücklich signierten
Extension-Namespace verwenden. `issued_at` und `expires_at` sind RFC-3339-UTC-Strings.

Für die Signatur wird zunächst der Envelope ohne exakt `payload_hash` und `signature`
gebildet. Dieser Body wird als UTF-8-JSON mit
`sort_keys=true`, `ensure_ascii=false`, `separators=(",", ":")` serialisiert; nicht
serialisierbare Werte sind ein Schemafehler. `payload_hash` ist der lowercase Hex-SHA-256
dieser Bytes. `signature` ist base64 der Ed25519-Signatur über die ASCII-Bytes dieses
Hex-Hashes. `signer_key` bleibt im signierten Body. `source_node_id` muss aus diesem
Public Key ableitbar sein. Die V1-Ableitung ist exakt `ag_` plus die ersten 16 lowercase
Hex-Zeichen von `SHA256(signer_key_hex_ascii)`, wobei `signer_key_hex_ascii` der
64-Zeichen-Hexstring des Raw-Public-Keys ist. Relays dürfen keinen signierten Schlüssel
hinzufügen, entfernen oder verändern.

Damit ist die Signaturbytefolge unabhängig von Python-`default=str`, JSON-Whitespace,
Hub-IDs oder Payload-Substring-Regeln. Die bestehende Steward-`exclude_hub_id`-Toleranz
ist Legacy und nicht V1.

## 4. Zustandsvertrag

Der Federation-Delegationsvertrag besitzt folgende V1-Zustände:

```text
CREATED
→ SENT
→ ACCEPTED
→ EXECUTING
→ RESULT_REPORTED
→ VERIFYING_AT_ORIGIN
→ VERIFIED | FAILED_VERIFICATION
```

Seitenausgänge:

```text
REJECTED
EXPIRED_BEFORE_ACCEPTANCE
EXPIRED_DURING_EXECUTION
FAILED_AT_TARGET
CANCELED
```

Receipt-Stufen sind separat und monoton:

```text
transport_committed → admission → started → terminal → verification
```

Eine fehlende Folgestufe ist `delivery_unknown`, `expired` oder `recovery_required`, nie
implizit Erfolg.

Diese Zustände ersetzen keine Managed-Task-, A2A- oder Sankalpa-Enums. Die genaue
Übersetzung bleibt Teil von ADR-10. Für V1 gelten aber folgende Invarianten:

1. `SENT` ist kein Erfolg.
2. `ACCEPTED` ist kein Ausführungserfolg.
3. `RESULT_REPORTED` ist keine verifizierte Wirkung.
4. Nur der Ursprung darf seine fachliche Postcondition als `VERIFIED` einstufen.
5. Ein Fehlerresultat darf nicht über denselben Übergang wie ein Erfolgsresultat pauschal
   zu `PENDING` übersetzt werden.
6. Jeder Übergang muss `delegation_id`, `correlation_id`, vorherigen Zustand und die
   erwartete `message_id`-/Receipt-Deduplizierung prüfen.
7. `ACCEPTED` legt den persistenten Admission-/Dedupe-Eintrag vor jeder lokalen Mission an.
8. `RECOVERY_REQUIRED` erlaubt keine automatische zweite Side Effect-Ausführung.

## 5. Targeting und Admission

### 5.1 Exaktes Targeting

- Der Transport muss `target_node_id` routen.
- Der Empfänger muss vor Fachdispatch prüfen, dass das Target seiner eigenen gebundenen
  Node-Identity entspricht.
- Broadcast ist für `delegate_task` verboten.
- Ein Relay darf den Zielknoten nicht aus Payload-Prosa ableiten oder überschreiben.
- `message_id`, `payload_hash`, `signature` und `signer_key` müssen beim Routing unverändert
  bleiben; Hub-/Relay-Metadaten werden nicht nachträglich in den signierten V1-Envelope
  eingefügt.

### 5.2 Admission-Gates

Vor Annahme müssen mindestens geprüft werden:

- Contract-Version unterstützt,
- Signatur und Senderbindung gültig,
- Target stimmt exakt,
- Request nicht expired,
- `delegation_id`/`idempotency_key` nicht widersprüchlich wiederverwendet,
- Sender erfüllt Trust-/Authority-Gate,
- Capability existiert und besitzt einen konkreten Handler,
- Repo und erlaubte Aktionen liegen innerhalb Authority,
- lokale Kapazität erlaubt Annahme,
- Wiring-Manifest weist für die Capability einen konkreten Handler und Resultatpfad aus.

Fehlende Handler oder Capability sind `rejected`, nicht still konsumiert.

## 6. Idempotenz, Duplicate und Recovery

ADR-08 ist für V1 akzeptiert. Es gelten folgende verbindliche Regeln:

- Derselbe `delegation_id` plus identischer kanonischer Request darf keine zweite lokale
  Mission erzeugen; der persistente Admission-/Dedupe-Eintrag wird vor Ausführung atomar
  geschrieben.
- Derselbe `delegation_id` mit abweichendem Request muss fail-closed abgelehnt und als
  Konflikt persistiert werden.
- Ein doppeltes terminales Resultat darf keinen zweiten Ursprungstransition auslösen.
- Nach Crash muss Agent City aus persistentem State entscheiden können, ob der Request
  unbekannt, angenommen, ausführend, `RECOVERY_REQUIRED` oder terminal ist.
- `EXECUTING` besitzt eine Lease-/Heartbeat-Grenze; Lease-Ablauf erzeugt
  `RECOVERY_REQUIRED`, nicht automatisch eine zweite Ausführung.
- Der Ursprung darf bei Timeout nicht blind neu ausführen; Retry behält die signierten Bytes
  und `message_id` der wiederholten Message.
- Nicht-idempotente Side Effects benötigen einen fachlichen Dedup-Key oder werden abgelehnt.
- Titel, Timestamp oder Listenposition dürfen nie als Dedup-Key dienen.

## 7. Authority und Safety

- Delegation überträgt nur die explizit serialisierte Authority.
- Agent City darf keine weitergehende Git-, GitHub-, Merge-, Secret- oder Runtime-Aktion
  aus allgemeiner Agentenrolle ableiten.
- Merge, Branch-Protection-Bypass, Secret-Zugriff und Context-Bridge-Aktivierung sind in V1
  standardmäßig außerhalb.
- Der Zielhandler muss die Authority vor lokaler Missionserzeugung prüfen.
- Eine Authority-Verletzung erzeugt ein strukturiertes Rejection-/Failure-Resultat.

## 8. Verification am Ursprung

V1 trennt Zielresultat und Ursprungsverifikation:

1. Agent City stellt Evidence gemäß `verification_contract` bereit und sendet ein
   `terminal`-Receipt/Resultat.
2. Steward korreliert ausschließlich über `delegation_id`/`correlation_id` und die
   unveränderliche Message-ID.
3. Steward beobachtet die Postcondition unabhängig, soweit sie extern beobachtbar ist.
4. Erst danach darf der Origin-State ein `verification`-Receipt mit `VERIFIED` oder
   `FAILED_VERIFICATION` ausstellen.
5. Tool Exit 0, PR-Erstellung oder ein grüner Target-Workflow allein erfüllen die
   Postcondition nicht.

ADR-09 ist für V1 akzeptiert: Transport, Admission, Start, Terminal und Verification sind
getrennte Receipt-Stufen mit rollenbegrenzten Ausstellern. Transportzustellung darf niemals
als Wirkungsnachweis ausgegeben werden.

## 9. Failure- und Receipt-Vertrag

Mindestens folgende maschinenlesbare Klassen müssen unterscheidbar bleiben:

- `unsupported_contract`
- `wrong_target`
- `signature_invalid`
- `authority_denied`
- `capability_unavailable`
- `duplicate_conflict`
- `expired`
- `target_execution_failed`
- `target_result_unverifiable`
- `origin_verification_failed`
- `delivery_unknown`
- `recovery_required`

Receipt-Aussteller sind hart begrenzt:

| `receipt_stage` | zulässiger `issuer_role` |
|---|---|
| `transport_committed` | `relay` oder `hub` |
| `admission` | `target_node` |
| `started` | `target_scheduler` |
| `terminal` | `target_worker` oder `target_node` |
| `verification` | `origin_node` |

Die Zuordnung zum GitHub-Workflow-Exit ist durch ADR-05 nicht entschieden. Unabhängig vom
Exit darf keine dieser Klassen ausschließlich als Logzeile enden.

## 10. Verbleibende ADR-Blocker

Für die vollständige V1-Spec bleiben folgende ADRs außerhalb dieses Sprints offen:

- ADR-05: Workflow-Wahrheit für Delivery-/Execution-Fehler,
- ADR-10: Adapter zu Managed Task, A2A und Sankalpa.

ADR-01, ADR-03 und ADR-04 bleiben ebenfalls offen. ADR-02, -06, -07, -08 und -09 sind
akzeptiert und in den Abschnitten §3–§9 normativ eingearbeitet. Diese Spec darf die übrigen
ADRs nicht implizit entscheiden.

## 11. Abgeleitete Test- und Crucible-Verträge

### 11.1 Rote Tests vor Produktcode

1. Agent City lehnt einen an anderen Node adressierten Request ab.
2. Agent City besitzt einen expliziten `delegate_task`-Handler; ohne Handler entsteht ein
   Rejection-Resultat.
3. Doppelte identische Request-Nachricht mit gleicher `message_id`/`idempotency_key` erzeugt
   genau ein `target_work_id` und wiederholt nur das bekannte Receipt.
4. Gleiche `delegation_id` mit abweichender Payload wird fail-closed abgelehnt.
5. Zwei Tasks mit identischem Titel werden anhand ihrer IDs korrekt getrennt.
6. Erfolgs- und Fehlerresultat nehmen verschiedene Transitionen.
7. Der V1-Golden-Envelope wird von Agent City akzeptiert; manipulierte Payload, falscher
   Key, falsches Target, Hub-Mutation und nicht kanonische JSON-Bytes werden abgelehnt.
8. Crash nach Acceptance erzeugt nach Recovery keine zweite Ausführung.
9. Doppeltes terminales Resultat/Receipt verändert den Ursprung nur einmal; widersprüchliche
   Resultate erzeugen `duplicate_conflict`.
10. Receipt-Aussteller außerhalb ihrer Rolle werden abgelehnt; Target-Workflow grün bei
    fehlender Postcondition endet am Ursprung
    `FAILED_VERIFICATION`, nicht `VERIFIED`.

### 11.2 Repoübergreifender Crucible

Ein Test muss reale Wire-Bytes aus Steward durch den tatsächlichen Transport und den
Agent-City-Ingress führen. Mock-Nachrichten, die ein eigenes Signaturformat erfinden,
reichen nicht.

Der minimale positive Ablauf:

```text
Request → Acceptance → genau eine lokale Mission → terminales Resultat
→ Rückkorrelation über IDs → unabhängige Postcondition → VERIFIED
```

Störfälle:

- doppelte Nachricht,
- stale/expired Nachricht,
- falsches Target,
- falsche Signatur,
- Crash nach Acceptance,
- Delivery unbekannt,
- Resultat doppelt,
- Resultat für falsche Delegation,
- Verification scheitert.

## 12. Migration und Rollout

Noch keine Migration ist autorisiert. Eine spätere Implementierung muss getrennte,
reviewbare Schritte verwenden:

1. Wire-/Crypto-Contract und Cross-Repo-Golden-Fixtures nach ADR-06,
2. Wiring-Manifest/Auditor-Vertrag nach ADR-07,
3. Agent-City-Admission ohne Ausführung,
4. persistente ID-/Idempotenzgrenze und Lease nach ADR-08,
5. gestufte Receipt-Stufen nach ADR-09,
6. genau ein Capability-Handler,
7. terminaler Resultatpfad,
8. Ursprungsverifikation,
9. kontrollierter Crucible.

Der bestehende Titelcallback darf während einer Migration nur beobachtet, niemals als
Fallback für V1 verwendet werden. Aktivierung benötigt ein separates Operator-Gate.

## 13. Definition of Ready für Spec Freeze V1

- ADR-02/-06/-07/-08/-09 akzeptiert und gegen diesen Contract reconciliiert,
- ADR-05 und ADR-10 entschieden,
- Wire-Schemas vollständig und kanonisch serialisierbar,
- jede Transition mit Vor-/Nachbedingung und Failure-Pfad,
- Authority-/Target-/Crypto-Grenze adversarial reviewt,
- Tests aus §11 als ausführbare rote Verträge präzisiert,
- Migration ohne Broadcast- oder Titel-Fallback,
- Context Bridge weiterhin geparkt,
- zwei unabhängige Reviews finden keine kritische Mehrdeutigkeit,
- ein vollständiger Widerspruchsreview bestätigt, dass kein Text auf Titelmatching,
  Broadcast, boolesche Delivery-Bestätigung oder implizite Signaturbytes zurückfällt.

Bis dahin bleibt diese Fassung `DRAFT 0.2` und autorisiert keinen Produktcode.
