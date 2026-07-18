# FEDERATION DELEGATION CONTRACT V1 — DRAFT 0.5

> Status: READY FOR GOLDEN FIXTURES (normativer Wire-Freeze; keine Fixtures/Implementierung)
> Datum: 2026-07-18
> Scope: enge, signierte Federation-Delegation zwischen Steward (Origin) und Agent City (Target)
> Gate: SFDJ-1 unverändert eingefroren; ADR-02/-06/-07/-08/-09 ACCEPTED im engen V1-Scope
> Sperre: kein Produktcode, keine Handler-/Ledger-/Workflow-Änderung, keine Aktivierung, kein Merge

Draft 0.5 ersetzt Draft 0.4. Die Regeln dieses Dokuments sind die einzige V1-Wire-Basis
für Golden-Wire-Fixtures. Spätere Execution-Spine-Arbeit darf sie nur als belegten Vertrag
konsumieren; sie darf hier keine impliziten Defaults ergänzen.

## 1. Zweck und Nicht-Ziele

Zweck:

~~~text
Origin Managed Task
  -> kanonischer, signierter, exakt adressierter delegate_task
  -> Target Admission und persistente Deduplizierung
  -> höchstens ein target_work_id
  -> gestartete und terminale Evidence
  -> Origin-Korrelation und unabhängige Verification
~~~

Nicht-Ziele:

- universelle Execution Spine
- Provider-Failover oder Provider-Chamber-Vertrag
- automatische Merge-Autorität
- Context-Bridge-Aktivierung
- Broadcast, Titelmatching oder stiller Legacy-Fallback
- automatische Governance, Quorum oder Root-Übernahme
- Exactly-once-Ausführung (Transport ist at-least-once)

## 2. V1-Operationen und Rollen

| Operation | Richtung | Aussteller/Empfänger | Wirkung |
|---|---|---|---|
| delegate_task | Origin -> Target | Origin / Target | Admission einer konkreten Arbeit |
| delegation_status_query | Origin -> Target | Origin oder berechtigter Relay / Target | read-only Snapshot-Anfrage |
| delegation_status | Target -> Origin | Target / Origin | minimaler, signierter Snapshot |
| delegation_receipt | Target/Relay/Origin -> berechtigter Peer | stage-spezifischer Issuer | Evidence ohne neue Arbeit |
| task_completed | Target -> Origin | Target / Origin | Legacy-Alias; V1 nutzt terminal receipt |
| task_failed | Target -> Origin | Target / Origin | Legacy-Alias; V1 nutzt terminal receipt |

task_completed und task_failed sind im Draft 0.5 keine separaten Wire-Schemas:
ein V1-Target sendet delegation_receipt mit receipt_stage=terminal. Verification wird
als delegation_receipt mit receipt_stage=verification gebunden.

## 3. Identitäten und Kausalität

| Feld | Typ und Erzeuger | V1-Invariante |
|---|---|---|
| delegation_id | IdString; Origin vor dem ersten Send | pro Delegations-Lifecycle genau einmal erzeugt, unverändert |
| correlation_id | IdString; Origin | exakt gleich delegation_id in allen V1-Nachrichten |
| message_id | IdString; aktueller Envelope-Issuer | jede logische Wire-Message einmal; vor Signatur erzeugt |
| request_message_id | IdString; Origin beim ersten Request | zeigt immer auf die allererste delegate_task-Message; bei Reissue unverändert |
| causation_message_id | IdString oder verboten | unmittelbare auslösende Nachricht; initialer Request hat kein Feld |
| origin_task_id | IdString; Origin | lokaler Task; nie vom Target neu interpretiert |
| target_work_id | IdString; Target nach durabler Admission | höchstens einmal pro delegation_id; nach Admission unverändert |
| receipt_id | IdString; Receipt-Issuer | fachliche Receipt-Identität; gleiche Stage/gleicher Inhalt = gleiche ID |
| request_digest | HashHex; Origin und Target unabhängig berechnet | semantischer Request-Hash, bei Reissue unverändert |
| idempotency_key | fedv1: + 64 Hex; Origin | exakt aus request_digest abgeleitet, frei gewählte Werte ungültig |
| receipt_content_digest | HashHex; Receipt-Issuer und Empfänger | Hash des semantischen Receipt-Inhalts, nicht des Envelope |
| node_id | NodeId; Registry aus Root | über Signing-Key-Rotation stabil |
| key_id | KeyId; Registry aus Signing-Key | identifiziert den aktiven Signing-Key |

