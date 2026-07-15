# FEATURE 04 — G1-SCHLUSSPRÜFUNG

> **Status:** G1 APPROVED — ausschließlich G2-Pre-Flight für die reine Feature-04-Bibliothek autorisiert
> **Prüfdatum:** 2026-07-15
> **Produktionsbasis:** `kimeisele/steward@327eca2f8bf275563c5940ba807996b52ca44fa3`
> **Produktions-Tree:** `042d35690cd4251fff978d17a0c8d8f3dc5b19a6`
> **Review-Branch:** `spec/context-bridge-feature-04`
> **Scope:** `specs/CONTEXT_BRIDGE_FEATURE_04.md` und
> `specs/context_bridge_evidence/FEATURE_04_HASH_VECTORS.json`

---

## 1. Urteil

Feature-Spec 04 ist als reiner Modell-, Normalisierungs-, Hash- und Vergleichsvertrag
G1-freigegeben.

Die Freigabe autorisiert nur den nächsten G2-Pre-Flight. Sie autorisiert noch keine
Implementierung und insbesondere keinen Publisher, Root-Write, Workflow-, Heartbeat-,
LLM-, Source-Migrations- oder Governance-Patch.

---

## 2. Geprüfte Verträge

- C0-/Orientation-Markerparser und Fail-closed-Grenzen,
- PUBLIC_SAFE und T0–T5-Default-Deny,
- SourceResult- und SourceSnapshot-Vokabulare,
- Snapshot-, Payload- und Consumer-Output-Hash-Domains,
- floatfreies kanonisches JSON,
- C0-Review-Attestation,
- semantische C0–C4-Trigger,
- expliziter PreviousPublishedRecord und Vergleichsstate,
- Bootstrap-, No-op-, Degradation- und Safe-Fallback-Semantik,
- rote Regressionen und adversariale Fixtures,
- vollständige feste Hash-Testvektoren.

---

## 3. Materielle Review-Funde und Korrekturen

### 3.1 Vedana-Komponentensemantik

Der erste Draft behandelte `error_pressure` und `context_pressure` als direkte Pressure-
Skalen. Live-Code beweist das Gegenteil: `measure_vedana()` invertiert beide Werte;
`1.0` ist gesund. Gleichzeitig liest `compute_focus()` mindestens `context_pressure`
gegenteilig.

**Korrektur:** Beide Rohfelder bleiben in V1 default-deny. Die Spec dokumentiert den
Live-Mismatch; sie erfindet keine neuen Schwellen und zieht keine Caller-Reparatur in
Feature 04.

### 3.2 Nicht teilnehmende Quellen

Der erste Draft wollte jeden Source-Status in den Payload-Core aufnehmen. Damit hätten
Sessionrotation oder Issue-Verfügbarkeit einen Root-Diff erzeugt, obwohl ihre Inhalte in
V1 ausgeschlossen sind.

**Korrektur:** Alle Quellen bleiben im diagnostischen Snapshot. Nur elf tatsächlich
teilnehmende V1-Quellen erscheinen im SemanticPayloadCore. Tasks, Issues, Sessions,
Architecture, Annotations und Continuity warten auf Feature 02/03 oder ein späteres
reviewtes Schema.

### 3.3 Kumulative Safety-Zähler

Gateway-Error-/Reject- und Immune-Rollback-Zähler sind kumulativ. Ein einfacher Test
`count > 0` würde nach dem ersten Ereignis dauerhaft Alarm oder nach Prozessreset falsch
`clear` erzeugen.

**Korrektur:** Ein expliziter ComparisonState wird als C4-Snapshot-/Recordstate geführt.
Nur Deltas erzeugen Events; sinkende Counts ohne Reset-Provenance sind invalid. Der Kern
bleibt rein, weil der frühere State expliziter Input ist.

### 3.4 C0-Autorität

Ein passender C0-Hash beweist noch keinen menschlichen Review.

**Korrektur:** Der Bootstrap benötigt eine passende `ConstitutionAttestation` mit
Source-Blob, Review-Commit und Status `verified`. Feature 04 validiert nur Form und
Bindung; die spätere Governance-Verifikation bleibt Feature 01.

### 3.5 Hash-Reproduzierbarkeit

Prosa über SHA-256 genügt nicht als sprachübergreifender Vertrag.

**Korrektur:** Vollständige Minimalmodelle, kanonische Bytes und volle erwartete Hashes
liegen maschinenlesbar in `FEATURE_04_HASH_VECTORS.json`. Python-Standardbibliothek und
eine getrennte `jq -cS -j` plus `shasum -a 256`-Pipeline erzeugten identische Werte.

---

## 4. Mechanische Prüfung

| Prüfung | Ergebnis |
|---|---|
| Spec-Diff whitespace-valid | PASS |
| JSON-Testvektor parsebar | PASS |
| Snapshot-Source-IDs sortiert/eindeutig, Anzahl 17 | PASS |
| Payload-Source-IDs sortiert/eindeutig, Anzahl 11 | PASS |
| C0-Testhash intern konsistent | PASS |
| Canonical-JSON-Bytes stimmen | PASS |
| Snapshot-Hash Python | `999ba49ddaea6300f3398159103491915a9b5ce3b7871a9cbd2f7b20b761ceba` |
| Snapshot-Hash jq/shasum | identisch |
| Payload-Hash Python | `d3a344af1700b88346695e13833ec5d6f81b66584ef8272542c64f7d4aa4d71a` |
| Payload-Hash jq/shasum | identisch |
| Produktcode-/Test-/Workflow-Dateien geändert | NEIN |

---

## 5. G1-Grenze

G1 bestätigt den Vertrag, nicht seine produktive Integration.

Der nächste Arbeitsgang darf ausschließlich:

1. aktuellen `origin/main` und Tree neu pinnen,
2. die vorgesehenen reinen Modul-/Testpfade bestätigen,
3. rote Tests zuerst definieren,
4. einen ausdrücklichen G2-Startentscheid dokumentieren,
5. danach nur die reine Feature-04-Bibliotheksfläche implementieren.

Nicht autorisiert bleiben:

- `CLAUDE.md` oder `AGENTS.md` schreiben,
- `.steward/conventions.md` migrieren,
- `briefing.py`, Hook-, CLI-, Intent- oder Workflow-Caller umleiten,
- `.context_hash` ersetzen oder löschen,
- LLM-Publisher verändern,
- GitHub-Governance aktivieren,
- Feature 01, 02 oder 03 vorziehen.

---

## 6. Schlussstatus

Feature 04 G1 ist geschlossen. Implementation bleibt bis zum separaten, aktuellen
G2-Pre-Flight gesperrt.
