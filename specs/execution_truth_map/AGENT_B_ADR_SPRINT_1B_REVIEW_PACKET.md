# AGENT B REVIEW PACKET — ADR DECISION SPRINT 1B

> Status: REVISION REQUIRED — Draft 0.3 ist noch nicht bereit für Golden-Wire-Fixtures oder Crucible-Design
> Datum: 2026-07-18
> Repository: kimeisele/steward
> Scope: Federation Delegation Contract V1; kein Produktcode

Dieses Dokument ist eine vollständig eigenständige Review-Unterlage. Es enthält die
Evidenzbasis, die revidierten Entscheidungen, Wire-Regeln, Receipt-/Recovery-Semantik,
Statusmodell, offene Abhängigkeiten und den Review-Auftrag. Keine weitere Datei ist für die
technische Beurteilung erforderlich.

---

## 1. Arbeits- und Evidenzbasis

Branch und Commit:

- Branch: adr/federation-delegation-sprint-1
- Vorheriger Draft-0.2-Commit: 7a6480a645
- Sprint-1B-Revision: dieses Packet plus Draft-0.3-Dokument
- Branch-Basis: origin/main 110b933231ebdcd3fc43c04ee30afe5df88be513
- Kein Produktcode, kein Merge und keine Aktivierung

Die Recon-Historie wurde ohne Heartbeat-/Federation-Sync-Rauschen geprüft:

~~~text
git log --extended-regexp --invert-grep \
  --grep='(^|[^[:alpha:]])heartbeat([^[:alpha:]]|$)|steward: federation sync'
~~~

Live-Pins:

| Repository | Head | Tree |
|---|---|---|
| Steward | 24f86ec0749a1eff919921a947189ee5c459a4c8 | 42abf088363f99f8eed32ca7b8c663cb6487a202 |
| Agent City | e798bdbf7b3969beea577fe265657bbb7c142115 | 496a321f6b426122892cbbbeaa1e20e5f002167c |
| Steward Protocol | 34a8a0efc25c15ef7c07dd4fb50aeb2510c071e8 | 48897cf33b748855a3d84538357108083bb70d5c |

Relevante Tests und Runtime-Belege:

- Steward-Fokuslauf: 349 passed.
- Aktueller Health-Smoke-Test: 17 passed.
- Agent-City Federation-/PR-Fokuslauf: 88 passed, 4 failed.
- Vier Agent-City-E2E-Fehler: PR_VERDICT: Signature verification FAILED.
- Agent-City-Run 29644618328: GH006 beim Protected-Branch-Push, Workflow dennoch success.
- Ursache im Workflow: .github/workflows/agent-city-heartbeat.yml:127 enthält git push || true.
- Steward-Heartbeat 29645810216: drei von drei Providern nutzbar, keine Collapse-/Decode-Flags.

Unverändert:

- docs/PHASE1_BEFUND_steward.md
- Context Bridge, PR #728, E1, D2b, G1, Publisher, Delivery und Aktivierung
- Steward-, Agent-City- und Steward-Protocol-Produktcode
- Workflows, Secrets, Runtime-Konfiguration und Produktionszustand

---

## 2. Agent-B-Befund zu Draft 0.2

Agent B hat die Grundrichtung bestätigt, aber Draft 0.2 wegen folgender Lücken als
REVISION REQUIRED bewertet:

1. Transport-Replay und Application-Retry waren vermischt.
2. idempotency_key war nicht kryptografisch an die semantische Payload gebunden.
3. Node-ID enthielt nur 64 Bit und war direkt an einen Signing-Key gekoppelt.
4. Domain Separation fehlte.
5. Canonical JSON war bei Zeit, Unicode, Zahlen, Base64, Limits und Versionsliteral unvollständig.
6. payload_hash war semantisch falsch benannt, weil fast der gesamte Envelope gehasht wird.
7. Receipt-Stufen bildeten fälschlich eine lineare Reihenfolge.
8. subject_message_id war als alleinige Kausalitätsreferenz zu schwach.
9. Receipt-Replay war nicht zwischen identischen und neuen Envelopes unterschieden.
10. Unauthentifizierte Fehler konnten zu externen Reject-/Amplification-Pfaden führen.
11. Target- und Origin-Ledger waren nicht sauber getrennt.
12. implemented vermischte Code-Vollständigkeit mit Crucible- und Produktionsbeweis.