subject_message_id ist in V1 verboten. Ein initialer delegate_task setzt
request_message_id = message_id und darf causation_message_id nicht enthalten.
Jede Receipt-, Result- und Status-Message trägt request_message_id der allerersten
Request-Message. Ein Reissue erhält eine neue message_id, aber keinen neuen Request-Root.

## 4. Transport-Retransmission und Application-Reissue

Transport-Retransmission ist ausschließlich eine erneute Zustellung derselben gültigen
Message:

- identische SFDJ-1-Bytes, message_id, message_hash, Signatur, issued_at, expires_at,
  request_digest und receipt_content_digest (falls Receipt)
- nur solange issued_at <= now < expires_at
- kein neuer Ledger-Übergang, kein neuer Work-Handle, keine neue Receipt-ID
- Empfänger behandelt identische Bytes als Replay und bestätigt lokal dedupliziert

Application-Reissue ist ein neuer fachlicher Sendversuch nach Statusabfrage oder Recovery-Entscheidung:

- neue message_id, issued_at, expires_at, message_hash und Signatur
- gleiche delegation_id, request_message_id, correlation_id, Target, Authority und
  semantische Payload; gleicher request_digest und idempotency_key
- causation_message_id zeigt auf die unmittelbar auslösende Status-/Recovery-Evidence
- vor Reissue muss eine gültige Statusabfrage/Evidence zeigen, dass kein Admission-Handle
  existiert; bei ACCEPTED, EXECUTING, RECOVERY_REQUIRED, RESULT_REPORTED,
  REJECTED oder EXPIRED ist blindes Reissue verboten
- Target dedupliziert über delegation_id plus request_digest; es entsteht niemals ein
  zweites target_work_id

## 5. Geschlossene Primitive und SFDJ-1

Alle Envelopes und Payloads verwenden das unverändert eingefrorene Profil
Steward Federation Delegation JSON Canonicalization Profile 1 (SFDJ-1):

- UTF-8 ohne BOM; Duplicate-JSON-Keys sind Fehler.
- Schlüssel und Stringwerte müssen rekursiv bereits NFC sein; nicht-NFC wird abgelehnt.
- Schlüssel werden lexikographisch nach NFC-UTF-8-Bytes sortiert; Array-Reihenfolge bleibt.
- Keine äußeren Whitespace-Bytes; Slash wird nicht escaped; Quote/Backslash standardmäßig.
- Steuerzeichen U+0000..U+001F als lowercase \u00xx; sonst Unicode als UTF-8 ohne
  ASCII-Escaping.
- Nur Integer -2^63..2^63-1; keine Floats, Exponenten, führenden Pluszeichen, führenden
  Nullen, -0, NaN oder Infinity.
- Eingangsbytes müssen bytegleich der SFDJ-1-Rekonstruktion sein; semantisch gleiche, aber
  byteverschiedene JSON-Darstellung ist rejected_noncanonical.
- RFC-3339-Zeitwerte sind exakt YYYY-MM-DDTHH:MM:SSZ in UTC, ohne Fractional Seconds,
  Offset oder Leap-Second.
- Base64 ist RFC-4648 Standardalphabet mit erforderlichem Padding; URL-safe Zeichen,
  Whitespace und fehlendes Padding sind ungültig.
- Maxima: Envelope 256 KiB, Payload 128 KiB, Verschachtelung 16, Arrays 1024 Elemente,
  Objekt-Key 256 UTF-8-Bytes, String 64 KiB.
- contract_version ist exakt federation-delegation-v1.

Primitive Profile:

