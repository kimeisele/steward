# FEDERATION DELEGATION IMPLEMENTATION PLAN 01

> Status: DRAFT FOR AGENT-B REVIEW — kein Produktcode in diesem Dokument-Schritt
> Version: 0.1
> Datum: 2026-07-18
> Scope: kleinster realer vertikaler Federation-V1-Slice
> Gate: Golden Wire Fixtures 01A akzeptiert; Draft 0.5 normativ eingefroren

Dieses Dokument ist die vollständige Entscheidungsvorlage für den ersten
Implementierungsschritt. Es autorisiert noch keine Codeänderung. Es trennt bewusst den
kleinen ersten Wirkungspfad von Recovery, Worker-Ausführung, Verification und Workflow-
Eskalation.

## 1. Evidenz- und Arbeitsbasis

Normative und reproduzierbare Pins:

| Artefakt | Pin | Bedeutung |
|---|---|---|
| Federation Contract | `specs/FEDERATION_DELEGATION_CONTRACT_V1_DRAFT_0_5.md`, Spec-Pin `ddf170d10a5d546af4b012a2d2335c37fcb44508` | geschlossene V1-Wire-, ID-, Signatur-, Receipt- und Ledger-Regeln |
| Steward Golden Fixtures 01A | `e00324c8532f3afae5133d8594f1ff4f535d1dd8` | unabhängige Steward-Regeneration und 17 Negativgrenzen |
| Agent City Golden Fixtures 01A | `bca0358191d52a04da1857ac313346c3e0f641fd` | unabhängige Agent-City-Regeneration und dieselbe Negativmatrix |
| Fixture Manifest | `tests/fixtures/federation_v1/manifest.json` | deterministische Seeds, Werte und Artefakt-SHA-256 |
| Fixture Report | `specs/execution_truth_map/GOLDEN_WIRE_FIXTURES_01_REPORT.md` | Abnahmebeleg 01A |

Historische Truth-Map-Live-Pins bleiben Befund und werden vor Implementierung erneut live
gepinnt. Sie werden nicht als Beweis für den heutigen Runtime-Stand behandelt. Heartbeat-
Commits gehören ausdrücklich nicht in eine Historienbewertung; für diesen Plan wird keine
Heartbeat-Historie als Signal verwendet.

## 2. Ziel und kleinster zugelassener Slice

### Entscheidung

Der erste Produkt-Slice ist:

```text
Steward baut signierten V1-delegate_task-Request
  -> exakter Target-Transport zum Agent City
  -> Agent City validiert SFDJ-1, Provenance, Signatur, Authority und Target
  -> Target-Ledger commitet durable Admission vor jedem Side Effect
  -> Agent City signiert delegation_receipt(admission)
  -> Receipt erreicht Steward und wird über delegation_id/request_message_id korreliert
```

Der Slice erzeugt bei erfolgreicher Admission genau einen `target_work_id`, legt aber
keinen Worker/Mission-Lauf an und führt kein Tool aus. Damit ist erstmals echter
Produktcode zulässig, ohne die Semantik von Execution, Verification oder Managed-Task-
Abschluss vorwegzunehmen.

### Im Slice enthalten

- repo-lokale Produktionsgrenzen für SFDJ-1 und Ed25519-V1-Verifikation;
- ein expliziter Steward-Origin-Producer für den eingefrorenen `delegate_task`-Vertrag;
- signierter V1-Ingress im Agent City;
- exaktes `target_node_id`-Matching ohne Broadcast;
- Root-/Signing-Key-Registry-Prüfung und Authority-Prüfung;
- persistenter Target-Admission-/Dedupe-Ledger;
- `accepted`- und fachlich begründete `rejected`-Admission-Receipt;
- originseitiger Admission-Ledger mit ID-Korrelation, ohne Titel-Substring-Matching;
- Wiring-Manifest-Einträge und repoübergreifende Tests.

### Ausdrücklich nicht enthalten

- Worker-, Mission- oder Tool-Ausführung;
- `started`, `terminal` und `verification` Receipts;
- Status-Query/Status-Snapshot als produktive Capability;
- Lease, Crash-Recovery, `RECOVERY_REQUIRED`-Entscheidung oder automatischer Retry;
- Provider-Failover, Execution Spine, Context Bridge oder Workflow-Eskalation;
- ManagedTask-Statusänderung auf `COMPLETED` oder automatische Resultat-Anwendung;
- Merge-Autorität, Push, Deployment oder Produktionsaktivierung;
- automatische Root-Recovery, Quorum oder Governance.

