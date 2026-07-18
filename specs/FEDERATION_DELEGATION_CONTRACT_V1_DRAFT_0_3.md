# FEDERATION DELEGATION CONTRACT V1 — DRAFT 0.3 (SUPERSEDED)

> Superseded by `specs/FEDERATION_DELEGATION_CONTRACT_V1_DRAFT_0_4.md`. Draft 0.3 is
> historical and not a Golden-Wire- or Crucible-Basis.

> Status: DRAFT 0.3 — REVISION PROPOSED; NOT READY FOR GOLDEN FIXTURES OR CRUCIBLE
> Datum: 2026-07-18
> Scope: gezielte Federation Delegation zwischen Steward und Agent City
> Sperre: kein Produktcode, keine Aktivierung, kein Merge

Draft 0.3 ersetzt Draft 0.2 normativ. Draft 0.2 bleibt historische Vorfassung und ist
nicht als Wire- oder Fixture-Basis zu verwenden.

## 1. Zweck und Nicht-Ziele

Zweck:

~~~text
Steward Managed Task
→ signierter, gezielter Delegation Request
→ Agent-City-Admission
→ genau eine lokale Zielarbeit
→ terminales Resultat
→ Origin-Korrelation
→ unabhängige Verification
~~~

Nicht-Ziele:

- universelle Execution Spine
- Provider-Failover
- allgemeine Workflow-Engine
- Context-Bridge-Aktivierung
- automatische Merge-Autorität
- Broadcast als Targeting
- Titelmatching
- stiller Legacy-Fallback

## 2. Operationen

V1-Draft-0.3-Operationen:

| Operation | Richtung | Side Effect |
|---|---|---|
| delegate_task | Origin → Target | ja, nach Admission |
| delegation_status_query | Origin → Target | nein |
| delegation_status | Target → Origin | nein |
| delegation_receipt | Relay/Target/Origin → Origin/Target, je Stage | nein, Evidence |
| task_completed | Target → Origin | Resultat |
| task_failed | Target → Origin | Resultat |

Verification wird normalerweise als Origin-State persistiert. Eine externe Verification-
Attestation verwendet delegation_receipt mit receipt_stage=verification.

## 3. Identitäten

| Feld | Erzeuger | Regel |
|---|---|---|
| delegation_id | Origin vor erstem Send | ein Lifecycle, unverändert |
| correlation_id | aus delegation_id | exakt bytegleich delegation_id |
| message_id | Sender vor Signatur | pro logischer Message |
| request_message_id | Initial Request | bei allen Antworten unverändert |
| causation_message_id | Antwort-/Receipt-Aussteller | unmittelbare Ursache |
| origin_task_id | Steward TaskManager | lokale Task-ID |
| target_work_id | Target nach Admission | höchstens einmal pro Delegation |
| receipt_id | Receipt-Aussteller | pro fachlichem Receipt |
| request_digest | Origin und Target rekonstruiert | semantischer Request-Hash |
| idempotency_key | deterministisch | fedv1: + request_digest |
| node_id | stabile Registry-Identity | nicht vom rotierenden Signing-Key |
| key_id | aus Signing-Key | key_ + vollständiger Key-Fingerprint |

subject_message_id ist in federation-delegation-v1 verboten.

## 4. Transport-Replay und Application-Reissue

### Transport-Retransmission

- dieselben kanonischen Bytes
- dieselbe message_id
- gleicher message_hash
- gleiche issued_at und expires_at
- gleiche Signatur
- nur solange expires_at nicht überschritten ist
- keine neue Admission, kein neuer Work-Handle

### Application-Reissue

- neue message_id
- neue issued_at und expires_at
- neuer message_hash und neue Signatur
- gleiche delegation_id
- gleicher request_digest
- gleiche Authority und gleiches Target
- keine neue lokale Arbeit, wenn Target-Ledger bereits Admission, Work oder Recovery kennt

Vor Application-Reissue muss eine delegation_status_query oder vorhandene Status-Evidence
belegen, dass kein target_work_id und keine Admission existieren. Bei ACCEPTED,
EXECUTING, RECOVERY_REQUIRED oder terminalem Zustand ist Reissue verboten.

## 5. Semantische Request-Bindung

Pflichtfelder der delegate_task-Payload:

~~~text
delegation_id
origin_task_id
capability
intent
task_description
target_repo
authority
expected_outcome
verification_contract
deadline
request_digest
idempotency_key
~~~

task_title ist optionaler Darstellungswert und nicht Teil des Digest.