| Name | Form |
|---|---|
| IdString | ASCII [A-Za-z0-9][A-Za-z0-9._:-]{0,127}, nicht-null, kein Whitespace |
| NodeId | exakt ag_ plus 32 lowercase Hexzeichen |
| KeyId | exakt key_ plus 64 lowercase Hexzeichen |
| HashHex | exakt 64 lowercase Hexzeichen |
| Timestamp | exakt YYYY-MM-DDTHH:MM:SSZ |
| DisplayText | UTF-8/NFC, optional, bei Anwesenheit nicht-null; nur Darstellung |
| EvidenceRef | ASCII/UTF-8 URI, 1..256 Bytes; keine Secrets |
| PublicKeyB64 | RFC-4648 Standard-Base64 mit Padding; decoded exakt 32 rohe Ed25519-Bytes |
| SignatureB64 | RFC-4648 Standard-Base64 mit Padding; decoded exakt 64 Ed25519-Signaturbytes |

Kein Feld ist implizit nullable. null ist nur dort erlaubt, wo ein Schema es ausdrücklich
als Zustandsträger nennt. Payload- und Top-Level-Unknown-Fields sind verboten.

## 6. Geschlossene Payload-Schemas (V1)

Die folgenden Tabellen sind geschlossene Schemas. Ein nicht genannter Key ist ungültig.
Darstellungsfelder display_title und display_description steuern niemals Dispatch,
Authority, Korrelation, Idempotenz oder Verification.

### 6.1 delegate_task

Payload-Maximum 128 KiB; alle Pflichtfelder nicht-null.

| Feld | Typ / Grenze | Req. | Enum/Null | Digest / Autorität / Datenschutz |
|---|---|---:|---|---|
| delegation_id | IdString | ja | keine/null | eingeschlossen; bindet Lifecycle |
| origin_task_id | IdString | ja | keine/null | eingeschlossen; Origin-local |
| capability | Token [a-z][a-z0-9_.-]{0,63} | ja | V1-Fixture-Enum fix_repository; andere Werte nur nach signiertem Wiring-Manifest | eingeschlossen; Dispatch/Authority |
| intent | Objekt exakt {kind,version} | ja | kind=repair, version=v1 | eingeschlossen; Dispatch |
| task_description | NFC-String 1..4096 Bytes | ja | nicht-null | eingeschlossen; gebundener Arbeitskontext, steuert nie Capability/Authority/Verification |
| target_repo | IdString, 1..128 | ja | nicht-null | eingeschlossen; Target-Scope |
| authority | geschlossenes Objekt, max 8 Actions | ja | nicht-null | eingeschlossen; Sicherheitsgrenze |
| expected_outcome | exakt {kind:verified_tests_and_observation} | ja | nicht-null | eingeschlossen; Verification-Vorbedingung |
| verification_contract | geschlossenes Objekt | ja | nicht-null | eingeschlossen; Verification |
| deadline | Timestamp | ja | nicht-null | eingeschlossen; Ablauf/Recovery |
| request_digest | HashHex | ja | nicht-null | Darstellung des Bindungsbeweises; selbst nicht in Digest |
| idempotency_key | exakt fedv1: + 64 Hex | ja | nicht-null | aus Digest; selbst nicht in Digest |
| display_title | DisplayText, max 256 Bytes | nein | nicht-null falls vorhanden | ausgeschlossen; reine UI |
| display_description | DisplayText, max 4096 Bytes | nein | nicht-null falls vorhanden | ausgeschlossen; reine UI |

authority ist exakt:
allowed_actions Array (1..8, unique, Enum read|test|branch|commit),
denied_actions Array (0..8, unique, Enum merge|secret_access|context_bridge_activation) und
repo_scope IdString. Keine zusätzlichen Keys, keine null.

verification_contract ist exakt:
postcondition_kind=tests_and_runtime_observation und
required_evidence Array (1..4, unique, Enum test_result|runtime_observation).
intent, expected_outcome und diese Authority-Objekte sind keine freien Prosaobjekte.

Request-Digest-Input ist SFDJ-1 über:

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
    "intent": {"kind":"repair","version":"v1"},
    "task_description": "...",
    "target_repo": "...",
    "authority": {},
    "expected_outcome": {"kind":"verified_tests_and_observation"},
    "verification_contract": {},
    "deadline": "..."
  }
}
~~~

