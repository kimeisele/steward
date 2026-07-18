# ADR DECISION SPRINT 1C — NORMATIVE REVISION

> Status: ACCEPTED — SPRINT 1C FREEZE (enger Federation-V1-Scope)
> Datum: 2026-07-18
> Scope: Federation Delegation Contract V1; kein Produktcode

Sprint 1C behandelt ausschließlich die von Agent B in Draft 0.3 identifizierten normativen
Lücken. Draft 0.5 ist die eingefrorene Contract-Fassung; die Entscheidung ist im engen
Federation-V1-Wire-Scope ACCEPTED. Produktcode und Fixtures bleiben gesperrt.

## 1. Status

| ADR | Status |
|---|---|
| ADR-02 | ACCEPTED — SPRINT 1C FREEZE |
| ADR-06 | ACCEPTED — SPRINT 1C FREEZE |
| ADR-07 | ACCEPTED — SPRINT 1C FREEZE |
| ADR-08 | ACCEPTED — SPRINT 1C FREEZE |
| ADR-09 | ACCEPTED — SPRINT 1C FREEZE |

## 2. Wrong-Target und Auth-Failure

Ein target_node_id, das nicht der lokalen Node-ID entspricht, erzeugt ausschließlich:

- internes Finding/Quarantine
- Rate-Limit und Amplification-Schutz
- keine signierte Netzwerkantwort
- kein Reject-Receipt
- kein Routing-/Identity-Orakel
- keine Target-/Origin-Ledger-Transition

Das gilt auch bei gültiger Signatur und Registry-Provenance. Die lokale Node bestätigt nicht,
ob eine andere Node, Capability oder Authority existiert.

Ein externes signiertes Reject-Receipt ist nur zulässig, wenn Signatur, Registry-Provenance,
Sender-Authority und korrektes lokales Target bereits erfolgreich geprüft sind. Zulässige
fachliche Rejects sind unsupported_contract, authority_denied, capability_unavailable,
request_digest_mismatch, duplicate_conflict, idempotency_conflict und expired.

## 3. Root-Identity und Key-Provenance

### Root

- Root-Ed25519-Key wird beim Bootstrap offline/HSM-geschützt erzeugt.
- Root-Private-Key wird nie übertragen und nie in Runtime-Envelopes eingebettet.
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

Die Registry akzeptiert ein Enrollment nur nach korrekter Root-Signatur, Node-ID-Ableitung,
Registry-Epoch-Prüfung und Kollisionsprüfung.

Im Sprint-1C-Freeze ist dieser Record geschlossen: exakt
enrollment_version=federation-root-enrollment-v1, identity_root_public_key (PublicKeyB64,
32 rohe Bytes), node_id, not_before, provenance_digest (HashHex), registry_epoch (Integer
0..2^63-1) und root_signature (SignatureB64, 64 Bytes), keine Unknown-Fields/null. Die
Signatur ist Ed25519 über Domain STEWARD-FEDERATION-ROOT-ENROLLMENT-V1 plus NUL und die
rohen SHA-256-Bytes der SFDJ-1-Codierung ohne root_signature.

### Stabile Node-ID

~~~text
node_id =
  "ag_" + erste 32 lowercase Hex-Zeichen von
  SHA256(identity_root_public_key_hex_ascii)
~~~

Die Node-ID bleibt bei Signing-Key-Rotation stabil.

### Signing-Key-Zertifikat

~~~text
(node_id, key_id, signer_key, not_before, not_after,
 rotation_kind, certificate_epoch)
~~~

Root-Domain:

~~~text
STEWARD-FEDERATION-SIGNING-KEY-AUTH-V1\0
~~~

Eine Registry-Zeile ohne Root-signiertes Key-Certificate ist keine ausreichende Key-Bindung.

Das Certificate ist ebenfalls geschlossen: activation_at, activation_epoch,
certificate_epoch, certificate_version=federation-signing-key-auth-v1,
identity_root_public_key, key_id, node_id, not_after, not_before, registry_epoch,
revocation_ref (HashHex oder null), rotation_kind=regular|emergency_compromise,
signer_key (PublicKeyB64) und root_signature. Seine Root-Signatur verwendet dieselbe
SFDJ-1-Regel mit Domain STEWARD-FEDERATION-SIGNING-KEY-AUTH-V1 plus NUL. Activation,
Epochs, Key-ID-/Node-ID-Ableitung und Zeitfenster werden vor Aktivierung geprüft.

### key_id und Aktivierung

~~~text
key_id =
  "key_" + vollständige 64 lowercase Hex-Zeichen von
  SHA256(signing_public_key_raw_bytes)
~~~

Ablauf:

1. Certificate wird als pending registriert.
2. Registry aktiviert mit activation_epoch und activation_at.
3. Signing vor activation_at ist verboten.
4. Target prüft Root-Certificate und Registry-Status.

### Rotation, Root-Ablösung, Collision

- reguläre Rotation: neue key_id, stabile node_id, explizites Überlappungsfenster
- emergency_compromise: sofortige Sperre für neue Messages
- Root-Rotation: alte Root signiert neue Root; neue Root signiert Übergang; effective_at und
  transition_epoch sind Pflicht
