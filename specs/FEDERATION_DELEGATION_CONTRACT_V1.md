# FEDERATION DELEGATION CONTRACT V1

> **Status:** DRAFT 0.1 — PREPARED FOR ADR + ADVERSARIAL REVIEW; NOT IMPLEMENTATION-READY
> **Datum:** 2026-07-18
> **IST-Basis:** `specs/execution_truth_map/EXECUTION_TRUTH_MAP_RECON.md`
> **ADR-Basis:** `specs/execution_truth_map/ADR_BACKLOG.md`
> **Sperre:** Kein Produktcode, keine Aktivierung und kein Cross-Repo-Merge aus dieser Fassung.

---

## 0. Dokumentrolle

Diese Spec bereitet ausschließlich den Vertrag für eine gezielte, korrelierbare und
verifizierbare Delegation zwischen Steward und Agent City vor. Sie ist keine
Execution-Spine-Spec und führt kein universelles Execution-Modell ein.

Die Abschnitte sind bewusst getrennt:

- §1–2: belegtes IST,
- §3–9: SOLL-Vertrag für Federation Delegation V1,
- §10: offene ADR-Blocker,
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

## 3. Vertragsobjekte

### 3.1 Delegation Request

Ein V1-Request benötigt mindestens folgende semantische Felder. Die endgültige Wire-
Serialisierung bleibt bis ADR-06/ADR-07 reviewpflichtig.

| Feld | Typ | Vertrag |
|---|---|---|
| `contract_version` | String | exakt unterstützte Delegation-Version |
| `delegation_id` | opaque String | über den gesamten Delegationspfad unverändert; V1-lokal, keine universelle Execution-ID-Behauptung |
| `origin_task_id` | String | exakte persistente Task-ID beim Ursprung |
| `source_node_id` | String | kryptographisch gebundener Sender |
| `target_node_id` | String | exakter kryptographischer Zielknoten |
| `capability` | String | verlangte Fähigkeit, nicht freier Rollentitel |
| `intent` | strukturierter Wert | erlaubter, versionierter Intent; keine reine Prosa als Dispatchschlüssel |
| `task_title` | String | nur Darstellung; niemals Korrelation oder Idempotenz |
| `task_description` | String | begrenzter Arbeitskontext |
| `target_repo` | String/Null | kanonischer Repository-Identifier |
| `authority` | strukturierter Wert | erlaubte Aktionen und ausdrücklich verbotene Aktionen |
| `expected_outcome` | strukturierter Wert | fachliche Zielbedingung |
| `verification_contract` | strukturierter Wert | vom Ursprung prüfbare Postcondition/Evidence-Anforderung |
| `deadline` | Timestamp/Null | Annahme-/Ausführungsgrenze |
| `idempotency_key` | String | stabile Retry-/Duplicate-Grenze |

`delegation_id` beantwortet ADR-01/02 nicht. Es ist nur die zwingende Identität dieses
Federation-Vertrags. Ob und wie es später an eine universelle Execution-ID gebunden wird,
bleibt offen.

### 3.2 Admission Result

Agent City muss den Request vor jeder Ausführung entweder annehmen oder ablehnen.

Mindestfelder:

- `contract_version`
- `delegation_id`
- `origin_task_id`
- `source_node_id`
- `target_node_id`
- `admission_status`: `accepted` oder `rejected`
- maschinenlesbarer `reason_code`
- bei Annahme: persistente `target_work_id`
- Timestamp und Signaturbindung

Die endgültige Operation und die Einordnung als Receipt hängen von ADR-09 ab. Unabhängig
davon ist stille Annahme verboten.

### 3.3 Terminal Result

V1 verwendet weiterhin die fachlichen Ausgänge `task_completed` und `task_failed`, aber
deren Payload muss mindestens enthalten:

- `contract_version`
- `delegation_id`
- `origin_task_id`
- `target_work_id`
- `source_node_id`
- `target_node_id`
- terminaler Status
- strukturierter Outcome oder Failure
- Evidence-Referenzen
- Start-/Endzeit
- Wiederholungs-/Attempt-Zähler, falls vorhanden
- Signaturbindung

Titel, Branchname und PR-URL dürfen Zusatzfelder sein, niemals Primärkorrelation.

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

Diese Zustände ersetzen keine Managed-Task-, A2A- oder Sankalpa-Enums. Die genaue
Übersetzung bleibt Teil von ADR-10. Für V1 gelten aber folgende Invarianten:

1. `SENT` ist kein Erfolg.
2. `ACCEPTED` ist kein Ausführungserfolg.
3. `RESULT_REPORTED` ist keine verifizierte Wirkung.
4. Nur der Ursprung darf seine fachliche Postcondition als `VERIFIED` einstufen.
5. Ein Fehlerresultat darf nicht über denselben Übergang wie ein Erfolgsresultat pauschal
   zu `PENDING` übersetzt werden.
6. Jeder Übergang muss `delegation_id` und vorherigen Zustand prüfen.

## 5. Targeting und Admission

### 5.1 Exaktes Targeting

- Der Transport muss `target_node_id` routen.
- Der Empfänger muss vor Fachdispatch prüfen, dass das Target seiner eigenen gebundenen
  Node-Identity entspricht.
