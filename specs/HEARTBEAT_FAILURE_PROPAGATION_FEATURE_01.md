# HEARTBEAT-FEHLERPROPAGATION — FEATURE-SPEC 01

## Sichtbarmachung anhaltenden kognitiven/Provider-Kollaps

> **Status:** DRAFT 0.1 — NICHT G1; ZUR ADVERSARIALEN KRITIK; IMPLEMENTIERUNG UND
> AKTIVIERUNG GESPERRT
> **Datum:** 2026-07-17
> **Produktionsbasis:** `kimeisele/steward@bf2fba2075a87463fc8e333f8f57d805fce4d030`
> **Herkunft:** Phase-2 §7.3; Recon RECON_01–04 in `heartbeat_failure_propagation_evidence/`

---

## 1. Zweck und Gate

Einen **anhaltenden** kognitiven/Provider-Kollaps beobachtbar machen, ohne die bewusste
Resilienz des Heartbeats (Daemon stirbt nicht an transienten Fehlern) zu brechen. Zuerst
reine Sichtbarkeit (LOGGING), Erzwingen (Run rot) erst nach belegter Beobachtung und nur
hinter Kill-Switch.

Dies ist ein DRAFT. Aus ihm darf kein Patch abgeleitet werden. Gate G1 wird erst nach
adversarialem Review (§10) und Operator-Go erteilt.

## 2. Normative Abhängigkeiten

- `heartbeat_failure_propagation_evidence/RECON_01_SWALLOW_PATHS.md` (vier Schluck-Schichten)
- `RECON_02_CONSUMPTION_AND_CLASSES.md` (None-Konsum, vorhandene Klassifikation)
- `RECON_03_ADVERSARIAL.md` (Befund-Umkehrung: Erkennung vorhanden, Aussenverdrahtung fehlt)
- `RECON_04_PERSISTENCE_AND_EXTERNAL.md` (in-memory-only, konsolidierte Fehlerklassen-Matrix)

## 3. Gepinnter Ist-Zustand (belegt)

- Kollaps wird erkannt: `vedana.py:78` (`_W_PROVIDER = 0.35`) → `dharma.py:56`
  (`health < 0.3 → ctx.health_anomaly = True`).
- Erkennung wirkt nur nach innen: `engine.py:310` (Runden kappen + LLM-Guidance). Kein
  Exit/Alert.
- Kaskade endet `return None` (`chamber.py:325`), Harness schluckt (`steward-heartbeat.yml:
  83–90`, Exit 0). Resilienz — bewusst.
- Kollaps-Zustand ist **in-memory only** (`chamber.py:114–121`; kein Disk-Write von
  `_total_failures`/`_last_reset`) → **über Runs blind**.
- Persistierter Health-Report hat **kein** Provider-/Kognitions-Feld
  (`moksha_health.py:62–94`).
- `chamber.stats()` liefert `total_failures`, `total_calls`, `providers[].alive`
  (`chamber.py:440`, konsumiert `engine.py:356–360`).
- Vorhandenes Aussensignal-Muster: `dharma.py:187–214` (GitHub-Issue, Label
  `federation-health`) — heute nur für Peers.

## 4. Scope und Nicht-Scope

**In Scope:** ein persistierter Run-übergreifender Kollaps-Zähler; ein Provider-/
Kognitions-Feld im vorhandenen Health-Report; optionale Eskalation über das vorhandene
`dharma`-Issue-Muster; optionale, kill-switch-gesicherte Run-Signalisierung.

**Nicht-Scope:** kein `raise` in `chamber`; keine Änderung der Workflow-`try/except`-
Resilienz; keine neue Kaskaden-/Provider-Logik; Context-Bridge, Identität, Key-Rotation,
Quarantäne unberührt. Kein Sammelpatch.

## 5. Zielarchitektur (Vorschlag, angreifbar)

1. **Kollaps-Signal je Run ermitteln** aus `chamber.stats()` am Run-Ende (MOKSHA): ist der
   Run vollständig kollabiert (0 alive / alle Provider tot über den Run)? Reine Ableitung
   aus vorhandenem `stats()`, keine neue Zählung.
2. **Persistierter Zähler** in bereits über Runs persistiertem State (`.steward/`):
   `consecutive_collapsed_runs`. +1 bei Voll-Kollaps-Run, Reset auf 0 bei einem Run mit
   ≥1 erfolgreicher Kognition. Das ist der fehlende Run-übergreifende Zustand.
