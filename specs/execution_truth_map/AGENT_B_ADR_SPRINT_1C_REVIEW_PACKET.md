# ADR DECISION SPRINT 1C — NORMATIVE REVISION

> Status: REVISION PROPOSED — Agent-B-Review erforderlich
> Datum: 2026-07-18
> Scope: Federation Delegation Contract V1; kein Produktcode

Sprint 1C schließt die engen Draft-0.3-Lücken. Draft 0.4 darf erst nach Agent-B-Abnahme als
Golden-Wire-Basis gelten.

## 1. Gesamtstatus

| ADR | Sprint-1B | Sprint-1C |
|---|---|---|
| ADR-02 | AMENDED | AMENDED — Reissue-Root und Receipt-Reissue explizit |
| ADR-06 | OPEN / REVISION REQUIRED | OPEN / REVISION REQUIRED — Root-Identity- und Revocation-Vertrag ergänzt |
| ADR-07 | AMENDED | AMENDED — Lifecycle-Maturity und Disposition getrennt; Status-Query verkabelt |
| ADR-08 | AMENDED | AMENDED — Query/Reissue/Digest-Regeln ergänzt |
| ADR-09 | AMENDED | AMENDED — Receipt-Retransmission und Receipt-Reissue ergänzt |

## 2. Wrong-Target-Regel

Ein Message mit target_node_id ungleich der lokalen Node-ID erzeugt:

- kein externes Reject-Receipt
- keine signierte Netzwerkantwort
- kein Routing-/Identity-Orakel
- nur internes, rate-limitiertes Finding/Quarantine
- keine Mutation von Target- oder Origin-Ledger

Das gilt auch bei gültiger Signatur und gültiger Registry-Provenance. Der Empfänger darf
nicht bestätigen, dass die Node-ID existiert, ob Capability/Authority gültig wäre oder welche
andere Route zuständig ist.

Ein signiertes Reject-Receipt ist nur zulässig, wenn:

1. Signatur und Key-Provenance gültig sind,
2. die Message an diese Node adressiert ist,
3. der Sender als zulässiger Origin/Relay authentifiziert ist,
4. der Fehler semantisch nach der Authentifizierung erkannt wurde.

Beispiele für authentifizierte Rejects am korrekten Target:

- unsupported_contract
- authority_denied
- capability_unavailable
- request_digest_mismatch
- duplicate_conflict
- idempotency_conflict
- expired

wrong_target bleibt ein internes Finding und ist kein externer Fehler-Opcode.

## 3. Root-Identity-Vertrag

### Root-Key-Erzeugung und Besitz

- Jeder Node besitzt genau eine registrierte Identity-Root pro Node-ID-Epoch.
- Der Root-Ed25519-Key wird beim Bootstrap in einem Offline-/HSM- oder gleichwertig
  geschützten Prozess erzeugt.
- Der Root-Private-Key wird niemals in Federation-Envelopes oder Runtime-Transporten
  übertragen.
- Der Node-Betreiber bewahrt Root-Private-Key und verschlüsselte Recovery-Kopie getrennt
  von rotierenden Signing-Keys auf.
- Runtime-Worker erhalten nur die aktuell aktivierten Signing-Keys.

### Root-Provenance

Die Registry akzeptiert eine Node nur mit einem signierten Enrollment-Record:

~~~text
node_enrollment_body =
(node_id, identity_root_public_key, registry_epoch, not_before, provenance_metadata)
~~~

Der Enrollment-Record enthält:

- node_id
- identity_root_public_key
- registry_epoch
- not_before
- provenance metadata
- root_enrollment_signature

Die Root-Signatur nutzt eine eigene Domain:

~~~text
STEWARD-FEDERATION-ROOT-ENROLLMENT-V1\0
~~~

Die Registry prüft:

1. Node-ID-Ableitung aus identity_root_public_key.
2. Root-Signatur über den Enrollment-Body.
3. registry_epoch und konkurrierende Einträge.
4. keine vorhandene andere Root für dieselbe Node-ID.

### Autorisierung eines Signing-Keys

Ein rotierender Signing-Key benötigt ein Root-signiertes Key-Certificate:

~~~text
signing_key_certificate_body =
(node_id, key_id, signer_key, not_before, not_after,
 rotation_kind, certificate_epoch)
~~~

Die Root-Signatur verwendet:

~~~text
STEWARD-FEDERATION-SIGNING-KEY-AUTH-V1\0
~~~

Ein Key-Certificate ist nur gültig, wenn:

- node_id zur Identity-Root passt,
- key_id aus signer_key berechnet wird,
- not_before < not_after,
- Certificate-Epoch nicht rückwärts läuft,
- Root-Signatur korrekt ist,
- Registry den Certificate-Status aktiviert hat.

Eine Registry-Zeile ohne Root-Signatur ist keine ausreichende Key-Bindung.

### Registrierung und Aktivierung

- Certificate wird zuerst als pending registriert.
- Erst ein signierter Registry-Aktivierungsrecord macht key_id aktiv.
- Aktivierung enthält activation_epoch und activation_at.
- Signing vor activation_at ist verboten.
- Der Target prüft Certificate, Registry-Status und Zeitfenster vor der Signaturprüfung der
  Fachoperation.

### Root-Aufbewahrung und Root-Rotation

- Root-Provenance wird mindestens solange aufbewahrt, wie irgendeine darauf basierende
  Message/Evidence verifiziert werden muss.
- Root-Rotation erfordert eine alte Root-Signatur über die neue Root und eine neue Root-
  Signatur über den Übergang.
- Der Übergang enthält successor_root, effective_at, reason und transition_epoch.
- Bei verlorener oder kompromittierter Root ist eine Registry-Governance-Recovery mit
  explizitem Quorum-/Operator-Beleg erforderlich; ein Runtime-Worker darf Root-Provenance
  nicht selbst überschreiben.

### Node-ID-Kollision und konkurrierende Registrierung

- Gleiche node_id mit anderer identity_root_public_key ist node_id_collision.
- Eine solche Registrierung wird abgelehnt und intern quarantänisiert.
- Kein automatisches Umbenennen, kein stilles Überschreiben.
- Identisches Enrollment derselben Root ist idempotent.
- Konkurrierende gültige Enrollments derselben Node-ID werden durch registry_epoch und
  Governance-Evidence entschieden; bis dahin ist die Node nicht für neue Messages aktiv.
- Eine Kollision ist niemals durch kürzere Fingerprints zu lösen.

## 4. Revocation-Zeitmodell

Jedes Key-Certificate führt exakt:

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
- revoked_at: Zeitpunkt, zu dem die Registry die Revocation registriert.
- revocation_effective_at: Zeitpunkt, ab dem neue Messages mit dem Key abgelehnt werden.
- revocation_reason: rotation, compromise, lost, operator_action oder other.
- rotation_kind: regular oder emergency_compromise.

Reguläre Rotation:

- revocation_effective_at ist der geplante Übergangszeitpunkt.
- Messages mit issued_at < revocation_effective_at bleiben bei gültiger Provenance prüfbar.
- Nach diesem Zeitpunkt signierte neue Messages mit dem alten Key werden abgelehnt.

Kompromittierung:

- Bei bekanntem compromise_time wird revocation_effective_at auf den frühesten belastbar
  belegten Kompromittierungszeitpunkt gesetzt.
- Bei unbekanntem compromise_time wird revocation_effective_at auf die früheste
  Registry-/Operator-Beobachtung gesetzt.
- Messages im Intervall zwischen unbekanntem Kompromiss und Beobachtung sind
  historical_uncertain und dürfen nicht allein wegen issued_at < revoked_at als gültig
  akzeptiert werden.
- Sie benötigen zusätzliche unabhängige Evidence oder bleiben quarantänisiert.
- Messages mit issued_at >= revocation_effective_at werden abgelehnt.
- Bei emergency_compromise darf keine automatische historische Success-/Verification-
  Entscheidung aus der alten Signatur allein abgeleitet werden.

Historische Nachrichten:

Eine historische Message ist nur dann verifizierbar, wenn:

1. Root-Enrollment und Key-Certificate-Provenance erhalten sind,
2. issued_at innerhalb not_before/not_after liegt,
3. Signatur, message_hash und Domain korrekt sind,
4. keine compromise-Evidence ihr Zeitfenster als historical_uncertain markiert,
5. Registry-Retention die Prüfung noch ermöglicht.

Retention:

- Root- und Key-Provenance wird mindestens bis nach not_after plus maximaler Envelope-
  Gültigkeit, Clock-Skew und der konfigurierten Audit-Retention aufbewahrt.
- Wird Provenance gelöscht, lautet das Ergebnis unavailable, nie verified.
- Registry-Deletion ist kein impliziter Widerruf und kein Erfolg.

## 5. Sprachneutrales Canonical-JSON-Profil SFDJ-1

Draft 0.4 bindet nicht an Python-Parameter, sondern an das normative Profil
Steward Federation Delegation JSON Canonicalization Profile 1 (SFDJ-1).