Ausgeschlossen sind Envelope-Metadaten, IDs außer den genannten semantischen IDs,
display_*, request_digest und idempotency_key. Berechnung:
request_digest = lowercase_hex(SHA256(SFDJ-1(canonical_request_digest_input)));
idempotency_key = fedv1: + request_digest. Target berechnet selbst. Falsch gelieferter
Digest ist request_digest_mismatch; gleiche delegation_id mit anderem Digest ist
duplicate_conflict; gleiche Idempotency-Key mit anderem Digest ist idempotency_conflict.

### 6.2 delegation_receipt

Payload-Maximum 128 KiB; receipt_id, delegation_id, receipt_stage, issuer_role, status,
receipt_content_digest sind immer Pflicht und nicht-null. Stage-Enum:
transport_committed|admission|started|terminal|verification.

issuer_role ist ein geschlossener Stage-Enum-Wert aus relay|hub|target_node|target_scheduler|
target_worker|origin_node; der Wert muss der Stage-Tabelle entsprechen. Gemeinsame optionale Keys und Limits:
target_work_id IdString, stageabhängig nullable; reason_code Enum, max 64;
evidence_refs Array 0..8 von EvidenceRef; freie Evidence-Daten sind nicht erlaubt. Die
Stage-Regel überschreibt das allgemeine Array-Maximum: terminal und verification verlangen
1..8 EvidenceRefs; admission und started erlauben 0..4; transport_committed verlangt
mailbox_ref und keine freien EvidenceRefs.

| Stage | Issuer-Rolle | Status-Enum | Zusätzliche geschlossene Felder und Regeln |
|---|---|---|---|
| transport_committed | relay oder hub | committed | target_work_id muss null/fehlen; mailbox_ref EvidenceRef Pflicht; keine Arbeitsbehauptung |
| admission | target_node | accepted oder rejected | target_work_id genau bei accepted Pflicht, bei rejected null/fehlend; rejected verlangt reason_code aus unsupported_contract|authority_denied|capability_unavailable|request_digest_mismatch|duplicate_conflict|idempotency_conflict|expired; accepted höchstens 4 EvidenceRefs |
| started | target_scheduler | started | target_work_id, started_at Timestamp und attempt_count Integer 1..32 Pflicht; keine Ergebnisbehauptung |
| terminal | target_worker oder target_node | completed oder failed | target_work_id, started_at, ended_at, attempt_count Pflicht; genau eines von outcome oder failure; outcome exakt {result_kind:tests_and_observation,test_status:passed|failed}; failure.code Enum target_execution_failed|target_result_unverifiable|recovery_required|expired|authority_denied|capability_unavailable|unknown |
| verification | origin_node | verified oder failed_verification | target_work_id, verification_kind=independent_postcondition und 1..8 EvidenceRefs Pflicht; keine neue Target-Arbeit |

Alle Stage-Payloads sind geschlossen; issuer_role ist ein Pflichtfeld und kein freier
String. receipt_content_digest umfasst receipt_id, stage, issuer_role, delegation_id,
target_work_id, status, reason_code, EvidenceRefs, Zeitfelder, attempt_count, outcome/failure
und stage-spezifische Werte. Er umfasst nicht Envelope-IDs, Envelope-Zeit, Hash, Signatur,
Key, receipt_content_digest selbst oder Darstellungsfelder. Ein semantisch gleicher
Receipt-Body muss denselben Digest tragen.

### 6.3 delegation_status_query

Geschlossenes Payload-Maximum 2 KiB, alle Felder Pflicht und nicht-null:

| Feld | Typ / Enum | Digest/Authority/Privacy |
|---|---|---|
| delegation_id | IdString | Query-Bindung; nur eigene kryptografisch gebundene ID |
| request_message_id | IdString | muss erste delegate_task-Message sein; Query-Kausalität |
| known_request_digest | HashHex | Target vergleicht gegen Ledger; Bindungs-/Konfliktnachweis |
| query_scope | Enum exakt lifecycle_and_receipts | keine Erweiterung in V1 |

Nur der registrierte Origin darf seine Delegation abfragen. Ein Relay benötigt eine
explizite, auf diese delegation_id begrenzte Leseberechtigung. Falsches Target oder
unauthentifizierter Sender erzeugt nur lokales Finding/Quarantine, keine Netzwerkantwort.
Rate-Limit und Audit sind lokal. Query ist read-only und erzeugt keine Arbeit.

### 6.4 delegation_status

