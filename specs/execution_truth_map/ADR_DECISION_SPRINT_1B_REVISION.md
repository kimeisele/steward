# ADR DECISION SPRINT 1B — NORMATIVE REVISION

> Status: REVISION PROPOSED — Agent-B-Review erforderlich
> Datum: 2026-07-18
> Scope: Federation Delegation Contract V1; kein Produktcode

Dieses Dokument ergänzt und revidiert die Sprint-1-Entscheidungen. Draft 0.2 wird nicht als
Golden-Wire- oder Crucible-Basis verwendet. Die folgenden Regeln sind ein Draft-0.3-Vorschlag.

## 1. Gesamtstatus

| ADR | Sprint-1-Status | Sprint-1B-Status |
|---|---|---|
| ADR-02 | ACCEPTED | AMENDED — Transport-Replay und Application-Reissue getrennt |
| ADR-06 | ACCEPTED | OPEN / REVISION REQUIRED — Node-Key-Bindung, Rotation, Revocation und Domain Separation neu festzulegen |
| ADR-07 | ACCEPTED | AMENDED — Capability-Statusstufen erweitert |
| ADR-08 | ACCEPTED | AMENDED — request_digest, Reissue-Grenze und Statusabfrage ergänzt |
| ADR-09 | ACCEPTED | AMENDED — Partial Order, Kausalitäts-IDs und Receipt-Replay ergänzt |

## 2. ADR-02: Transport-Replay versus Application-Reissue

### Entscheidung

Transport-Retransmission und fachlicher Application-Retry sind verschiedene Vorgänge.

Transport-Retransmission:

- exakt dieselben kanonischen Bytes
- dieselbe message_id
- derselbe request_digest
- derselbe issued_at-Wert
- derselbe expires_at-Wert
- keine Änderung an Target, Authority, Payload oder Signatur
- zulässig nur, solange die Nachricht nicht abgelaufen ist
- darf keine neue Admission oder neue lokale Arbeit erzeugen

Application-Reissue:

- neuer Envelope
- neue message_id
- neuer issued_at-Wert
- neuer expires_at-Wert
- neue Signatur und neuer message_hash
- gleiche delegation_id
- gleicher request_digest
- gleiche semantische Payload
- kein neues target_work_id, wenn Target-Ledger bereits Admission, Execution oder Recovery kennt
- neues Target oder erweiterte Authority verboten

Vor Application-Reissue muss der Origin:

1. eine Statusabfrage an den bekannten target_node senden oder eine bereits gültige
   Status-/Receipt-Evidence auswerten;
2. feststellen, dass kein target_work_id und keine Admission bekannt sind;
3. entweder UNKNOWN oder delivery_expired_before_admission erhalten;
4. bei ACCEPTED, EXECUTING, RECOVERY_REQUIRED oder terminalem Zustand auf Reissue verzichten
   und den bestehenden Work-Lifecycle verfolgen.

Eine abgelaufene Transport-Message darf nicht mit identischen alten Bytes erneut als gültige
V1-Message gesendet werden. Sie darf nur als Transport-Retry innerhalb ihrer Gültigkeit
wiederholt werden. Nach Ablauf ist ein Application-Reissue mit neuer message_id erforderlich.

Für Statusabfragen werden zwei control-plane Operationen eingeführt:

- delegation_status_query: Origin → Target, keine Ausführung
- delegation_status: Target → Origin, Snapshot des Target-Ledgers

## 3. ADR-02: ID-Invarianten

Unverändert beziehungsweise bestätigt:

- delegation_id: Origin erzeugt vor erstem Send; genau eine pro Delegations-Lifecycle.
- correlation_id: exakt delegation_id.
- message_id: pro logischer Message; Transport-Retry behält sie; Application-Reissue erzeugt neue.
- origin_task_id: lokale Steward-Task-ID.
- target_work_id: nach durabler Admission höchstens einmal.
- receipt_id: fachliche Identität eines Receipt-Datensatzes.
- request_message_id: ursprüngliche delegate_task-Message.
- causation_message_id: unmittelbar auslösende Message des aktuellen Receipts/Resultats.
- idempotency_key: deterministisch aus request_digest abgeleitet.