Folgerung: Draft 0.2 wird weder als Golden-Wire-Basis noch als Crucible-Basis verwendet.

---

## 3. Relevante IST-Risse

- steward/federation.py:FederationBridge.flush_outbound setzt correlation_id="".
- steward/tools/delegate.py:DelegateTool.execute überträgt target_agent, aber keine
  Ursprungstask-ID oder belastbare Korrelation.
- FederationBridge.flush_outbound sendet an alive/suspect Peers statt exakt an target_agent.
- FederationBridge._handle_task_callback korreliert über delegated:{task_title} als Substring.
- city/federation_nadi.py:FederationNadi.receive dedupliziert in-memory über source:timestamp.
- steward/federation_relay.py:DeliveryReceipt bestätigt Peer-Aktivität heuristisch für ganze
  Batches und ist in-memory.
- steward/federation_crypto.py:canonical_message_hash nutzt legacy Scope, default=str und
  optionale Hub-Ausnahme.
- steward/federation.py:FederationBridge._sign_message_dict schließt signer_key aus und
  signiert ohne Draft-0.3-Domain Separation.
- city/hooks/dharma/pr_verdict.py verlangt signer_key und verifiziert einen inkompatiblen
  inneren Payload-Scope.
- steward/federation.py:ALL_OPERATIONS deklariert 24 Operationen; Richtung, Handler,
  Resultatpfad und Tests sind nicht vollständig verdrahtet.
- Agent City besitzt am Live-Pin keinen delegate_task-/OP_DELEGATE_TASK-Fachhandler.
- Es gibt keinen gemeinsamen durablen Delegation-Ledger für Admission, Work, Lease,
  Terminalresultat und Konflikte.
- _execute_federated_task kann Completion vor echter Verification erzeugen.
- Agent-City-Workflow kann funktionale Fehler bei grünem Run verbergen.

---

## 4. Status der fünf ADRs nach Sprint 1B

| ADR | Sprint-1-Status | Sprint-1B-Status |
|---|---|---|
| ADR-02 | ACCEPTED | AMENDED, Review erforderlich |
| ADR-06 | ACCEPTED | OPEN / REVISION REQUIRED |
| ADR-07 | ACCEPTED | AMENDED, Review erforderlich |
| ADR-08 | ACCEPTED | AMENDED, Review erforderlich |
| ADR-09 | ACCEPTED | AMENDED, Review erforderlich |

ADR-06 bleibt ausdrücklich OPEN, bis Node-ID, key_id, Rotation, Revocation, Registry-
Provenance und Domain Separation von Agent B bestätigt sind.

---

## 5. ADR-02: Transport-Replay versus Application-Reissue

### Transport-Retransmission

Eine Transport-Retransmission ist keine neue fachliche Handlung:

- exakt dieselben kanonischen Bytes
- dieselbe message_id
- derselbe message_hash
- derselbe request_digest
- gleiche issued_at und expires_at
- gleiche Signatur
- nur vor expires_at
- kein neues target_work_id
- keine neue lokale Mission

### Application-Reissue

Ein Application-Reissue nach Ablauf oder endgültigem Transportverlust ist eine neue
Protokoll-Message desselben Delegations-Lifecycles:

- neue message_id
- neuer issued_at-Wert
- neuer expires_at-Wert
- neuer message_hash
- neue Signatur
- gleiche delegation_id
- gleicher request_digest
- gleiche Authority
- gleiches Target
- niemals neue Arbeit bei bereits bekannter Admission, Ausführung oder Recovery

Vor Application-Reissue muss der Origin eine delegation_status_query ausführen oder gültige
Status-Evidence besitzen. Reissue ist nur zulässig, wenn der Target-Ledger UNKNOWN oder
delivery_expired_before_admission meldet und kein target_work_id existiert.

Bei ACCEPTED, EXECUTING, RECOVERY_REQUIRED oder terminalem Zustand ist Application-Reissue
verboten. Der bestehende Lifecycle muss verfolgt oder explizit recovered werden.

Neue Control-Plane-Operationen:

- delegation_status_query: Origin → Target, kein Side Effect
- delegation_status: Target → Origin, signierter Target-Ledger-Snapshot