- Root-Verlust/-Kompromittierung: Governance-/Operator-Recovery mit explizitem Beleg
- gleiche node_id mit anderer Root: node_id_collision, Reject/Quarantine
- identisches Enrollment derselben Root: idempotent
- konkurrierende Registrierungen: registry_epoch/Governance-Entscheidung; bis dahin nicht aktiv
- kein stilles Überschreiben oder automatisches Umbenennen

## 4. Revocation-Zeitmodell

Jedes Key-Certificate führt:

~~~text
not_before
not_after
revoked_at
revocation_effective_at
revocation_reason
rotation_kind
~~~

- not_before: frühester zulässiger issued_at
- not_after: spätester zulässiger issued_at
- revoked_at: Registrierung der Revocation
- revocation_effective_at: Beginn der Ablehnung neuer Messages
- revocation_reason: rotation, compromise, lost, operator_action oder other
- rotation_kind: regular oder emergency_compromise

Reguläre Rotation lässt alte Messages mit issued_at vor effective_at bei vollständiger
Provenance verifizierbar.

Bei Kompromittierung:

- bekannter compromise_time: effective_at = frühester belegter Kompromiss
- unbekannter compromise_time: effective_at = früheste Registry-/Operator-Beobachtung
- Zwischenzeit: historical_uncertain, nicht allein aufgrund issued_at < revoked_at gültig
- zusätzliche unabhängige Evidence erforderlich, sonst Quarantine
- issued_at >= effective_at wird abgelehnt
- emergency_compromise erzeugt keine automatische historische Verification

Historische Verifikation benötigt Root-/Key-Provenance, gültiges Zeitfenster, gültige Domain-
Signatur und keine historical_uncertain-Markierung. Provenance wird mindestens bis not_after
plus maximaler Envelope-Gültigkeit, Clock-Skew und konfigurierte Audit-Retention behalten.
Gelöschte Provenance ergibt unavailable, nie verified.

## 5. SFDJ-1 Canonical JSON

Draft 0.4 verwendet das sprachneutrale Steward Federation Delegation JSON Canonicalization
Profile 1 (SFDJ-1).

- UTF-8 ohne BOM
- Duplicate Keys sind Parse-Fehler
- Object Keys und Stringwerte müssen bereits NFC sein; Nicht-NFC wird abgelehnt
- rekursive NFC-Prüfung auf alle Keys und Stringwerte
- unpaired Surrogates verboten
- Keys nach NFC-normalisierten UTF-8-Bytefolgen lexikographisch sortiert
- Arrays behalten Reihenfolge
- keine Whitespace-Bytes außerhalb von Strings
- Slash wird nicht escaped
- Quote/Backslash Standard-Escape
- U+0000 bis U+001F als lowercase \u00xx
- sonstige Unicode-Codepoints als UTF-8 ohne ASCII-Escaping
- nur Integer -2^63 bis 2^63-1
- keine Floats, Exponenten, führenden Pluszeichen, führenden Nullen, -0, NaN, Infinity
- vollständige Eingangsbytes müssen bytegleich der SFDJ-1-Rekonstruktion sein
- semantisch gleiche, byteverschiedene Bytes werden rejected_noncanonical
- Envelope 256 KiB, Payload 128 KiB, Tiefe 16, Array 1024, Key 256 Bytes, String 64 KiB
- Base64 RFC 4648 Standard mit erforderlichem Padding; URL-safe Zeichen und Whitespace verboten
- contract_version exakt federation-delegation-v1

## 6. Request- und Receipt-Reissue

Request-Transport-Retransmission:

- gleiche Bytes, message_id, message_hash, request_digest, issued_at, expires_at und Signatur
- nur vor Ablauf, kein neuer Ledger-Übergang

Request-Application-Reissue:

- neue message_id, issued_at/expires_at, message_hash und Signatur
- gleiche delegation_id, request_digest, Authority, Target und request_message_id
- causation_message_id verweist auf Status-/Recovery-Entscheidung
- nur nach Status Query bei UNKNOWN oder delivery_expired_before_admission
- kein neues target_work_id bei bekannter Admission/Execution/Recovery

Receipt-Transport-Retransmission:

- gleiche Bytes, message_id, receipt_id, receipt_content_digest, request_message_id,
  causation_message_id, Zeitwerte und Signatur
- nur vor Ablauf

Receipt-Application-Reissue:

- neue message_id, issued_at/expires_at, message_hash und Signatur
- gleiche receipt_id und gleicher receipt_content_digest
- gleicher fachlicher Inhalt
- gleicher request_message_id
- neue causation_message_id
- keine neue Receipt-Stufe und kein neuer Ledger-Übergang

receipt_content_digest:

~~~text
lowercase_hex(SHA256(SFDJ-1(canonical_receipt_content)))
~~~

receipt_content enthält receipt_id, receipt_stage, delegation_id, request_message_id,
target_work_id, status und evidence_refs. Transport-, Envelope- und Signatur-IDs sind
ausgeschlossen.

Gleiche receipt_id mit gleichem content digest ist Replay/Reissue. Gleiche receipt_id mit
anderem content digest ist receipt_id_conflict.

