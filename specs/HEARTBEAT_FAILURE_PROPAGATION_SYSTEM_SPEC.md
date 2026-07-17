# HEARTBEAT-FEHLERPROPAGATION — MASTER-SYSTEMSPEZIFIKATION

> **Status:** DRAFT 0.1 — RECON-PHASE; NOCH KEINE FEATURE-SPEC; IMPLEMENTIERUNG UND
> AKTIVIERUNG GESPERRT
> **Datum:** 2026-07-17
> **Produktionsbasis:** `kimeisele/steward@bf2fba2075a87463fc8e333f8f57d805fce4d030`
> **Plan-Herkunft:** Phase-2 `docs/PHASE2_CURRENT.md` §7.3 (Heartbeat-Fehlerpropagation)
> **Sperre:** Aus diesem Dokument darf noch kein Produktivpatch abgeleitet werden. Erst nach
> abgeschlossenem Recon und separat reviewter Feature-Spec wird ein kleinster Root-Cause-
> Patch autorisiert.

---

## 0. WARUM DIESE BAUSTELLE EXISTIERT

Der Steward-Heartbeat ist das zentrale Lebens- und Gesundheitssignal der Föderation. Ein
grüner Heartbeat-Run wird — von Menschen wie von Folgeagenten — als „das Fundament ist
gesund" gelesen.

Der Recon (siehe `heartbeat_failure_propagation_evidence/RECON_01_SWALLOW_PATHS.md`) belegt
am Code: **der Heartbeat-Run ist strukturell unfähig, an kognitivem, Hook- oder
Provider-Versagen rot zu werden.** Vier unabhängige `try/except`-Schichten fangen jeden
Fehler ab, loggen ihn (teils unterhalb der sichtbaren Log-Schwelle) und lassen den Prozess
mit Exit 0 enden.

Konsequenz: Das grüne Signal ist als Gesundheitsaussage über die Kognition **wertlos**. Das
ist exakt Phase-1 §220.3 (*„Ein leeres Log sieht aus wie Erfolg. Verifizieren am
Produktionslog, nie am grünen Test."*) — nur strukturell verankert. Die Erkennung existiert
(Log-Zeilen); die **Verdrahtung zum Run-Status fehlt** (klassisch: gebaut, nicht verkabelt).

Diese Grenze ist sicherheitskritisch, weil die gesamte Beweisdisziplin des Projekts —
jeder „Produktionsrun grün"-Nachweis — auf einem Signal ruht, das aktuell lügen kann.

## 0A. LEITPLANKEN (nicht verhandelbar)

- Die Föderation läuft durch dieses Gate. **Erst LOGGING-/Beobachtungsmodus, dann
  erzwingen** (Phase-1 §220). Kein blindes `raise`, das ein transienter Provider-429 zum
  Föderations-Stillstand eskalieren lässt.
- Kein Rewrite, kein zweiter paralleler Heartbeat, kein monolithischer PR, keine
  Implementierung aus Chat-Prosa, keine Freigabe ohne Produktionslog-Beweis.
- Nur der Code zählt, nicht Kommentare oder `CLAUDE.md` (Phase-1 §220.3).
- Verifiziert wird am **Produktionslog**, nicht am grünen Test.

## 1. ZWECK (Zielrichtung, noch nicht Vertrag)

Fehlerklassen des Heartbeats trennen, statt sie pauschal zu schlucken:

- **kritisch** → muss den Run rot machen (z. B. Total-Provider-Kollaps über einen ganzen
  Zyklus, Bootstrap-/Identitätsfehler);
- **degradierbar** → toleriert, aber sichtbar und gezählt (z. B. ein transienter
  Provider-Ausfall mit erfolgreichem Fallback);
- **extern / Post-Action** → toleriert und getrennt geführt (z. B. entfernte Zustellung).

Die konkrete Zuordnung wird **nicht hier**, sondern erst nach vollständigem Recon in einer
eigenen Feature-Spec festgelegt.

## 2. SCOPE / NICHT-SCOPE (vorläufig)

**In Scope:** die vier belegten Schluck-Schichten im Heartbeat-Pfad (Provider-Kaskade,
Hook-Dispatch, Workflow-Harness, interner Phasen-Dispatcher) und ihre Verdrahtung zum
Run-Exit-Status.

**Nicht in Scope (getrennte Baustellen):** die Context-Bridge (eigener Agent, eigene
Ordner `CONTEXT_BRIDGE_*` / `context_bridge_evidence/`), Identitäts-Rename, Key-Rotation,
Quarantäne-Cleanup. Kein Sammelpatch.

## 3. ISOLATION (gegen Parallel-Agenten-Merge-Konflikte)

Diese Baustelle lebt **ausschließlich** in:
- `specs/HEARTBEAT_FAILURE_PROPAGATION_SYSTEM_SPEC.md` (dieses Dokument)
- `specs/heartbeat_failure_propagation_evidence/**`

Sie schreibt **nicht** in `docs/PHASE2_BEFUND.md`, `docs/PHASE2_CURRENT.md` oder in
`context_bridge_*`-Pfade. Dadurch entstehen keine Merge-Kollisionen mit anderen Agenten.

## 4. EVIDENZ-INDEX

| Dok | Inhalt | Status |
|---|---|---|
| `heartbeat_failure_propagation_evidence/RECON_01_SWALLOW_PATHS.md` | Die vier Schluck-Schichten, am Code belegt | RECON — teils offen |
| `heartbeat_failure_propagation_evidence/RECON_02_CONSUMPTION_AND_CLASSES.md` | None-Konsum (Event, nicht verkabelt), bestehende Fehlerklassifikation, Andockpunkt `health_anomaly` | RECON — teils offen |

## 5. NÄCHSTER GATE

Recon fortsetzen (offene Punkte in RECON_01 §8), bis die Fehlerklassen-Matrix vollständig
belegt ist. Erst danach: separate Feature-Spec, dann kleinster Patch im LOGGING-Modus.
