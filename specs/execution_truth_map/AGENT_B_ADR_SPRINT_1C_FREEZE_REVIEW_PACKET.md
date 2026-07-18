# AGENT-B REVIEW PACKET — FEDERATION DELEGATION V1 SPRINT 1C FREEZE

> Version: Sprint 1C Freeze / Contract Draft 0.5 corrected (four direct review fixes)
> Status: READY FOR GOLDEN FIXTURES — nur Dokumentations-Gate; keine Fixtures, kein Produktcode
> Datum: 2026-07-18
> Review-Ziel: abschließende Prüfung des engen Federation-V1-Wire-Vertrags

Dieses Dokument ist self-contained. Die genannten Pfade sind ergänzende Belege, keine
Voraussetzung für die Beurteilung. Phase 1 und Context Bridge bleiben unverändert.

## 1. Arbeits- und Evidenzbasis

Arbeitsbranch: adr/federation-delegation-sprint-1
Repository: github.com/kimeisele/steward
Review-Basis-Commit vor diesem Freeze: 16fdac80506969635ab74c58803c2811dfbaa748
Historische Recon-Pins:

- Steward Inhaltspinne: 9ebaff3722c98b4cc53c3d921f8c8511c3eaf5b3
- Agent City: e798bdbf7b3969beea577fe265657bbb7c142115
- Steward Protocol: 34a8a0efc25c15ef7c07dd4fb50aeb2510c071e8

Historie wurde für den Recon mit invertiertem Heartbeat-/Federation-Sync-Filter gelesen,
um Heartbeat-State-Commits als Signal-Rauschen auszuschließen. Draft 0.5 ist ein
Dokumentations-Commit nach dem Review; der umschließende Git-SHA ist der Pin dieses Pakets.

### Sprint-Scope

Nur:

1. Payload-Schema-Freeze für delegate_task, delegation_receipt (transport_committed,
   admission, started, terminal, verification), delegation_status_query und
   delegation_status.
2. Root-Recovery bewusst außerhalb von Federation V1 begrenzen.
3. Status-Query auf eigene Delegation und minimales Datenschutz-Schema begrenzen.
4. SFDJ-1 unverändert einfrieren.
5. ADR-02/-06/-07/-08/-09 im engen Federation-V1-Scope auf ACCEPTED setzen.
6. Contract Draft 0.5 und endgültige Blocker-Matrix dokumentieren.

Ausdrücklich nicht verändert:

- kein Produktcode, keine Handler, Ledger, Workflow- oder Provider-Implementierung
- keine Golden-Wire-Fixtures und kein Crucible
- keine Phase-1-Datei
- keine Context-Bridge-Arbeit, PR #728 bleibt offen/geparkt
- kein Merge und keine Aktivierung

Geänderte bzw. neue Dokumentartefakte dieses Freeze:

- specs/FEDERATION_DELEGATION_CONTRACT_V1_DRAFT_0_5.md
- specs/execution_truth_map/AGENT_B_ADR_SPRINT_1C_FREEZE_REVIEW_PACKET.md
- specs/execution_truth_map/ADR_DECISION_SPRINT_1C_REVISION.md
- specs/execution_truth_map/ADR_SPRINT_1C_FINAL_BLOCKER_MATRIX.md
- ADR-02/-06/-07/-08/-09 und ADR_BACKLOG.md: Status-/Gate-Aktualisierung
- docs/PHASE2_BEFUND.md: kompakte autoritative Milestone-Zusammenfassung

Validierung vor dem finalen Commit:

- Dokument-Smoke: keine Markdown-Whitespace-/Patchfehler via git diff --check.
- Read-only Regression: pytest -q tests/test_moksha_health.py => 17 passed.
- Keine Produktdatei ist Teil dieses Sprint-1C-Freeze-Pakets.
- Remote-Push und Remote-SHA werden nach Commit mit git ls-remote verifiziert.

## 2. Belegte Ausgangsrisse

Die Truth Map belegt den IST-Zustand; diese Entscheidungen formalisiert ihn nicht rückwirkend.

### Identität und Korrelation

- steward/tools/delegate.py:DelegateTool.execute sendet Task-Titel und target_agent,
  aber keine stabile lokale Task-ID/Correlation-ID.
- steward/federation.py:FederationBridge.flush_outbound setzt correlation_id="" und
  ignoriert payload.target_agent bei der Peer-Auswahl; es wird an alle passenden Peers gesendet.
- steward/federation.py:FederationBridge._handle_delegate_task erzeugt am Ziel eine neue
  TaskManager-UUID, statt einen Request-Root zu übernehmen.
- _handle_task_callback korreliert über den ersten BLOCKED-Task, dessen Beschreibung den
  delegierten Titel als Substring enthält. Gleiche Titel, Retries und doppelte Callbacks
  sind damit nicht sicher unterscheidbar.
- Es gibt keine durchgehende execution_id und keine Provider-attempt-ID.

### Fehler und Wirkungsnachweis