Ein Admission-Receipt beweist ausschließlich die durable Target-Entscheidung. Es beweist
weder Start noch Ausführung noch eine Postcondition.

## 3. Produktionsgrenzen und Verantwortungsaufteilung

### 3.1 SFDJ-1 und Crypto

Es wird im ersten Slice keine gemeinsame Runtime-Library zwischen Steward und Agent City
eingeführt. Beide Repositories erhalten einen kleinen, repo-lokalen V1-Adapter mit derselben
normativen Schnittstelle und denselben Golden Fixtures. Die Adapter dürfen ihre bestehende
lokale Crypto-/JSON-Infrastruktur verwenden, müssen aber alle Draft-0.5-Regeln explizit
testen:

- SFDJ-1-Kanonisierung und bytegleiche Eingangsprüfung;
- geschlossene Envelope-/Payload-Schemas;
- RFC-3339-Profil, Größenlimits und Base64-Regeln;
- `message_hash`, Domain Separation und Ed25519-Signatur;
- Root-Enrollment-/Signing-Certificate-Provenance;
- `request_digest` und deterministischer `idempotency_key`.

Golden Fixtures bleiben die Paritätsgrenze; ein späteres gemeinsames Paket darf erst nach
bewiesener Produktionsparität als separates Design entschieden werden.

### 3.2 Transportcarrier versus V1-Wire

Der bestehende dateibasierte Nadi-/Federation-Transport bleibt Carrier und ist nicht der
V1-Signaturvertrag. Damit keine Legacy-JSON-Serialisierung die kanonischen V1-Bytes
verändert, transportiert der Carrier:

```json
{
  "operation": "federation_v1.delegate_task",
  "source": "<origin node_id>",
  "target": "<target node_id>",
  "payload": {
    "wire_bytes_b64": "<RFC-4648-Base64 der exakten SFDJ-1-Bytes>",
    "wire_version": "federation-delegation-v1"
  }
}
```

Der Carrier ist nicht signiert und erhält keine Autorität. Der Agent-City-V1-Adapter
dekodiert `wire_bytes_b64` und prüft ausschließlich die darin enthaltenen V1-Bytes. Der
Carrier `target` muss ebenfalls exakt dem V1-`target_node_id` entsprechen; `*`, Broadcast,
Peer-Liste oder implizites Routing sind verboten. Unbekannte oder nicht adressierte Carrier
werden lokal quarantänisiert und erzeugen keine Netzwerkantwort.

Die Legacy-Carrier-Felder `timestamp`, `ttl_s`, `correlation_id` und generische Payload-
Schlüssel dürfen nicht als Ersatz für V1-IDs oder V1-Zeitwerte verwendet werden.

## 4. Konkreter Pfad und Verantwortlichkeiten

### 4.1 Steward-Origin

Ein neuer, expliziter V1-Origin-Service beziehungsweise Adapter (geplanter Symbolname:
`FederationDelegationV1Origin`) übernimmt:

1. Entgegennahme einer bereits autorisierten, strukturierten Delegationsspezifikation;
2. Erzeugung von `delegation_id`, `origin_task_id` und initialer `message_id` genau einmal;
3. Aufbau des geschlossenen `delegate_task`-Payloads;
4. Berechnung und Prüfung von `request_digest` und `idempotency_key`;
5. Signatur mit dem aktivierten Steward Signing-Key;
6. Persistenz des Origin-Ledger-Eintrags vor dem Sendversuch;
7. Verpackung der exakten Envelope-Bytes in den Transportcarrier;
8. Korrelation eingehender Admission-Receipts über `delegation_id` und
   `request_message_id`.

Die erste Implementierung wird nicht automatisch aus dem freien `DelegateToPeerTool.title`
gebaut. `DelegateToPeerTool` bleibt bis zu einer separaten Migration als Legacy-Pfad
isoliert. Für den Slice gibt es eine explizite strukturierte API/Test-Entry-Point; dadurch
werden keine fehlenden Authority-, Outcome- oder Deadline-Felder aus Prosa erraten.

Der Origin-Ledger speichert mindestens:

```text
delegation_id, origin_task_id, request_message_id, correlation_id,
target_node_id, request_digest, idempotency_key, request_message_hash,
send_state, admission_receipt_id?, target_work_id?, last_evidence_hash?
```

`send_state` ist für diesen Slice auf `created`, `sent`, `admission_received` oder
`admission_rejected` begrenzt. Kein Eintrag wird als `COMPLETED` oder `VERIFIED` markiert.

### 4.2 Agent-City-Transportadapter

Ein V1-spezifischer Empfangspfad (geplanter Symbolname:
`FederationDelegationV1Ingress`) liest den Carrier vor dem generischen Legacy-Directive-
Pfad. Er:

1. akzeptiert nur `operation=federation_v1.delegate_task`;
2. prüft Carrier-Target gegen die lokale Node-ID;
3. dekodiert `wire_bytes_b64` ohne Neuserialisierung;
4. führt die Draft-0.5-Fail-Closed-Reihenfolge aus;
5. übergibt nur ein validiertes `delegate_task`-Objekt an den Admission-Handler;
6. übergibt ungültige oder falsch adressierte Nachrichten an lokale Finding/Quarantine;
7. reicht V1-Nachrichten nicht an generische Directive- oder Worker-Handler weiter.

Der bestehende Legacy-`FederationNadi.receive()`-Pfad bleibt für Legacy-Nachrichten
funktionsfähig, ist aber kein V1-Dedupe. Der V1-Adapter darf sich nicht auf dessen
`source:timestamp`-In-Memory-Deduplizierung verlassen; V1-Deduplizierung gehört in den
persistenten Target-Ledger.

### 4.3 Agent-City-Admission-Handler

Der geplante Handler (`FederationDelegationV1AdmissionHandler`) verarbeitet ausschließlich
`operation=delegate_task`, `contract_version=federation-delegation-v1` und die Capability
`fix_repository` aus dem eingefrorenen Wiring-Manifest.

Fail-Closed-Reihenfolge:

1. Carrier-Target und Größenlimit;
2. UTF-8, Duplicate-Key, SFDJ-1 und geschlossene Schemafelder;
3. Version, IDs, Zeitfenster, Base64 und Payload-Größen;
4. Root-/Certificate-Provenance, aktiver Signing-Key und `node_id`-Bindung;
5. `message_hash` und Domain-separated Ed25519-Signatur;
6. exaktes Target, Origin-Authority und `target_repo`-Scope;
7. `request_digest`, `idempotency_key` und persistente Deduplizierung;
8. atomarer Admission-Commit;
9. signiertes Admission-Receipt.

Ungültige, nicht authentifizierte, falsch adressierte oder nicht autorisierte Eingänge
erzeugen nur lokales Finding/Quarantine und keine automatische Netzwerkantwort. Ein
authentifizierter V1-Request darf bei fachlicher Ablehnung ein signiertes `admission`-
Receipt mit `status=rejected` erhalten.

### 4.4 Target-Admission-Ledger

Der erste Ledger ist bewusst klein und repo-lokal. Er wird unter dem bestehenden
Federation-Datenbereich atomar persistiert (konkreter Pfad wird im Code-Review gegen den
Live-State bestätigt; keine neue Datenbankplattform im Plan). Eine Transaktion umfasst:

```text
received -> validated -> admitted|rejected
```

Bei `admitted` werden in derselben durable Operation gespeichert:

```text
delegation_id
request_message_id
correlation_id (= delegation_id)
origin_node_id
target_node_id (lokale Node-ID)
request_digest
idempotency_key
request_message_id/message_hash
target_work_id (opaque, einmalig erzeugt)
admission_receipt_id
admission_receipt_content_digest
state=ACCEPTED
```

Es gibt keinen Worker-Handle außerhalb dieses Ledger-Eintrags und keinen Side Effect vor
dem Commit. `target_work_id` ist genau einmal pro `delegation_id` zulässig.

Dedupe-Regeln im Slice:

- identische `message_id` und identische Bytes: lokaler No-op; vorhandenes Admission-
  Receipt wird erneut transportiert, ohne neue Arbeit;
- gleiche `delegation_id` mit identischem `request_digest`: vorhandener Ledger-Eintrag,
  kein neuer `target_work_id`;
