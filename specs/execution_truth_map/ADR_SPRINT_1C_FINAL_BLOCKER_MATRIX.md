# ADR SPRINT 1C — FINAL BLOCKER MATRIX

> Status: FREEZE COMPLETE — Draft 0.5 READY FOR GOLDEN FIXTURES
> Datum: 2026-07-18
> Scope: enger Federation Delegation Contract V1; kein Produktcode

Diese Matrix ersetzt die historische Sprint-1B-Matrix als aktuelles Gate. Sie bewertet
Dokument-/Wire-Reife, nicht die Implementierung des Produktpfads.

| Blocker/Gate | Normative Lösung in Draft 0.5 | Status | Nächster Nachweis |
|---|---|---|---|
| Transport-Replay vs Application-Retry | Retransmission = identische gültige Bytes/IDs; Reissue = neue message_id/Zeit/Signatur, gleicher Request-Root/Digest | CLOSED | Golden request fixtures |
| Request-Bindung | serverseitig prüfbarer SHA-256 request_digest; idempotency_key = fedv1: + Digest | CLOSED | Digest mutation fixtures |
| Node-ID/Key-Rotation | Root-stabile Node-ID (128-bit Präfix), key_id aus vollständigem Signing-Key-Fingerprint, Root-Certificate | CLOSED | Root/key golden fixtures |
| Root-Recovery | fail-closed Node; manuell/out-of-band; keine Quorum-/Übernahmesemantik | CLOSED | Policy/negative fixtures |
| Revocation | not_before/not_after/revoked_at/revocation_effective_at/reason/rotation_kind; historical_uncertain | CLOSED | Time/revocation fixtures |
| Domain Separation | feste Federation-V1-Domain plus rohe Hashbytes, Ed25519 | CLOSED | Cross-domain negative test |
| SFDJ-1 | sprachneutral: NFC reject, Byte-Canonicality, Integer-only, UTC-Zeit, Base64, Limits | CLOSED | Parser fixtures |
| Hash-Nomenklatur | message_hash für Envelope; payload_hash V1-verboten; receipt_content_digest für Body | CLOSED | Schema/hash fixtures |
| Receipt-Ordnung | Partial Order, rejected-Seitenpfad, out_of_order_pending, ledger_conflict | CLOSED | Reordering fixtures |
| Receipt-Replay | gleiche receipt_id + gleicher Fach-Digest = Replay/Reissue; anderer Digest = conflict | CLOSED | Duplicate/conflict fixtures |
| Kausalität | request_message_id als Request-Root; causation_message_id unmittelbar; subject_message_id verboten | CLOSED | Causation fixtures |
| Auth-/Wrong-Target | internes Finding/Quarantine, keine automatische Netzwerkantwort; fachlicher Reject nur authentifiziert/korrekt adressiert | CLOSED | Abuse/target fixtures |
| Ledger-Besitz | Target-Ledger und Origin-Ledger getrennt | CLOSED | Crash/recovery design |
| Idempotenz/Recovery | durable Dedupe, Lease, RECOVERY_REQUIRED, kein blinder Zweitstart, at-least-once | CLOSED | Recovery fixture/crucible later |
| Capability-Schema | geschlossene Payloads; Manifest inkl. Status Query | CLOSED | Wiring manifest tests |
| Capability-Status | maturity und disposition getrennt; keine Kombination declared/partial/unavailable + active | CLOSED | Manifest validation |
| Status-Query-Privacy | nur kryptografisch gebundener Origin/eingegrenztes Relay; minimaler Snapshot; UNKNOWN nicht als Orakel | CLOSED | Privacy/UNKNOWN fixtures |
| ADR-03 ManagedTask Completion | Mapping von verifiziertem Federation-Ergebnis offen | OPEN — späterer Blocker | vor ManagedTask.COMPLETED |
| ADR-05 Produktionswahrheit | Workflow-/Production-Gates offen | OPEN — späterer Blocker | vor Produktions-Crucible |
| ADR-10 Gesamtintegration | Status-/Observability-/Governance-Integration offen | OPEN — späterer Blocker | vor vollständiger V1-Integration |
| ADR-01 allgemeine Execution-ID | außerhalb isoliertem Wire-Scope | OPEN — kein Fixture-Blocker | spätere Spine-Spec |
| ADR-04 Provider-Pfad | außerhalb, solange Fixture keinen Provider-Handler nutzt | OPEN — konditional | vor providerabhängigem Crucible |

## Gate-Entscheidung

- SFDJ-1: UNVERÄNDERT eingefroren.
- ADR-02, ADR-06, ADR-07, ADR-08, ADR-09: ACCEPTED im engen Federation-V1-Scope.
- Federation Delegation Contract Draft 0.5: READY FOR GOLDEN FIXTURES.
- Noch nicht erlaubt: Produktcode, Parser-/Handler-Implementierung, Ledger-/Workflow-
  Änderungen, Fixtures ausführen, Crucible ausführen, Merge oder Aktivierung.
- Nächster Milestone: Golden-Wire-Fixtures sowie unabhängige Steward-/Agent-City-Parser-
  und Signaturtests.
- Phase 1 und Context Bridge bleiben unverändert; PR #728 bleibt geparkt.