### ID-Regeln

- delegation_id: Origin vor erstem Send, ein Lifecycle.
- correlation_id: exakt delegation_id.
- message_id: eine pro logischer Message.
- origin_task_id: lokale Steward-Task-ID.
- target_work_id: nach durabler Admission höchstens einmal.
- request_message_id: ursprüngliche delegate_task-Message.
- causation_message_id: unmittelbare Ursache der aktuellen Message.
- receipt_id: fachliche Receipt-Identität.
- subject_message_id: Draft-0.3-verboten.

---

## 6. ADR-08: Request-Digest und Idempotenz

Ein frei gewählter idempotency_key reicht nicht. Draft 0.3 verlangt einen deterministischen
request_digest, den Origin und Target unabhängig berechnen.

### Digest-Input

Exakt dieses semantische Objekt wird kanonisiert:

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

- task_title
- message_id
- request_message_id
- causation_message_id
- issued_at
- expires_at
- message_hash
- signature
- signer_key
- key_id
- request_digest
- idempotency_key

Berechnung:

~~~text
request_digest =
  lowercase_hex(SHA256(canonical_request_digest_input_utf8_bytes))

idempotency_key =
  "fedv1:" + request_digest
~~~

Target berechnet den Digest selbst. Abweichungen:

- anderer Digest bei gleicher delegation_id: duplicate_conflict
- gleiche idempotency_key mit anderem Digest: idempotency_conflict
- callerseitig frei gesetzter oder falsch berechneter Key: request_digest_mismatch
- gleiche semantische Payload mit neuer delegation_id: neue Delegation, kein Cross-Lifecycle-Dedup

deadline und authority sind Bestandteil des Digests und dürfen beim Retry nicht verändert
werden.

---

## 7. ADR-06: Node-ID, Key-ID, Rotation, Revocation und Domain Separation

### Stable Node-ID

Die Node-ID wird nicht mehr aus dem aktuellen Signing-Key abgeleitet:

~~~text
node_id =
  "ag_" + erste 32 lowercase Hex-Zeichen von
  SHA256(identity_root_public_key_hex_ascii)
~~~

Damit stehen 128 Bit Fingerprint-Material und eine stabile Node-ID zur Verfügung.

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

### Rotation

- neuer Signing-Key → neue key_id
- node_id bleibt unverändert
- Überlappungsfenster für alte und neue Schlüssel ist explizit registriert
- neue Messages nach Aktivierung nur mit neuem Key
- alte Messages bleiben verifizierbar, wenn issued_at in ihrer damaligen Gültigkeit lag
  und die Evidence-Retention noch besteht
- key_id ist signierter Envelope-Bestandteil

### Revocation

- revoked Key darf keine neuen Messages signieren
- historische Messages werden nicht rückwirkend ungültig, wenn issued_at und Registry-
  Provenance gültig waren
- kompromittierter Key wird sofort für neue Messages gesperrt
- unbekannte oder nicht registrierte key_id führt zu fail-closed Quarantine
- Revocation-Evidence wird als internes Finding persistiert

Der aktuelle 16-Hex-Key-Digest und die direkte Node-ID-Kopplung an jeden Signing-Key sind
Legacy und nicht Draft-0.3-kompatibel.

### Domain Separation

Feste Domain:

~~~text
STEWARD-FEDERATION-DELEGATION-V1\0
~~~

Der Envelope-Hash wird als rohe 32-Byte-SHA-256-Ausgabe signiert:

~~~text
signature_input =
  UTF8("STEWARD-FEDERATION-DELEGATION-V1\0")
  || raw_sha256_digest_bytes

signature =
  RFC4648_STANDARD_BASE64_WITH_PADDING(
    Ed25519_sign(signing_private_key, signature_input)
  )
~~~

Der Hash wird als message_hash in lowercase Hex übertragen, aber nicht als ASCII-Hex
signiert. Cross-Protocol-Replay wird dadurch verhindert.

ADR-06 bleibt OPEN / REVISION REQUIRED, bis Agent B diese Identity- und Crypto-Grenzen
bestätigt.

---

## 8. Vollständige Canonical-Wire-Regeln

Exakter Versionsliteralwert:

