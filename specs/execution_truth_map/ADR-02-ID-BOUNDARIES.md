# ADR-02 — EXECUTION-, CORRELATION- UND MESSAGE-ID

> **Status:** AMENDED — SPRINT 1C REVISION IN `ADR_DECISION_SPRINT_1C_REVISION.md`
> **Hinweis:** Der folgende Sprint-1-Text ist historische Begründung; Draft 0.3 und Sprint
> 1B sind für normative Regeln maßgeblich.
> **Datum:** 2026-07-18
> **Entscheider:** Codebase-Agent, zur Review durch Agent B
> **Geltungsbereich:** Federation Delegation Contract V1; keine universelle Execution Spine

## Entscheidung

V1 trennt die semantischen Rollen, verwendet aber eine explizite V1-Beziehung:

| Feld | Rolle | Erzeugung | Kardinalität |
|---|---|---|---|
| `delegation_id` | stabile Identität einer Delegation | Steward-Origin vor dem ersten Send | 1 pro Delegations-Lifecycle |
| `correlation_id` | Antwort-/Receipt-Bezug | nicht separat zufällig erzeugt; V1 muss exakt `delegation_id` referenzieren | viele Messages → 1 Delegation |
| `message_id` | Identität eines einzelnen Protokoll-Envelopes | Sender pro logischer Message | 1 pro Message; Retry derselben Bytes behält sie |
| `origin_task_id` | lokale Steward-Task | TaskManager | 1 lokale Task, nicht global |
| `target_work_id` | lokale Agent-City-Arbeit | Ziel nach durable Admission | 0 oder 1 pro `delegation_id` |

`delegation_id`, `origin_task_id`, `target_work_id` und `message_id` sind niemals aus Titel,
Timestamp, Listenposition oder Payload-Substring abzuleiten. `correlation_id` ist ein
separates Feld mit separater Semantik, erhält in V1 aber deterministisch den Wert der
`delegation_id`. Damit ist die Wire-Korrelation eindeutig, ohne ADR-01 (universelle
Execution-Identität über Provider, Tool und Workflow) vorwegzunehmen.

Ein Transport-Retry derselben kanonischen Bytes darf `message_id` nicht ändern. Eine neue
fachliche Antwort (Admission, Receipt oder Result) erhält eine neue `message_id` und
referenziert dieselbe `delegation_id` in `correlation_id`.

## Live-Code-Befund

- `steward/federation.py:BridgeEvent` besitzt keine Correlation-ID.
- `FederationBridge.flush_outbound()` setzt `correlation_id=""`.
- `steward/tools/delegate.py:DelegateTool.execute` sendet keine Ursprungstask-ID.
- `steward/federation.py:_handle_task_callback` sucht blockierte Tasks per
  `delegated:{task_title}`-Substring.
- `city/federation_nadi.py:FederationMessage` besitzt `correlation_id`, aber keinen
  `message_id`; `receive()` dedupliziert in-memory über `source:timestamp`.
- `steward/federation_transport.py` ergänzt `message_id` nur für unsignierte Nachrichten.
- `steward/a2a_adapter.py:A2ATask` und Managed Task besitzen getrennte IDs ohne Mapping.

Live-Pins: Steward `110b933231ebdcd3fc43c04ee30afe5df88be5130`, Agent City
`e798bdbf7b3969beea577fe265657bbb7c142115`, Protocol `34a8a0efc25c15ef7c07dd4fb50aeb2510c071e8`.

## Optionen

### Option A — eine gemeinsame ID

`correlation_id`, Task-ID und Message-ID würden denselben String teilen.

Vorteile:

- minimale Payload-Änderung,
- einfache Logs.

Nachteile:

- Retries, Antworten und fachliche Delegationen sind nicht unterscheidbar,
- lokale Task-IDs werden fälschlich global,
- Replay-/Duplicate-Grenzen werden vermischt,
- A2A, Relay und Workflow können nicht sauber korrelieren,
- Recovery kann eine Message nicht von einer Delegation unterscheiden.

### Option B — getrennte Rollen mit expliziter V1-Beziehung (gewählt)

Delegation-, Message-, lokale Task- und Zielarbeitsidentität werden getrennt; alle
Federation-V1-Nachrichten referenzieren die Delegation über `correlation_id`.

Vorteile:

- Retry, Replay, Antwort und fachlicher Lifecycle sind unterscheidbar,
- lokale IDs bleiben lokal,
- Target- und Result-Checks werden maschinenlesbar,
- spätere ADR-01-Entscheidung bleibt möglich.

Kosten:

- Migration aller Sender, Empfänger und Fixtures,
- zusätzliche Persistenz und Duplicate-Checks,
- Legacy-Titelcallbacks müssen auslaufen.

## Auswirkungen

- **Steward:** `DelegateTool`, BridgeEvent, Outbound-Envelope und Callback-Handler müssen
  die IDs unverändert tragen; Titelmatching wird kein V1-Fallback.
- **Agent City:** Ingress, Mission/Worker-State und Resultate müssen `delegation_id`,
  `correlation_id`, `message_id` und `target_work_id` persistieren.
- **Steward Protocol:** FederationMessage muss die Felder verlustfrei transportieren;
  lokale Protocol-Task-IDs bleiben unverändert.
- **Migration:** Legacy-Nachrichten ohne V1-IDs werden nicht als V1 angenommen; sie dürfen
  nur in einem separat markierten Legacy-Pfad beobachtet werden.
- **Recovery:** Der Zustandsschlüssel ist `delegation_id`; Message-Dedup erfolgt über
  `message_id`; widersprüchliche Wiederverwendung ist ein Konflikt.
- **Authority:** IDs verleihen keine Autorität. Sender-/Target-Key und Authority-Payload
  bleiben eigene Prüfungen.
- **Tests:** gleiche Titel mit unterschiedlichen IDs, doppelte Messages, neue Antwort-
  Message-ID bei gleicher Delegation und falsche Korrelation müssen geprüft werden.

## Adversariales Gegenargument

Die getrennten Felder könnten mehr Komplexität einführen und bei fehlerhafter Persistenz
selbst auseinanderlaufen. Das Gegenmittel ist nicht Zusammenlegen, sondern eine harte
Invariante: `correlation_id == delegation_id` in V1, unveränderliche Message-ID pro
logischer Message und fail-closed Prüfung aller lokalen IDs. Ein gemeinsamer String würde
den heutigen Mehrdeutigkeitsfehler nur unsichtbar machen.

## Review-/Implementierungsreife

**Entscheidung:** ACCEPTED für V1. Implementierung noch nicht freigegeben. ADR-06, -08 und
-09 müssen gemeinsam umgesetzt werden; ohne Signatur, durable Dedup und Receipt-Stufen ist
die ID-Entscheidung nicht produktionsreif.

## Sprint-1C-Amendment

Transport-Retransmission und Application-Reissue sind getrennt. Retransmission behält
kanonische Bytes, message_id, request_digest, issued_at und expires_at und ist nur vor Ablauf
zulässig. Application-Reissue erhält eine neue message_id, issued_at, expires_at, message_hash
und Signatur, aber dieselbe delegation_id, denselben request_digest und denselben
request_message_id. `causation_message_id` verweist auf die auslösende Status-/Recovery-
Message. `subject_message_id` ist Draft-0.4-verboten.