subject_message_id wird in V1 nicht weiter verwendet. Es wird durch request_message_id und
causation_message_id ersetzt. Das verhindert, dass eine Receipt-Kette die einzige
Kausalitätsbeweiskette ist.

## 4. ADR-08: Semantischer Request-Digest

### Entscheidung

Jede delegate_task-Message trägt einen serverseitig prüfbaren request_digest. Ein frei
gewählter idempotency_key ist kein ausreichender Beweis.

Der Digest-Input ist exakt dieses JSON-Objekt:

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

Eingeschlossen:

- contract_version
- operation
- source_node_id
- target_node_id
- delegation_id
- origin_task_id
- capability
- intent
- task_description
- target_repo
- authority
- expected_outcome
- verification_contract
- deadline

Ausgeschlossen:

- task_title als reine Darstellung
- message_id
- request_message_id
- causation_message_id
- issued_at
- expires_at
- message_hash
- signature
- signer_key
- key_id
- request_digest selbst
- idempotency_key selbst

Die semantischen Felder werden nach den Draft-0.3-Canonical-Regeln serialisiert. Dann gilt:

~~~text
request_digest =
  lowercase_hex(SHA256(canonical_request_digest_input_utf8_bytes))

idempotency_key =
  "fedv1:" + request_digest
~~~

Der Target-Handler berechnet den Digest selbst und vergleicht beide Werte. Caller-
gelieferte Abweichungen werden fail-closed als request_digest_mismatch verworfen.

Gleiche delegation_id:

- gleicher request_digest: Duplicate/Replay nach ADR-08
- anderer request_digest: duplicate_conflict
- gleiche idempotency_key mit anderem Digest: idempotency_conflict
- gleiche semantische Payload mit neuer delegation_id: neue Delegation, kein Cross-Lifecycle-Dedup

deadline ist eingeschlossen und darf beim Application-Reissue nicht verlängert werden.
Authority und Target sind eingeschlossen und dürfen beim Retry nicht erweitert werden.

## 5. ADR-06: Stable Node-ID, Key-ID, Rotation und Revocation

### Entscheidungsvorschlag

Die Node-ID ist nicht mehr direkt an den aktuell verwendeten Signing-Key gebunden.

Node-ID:

~~~text
node_id =
  "ag_" + erste 32 lowercase Hex-Zeichen von
  SHA256(identity_root_public_key_hex_ascii)
~~~

Das ergibt 128 Bit Fingerprint-Material. Die Identity-Root ist eine registrierte, stabile
Node-Provenance. Die aktuelle Signatur erfolgt mit einem rotierbaren Signing-Key.

Key-ID:

~~~text
key_id =
  "key_" + vollständige 64 lowercase Hex-Zeichen von
  SHA256(signing_public_key_raw_bytes)
~~~

Der Envelope enthält signer_key und key_id. Die Registry bindet:

~~~text
(node_id, key_id, signer_key, not_before, not_after, status, provenance)
~~~

Key-Rotation:

- neuer signing_key und neue key_id
- node_id bleibt stabil
- alte und neue Keys dürfen in einem expliziten Überlappungsfenster verifiziert werden
- neue Messages werden nach dem Aktivierungszeitpunkt nur mit dem neuen Key signiert
- alte Messages bleiben prüfbar, wenn issued_at innerhalb der damaligen Gültigkeit lag und
  Retention/Evidence noch vorhanden ist
- key_id ist Teil des signierten Envelope-Bodys

Revocation:

- revoked Keys dürfen keine neuen Messages erzeugen
- eine bereits gültige Message wird nicht allein wegen späterer Revocation rückwirkend
  ungültig; ihre issued_at- und Registry-Provenance müssen nachweisbar bleiben
- bei kompromittiertem Key werden neue Messages sofort abgelehnt
- Registry-Status, Gültigkeitsfenster und Revocation-Evidence gehören in den Origin-/Target-
  Finding-Pfad
- unbekannte oder nicht registrierte key_id führt zu fail-closed Reject/Quarantine

Der bisherige 16-Hex-Digest aus dem aktuellen Code ist Legacy und nicht Draft-0.3-kompatibel.
Die direkte Ableitung der Node-ID aus jedem aktuellen Signing-Key ist ebenfalls Legacy.

