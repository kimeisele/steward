# HEARTBEAT-FEHLERPROPAGATION — RECON 01: SCHLUCK-PFADE

> **Status:** EVIDENCE PARTIAL — VIER SCHLUCK-SCHICHTEN BELEGT; FEHLERKLASSEN-ZUORDNUNG OFFEN
> **Datum:** 2026-07-17
> **Code-Basis:** `kimeisele/steward@bf2fba2075a87463fc8e333f8f57d805fce4d030`
> **Scope:** Read-only Recon des Heartbeat-Ausführungspfads; keine Code-Änderung

---

## 1. Frage

Kann ein Heartbeat-Run rot werden, wenn die Kognition versagt — insbesondere bei
Total-Erschöpfung der Provider-Kaskade? Oder endet der Run strukturell immer grün?

## 2. Der Prod-Ausführungspfad (belegt)

Der Produktions-Heartbeat läuft als GitHub-Action-Schritt
(`.github/workflows/steward-heartbeat.yml`), der einen Inline-`python -c`-Block startet
(Z. 68). Dieser Block ruft für `CYCLES` Zyklen (Default 4) je vier Phasen **direkt** auf:

```
('GENESIS', agent._phase_genesis)
('DHARMA',  agent._phase_dharma)
('KARMA',   lambda: agent.run_autonomous_sync(idle_minutes=15))
('MOKSHA',  agent._phase_moksha)
```

Kein `set -e`-Abbruch auf Phasenfehler, kein `continue-on-error`, kein `|| echo`. Der
Exit-Status des Schritts = Exit-Status des Python-Prozesses.

## 3. Die vier Schluck-Schichten (am Code belegt)

Jede Schicht fängt Fehler ab, ohne sie zum Exit-Status zu propagieren:

| # | Ort | Verhalten | Log-Level | Sichtbar bei `INFO`? |
|---|---|---|---|---|
| L1 | `steward/provider/chamber.py:314–325` | Provider-Kaskade erschöpft → `return None` (kein `raise`) | `error` | ja |
| L2 | `steward/phase_hook.py:162–174` | jeder Hook-Fehler → `logger.warning`, `continue` | `warning` | ja |
| L3a | `.github/workflows/steward-heartbeat.yml:83–90` | jeder Phasenfehler → `logger.error` + `traceback`, weiter; Prozess endet Exit 0 | `error` | ja |
| L3b | `steward/agent.py:763–766` (`_run_phase`) | interner Phasenfehler → `logger.debug("… non-fatal")` | `debug` | **nein** |

### Belege (verbatim)

**L1 — `chamber.py:319–325`:**
```python
logger.error(
    "ALL providers exhausted (%d total, %d alive, %d failures)",
    len(self._cells), alive_count, self._total_failures,
)
return None
```
`invoke()` dokumentiert selbst (Z. 223): *„Returns NormalizedResponse or None if all
providers exhausted."* Kein `raise`. Der Aufrufer erhält `None`.

**L2 — `phase_hook.py:173–174`:**
```python
except Exception as e:
    logger.warning("Hook %s failed: %s", hook.name, e)
```
Der Loop über die Hooks läuft nach dem `except` weiter (`continue`-Semantik).

**L3a — `steward-heartbeat.yml:83–90`:**
```python
try:
    phase_fn()
except Exception as e:
    logger.error('%s failed: %s', phase_name, e)
    traceback.print_exc()
```
Nach der Doppelschleife endet das Script normal → **Exit 0 → Workflow grün.**

**L3b — `agent.py:763–766`:**
```python
try:
    handler()
except Exception as e:
    logger.debug("Cetana phase %s error (non-fatal): %s", phase.name, e)
```
Der Heartbeat setzt `logging.basicConfig(level=logging.INFO)`. `debug < INFO` → diese
Schicht ist im Produktionslog **unsichtbar**. Hinweis: L3b liegt auf dem internen
Cetana-Daemon-Pfad; der Prod-Heartbeat nutzt L3a. Beide existieren.

## 4. Zentraler Befund

Der Heartbeat-Run ist **strukturell unfähig, an kognitivem, Hook- oder Provider-Versagen
rot zu werden.** Selbst ein Total-Provider-Kollaps über alle Zyklen endet Exit 0. Das
einzige Signal ist eine Log-Zeile (L1 `error`), auf die **kein Gate** prüft.

Das grüne Heartbeat-Signal ist damit als Aussage über kognitive Gesundheit wertlos —
strukturell, nicht zufällig. Deckt sich mit den wiederkehrenden Live-Beobachtungen
(Provider-Degradation Groq 401 / Gemini 429 / Mistral 400 bei „erfolgreichem" Run,
`docs/PHASE2_CURRENT.md` §5) und mit Phase-1 §220.3.

## 5. Wirkungsvertrag (Zielrichtung, noch nicht Spec)

Die pauschalen `except Exception` sind das Problem. Ziel ist eine Fehlerklassen-Trennung
(kritisch → rot / degradierbar → toleriert+sichtbar / extern → getrennt), zunächst im
LOGGING-/Beobachtungsmodus verdrahtet, bevor irgendetwas rot erzwingt.

## 6. Blast-Radius / Warum vorsichtig

Die Föderation läuft durch dieses Gate. Ein naives „raise" auf L1 würde einen transienten
Provider-Ausfall zum Föderations-Stillstand eskalieren. Deshalb ist die Fehlerklassen-
Zuordnung (was ist wirklich kritisch?) der eigentliche Kern und muss vollständig belegt
sein, bevor ein Patch entsteht.

## 7. Sicherheitsauswirkung

Keine (read-only). Das Dokument ändert kein Verhalten. Es dokumentiert eine bestehende,
belegte Fundament-Schwäche.

## 8. Offen / noch nicht belegt (nächste Recon-Runde)

1. **Konsum von `None` aus `invoke()`**: Wo genau (Conversation-Engine, `AutonomyEngine`)
   wird das `None` bei Provider-Kollaps konsumiert? Führt es zu stillem No-op oder zu einer
   Exception, die dann in L2/L3 landet? (`agent.py:428` reicht den Provider weiter.)
2. **Fehlerklassen-Matrix**: Welche konkreten Exception-Typen / Zustände sind *kritisch*
   vs. *degradierbar*? (`QuotaExceededError` in `chamber.py:236` als erster Kandidat.)
3. **Zyklus- vs. Einzelaufruf-Granularität**: Ein einzelner Provider-Ausfall ≠ Kollaps über
   einen ganzen Zyklus. Wo ist die richtige Grenze für „kritisch"?
4. **Bestehende Sichtbarkeits-Infrastruktur**: Gibt es bereits einen Health-/Anomalie-Pfad
   (`ctx.health_anomaly` in `agent.py:790`), an den sich eine Fehlerpropagation
   anschließen ließe, statt neu zu bauen? (Phase-1-Prinzip: erst grep, ob es existiert.)

## 9. Gate-Wirkung

Recon nicht abgeschlossen. Kein Feature-Spec-, Implementierungs- oder Aktivierungs-Gate
freigegeben. Nächster Schritt: offene Punkte §8 belegen.
