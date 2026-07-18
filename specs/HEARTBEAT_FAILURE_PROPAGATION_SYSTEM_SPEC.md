# HEARTBEAT-FEHLERPROPAGATION — MASTER-SYSTEMSPEZIFIKATION

> **Status:** RECONCILED 1.0 — RECON ABGESCHLOSSEN; FEATURE 01 SCHNITT A IMPLEMENTIERT
> UND PRODUKTIV SICHTBAR; SCHNITT B/C NICHT FREIGEGEBEN
> **Datum:** 2026-07-18
> **Aktuelle Produktionsbasis:**
> `kimeisele/steward@24f86ec0749a1eff919921a947189ee5c459a4c8`
> **Historische Recon-Basis:**
> `kimeisele/steward@bf2fba2075a87463fc8e333f8f57d805fce4d030`
> **Plan-Herkunft:** Phase-2 `docs/PHASE2_CURRENT.md` §7.3 (Heartbeat-Fehlerpropagation)
> **Sperre:** Schnitt A ist historische, gemergte Realität und kein neuer Auftrag. Schnitt B
> (Eskalation) und C (Run-rot) bleiben bis zu eigenen Specs, Produktionsdaten und explizitem
> Operator-Go gesperrt. Keine weitere Implementierung aus diesem Masterdokument ableiten.

---

## 0R. AUTORITATIVE RECONCILIATION (2026-07-18)

Dieser Abschnitt ersetzt die frühere Kopfzeilenbehauptung „noch keine Feature-Spec oder
Implementierung". Die darunter erhaltene Recon-/Review-Prosa bleibt historische Evidence.

### Tatsächlicher Lieferstand

| Gegenstand | Stand | Beleg |
|---|---|---|
| RECON_01–04 | abgeschlossen | `specs/heartbeat_failure_propagation_evidence/` |
| Feature 01 Schnitt A | implementiert | Commits `71a207e39efa84396b8f030a58a66b7abd77b513`, `899135cee8af79efa74139fc10da7e015508eef0` |
| Merge | auf `main` | PR `#759`, Merge `281c7112bb90d0fe1440d25bf8229dfe12980f17` |
| Direkte Tests | grün | `pytest -q tests/test_moksha_health.py` → `17 passed` am aktuellen Recon-Pin |
| Produktionsartefakt | vorhanden | `.steward/federation_health.json:cognition` am Live-Pin |
| Schnitt B | nicht implementiert | eigenes G2-/Operator-Gate erforderlich |
| Schnitt C | gesperrt | A-Daten, Schwelle, atomares Persistenzfundament, Kill-Switch und Operator-Go fehlen |

### Aktueller Produktionszustand

Am Live-Pin sind drei Provider alive und usable. `hard_down`, `degraded` und
`skip_collapse` sind `false`, `decode_error` ist `null`, der persistierte Streak ist `0`.
Schnitt A beobachtet damit produktiv, ändert aber weiterhin keinen Kontrollfluss und keinen
Workflow-Exit.

Das übergeordnete Problem ist nicht geschlossen: Agent City Run `29644618328` endete am
selben Tag grün, obwohl der State-Push mit `GH006 Protected branch update failed` scheiterte.
Das ist ein separater, live belegter Fehlerkanal. Schnitt A misst Provider-/Kognitionszustand;
es behauptet keine allgemeine Workflow-Wahrheit.

Vollständiger aktueller Recon:
`specs/execution_truth_map/EXECUTION_TRUTH_MAP_RECON.md`.

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

## 3. HISTORISCHE ISOLATION UND HEUTIGE DOKUMENTROLLE

Während Recon und Schnitt-A-Entwicklung lebte diese Baustelle **ausschließlich** in:
- `specs/HEARTBEAT_FAILURE_PROPAGATION_SYSTEM_SPEC.md` (dieses Dokument)
- `specs/heartbeat_failure_propagation_evidence/**`

Die damalige Parallelitätsregel untersagte Phase-2-Schreibzugriffe. Sie ist für den
akzeptierten Dokumentationsmilestone vom 2026-07-18 superseded: `docs/PHASE2_BEFUND.md`
erhält nun ausdrücklich nur die kompakte autoritative Zusammenfassung. Context-Bridge-
Pfade und `docs/PHASE2_CURRENT.md` bleiben unberührt.

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

## 5. GATE-STATUS NACH SCHNITT A

**Recon abgeschlossen (RECON_01–04).** Die Fehlerklassen-Matrix ist vollständig belegt
(RECON_04 §5). Feature 01 wurde siebenmal reviewt; Schnitt A wurde anschließend mit PR
`#759` implementiert, reviewgehärtet und gemergt. Die Statusform-Gegenprüfung ist im Code
als `_validate_protocol_shape_once()` sowie in direkten Tests enthalten.

Schnitt A misst Hard-Down, Degradation und Skip-Kollaps und persistiert den Streak. Er ist
reines Instrument: kein `raise`, kein Exit-Gate, keine Eskalation. Damit ist A geliefert,
nicht die gesamte Heartbeat-Fehlerpropagation.

**Nächste getrennte Gates:**

1. B nur nach Auswertung belastbarer A-Produktionsdaten und eigener Spec: sichtbare
   Eskalation ohne Run-rot.
2. C bleibt gesperrt, bis Prädikat und Schwelle empirisch feststehen, der Health-Write
   atomar ist und ein Default-off Kill-Switch plus Operator-Go vorliegt.
3. Allgemeine Workflow-Fehler wie Agent-City-Git-Push sind nicht Teil von A und benötigen
   einen getrennten Vertrag; sie dürfen nicht nachträglich in Feature 01 hineingezogen werden.