- gleiche `delegation_id` mit anderem Digest: `duplicate_conflict`, fail-closed;
- gleiche `message_id` mit anderen Bytes: `message_id_conflict`, fail-closed;
- gültiger Request nach `REJECTED` wird nicht automatisch neu ausgeführt;
- Crash-/Lease-/Recovery-Zustände werden nicht implementiert, sondern als explizit
  ausstehender Folgescope dokumentiert.

### 4.5 Admission-Receipt

Der Target-Handler erzeugt für eine neue akzeptierte Admission ein
`delegation_receipt` mit:

```text
receipt_stage = admission
issuer_role = target_node
status = accepted
delegation_id = Request-Payload delegation_id
target_work_id = durable Ledger-ID
request_message_id = erste Request-message_id
correlation_id = delegation_id
receipt_content_digest = Digest des semantischen Receipt-Inhalts
```

Für fachlich authentifizierte Ablehnungen gilt `issuer_role=target_node`,
`status=rejected`, kein `target_work_id` und ein zulässiger `reason_code` aus Draft 0.5.
Ein Receipt enthält keine Worker-, Stacktrace-, Pfad- oder Secret-Daten.

Transport-Retransmission desselben Receipt verwendet identische Bytes und dieselbe
`message_id`/`receipt_id`. Eine echte Application-Reissue ist im ersten Slice nicht
implementiert; sie bleibt dem Recovery-/Status-Slice vorbehalten.

### 4.6 Origin-Korrelation

Der Steward-Receipt-Handler akzeptiert eine Admission nur, wenn:

- Signatur, Target, Registry und Receipt-Schema gültig sind;
- `request_message_id` auf den gespeicherten Request-Root zeigt;
- `delegation_id`, `correlation_id`, `request_digest` und `target_work_id` zum Origin-
  Ledger passen;
- die Receipt-ID und der `receipt_content_digest` noch nicht widersprüchlich gespeichert
  sind.

Die Zuordnung erfolgt ausschließlich über diese IDs. Titel, Beschreibung, Listenposition,
`delegated:<title>`-Substring und implizite Peer-Reihenfolge sind im V1-Pfad verboten.
Der bestehende Legacy-Callback darf unverändert weiterlaufen, wird aber nicht durch ein
V1-Receipt ausgelöst.

## 5. Capability-Wiring-Manifest für Slice 01

Das Manifest wird als testbares Dokumentationsartefakt angelegt; es ist kein Ersatz für
Code- oder E2E-Belege. Die erwarteten Einträge sind:

| Capability | Richtung | Emitter | Exaktes Target | Transport | Admission/Fachhandler | Authority | Idempotenz | Result/Receipt | Slice-Status vor Crucible |
|---|---|---|---|---|---|---|---|---|---|
| `delegate_task` | Steward -> Agent City | `FederationDelegationV1Origin` | `target_node_id` und Carrier-Target identisch | V1-Nadi-Carrier mit `wire_bytes_b64` | `FederationDelegationV1Ingress` -> `FederationDelegationV1AdmissionHandler` | Root-zertifizierter Origin-Key, Capability `fix_repository`, geschlossene Authority | Target-Admission-Ledger keyed by `delegation_id` + `request_digest`, Message-Dedupe | `delegation_receipt(admission)` | `code_complete` erst nach Contract-/Cross-Repo-Tests, sonst `partially_wired` |
| `delegation_receipt` (admission) | Agent City -> Steward | Admission-Receipt-Emitter | gespeicherter Origin-Node | gleicher Carrier, kein Broadcast | Origin-Receipt-Validator | Target-Key, Receipt-Root/Kausalität | `receipt_id` + `receipt_content_digest` | `admission accepted|rejected` | `partially_wired` bis Origin-Korrelationstest grün |
| `delegation_status_query` | Origin -> Agent City | keiner in Slice 01 | — | — | nicht implementiert | read-only Authority später | — | `delegation_status` später | `declared`, `unavailable`, `disabled` |
| `delegation_status` | Agent City -> Origin | keiner in Slice 01 | — | — | nicht implementiert | Target privacy contract später | — | Snapshot später | `declared`, `unavailable`, `disabled` |

`active` wird für keine Capability vor dem repoübergreifenden Crucible gesetzt. `legacy`
bleibt für bestehende `OP_DELEGATE_TASK`-Payloads ohne V1-Envelope erhalten; sie dürfen
nicht als V1-Implementierungsbeweis zählen. `implemented` wird nicht verwendet; die
Draft-0.5-Achsen `lifecycle_maturity` und `disposition` sind maßgeblich.

