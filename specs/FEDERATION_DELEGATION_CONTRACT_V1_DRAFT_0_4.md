# FEDERATION DELEGATION CONTRACT V1 — DRAFT 0.4 (HISTORICAL)

> Status: SUPERSEDED by Draft 0.5; retained as historical review baseline
> Datum: 2026-07-18
> Scope: gezielte Federation Delegation zwischen Steward und Agent City
> Sperre: kein Produktcode, keine Aktivierung, kein Merge

Draft 0.4 ersetzte Draft 0.3 als historische Review-Basis. Die normative und fixture-fähige
Fassung ist `specs/FEDERATION_DELEGATION_CONTRACT_V1_DRAFT_0_5.md`; dieses Dokument wird
nicht weiter als V1-SSOT fortgeschrieben.

## 1. Zweck und Nicht-Ziele

Zweck:

~~~text
Steward Managed Task
→ signierter, exakt adressierter Delegation Request
→ Agent-City-Admission
→ höchstens eine lokale Zielarbeit
→ terminales Resultat
→ Origin-Korrelation
→ unabhängige Verification
~~~

Nicht-Ziele:

- universelle Execution Spine
- Provider-Failover
- automatische Merge-Autorität
- Context-Bridge-Aktivierung
- Broadcast
- Titelmatching
- stiller Legacy-Fallback

## 2. Operationen

| Operation | Richtung | Wirkung |
|---|---|---|
| delegate_task | Origin → Target | lokale Zielarbeit erst nach Admission |
| delegation_status_query | Origin → Target | read-only |
| delegation_status | Target → Origin | read-only Snapshot |
| delegation_receipt | Relay/Target/Origin → berechtigter Peer | Evidence |
| task_completed | Target → Origin | terminales Resultat |
| task_failed | Target → Origin | terminales Resultat |

Verification wird normalerweise als Origin-State persistiert. Externe Attestation verwendet
delegation_receipt mit receipt_stage=verification.

## 3. Identitäten und Request-Root

| Feld | Regel |
|---|---|
| delegation_id | Origin vor erstem Send; ein Lifecycle; unverändert |
| correlation_id | exakt delegation_id |
| message_id | aktuelle logische Message; vor Signatur erzeugt |
| request_message_id | allererste delegate_task-Message; bei allen Antworten unverändert |
| causation_message_id | unmittelbare Ursache der aktuellen Antwort/Receipt |
| origin_task_id | lokale Steward-Task-ID |
| target_work_id | nach durabler Admission höchstens einmal |
| receipt_id | fachliche Receipt-Identität |
| receipt_content_digest | semantischer Receipt-Body-Hash |
| request_digest | semantischer Request-Hash |
| idempotency_key | fedv1: + request_digest |
| node_id | stabile Identity-Root-Node-ID |
| key_id | Signing-Key-Fingerprint, durch Root zertifiziert |

subject_message_id ist im Contract V1 verboten.

Initialer delegate_task:

- request_message_id = message_id
- causation_message_id ist verboten

Application-Reissue:

- neue message_id
- gleicher request_message_id wie der allererste Request
- causation_message_id verweist auf Statusantwort, Receipt-Reissue-Anforderung oder Recovery-
  Entscheidung
- gleiche delegation_id und gleicher request_digest
- kein neuer Request-Root

## 4. Transport-Retransmission und Application-Reissue

### Transport-Retransmission

- exakt gleiche kanonische Bytes
- gleiche message_id
- gleicher message_hash
- gleicher request_digest
- gleiche issued_at/expires_at
- gleiche Signatur
- nur vor expires_at
- kein neuer Ledger-Übergang
- kein neues target_work_id

### Application-Reissue

- neue message_id
- neue issued_at/expires_at
- neuer message_hash und neue Signatur
- gleiche delegation_id
- gleicher request_digest
- gleiche Authority, gleiches Target
- kein neues target_work_id bei bekanntem Target-Ledger-Zustand

Vor einem Reissue muss delegation_status_query oder vorhandene Status-Evidence belegen, dass
kein target_work_id und keine Admission existieren. Bei ACCEPTED, EXECUTING,
RECOVERY_REQUIRED oder terminalem Zustand ist Reissue verboten.

## 5. Semantischer Request-Digest

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