### Parse und Unicode

1. Eingabe ist UTF-8 ohne BOM.
2. JSON wird mit Duplicate-Key-Erkennung geparst.
3. Object member names und Stringwerte müssen bereits NFC sein.
4. Nicht-NFC-Eingaben werden abgelehnt, nicht normalisiert.
5. Unpaired Surrogates sind verboten.
6. Die NFC-Prüfung wird rekursiv auf alle Schlüssel und Stringwerte angewandt.

### Sortierung und Escape

- Object member names werden nach lexikographischer Reihenfolge ihrer NFC-normalisierten
  UTF-8-Bytefolgen sortiert.
- Arrays behalten ihre Reihenfolge.
- Keine Whitespace-Bytes außerhalb von Stringwerten.
- Slash / wird nicht escaped.
- Backslash und Quote werden mit den Standard-JSON-Escapes escaped.
- U+0000 bis U+001F werden mit lowercase vierstelliger \u00xx-Notation escaped.
- Andere Unicode-Codepoints werden als UTF-8 ausgegeben; ASCII-Escaping ist verboten.
- Bool und null behalten ihre JSON-Literale true, false und null.

### Zahlen

- Nur Integer im Bereich -2^63 bis 2^63-1.
- Keine Floats.
- Keine Exponentenschreibweise.
- Kein führendes Plus.
- Keine führenden Nullen außer dem Literal 0.
- -0 ist verboten.
- NaN und Infinity sind verboten.

### Ausgabe und Kanonizitätsprüfung

- JSON-Ausgabe ohne Whitespace.
- Object keys sortiert nach SFDJ-1.
- Eingehende unsigned canonical bytes müssen bytegleich mit der SFDJ-1-Rekonstruktion sein.
- Eine semantisch gleiche, aber byteverschiedene Darstellung wird rejected_noncanonical.
- Der vollständige eingehende Envelope muss ebenfalls bytegleich seiner SFDJ-1-Darstellung
  sein; Top-Level-Key-Reordering ist nicht zulässig.
- Ein Empfänger signiert oder hasht niemals eine still normalisierte Eingabe.

### Größenlimits

- Envelope maximal 256 KiB.
- Payload maximal 128 KiB.
- Verschachtelung maximal 16 Ebenen.
- Arrays maximal 1024 Elemente.
- Object member names maximal 256 UTF-8 Bytes.
- Einzelne Stringwerte maximal 64 KiB.

### Base64 und Version

- contract_version exakt federation-delegation-v1.
- Base64 ist RFC 4648 Standard Base64.
- Padding ist Pflicht, sofern erforderlich.
- URL-safe - und _ sind verboten.
- Whitespace ist verboten.
- Ed25519-Signatur decodiert exakt zu 64 Bytes.

## 6. Receipt-Retransmission und Receipt-Reissue

### Receipt-Transport-Retransmission

- identische kanonische Bytes
- gleiche message_id
- gleiche receipt_id
- gleicher receipt_content_digest
- gleiche request_message_id
- gleiche causation_message_id
- gleiche issued_at/expires_at
- gleiche Signatur
- nur vor expires_at

### Receipt-Application-Reissue

Ein reissue ist keine neue Stufe und kein neuer Ledger-Übergang:

- neue message_id
- neue issued_at/expires_at
- neuer message_hash
- neue Signatur
- gleiche receipt_id
- gleicher receipt_content_digest
- gleicher fachlicher Receipt-Inhalt
- gleicher request_message_id
- causation_message_id verweist auf die aktuelle Status-/Recovery-Entscheidung

Receipt-Inhalt:

~~~json
{
  "receipt_id": "...",
  "receipt_stage": "...",
  "delegation_id": "...",
  "request_message_id": "...",
  "target_work_id": "...",
  "status": "...",
  "evidence_refs": []
}
~~~

receipt_content_digest ist:

~~~text
lowercase_hex(SHA256(SFDJ-1(canonical_receipt_content)))
~~~

Ausgeschlossen aus receipt_content_digest sind message_id, causation_message_id, issued_at,
expires_at, message_hash, signature, signer_key und key_id.

Konflikte:

- gleiche receipt_id + gleicher receipt_content_digest: Replay/Reissue erlaubt.
- gleiche receipt_id + anderer receipt_content_digest: receipt_id_conflict.
- neue Receipt-Stufe: neue receipt_id, neue message_id, neuer fachlicher Ledger-Übergang.
- Receipt-Reissue darf keine Stufe erhöhen oder Ledger-Transition auslösen.

## 7. Request-Root und Kausalität