- ProviderChamber.invoke liefert bei Erschöpfung None; AgentLoop erzeugt AgentEvent.ERROR,
  aber keinen terminalen, korrelierten Workflow-Outcome.
- agent_error ist im Produktionspfad ohne verlässlichen Listener/Persistenz.
- Agent-City .github/workflows/agent-city-heartbeat.yml:127 maskiert git push mit git push
  || true; Run 29644618328 war grün trotz GH006 protected-branch failure.
- Federation Handler-Fehler werden teilweise als bool/Log behandelt; Fehler propagieren
  nicht verbindlich zu Origin-Task, Health, Finding und Receipt.
- DeliveryReceipt in steward/federation_relay.py bestätigt Hub-Zustellung/Peer-Sichtbarkeit,
  nicht Admission, Ausführung oder Postcondition.

### Federation-Wiring und Crypto

- ALL_OPERATIONS in steward/federation.py deklariert 24 Operationen, aber Richtung,
  Handler, Resultatpfad und E2E-Beweis sind nicht vollständig maschinenlesbar.
- OP_DELEGATE_TASK/delegate_task hat in city/ und tests/ keinen Fachhandler; der generische
  Ingress/DHARMA-Pfad konsumiert die Oberfläche ohne konkreten Worker.
- Steward signiert PR-Verdicts über Hashtext/Envelope-Regeln, Agent City erwartet signer_key
  und hex-Signatur; vier Agent-City-E2E-Tests enden mit PR_VERDICT: Signature verification FAILED.
- Status-, Receipt- und Task-IDs haben bislang keine gemeinsame Kausalitäts- und Reissue-Regel.

Belege/Dateien:

- specs/execution_truth_map/EXECUTION_TRUTH_MAP_RECON.md
- steward/tools/delegate.py
- steward/federation.py
- steward/provider/chamber.py
- steward/loop/engine.py
- city/federation_nadi.py
- city/phase_hook.py
- .github/workflows/agent-city-heartbeat.yml
- tests/test_moksha_health.py und die in der Truth Map aufgeführten Agent-City-E2E-Tests

## 3. ADR Decision Sprint 1C — ACCEPTED im engen V1-Scope

Die Entscheidungen gelten nur für den Federation Delegation Contract V1. Sie sind keine
universelle Execution-Spine-Spec und schreiben keine Live-Handler vor.

### ADR-02 — Execution-, Correlation- und Message-ID

Entscheidungsfrage: Wie bleiben Delegation, ursprünglicher Request, einzelne Messages,
Causation, Zielarbeit und Receipts über Retries und Reordering eindeutig verknüpft?

Geprüfte Optionen:

A. eine universelle ID oder Titel-basierte Zuordnung: verworfen; sie kollidiert mit
   vorhandenen getrennten Task-/A2A-/Tool-IDs und dem belegten Titel-Substring-Bug.

B. getrennte, explizit gebundene IDs: ACCEPTED.

Normative Regeln:

- delegation_id wird vom Origin einmal pro Lifecycle erzeugt und bleibt unverändert.
- correlation_id ist exakt delegation_id.
- die erste delegate_task-Message erhält message_id und setzt request_message_id=message_id;
  causation_message_id ist dort verboten.
- Jede Reissue-Message erhält neue message_id, neue Zeit und neue Signatur, aber dieselbe
  delegation_id, correlation_id und request_message_id des ersten Requests.
- causation_message_id referenziert die unmittelbar auslösende Status-/Receipt-/Recovery-
  Message. subject_message_id ist verboten.
- origin_task_id bleibt die lokale Origin-Task-ID; target_work_id wird nach durablem
  Admission genau einmal vom Target erzeugt und bleibt unverändert.
- receipt_id ist die fachliche Receipt-Identität; receipt_content_digest bindet den
  semantischen Receipt-Body.
- request_digest und idempotency_key binden die semantische Request-Payload.
- Keine ID darf aus Titel, Listenposition, Peer-Zeitstempel oder impliziter Reihenfolge
  rekonstruiert werden.

Migration: Legacy-Nachrichten ohne diese IDs sind nicht V1-kompatibel und erhalten keinen
stillen Fallback. Recovery nutzt Status/Evidence, niemals blinde Neuausführung.
Adversariales Gegenargument: zusätzliche IDs erhöhen Storage-/Korrelationstiefe. Antwort:
diese Kosten sind explizit und kleiner als nichtdeterministische Doppelarbeit.
Restrisiko: Managed-Task-Mapping bleibt bis ADR-03 offen.

### ADR-06 — Federation-Signatur, Root und Revocation

Entscheidungsfrage: Welche unverwechselbaren Bytes werden mit welchem Schlüssel und welcher
Provenance signiert?

Option A: bestehende Hashtext-/inner-payload-Signaturen: verworfen; Steward und Agent City
prüfen unterschiedliche Byte-/Encoding-/Key-Verträge.

Option B: Root-stabile Node-ID, Root-zertifizierte Signing-Keys, SFDJ-1, Domain Separation
und fail-closed Verifikation: ACCEPTED.

Normative Regeln:

- node_id = ag_ plus die ersten 32 lowercase Hexzeichen von
  SHA256(identity_root_public_key_hex_ascii); Signing-Key-Rotation ändert node_id nicht.
- key_id = key_ plus vollständige 64 lowercase Hexzeichen von
  SHA256(signing_public_key_raw_bytes).
- Root-Enrollment und Signing-Key-Certificate benötigen Root-Signaturen mit den festen
  Domains STEWARD-FEDERATION-ROOT-ENROLLMENT-V1 und
  STEWARD-FEDERATION-SIGNING-KEY-AUTH-V1, jeweils mit abschließendem NUL-Byte.
- Eine Registry-Zeile allein bindet keinen Key; Root-Provenance, activation, Zeitfenster,
  Revocation und Retention sind erforderlich.
- Signaturinput ist UTF-8-Domain STEWARD-FEDERATION-DELEGATION-V1 plus NUL, gefolgt von
  den rohen 32 Hashbytes; nicht ASCII-Hex.
- Ed25519-Signatur wird Standard-RFC4648-Base64 mit Padding übertragen; URL-safe/Base64-
  Whitespace sind ungültig.
- Root-Verlust oder Root-Kompromittierung ist nicht durch Federation-Messages heilbar.
  Node fail-closed für neue V1-Nachrichten; manuelle out-of-band Neu-Enrollment/
  Governance außerhalb V1; keine Quorum- oder automatische Node-ID-Übernahme. Historische
  Provenance und Audit bleiben erhalten.
- Revocation verwendet not_before, not_after, revoked_at, revocation_effective_at,
  revocation_reason und rotation_kind. not_before/not_after begrenzen issued_at; revoked_at
  ist Registry-Eintragungszeit, effective_at der Ablehnungsbeginn. reason ist
  rotation|compromise|lost|operator_action|other, kind regular|emergency_compromise.
  Unbekannte Kompromisszeit erzeugt historical_uncertain; issued_at < revoked_at allein
  genügt nicht. Gelöschte Provenance ist unavailable, nie verified; Retention umfasst
  not_after plus Envelope-TTL, Clock-Skew und Audit-Retention.

Die beiden Provenance-Records sind selbst geschlossene SFDJ-1-Objekte. Root Enrollment
verwendet exakt enrollment_version=federation-root-enrollment-v1, identity_root_public_key
(PublicKeyB64, 32 Bytes), node_id, not_before, provenance_digest (HashHex), registry_epoch
(Integer) und root_signature (64-Byte SignatureB64). Signiert wird SFDJ-1 aller Felder ohne
root_signature mit Domain STEWARD-FEDERATION-ROOT-ENROLLMENT-V1 plus NUL.
Das Signing-Key-Certificate verwendet exakt activation_at, activation_epoch,
certificate_epoch, certificate_version=federation-signing-key-auth-v1,
identity_root_public_key, key_id, node_id, not_after, not_before, registry_epoch,
revocation_ref (HashHex oder null), rotation_kind=regular|emergency_compromise,
signer_key (PublicKeyB64) und root_signature. Signiert wird SFDJ-1 aller Felder ohne
root_signature mit Domain STEWARD-FEDERATION-SIGNING-KEY-AUTH-V1 plus NUL. Unknown-Fields
sind verboten; Activation und Epochs werden vor Registry-Aktivierung geprüft.

Auswirkungen: Steward und Agent City müssen dieselben SFDJ-/Ed25519-/Root-Certificate-
Bytes prüfen; Steward Protocol erhält ein geschlossenes, sprachneutrales Wire-Profil.
Authority wird vor Dispatch geprüft. Adversariales Gegenargument: Root-Provenance und
manuelle Recovery sind operativ schwer. Antwort: V1 erfindet keine unsichere automatische
Governance. Restrisiko: Root-Recovery ist eine separate Governance-Spec.

### ADR-07 — Capability-Wiring und geschlossene Payloads

Entscheidungsfrage: Wann darf eine Operation als vorhanden gelten und welche Payloads sind
für V1 geschlossen?

Option A: deklarierte Operation = implementiert: verworfen; Truth Map zeigt fehlende Handler,
Transport-/Resultat- und Produktionspfade.

Option B: maschinenlesbares Manifest plus geschlossene V1-Schemas und zwei Statusachsen:
ACCEPTED.

Manifestfelder je operation, contract_version, repository, direction, target:

Emitter, Target, Transport, Admission Handler, Authority Gate, Fachhandler,
Result-/Failure-Operation, Idempotenzspeicher, Receipt-Emitter, E2E-Test, Produktionsbeleg.

Lifecycle maturity:

- declared: Schema und Richtung im Manifest.
- partially_wired: mindestens ein Pfad fehlt.
- code_complete: Codepfade und Contract-/Unit-Tests vorhanden.
- crucible_verified: adversarial repoübergreifender Crucible grün.
- production_proven: ausgerollter, beobachteter Produktionsbeleg.

Disposition: active, unavailable, legacy, disabled. declared/partially_wired/unavailable
plus active und legacy plus active sind verboten. active benötigt crucible_verified;
production_proven setzt zusätzlich Produktionsbeleg voraus. Implemented ist kein V1-Status.