task_title ist nur Darstellung.

Digest-Input:

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

Eingeschlossen: contract_version, operation, source_node_id, target_node_id, delegation_id,
origin_task_id, capability, intent, task_description, target_repo, authority,
expected_outcome, verification_contract und deadline.

Ausgeschlossen: task_title, Message-/Receipt-IDs, issued_at, expires_at, message_hash,
signature, signer_key, key_id, request_digest und idempotency_key.

Berechnung:

~~~text
request_digest =
  lowercase_hex(SHA256(SFDJ-1(canonical_request_digest_input_utf8_bytes)))

idempotency_key =
  "fedv1:" + request_digest
~~~

Target berechnet selbst. Abweichungen:

- anderer Digest bei gleicher delegation_id → duplicate_conflict
- gleiche idempotency_key mit anderem Digest → idempotency_conflict
- falsch gelieferter Digest → request_digest_mismatch
- gleiche Payload mit neuer delegation_id → neue Delegation

## 6. Root-Identity, Node-ID und Key-ID

### Node-ID

~~~text
node_id =
  "ag_" + erste 32 lowercase Hex-Zeichen von
  SHA256(identity_root_public_key_hex_ascii)
~~~

Die Node-ID bleibt über Signing-Key-Rotation stabil.

### Root-Key

- Root-Ed25519-Key wird offline/HSM-geschützt beim Bootstrap erzeugt.
- Root-Private-Key verlässt den geschützten Besitz nicht und wird nicht im Runtime-Envelope
  übertragen.
- Eine verschlüsselte Recovery-Kopie wird getrennt aufbewahrt.
- Runtime-Worker erhalten nur aktivierte Signing-Keys.

Enrollment-Body:

~~~text
(node_id, identity_root_public_key, registry_epoch, not_before, provenance_metadata)
~~~

Root-Domain:

~~~text
STEWARD-FEDERATION-ROOT-ENROLLMENT-V1\0
~~~

Root-Enrollment ist ohne korrekte Root-Signatur und Node-ID-Ableitung ungültig.

### Signing-Key-Certificate

~~~text
(node_id, key_id, signer_key, not_before, not_after,
 rotation_kind, certificate_epoch)
~~~

Certificate-Domain:

~~~text
STEWARD-FEDERATION-SIGNING-KEY-AUTH-V1\0
~~~

Root autorisiert den Signing-Key; Registry aktiviert ihn separat mit activation_epoch und
activation_at. Eine Registry-Zeile ohne Root-Signatur bindet keinen Key.

### key_id

~~~text
key_id =
  "key_" + vollständige 64 lowercase Hex-Zeichen von
  SHA256(signing_public_key_raw_bytes)
~~~

Registry-Provenance:

~~~text
(node_id, key_id, signer_key, not_before, not_after, status, provenance)
~~~

### Rotation, Root-Ablösung und Kollision

- reguläre Rotation: neue key_id, stabile node_id, explizites Überlappungsfenster
- Notfallrotation: rotation_kind=emergency_compromise
- Root-Rotation: alte Root signiert neue Root; neue Root signiert Übergang; effective_at und
  transition_epoch sind Pflicht
- verlorene/kompromittierte Root: Governance-/Operator-Recovery mit explizitem Beleg;
  Runtime-Worker dürfen Root-Provenance nicht überschreiben
- gleiche node_id mit anderer Root: node_id_collision, Reject/Quarantine
- identisches Enrollment derselben Root: idempotent
- konkurrierende Enrollments: registry_epoch/Governance-Entscheidung; bis dahin nicht aktiv
- kein stilles Überschreiben und kein automatisches Umbenennen

## 7. Revocation-Zeitmodell

Jedes Key-Certificate enthält:

~~~text
not_before
not_after
revoked_at
revocation_effective_at
revocation_reason
rotation_kind
~~~

Semantik:

- not_before: frühester zulässiger issued_at.
- not_after: spätester zulässiger issued_at.
- revoked_at: Zeitpunkt der Registry-Eintragung.
- revocation_effective_at: Zeitpunkt, ab dem neue Messages abgelehnt werden.
- revocation_reason: rotation, compromise, lost, operator_action oder other.
- rotation_kind: regular oder emergency_compromise.

Reguläre Rotation:

- alte Messages mit issued_at < revocation_effective_at bleiben bei gültiger Provenance
  prüfbar.
- neue alte-Key-Messages nach effective_at werden abgelehnt.

Kompromittierung:

- bekannter compromise_time: revocation_effective_at = frühester belegter Kompromiss.
- unbekannter compromise_time: revocation_effective_at = früheste Registry-/Operator-
  Beobachtung.
- Messages im unbestimmten Intervall sind historical_uncertain und nicht allein aufgrund
  issued_at < revoked_at gültig.
- historical_uncertain benötigt unabhängige Evidence oder bleibt quarantänisiert.
- issued_at >= revocation_effective_at wird abgelehnt.
- emergency_compromise erlaubt keine automatische historische Verification aus Signatur allein.

Historische Verification benötigt:

1. Root- und Key-Provenance.
2. issued_at innerhalb not_before/not_after.
3. gültige Signatur, message_hash und Domain.
4. keine historical_uncertain-Markierung.
5. vorhandene Retention-Evidence.

Provenance wird mindestens bis not_after plus maximaler Envelope-Gültigkeit, Clock-Skew und
konfigurierter Audit-Retention erhalten. Gelöschte Provenance ergibt unavailable, nie verified.

## 8. SFDJ-1: Sprachneutrales Canonical JSON

Draft 0.4 verwendet das normative Profil Steward Federation Delegation JSON Canonicalization
Profile 1 (SFDJ-1).

### Parse

- Eingabe UTF-8 ohne BOM.
- Duplicate JSON Keys sind Parse-Fehler.
- Object member names und Stringwerte müssen bereits NFC sein.
- Nicht-NFC wird rejected_noncanonical, nicht still normalisiert.
- Unpaired Surrogates sind verboten.
- NFC-Prüfung rekursiv auf alle Schlüssel und Werte.

### Sortierung und Escapes

- Keys lexikographisch nach NFC-normalisierten UTF-8-Bytefolgen.
- Arrays behalten Reihenfolge.
- Keine Whitespace-Bytes außerhalb Stringwerte.
- Slash wird nicht escaped.
- Quote und Backslash mit Standard-JSON-Escape.
- U+0000 bis U+001F als lowercase \u00xx.
- Andere Unicode-Codepoints als UTF-8 ohne ASCII-Escaping.
- true, false und null unverändert.

### Zahlen

- Nur Integer -2^63 bis 2^63-1.
- Keine Floats, Exponentenschreibweise, führenden Pluszeichen oder führenden Nullen.
- -0, NaN und Infinity verboten.

### Canonicality-Check

- Eingehende unsigned bytes werden rekonstruiert und byteweise verglichen.
- Der vollständige Envelope muss ebenfalls bytegleich seiner SFDJ-1-Darstellung sein.
- Semantisch gleiche, byteverschiedene JSON-Darstellung wird rejected_noncanonical.
- Keine still normalisierte Eingabe wird gehasht oder signiert.

Limits:

- Envelope 256 KiB
- Payload 128 KiB
- Tiefe 16
- Array 1024 Elemente
- Object-Key 256 UTF-8 Bytes
- Einzelner String 64 KiB

### Version und Base64

- contract_version = federation-delegation-v1
- Base64 RFC 4648 Standard mit erforderlichem Padding
- URL-safe - und _ verboten
- Whitespace verboten
- Ed25519-Signatur decodiert exakt 64 Bytes

## 9. Envelope und Hash

Pflichtfelder:

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

Konditionen:

- Initialer delegate_task: request_message_id = message_id; causation_message_id verboten.
- Jede Antwort/Receipt: request_message_id und causation_message_id Pflicht.
- subject_message_id unbekannt und verboten.

Hash:

~~~text
message_hash =
  lowercase_hex(
    SHA256(SFDJ-1(canonical_envelope_without_message_hash_and_signature_utf8_bytes))
  )
~~~

Der Name payload_hash ist im V1-Envelope verboten und Legacy-only.

Domain Separation:

~~~text
STEWARD-FEDERATION-DELEGATION-V1\0
~~~

~~~text
signature_input =
  UTF8("STEWARD-FEDERATION-DELEGATION-V1\0")
  || raw_sha256_digest_bytes