- Broadcast ist für `delegate_task` verboten.
- Ein Relay darf den Zielknoten nicht aus Payload-Prosa ableiten oder überschreiben.

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
- lokale Kapazität erlaubt Annahme.

Fehlende Handler oder Capability sind `rejected`, nicht still konsumiert.

## 6. Idempotenz, Duplicate und Recovery

Bis ADR-08 entschieden ist, gelten folgende Mindestinvarianten:

- Derselbe `delegation_id` plus identischer kanonischer Request darf keine zweite lokale
  Mission erzeugen.
- Derselbe `delegation_id` mit abweichendem Request muss fail-closed abgelehnt und als
  Konflikt persistiert werden.
- Ein doppeltes terminales Resultat darf keinen zweiten Ursprungstransition auslösen.
- Nach Crash muss Agent City aus persistentem State entscheiden können, ob der Request
  unbekannt, angenommen, ausführend oder terminal ist.
- Der Ursprung darf bei Timeout nicht blind neu ausführen; er muss Status/Recovery gemäß
  dem späteren ADR-08-Vertrag klären.
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

1. Agent City stellt Evidence gemäß `verification_contract` bereit.
2. Steward korreliert ausschließlich über die stabilen Vertrags-IDs.
3. Steward beobachtet die Postcondition unabhängig, soweit sie extern beobachtbar ist.
4. Erst danach darf der Federation-Vertrag `VERIFIED` erreichen.
5. Tool Exit 0, PR-Erstellung oder ein grüner Target-Workflow allein erfüllen die
   Postcondition nicht.

Welche Evidence als Receipt gilt und wer sie attestiert, bleibt ADR-09. V1 verbietet
jedoch, Transportzustellung als Wirkungsnachweis auszugeben.

## 9. Failure-Vertrag

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

Die Zuordnung zum GitHub-Workflow-Exit ist durch ADR-05 nicht entschieden. Unabhängig vom
Exit darf keine dieser Klassen ausschließlich als Logzeile enden.

## 10. Offene ADR-Blocker

Vor Spec-Freeze müssen mindestens entschieden sein:

- ADR-02: Beziehung zwischen Delegation-, Correlation- und Message-ID,
- ADR-05: Workflow-Wahrheit für Delivery-/Execution-Fehler,
- ADR-06: kanonischer Federation-Signaturvertrag,
- ADR-07: maschinenlesbare Capability-/Handler-Deklaration,
- ADR-08: Retry-/Recovery-Idempotenz,
- ADR-09: Receipt-Stufen und Aussteller,
- ADR-10: Adapter zu Managed Task, A2A und Sankalpa.

ADR-01, ADR-03 und ADR-04 bleiben für die spätere übergreifende Architektur offen. Diese
Spec darf sie nicht implizit entscheiden.

## 11. Abgeleitete Test- und Crucible-Verträge

### 11.1 Rote Tests vor Produktcode

1. Agent City lehnt einen an anderen Node adressierten Request ab.
2. Agent City besitzt einen expliziten `delegate_task`-Handler; ohne Handler entsteht ein
   Rejection-Resultat.
3. Doppelte identische Request-Nachricht erzeugt genau ein `target_work_id`.
4. Gleiche `delegation_id` mit abweichender Payload wird fail-closed abgelehnt.
5. Zwei Tasks mit identischem Titel werden anhand ihrer IDs korrekt getrennt.
6. Erfolgs- und Fehlerresultat nehmen verschiedene Transitionen.
7. Reales Steward-Signaturformat wird von Agent City akzeptiert; manipulierte Payload,
   falscher Key und falsches Target werden abgelehnt.
8. Crash nach Acceptance erzeugt nach Recovery keine zweite Ausführung.
9. Doppeltes terminales Resultat verändert den Ursprung nur einmal.
10. Target-Workflow grün bei fehlender Postcondition endet am Ursprung
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

1. Wire-/Crypto-Contract und Cross-Repo-Fixtures,
2. Agent-City-Admission ohne Ausführung,
3. persistente ID-/Idempotenzgrenze,
4. genau ein Capability-Handler,
5. terminaler Resultatpfad,
6. Ursprungsverifikation,
7. kontrollierter Crucible.

Der bestehende Titelcallback darf während einer Migration nur beobachtet, niemals als
Fallback für V1 verwendet werden. Aktivierung benötigt ein separates Operator-Gate.

## 13. Definition of Ready für Spec Freeze V1

- alle §10-Blocker als ADR entschieden,
- Wire-Schemas vollständig und kanonisch serialisierbar,
- jede Transition mit Vor-/Nachbedingung und Failure-Pfad,
- Authority-/Target-/Crypto-Grenze adversarial reviewt,
- Tests aus §11 als ausführbare rote Verträge präzisiert,
- Migration ohne Broadcast- oder Titel-Fallback,
- Context Bridge weiterhin geparkt,
- zwei unabhängige Reviews finden keine kritische Mehrdeutigkeit.

Bis dahin bleibt diese Fassung `DRAFT 0.1` und autorisiert keinen Produktcode.