Der Digest-Input ist exakt:

~~~json
{
  "contract_version": "federation-delegation-v1",
  "operation": "delegate_task",
  "source_node_id": "...",
  "target_node_id": "...",
  "payload": {
    "delegation_id": "...",
    "origin_task_id": "...",
    "capability": "...",
    "intent": {},
    "task_description": "...",
    "target_repo": "...",
    "authority": {},
    "expected_outcome": {},
    "verification_contract": {},
    "deadline": "..."
  }
}
~~~

Ausgeschlossen sind task_title, Message-/Receipt-IDs, issued_at, expires_at, message_hash,
signature, signer_key, key_id, request_digest und idempotency_key.

Berechnung:

~~~text
request_digest =
  lowercase_hex(SHA256(canonical_request_digest_input_utf8_bytes))

idempotency_key =
  "fedv1:" + request_digest
~~~

Target berechnet und vergleicht. Abweichungen sind request_digest_mismatch. Gleiche
delegation_id mit anderem Digest ist duplicate_conflict. Gleiche idempotency_key mit anderem
Digest ist idempotency_conflict.

## 6. Envelope und Canonical Bytes

### Exakte V1-Felder

~~~text
contract_version
message_id
request_message_id
causation_message_id
source_node_id
target_node_id
operation
correlation_id
payload
issued_at
expires_at
message_hash
signature
signer_key
key_id
~~~

Konditional:

- Initialer delegate_task: request_message_id = message_id; causation_message_id ist verboten.
- Jede Antwort/Receipt: request_message_id und causation_message_id sind Pflicht.
- Statusantworten referenzieren ebenfalls den ursprünglichen Request.
- unbekannte Top-Level-Felder werden abgelehnt.
- payload ist ein JSON-Objekt.

### Zeit

- exact contract_version: federation-delegation-v1
- issued_at und expires_at: UTC, Format YYYY-MM-DDTHH:MM:SSZ
- keine Fractional Seconds
- kein anderer Offset als Z
- keine Leap Seconds
- issued_at < expires_at
- maximale Gültigkeit: 24 Stunden
- zulässige Clock-Skew: 300 Sekunden

### Unicode und JSON

- NFC-Normalisierung vor Schema-Validierung
- unpaired Surrogates verboten
- UTF-8 ohne BOM
- ensure_ascii=false
- sort_keys=true
- separators=(",", ":")
- Duplicate JSON Keys sind Parse-Fehler
- nur JSON-Integer -2^63 bis 2^63-1
- Floats, Exponentenschreibweise, NaN und Infinity verboten
- unbekannte Payload-Felder je Version verboten
- maximale Envelope-Größe 256 KiB
- maximale Payload-Größe 128 KiB
- maximale Verschachtelung 16 Ebenen
- maximale Array-Länge 1024

### Hash

Der Hash-Body enthält alle Envelope-Felder außer exakt message_hash und signature.

~~~text
message_hash =
  lowercase_hex(
    SHA256(canonical_envelope_without_message_hash_and_signature_utf8_bytes)
  )
~~~

Der Name payload_hash ist im V1-Envelope verboten und ausschließlich Legacy.

### Domain-Separation-Signatur

Feste Domain:

~~~text
STEWARD-FEDERATION-DELEGATION-V1\0
~~~

Signaturinput:

~~~text
UTF8("STEWARD-FEDERATION-DELEGATION-V1\0")
|| raw_sha256_digest_bytes
~~~

Signatur:

~~~text
RFC4648_STANDARD_BASE64_WITH_PADDING(
  Ed25519_sign(signing_private_key, signature_input)
)
~~~

URL-safe Base64, fehlendes Padding, Whitespace oder Signaturlänge ungleich 64 Bytes sind
ungültig.

## 7. Node-ID, Key-ID, Rotation und Revocation

Node-ID ist stabil und nicht an den aktuellen Signing-Key gekoppelt:

~~~text
node_id =
  "ag_" + erste 32 lowercase Hex-Zeichen von
  SHA256(identity_root_public_key_hex_ascii)
~~~

Key-ID:

~~~text
key_id =
  "key_" + vollständige 64 lowercase Hex-Zeichen von
  SHA256(signing_public_key_raw_bytes)
~~~

Registry-Provenance:

~~~text
(node_id, key_id, signer_key, not_before, not_after, status, provenance)
~~~