signature =
  RFC4648_STANDARD_BASE64_WITH_PADDING(
    Ed25519_sign(signing_private_key, signature_input)
  )
~~~

## 10. Verifikationsreihenfolge und Fail-Closed

1. UTF-8-/BOM-/Duplicate-Key-Prüfung.
2. SFDJ-1-Canonicality und Schema.
3. contract_version und Limits.
4. Zeitprofil und Ablauf.
5. signer_key/key_id-Format.
6. Root-/Key-Certificate und Registry-Status.
7. Node-ID-Provenance.
8. Canonical Bytes rekonstruieren.
9. message_hash vergleichen.
10. Domain-separated Ed25519 prüfen.
11. target_node_id exakt prüfen.
12. request_digest bei delegate_task selbst berechnen.
13. Authority, Capability und Wiring.
14. Ledger-/Dedupe-Prüfung.
15. Admission/Fachdispatch.

Wrong target:

- internes Finding/Quarantine
- keine externe signierte Antwort
- kein Identity-/Routing-Orakel
- keine Ledger-Transition
- Rate-Limit/Amplification-Schutz

Authentifizierte fachliche Rejects am korrekten Target sind möglich. Unauthentifizierte
oder nicht adressierte Inputs erzeugen keine automatische Netzwerkantwort.

## 11. Receipt-IDs und Partial Order

Receipt-Envelope:

~~~text
message_id
request_message_id
causation_message_id
receipt_id
receipt_content_digest
receipt_stage
delegation_id
correlation_id
issuer_node_id
issuer_role
target_node_id
target_work_id
issued_at
expires_at
status
evidence_refs
message_hash
signature
signer_key
key_id
~~~

Partial Order:

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

Zulässige Vorgänger:

| Stage | Vorgänger |
|---|---|
| transport_committed | SENT/outbox commit |
| admission | SENT oder transport_committed |
| started | admission accepted |
| terminal | started im Target-Ledger |
| verification | terminal oder terminale Failure-Evidence |

Out-of-order terminal:

- Origin persistiert out_of_order_pending.
- Anwendung erst nach Target-Ledger-Evidence von Start und Work-Handle.
- Started-Receipt wird nicht erfunden; started_receipt_missing bleibt sichtbar.
- admission=rejected erlaubt weder Started noch Terminal.
- Widersprüche ergeben ledger_conflict.

## 12. Receipt-Retransmission und Receipt-Reissue

Transport-Retransmission:

- gleiche Bytes, message_id, receipt_id, receipt_content_digest, request_message_id,
  causation_message_id, issued_at/expires_at und Signatur
- nur vor expires_at
- kein neuer Ledger-Übergang

Application-Reissue:

- neue message_id, issued_at/expires_at, message_hash und Signatur
- gleiche receipt_id
- gleicher receipt_content_digest
- gleicher fachlicher Inhalt
- gleicher request_message_id
- causation_message_id referenziert Status-/Recovery-Entscheidung
- keine neue Stage und kein neuer Ledger-Übergang

receipt_content_digest:

~~~text
lowercase_hex(SHA256(SFDJ-1(canonical_receipt_content)))
~~~

receipt_content enthält receipt_id, receipt_stage, delegation_id, request_message_id,
target_work_id, status und evidence_refs. Es enthält nicht message_id, causation_message_id,
issued_at, expires_at, message_hash, signature, signer_key oder key_id.

Konflikte:

- gleiche receipt_id + gleicher content digest: Replay/Reissue erlaubt.
- gleiche receipt_id + anderer content digest: receipt_id_conflict.
- neue Stage: neue receipt_id, neue message_id, neuer Ledger-Übergang.

## 13. Status-Query

### delegation_status_query

Envelope:

- operation = delegation_status_query
- source_node_id = registrierter Origin
- target_node_id = exakter Zielknoten
- request_message_id = erste Request-Message
- causation_message_id fehlt bei erster Query
- correlation_id = delegation_id

Payload:

~~~json
{
  "delegation_id": "...",
  "request_message_id": "...",
  "known_request_digest": "...",
  "query_scope": "lifecycle_and_receipts"
}
~~~

