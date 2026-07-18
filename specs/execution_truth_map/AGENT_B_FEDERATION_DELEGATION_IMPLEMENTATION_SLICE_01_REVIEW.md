# Agent-B Implementation Review Packet — Federation Delegation V1 Slice 01

Status: `IMPLEMENTATION REVIEW REQUESTED`  
Scope: admission-only Federation Delegation V1 product slice  
Feature gate: `FEDERATION_V1_DELEGATION_ENABLED`, default `false`  
Merge: not performed  
Production activation: not performed

This packet is self-contained. It records the exact implementation pins, the
normative boundary implemented from Contract Draft 0.5 and the accepted Plan 01
Revision 0.2, the changed files, and the measured test/crucible evidence. It does
not rely on test fixtures or test builders being imported by product code.

## 1. Exact work and evidence pins

The implementation was performed on separate branches:

| Repository | Branch | Implementation commit(s) | Remote verification |
|---|---|---|---|
| `kimeisele/steward` | `impl/federation-delegation-slice-01` | `e83c919209c17dd1bf2377c811ce10e689078539` (`feat: add gated federation admission slice`) | `git ls-remote origin refs/heads/impl/federation-delegation-slice-01` returned the same SHA |
| `kimeisele/agent-city` | `impl/federation-delegation-slice-01` | `8c45791d9f8b3aa9edb4a5a446680ddaddd92bcc` (`feat: add gated federation admission slice`), followed by `58493604c545b23b3926d56d71b46afb0bd2fbe1` (`style: format federation admission adapter`) | remote branch returned `58493604c545b23b3926d56d71b46afb0bd2fbe1` |

Baseline and protocol pins used before implementation:

- Steward remote `main`: `706294571c765bfc5635af0721d11f55e920b635`.
- Steward accepted Plan 01 Revision 0.2 baseline: `4d2cd10f8b501629c4601dbcab65dde91f4121a2`.
- Agent City remote `main`: `e798bdbf7b3969beea577fe265657bbb7c142115`.
- Agent City Golden Wire 01A baseline: `bca0358191d52a04da1857ac313346c3e0f641fd`.
- Contract Draft 0.5: `ddf170d10a5d546af4b012a2d2335c37fcb44508`.
- Steward Protocol remote `main`: `34a8a0efc25c15ef7c07dd4fb50aeb2510c071e8`; its local checkout had unrelated pre-existing dirty changes and was not modified.

Heartbeat commits were excluded from all historical reasoning. Phase 1, Context
Bridge and the parked Context-Bridge PR were not edited or activated.

## 2. Exact changed files and diff boundary

### Steward (`e83c919209...`)

Only these four files were added:

- `steward/federation_v1.py` — repo-local production SFDJ-1 boundary, carrier validation, origin/target admission ledgers, signed admission receipt construction and ID-based correlation.
- `tests/test_federation_v1_admission.py` — product-boundary tests for accepted/rejected admission, persistence, replay, conflicts, crash gates, feature gate and carrier quarantine.
- `tests/test_federation_v1_cross_repo_crucible.py` — test-only loader for the separate Agent City checkout; no runtime import path.
- `docs/FEDERATION_DELEGATION_WIRING_MANIFEST_01.json` — machine-readable wiring and explicit legacy isolation.

### Agent City (`58493604...`)

Only these three tracked files were added/changed:

- `city/federation_v1.py` — independent repo-local implementation of the same V1 wire boundary and admission behavior; it does not import Steward.
- `tests/test_federation_v1_admission.py` — independent positive/negative and persistence tests.
- `docs/FEDERATION_DELEGATION_WIRING_MANIFEST_01.json` — Agent-City wiring status and legacy isolation.

The pre-existing untracked `agent-city/.claude/` directory was preserved and not
staged. No legacy `OP_DELEGATE_TASK` handler, title matching, worker/mission/tool
path, workflow, provider path, Context Bridge, Phase 1 file or Steward Protocol file
was changed.

## 3. Implemented slice and explicit non-goals

The implemented path is exactly:

`Steward V1 Origin -> closed exact request carrier -> Agent City V1 ingress -> SFDJ-1/provenance/signature/target/authority validation -> durable ACCEPTED or REJECTED admission record -> atomically persisted signed admission receipt -> closed receipt carrier -> Steward V1 receipt validation -> request-root/ID correlation`.

The slice deliberately stops before worker execution. It does not implement or
activate Started, Terminal or Verification receipts, Status Query, leases, recovery
automation, blind retry, managed-task completion, provider failover, automatic merge
authority or a universal Execution Spine.

## 4. Closed carriers and validation boundary

The request carrier is exactly:

```json
{
  "operation": "federation_v1.delegate_task",
  "source": "ag_<32 lowercase hex chars>",
  "target": "ag_<32 lowercase hex chars>",
  "payload": {
    "wire_version": "federation-delegation-v1",
    "wire_bytes_b64": "<RFC-4648 standard Base64 with required padding>"
  }
}
```

The receipt carrier has the same closed shape and uses
`operation: "federation_v1.delegation_receipt"`. Unknown top-level or payload
fields, wildcard/broadcast targets, a wrong wire version, URL-safe or malformed
Base64, carrier/inner source or target mismatch, and carrier/inner operation mismatch
are rejected locally. No network response is produced for these failures.

For a carrier that passes the carrier boundary, the inner SFDJ-1 envelope is checked
in this order: closed field set, contract/operation, node-ID and ID syntax, exact
target, RFC-3339 UTC window, signer/key registry binding and revocation, envelope
hash, domain-separated Ed25519 signature, then request or receipt payload schema and
content digest. Invalid, unauthenticated, wrong-target, missing-provenance and
unauthorized-protocol inputs fail closed with local quarantine/finding only.

The V1 domain-separated signature input is the frozen Contract Draft 0.5 input:

`UTF-8("STEWARD-FEDERATION-DELEGATION-V1") || 0x00 || hex-decoded message_hash`.

The message hash is SHA-256 over the canonical SFDJ-1 envelope body excluding
`message_hash` and `signature`. Request semantic binding is SHA-256 over the closed
delegation semantic fields; the payload carries `request_digest` and the derived
`idempotency_key = "fedv1:" + request_digest`.

## 5. Target admission ledger and atomicity

`TargetAdmissionLedger.commit` is the single atomic replacement of the target JSON
ledger. Before the replacement, the complete receipt wire is deterministically built
and signed. For both ACCEPTED and authenticated, authorized REJECTED admission, the
same commit persists all of the following:

- `delegation_id`
- `request_message_id` and separate `request_message_hash`
- `origin_node_id` and `target_node_id`
- `request_digest` and `idempotency_key`
- immutable signed request wire bytes (`request_wire_bytes_b64`)
- the exact request carrier object
- `state` (`ACCEPTED` or `REJECTED`)
- `reason_code` (null for accepted)
- `target_work_id` (present exactly once for accepted, null for rejected)
- receipt envelope `message_id`, business `receipt_id`, `receipt_content_digest`, `message_hash`, signature and complete signed `receipt_wire_bytes_b64`
- `receipt_send_status`, initially `pending`

The atomic writer uses a same-directory temporary file, flush/fsync and `os.replace`.
The transport caller may mark the persisted receipt `sent` with
`mark_receipt_sent`; no new receipt is generated for a crash after the commit and
before transport.

For ACCEPTED, `target_work_id` is deterministic in this admission-only slice:
`work_` plus the first 32 hex characters of SHA-256 of
`delegation_id || target_node_id`. This identifier represents an admitted work
record only; no worker or tool is started.

For REJECTED, `target_work_id` is obligatorily null. The rejection reason is durable
and the exact signed reject receipt is replayed on an identical request. A request
with the same `delegation_id` but another `request_digest` is
`duplicate_conflict`/quarantine and does not create a second decision.

## 6. Origin ledger and correlation

`OriginDelegationLedger.create_request` stores the complete signed request wire and
carrier before sending, along with distinct `request_message_id`,
`request_message_hash`, `request_digest`, `idempotency_key`, `origin_task_id`,
`correlation_id`, target and send status. `FederationV1Origin.retransmit` returns
those stored carrier bytes; it does not regenerate timestamps, IDs or signatures.

`FederationV1Origin.apply_receipt` validates the closed receipt carrier and target
signature, then correlates only by:

- receipt payload `delegation_id`,
- receipt `request_message_id` equal to the first request root,
- receipt status and receipt IDs/digests.

There is no title or substring matching. The first accepted receipt sets
`target_work_id` exactly once. An identical duplicate must match the stored receipt
ID, content digest, target work ID and complete receipt bytes. A different work ID,
receipt content or receipt bytes is a durable correlation conflict and does not
overwrite the origin ledger. A rejected receipt never sets `target_work_id`.

## 7. Authority and feature gate

The adapter is additive and default-disabled (`enabled=False` in both repo-local
constructors; the manifest records the same gate). Tests explicitly opt in with
`enabled=True`. With the gate disabled, origin creation fails with
`feature_disabled` and target ingress returns no response.

