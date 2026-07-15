# FEATURE 00 — G1-SCHLUSSPRÜFUNG

> **Status:** G1 APPROVED — nur Feature-Spec 04 als nächster Schritt autorisiert
> **Prüfdatum:** 2026-07-15
> **Produktionsbasis:** `kimeisele/steward@c7230dde128dbe6db20d3b144da5403988195154`
> **Review-Branch:** `spec/context-bridge-feature-00`
> **Initialer Draft-Commit:** `18ab1bc8ee8e8595215551153b1b144251156291`
> **Scope:** `specs/CONTEXT_BRIDGE_FEATURE_00.md`. Keine Produktcode-, Test-, Workflow-,
> Root-Datei-, Constitution-, GitHub-Setting- oder Produktionsänderung.

---

## 1. Urteil

Feature-Spec 00 besteht Gate G1.

Die Freigabe autorisiert ausschließlich:

> Feature-Spec 04 für kanonisches Modell, Normalisierung, Markerparser,
> PUBLIC_SAFE-Validierung, Hash-Domains und rote Contract-Tests auszuarbeiten.

Sie autorisiert keine Implementierung. Feature 00 besitzt absichtlich kein eigenes
Implementierungs-G2.

---

## 2. Geprüfter Vertrag

Der Review prüfte:

- den exakten C0-v1-Wortlaut,
- Consumer-/Runtime-/Operator-/Projektrollen,
- T0-T5-Trust-Zonen,
- C0-/Dynamic-/Orientation-Marker,
- Source-Größen-, Encoding- und Fail-closed-Regeln,
- Safe Fallback ohne zweite Constitution-Wahrheit,
- PUBLIC_SAFE-Basistypen und initiales Freitext-Default-Deny,
- Claude-/Codex-Discovery und Bytegleichheits-Default,
- Required-Contract-Check,
- CODEOWNERS-, Branchschutz- und Zwei-Principal-Zielvertrag,
- rote und adversariale Tests,
- Nicht-Scope und Feature-Reihenfolge.

---

## 3. Gefundene und behobene Reviewpunkte

### R1 — Source-Trust-Matrix fehlte

Der erste Draft enthielt Rollen und Default-Deny, aber keine explizite T0-T5-Matrix.

**Korrektur:** Normative Zonen T0 bis T5 wurden mit erlaubter und verbotener Wirkung
ergänzt. Signatur, Öffentlichkeit oder Wiederholung erhöhen Trust nicht automatisch.

### R2 — Discovery und Basistypvalidierung waren zu implizit

Der Draft erklärte Byteidentität, schrieb aber die belegten Claude-/Codex-Discovery-
Verträge und geschlossenen dynamischen Basistypen nicht vollständig aus.

**Korrektur:** Root-Discovery, Scope, Priorität, No-Include-Vertrag sowie Enum-, Count-,
Path-, Hash-, ID-, Zeit- und Unicode-Regeln wurden normativ ergänzt.

### R3 — Evidence-Traceability war nicht explizit

Die Regeln waren inhaltlich aus G0 abgeleitet, aber OQ-07 bis OQ-18 waren nicht direkt
auf die jeweiligen Feature-00-Verträge gemappt.

**Korrektur:** Eine normative Evidence-Tabelle verlinkt Governance, Rollen, Consumer,
PUBLIC_SAFE, Source-Status, Veröffentlichung und Constitution auf ihre Primärpakete.

Nach diesen Korrekturen blieb kein G1-Blocker offen.

---

## 4. Mechanische Prüfungen

| Prüfung | Ergebnis |
|---|---|
| C0-v1 extrahierbar | PASS |
| C0-Größe | PASS — 1.860 UTF-8-Bytes, unter 4.096 |
| C0 ohne `You are Steward`/`Your North Star` | PASS |
| C0 ohne Owner-, Live-Identity-, Peer- oder Frequenzwerte | PASS |
| Phase-1-read-only vorhanden | PASS |
| Phase-2 als advisory/falsifiable markiert | PASS |
| Operatorauftrag außerhalb Bridge-Autorität | PASS |
| T0-T5 vollständig | PASS |
| Consumer-Discovery explizit | PASS |
| dynamische Basistypen geschlossen | PASS |
| Free-form T3/T4/T5 initial default-deny | PASS |
| Safe Fallback ohne zweite manuelle Source | PASS |
| Required Check darf nicht skippen | PASS |
| Byteidentität bleibt Default | PASS |
| Implementierungssperre mehrfach explizit | PASS |
| `git diff --check` | PASS |

---

## 5. Bewusst spätere Entscheidungen

Diese Punkte sind keine Feature-00-Lücken:

- konkrete Python-Typen und Parser-API,
- kanonische Serialisierung und Hash-Testvektoren,
- Validator-Modul- und Fixture-Pfade,
- Lock-, Manifest-, Recovery- und Dual-Publisher-Implementierung,
- tatsächliche menschliche Code-Owner-Identität,
- konkrete Workflow-/Branch-/Auto-Merge-Aktivierung,
- Operations- und Produktionsdrill.

Sie gehören entsprechend der verbindlichen Reihenfolge in Feature 04 beziehungsweise
Feature 01 und benötigen eigene G1-/G2-Gates.

---

## 6. Merge- und Folgevertrag

Der Feature-00-PR darf erst nach grüner bestehender CI und erneutem Diff-Scope-Check
gemerged werden. Der Merge verändert nur Spec-/Evidence-Dokumentation.

Nach Merge gilt:

1. keine Implementierung beginnen,
2. frischen Live-Head pinnen,
3. ausschließlich Feature-Spec 04 erstellen,
4. keine Source-, Root-, Workflow- oder Testdatei berühren.