- request_message_id verweist während des gesamten Lifecycles auf die allererste
  delegate_task-Message.
- Application-Reissue erhält neue message_id, aber keinen neuen Request-Root.
- causation_message_id verweist auf die unmittelbar auslösende Statusantwort,
  Receipt-Reissue-Anforderung oder Recovery-Entscheidung.
- Jede Receipt- und Result-Message ist direkt zum ersten Request zurückführbar.
- subject_message_id ist im V1-Schema verboten.

Initialer Request:

- request_message_id = message_id
- causation_message_id fehlt

Jede Antwort/Receipt:

- request_message_id ist Pflicht und unverändert.
- causation_message_id ist Pflicht.
- message_id identifiziert den aktuellen Envelope.
- receipt_id identifiziert den Receipt-Datensatz.

## 8. Status-Query-Capability

### delegation_status_query

Envelope:

- operation = delegation_status_query
- source_node_id = registrierter Origin
- target_node_id = exakt der Zielknoten der Delegation
- request_message_id = ursprüngliche Request-Message
- causation_message_id fehlt bei der ersten Query
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

Regeln:

- Nur der registrierte Origin oder eine ausdrücklich autorisierte Relay-Identity darf fragen.
- Query hat keinen Side Effect im Target-Ledger.
- Target-Targeting muss exakt stimmen.
- Query darf nur Informationen dieser delegation_id liefern.
- Rate-Limit pro source_node_id und delegation_id.
- Replay derselben Query-Message ist identisch.
- Neue Query-Message darf neuen Snapshot anfordern, erzeugt aber keine Arbeit.
- Falsche oder unauthentifizierte Query: internes Finding/Quarantine; keine automatische
  signierte Antwort.
- UNKNOWN darf signiert zurückgegeben werden, wenn Sender authentifiziert, korrekt adressiert
  und für die Delegation autorisiert ist.

### delegation_status

Envelope:

- operation = delegation_status
- source_node_id = target_node_id der Delegation
- target_node_id = registrierter Origin
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

snapshot_version ist monoton pro delegation_id im Target-Ledger. Ein UNKNOWN-Snapshot legt
keinen Admission-Eintrag an. Statusantworten werden nach denselben Replay-, Hash-, Signatur-
und Receipt-Regeln behandelt. Eine Statusantwort ist kein Receipt und keine Verification.

ADR-07-Wiring für Status Query:

- emitter: Origin status client
- direction: Origin → exact Target
- target matcher: Zielknoten der ursprünglichen Delegation
- authority: read_status only
- handler: Target status-query handler
- state owner: Target-Ledger read-only
- result: delegation_status
- receipt: keine Arbeits-Receipt; Status-Evidence im Origin-Ledger
- idempotency: message_id replay; keine Side Effect-Deduplizierung erforderlich
- tests: positive, wrong-target, unauthorized, UNKNOWN, replay, rate-limit, stale snapshot,
  changed request_digest, crash during query
- production evidence: signierter Snapshot und korrelierter Origin-Ledger-Eintrag

## 9. Wrong-Target und Auth-Failure

Wrong target:

- internes Finding/Quarantine
- keine externe signierte Antwort
- keine Information, ob Node, Capability oder Sender existieren
- keine Ledger-Transition
- Rate-Limit/Amplification-Schutz

Authentifizierter, korrekt adressierter Request mit fachlichem Fehler:

- signiertes Reject-Receipt möglich
- nur nach gültiger Signature, Root-/Key-Provenance, korrektem Target und Sender-Authority

Relay darf nur transport_committed ausstellen.

## 10. Getrennte Ledger

Target-Ledger:

- received
- admitted/rejected
- request_digest
- target_work_id
- lease/owner
- executing
- recovery_required
- terminal result
- target receipts
- message/receipt conflicts
- status snapshot version

Origin-Ledger:

- request created/sent
- request_message_id
- transport evidence
- admission/start/terminal receipts
- verification
- once-only application auf origin_task_id
- application reissue history
- origin conflicts/findings

Synchronisation:

1. Target-Ledger autorisiert lokale Arbeit und Terminalresultat.
2. Origin-Ledger autorisiert Verification und Managed-Task-Anwendung.
3. Origin darf Target-Zustände nicht erfinden.
4. Target darf Origin-Verification nicht ausstellen.
5. delegation_status liest Target-Ledger und ist signierte Evidence.
6. Divergierende Snapshots werden auf beiden Seiten ledger_conflict.
7. Kein Receipt ohne vorherigen Ledger-Commit.

## 11. Capability-Status: zwei Achsen

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