Die Capabilities delegation_status_query und delegation_status sind selbst manifestpflichtig.
Payload-Unknown-Fields sind verboten; nur display_title/display_description sind begrenzte
Darstellung und nie Semantik. V1-Fixture-Capability ist fix_repository; weitere Capability-
Tokens brauchen ein signiertes, versioniertes Wiring-Manifest.

Adversariales Gegenargument: geschlossene Schemas behindern Erweiterung. Antwort: Versionierte
Schema-Erweiterung ist sicherer als ungeprüfte Unknown-Fields. Restrisiko: neue Capability-
Versionen benötigen ein späteres Manifest-Review.

### ADR-08 — Retry, Recovery und Idempotenz

Entscheidungsfrage: Wie verhindert at-least-once Transport doppelte Side Effects?

Option A: exakt-einmalige Ausführung behaupten oder blind bei Timeout neu senden: verworfen;
Crash und partielle Tool-Ausführung machen das unbeweisbar.

Option B: persistente Target-Deduplizierung, Reissue-Regeln, Lease und RECOVERY_REQUIRED:
ACCEPTED.

- Transport-Retransmission = exakt dieselben gültigen Bytes/IDs/Signatur, nur vor expires_at.
- Application-Reissue = neue message_id/Zeit/Hash/Signatur, aber gleiche delegation_id,
  request_message_id, request_digest, idempotency_key, Semantik und Authority.
- Reissue ist nur nach Statusabfrage/Evidence ohne Admission-Handle erlaubt; bei accepted,
  executing, recovery_required oder terminal verboten.
- Target commitet Deduplizierung und target_work_id vor Side Effect.
- gleiche delegation_id plus gleicher Digest = vorhandenes Ergebnis/Evidence, kein zweiter Work.
- gleiche ID plus anderer Digest oder gleiche Idempotency-Key plus anderer Digest =
  fail-closed conflict.
- Crash vor Admission: erneutes Angebot möglich. Crash nach Admission: Work-Handle bleibt.
  Crash in Execution: Resume oder RECOVERY_REQUIRED. Crash nach Terminal: Origin wendet
  einmalig an. Lease-Ablauf erlaubt keinen blinden Zweitstart.
- Partielle Tool-Wirkung verlangt Dedup-Key, Read-back oder explizite Recovery-Entscheidung.

Adversariales Gegenargument: Statusabfrage kann selbst ausfallen. Antwort: UNKNOWN und
RECOVERY_REQUIRED bleiben sichtbar; Ausfall legitimiert keine zweite Arbeit.
Restrisiko: konkrete Lease-Dauer ist außerhalb des V1-Wire-Vertrags zu konfigurieren.

### ADR-09 — Receipt-Semantik

Entscheidungsfrage: Welche Evidence-Stufen beweisen was und wie werden Replays/Kausalität
behandelt?

Option A: ein terminales Erfolgsflag oder DeliveryReceipt als Ausführungsbeweis: verworfen;
Truth Map belegt, dass Transport nicht Wirkung/Verification beweist.

Option B: gestufte Receipts mit Partial Order, receipt_id und receipt_content_digest:
ACCEPTED.

Stufen:

| Stage | Aussteller | Beweist | Beweist ausdrücklich nicht |
|---|---|---|---|
| transport_committed | relay/hub | Mailbox-/Transport-Commit | Admission, Start, Ergebnis |
| admission | target_node | accepted/rejected und Dedupe-Entscheidung | Ausführung/Success |
| started | target_scheduler | Work-Handle durable gestartet | Ergebnis/Postcondition |
| terminal | target_worker/target_node | Target meldete completed/failed mit bounded evidence | unabhängige Verification |
| verification | origin_node | Origin prüfte independent_postcondition | neue Target-Ausführung |

Partial Order:

SENT -> optional transport_committed -> admission(accepted) -> started -> terminal -> verification.
SENT -> admission(rejected) ist terminaler Seitenpfad.
accepted -> recovery_required ist ein Seitenpfad ohne blindes Re-run.

Out-of-order terminal wird als out_of_order_pending persistiert; fehlende Started-Evidence
wird nicht erfunden. Widerspruch ist ledger_conflict. admission=rejected darf keine
Started-/Terminal-Receipt erzeugen.

Receipt-Transport-Retransmission sendet identische Bytes mit gleicher message_id und
receipt_id. Receipt-Application-Reissue erzeugt neue Envelope-message_id/Zeit/Hash/Signatur,
aber dieselbe receipt_id, denselben receipt_content_digest und denselben fachlichen Body;
es gibt keine neue Stage oder Transition. Gleiche receipt_id mit anderem Fach-Digest ist
receipt_id_conflict. request_message_id bleibt der ursprüngliche Request-Root; causation
zeigt auf die auslösende Receipt-/Status-/Recovery-Message.

