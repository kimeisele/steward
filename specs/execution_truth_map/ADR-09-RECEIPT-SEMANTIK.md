# ADR-09 — RECEIPT-SEMANTIK

> **Status:** ACCEPTED 1.0 — FEDERATION-DELEGATION-V1-SCOPE
> **Datum:** 2026-07-18
> **Entscheider:** Codebase-Agent, zur Review durch Agent B
> **Geltungsbereich:** Federation Delegation V1; kein allgemeines Outcome-/Execution-Modell

## Entscheidung

V1 verwendet **gestufte, typisierte Receipts** statt eines einzelnen Delivery-Erfolgs.
Jede Receipt besitzt mindestens:

```text
receipt_id
receipt_stage
delegation_id
correlation_id (= delegation_id)
message_id (eigene Receipt-Envelope-ID)
subject_message_id (auslösende Message)
issuer_node_id
issuer_role
target_node_id
target_work_id (Pflicht ab Admission-accepted; `null` nur bei Transport-/Reject-Receipt)
issued_at
status
evidence_ref (falls vorhanden)
signature
```

### Receipt-Stufen

| Stufe | Aussteller | Aussage | Keine Aussage |
|---|---|---|---|
| `transport_committed` | Relay/Hub | signierte Bytes wurden in die Ziel-Mailbox committed | Ziel hat gelesen/angenommen |
| `admission` | Zielknoten | Request validiert und `accepted`/`rejected`; bei Annahme `target_work_id` | Worker hat begonnen |
| `started` | Zielknoten/Worker-Scheduler | genau eine lokale Arbeit wurde aus dem Admission-State gestartet | Erfolg |
| `terminal` | Zielknoten | `completed` oder `failed` mit Outcome/Evidence | fachliche Postcondition des Ursprungs |
| `verification` | Ursprung | unabhängige Postcondition `verified` oder `failed_verification` | neue Zielausführung |

`transport_unknown`, `delivery_expired`, `admission_rejected` und
`verification_failed` sind explizite negative Outcomes, keine impliziten Success-/No-op-
Defaults. Ein Receipt darf keine höhere Stufe behaupten als die eigene Ausstellerrolle.

### Monotonie und Korrelation

- Jede Receipt referenziert genau eine `delegation_id`; fehlende oder fremde IDs werden
  verworfen.
- `receipt_id` ist pro Receipt eindeutig und immutable.
- `message_id` identifiziert den Receipt-Envelope selbst; `subject_message_id` identifiziert
  die Message, deren Verarbeitung die Receipt-Stufe ausgelöst hat. Beide sind Pflicht und
  dürfen nicht vertauscht werden.
- Ein identisches Receipt-Duplikat ist No-op; widersprüchliche Receipts gleicher Stufe
  werden als Konflikt persistiert.
- `transport_committed` darf ohne spätere Admission bestehen bleiben; daraus darf kein
  `accepted` oder `verified` abgeleitet werden.
- `verification` ist die einzige Stufe, die fachliche Wirkung am Ursprung bestätigt.
- Der Ursprung darf `verification` erst nach unabhängiger Beobachtung gemäß
  `verification_contract` ausstellen.

## Live-Code-Befund

- `steward/federation_relay.py:DeliveryReceipt` enthält nur `batch_id`, Target,
  `message_ids`, Push-Zeit und boolesches `confirmed`.
- Relay bestätigt bei jeder späteren Nachricht desselben Peers alle offenen Receipts dieses
  Peers (`_pending_receipts`, `responding_peers`); dies ist keine Message-ID-Ack-Semantik.
- Receipts sind in-memory und nicht als langlebiger Delegationszustand persistiert.
- `FederationBridge.append_to_inbox`/Transport liefern Zählwerte, aber keinen typed
  Admission-/Terminal-Receipt.
- Agent-City-PR-Verdict-Handler führt bei gültiger Nachricht eine PR-Aktion aus, besitzt
  aber keinen V1-Receipt-Contract für Admission, Start, Terminal und Ursprungsverifikation.
- `ToolResult`, `FixResult` und `GateResult` beweisen lokale Tool-/Gate-Ergebnisse, nicht
  die externe Postcondition.

## Optionen

### Option A — ein boolescher DeliveryReceipt

Ein Receipt bestätigt „zum Peer zugestellt“; alle weiteren Zustände werden aus Logs oder
späteren Nachrichten geschätzt.

Vorteile:

- geringe Payload-/Persistenzkosten,
- einfache bestehende Relay-Integration.

Nachteile:

- Transport, Annahme, Start und Wirkung werden vermischt,
- die heutige Peer-Heuristik kann falsche Bestätigung erzeugen,
- Recovery kann nicht wissen, ob ein Side Effect begann,
- der Ursprung kann Tool-Erfolg mit fachlichem Erfolg verwechseln.

### Option B — gestufte typisierte Receipts (gewählt)

Transport, Admission, Start, Terminal und Verification werden getrennt attestiert und
rollenbeschränkt.

Vorteile:

- jede Behauptung hat einen klaren Aussteller und Beweisumfang,
- Timeout-/Recovery-Zustände bleiben sichtbar,
- `FAILED_VERIFICATION` kann von `FAILED_AT_TARGET` unterschieden werden,
- der Crucible kann jede Stufe und jedes Störfenster testen.

Kosten:

- mehrere Nachrichten-/State-Artefakte,
- durable Receipt-/Conflict-Persistenz,
- zusätzliche Signatur- und Korrelationsprüfungen,
- liveness muss über explizite Unknown-/Expired-Stufen behandelt werden.

## Auswirkungen

- **Steward:** Origin-Ledger speichert Receipts und darf nur `verification` als fachliche
  Completion anwenden; Transportbestätigung bleibt niedriger Status.
- **Agent City:** Zielknoten stellt Admission, Started und Terminal aus; jeder Receipt
  braucht `target_work_id`, wo diese existiert.
- **Steward Protocol:** Receipt-Schema und Signatur müssen gemeinsam mit ADR-02/06
  serialisiert und dedupliziert werden.
- **Migration:** heutige `DeliveryReceipt.confirmed` wird als Legacy-Transportbeobachtung
  markiert, nicht als V1-Admission/Verification.
- **Recovery:** fehlende nächste Stufe erzeugt `delivery_unknown`/Timeout, niemals inferred
  success; Receipt-Ledger unterstützt Crash-Replay.
- **Authority:** Relay darf nur `transport_committed`, Ziel nur Zielzustände, Ursprung nur
  `verification` ausstellen.
- **Tests:** Stufenreihenfolge, falscher Aussteller, falsche IDs, Duplicate, widersprüchliche
  Receipt, Delivery ohne Admission, grüner Target-Workflow ohne Postcondition.

## Adversariales Gegenargument

Mehr Receipts können Scheinsicherheit und State-Bloat erzeugen. Das wird durch die Aussage-
grenzen verhindert: jede Receipt nennt explizit, was sie nicht beweist, und nur die
Origin-Verification darf fachliche Wirkung bestätigen. TTL/Retention und Aggregation sind
spätere Betriebsparameter, ändern aber nicht die Stufensemantik.

## Review-/Implementierungsreife

**Entscheidung:** ACCEPTED für V1. Implementierung nicht freigegeben. Vor Code müssen
Receipt-Schema, Issuer-Key-Bindung, persistente Retention und der Stufen-Crucible als
ausführbare Tests eingefroren werden.