- Rotation erzeugt neue key_id, nicht neue node_id.
- Während des Überlappungsfensters sind alte und neue Keys verifizierbar.
- Neue Messages werden nach Aktivierung nur mit dem neuen Key signiert.
- Alte Messages bleiben prüfbar, wenn issued_at innerhalb ihrer damaligen Gültigkeit lag.
- Revoked Keys dürfen keine neuen Messages erzeugen.
- Unbekannte oder nicht registrierte Keys werden fail-closed verworfen.
- Kompromittierte Keys werden sofort für neue Messages gesperrt.
- Registry- und Revocation-Evidence werden als internes Finding persistiert.

Der aktuelle 16-Hex-Key-Digest und die direkte Node-ID-Kopplung an den Signing-Key sind
Legacy und nicht V1.

## 8. Verifikationsreihenfolge

1. JSON dekodieren und Duplicate Keys ablehnen.
2. Exakte Top-Level-Feldmenge und operation-spezifisches Schema prüfen.
3. contract_version und Größen-/Tiefenlimits prüfen.
4. Zeitprofil und Ablauf prüfen.
5. signer_key, key_id und Base64-/Hex-Formate prüfen.
6. Node-/Key-Registry und Gültigkeitsfenster prüfen.
7. source_node_id gegen stabile Registry-Identity prüfen.
8. Canonical Bytes bilden.
9. message_hash neu berechnen und vergleichen.
10. Domain-Separation-Ed25519-Signatur prüfen.
11. target_node_id exakt prüfen.
12. request_digest für delegate_task selbst berechnen und vergleichen.
13. Authority, Capability und Wiring prüfen.
14. Dedupe-/Ledger-Prüfung durchführen.
15. Erst danach Admission und Fachdispatch.

Unauthentifizierte Eingänge führen nur zu interner Quarantine/Finding und keiner automatischen
signierten Netzwerkantwort. Authentifizierte, korrekt adressierte, aber fachlich abgelehnte
Requests dürfen ein signiertes Reject-Receipt erhalten.

## 9. Receipt-Partial-Order

Receipt-Stufen bilden diesen Partial Order:

~~~text
SENT
  ├─ transport_committed (optional)
  ├─ admission=accepted
  │    ├─ started
  │    │    └─ terminal
  │    │          └─ verification
  │    └─ recovery_required
  └─ admission=rejected (terminaler Seitenpfad)
~~~

Fachliche Vorgänger:

| Receipt | Vorgänger |
|---|---|
| transport_committed | SENT/outbox commit |
| admission accepted/rejected | SENT oder transport_committed |
| started | admission accepted |
| terminal | started im Target-Ledger; kann beim Origin out-of-order eintreffen |
| verification | terminal oder terminale Failure-Evidence |

Out-of-order:

- Origin persistiert terminal vor started als out_of_order_pending.
- Terminal wird nur angewendet, wenn Target-Ledger Start und Work-Handle beweist.
- Fehlendes Started-Receipt wird nicht erfunden; started_receipt_missing bleibt sichtbar.
- admission=rejected ist terminaler Seitenpfad; Started und Terminal sind unzulässig.
- widersprüchliche Zustände werden ledger_conflict.
- fehlende Folgestufe ist delivery_unknown, expired oder recovery_required, niemals Erfolg.

## 10. Kausalitäts- und Receipt-IDs

Jede Antwort/Receipt führt:

~~~text
message_id
request_message_id
causation_message_id
receipt_id (nur Receipt/terminal Resultat)
~~~

- request_message_id bleibt die ursprüngliche delegate_task-Message.
- causation_message_id ist die unmittelbar auslösende Message.
- message_id identifiziert den aktuellen Envelope.
- receipt_id identifiziert den fachlichen Receipt-Datensatz.
- subject_message_id ist verboten.

Receipt-Replay:

- gleiche message_id + gleicher message_hash → Replay/No-op
- gleiche message_id + anderer message_hash → message_id_conflict
- gleiche receipt_id + identischer Body → Replay/No-op
- gleiche receipt_id + anderer Body → receipt_id_conflict
- neue Receipt-Stufe → neue message_id und receipt_id, gleicher request_message_id

## 11. Idempotenz und Recovery

Target-Ledger-Zustände:

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

