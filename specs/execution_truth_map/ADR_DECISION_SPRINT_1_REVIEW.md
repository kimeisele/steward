# ADR DECISION SPRINT 1 — WIDERSPRUCHS- UND IMPLEMENTIERUNGSREIFE-REVIEW

> **Status:** REVIEW-VORLAGE — ADR-02/-06/-07/-08/-09 `ACCEPTED` im engen Federation-
> Delegation-V1-Scope; Agent-B-Review und Spec-Freeze weiterhin offen
> **Datum:** 2026-07-18
> **Scope:** nur Federation Delegation Contract V1; keine Execution-Spine-Entscheidung,
> kein Produktcode

## 1. Geprüfter Bestand

Dieser Review prüft die fünf einzeln vorgelegten ADRs gegen den aktualisierten Contract:

| ADR | Entscheidung | Einzelbeleg |
|---|---|---|
| ADR-02 | `ACCEPTED` — getrennte ID-Rollen; V1 `correlation_id == delegation_id` | [`ADR-02-ID-BOUNDARIES.md`](ADR-02-ID-BOUNDARIES.md) |
| ADR-06 | `ACCEPTED` — kanonischer Envelope, SHA-256/Ed25519/base64, keine Hub-Mutation | [`ADR-06-FEDERATION-SIGNATURE.md`](ADR-06-FEDERATION-SIGNATURE.md) |
| ADR-07 | `ACCEPTED` — vollständiges Wiring-Manifest als Implementierungs-Gate | [`ADR-07-CAPABILITY-WIRING.md`](ADR-07-CAPABILITY-WIRING.md) |
| ADR-08 | `ACCEPTED` — at-least-once Transport, durable Idempotenz, sichtbare Recovery | [`ADR-08-RETRY-RECOVERY-IDEMPOTENZ.md`](ADR-08-RETRY-RECOVERY-IDEMPOTENZ.md) |
| ADR-09 | `ACCEPTED` — typisierte, rollenbegrenzte Receipt-Stufen | [`ADR-09-RECEIPT-SEMANTIK.md`](ADR-09-RECEIPT-SEMANTIK.md) |

Die Live-Pins und Code-/Testbelege stammen aus dem akzeptierten Recon in
[`EXECUTION_TRUTH_MAP_RECON.md`](EXECUTION_TRUTH_MAP_RECON.md). Die Entscheidungen sind
Vertragsentscheidungen für V1, keine Behauptung, dass die aktuelle Implementierung sie
bereits erfüllt.

## 2. Widerspruchsmatrix

| Schnittstelle | Prüfung | Ergebnis | Auflage |
|---|---|---|---|
| ADR-02 ↔ ADR-06 | `message_id` wird vor der Signatur erzeugt; Retry verändert signierte Bytes nicht | **kein Widerspruch** | Golden-Byte-Fixture muss dieselbe Message-ID bei Replay beweisen |
| ADR-02 ↔ ADR-08 | Delegation bleibt Lifecycle-Key; Message-ID dedupliziert einzelne Bytes; Konflikt bei gleicher Delegation mit anderem Body | **kein Widerspruch** | Ledger muss beide Schlüssel atomar prüfen |
| ADR-02 ↔ ADR-09 | Jede Receipt referenziert `delegation_id`; eigene Receipt-`message_id`, `receipt_id` und `subject_message_id` bleiben getrennt | **kein Widerspruch** | Receipt-Schema darf `correlation_id` nicht optional machen |
| ADR-06 ↔ ADR-07 | Manifest verweist auf dieselbe Version, Schema- und Canonical-Byte-Regeln | **kein Widerspruch** | Der Auditor muss fehlende Crypto-/Schema-Kante als `partial`/`unavailable` ausweisen |
| ADR-06 ↔ ADR-09 | Receipts sind selbst signierte V1-Messages; Issuer-Key und Rolle müssen zusammenpassen | **kein Widerspruch** | Relay darf nur Transport-Receipt ausstellen |
| ADR-07 ↔ ADR-08 | `state_transition` und Recovery-/Dedup-Owner sind Wiring-Kanten | **kein Widerspruch** | Handler ohne durable Admission oder Recovery bleibt nicht `implemented` |
| ADR-07 ↔ ADR-09 | Result-/Receipt-Operationen und erlaubte Aussteller stehen im Manifest | **kein Widerspruch** | fehlender Receipt-Pfad verhindert Implementierungsstatus |
| Contract §3/§4 ↔ offene ADRs | `intent`, `authority`, Postcondition, Managed-Task-/Statusadapter sind als strukturierte Vertragsfelder genannt, aber nicht durch ADR-01/-03/-04/-05/-10 entschieden | **kein impliziter Default** | diese Felder bleiben explizite Spec-Freeze-Blocker; kein Code darf sie still auslegen |

