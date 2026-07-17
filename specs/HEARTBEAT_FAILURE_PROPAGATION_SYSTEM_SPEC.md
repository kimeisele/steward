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
| `heartbeat_failure_propagation_evidence/RECON_03_ADVERSARIAL.md` | Gegenbeweis-Versuch: Claim hält; Befund umgedreht — Erkennung vorhanden, Aussenverdrahtung fehlt; Fix-Richtung korrigiert (nicht `raise`) | EVIDENCE |
| `heartbeat_failure_propagation_evidence/RECON_04_PERSISTENCE_AND_EXTERNAL.md` | Kollaps-Zustand nur in-memory (über Runs blind); Push-Fehler geschluckt+ungezählt; konsolidierte Fehlerklassen-Matrix | EVIDENCE COMPLETE |

**Befund-Korrektur (RECON_03):** Der Kern ist nicht „der Heartbeat schluckt Fehler" (das
Schlucken ist plausibel bewusste Resilienz), sondern „eine bereits vorhandene Kollaps-
Erkennung (`vedana` Provider-Puls → `health_anomaly`) ist nur nach innen verdrahtet oder
verwaist". Zielrichtung: vorhandene Erkennung bei *anhaltendem* Kollaps nach außen sichtbar
machen — LOGGING zuerst, kein erzwungenes Rot vor Beobachtung.

## 5. NÄCHSTER GATE

**Recon abgeschlossen (RECON_01–04).** Die Fehlerklassen-Matrix ist vollständig belegt
(RECON_04 §5). Kein offener Recon-Punkt ist vor der Spec zwingend.

Feature-Spec liegt als **DRAFT 1.0 — bedingtes Go** vor:
`HEARTBEAT_FAILURE_PROPAGATION_FEATURE_01.md`. **Sieben** Review-Runden, keine offenen
Designfehler. Schnitt A misst Hard-Down, Degradation und Skip-Kollaps; §5.3 vollständig
definiert und **fail-laut** (Dekoder werfen bei `steward-protocol`-Form-Drift statt still
„gesund" zu lesen); §10.4a gepinnt (`vibe_core` via PyPI-Paket `steward-protocol`);
Per-Provider-Quota als toter Pfad aufgelöst; Membran-Skip bewusst nicht erfasst.
**Verbleibend vor formalem G1:** (i) Statusform-Gegenprüfung gegen die Produktions-
`steward-protocol`-Version als **erster Implementierungsschritt**; (ii) normales
Deployment-Gate. **Kein Produktcode ohne Operator-Go.**
