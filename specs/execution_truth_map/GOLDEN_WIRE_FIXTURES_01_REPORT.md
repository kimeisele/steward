# GOLDEN WIRE FIXTURES 01 — MILESTONE REPORT

> Status: COMPLETE — positive parity and negative-boundary tests green
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

## 4. Negative-Grenzen

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

## 5. Unabhängige Tests

Steward:

    pytest -q tests/federation_v1/test_golden_wire.py
    20 passed

Agent City:

    pytest -q tests/federation_v1/test_golden_wire.py
    20 passed

Die Referenzmodule sind repo-lokal und importieren keine Runtime-Federation-Implementierung
des jeweils anderen Repositories. Die Fixture-Dateien wurden identisch kopiert und über
Manifest-SHA-256 verifiziert.

## 6. Gate

Golden Wire Fixtures 01 ist testseitig abgeschlossen. Das Ergebnis beweist die positive
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
