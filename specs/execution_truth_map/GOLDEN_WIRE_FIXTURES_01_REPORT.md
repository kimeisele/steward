# GOLDEN WIRE FIXTURES 01A — MILESTONE REPORT

> Status: COMPLETE — independent regeneration and negative-boundary parity green
> Fixture branch: fixtures/federation-v1-golden-01
> Scope: test-only artifacts and independent reference tests
> Spec pin: ddf170d10a5d546af4b012a2d2335c37fcb44508
> No runtime handler, ledger, workflow or production integration

## 1. Artefakte

Fixture root:

- tests/fixtures/federation_v1/keys/
- tests/fixtures/federation_v1/provenance/
- tests/fixtures/federation_v1/messages/
- tests/fixtures/federation_v1/negative/
- tests/fixtures/federation_v1/manifest.json

Der Manifest enthält Fixture-Version, Spec-Commit, erwartete positive Werte, alle Negativfälle
mit Reject-Code/Validierungsphase sowie SHA-256 für jedes Artefakt außer dem Manifest selbst.
Die privaten Seeds sind synthetische, deterministische Testwerte und als nicht-produktiv
markiert. Keine echten Secrets wurden verwendet.

## 2. Positiver Root-/Certificate-Beweis

| Seite | node_id | key_id |
|---|---|---|
| Origin | ag_25f578ee40fd903d47753dab144a834d | key_24f6ed6acbfe1009c030d7ca567c33ca4830911498236b5561a6c82abec5de28 |
| Target | ag_4764c2d6e6c17738992e6ca41ab0aeef | key_68894d58f18f2c34d49eb2f4b110e042cd0f3150a4dc39243d7f63bd598c0783 |

Origin:

- Enrollment canonical-body SHA-256:
  1ee9ed6654619760df1e57316b41fb8a652fb632ef98cbe69c3eba7dd31039ad
- Certificate canonical-body SHA-256:
  5f3cffee8ed2272deabaa71c21b5682b04fe9f60b2c58742960ad914ce4b3429

Target:

- Enrollment canonical-body SHA-256:
  c6097672b99d14cc78b0c97032221c895f084390a0cdd3deae648296da73f4bf
- Certificate canonical-body SHA-256:
  8bb01d9735e4287bd27066e69b046e8bc07c2dd5bf381ab13a7b72e01bb0f304

Für beide Seiten prüfen die Referenztests SFDJ-1-Bytegleichheit, Root-Signatur,
Node-ID-/Key-ID-Ableitung, Certificate-Zeitfenster und Domain Separation.

## 3. Positiver delegate_task-Beweis

- Canonical Request Bytes:
  tests/fixtures/federation_v1/messages/delegate_task.json
- request_digest:
  7fc471574d5f54d8373c5040309900abefc0c2d4cbe2349e3e09090670dbd241
- idempotency_key:
  fedv1:7fc471574d5f54d8373c5040309900abefc0c2d4cbe2349e3e09090670dbd241
- message_hash:
  daca235ba51c750b71773e2547ef315abdf8a0035315815cfa2989c0a2f67ccb
- Signature-Input liegt als hex unter
  tests/fixtures/federation_v1/messages/delegate_task.signature_input.hex.
- Ed25519-Signatur und Public-Key sind echte berechnete Werte im Envelope.

Steward und Agent City erzeugen aus dem gespeicherten Envelope unabhängig dieselben:

- Canonical Bytes
- Request Digest
- Idempotency-Key
- Node-ID
- Key-ID
- Message Hash
- Ed25519-Signaturprüfung

## 4. Positive-Regeneration-Parität (01A)

Die beiden Repositories regenerieren die positiven Werte aus denselben semantischen
Eingaben und den deterministischen Test-Seeds, ohne einander oder eine gemeinsame
Runtime-Library zu importieren. Jede Zeile vergleicht den regenerierten Wert mit dem
gespeicherten Fixture und dem Manifest.

| Wert | Steward regeneriert | Agent City regeneriert | Fixture | byteidentisch |
|---|---:|---:|---:|---:|
| Origin/Target Enrollment Bytes | ja | ja | ja | ja |
| Origin/Target Certificate Bytes | ja | ja | ja | ja |
| node_id (Origin/Target) | ja | ja | ja | ja |
| key_id (Origin/Target) | ja | ja | ja | ja |
| request_digest | ja | ja | ja | ja |
| idempotency_key | ja | ja | ja | ja |
| delegate_task Request Bytes | ja | ja | ja | ja |
| message_hash | ja | ja | ja | ja |
| Domain-separated Signature Input | ja | ja | ja | ja |
| Ed25519-Signatur | ja | ja | ja | ja |

Die Provenance-Tests prüfen geschlossene Feldmengen, Root-Key-Bindung, Certificate-
Root-Bindung, `node_id`/`key_id`, Domain Separation, Registry-/Certificate-/Activation-
Epochs, Aktivierungs- und Gültigkeitsfenster, `rotation_kind`, `revocation_ref` sowie
RFC-3339-Zeitsemantik am festen Prüfzeitpunkt `2026-07-18T11:00:00Z`.