Adversariales Gegenargument: mehrere Stufen vergrößern Reordering-Zustand. Antwort: genau
dieser Zustand macht fehlende Beweise sichtbar statt sie als Erfolg zu maskieren.
Restrisiko: Verification-Postconditions werden je Capability konkretisiert.

## 4. Vollständiger geschlossener Wire-Vertrag

### 4.1 Primitive und Canonical JSON

SFDJ-1 ist sprachneutral und unverändert eingefroren:

- UTF-8 ohne BOM, Duplicate Keys reject, rekursive NFC-Pflicht (nicht-NFC reject).
- Keys nach NFC-UTF-8-Bytes sortiert, Arrays in Eingangsreihenfolge.
- Keine äußeren Whitespace; Slash nicht escaped; Quote/Backslash standard JSON;
  Steuerzeichen als lowercase Unicode-Escape.
- Nur Integer -2^63..2^63-1; keine Floats, Exponenten, führenden Nullen, -0, NaN/Infinity.
- eingehende Bytes müssen bytegleich rekonstruiert werden.
- Zeit exakt UTC YYYY-MM-DDTHH:MM:SSZ, keine Fractional Seconds/Offsets/Leap-Seconds.
- RFC4648 Standard-Base64 mit Padding, nicht URL-safe; signer_key und
  identity_root_public_key decodieren jeweils exakt 32 rohe Ed25519-Bytes, eine Signatur
  exakt 64 Bytes.
- Limits Envelope 256 KiB, Payload 128 KiB, Tiefe 16, Array 1024, Key 256 Bytes,
  String 64 KiB; contract_version exakt federation-delegation-v1.

Primitive: IdString ASCII [A-Za-z0-9][A-Za-z0-9._:-]{0,127}; NodeId ag_ plus 32
lowercase hex; KeyId key_ plus 64 lowercase hex; HashHex 64 lowercase hex; Timestamp
wie oben; EvidenceRef 1..256-Byte-URI; kein Feld implizit nullable. Top-Level- und
Payload-Unknown-Fields sind verboten.

### 4.2 Envelope-Top-Level

Pflichtkeys: contract_version, message_id, request_message_id, source_node_id,
target_node_id, operation, correlation_id, payload, issued_at, expires_at, message_hash,
signature, signer_key, key_id. causation_message_id ist für Antworten/Receipts/Status
Pflicht und für den initialen Request verboten. request_message_id ist initial gleich
message_id; später immer der Request-Root. Keine zusätzlichen Keys, subject_message_id
verboten.

message_hash = lowercase_hex(SHA256(SFDJ-1(canonical envelope without message_hash/signature))).
Signatur = Ed25519 über:
UTF8(STEWARD-FEDERATION-DELEGATION-V1 plus NUL) || rohe SHA256-Digestbytes;
Übertragung Standard-Base64 mit Padding.

### 4.3 delegate_task Payload

Pflicht: delegation_id, origin_task_id, capability, intent, task_description, target_repo,
authority, expected_outcome, verification_contract, deadline, request_digest,
idempotency_key. Optional nur display_title (max 256 Bytes) und display_description
(max 4096 Bytes), beide NFC/nicht-null bei Anwesenheit.

- capability Token; Fixture-Enum fix_repository, andere Werte nur manifestiert.
- intent exakt kind=repair, version=v1.
- authority exakt allowed_actions (1..8 aus read/test/branch/commit), denied_actions
  (0..8 aus merge/secret_access/context_bridge_activation), repo_scope IdString.
- expected_outcome exakt kind=verified_tests_and_observation.
- verification_contract exakt postcondition_kind=tests_and_runtime_observation und
  required_evidence (1..4 aus test_result/runtime_observation).
- task_description NFC 1..4096 Bytes ist gebundener Arbeitskontext, steuert aber nie
  Capability, Authority oder Verification; target_repo IdString 1..128; deadline Timestamp.
- display_title/display_description sind die einzigen freien Darstellungsfelder und werden
  aus Dispatch-, Authority-, Korrelation-, Idempotenz- und Verification-Digests ausgeschlossen.
- request_digest bindet contract_version, operation, source_node_id, target_node_id und
  alle semantischen Felder außer display_*, request_digest/idempotency_key und Envelope-
  Metadaten; SHA256 über SFDJ-1. idempotency_key ist fedv1: + Digest.

### 4.4 delegation_receipt Payload

Gemeinsame Pflicht: receipt_id, delegation_id, receipt_stage, issuer_role, status,
receipt_content_digest. Stage-Enum transport_committed, admission, started, terminal,
verification; Payload-Unknown-Fields verboten.

issuer_role ist selbst ein geschlossenes Pflichtfeld und muss zum Stage-Enum passen:
relay/hub, target_node, target_scheduler, target_worker/target_node oder origin_node.
terminal und verification verlangen 1..8 EvidenceRefs; admission/started erlauben 0..4;
transport_committed verlangt mailbox_ref und keine freien EvidenceRefs.

- transport_committed: Issuer relay/hub, status committed, mailbox_ref Pflicht,
  target_work_id null/fehlend; beweist keinen Work-Handle.