## 6. Migration und Legacy-Isolation

1. **Inventar-Gate:** Vor Code werden die aktuellen Steward-, Agent-City- und
   Steward-Protocol-HEADs live gepinnt. Heartbeat-Commits werden aus jeder Historien-
   bewertung ausgeschlossen.
2. **Additive Adapter:** V1-Validator, Carrier und Ledger werden additiv eingeführt. Der
   bestehende Legacy-Handler wird nicht umgedeutet und erhält keine stillen V1-Felder.
3. **Explizite Erkennung:** Nur Carrier `federation_v1.delegate_task` mit vollständigem
   `wire_bytes_b64` gelangt in V1. Legacy `OP_DELEGATE_TASK` bleibt ein separater,
   `legacy` markierter Pfad.
4. **Keine Rückwärtskonversion:** V1-IDs werden nicht aus Titeln oder alten Timestamps
   rekonstruiert. Legacy-Nachrichten bekommen keine erfundene `delegation_id`.
5. **Disabled by default:** Ein Feature-Gate darf den Codepfad in Tests öffnen, bleibt in
   produktiven Default-Konfigurationen deaktiviert, bis der Crucible und die reguläre
   CI-/PR-Prüfung grün sind.
6. **Kein Managed-Task-Mapping:** Der erste Slice schreibt nur Origin-/Target-Ledger.
   Die Entscheidung, wann ein verifiziertes Ergebnis einen Managed Task abschließt,
   bleibt ADR-03 und einem späteren Slice vorbehalten.

## 7. Test- und Rollout-Sequenz

### Gate A — repo-lokale Produktionsgrenzen

- Steward und Agent City verifizieren alle positiven Golden Fixtures mit den geplanten
  Produktionsadaptern;
- alle 17 Negativ-Fixtures scheitern an derselben ersten Phase;
- keine Runtime-Importe zwischen den Repositories;
- Legacy-Federation-Tests bleiben grün.

### Gate B — Target-Ledger-Unit-Tests

- gültige Admission erzeugt genau einen Ledger-Eintrag und genau einen `target_work_id`;
- identische Wiederholung ist No-op und erzeugt keinen zweiten Work-Handle;
- gleiche Delegation mit anderem Digest ergibt `duplicate_conflict`;
- gleiche Message-ID mit anderen Bytes ergibt `message_id_conflict`;
- falsches Target, falscher Key, nicht zertifizierter Key und nicht authentifizierter
  Eingang erzeugen lokale Quarantine ohne Netzwerkantwort;
- fachliche Authority-Ablehnung erzeugt ein korrekt signiertes `admission=rejected`-
  Receipt;
- Crash-Simulation vor Ledger-Commit erzeugt keinen Admission-Handle. Crash-Recovery
  nach Commit ist ein negativer Scope-Test: nicht implementiert, kein blinder Re-Run.

### Gate C — Carrier- und Korrelationstests

- Carrier verändert die inneren V1-Bytes nicht;
- Carrier-Target und V1-Target müssen identisch sein;
- Receipt kommt mit neuem Receipt-`message_id`, aber unverändertem Request-Root zurück;
- Origin korreliert nur über `delegation_id`, `request_message_id`, Digest und Receipt-ID;
- zwei gleiche Titel mit unterschiedlichen IDs werden getrennt behandelt;
- keine V1-Message aktiviert den Legacy-Titelcallback.

### Gate D — erster Cross-Repo-Crucible

Der Crucible ist bewusst auf Admission begrenzt:

```text
Steward V1-Origin erzeugt Request
 -> Carrier liefert exakt adressiert an Agent City
 -> Agent City validiert und commitet ACCEPTED + target_work_id
 -> Agent City sendet signiertes admission-Receipt
 -> Steward verifiziert und persistiert admission_received
 -> kein Worker, kein Tool, kein Git-Write, kein ManagedTask-COMPLETED
```

Adversariale Varianten: Transport-Duplikat, gleiche Delegation/anderer Digest,
gleiche Message-ID/andere Bytes, falsches Target, falscher Signing-Key, nicht autorisierte
Capability und ungekoppeltes Receipt. Für jede Variante gilt: sichtbarer Finding-/Reject-
Code, keine zusätzliche Arbeit, keine Netzwerkantwort bei unauthentifiziertem Eingang.