~~~text
federation-delegation-v1
~~~

Zeitprofil:

- UTC
- YYYY-MM-DDTHH:MM:SSZ
- keine Fractional Seconds
- kein Offset außer Z
- keine Leap Seconds
- issued_at < expires_at
- maximale Gültigkeit 24 Stunden
- zulässige Clock-Skew 300 Sekunden

Unicode:

- NFC-Normalisierung
- unpaired Surrogates verboten
- UTF-8 ohne BOM
- ensure_ascii=false

JSON:

- sort_keys=true
- separators=(",", ":")
- Duplicate Keys sind Parse-Fehler
- nur Integer -2^63 bis 2^63-1
- Floats, Exponentenschreibweise, NaN und Infinity verboten
- unbekannte Payload-Felder je Version verboten
- maximale Envelope-Größe 256 KiB
- maximale Payload-Größe 128 KiB
- maximale Verschachtelung 16 Ebenen
- maximale Array-Länge 1024

Base64:

- RFC 4648 Standard Base64
- Padding ist Pflicht, sofern erforderlich
- URL-safe Zeichen '-' und '_' verboten
- Whitespace verboten
- decoded signature exakt 64 Bytes

Der Hash heißt message_hash, nicht payload_hash:

~~~text
message_hash =
  lowercase_hex(
    SHA256(canonical_envelope_without_message_hash_and_signature_utf8_bytes)
  )
~~~

---

## 9. Exakter Draft-0.3-Envelope

Pflicht-/Kausalitätsfelder:

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

Operation-spezifische Konditionen:

- Initialer delegate_task:
  - request_message_id = message_id
  - causation_message_id ist verboten
- Jede Receipt und jedes Resultat:
  - request_message_id ist Pflicht
  - causation_message_id ist Pflicht
  - receipt_id ist bei Receipt/terminal Resultat Pflicht
- subject_message_id ist unbekannt und wird abgelehnt.

Exemplarischer Request:

~~~json
{
  "contract_version": "federation-delegation-v1",
  "message_id": "msg-request-0001",
  "request_message_id": "msg-request-0001",
  "source_node_id": "ag_origin_128bit",
  "target_node_id": "ag_target_128bit",
  "operation": "delegate_task",
  "correlation_id": "del-0001",
  "payload": {
    "delegation_id": "del-0001",
    "origin_task_id": "task-0042",
    "capability": "fix_repository",
    "intent": {"name": "repair", "version": "v1"},
    "task_description": "Execute the authorized repair.",
    "target_repo": "kimeisele/agent-city",
    "authority": {
      "allowed_actions": ["read", "test", "branch", "commit"],
      "denied_actions": ["merge", "secret_access", "context_bridge_activation"]
    },
    "expected_outcome": {"type": "verified_test_and_runtime_observation"},
    "verification_contract": {"postcondition": "handler accepts one valid delegation"},
    "deadline": "2026-07-18T18:00:00Z",
    "request_digest": "<64 lowercase hex>",
    "idempotency_key": "fedv1:<same request_digest>"
  },
  "issued_at": "2026-07-18T16:00:00Z",
  "expires_at": "2026-07-18T18:00:00Z",
  "message_hash": "<64 lowercase hex>",
  "signature": "<RFC4648 standard Base64 with padding>",
  "signer_key": "<64 lowercase hex raw Ed25519 key>",
  "key_id": "key_<64 lowercase hex>"
}
~~~

Exemplarisches Admission-Receipt:

~~~json
{
  "contract_version": "federation-delegation-v1",
  "message_id": "msg-admission-0001",
  "request_message_id": "msg-request-0001",
  "causation_message_id": "msg-request-0001",
  "source_node_id": "ag_target_128bit",
  "target_node_id": "ag_origin_128bit",
  "operation": "delegation_receipt",
  "correlation_id": "del-0001",
  "payload": {
    "receipt_id": "receipt-admission-0001",
    "receipt_stage": "admission",
    "delegation_id": "del-0001",
    "target_work_id": "work-0042",
    "status": "accepted",
    "issuer_role": "target_node",
    "evidence_ref": "target-ledger://del-0001/admission"
  },
  "issued_at": "2026-07-18T16:00:04Z",
  "expires_at": "2026-07-18T18:00:00Z",
  "message_hash": "<computed>",
  "signature": "<computed>",
  "signer_key": "<target-key>",
  "key_id": "<target-key-id>"
}
~~~

