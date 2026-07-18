# ADR SPRINT 1B — BLOCKER MATRIX

> Status: OPEN / REVISION REQUIRED
> Datum: 2026-07-18
> Scope: Federation Delegation Contract V1 Draft 0.3

| Blocker | Current evidence | Draft-0.3 rule | Status | Gate |
|---|---|---|---|---|
| Transport vs Application Retry | Old rule reused message_id ambiguously | same bytes/message_id only for valid transport retransmission; reissue gets new envelope/message_id | addressed, review required | Agent-B approval |
| Request Binding | idempotency_key was caller string | semantic request_digest plus deterministic fedv1: key | addressed, review required | digest golden test |
| Node Identity | current derive_node_id uses 16 hex chars and current key | stable 128-bit node_id, key_id, registry provenance | open | ADR-06 decision |
| Key Rotation | node_id changed with key | stable node_id, overlapping key validity, revocation | open | registry/rotation ADR review |
| Domain Separation | signature over ASCII hash without protocol domain | fixed STEWARD-FEDERATION-DELEGATION-V1 domain plus raw digest | addressed, review required | crypto golden test |
| Canonical JSON | missing time/unicode/number/base64/limits | exact version/time/NFC/integer/base64/size rules | addressed, review required | parser fixture |
| Hash Naming | payload_hash hashes envelope body | message_hash; payload_hash legacy-only | addressed | schema freeze |
| Receipt Ordering | linear monotonic model | partial order, rejected branch, out-of-order pending | addressed, review required | reordering crucible |
| Causal IDs | subject_message_id ambiguous | request_message_id + causation_message_id + message_id + receipt_id | addressed, review required | causal fixture |
| Receipt Replay | same vs new message unclear | same receipt replay identical; new stage new IDs | addressed, review required | duplicate fixture |
| Auth Failure | any reject could amplify | unauthenticated quarantine only; signed reject only after auth | addressed, review required | abuse test |
| Ledger Ownership | target/origin state mixed | separate Target-Ledger and Origin-Ledger | addressed, review required | crash/recovery test |
| Capability Status | implemented mixed code and production proof | declared/partially_wired/code_complete/crucible_verified/production_proven | addressed, review required | manifest test |
| Managed Task Completion | mapping not decided | ADR-03 required before Managed-Task-COMPLETED mapping | open | ADR-03 |
| Workflow Truth | GH006 masked by green run | ADR-05 required before production Crucible | open | ADR-05 |
| Status Adapters | no formal Managed/A2A/Sankalpa mapping | ADR-10 required before full integration | open | ADR-10 |
| Provider Exhaustion | ProviderChamber returns None/ERROR | outside isolated V1 unless provider-dependent handler | open | ADR-04 if scope expands |

Readiness verdict:

- Golden-Wire-Fixtures: BLOCKED until ADR-06 and all canonical/digest rules are accepted.
- Crucible-Design: BLOCKED until Partial Order, ledger ownership, replay and status query are accepted.
- Product implementation: BLOCKED.
- Phase 1 and Context Bridge: unchanged and protected.