### Gate E — Rollout

- CI auf beiden Branches und reguläre PR-Prüfung;
- Wiring-Manifest aktualisiert: `code_complete`, aber noch nicht `active`, solange kein
  Crucible-Beleg vorliegt;
- Feature-Gate bleibt deaktiviert bis Agent-B-Abnahme des Plans und des Implementierungs-
  Diffs;
- nach Crucible kann ein separater Aktivierungsentscheid getroffen werden. Dieser Plan
  autorisiert keine Aktivierung und keinen Merge.

## 8. Definition of Done für Implementierungsslice 01

Der Slice ist nur dann abgeschlossen, wenn alle folgenden Aussagen belegbar sind:

1. Draft-0.5-Golden-Wire-Bytes werden in beiden Produktionsgrenzen verifiziert.
2. Ein echter Steward->Agent-City-Transportlauf erzeugt durable Admission vor jedem
   Side Effect.
3. `target_work_id` entsteht höchstens einmal pro `delegation_id`.
4. Das Admission-Receipt ist signiert, schema-valid, request-root-korreliert und beim
   Origin genau einmal anwendbar.
5. Falsches Target, falscher/unerlaubter Key, Digest-Konflikt und Message-Konflikt sind
   fail-closed und maschinenlesbar sichtbar.
6. Legacy-`OP_DELEGATE_TASK` und Titelmatching sind im V1-Pfad nicht erreichbar.
7. Wiring-Manifest, positive/negative Unit-Tests und der Admission-Crucible sind grün.
8. Es gibt keine Worker-Ausführung, keine Verification, keinen Managed-Task-Abschluss,
   keine Recovery-Automation und keine produktive Aktivierung in diesem Diff.

## 9. Harte Stop-Gates und offene Entscheidungen

Implementierung darf nicht beginnen, wenn eine der folgenden Bedingungen nicht erfüllt ist:

- Agent-B akzeptiert diesen Plan und den genauen Carrier-/Ledger-Schnitt;
- Live-Pins von Steward, Agent City und Steward Protocol sind erneut verifiziert;
- die Produktionsadapter verwenden keine Test-Builder und keine Fixture-Konstanten;
- der Target-Ledger-Owner und atomare Persistenzgrenzfall sind im Code-Review eindeutig;
- ADR-03, ADR-05 und ADR-10 werden nicht implizit entschieden. Sie bleiben für Managed-
  Task-Abschluss, Produktions-Crucible und vollständige Integration offen;
- Context Bridge, Execution-Spine-Gesamtspec, Provider-Failover-Umbau und Merge-Autorität
  bleiben gesperrt.

## 10. Review-Auftrag an Agent B

Bitte diesen Plan als Implementierungs-Gate prüfen:

1. Ist `wire_bytes_b64` als reiner, unsignierter Transportcarrier mit exakt erhaltenen
   V1-Bytes kompatibel mit Draft 0.5, oder fehlt eine normative Transportgrenze?
2. Ist der vorgeschlagene Slice wirklich der kleinste reale Pfad, oder enthält er bereits
   unzulässige Origin-/Target-Ledger-Semantik?
3. Sind Admission-Receipt, `target_work_id`, Deduplizierung und Origin-Korrelation
   vollständig und ohne Titelmatching implementierbar?
4. Ist die Trennung von V1-Adapter und Legacy-`OP_DELEGATE_TASK` fail-closed und ohne
   stillen Fallback beschrieben?
5. Fehlen Authority-, Provenance-, Privacy- oder falsches-Target-Regeln am Carrier-
   beziehungsweise Handler-Schnitt?
6. Ist der Verzicht auf Worker, Recovery, Status Query und Verification im ersten Slice
   technisch konsistent mit dem Contract?
7. Sind Wiring-Manifest-Status und Rollout-Gates maschinenprüfbar genug?
8. Welche konkrete Änderung ist vor dem ersten Produktcode zwingend; welche Teile dieses
   Plans müssen als `OPEN` verbleiben?

**Erwartete Entscheidung:** `ACCEPTED FOR IMPLEMENTATION SLICE 01`, `REVISION REQUIRED`
oder `BLOCKED BY CONTRACT`. Bis zu `ACCEPTED FOR IMPLEMENTATION SLICE 01` bleibt der
Produktcode unverändert.