Exemplarisches terminales Resultat:

~~~json
{
  "contract_version": "federation-delegation-v1",
  "message_id": "msg-terminal-0001",
  "request_message_id": "msg-request-0001",
  "causation_message_id": "msg-started-0001",
  "source_node_id": "ag_target_128bit",
  "target_node_id": "ag_origin_128bit",
  "operation": "task_completed",
  "correlation_id": "del-0001",
  "payload": {
    "receipt_id": "receipt-terminal-0001",
    "receipt_stage": "terminal",
    "delegation_id": "del-0001",
    "target_work_id": "work-0042",
    "terminal_status": "completed",
    "outcome": {"tests": "passed"},
    "evidence_refs": ["target-test://run/0001"],
    "started_at": "2026-07-18T16:00:05Z",
    "ended_at": "2026-07-18T16:04:00Z",
    "attempt_count": 1,
    "issuer_role": "target_worker"
  },
  "issued_at": "2026-07-18T16:04:01Z",
  "expires_at": "2026-07-19T16:04:01Z",
  "message_hash": "<computed>",
  "signature": "<computed>",
  "signer_key": "<target-key>",
  "key_id": "<target-key-id>"
}
~~~

Die Werte <computed> sind ausschließlich Strukturbeispiele; sie sind keine Fixture-
Signaturen.

---

## 10. Receipt-Partial-Order und Replay

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

| Receipt | Vorgänger |
|---|---|
| transport_committed | SENT/outbox commit |
| admission accepted/rejected | SENT oder transport_committed |
| started | admission accepted |
| terminal | started im Target-Ledger; Ankunft darf out-of-order sein |
| verification | terminal oder terminale Failure-Evidence |

Regeln:

- terminal vor started wird als out_of_order_pending persistiert.
- terminal wird erst angewendet, wenn Target-Ledger Start und Work-Handle beweist.
- fehlendes Started-Receipt wird nicht erfunden; started_receipt_missing bleibt sichtbar.
- admission=rejected ist terminaler Seitenpfad; Started und Terminal sind unzulässig.
- Widersprüche werden ledger_conflict.
- transport_committed ist keine Annahme.

Replay:

- gleiche message_id + gleicher message_hash → Replay/No-op
- gleiche message_id + anderer message_hash → message_id_conflict
- gleiche receipt_id + identischer Body → Replay/No-op
- gleiche receipt_id + anderer Body → receipt_id_conflict
- neue Receipt-Stufe → neue message_id und receipt_id, gleicher request_message_id

---

## 11. Getrennte Target- und Origin-Ledger

### Target-Ledger

Autorität für:

- received
- admitted/rejected
- request_digest
- target_work_id
- lease/owner
- executing
- recovery_required
- terminal result
- Target-Receipt-Evidence
- Message-/Receipt-Conflicts

### Origin-Ledger

Autorität für:

- request created/sent
- request_message_id
- Transport-Evidence
- Admission-/Started-/Terminal-Receipts
- Verification
- einmalige Anwendung auf origin_task_id
- Origin-Conflicts und Findings

Synchronisationsregeln:

1. Target-Ledger entscheidet lokale Annahme, Work, Lease und Terminalresultat.
2. Origin-Ledger entscheidet Send, Korrelation, Verification und Origin-Task-Anwendung.
3. Origin erfindet keine Target-Zustände.
4. Target stellt keine Origin-Verification aus.
5. delegation_status liest Target-Ledger und liefert signierten Snapshot.
6. Widersprüchliche Snapshots werden auf beiden Seiten als ledger_conflict markiert.
7. Jeder Receipt-Zustand setzt den entsprechenden Ledger-Commit voraus.

---

## 12. Authentifizierte versus unauthentifizierte Fehler

Vor erfolgreicher Authentifizierung:

- nur internes Finding/Quarantine
- Rate-Limit und Amplification-Schutz
- keine automatische signierte Netzwerkantwort
- keine Offenlegung von Target-, Capability- oder Authority-Information
- keine Mutation von Target- oder Origin-Ledger außer Quarantine-Evidence