- Admission-/Dedupe-Eintrag vor jeder Side Effect-Ausführung atomar schreiben.
- Identischer Digest liefert bekanntes Receipt/Resultat und kein zweites Work-Handle.
- Konflikt-Digest fail-closed persistieren.
- Crash vor Admission: identischer Request darf erneut zur Admission angeboten werden.
- Crash nach Admission: target_work_id bleibt; keine zweite Mission.
- Crash während Execution: vorhandenen Work-Handle fortsetzen oder recovery_required.
- Crash nach Terminalresultat: Resultat erneut liefern, am Ursprung nur einmal anwenden.
- Lease-Ablauf ist kein automatischer Zweitstart.
- Application-Reissue nur nach Statusabfrage mit UNKNOWN/delivery_expired_before_admission.
- ACCEPTED, EXECUTING, RECOVERY_REQUIRED und terminale Zustände sperren Reissue.
- Partielle externe Side Effects benötigen Dedup-Key, Read-back oder explizite Recovery.
- Exactly-once wird nicht behauptet.

## 12. Getrennte Ledger

### Target-Ledger

Besitzt received, admitted/rejected, request_digest, target_work_id, lease/owner,
executing, recovery_required, terminal result, Target-Receipt-Evidence und Conflicts.

### Origin-Ledger

Besitzt request created/sent, request_message_id, Transport-Evidence, Admission-/Started-/
Terminal-Receipts, Verification, einmalige Anwendung auf origin_task_id und Origin-Conflicts.

Regeln:

- Target-Ledger ist Autorität für lokale Annahme, Work, Lease und Terminalresultat.
- Origin-Ledger ist Autorität für Send, Korrelation, Verification und Origin-Task-Anwendung.
- Origin erfindet keine Target-Zustände.
- Target stellt keine Origin-Verification aus.
- Statusabfrage liest den Target-Ledger und erzeugt einen signierten Snapshot.
- Widersprüchliche Snapshots werden beidseitig als ledger_conflict persistiert.

## 13. Capability-Wiring

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

Status:

- declared
- partially_wired
- code_complete
- crucible_verified
- production_proven
- unavailable
- legacy

implemented ist kein gültiger Draft-0.3-Status.

- code_complete: alle Codekanten und Ledger-/Receipt-/Authority-Pfade existieren; kein
  Crucible-/Produktionsnachweis.
- crucible_verified: reale Wire-Bytes, positiver und adversarialer Cross-Repo-Crucible grün.
- production_proven: Crucible plus reproduzierbarer Produktionsbeleg über aktuellen Rollout.
- fehlender Receipt-, Recovery- oder Authority-Pfad verhindert code_complete.

delegate_task ist im heutigen IST mindestens unavailable auf Agent-City-Seite und insgesamt
partially_wired.

## 14. Authority und Failure

Signatur beweist Identität und Integrität, nicht fachliche Berechtigung.

Authority wird explizit übertragen und begrenzt:

- erlaubte Aktionen
- verbotene Aktionen
- Zielrepository
- keine implizite Merge-, Secret- oder Context-Bridge-Autorität

Unauthentifizierte Fehler:

- internes Finding/Quarantine
- Rate-Limit
- keine signierte Antwort
- keine Information über Target-/Capability-/Authority-Existenz

Authentifizierte fachliche Rejects:

- unsupported_contract
- wrong_target
- authority_denied
- capability_unavailable
- request_digest_mismatch
- duplicate_conflict
- idempotency_conflict
- expired

## 15. Offene ADR-Abhängigkeiten

- ADR-01: für isolierte Federation-Wire-Semantik offen zulässig; keine universelle execution_id.
- ADR-03: vor Mapping auf Managed-Task-COMPLETED zwingend.
- ADR-04: offen, solange kein providerabhängiger V1-Crucible-Handler verwendet wird.
- ADR-05: vor Produktions-Crucible zwingend.
- ADR-10: vor vollständiger Federation-V1-Integration zwingend.
- ADR-06: Node-ID, key_id, Rotation, Revocation und Domain Separation bleiben bis Agent-B-
  Review OPEN.

## 16. Migration und Readiness

- Legacy payload_hash wird nicht als V1 message_hash akzeptiert.
- Legacy subject_message_id wird nicht als V1-Kausalitätsfeld akzeptiert.
- Alte 16-Hex-Node-IDs und direkte Key-Kopplung bleiben Legacy.
- Legacy title-/timestamp-Dedup bleibt außerhalb V1.
- Kein Mischformat innerhalb federation-delegation-v1.
- Golden-Wire-Fixtures erst nach Agent-B-Abnahme der Revision.
- Crucible-Design erst nach Fixture-/Partial-Order-/Ledger-Freeze.
- Produktcode, Phase 1 und Context Bridge bleiben unverändert.

Draft 0.3 ist daher weiterhin NOT IMPLEMENTATION-READY.