Geschlossenes Payload-Maximum 8 KiB, alle Felder Pflicht außer ausdrücklich nullable:

| Feld | Typ / Enum / Grenze | Semantik und Datenschutz |
|---|---|---|
| delegation_id | IdString | angefragte, kryptografisch gebundene ID |
| request_message_id | IdString | erster Request-Root |
| snapshot_id | IdString | eindeutige Snapshot-Version |
| snapshot_version | Integer 0..2^63-1 | monoton pro delegation_id |
| target_state | Enum UNKNOWN|ACCEPTED|EXECUTING|RECOVERY_REQUIRED|RESULT_REPORTED|REJECTED|EXPIRED | eingefrorener Zielzustand |
| target_work_id | IdString oder null | non-null für ACCEPTED/EXECUTING/RECOVERY_REQUIRED/RESULT_REPORTED; null für UNKNOWN/REJECTED/EXPIRED |
| request_digest | HashHex | verifizierte Bindung |
| observed_receipt_stages | Array 0..5, unique, Enum aus fünf Stages, SFDJ-sortiert | nur beobachtete Stufen |
| terminal_status | Enum completed|failed|verified|failed_verification oder null | non-null nur bei RESULT_REPORTED |
| as_of | Timestamp | Snapshot-Zeit |

Die Antwort enthält niemals Worker-Identität, Lease-Owner, Stacktrace, Secret, Dateipfad,
interne Evidence oder fremde Delegationen. UNKNOWN offenbart keine Existenz anderer IDs,
Capabilities oder Knoten. Eine korrekt authentifizierte, korrekt adressierte Origin darf
für ihre eigene unbekannte ID den minimalen UNKNOWN-Snapshot erhalten. Das Statusobjekt
ist weder Receipt noch Verification; es ist signiert und über Request-Root/Kausalitäts-ID
gebunden.

## 7. Root-Identität, Registrierung und Recovery

node_id = ag_ + first_32_lower_hex(SHA256(identity_root_public_key_hex_ascii)).
identity_root_public_key ist in Registry-/Enrollment-Provenance als PublicKeyB64 (rohe,
decoded 32-Byte-Ed25519-Key) gespeichert; identity_root_public_key_hex_ascii ist dessen
lowercase Hexdarstellung ausschließlich für die Node-ID-Ableitung. Die Root ist Ed25519,
wird offline/HSM-geschützt erzeugt und nie in Runtime-Envelopes
übertragen. Root-Provenance umfasst Enrollment-Body, Root-Signatur, Registry-Epoch,
not_before und Retention. Ein Signing-Key wird über ein Root-signiertes Certificate
mit key_id, Zeitfenster, rotation_kind und certificate_epoch autorisiert; eine Registry-Zeile
allein bindet keinen Key.

Root-Enrollment und Signing-Key-Autorisierung verwenden:
STEWARD-FEDERATION-ROOT-ENROLLMENT-V1\0 bzw.
STEWARD-FEDERATION-SIGNING-KEY-AUTH-V1\0. Node-ID-Kollisionen werden quarantänisiert;
kein stilles Überschreiben oder Umbenennen. Signing-Key-Rotation hält node_id stabil.

**Root-Recovery ist ausdrücklich kein V1-Protokollbestandteil:**

- Verlust oder Kompromittierung der Identity-Root kann nicht durch Federation-Messages
  behoben werden.
- Die betroffene Node wird für neue V1-Nachrichten fail-closed deaktiviert: kein Signieren,
  keine Admission und keine Status-Antworten; interne Audit-/Quarantine-Evidence bleibt.
- Root-Recovery oder Neu-Enrollment ist ein manueller, out-of-band Governance-Vorgang
  außerhalb von Federation Delegation V1.
- V1 definiert weder Quorum-Semantik noch automatische Node-ID-Übernahme, Root-Replacement
  oder Operator-Automatismus. Solche Regeln sind eine spätere Governance-Spec.
- Historische Registry-Provenance und Audit-State bleiben erhalten; eine externe Recovery
  darf sie nicht rückwirkend umschreiben.
- Der frühere Platzhalter Quorum-/Operator-Beleg ist damit als Nicht-Ziel/externe
  Abhängigkeit markiert.