Nach gültiger Signatur, Registry-Provenance und korrektem Target sind signierte Reject-
Receipts zulässig:

- unsupported_contract
- wrong_target
- authority_denied
- capability_unavailable
- request_digest_mismatch
- duplicate_conflict
- idempotency_conflict
- expired

Relay darf ausschließlich transport_committed ausstellen.

---

## 13. Capability-Wiring-Status

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

Statusstufen:

- declared: bekannt, keine Vollständigkeitsbehauptung.
- partially_wired: Pflichtkanten fehlen.
- code_complete: Codekanten, Authority, Ledger, Recovery, Resultat und Receipt vorhanden;
  kein Crucible-/Produktionsbeweis.
- crucible_verified: reale Wire-Bytes und positiver/adversarialer Cross-Repo-Crucible grün.
- production_proven: Crucible plus reproduzierbarer Produktionsbeleg.
- unavailable: kein Handler-/Resultatpfad.
- legacy: historischer oder separat versionierter Pfad.

implemented ist in Draft 0.3 kein gültiger Status.

delegate_task heute:

- Steward-Emitter vorhanden.
- Transport vorhanden.
- exaktes Targeting fehlt.
- Agent-City-Handler fehlt.
- Admission-/Dedupe-Ledger fehlt.
- typed Receipt-Pfad fehlt.
- ID-basierte Callback-Korrelation fehlt.
- Produktionsbeleg fehlt.

Status im IST: unavailable auf Agent-City-Seite und insgesamt partially_wired.

---

## 14. Recovery- und Application-Retry-Fälle

- Replay vor Ablauf: gleiche Bytes, gleiche message_id.
- Ablauf ohne Admission: Statusabfrage, dann neues Application-Reissue mit gleicher delegation_id
  und gleichem request_digest.
- ACCEPTED: kein Reissue, Target-Work verfolgen.
- EXECUTING: kein Reissue, Lease/Status verfolgen.
- RECOVERY_REQUIRED: explizite Recovery, kein blinder Zweitstart.
- Terminal: Resultat replayen oder Verification durchführen.
- Crash vor Admission: Retry zur Admission zulässig.
- Crash nach Admission: target_work_id bleibt.
- Crash während Execution: Work-Handle fortsetzen oder Recovery.
- Crash nach Terminal: Origin wendet Resultat nur einmal an.
- Partial Tool Side Effect: Dedup-Key, Read-back oder Recovery.

Exactly-once wird nicht behauptet.

---

## 15. Offene ADR-Abhängigkeiten

- ADR-01 bleibt für isolierte Federation-Wire-Semantik offen zulässig; keine universelle execution_id.
- ADR-03 muss vor Mapping auf Managed-Task-COMPLETED entschieden werden.
- ADR-04 bleibt offen, solange kein providerabhängiger V1-Crucible-Handler verwendet wird.
- ADR-05 ist vor Produktions-Crucible zwingend.
- ADR-10 ist vor vollständiger Federation-V1-Integration zwingend.
- ADR-06 bleibt bis Bestätigung der neuen Node-/Key-/Domain-Regeln OPEN.

---

## 16. Aktualisierte Blocker-Matrix

| Blocker | Draft-0.3-Regel | Status | Gate |
|---|---|---|---|
| Transport vs Application Retry | gleiche Bytes/Message-ID nur bei gültigem Transport-Replay; Reissue neue Message | adressiert, Review offen | Agent-B-Abnahme |
| Request Binding | request_digest plus deterministischer fedv1:-Key | adressiert, Review offen | Digest-Golden-Test |
| Node-ID/Rotation | stabile 128-Bit-Node-ID, key_id, Registry-Provenance | offen | ADR-06 |
| Domain Separation | feste Federation-V1-Domain plus roher SHA-Digest | adressiert, Review offen | Crypto-Golden-Test |
| Canonical JSON | exakte Zeit-, Unicode-, Integer-, Base64- und Limit-Regeln | adressiert, Review offen | Parser-Fixture |
| Receipt Ordering | Partial Order, Reject-Seitenpfad, Out-of-Order-Pending | adressiert, Review offen | Reordering-Crucible |
| Kausalität | request_message_id plus causation_message_id | adressiert, Review offen | Causal-Fixture |
| Receipt Replay | identisches Receipt replayed; neue Stufe neue IDs | adressiert, Review offen | Duplicate-Fixture |
| Auth Failure | Quarantine ohne Signatur; signiertes Reject erst nach Auth | adressiert, Review offen | Abuse-Test |
| Ledger Ownership | Target- und Origin-Ledger getrennt | adressiert, Review offen | Crash-/Recovery-Test |
| Capability Status | declared → partially_wired → code_complete → crucible_verified → production_proven | adressiert, Review offen | Manifest-Test |
| ADR-03 | Managed-Task-COMPLETED-Mapping | offen | ADR-03 |
| ADR-05 | Workflow-Wahrheit/Produktionsbeleg | offen | ADR-05 |
| ADR-10 | Statusadapter | offen | ADR-10 |