### Befund

Es wurde kein direkter Widerspruch zwischen den fünf akzeptierten Entscheidungen gefunden.
Die schärfste gemeinsame Invariante lautet:

```text
signierte Message-ID ≠ Delegations-Lifecycle-ID ≠ lokale Task-ID;
alle Receipt- und Resultatpfade referenzieren die Delegation explizit;
keine Transport- oder Admission-Receipt behauptet Verifikation.
```

Die Entscheidungen dürfen daher gemeinsam als Contract-Schnitt verwendet werden, ohne
eine universelle `execution_id` oder ein neues übergreifendes Statusmodell vorwegzunehmen.

## 3. Implementierungsreife

**Urteil: NOT IMPLEMENTATION-READY.** Die fünf ADRs sind im V1-Scope entschieden, aber die
Implementierung bleibt bis zu den folgenden Gates gesperrt:

1. Agent B bestätigt oder verwirft jede ADR einzeln; offene Einwände werden als Revision,
   nicht als stiller Default, eingetragen.
2. ADR-05 (Workflow-Wahrheit) und ADR-10 (Status-/Adaptervertrag) werden entschieden;
   ADR-01/-03/-04 bleiben bis zu ihrem eigenen Auftrag offen.
3. Der kanonische Envelope wird als Cross-Repo-Golden-Fixture mit exakt denselben UTF-8-
   Bytes, Hash-, Base64- und Ed25519-Schritten festgeschrieben.
4. Ein Wiring-Manifest für `delegate_task`, `delegation_receipt`, `task_completed` und
   `task_failed` weist im aktuellen IST die fehlenden Agent-City-Handler ausdrücklich als
   `unavailable` aus.
5. Ledger-Owner, atomare Admission, Lease-Grenze, `RECOVERY_REQUIRED` und Conflict-
   Persistenz werden als rote Tests präzisiert.
6. Receipt-Payload, `issuer_role`/Key-Bindung, Retention und monotone Zustandsprüfung werden
   als rote Tests präzisiert.
7. Erst danach darf ein getrenntes Implementierungs-Spec-/PR-Gate eröffnet werden.

Keine dieser Auflagen ist durch den aktuellen Dokumentationsmilestone erfüllt. Phase 1,
Context Bridge, Providerpfade und Produktcode bleiben unangetastet.

## 4. Aus der Spec ableitbarer repoübergreifender Crucible

Der Contract ist für einen späteren Crucible hinreichend konkret, ohne Implementation zu
autorisieren. Der Test muss reale Bytes und reale Ingress-/Resultatpfade verwenden:

### Positiver Pfad

```text
Steward erzeugt delegation_id/message_id
→ kanonisiert und signiert `delegate_task`
→ Transport committed (optionales Relay-Receipt)
→ Agent City prüft Version, Signatur, Target, Authority und Wiring
→ Admission-Receipt mit genau einem target_work_id
→ Started-Receipt
→ genau eine lokale Mission
→ terminales task_completed/task_failed mit neuer message_id
→ Steward dedupliziert und korreliert über delegation_id/correlation_id
→ unabhängige Postcondition
→ origin verification-Receipt
```

### Adversariale Pfade

- identisches Message-Replay: ein Admission-/Work-Handle, kein zweiter Side Effect;
- gleiche Delegation mit verändertem Body: `duplicate_conflict`;
- falsche oder unbekannte Signatur/Key: fail-closed;
- falsches Target oder Broadcast-Versuch: `wrong_target`;
- fehlender Handler: `capability_unavailable`, kein stilles Konsumieren;
- Crash nach Acceptance oder Lease-Ablauf: `RECOVERY_REQUIRED`, kein Blind-Retry;
- doppeltes oder widersprüchliches Terminal-Resultat: No-op beziehungsweise Konflikt;
- grünes Target-Workflow-Ergebnis ohne unabhängige Postcondition: `FAILED_VERIFICATION`.

Der Crucible beweist damit Vertragswirkung, nicht bloß lokale Unit-Test-Erfolge.

## 5. Schlussstatus

- ADR-02/-06/-07/-08/-09: **ACCEPTED**, jeweils mit eigenem Gegenargument und
  Implementierungsauflagen.
- Contract V1: **DRAFT 0.2**, gegen die fünf ADRs reconciliiert, aber nicht eingefroren.
- Widerspruchsreview: **kein direkter Widerspruch gefunden**; offene ADRs sind explizite
  Blocker.
- Implementierungsreife: **OPEN / NOT READY**.
- Produktcode, Phase 1 und Context Bridge: **unverändert und gesperrt**.