- admission: Issuer target_node, status accepted/rejected; accepted braucht target_work_id,
  rejected null/fehlend und reason_code aus unsupported_contract, authority_denied,
  capability_unavailable, request_digest_mismatch, duplicate_conflict,
  idempotency_conflict, expired.
- started: Issuer target_scheduler, status started; target_work_id, started_at Timestamp,
  attempt_count 1..32.
- terminal: Issuer target_worker/target_node, status completed/failed; target_work_id,
  started_at, ended_at, attempt_count; genau outcome oder failure. outcome = result_kind
  tests_and_observation plus test_status passed/failed. failure.code =
  target_execution_failed, target_result_unverifiable, recovery_required, expired,
  authority_denied, capability_unavailable oder unknown.
- verification: Issuer origin_node, status verified/failed_verification; target_work_id,
  verification_kind independent_postcondition, 1..8 EvidenceRefs.

receipt_content_digest bindet den gesamten semantischen Stage-Body inklusive IDs, Issuer,
Status,
Zeitfelder, Attempt, Evidence und Outcome/Failure, aber nicht Envelope-IDs, Envelope-Zeit,
message_hash, Signatur, Key, receipt_content_digest selbst oder display_*.

### 4.5 Status Query und Privacy

delegation_status_query ist geschlossen, max 2 KiB, Pflichtfelder:
delegation_id, request_message_id, known_request_digest, query_scope.
query_scope ist ausschließlich lifecycle_and_receipts. Ein authentifizierter und korrekt
adressierter Origin darf abfragen; bei eigenem Ledger-Eintrag kommt der echte Snapshot,
bei unbekannter oder fremder delegation_id derselbe minimale UNKNOWN-Snapshot ohne
Reason-/Timing-Differenz. Relay bleibt auf eine explizit delegationsgebundene Lesefreigabe
beschränkt. Falsches Target/unauthenticated -> lokales Finding/Quarantine, keine
Netzwerkantwort; Rate-Limit/Audit lokal; read-only, keine Arbeit.

delegation_status ist geschlossen, max 8 KiB:
delegation_id, request_message_id, snapshot_id, snapshot_version, target_state,
target_work_id (nur für UNKNOWN/REJECTED/EXPIRED nullable), request_digest,
observed_receipt_stages (unique, max fünf), terminal_status (completed|failed oder null,
nur RESULT_REPORTED nicht-null; verified/failed_verification gehören ausschließlich zum
Origin-Ledger und zur verification-Receipt)
und as_of. target_state Enum UNKNOWN, ACCEPTED, EXECUTING, RECOVERY_REQUIRED,
RESULT_REPORTED, REJECTED, EXPIRED. snapshot_version monoton pro Delegation.
Response enthält keine Worker-/Lease-Identität, Stacktraces, Secrets, Pfade, fremde
Delegationen oder nicht vertragliche Evidence. Ein authentifizierter Origin erhält bei
Ledger-Eintrag für genau seine ID den echten Snapshot. Bei unbekannter ID oder einer ID,
die einem anderen Origin gehört, erhält er denselben minimalen UNKNOWN-Snapshot mit
identischen Feldern, Größenklasse, Statuswerten und ohne unterschiedliche Reason-/Timing-
Evidence. Damit ist UNKNOWN kein Existenzorakel. Status ist signiert, aber keine
Receipt/Verification.

### 4.6 JSON-Beispiele (semantische Fixtures)

Kanonischer Request-Body vor Hash/Signatur:

~~~json
{
  "contract_version": "federation-delegation-v1",
  "message_id": "msg_req_0001",
  "request_message_id": "msg_req_0001",
  "source_node_id": "ag_11111111111111111111111111111111",
  "target_node_id": "ag_22222222222222222222222222222222",
  "operation": "delegate_task",
  "correlation_id": "del_0001",
  "payload": {
    "authority": {
      "allowed_actions": ["branch","commit","read","test"],
      "denied_actions": ["context_bridge_activation","merge","secret_access"],
      "repo_scope": "agent-city"
    },
    "capability": "fix_repository",
    "deadline": "2026-07-18T12:00:00Z",
    "delegation_id": "del_0001",
    "expected_outcome": {"kind": "verified_tests_and_observation"},
    "idempotency_key": "fedv1:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "intent": {"kind": "repair","version": "v1"},
    "origin_task_id": "task_0001",
    "request_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "target_repo": "agent-city",
    "task_description": "Repair the bounded federation defect.",
    "verification_contract": {
      "postcondition_kind": "tests_and_runtime_observation",
      "required_evidence": ["runtime_observation","test_result"]
    }
  },
  "issued_at": "2026-07-18T11:00:00Z",
  "expires_at": "2026-07-18T11:05:00Z",
  "message_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==",
  "signer_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
  "key_id": "key_3333333333333333333333333333333333333333333333333333333333333333"
}
~~~

Admission Receipt:

~~~json
{
  "contract_version": "federation-delegation-v1",
  "message_id": "msg_rcpt_adm_0001",
  "request_message_id": "msg_req_0001",
  "causation_message_id": "msg_req_0001",
  "source_node_id": "ag_22222222222222222222222222222222",
  "target_node_id": "ag_11111111111111111111111111111111",
  "operation": "delegation_receipt",
  "correlation_id": "del_0001",
  "payload": {
    "delegation_id": "del_0001",
    "receipt_id": "rcpt_0001",
    "receipt_stage": "admission",
    "receipt_content_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "issuer_role": "target_node",
    "status": "accepted",
    "target_work_id": "work_0001"
  },
  "issued_at": "2026-07-18T11:00:01Z",
  "expires_at": "2026-07-18T11:05:01Z",
  "message_hash": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==",
  "signer_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
  "key_id": "key_4444444444444444444444444444444444444444444444444444444444444444"
}
~~~

Application-Reissue (gleiche semantische delegate_task-Payload, neuer Envelope):

~~~json
{
  "contract_version": "federation-delegation-v1",
  "message_id": "msg_req_0002",
  "request_message_id": "msg_req_0001",
  "causation_message_id": "msg_status_0001",
  "source_node_id": "ag_11111111111111111111111111111111",
  "target_node_id": "ag_22222222222222222222222222222222",
  "operation": "delegate_task",
  "correlation_id": "del_0001",
  "payload": {
    "delegation_id": "del_0001",
    "origin_task_id": "task_0001",
    "capability": "fix_repository",
    "intent": {"kind": "repair", "version": "v1"},
    "task_description": "Repair the bounded federation defect.",
    "target_repo": "agent-city",
    "authority": {"allowed_actions": ["branch","commit","read","test"],"denied_actions": ["context_bridge_activation","merge","secret_access"],"repo_scope": "agent-city"},
    "expected_outcome": {"kind": "verified_tests_and_observation"},
    "verification_contract": {"postcondition_kind": "tests_and_runtime_observation","required_evidence": ["runtime_observation","test_result"]},
    "deadline": "2026-07-18T12:00:00Z",
    "request_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "idempotency_key": "fedv1:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "issued_at": "2026-07-18T11:02:00Z",
  "expires_at": "2026-07-18T11:07:00Z",
  "message_hash": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==",
  "signer_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
  "key_id": "key_3333333333333333333333333333333333333333333333333333333333333333"
}
~~~

Die neue message_id, Zeit, message_hash und Signatur sind neu; request_message_id,
delegation_id, request_digest, idempotency_key und correlation_id bleiben unverändert.
Der gezeigte Digest ist ein Formwert, nicht der Hash dieses Prosa-Beispiels.

Status Query payload (embedded under the full signed envelope):

~~~json
{
  "delegation_id": "del_0001",
  "known_request_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "query_scope": "lifecycle_and_receipts",
  "request_message_id": "msg_req_0001"
}
~~~

Minimal UNKNOWN response payload (embedded under delegation_status envelope):

~~~json
{
  "as_of": "2026-07-18T11:01:00Z",
  "delegation_id": "del_0001",
  "observed_receipt_stages": [],
  "request_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "request_message_id": "msg_req_0001",
  "snapshot_id": "snap_0001",
  "snapshot_version": 0,
  "target_state": "UNKNOWN",
  "target_work_id": null,
  "terminal_status": null
}
~~~

Die JSON-Blöcke sind Strukturbeispiele; Golden Fixtures müssen die ausgeschriebenen SFDJ-1-
Bytes, Hashes und Ed25519-Signaturen reproduzierbar berechnen. Die Platzhalterwerte oben
sind keine gültigen Produktionssignaturen.

## 5. Receipt-/Ledger-/Recovery-Vertrag

Target-Ledger besitzt: received, request_digest, idempotency_key, Admission, target_work_id,
Lease/Owner, started/executing, RECOVERY_REQUIRED, terminal result und Konflikte.

Origin-Ledger besitzt: Request-Erstellung/Send, request_message_id, Transport-Evidence,
Admission/Started/Terminal/Verification-Receipts, Status-Snapshots, Verification und
einmalige Anwendung auf origin_task_id.

Partielle Reihenfolge und Zustandsbehandlung:

- admission rejected ist terminaler Seitenpfad; kein Started/Terminal.
- terminal vor started wird pending Evidence; Status/Target-Ledger muss Work-Handle belegen.
- fehlende Stufen werden nie erfunden; widersprüchliche Evidence = ledger_conflict.
- gleiches Receipt-Body/Digest = Duplicate/Replay; geänderter Body bei gleicher receipt_id =
  receipt_id_conflict.
- Transport retransmission: identische Message-Bytes und IDs.
- Application reissue: neue Envelope-Message-ID, gleiche fachliche ID/Content-Digest.
- Status UNKNOWN darf nicht als Freigabe für blinde Neuausführung interpretiert werden.
- RECOVERY_REQUIRED verlangt explizite Status-/Recovery-Entscheidung vor Reissue.
- Lease-Ablauf ist kein Berechtigungsbeweis für zweiten Start.
- Exactly-once wird nicht behauptet; Side Effects benötigen Dedup-Key, Read-back oder
  Recovery.

## 6. Root-Recovery und Auth-Failure

Root-Recovery:

- Node mit verlorener/kompromittierter Root wird für neue V1-Nachrichten fail-closed.
- Federation V1 enthält keine Quorum-, Operator-, automatische Übernahme- oder Root-
  Replacement-Semantik.
- Manuelle out-of-band Governance/Neu-Enrollment ist externe Abhängigkeit.
- Historische Registry-Provenance/Audit bleiben erhalten.

Auth-/Wrong-Target:

- Parse-, Schema-, Key-, Signatur-, Registry- oder Target-Fehler erzeugen lokales Finding/
  Quarantine.
- Vor ausreichender Authentifizierung und korrektem Target keine externe Reject-Signatur.
- Dies verhindert Amplification und ein Identity-/Routing-Orakel.
- Authentifizierte, korrekt adressierte fachliche Rejects sind erlaubt und müssen Receipt-
  Gründe aus dem geschlossenen Enum verwenden.

## 7. Offene ADRs und Abhängigkeiten

| ADR | Frage | V1-Status | Abhängigkeit |
|---|---|---|---|
| ADR-01 | allgemeiner Federation-/Provider-Kontext | OPEN, außerhalb isolierter Wire-Semantik | blockiert keinen reinen V1-Wire-Fixture |
| ADR-03 | Mapping verifiziertes Federation-Ergebnis auf ManagedTask | OPEN | muss vor ManagedTask.COMPLETED entschieden werden |
| ADR-04 | Provider-spezifischer Handler-/Failover-Vertrag | OPEN | blockiert erst providerabhängigen Crucible |
| ADR-05 | Produktions-/Governance-Crucible-Gates | OPEN | blockiert Produktions-Crucible |
| ADR-10 | vollständige Integrations-/Observability-Governance | OPEN | blockiert vollständige V1-Integration |

Keine dieser offenen Fragen darf im engen V1-Wire-Contract implizit beantwortet werden.

## 8. Readiness-Entscheidung

Nach Sprint 1C sind die drei Agent-B-Gates erfüllt:

1. geschlossene Payload-Subschemas und unbekannte Felder/Nullability/Größen sind eingefroren;
2. Root-Recovery ist bewusst manuell/out-of-band, fail-closed und ohne Quorum-Automatismus;
3. Status Query ist auf kryptografisch gebundene eigene Delegation und minimales Snapshot-
   Datenschutzmodell begrenzt.

Daher: **READY FOR GOLDEN FIXTURES** für den engen Wire-Vertrag. Dieser Status autorisiert
nicht die Implementierung. Der nächste Milestone ist ausschließlich Golden-Wire-Fixtures plus
unabhängige Steward-/Agent-City-Parser- und Signaturtests. Danach braucht es vor einem
Produktions-Crucible weiterhin ADR-03/05/10 und ein separates Review.

## 9. Agent-B Review-Auftrag

Bitte Draft 0.5 direkt auf die folgenden Punkte prüfen, ohne Produktcode zu schreiben:

1. Sind die fünf Payload-Schemas hinsichtlich required/optional/nullability, Typen,
   Größenlimits, Enums und Unknown-Field-Regel vollständig und widerspruchsfrei?
2. Ist jedes Feld eindeutig als request_digest-, receipt_content_digest- oder
   digest-excluded klassifiziert?
3. Sind die SFDJ-1-Bytes sprachneutral, insbesondere NFC-Rejection, Key-Sortierung,
   Integer-/Timestamp-/Base64-Regeln und Canonicality-Check?
4. Sind Root-Key-Provenance, key_id, Rotation, Revocation und die externe Root-Recovery-
   Grenze ohne automatische Quorum-/Übernahmesemantik implementierbar?
5. Verhindern Domain Separation und die Verifikationsreihenfolge Cross-Protocol-Replay,
   Wrong-Target-Orakel und unauthentifizierte Reject-Amplification?
6. Sind request_message_id, causation_message_id, message_id, receipt_id und
   receipt_content_digest bei Request-/Receipt-Retransmission und Reissue kausal eindeutig?
7. Ist der Receipt-Partial-Order inklusive terminal-vor-started, rejected-Seitenpfad,
   Pending-Evidence und ledger_conflict testbar?
8. Sind Target- und Origin-Ledger sauber getrennt, und verbietet RECOVERY_REQUIRED blinde
   Neuausführung trotz at-least-once und partieller Side Effects?
9. Sind delegation_status_query und delegation_status selbst vollständig gewired,
   privacy-minimal, rate-limited und bei UNKNOWN nicht als Existenz-Orakel missbrauchbar?
10. Ist Draft 0.5 jetzt tatsächlich READY FOR GOLDEN FIXTURES, oder gibt es eine direkte
    normative Inkonsistenz, die vor SFDJ-1-Freeze/Fixture-Design behoben werden muss?

Bitte nur ACCEPTED oder konkret begründete OPEN-Punkte melden. Kein Sprint 1D mit neuen
Architekturthemen eröffnen; keine Fixtures und keinen Produktcode im Review-Schritt.
