# ADR-07 — CAPABILITY-WIRING-DEFINITION

> **Status:** AMENDED — SPRINT 1C REVISION IN `ADR_DECISION_SPRINT_1C_REVISION.md`
> **Hinweis:** Der folgende Sprint-1-Text ist historische Begründung; die neuen Statusstufen
> stehen in der Sprint-1B-Revision.
> **Datum:** 2026-07-18
> **Entscheider:** Codebase-Agent, zur Review durch Agent B
> **Geltungsbereich:** Nachweis, wann eine Federation-Operation als implementiert gelten darf

## Entscheidung

Eine Federation-Capability gilt erst dann als `implemented`, wenn ein maschinenlesbares
Wiring-Manifest alle folgenden Kanten nachweist:

```text
operation/version
→ direction
→ schema + canonical bytes
→ emitter
→ outbound transport
→ exact target matcher
→ inbound membrane
→ authority/trust gate
→ concrete handler
→ durable state transition
→ result/receipt operation
→ origin correlation
→ positive + adversarial E2E test
```

Das Manifest ist ein Prüfvertrag, kein neuer Runtime-Super-Agent. Fehlende Kanten sind
`unavailable` oder `partial`, niemals `implemented`. `ALL_OPERATIONS` allein ist keine
Implementierungsbehauptung.

### Mindestfelder je Manifest-Eintrag

| Feld | Bedeutung |
|---|---|
| `operation` / `contract_version` | kanonische Wire-Identität |
| `direction` | `outbound`, `inbound` oder `bidirectional` |
| `schema` | Pflichtfelder, Limits und Version |
| `emitter` | Symbol/Test, das die Operation erzeugt |
| `transport` | konkreter Transport und Delivery-Grenze |
| `targeting` | exakte Target-Prüfung |
| `authority_gate` | Trust, Key und erlaubte Aktionen |
| `handler` | konkrete Empfangsfunktion |
| `state_transition` | persistenter Vor-/Nachzustand |
| `result_operations` | Admission/Failure/Terminal/Receipt-Ausgänge |
| `correlation` | IDs und Kardinalitätsregeln gemäß ADR-02 |
| `tests` | positive, negative und repoübergreifende Tests |
| `status` | `implemented`, `partial`, `unavailable`, `legacy` |

## Live-Code-Befund

- `steward/federation.py:ALL_OPERATIONS` deklariert 24 Operationen.
- `FederationBridge.__post_init__` registriert nur 15 Inbound-Handler.
- `OP_DELEGATE_TASK` hat einen Steward-Handler, aber keinen Agent-City-Handler am Live-Pin.
- `FederationNadiHook` in Agent City nimmt Operationen generisch auf; `Dharma.execute`
  konsumiert die Federation-Surface anschließend auch für unbekannte Operationen.
- `DelegateTool.execute` emittiert `target_agent`, aber der Steward-Bridge-Outbound
  expandiert an alle alive/suspect Peers.
- `tests/test_federation.py` und Agent-City-Unit-Tests beweisen lokale Teilpfade, aber
  kein reales Steward→Agent-City-Delegate-Crucible.
- Die vier PR-Verdict-E2E-Tests scheitern am Signaturvertrag, obwohl lokale Handler existieren.

Live-Pins: Steward `110b933231ebdcd3fc43c04ee30afe5df88be5130`, Agent City
`e798bdbf7b3969beea577fe265657bbb7c142115`.

## Optionen

### Option A — Deklarationsliste als Implementierungsnachweis

`ALL_OPERATIONS` und ein lokaler Handler gelten als ausreichend.

Vorteile:

- minimale Prozessänderung,
- bestehende Tests bleiben grün.

Nachteile:

- Sender ohne Empfänger gelten fälschlich als fertig,
- Targeting, Authority, Resultat und Tests werden nicht geprüft,
- genau der `delegate_task`-Riss bleibt unsichtbar,
- Migration und Recovery besitzen keinen gemeinsamen Nachweis.

### Option B — vollständiges Wiring-Manifest mit CI-Gate (gewählt)

Jede Capability muss alle Kanten und Tests nachweisen; fehlende Kanten verhindern den
Status `implemented`.

Vorteile:

- „gebaut, nicht verdrahtet“ wird maschinenlesbar sichtbar,
- Cross-Repo-Verantwortung wird explizit,
- Authority und Resultatpfad werden nicht implizit angenommen,
- der Crucible kann aus dem Manifest abgeleitet werden.

Kosten:

- Manifestpflege und CI-Validierung,
- Legacy-Operationen müssen als `legacy`/`partial` markiert werden,
- echte repoübergreifende Fixtures sind teurer als lokale Unit-Tests.

## Auswirkungen

- **Steward:** Operationen brauchen Richtung, Targeting, Handler- und Resultatnachweis;
  `ALL_OPERATIONS` muss von Status-/Manifestdaten getrennt werden.
- **Agent City:** Jede inbound Operation benötigt einen konkreten Handler oder eine
  explizite Rejection; generisches Queue-Konsumieren ist kein Handler.
- **Steward Protocol:** Schema-/Envelope-Version und Serialisierung müssen als Manifest-
  Kante testbar sein.
- **Migration:** Bestehende Operationen werden zunächst inventarisiert und als `partial`
  oder `legacy` geführt; kein stilles Umdeklarieren.
- **Recovery:** Manifest muss den persistenten State-Owner und Recovery-Transition nennen;
  ein Handler ohne Recovery ist nicht vollständig.
- **Authority:** Sender-Key, Trust-Floor, Target und erlaubte Wirkung werden je Operation
  ausgewiesen; Transport allein gilt nicht als Autorisierung.
- **Tests:** lokale Emitter-/Handler-Tests plus Cross-Repo-Golden-Wire- und adversarial
  Tests; ein fehlender Test hält den Status unter `implemented`.

## Adversariales Gegenargument

Ein vollständiges Manifest könnte zu einem schwer wartbaren zweiten SSOT werden. Das Risiko
ist real. Deshalb beschreibt das Manifest nur überprüfbare Wiring-Kanten und verweist auf
Code-/Schema-Symbole; es dupliziert keine Businesslogik. Ohne diese minimale Projektion ist
aber nicht feststellbar, ob eine deklarierte Operation wie `delegate_task` überhaupt einen
Empfänger besitzt.

## Review-/Implementierungsreife

**Entscheidung:** ACCEPTED als Governance-/CI-Gate. Die konkrete Manifestdatei und der
Auditor sind noch nicht Produktcode und werden erst nach Contract-Freeze spezifiziert.

## Sprint-1C-Amendment

Lifecycle-Reife und Disposition werden getrennt geführt. Reife:
`declared`, `partially_wired`, `code_complete`, `crucible_verified`, `production_proven`.
Disposition: `active`, `unavailable`, `legacy`, `disabled`. `implemented` ist kein
Draft-0.4-Status. Der Manifest-Key enthält mindestens Operation, Version, Repository,
Richtung und Target. `active` verlangt im Testprofil mindestens `crucible_verified` und im
Produktionsprofil `production_proven`. `delegation_status_query` und `delegation_status`
sind selbst Manifest-Einträge mit Read-only-Authority, exaktem Target, Snapshot-Handler,
Replay-/Rate-Limit-Tests und Produktions-Evidence.