## 5. Negative-Grenzen und erste Fehlerphase (01A)

17 Fälle sind im Manifest festgelegt und werden in beiden Repositories geprüft:

- non-NFC, falsche Key-Reihenfolge, Duplicate-Key
- Float, -0
- fehlendes Base64-Padding, URL-safe Base64
- falscher Message Hash, mutierter Payload, mutiertes Target
- falscher Signing-Key, nicht autorisierter Signing-Key
- falsches Target
- gleiche Delegation mit anderem Digest
- gleiche Message-ID mit anderen Bytes
- abgelaufenes Certificate
- widerrufener Key

Jeder Fall besitzt einen maschinenlesbaren Reject-Code und eine benannte Validierungsphase.
Die lokale Referenzvalidierung dispatcht ausschließlich nach dem geparsten Schema und
prüft jede Nachricht in einer festen Phasenreihenfolge; weder Fall-ID noch Dateiname
entscheidet den Reject-Code. Beide Repositories liefern dieselbe erste Fehlergrenze:

| Fixture | Steward first failure | Agent City first failure | erwartet | identisch |
|---|---|---|---|---:|
| non_nfc | rejected_noncanonical / sfdj_nfc | rejected_noncanonical / sfdj_nfc | rejected_noncanonical / sfdj_nfc | ja |
| wrong_key_order | rejected_noncanonical / sfdj_key_order | rejected_noncanonical / sfdj_key_order | rejected_noncanonical / sfdj_key_order | ja |
| duplicate_json_key | duplicate_json_key / parse | duplicate_json_key / parse | duplicate_json_key / parse | ja |
| float | float_forbidden / number | float_forbidden / number | float_forbidden / number | ja |
| negative_zero | rejected_noncanonical / number | rejected_noncanonical / number | rejected_noncanonical / number | ja |
| missing_base64_padding | invalid_base64 / base64 | invalid_base64 / base64 | invalid_base64 / base64 | ja |
| url_safe_base64 | url_safe_base64_forbidden / base64 | url_safe_base64_forbidden / base64 | url_safe_base64_forbidden / base64 | ja |
| wrong_message_hash | message_hash_mismatch / message_hash | message_hash_mismatch / message_hash | message_hash_mismatch / message_hash | ja |
| mutated_payload | message_hash_mismatch / message_hash | message_hash_mismatch / message_hash | message_hash_mismatch / message_hash | ja |
| mutated_target_node_id | message_hash_mismatch / message_hash | message_hash_mismatch / message_hash | message_hash_mismatch / message_hash | ja |
| wrong_signing_key | signature_invalid_wrong_key / signature | signature_invalid_wrong_key / signature | signature_invalid_wrong_key / signature | ja |
| unregistered_signing_key | key_not_authorized / registry | key_not_authorized / registry | key_not_authorized / registry | ja |
| wrong_target_resigned | wrong_target / target_match | wrong_target / target_match | wrong_target / target_match | ja |
| same_delegation_different_digest | duplicate_conflict / target_dedupe | duplicate_conflict / target_dedupe | duplicate_conflict / target_dedupe | ja |
| same_message_id_different_bytes | message_id_conflict / message_dedupe | message_id_conflict / message_dedupe | message_id_conflict / message_dedupe | ja |
| expired_certificate | certificate_expired / registry_time | certificate_expired / registry_time | certificate_expired / registry_time | ja |
| revoked_certificate | key_revoked / registry_status | key_revoked / registry_status | key_revoked / registry_status | ja |

## 6. Unabhängige Tests

Steward:

    pytest -q tests/federation_v1
    23 passed

Agent City:

    pytest -q tests/federation_v1
    23 passed

Die Referenzmodule und Builder sind repo-lokal und importieren weder Runtime-Federation-
Implementierung noch Test-Builder des jeweils anderen Repositories. Die Fixture-Dateien
wurden identisch kopiert und über Manifest-SHA-256 verifiziert. Die Negativtests beweisen
zudem, dass die erwartete Grenze jeweils die erste fehlschlagende allgemeine Phase ist.

## 7. Gate

Golden Wire Fixtures 01A ist testseitig abgeschlossen. Das Ergebnis beweist die positive
SFDJ-/Digest-/ID-/Signature-Parität und die vereinbarten Reject-Grenzen; es implementiert
keinen produktiven Handler und behauptet keine Ledger-/Recovery-/Workflow-Wirkung.

Noch nicht durchgeführt:

- Produktintegration
- Federation-Handler
- Ledger oder Runtime-Deduplizierung
- Provider-/Workflow-Crucible
- Produktionsaktivierung
- Merge

Der nächste Review-Schritt ist die erneute Agent-B-Abnahme dieses Fixture-Milestones auf
den Steward- und Agent-City-Branches.