## 7. Request-Root und Kausalität

- request_message_id bleibt über den gesamten Lifecycle die allererste delegate_task-Message.
- Application-Reissue erhält niemals einen neuen Request-Root.
- causation_message_id verweist auf die unmittelbar auslösende Statusantwort, Receipt-Reissue-
  Anforderung oder Recovery-Entscheidung.
- Jede Receipt-/Result-Message ist direkt zum ersten Request zurückführbar.
- subject_message_id ist im V1-Schema verboten.

## 8. Status-Query-Contract

### delegation_status_query

- Origin → exakter Target
- source_node_id = registrierter Origin
- target_node_id = ursprünglicher Zielknoten
- request_message_id = erste Request-Message
- causation_message_id fehlt bei erster Query
- correlation_id = delegation_id
- read-only, kein Target-Ledger-Side-Effect
- nur registrierter Origin/autorisiertes Relay
- Rate-Limit pro Source und Delegation
- UNKNOWN darf authentifiziert und korrekt adressiert signiert zurückgegeben werden
- falsche/unauthentifizierte Query: internes Finding/Quarantine ohne Antwort

Payload:

~~~json
{
  "delegation_id": "...",
  "request_message_id": "...",
  "known_request_digest": "...",
  "query_scope": "lifecycle_and_receipts"
}
~~~

### delegation_status

- Target → registrierter Origin
- source_node_id = Target
- target_node_id = Origin
- request_message_id = erste Request-Message
- causation_message_id = Query-Message
- correlation_id = delegation_id
- signierter Snapshot, keine Receipt und keine Verification

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

Für Target-Status ist terminal_status ausschließlich completed, failed oder null; verified
und failed_verification gehören ausschließlich dem Origin-Ledger und der verification-
Receipt. Bei unbekannter ID oder fremdem Origin liefert das Target denselben minimalen
UNKNOWN-Snapshot wie bei einer unbekannten Delegation; keine Reason-/Timing-Differenz.
snapshot_version ist monoton pro delegation_id. Query-Replay ist idempotent; neue Queries
erzeugen keine Arbeit. Wiring verlangt Emitter, exact target, read_status Authority,
read-only Target-Handler, Snapshot-Result, Replay-/Rate-Limit-/UNKNOWN-/Wrong-Target-Tests
und Produktions-Evidence.

## 9. Capability-Statusachsen

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

Verboten:

- declared + active
- partially_wired + active
- unavailable + active
- legacy + active im federation-delegation-v1-Profil

active verlangt crucible_verified im Testprofil und production_proven im Produktionsprofil.
disabled ist mit jeder Reife zulässig. implemented ist kein Draft-0.4-Status.

## 10. Review-Gate

Der historische Draft-0.4-Gate-Text verlangte Agent-B-Bestätigung von Root-/Key-/Revocation-
Vertrag, SFDJ-1, Request-/Receipt-Reissue, Request-Root, Status Query, Wrong-Target-Regel,
Auth-Failure-Trennung, Capability-Statusachsen und Payload-Subschemas. Dieses Gate ist in
§11 durch den Sprint-1C-Freeze erfüllt und superseded.

Bis dahin kein Produktcode, keine Fixtures, kein Crucible-Design, kein Merge. Phase 1 und
Context Bridge bleiben unverändert.

## 11. Sprint-1C-Freeze

Agent-Bs drei engen Freeze-Aufgaben sind normativ geschlossen:

1. Die Payload-Schemas für delegate_task, delegation_receipt (transport_committed,
   admission, started, terminal, verification), delegation_status_query und
   delegation_status sind geschlossen: Typen, Pflichtfelder, Nullability, Limits, Enums,
   Unknown-Field-Verbot, Digest-Bindung sowie Authority-/Privacy-Bedeutung stehen in Draft
   0.5 und dem self-contained Freeze-Packet.
2. Root-Verlust oder -Kompromittierung wird nicht automatisch durch Federation repariert.
   Die Node fail-closed für neue V1-Nachrichten; Root-Recovery/Neu-Enrollment ist manuell,
   out-of-band und nicht Teil von V1. Quorum, automatische Übernahme und Root-Replacement
   sind ausdrückliche Nicht-Ziele; Historie und Audit bleiben erhalten.
3. Status Query ist auf die kryptografisch gebundene eigene delegation_id begrenzt.
   Das Snapshot-Schema ist minimal; fremde Delegationen, Worker-/Lease-Details,
   Stacktraces, Secrets, Pfade und nicht vertragliche Evidence werden nicht ausgegeben.
   UNKNOWN ist kein Existenz-Orakel; Rate-Limit und Audit-Finding bleiben lokal.

SFDJ-1 ist unverändert eingefroren. Draft 0.5 ist **READY FOR GOLDEN FIXTURES**. Dieser
Status autorisiert ausschließlich den nächsten Dokument-/Test-Milestone (Golden-Wire-
Fixtures und unabhängige Parser-/Signaturtests), nicht Produktimplementierung oder
Crucible-Ausführung. ADR-03, ADR-05 und ADR-10 bleiben spätere Integrationsblocker.