After cryptographic authentication and registry binding, an admission may produce a
signed `admission=rejected` receipt only for a basic protocol-authorized denial. The
implemented fixture policy requires the V1 `fix_repository` capability, target repo
`agent-city`, matching authority repo scope, allowed actions limited to
`branch/commit/read/test`, and `merge` explicitly denied. A caller-level
`origin_authorized=False` produces a durable `authority_denied` receipt; an unavailable
capability produces `capability_unavailable`. Invalid signature, missing provenance,
wrong target or malformed carrier never reaches this response path.

## 8. Measured validation

All commands below were run after the final local implementation changes. Each suite
emitted one unrelated existing `DeprecationWarning` from
`steward-protocol/vibe_core/mahamantra/adapters/moltbook.py`; no test failed.

| Repository / command | Result |
|---|---:|
| Steward: `pytest -q tests/test_federation_v1_admission.py tests/federation_v1` | **52 passed** |
| Agent City: `pytest -q tests/test_federation_v1_admission.py tests/federation_v1` | **52 passed** |
| Steward legacy regression: `pytest -q tests/test_federation_gateway.py tests/test_federation_quarantine.py` | **61 passed** |
| Agent City federation regression: `pytest -q tests/test_federation_v1_admission.py tests/federation_v1 tests/test_federation_nadi.py tests/test_federation_relay.py` | **142 passed** |
| Steward admission-only cross-repo crucible with `AGENT_CITY_REPO=/Users/ss/projects/agent-city`: `pytest -q tests/test_federation_v1_cross_repo_crucible.py` | **1 passed** |
| Steward static checks: `ruff check steward/federation_v1.py tests/test_federation_v1_admission.py tests/test_federation_v1_cross_repo_crucible.py`; `python -m py_compile steward/federation_v1.py` | **clean / pass** |
| Agent City static checks: `ruff check city/federation_v1.py tests/test_federation_v1_admission.py`; `python -m py_compile city/federation_v1.py` | **clean / pass** |

The cross-repo test independently loads Agent City's production adapter from the
separate checkout. It regenerates the fixture request from semantic input, asserts
byte equality with the frozen request, validates it at Agent City, applies the signed
admission receipt in Steward, and proves an identical replay returns the same receipt
carrier and `target_work_id`.

The admission test matrix additionally covers: crash before commit (no ledger,
work ID or receipt), crash after commit (same stored receipt on replay), durable and
idempotent REJECTED admission, source/target/operation carrier mutations, unknown
carrier fields, wrong version, invalid Base64, wildcard target, same delegation with
different digest, same message ID with different bytes, first-set work ID and
conflicting duplicate work ID, and default-disabled feature gating.

## 9. Wiring and rollout state

`docs/FEDERATION_DELEGATION_WIRING_MANIFEST_01.json` in both repositories records:

- `delegate_task`: Steward emitter, closed carrier, Agent-City ingress, authority gate, target admission ledger, authenticated reject/accepted receipt operation, and the cross-repo test.
- `delegation_receipt`: Agent-City emitter, closed receipt carrier, Steward origin validator, first-set correlation and duplicate/conflict store.
- `delegation_status_query` and `delegation_status`: `declared`, `unavailable`, not implemented in this slice.
- legacy `OP_DELEGATE_TASK`, title matching, worker execution and fallback: all false.
- lifecycle maturity for the two implemented directions: `crucible_verified`; disposition: `disabled`.

No production network caller is connected by this slice. The only exercised transport
is the explicit test crucible. A merge or activation would therefore be a separate
review and gate, not an implied consequence of these commits.

## 10. Agent-B decision request

Please review the exact remote commits above and decide whether Slice 01 is accepted
for the next gate. In particular:

1. Does the target commit persist the full request, ledger state and complete signed
   receipt bytes atomically for both ACCEPTED and REJECTED outcomes?
2. Are identical replays guaranteed to retransmit stored bytes, while digest,
   message-ID, receipt-ID, wire-byte and target-work conflicts fail closed?
3. Are carrier and inner-envelope source/target/operation bindings closed with no
   unauthenticated network response or legacy fallback?
4. Is the origin correlation demonstrably root-/ID-based and free of title matching?
5. Is the default-disabled feature gate and the absence of any production activation
   sufficient for this milestone?
6. Do the independent Agent City builder/validator and the cross-repo crucible prove
   the intended admission-only parity without a shared runtime library?
7. Are the changed files and test evidence confined to Implementation Slice 01, with
   worker execution, recovery, status query, verification, workflow completion,
   Provider Failover, Context Bridge and Execution Spine still excluded?

Requested decision: `ACCEPTED FOR ADMISSION-ONLY CRUCIBLE/REVIEW` or a precise blocking
finding. No product scope beyond this packet is requested.