Nur der registrierte Origin oder autorisierte Relay darf abfragen. Die Query ist read-only,
targetiert exakt, unterliegt Rate-Limit und erzeugt keine lokale Arbeit. Replay ist identisch;
neue Query kann neuen Snapshot anfordern. Falsche/unauthentifizierte Query erhält interne
Quarantine, keine automatische Signaturantwort. UNKNOWN darf einem authentifizierten,
korrekt adressierten Origin signiert zurückgegeben werden.

### delegation_status

Envelope:

- operation = delegation_status
- source_node_id = Target
- target_node_id = Origin
- request_message_id = erste Request-Message
- causation_message_id = Query-Message
- correlation_id = delegation_id

Payload:

~~~json
{
  "delegation_id": "...",
  "request_message_id": "...",
  "snapshot_id": "...",
  "snapshot_version": 7,
  "target_state": "UNKNOWN|ACCEPTED|EXECUTING|RECOVERY_REQUIRED|RESULT_REPORTED|REJECTED|EXPIRED",
  "target_work_id": null,
  "request_digest": "...",
  "observed_receipt_stages": [],
  "terminal_status": null,
  "as_of": "YYYY-MM-DDTHH:MM:SSZ"
}
~~~

snapshot_version ist monoton pro delegation_id. Statusantwort ist keine Receipt und keine
Verification. Sie folgt denselben Hash-, Signatur-, Replay- und Kausalitätsregeln.

## 14. Idempotenz, Recovery und Ledger

Target-Ledger:

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

Target-Ledger besitzt received, Admission, request_digest, target_work_id, Lease/Owner,
Execution, Recovery, terminales Resultat, Target-Receipts und Konflikte.

Origin-Ledger besitzt Request-Send, request_message_id, Transport-Evidence, Receipts,
Verification, einmalige Anwendung auf origin_task_id, Application-Reissues und Findings.

- Admission-/Dedupe-Commit vor Side Effect.
- Identischer Digest: bekanntes Resultat, kein zweiter Work-Handle.
- Konflikt-Digest: fail-closed.
- Crash vor Admission: identischer Request darf erneut angeboten werden.
- Crash nach Admission: target_work_id bleibt.
- Crash während Execution: Work-Handle fortsetzen oder recovery_required.
- Crash nach Terminal: Origin wendet Resultat einmal an.
- Lease-Ablauf erlaubt keinen blinden Zweitstart.
- Partielle Side Effects benötigen Dedup-Key, Read-back oder Recovery.
- Exactly-once wird nicht behauptet.

## 15. Capability-Status

Lifecycle maturity:

- declared
- partially_wired
- code_complete
- crucible_verified
- production_proven

Disposition:

- active
- unavailable
- legacy
- disabled

Manifest-Key:

~~~text
(operation, contract_version, repository, direction, target)
~~~

Verbotene Kombinationen:

- declared + active
- partially_wired + active
- unavailable + active
- legacy + active im federation-delegation-v1-Profil

active verlangt crucible_verified in Testprofilen und production_proven im Produktionsprofil.
disabled ist mit jeder Lifecycle-Stufe zulässig. implemented ist kein Draft-0.4-Status.

## 16. Offene Abhängigkeiten und Readiness

- ADR-01 für isolierte Wire-Semantik offen zulässig.
- ADR-03 vor Managed-Task-COMPLETED-Mapping erforderlich.
- ADR-04 offen, solange kein providerabhängiger V1-Crucible verwendet wird.
- ADR-05 vor Produktions-Crucible erforderlich.
- ADR-10 vor vollständiger Integration erforderlich.
- ADR-06 bleibt bis Agent-B-Abnahme der Root-/Key-/Revocation-/SFDJ-1-Regeln offen.

READY FOR GOLDEN FIXTURES erst wenn:

1. Root-Identity, Key-Certificate, Rotation, Revocation und Collision-Handling akzeptiert.
2. SFDJ-1 sprachneutral akzeptiert.
3. Request-/Receipt-Reissue akzeptiert.
4. Request-Root und Kausalitäts-IDs akzeptiert.
5. Status Query vollständig spezifiziert und verkabelt.
6. Wrong-Target/Auth-Failure widerspruchsfrei.
7. Capability-Statusmodell akzeptiert.
8. Erste Payload-Subschemas eingefroren.

Bis dahin bleiben Produktcode, Fixtures, Crucible-Design, Merge, Phase 1 und Context Bridge
gesperrt.