Diese Entscheidung bleibt bis Agent-B-Review OPEN, weil Registry-Provenance und Rotation
sicherheitskritische Betriebsverträge sind.

## 6. ADR-06: Domain Separation

Draft 0.3 verwendet eine feste Protokolldomain:

~~~text
STEWARD-FEDERATION-DELEGATION-V1\0
~~~

Der kanonische Envelope-Hash wird als rohe 32-Byte-SHA-256-Ausgabe berechnet. Der Hash wird
als message_hash in lowercase Hex übertragen, aber nicht als ASCII-Hex signiert.

Signaturinput:

~~~text
signature_input =
  UTF8("STEWARD-FEDERATION-DELEGATION-V1\0")
  || raw_sha256_digest_bytes
~~~

Signatur:

~~~text
signature =
  RFC4648_STANDARD_BASE64_WITH_PADDING(
    Ed25519_sign(signing_private_key, signature_input)
  )
~~~

Damit ist die Signatur an Federation Delegation V1 gebunden und nicht in einem anderen
Protokollkontext wiederverwendbar. Die Domain ist Teil der normativen Signaturbytes.

## 7. Vollständige Canonical-Wire-Regeln

Draft 0.3 literal:

~~~text
federation-delegation-v1
~~~

Zeitformat:

- exakt UTC
- exakt RFC-3339-Profil YYYY-MM-DDTHH:MM:SSZ
- keine Fractional Seconds
- kein Offset außer Z
- keine Leap Seconds
- issued_at < expires_at
- maximale Envelope-Gültigkeit: 24 Stunden
- zulässige lokale Clock-Skew: höchstens 300 Sekunden

Unicode:

- Eingabestrings werden vor Schema-Validierung auf Unicode NFC normalisiert
- nicht auflösbare oder unpaired Unicode-Surrogates sind verboten
- ensure_ascii=false
- UTF-8-Ausgabe ohne BOM

JSON-Zahlen:

- nur JSON-Integer im Bereich -2^63 bis 2^63-1
- Floats sind im V1-Wire verboten
- exponentielle Zahlenschreibweise ist verboten
- NaN und Infinity sind verboten
- Zahlen werden nicht als String toleriert, wenn das Schema Integer verlangt

Objekte und Arrays:

- Duplicate JSON Keys sind Parse-Fehler
- sort_keys=true
- separators=(",", ":")
- unbekannte Top-Level-Felder sind verboten
- unbekannte Payload-Felder sind je contract_version verboten
- maximale Envelope-Größe: 256 KiB
- maximale Payload-Größe: 128 KiB
- maximale Objekt-/Array-Verschachtelung: 16 Ebenen
- maximale Array-Länge: 1024

Base64:

- RFC 4648 Standard Base64
- Padding "=" ist Pflicht, sofern nach RFC 4648 erforderlich
- URL-safe "-" und "_" sind verboten
- Whitespace ist verboten
- Signature muss decodiert exakt 64 Ed25519-Bytes ergeben

Envelope-Hash:

~~~text
message_hash =
  lowercase_hex(SHA256(canonical_envelope_without_message_hash_and_signature_utf8_bytes))
~~~

Die kanonischen Bytes enthalten signer_key, key_id, source_node_id, target_node_id,
message_id, correlation_id, request_message_id/causation_message_id sofern im jeweiligen
Schema vorhanden, operation, payload, issued_at und expires_at.

Der bisherige Name payload_hash wird in Draft 0.3 nicht mehr akzeptiert. Er ist Legacy.
message_hash ist der korrekte Name für den Hash des signierten Envelope-Body.

## 8. ADR-09: Receipt-Partial-Order

Receipt-Stufen bilden keine lineare Ankunftsreihenfolge. Sie bilden einen fachlichen
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

terminal kann beim Origin vor started eintreffen, wenn Transportzustellung reordert wurde.
Das ist kein fachlicher Widerspruch, solange der Target-Ledger belegt, dass die Arbeit
tatsächlich nach Admission gestartet wurde.

Regeln:

- Origin persistiert ein out_of_order_pending Receipt, statt es wegen Ankunftsreihenfolge
  zu verwerfen.
