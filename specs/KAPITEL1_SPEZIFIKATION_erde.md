# KAPITEL 1 — DETAILSPEZIFIKATION: Das angeborene Immunsystem (Erde / Resilienz)

> **Charakter:** Dies ist eine AUSFÜHRBARE Spezifikation für Claude Code — kein
> Befund, keine grobe Route. Sie lässt bewusst keinen Raum für Spekulation.
> **Vorbedingung:** Befund §4j/§4k/§10/§11 + Skelett Runde 2A gelesen.
> **Ziel:** Den „stillen Tod” stoppen — unbekannte/handler-lose Intents dürfen
> NIE fälschlich als COMPLETED gelten. Minimal-invasiv (Sentinel), ohne den
> globalen `None`-als-Erfolg-Vertrag zu ändern.

-----

## 0. PRE-FLIGHT — was Claude Code ZUERST verifizieren MUSS (vor jeder Zeile Code)

Diese Checks lösen die offenen Kanten aus dem Audit. Wenn ein Check anders
ausfällt als erwartet, STOPP und neu bewerten — nicht blind weiterbauen.

|# |Check (Befehl)                                                |Erwartung                                                  |Wenn anders →                                                   |
|--|--------------------------------------------------------------|-----------------------------------------------------------|----------------------------------------------------------------|
|P1|`grep -rn "\.dispatch(" steward/ | grep -v "hooks.dispatch"`  |Nur `intent_handlers.py` (def) + `autonomy.py:272` (Aufruf)|Mehr Aufrufer → Sentinel-Logik an JEDER Stelle wiederholen      |
|P2|`grep -rn "dispatch_intent" steward/`                         |Nur Definition + 1 Aufruf (`autonomy.py:229`)              |Mehr Aufrufer → alle anpassen                                   |
|P3|`grep -rn "is None" tests/ | grep -i dispatch` + Testlauf grün|Wie viele Tests erzwingen `None`==Erfolg?                  |Viele → Option C (Sentinel) zwingend; Wenige → Option A erwägbar|
|P4|`grep -rn "record_autonomous" steward/`                       |Versteht Ledger-Signatur `(intent_name, bool)`             |Andere Signatur → anpassen                                      |
|P5|Baseline-Testlauf VOR Änderung (`pytest`)                     |~1093 grün, 1 bekannt rot                                  |Mehr rot → erst Baseline klären                                 |

→ **P3 ist die entscheidende offene Variable.** Sie wählt zwischen Option C
(default, sicher) und Option A.

-----

## 1. DER EINGRIFF — minimal-invasiv (Option C: Sentinel)

### 1a. Sentinel definieren (REALITY: steward)

**Datei:** `steward/intent_handlers.py` (oben, Modul-Ebene)

```python
# Sentinel: unterscheidet "kein Handler vorhanden" von "None = kein Problem gefunden".
# Löst die überladene None-Semantik auf, ohne den globalen None-Erfolgs-Vertrag zu ändern.
NO_HANDLER = object()
```

### 1b. dispatch() gibt bei fehlendem Handler den Sentinel zurück (REALITY)

**Datei:** `steward/intent_handlers.py`, Methode `dispatch()`, aktuell Z. 62-65:

```python
# VORHER:
handler = dispatch.get(intent)
if handler is None:
    logger.warning("No handler for intent %s", intent)
    return None                      # ← mehrdeutig: sieht aus wie Erfolg

# NACHHER:
handler = dispatch.get(intent)
if handler is None:
    logger.warning("No handler for intent %s", intent)
    return NO_HANDLER                # ← eindeutig: kein Handler ≠ kein Problem
```

> **Vertrag bleibt:** Erfolgreiche Handler geben weiterhin `None` (kein Problem)
> oder einen Problem-String zurück. Nur der „kein Handler”-Fall ändert sich.
> Der globale None==Erfolg-Vertrag der HANDLER ist unberührt.

### 1c. Wrapper reicht Sentinel durch (REALITY)

**Datei:** `steward/autonomy.py`, `dispatch_intent()` Z. 270-272 — Rückgabetyp
erweitern (Signatur-Annotation: `str | None | object`), Logik unverändert
(`return self.handlers.dispatch(intent)`).

### 1d. Bedingte Statusvergabe am EINZIGEN Aufrufer (REALITY) — der Kern

**Datei:** `steward/autonomy.py`, aktuell Z. 229-231:

```python
# VORHER (der "stille Tod" — bedingungslos COMPLETED):
problem = self.dispatch_intent(intent)
task_mgr.update_task(task.id, status=TaskStatus.COMPLETED)
self._ledger.record_autonomous(intent.name, problem is not None)

# NACHHER (bedingte Statusvergabe):
from steward.intent_handlers import NO_HANDLER
result = self.dispatch_intent(intent)

if result is NO_HANDLER:
    # Angeborenes Immunsystem: unbekanntes/handler-loses Signal NICHT verschlucken.
    logger.warning("No handler for intent %s — task BLOCKED for review", intent)
    task_mgr.update_task(task.id, status=TaskStatus.BLOCKED)
    self._ledger.record_autonomous(intent.name, False)
    return None
# result ist jetzt: None (kein Problem) ODER Problem-String — Vertrag wie gehabt
problem = result
task_mgr.update_task(task.id, status=TaskStatus.COMPLETED)
self._ledger.record_autonomous(intent.name, problem is not None)
# ... (restliche Problem-/Fix-Pipeline-Logik unverändert ab "if problem:")
```

