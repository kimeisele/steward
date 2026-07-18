# ADR-08 — RETRY-, RECOVERY- UND IDEMPOTENZVERTRAG

> **Status:** ACCEPTED 1.0 — FEDERATION-DELEGATION-V1-SCOPE
> **Datum:** 2026-07-18
> **Entscheider:** Codebase-Agent, zur Review durch Agent B
> **Geltungsbereich:** Delegation Request, Admission, Result und Recovery; keine Provider-Spine

## Entscheidung

V1 verwendet **at-least-once transport delivery mit durable idempotentem Receiver**.
At-most-once-Ausführung wird nicht behauptet; exakt-einmalige Wirkung ist nur zulässig,
wenn der konkrete Ziel-Handler sie fachlich unabhängig garantieren kann.

### Normative Regeln

1. `delegation_id` identifiziert einen Delegations-Lifecycle; `idempotency_key` bindet den
   kanonischen Request-Body.
2. Vor lokaler Ausführung muss der Zielknoten einen persistenten Admission-/Dedupe-Eintrag
   atomar anlegen. Erst danach darf ein Worker/Mission erzeugt werden.
3. Derselbe `delegation_id` plus identischer Request liefert das bereits bekannte Admission-
   oder Resultat zurück und erzeugt keine zweite Wirkung.
4. Derselbe `delegation_id` plus abweichender Request ist `duplicate_conflict`, fail-closed,
   und erzeugt ein Finding/Receipt.
5. Retry derselben kanonischen Message behält `message_id`; eine neue fachliche Antwort
   erhält eine neue Message-ID und dieselbe `correlation_id` gemäß ADR-02.
6. Terminale Resultate sind idempotent: ein identisches Duplikat ist No-op; widersprüchliche
   terminale Resultate werden quarantiniert/als Konflikt sichtbar gemacht.
7. Retry erhält weder neue Authority noch ein neues Target. Ablaufzeit und Authority des
   ursprünglichen Requests bleiben bindend.
8. Ein Crash nach `ACCEPTED` darf nicht durch blindes Neu-Ausführen behandelt werden.
   Recovery liest den persistenten Eintrag und führt entweder den bestehenden Work-Handle
   fort oder setzt `RECOVERY_REQUIRED` für eine explizite Recovery-Entscheidung.
9. Ein `EXECUTING`-Eintrag braucht eine Lease-/Heartbeat-Grenze. Lease-Ablauf ist nicht
   automatisch die Erlaubnis zur zweiten Ausführung.
10. Nicht-idempotente Side Effects benötigen entweder einen fachlichen Dedup-Key am Tool
    oder bleiben für V1 abgelehnt.

### V1-Zustandskanten

```text
UNKNOWN → ACCEPTED → EXECUTING → RESULT_REPORTED → VERIFIED/FAILED_VERIFICATION
                    ↘ RECOVERY_REQUIRED
UNKNOWN → REJECTED | DUPLICATE_CONFLICT | EXPIRED
```

`RECOVERY_REQUIRED` ist ein sichtbarer Zustand, kein stiller Retry. Der genaue Lease-
und Recovery-Operator bleibt innerhalb dieses Vertrags festgelegt: kein automatischer
zweiter Side Effect ohne fachlich idempotenten Handler.

## Live-Code-Befund

- Steward `FederationBridge._handle_task_callback` korreliert per Titel-Substring, nicht
  per stabiler ID.
- Agent City `FederationNadi.receive` dedupliziert nur in-memory über `source:timestamp`.
- Steward Relay persistiert `relay_seen_ids.json`, aber `DeliveryReceipt` bleibt in-memory.
- `FederationBridge` und Agent-City-Ingress besitzen keinen gemeinsamen Delegation-Ledger.
- `DelegateTool` markiert lokal `BLOCKED`, bevor ein Annahme-Receipt existiert.
- `_execute_federated_task` markiert die Task bei `result is not None`-Semantik und kann bei
  `None`/Fehler einen widersprüchlichen Callback erzeugen.
- Tests prüfen lokale Deduplizierung und Relay-Verhalten, aber keinen Crash nach Acceptance
  über zwei Repositories.

## Optionen

### Option A — At-most-once / Dedupe vor Ausführung ohne Recovery-Fortsetzung

Der Empfänger markiert eine Nachricht als gesehen, führt maximal einmal aus und verwirft
bei Crash den unbekannten Zwischenstand.

Vorteile:

- einfache Duplicate-Semantik,
- geringe Implementierungsfläche,
- keine zweite Ausführung.

Nachteile:

- Crash nach Markierung kann Arbeit dauerhaft verlieren,
- Sender kann zwischen Annahme und Ergebnis nicht unterscheiden,
- Recovery ist blind oder manuell ohne State,
- Transportverlust wird als Nichtausführung missinterpretiert.

### Option B — At-least-once Transport plus durable idempotenter Receiver (gewählt)

Nachrichten dürfen wiederholt eintreffen; persistenter Zustand und fachliche Dedup-Grenzen
verhindern doppelte Wirkung und machen Recovery sichtbar.

Vorteile:

- Delivery-Verlust kann sicher wiederholt werden,
- Crash-Zustand bleibt beobachtbar,
- fachliche Side Effects können eigene Idempotency-Keys tragen,
- widersprüchliche Resultate werden als Konflikt statt als Erfolg behandelt.

Kosten:

- durable Ledger/Lease,
- atomare Write- und Recovery-Tests,
- mögliche `RECOVERY_REQUIRED`-Fälle für Operator/Policy,
- nicht-idempotente Tools brauchen explizite Sperren.

## Auswirkungen

- **Steward:** Outbound muss Request-Hash/IDs stabil halten; Origin-Ledger darf Resultate
  nur einmal terminal anwenden.
- **Agent City:** Admission vor Missionserzeugung, durable `target_work_id`, Lease und
  Wiederaufnahme-/Konfliktpfad sind erforderlich.
- **Steward Protocol:** Transport darf bei Retry die signierten Bytes/`message_id` nicht
  verändern; Persistenz-API muss atomare Zustandsübergänge ermöglichen.
- **Migration:** Legacy-Titel-/Timestamp-Dedup wird nicht als V1-Fallback verwendet;
  Legacy bleibt separat markiert.
- **Recovery:** Crash-Fenster werden explizit als `RECOVERY_REQUIRED` sichtbar; kein
  inferiertes „nicht gelaufen“.
- **Authority:** Retry reproduziert nur die ursprüngliche Authority; Timeout erweitert sie
  nicht und erlaubt keinen Target-Wechsel.
- **Tests:** identisches Duplicate, Konflikt-Duplicate, Crash vor/nach Acceptance, Lease-
  Ablauf, doppeltes Resultat, widersprüchliches Resultat, nicht-idempotenter Side Effect.

## Adversariales Gegenargument

Ein durable Ledger garantiert keine fachliche Idempotenz: ein externes GitHub-/Tool-Write
kann nach dem Side Effect, aber vor dem Ledger-Commit crashen. Das ist richtig und wird
nicht mit „exactly once“ kaschiert. V1 verlangt deshalb für solche Tools entweder einen
externen fachlichen Dedup-Key/Read-back oder `RECOVERY_REQUIRED`; ein zweiter Blind-Call ist
verboten.

## Review-/Implementierungsreife

**Entscheidung:** ACCEPTED für V1. Implementierung nicht freigegeben. Vor Code müssen
Ledger-Owner, atomare Persistenz, Lease-Details und der Cross-Repo-Crash-Crucible als
ausführbare Tests präzisiert werden.