Revocation-Felder: not_before, not_after, revoked_at,
revocation_effective_at, revocation_reason, rotation_kind. not_before ist der früheste,
not_after der späteste zulässige issued_at. revoked_at ist die Registry-Eintragungszeit;
revocation_effective_at der Zeitpunkt, ab dem neue Nachrichten abgelehnt werden.
revocation_reason ist rotation|compromise|lost|operator_action|other; rotation_kind ist
regular oder emergency_compromise. Bei regulärer Rotation bleiben vor effective_at gültige
historische Nachrichten prüfbar. Bei bekanntem compromise_time wird effective_at auf den
frühesten belegten Kompromiss gesetzt; bei unbekannter Kompromisszeit auf die früheste
Registry-/Operator-Beobachtung. Nachrichten im unbestimmten Intervall werden als
historical_uncertain quarantänisiert und sind nicht allein wegen issued_at < revoked_at
gültig. issued_at >= effective_at wird abgelehnt. Gelöschte Provenance ergibt unavailable,
nie verified; Retention reicht mindestens bis not_after plus Envelope-TTL, Clock-Skew und
Audit-Retention.

## 8. Envelope, Hash, Signatur und Verifikation

Top-Level-Keys sind exakt:
contract_version, message_id, request_message_id (bei initialem Request gleich
message_id), causation_message_id (bei initialem Request verboten), source_node_id,
target_node_id, operation, correlation_id, payload, issued_at, expires_at,
message_hash, signature, signer_key, key_id. Keine zusätzlichen Keys.

message_hash = lowercase_hex(SHA256(SFDJ-1(canonical_envelope_without_message_hash_and_signature))).
Der alte Name payload_hash ist V1-verboten. Signaturinput:
UTF8(STEWARD-FEDERATION-DELEGATION-V1\0) || raw_sha256_digest_bytes;
Signatur ist Ed25519 und RFC-4648 Standard-Base64 mit Padding; decodiert exakt 64 Bytes.
signer_key ist PublicKeyB64, also der aktivierte, Root-zertifizierte öffentliche Ed25519-
Key mit decodiert exakt 32 Bytes.

Fail-closed-Reihenfolge:

1. UTF-8/BOM/Duplicate-Key, Größen- und SFDJ-1-Prüfung.
2. geschlossene Schema- und Versionsprüfung.
3. Zeitfenster und Key-ID-Format.
4. Root-/Key-Provenance, Registry-Status und Node-ID.
5. Canonical Bytes und message_hash.
6. Domain-separated Ed25519-Signatur.
7. exaktes Target und Sender-Authority.
8. Request-/Receipt-Digest, Dedupe und Ledger.
9. Admission oder read-only Status-Handler.

Falsches Target sowie unauthentifizierte/ungültige Inputs erzeugen ausschließlich internes
Finding/Quarantine, keine automatische signierte Netzwerkantwort und kein Identity-/Routing-
Orakel. Ein korrekt authentifiziertes, korrekt adressiertes Target darf fachlich rejecten.

## 9. Receipt-Semantik, Partial Order und Replay

transport_committed beweist nur Transport-/Mailbox-Commit durch Relay/Hub. admission
beweist Target-Entscheidung, nicht Ausführung. started beweist Start nach durablem Work-
Handle, nicht Erfolg. terminal beweist ein Target-Ergebnis, nicht unabhängige Postcondition.
verification beweist nur die vom Origin ausgeführte unabhängige Verification.

Zulässiger Partial Order:

~~~text
SENT -> transport_committed (optional) -> admission(accepted) -> started -> terminal -> verification
SENT -> admission(rejected) [terminaler Seitenpfad]
admission(accepted) -> recovery_required (Seitenpfad; kein blindes Re-run)
~~~

terminal darf durch At-least-once-Reordering vor started eintreffen. Origin persistiert
dann out_of_order_pending und wendet nichts an, bis Target-Evidence/Status den Work-Handle
belegt; fehlende Zwischenstufe bleibt sichtbar, wird nicht erfunden. Widersprüchliche Stufen
sind ledger_conflict. admission=rejected darf nie Started/Terminal erzeugen.