3. **Sichtbarkeit (Slice A):** Provider-/Kognitions-Block in `_build_health_report`
   (`alive/total`, `total_failures`, `consecutive_collapsed_runs`). Nur schreiben/loggen —
   **kein** Einfluss auf Run-Ausgang.
4. **Eskalation (Slice B):** ab Schwelle `consecutive_collapsed_runs ≥ N` das vorhandene
   `dharma`-Issue-Muster für Selbst-Kollaps wiederverwenden (Label z. B. `steward-health`).
   Kein Run-Rot.
5. **Erzwingen (Slice C, optional, kill-switch):** erst nach Beobachtung — bei Schwelle den
   Run als nicht-erfolgreich signalisieren (Exit≠0 im Heartbeat-Schritt), hinter
   Feature-Flag/Kill-Switch, Default AUS.

## 6. Verpflichtende Implementierungsschnitte (getrennt, je eigener G2)

- **Schnitt A — Sichtbarkeit:** Zähler + Health-Feld. Null Verhaltensänderung am Run-Ausgang.
  Produktionsbeweis: Feld erscheint, Run bleibt grün, transienter Ausfall erhöht den Zähler
  NICHT.
- **Schnitt B — Eskalation:** Issue-Muster-Wiederverwendung. Kein Run-Rot.
- **Schnitt C — Erzwingen:** kill-switch-gesicherte Run-Signalisierung. Nur nach A/B +
  belegter Schwelle.

Kein Schnitt darf mit einem anderen in einen Sammel-PR.

## 7. Testvertrag

- Gegen die **echte** `ProviderChamber` testen, kein Stub (Phase-1 §220.3).
- Voll-Kollaps-Run (alle Cells tot) → Zähler +1, Health-Feld gesetzt.
- **Guard gegen Fehlalarm:** ein einzelner transienter Ausfall mit erfolgreichem Fallback →
  Zähler bleibt/geht 0. (Der Guard, der die transient/kritisch-Grenze verteidigt.)
- Reset: ein Run mit ≥1 erfolgreicher Kognition → Zähler 0.
- Schnitt A ändert den Run-Exit-Status in **keinem** Fall.

## 8. Aktivierung, Kill-Switch, LOGGING-vor-Erzwingen

Schnitt A/B sind reine Beobachtung/Alarm, kein Run-Rot. Schnitt C ist per Default AUS und
nur über expliziten Kill-Switch aktivierbar. Verifikation immer am **Produktionslog**, nicht
am grünen Test.

## 9. Rollback

Jeder Schnitt ist einzeln reversibel: Health-Feld/Zähler entfernen bzw. Kill-Switch AUS.
Da Schnitt A/B den Run-Ausgang nicht ändern, ist ihr Blast-Radius auf Datenfelder begrenzt.

## 10. Offene Fragen — BITTE ADVERSARIAL ANGREIFEN (vor G1)

1. **Schwelle N** für „anhaltend über Runs" ist noch nicht belegt — sie darf **nicht**
   geraten werden, sondern muss aus Produktionsbeobachtung (Schnitt A) kommen. Bis dahin
   ist Schnitt C gesperrt.
2. **Trägt der Health-Report** die richtige Semantik, oder braucht der Zähler ein eigenes,
   atomar geschriebenes Feld? (Freshness/Concurrency — der Heartbeat ist Single-Writer via
   Workflow-Concurrency-Group, aber der Write muss zum bestehenden State-Commit atomar sein.)
3. **Reflektiert `chamber.stats()` am MOKSHA-Zeitpunkt den ganzen Run** oder nur den letzten
   Zyklus? RECON_04 zeigt `_total_failures` kumuliert (kein Per-Zyklus-Reset) — bei
   Implementierung am Live-Code erneut pinnen.
4. **Voll-Kollaps-Definition:** „0 alive Cells" vs. „keine erfolgreiche Kognition im Run" —
   letzteres ist robuster (ein Provider kann alive und trotzdem erfolglos sein). Zu
   entscheiden.
5. **Interagiert der `_maybe_reset_daily`** (`chamber.py:522`) mit der Zähler-Semantik?

## 11. Schlussstatus

DRAFT 0.1. Kein G1, keine Implementierung, keine Aktivierung. Nächster Schritt: adversariales
Review von §5/§10, dann — nach Operator-Go — G1-fähige Fassung.