> **Warum BLOCKED (nicht FAILED):** `BLOCKED` ist `is_active()` (Befund §10/§4k) —
> die Task bleibt SICHTBAR und im aktiven Pool, statt terminal verschwunden.
> Sie „blockiert den Kanal”, bis ein Handler existiert (Kap. 2) oder ein Mensch
> eingreift. Das ist das angeborene Immunsystem: Reaktion statt Ignoranz.

-----

## 2. DUALE VERIFIKATIONSTABELLE (verbindlich)

|Eingriff            |LAW (protocols)   |REALITY (substrate/steward)             |Tests (Claude Code prüft)                                     |
|--------------------|------------------|----------------------------------------|--------------------------------------------------------------|
|1a Sentinel-Def     |— (steward-intern)|`steward/intent_handlers.py` (Modulkopf)|neuer Test: `dispatch(unbekannt) is NO_HANDLER`               |
|1b dispatch→Sentinel|—                 |`steward/intent_handlers.py:62-65`      |obiger + Bestand grün                                         |
|1c Wrapper-Typ      |—                 |`steward/autonomy.py:270-272`           |Typprüfung                                                    |
|1d bedingter Status |—                 |`steward/autonomy.py:229-231`           |neuer Test: unbekannter Intent → Task BLOCKED, NICHT COMPLETED|


> **LAW-Spalte leer:** Dieser Eingriff ist rein steward-intern (Runtime-Logik),
> kein protocols/substrate-Dual. Das ist korrekt deklariert (LAW/REALITY-Regel
> aus Kap. 0 verlangt die EXPLIZITE Angabe — hier: nur REALITY/steward).

-----

## 3. NEUE TESTS (Claude Code schreibt vor/mit dem Eingriff)

1. **`test_dispatch_unknown_intent_returns_sentinel`**: ein nicht-registrierter
   Intent → `dispatch()` gibt `NO_HANDLER` zurück (nicht None, nicht Exception).
1. **`test_known_intent_no_problem_still_none`**: ein registrierter Handler, der
   kein Problem findet → gibt weiterhin `None` zurück (Vertrag unverändert).
1. **`test_unhandled_intent_task_blocked_not_completed`**: KARMA-Dispatch eines
   Intents ohne Handler → Task-Status = `BLOCKED`, NICHT `COMPLETED`.
1. **`test_normal_task_still_completes`**: ein normaler erfolgreicher Intent →
   Task `COMPLETED` (Regression: der stille Tod ist weg, aber Erfolg bleibt Erfolg).
1. **Regression:** volle Baseline (~1093) bleibt grün.

-----

## 4. WAS DIESER EINGRIFF BEWUSST NICHT TUT (Scope-Grenzen)

- **Keine** Intent-Registrierung (`BOTTLENECK_ESCALATION` etc.) — das ist Kap. 2.
  Kap. 1 sorgt nur dafür, dass deren Fehlen NICHT mehr still tötet.
- **Keine** generische „Entzündungs-Mission” / Auto-Reparatur des Unbekannten —
  bewusst aufgeschoben (embryonaler Vorbehalt). BLOCKED + Log reicht als
  angeborene Erstreaktion. Eskalation an die kognitive Zündschnur (Kap. 4) ist
  eine SPÄTERE Verfeinerung, nicht Teil von Kap. 1.
- **Keine** Änderung der globalen `dispatch()`-Handler-Signatur (kein
  DispatchResult-Objekt) — es sei denn, P3 zeigt, dass kaum Tests den
  None-Vertrag erzwingen UND das Team Option A bewusst wählt.
- **Keine** Cetana/Vedana-Änderung — der ehrlichere Fehlerdruck (§10) ist
  erwünschte Folge, kein Eingriff.

-----

## 5. ERWARTETE WIRKUNG (Verifikation nach dem Eingriff)

- Unbekannte/handler-lose Signale erscheinen als `BLOCKED`-Tasks (sichtbar) statt
  als falsche `COMPLETED`. Der „stille Tod” ist gestoppt.
- `vedana.health` wird ehrlicher (Fehlerdruck steigt evtl. moderat — §10,
  „Erwachen des Schmerzempfindens”). Cetana beschleunigt sanft, kein Infarkt.
- Operative Sichtbarkeit: ein `BLOCKED`-Task-Zähler zeigt erstmals, WIE VIELE
  Signale das System bisher verschluckt hat. (Diagnostischer Bonus — zeigt das
  wahre Ausmaß, das Kim als „alles rot” erlebte.)

-----

*Ende Kapitel-1-Spezifikation. Status: bereit für Claude Code, vorbehaltlich
Pre-Flight P1-P5 (insb. P3 Test-Vertrag). Nach Kap. 1 folgt Kap. 2 (Membran-
Intents) — es baut DIREKT auf dem hier eingeführten Sentinel/BLOCKED-Mechanismus
auf.*