Receipt-Transport-Retransmission: identische Bytes, message_id, receipt_id, Digest und
Signatur. Receipt-Application-Reissue: neue Envelope-message_id, Zeit, Hash und Signatur,
aber gleiche receipt_id, gleiche receipt_content_digest, gleicher Fachinhalt, gleicher
Request-Root; keine neue Stufe/Transition. Gleiche receipt_id mit anderem Fach-Digest ist
receipt_id_conflict. Jede neue Stufe erhält neue receipt_id. receipt_content_digest
hashiert nur den semantischen Receipt-Body.

## 10. Idempotenz, Recovery und getrennte Ledger

Transport ist at-least-once. Target-Ledger besitzt received, Admission, Request-Digest,
Idempotency-Key, target_work_id, Lease/Owner, Execution, RECOVERY_REQUIRED, Terminal-
Resultat und Konflikte. Origin-Ledger besitzt Request-Send, Transport-Evidence, alle
Receipts, Verification, Reissue und einmalige Anwendung auf origin_task_id.

Admission-/Dedupe-Commit erfolgt vor Side Effect. Identische Wiederholung liefert vorhandene
Evidence, aber keinen zweiten Work-Handle. Gleiche ID mit abweichendem Digest ist fail-closed.
Crash vor Admission darf denselben Request erneut anbieten. Crash nach Admission bewahrt
target_work_id. Crash während Execution führt zu Resume oder RECOVERY_REQUIRED; Lease-
Ablauf erlaubt keinen blinden Zweitstart. Crash nach Terminal wird am Origin genau einmal
angewendet. Partielle Tool-Ausführung verlangt Dedup-Key, Read-back oder Recovery-Entscheid;
Exactly-once wird nicht behauptet. RECOVERY_REQUIRED muss vor jeder fachlichen Reissue-
Entscheidung durch Statusabfrage/Evidence geklärt werden.

## 11. Capability-Wiring und Statusachsen

Ein maschinenlesbares Manifest führt je (operation, contract_version, repository,
direction, target) mindestens: Emitter, Target, Transport, Admission-Handler, Authority-
Gate, Fachhandler, Result-/Failure-Operation, Idempotenzspeicher, Receipt-Emitter,
E2E-Test und Produktionsbeleg. delegation_status_query und delegation_status sind
eigene Capabilities und müssen denselben Manifestregeln entsprechen.

Lifecycle maturity:
declared, partially_wired, code_complete, crucible_verified, production_proven.
Disposition:
active, unavailable, legacy, disabled.

Mindestkriterien: declared = Schema/Direction im Manifest; partially_wired = mindestens
ein fehlender Pfad; code_complete = alle Codepfade und Unit/Contract-Tests; crucible_verified
= adversarial repoübergreifender Crucible grün; production_proven = ausgerollter, beobachteter
Produktionsbeleg. Verboten sind declared|partially_wired|unavailable + active und
legacy + active in V1. active verlangt mindestens crucible_verified; Produktivstatus
verlangt zusätzlich production_proven. Das Wort implemented ist kein V1-Status.

## 12. ADR-Gate und Abhängigkeiten

Im engen Federation-Wire-Scope sind ADR-02, ADR-06, ADR-07, ADR-08 und ADR-09
ACCEPTED. ADR-01 bleibt für isolierte Wire-Semantik offen; ADR-04 blockiert erst einen
providerabhängigen Crucible. ADR-03 muss vor der Rückübersetzung eines verifizierten
Federation-Ergebnisses in ManagedTask.COMPLETED entschieden werden. ADR-05 ist vor
Produktions-Crucible, ADR-10 vor vollständiger Federation-V1-Integration zwingend.

**Readiness:** Draft 0.5 ist READY FOR GOLDEN FIXTURES. Das bedeutet nur, dass die
geschlossenen Wire-Schemas, SFDJ-1, IDs, Signaturen, Receipt- und Recovery-Regeln fixture-
fähig eingefroren sind. Es erlaubt noch keinen Produktcode, keine Handler, Ledger-, Workflow-
oder Context-Bridge-Änderung und keine Crucible-Ausführung. SFDJ-1 bleibt unverändert
eingefroren; nächste Arbeit ist ausschließlich Golden-Wire-Fixtures plus unabhängige
Steward-/Agent-City-Parser- und Signaturtests.