Manifest-Schlüssel ist mindestens:

~~~text
(operation, contract_version, repository, direction, target)
~~~

Mindestkriterien:

- declared: bekannt/deklariert; keine Code-Vollständigkeit behauptet.
- partially_wired: einzelne Kanten, mindestens eine Pflichtkante fehlt.
- code_complete: Emitter, Transport, Target, Authority, Handler, Ledger, Recovery,
  Resultat und Receipt-Code vorhanden.
- crucible_verified: reale Bytes, positiver und adversarialer Cross-Repo-Crucible grün.
- production_proven: Crucible plus reproduzierbarer Produktionsbeleg über den aktuellen
  Runtime-/Rollout-Pfad.

Verbotene Kombinationen:

- declared + active verboten.
- partially_wired + active verboten.
- unavailable + active verboten.
- active im Produktionsprofil verlangt production_proven.
- crucible_verified + active ist nur in nicht-produktivem Testprofil zulässig.
- legacy + active im federation-delegation-v1-Profil verboten.
- disabled mit jeder Lifecycle-Stufe zulässig.
- production_proven + disabled zulässig, wenn der Pfad bewusst abgeschaltet wurde.
- Eine globale Capability-Statusangabe darf repo-/richtungsbezogene Status nicht ersetzen.

implemented ist kein Draft-0.4-Status.

## 12. Offene ADR-Abhängigkeiten

- ADR-01 bleibt für isolierte Federation-Wire-Semantik offen.
- ADR-03 muss vor Mapping eines verifizierten Federation-Resultats auf Managed-Task-COMPLETED
  entschieden werden.
- ADR-04 bleibt offen, solange kein providerabhängiger V1-Crucible-Handler verwendet wird.
- ADR-05 bleibt Produktions-/Crucible-Blocker.
- ADR-10 bleibt Integrationsblocker.
- ADR-06 bleibt bis Agent-B-Abnahme von Root-Identity, Revocation und SFDJ-1 OPEN.

## 13. Draft-0.4-Gate

READY FOR GOLDEN FIXTURES nur wenn:

1. Root-Identity- und Key-Certificate-Vertrag akzeptiert.
2. Revocation-Zeitmodell akzeptiert.
3. SFDJ-1 sprachneutral akzeptiert.
4. Request-/Receipt-Reissue akzeptiert.
5. Request-Root und Kausalitätsregeln akzeptiert.
6. Status Query vollständig spezifiziert und im Wiring-Manifest enthalten.
7. Wrong-Target und Auth-Failure widerspruchsfrei.
8. Zweiachsiges Capability-Statusmodell akzeptiert.
9. Payload-Subschemas für erste Fixtures eingefroren.

Bis dahin:

- kein Produktcode
- keine Fixtures
- kein Crucible-Design
- kein Merge
- Phase 1 read-only
- Context Bridge geparkt

## 14. Agent-B-Reviewauftrag

Bitte beantworten:

1. Ist die Wrong-Target-Regel ohne Routing-/Identity-Orakel eindeutig?
2. Ist Root-Key-Erzeugung, Root-Provenance, Signing-Key-Autorisierung, Rotation und
   Root-Recovery vollständig?
3. Ist das Revocation-Zeitmodell inklusive unbekanntem compromise_time und historischer
   Message-Gültigkeit sicher?
4. Ist SFDJ-1 sprachneutral und bytegenau genug für Golden Fixtures?
5. Ist Receipt-Retransmission versus Receipt-Reissue eindeutig und konfliktfest?
6. Bleibt request_message_id bei jedem Reissue korrekt auf dem ersten Request?
7. Sind delegation_status_query und delegation_status vollständig und gemäß ADR-07 verkabelt?
8. Sind Rate-Limit, Privacy und UNKNOWN-Verhalten der Status Query ausreichend?
9. Sind Lifecycle-Maturity und Disposition ohne verbotene Kombinationen modelliert?
10. Ist Draft 0.4 nach diesen Regeln READY FOR GOLDEN FIXTURES?

Vorläufig:

~~~text
ADR-02: AMENDED / REVIEW REQUIRED
ADR-06: OPEN / REVISION REQUIRED
ADR-07: AMENDED / REVIEW REQUIRED
ADR-08: AMENDED / REVIEW REQUIRED
ADR-09: AMENDED / REVIEW REQUIRED
Draft 0.4: NOT READY UNTIL AGENT-B ACCEPTANCE
Produktcode: unverändert
Phase 1: unverändert/read-only
Context Bridge: unverändert/geparkt
~~~
