# HEARTBEAT-FEHLERPROPAGATION — RECON 04: PERSISTENZ & EXTERNE KLASSE

> **Status:** EVIDENCE COMPLETE — RECON ABGESCHLOSSEN; FEATURE-SPEC IST DER NÄCHSTE GATE
> **Datum:** 2026-07-17
> **Code-Basis:** `kimeisele/steward@bf2fba2075a87463fc8e333f8f57d805fce4d030`
> **Scope:** Read-only. Schließt RECON_03 §7 (Zyklus-Persistenz, externe/Post-Action-Klasse).
> **Verifikation:** `moksha.py:118–137` von Opus gelesen; `_total_failures`/`_last_reset`/
> `build_chamber` per Opus-Grep bestätigt (nur `chamber.py`, kein Disk-Write); übrige Anker
> per Sub-Agent (Explore, verbatim).

---

## 1. Fragen (aus RECON_03 §7)

Wie lange „hält" ein Kollaps (transient vs. anhaltend), und wo ist der Zustand dafür? Und:
ist die externe/Post-Action-Klasse (Föderations-Push) kritisch oder degradierbar?

## 2. Persistenz des Kollaps-Zustands — belegt: nur in-memory

Der Kollaps-Zustand lebt ausschließlich im `ProviderChamber`-Dataclass (`chamber.py:114–121`:
`_breakers`, `_last_reset`, `_total_calls`, `_total_failures`; Zell-Integrität/prana). Er
wird **nicht auf Platte geschrieben**: `_total_failures`/`_last_reset` erscheinen (Opus-Grep)
nur in `chamber.py` (Increment `:495`, Lesen `:323/:415/:440`, Reset `:525/:533`) — kein
Write nach `.steward/*.json` oder `data/federation/*.json`. `build_chamber()` baut bei jedem
Prozess-Start eine **frische** Chamber (`__main__.py:284,471`). Einziger Clearing-Pfad:
`_maybe_reset_daily` (`chamber.py:522–534`) bei Datumswechsel.

**Daraus folgen drei Ebenen von „anhaltend" — und die dritte ist der blinde Fleck:**

| Ebene | Beispiel | Messbar? | Wo |
|---|---|---|---|
| transient | ein Call scheitert, Fallback greift | ja, per Design toleriert | `chamber.py:289–303` |
| anhaltend **im Run** | alle Provider tot über die 4 Zyklen *eines* Prozesses | ja, in-memory | `_total_failures`, alive-count, breaker |
| anhaltend **über Runs** | Kollaps über viele 15-Min-Runs hinweg | **NEIN — Zustand wird je Run verworfen** | — (keine Disk-Persistenz) |

## 3. Die entscheidende Asymmetrie

Der Heartbeat **persistiert Föderations-State** (`.steward/`, `data/federation/`) über Runs
— aber **nicht die Provider-/Kognitions-Gesundheit.** Der einzige geschriebene Health-Report
(`moksha_health.py:62–94`) enthält `peers/immune/gateway` und **kein Provider-/Kognitions-
Feld.** Genau die Dimension, die einen mehr-Run-anhaltenden Kollaps sichtbar machen würde,
wird weggeworfen. Das ist der Kern für die spätere Spec: die „kritisch"-Klasse
(anhaltend über Runs) braucht einen **persistierten** Kollaps-Zähler, weil die In-Memory-
Chamber über Runs blind ist.

## 4. Externe/Post-Action-Klasse (Föderations-Push) — belegt: geschluckt UND ungezählt

`git_nadi_sync.push()` gibt bei Fehler `False` zurück, `raise`t nie (`git_nadi_sync.py:
154–171`). Aufrufstelle `moksha.py:132–135`:
```python
git_sync = ServiceRegistry.get(SVC_GIT_NADI_SYNC)
if git_sync is not None:
    git_sync.push()
```
Der Rückgabewert wird **nicht zugewiesen/geprüft**; `relay.push_to_hub()` nur für eine
Log-Zeile genutzt. Kein `ctx.operations.append` (im Gegensatz zu
`moksha_health.py:59 "…:ok"`). Propagation nach außen: **ABSENT** — Delivery-Fehler ist
weder im Exit-Status noch im Health-Report noch in einem Flag sichtbar.

Einordnung: Delivery-Fehler ist eine **degradierbare** Klasse (transiente Remote-/Netz-
Probleme sollen den Daemon nicht töten), aber sie ist heute nicht nur toleriert, sondern
**unsichtbar** — kein Tracking.

## 5. Konsolidierte Fehlerklassen-Matrix (Recon-Ergebnis, Basis für die Feature-Spec)

| Klasse | Belegter Trigger | Heute | Zielverhalten (gehört in Feature-Spec) |
|---|---|---|---|
| transient | Einzel-Call scheitert, Fallback greift (`chamber.py:289`) | grün, Fallback | grün + gezählt |
| anhaltend-im-Run | alle Provider tot über Zyklen (`chamber.py:318`) | grün, nur `logger.error` | sichtbar (Health-Feld + Log) |
| anhaltend-über-Runs | Kollaps über mehrere Runs | **unsichtbar** (Zustand verworfen) | **persistierter Zähler → kritisch, LOGGING zuerst** |
| extern/Post-Action | Push scheitert (`moksha.py:135`) | geschluckt + ungezählt | toleriert + gezählt/sichtbar |

## 6. Recon-Abschluss & nächster Gate

Der Recon (RECON_01–04) ist **abgeschlossen**: die vier Schluck-Schichten, der None-Konsum,
die adversariale Bestätigung mit Befund-Umkehrung, und Persistenz/externe Klasse sind
belegt. Es gibt **keinen** offenen Recon-Punkt mehr, der vor der Spec zwingend ist.

**Nächster Gate = eigene Feature-Spec** (Format wie Context Bridge: Zweck, gepinnter
Ist-Zustand, Scope/Non-Scope, Zielarchitektur am Andockpunkt `vedana`/`health_anomaly` +
persistierter Kollaps-Zähler, Testvertrag, LOGGING-vor-Erzwingen, Rollback). **Kein
Produktcode und keine Feature-Spec ohne ausdrückliches Operator-Go.**