Golden-Wire-Fixtures und Crucible-Design bleiben bis zur Abnahme von ADR-06, Digest-,
Partial-Order-, Replay- und Ledger-Regeln gesperrt.

---

## 17. Draft-0.3-Readiness

Draft 0.3 ist noch nicht READY FOR GOLDEN FIXTURES.

Vor Fixture-Freeze erforderlich:

1. Agent-B-Abnahme von Node-ID, key_id, Registry-Provenance, Rotation und Revocation.
2. Agent-B-Abnahme des Domain-separated Signature Inputs.
3. Golden-Test der vollständigen Canonical-Regeln.
4. Freeze der Payload-Subschemas und Limits.
5. Freeze von request_digest und idempotency_key.
6. Freeze von Partial Order und Out-of-Order-Verhalten.
7. Freeze von request_message_id/causation_message_id.
8. Freeze von Receipt-Replay und Conflict-Semantik.
9. Freeze getrennter Ledger-Verantwortung.
10. Freeze der Capability-Statusstufen.

Bis dahin:

- kein Produktcode
- keine Golden Fixtures
- kein Crucible-Implementierungsdesign
- kein Merge
- Phase 1 read-only
- Context Bridge geparkt

---

## 18. Review-Auftrag an Agent B

Bitte beantworten:

1. Ist die Trennung zwischen Transport-Retransmission und Application-Reissue vollständig?
2. Ist request_digest über die angegebene semantische Payload exakt und ausreichend?
3. Sind idempotency_key, delegation_id und request_digest konfliktfrei gekoppelt?
4. Ist die stabile 128-Bit-Node-ID mit key_id, Rotation, Überlappung und Revocation sicher genug?
5. Ist die Registry-Provenance für alte und neue Signing-Keys vollständig?
6. Verhindert die Domain Separation Cross-Protocol-Replay eindeutig?
7. Sind Zeitprofil, Unicode, Zahlen, Duplicate Keys, Base64, Limits und Versionsliteral
   vollständig für Golden Bytes?
8. Ist message_hash die korrekte Benennung und Scope-Definition?
9. Ist der Receipt-Partial-Order inklusive Out-of-Order, Reject-Seitenpfad und Recovery
   implementierbar?
10. Sind request_message_id und causation_message_id ausreichend, um die Kette ohne
    subject_message_id direkt zum ursprünglichen Request zurückzuführen?
11. Ist Receipt-Replay für message_id und receipt_id eindeutig?
12. Verhindert die Auth-Failure-Trennung signierte Amplification?
13. Sind Target- und Origin-Ledger sauber getrennt und die Synchronisationsregeln vollständig?
14. Sind declared, partially_wired, code_complete, crucible_verified und production_proven
    maschinenlesbar und nicht widersprüchlich?
15. Ist Draft 0.3 nach diesen Änderungen READY FOR GOLDEN FIXTURES oder ist ein weiterer
    ADR-Sprint erforderlich?

Vorläufiges Ergebnis:

~~~text
ADR-02: AMENDED / REVIEW REQUIRED
ADR-06: OPEN / REVISION REQUIRED
ADR-07: AMENDED / REVIEW REQUIRED
ADR-08: AMENDED / REVIEW REQUIRED
ADR-09: AMENDED / REVIEW REQUIRED
Contract Draft 0.3: NOT READY
Produktcode: unverändert
Phase 1: unverändert/read-only
Context Bridge: unverändert/geparkt
~~~