- Terminal darf vor Started angewendet werden, wenn request_message_id, causation_message_id,
  target_work_id, started_at und Target-Signatur gültig sind und der Target-Ledger den
  Start beweist.
- Ein fehlendes Started-Receipt darf nicht erfunden werden; der Origin markiert
  started_receipt_missing.
- Admission=rejected beendet den Delegationspfad; Started und Terminal sind unzulässig.
- transport_committed ist optional und darf nie als Admission interpretiert werden.
- Verification verlangt terminales Resultat oder explizit terminale Failure-Evidence.
- Widersprüchliche Zustände werden als ledger_conflict persistiert.
- Fehlende oder verspätete Stufen werden delivery_unknown, expired oder recovery_required,
  nie inferred success.

Zulässige Vorgänger:

| Receipt | Zulässiger fachlicher Vorgänger |
|---|---|
| transport_committed | SENT/outbox commit |
| admission accepted/rejected | SENT oder transport_committed |
| started | admission accepted |
| terminal | started im Target-Ledger; Receipt darf am Origin out-of-order eintreffen |
| verification | terminal oder terminale Failure-Evidence |

## 9. Kausalitäts-IDs

Draft 0.3 entfernt subject_message_id aus dem V1-Schema.

Jede Message besitzt abhängig von ihrer Operation:

- message_id: aktuelle Envelope-ID
- request_message_id: ursprüngliche delegate_task-Message-ID
- causation_message_id: unmittelbar auslösende Message-ID
- receipt_id: fachliche Receipt-ID, nur für Receipts/terminal Resultate

Regeln:

- Initialer delegate_task Request: request_message_id = message_id; causation_message_id
  ist verboten.
- Jede Receipt und jedes Resultat: request_message_id ist Pflicht und unverändert.
- Jede Receipt und jedes Resultat besitzt causation_message_id.
- transport_committed.causation_message_id referenziert die Request-Message.
- admission.causation_message_id referenziert die Request-Message.
- started.causation_message_id referenziert die Admission-Receipt-Message.
- terminal.causation_message_id referenziert die Started-Receipt-Message oder den
  Target-Work-Event, sofern der Target-Ledger diesen Event signiert.
- verification.causation_message_id referenziert das terminale Resultat.
- subject_message_id ist in federation-delegation-v1 unbekannt und wird abgelehnt.

Die ursprüngliche Request-ID bleibt damit direkt erreichbar, ohne eine lückenlose Receipt-
Kette vorauszusetzen.

## 10. Receipt-Replay

Ein bereits ausgestelltes Receipt wird bei Transport-Replay exakt wieder ausgesendet:

- identische kanonische Bytes
- gleiche message_id
- gleiche receipt_id
- gleicher request_message_id
- gleicher causation_message_id
- gleiche issued_at/ expires_at
- gleiche Signatur

Eine neue Receipt-Stufe oder ein veränderter Status ist kein Replay. Sie erhält:

- neue message_id
- neue receipt_id
- neue causation_message_id
- denselben request_message_id
- neue Signatur
- neue issued_at/ expires_at innerhalb der Delegationsgrenze

Duplicate-Prüfung:

- gleiche message_id + gleicher message_hash: Replay/No-op
- gleiche message_id + anderer message_hash: message_id_conflict
- gleiche receipt_id + identischer Receipt-Body: Replay/No-op
- gleiche receipt_id + anderer Status/Stufe/Body: receipt_id_conflict
- unterschiedliche receipt_id bei gleicher Stufe: nur zulässig, wenn fachlich neue Receipt-
  Evidence existiert; sonst duplicate_conflict

## 11. Authentifizierte versus unauthentifizierte Fehler

Vor erfolgreicher Authentifizierung darf kein externer signierter Reject erzwungen werden.

Unauthentifizierte oder nicht verifizierbare Eingänge:

- interne Quarantine/Finding
- Rate-Limit und Amplification-Schutz
- keine automatische signierte Netzwerkantwort
- keine Preisgabe, ob Target, Capability oder Authority existieren
- keine Änderung am Target- oder Origin-Ledger außer Quarantine-Evidence

Authentifizierte Eingänge mit gültiger Signatur, gültiger Registry-Provenance und korrektem
Target dürfen ein signiertes Reject-Receipt erhalten, zum Beispiel:

- unsupported_contract
- wrong_target
- authority_denied
- capability_unavailable
- request_digest_mismatch
- duplicate_conflict
- expired

Ein gültiger Sender mit falschem Target erhält nicht zwingend eine externe Antwort, wenn die
lokale Policy das als Routing-/Privacy-Fall behandelt. Ein Relay darf ausschließlich
transport_committed ausstellen.

## 12. Getrennte Ledger und Zustandsbesitzer

### Target-Ledger

Besitzt ausschließlich:

- received
- admitted oder rejected
- request_digest
- target_work_id
- lease/owner
- executing
- recovery_required
- terminal result
- target-side Receipt-Evidence
- message-/receipt-conflicts

### Origin-Ledger

Besitzt ausschließlich:

- request created/sent
- request_message_id
- transport evidence
- admission Receipt
- started Receipt
- terminal Receipt/Result
- verification
- einmalige Anwendung auf origin_task_id
- Origin-side conflicts und Findings

Synchronisationsregeln:

1. Target-Ledger ist Autorität für lokale Annahme, Work, Lease und Terminal-Resultat.
2. Origin-Ledger ist Autorität für Send, Korrelation, Verification und Origin-Task-Anwendung.
3. Origin darf Target-Zustände nicht erfinden.
4. Target darf Origin-Verification nicht ausstellen.
5. Statusabfrage liest den Target-Ledger und erzeugt einen signierten Snapshot.
6. Widersprüchliche Snapshots werden auf beiden Seiten als ledger_conflict markiert.
7. Ein Ledger-Commit ist vor dem jeweils behaupteten Receipt-Zustand erforderlich.

## 13. ADR-07: Capability-Statusmodell

implemented ist kein gültiger Draft-0.3-Status mehr.

Normative Statusstufen:

- declared: Operation ist bekannt, aber keine Vollständigkeit behauptet.
- partially_wired: mindestens eine Kante vorhanden, mindestens eine Pflichtkante fehlt.
- code_complete: Emitter, Transport, Target, Handler, Authority, Ledger, Resultat und
  Receipt-Code existieren; kein Crucible-/Produktionsnachweis.
- crucible_verified: positiver und adversarialer repoübergreifender Crucible grün.
- production_proven: Crucible plus reproduzierbarer Produktionsbeleg über den aktuellen
  Rollout-/Runtime-Pfad.
- unavailable: geforderte Richtung besitzt keinen Handler-/Resultatpfad.
- legacy: historischer oder separat versionierter Pfad.

Mindestkriterien:

- code_complete darf nicht als production_proven erscheinen.
- crucible_verified verlangt reale Wire-Bytes und echte Ingress-/Resultatpfade.
- production_proven verlangt mindestens einen nachvollziehbaren Runtime-Beleg nach Rollout.
- fehlender Receipt-, Recovery- oder Authority-Pfad verhindert code_complete.
- Statusänderungen sind versioniert und dürfen nicht aus ALL_OPERATIONS allein abgeleitet werden.

## 14. Offene Abhängigkeiten

- ADR-01 bleibt für isolierte Federation-Wire-Semantik offen zulässig.
- ADR-04 bleibt offen, solange kein providerabhängiger V1-Crucible-Handler verwendet wird.
- ADR-03 muss vor Mapping auf Managed-Task-COMPLETED entschieden sein.
- ADR-05 ist vor Produktions-Crucible zwingend.
- ADR-10 ist vor vollständiger Federation-V1-Integration zwingend.
- ADR-06 bleibt bis Agent-B-Review von Node-ID, key_id, Rotation, Revocation und Domain
  Separation OPEN.

## 15. Sprint-1B-Entscheidung

Draft 0.2 ist nicht bereit für Golden-Wire-Fixtures oder Crucible-Design.

Draft 0.3 darf erst nach Agent-B-Abnahme dieser Revision als Basis für Golden Fixtures
verwendet werden. Bis dahin:

- kein Produktcode
- kein Fixture-Freeze
- kein Crucible-Implementierungsdesign
- kein Merge
- Phase 1 unverändert
- Context Bridge unverändert/geparkt
