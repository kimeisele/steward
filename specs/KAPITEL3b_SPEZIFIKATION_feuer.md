# KAPITEL 3b — DETAILSPEZIFIKATION: Der Wille (Feuer)

> **Charakter:** Ausführbare Spezifikation für Claude Code. Baut auf Kap. 3a
> (Gewissen, Branch `kapitel-3a-dharma`) auf. Gegen echten Substrat-Code
> verifiziert (Befund §19). **Voraussetzung:** Kap. 3a committed (das Gewissen
> sichert die erzeugten Missionen ab).
> **Ziel:** Anhaltende Makro-Stagnation (`is_stuck` über Task-Grenzen) löst über
> den CONDITION_BASED-Trigger eine BESONNENE, DIAGNOSTISCHE Mission aus — nicht
> blinden Aktionismus. Sattva gegen Tamas (§20a).

---

## 0. ARCHITEKTUR-PRINZIP (verifiziert)

- **Keine neue Erkennung:** `is_stuck` ist bereits makro-fähig — KsetraJna-Historie
  (`deque maxlen=50`) läuft kontinuierlich über Task-Grenzen, kein Reset (§19e).
  Wir müssen sie nur bei der Willensbildung ABFRAGEN und durchreichen.
- **Zwei Nähte (§19c):** (1) Datenfluss `is_stagnating` durch think→evaluate→
  _should_fire; (2) CONDITION_BASED-Auswertung in _should_fire + Mission-Strategie.
- **Verfassungs-Vollendung (Kim autorisiert §20/Doktrin):** CONDITION_BASED ist im
  Substrat als Trigger-Typ definiert, aber nie ausgewertet (Naht 1). Wir vollenden
  ihn — LEGAL, weil die Verfassung weiterentwickelt werden darf. LAW/REALITY-Regel:
  BEIDE `will.py` (substrate + protocols) betroffen, dual verifizieren.
- **Reaktion = DIAGNOSTISCH (§20a) + DRIFT-ERZEUGEND (§22d, Blindspot 1):** Die
  Stagnations-Mission ist LESEND (kein Thrashing) MUSS aber tatsächlich AUSGEFÜHRT
  werden und dabei einen LLM-Turn durchlaufen — denn dann ändern sich `last_pattern`
  (Buddhi erkennt neues Muster, 10%) + `round` (Turn-Inkrement, 15%) + health/error
  → Drift > 5%-Schwelle → is_stuck setzt sich zurück. Ein reiner Null-Token-DETEKTOR
  (wie `synthesize_briefing`, P9) erzeugt KEINE Pattern-Drift → Endlosschleife.
  Deshalb: Mission = echte reflektierende Diagnose mit LLM-Turn, NICHT der
  Briefing-Detektor.
- **Sicherung steht:** Jede erzeugte Mission-Task läuft durch den einen
  Dispatch-Pfad (autonomy.py:175), wo das Gewissen (Kap. 3a) sitzt. Automatisch
  abgesichert.

---

## 1. PRE-FLIGHT (nur lesen, kein Code — verhindert §18-artige Fehler)

| # | Check | Erwartung | Wenn anders → |
|---|---|---|---|
| P1 | `git branch --show-current` | `kapitel-3a-dharma` (Kap. 3a committed) | erst 3a sichern |
| P2 | `grep -n "def _should_fire" $(python3 -c "import vibe_core.mahamantra.substrate.sankalpa.will as w; print(w.__file__)")` | existiert, Signatur `(strategy, idle_minutes, pending_intents, ci_green)` | Signatur an Realität anpassen |
| P3 | `python3 -c "from vibe_core.mahamantra.protocols.sankalpa.types import TriggerType; print(TriggerType.CONDITION_BASED.value)"` | `condition_based` | Enum-Namen prüfen |
| P4 | Finde die ZWEITE will.py (LAW): `python3 -c "import vibe_core.mahamantra.protocols.sankalpa.will as w; print(w.__file__)" 2>&1` | Pfad ODER „kein evaluate dort" | klären welche Ebene _should_fire hat |
| P5 | `grep -n "sankalpa.think\|\.think(" steward/agent.py` | Aufrufstelle (~Z. 531) mit idle_minutes etc. | Aufrufkontext bestimmen |
| P6 | `grep -n "ksetrajna\|is_stuck\|_ksetrajna" steward/agent.py steward/autonomy.py` | KsetraJna-Instanz erreichbar (für is_stuck-Abfrage) | Zugriffspfad klären, an uns berichten |
| P7 | Baseline: `pytest tests/test_intents.py -q --timeout=45 2>&1 \| tail -3` | grün (Kap 1/2/3a) | Baseline klären |
| P8 | **(Blindspot 3 — Persistenz)** Prüfe, ob `SankalpaStrategy.execution_count_today` PERSISTENT gespeichert wird (Ledger/Datei) oder nur im RAM: `grep -n "execution_count_today\|last_executed\|_check_daily_reset\|persist\|save\|ledger" $(python3 -c "import vibe_core.mahamantra.substrate.sankalpa.will as w; print(w.__file__)")` | Count wird persistiert | Falls nur RAM: max_executions ist Placebo bei Reboot → eigener Cooldown nötig, an uns berichten |
| P9 | **(Blindspot 1 — Drift)** Prüfe, ob `synthesize_briefing` eine Zustandsänderung erzeugt, die KsetraJna als Drift sieht: `grep -n "def execute_synthesize_briefing\|def.*briefing\|write\|CLAUDE.md\|save" steward/intent_handlers.py` — schreibt es wirklich eine Datei / verändert es den beobachteten Zustand? | ja, erzeugt Fußabdruck | Falls NEIN: Mission muss Snapshot zusätzlich perturbieren, an uns berichten — SONST Diagnose-Endlosschleife |

> **P4 + P6 + P8 + P9 sind kritisch.** P4: LAW/REALITY-Dopplung. P6: KsetraJna-
> Zugriff. **P8: ist max_executions echt oder Placebo (Reboot-Schleife)? P9: setzt
> die Diagnose is_stuck wirklich zurück, oder Endlosschleife?** Bei Unklarheit ZUERST
> berichten, nicht raten.

---

## 2. DER EINGRIFF

### 2a. CONDITION_BASED-Auswertung in `_should_fire` (SUBSTRATE = REALITY)
In der Substrat-`will.py`, Funktion `_should_fire`. Neuer Parameter `is_stagnating`
und ein `elif`-Zweig. VORHER (verifiziert, §19b):
```python
def _should_fire(self, strategy, idle_minutes, pending_intents, ci_green) -> bool:
    ...
    if trigger.trigger_type == TriggerType.IDLE_BASED:
        return idle_minutes >= trigger.idle_minutes
    elif trigger.trigger_type == TriggerType.TIME_BASED:
        return self._check_time_trigger(trigger, strategy)
    return False
```
NACHHER:
```python
def _should_fire(self, strategy, idle_minutes, pending_intents, ci_green,
                 is_stagnating: bool = False) -> bool:  # neuer Parameter, default False (abwärtskompatibel)
    ...  # Constraints unverändert
    if trigger.trigger_type == TriggerType.IDLE_BASED:
        return idle_minutes >= trigger.idle_minutes
    elif trigger.trigger_type == TriggerType.TIME_BASED:
        return self._check_time_trigger(trigger, strategy)
    elif trigger.trigger_type == TriggerType.CONDITION_BASED:
        return is_stagnating  # Vollendung von Naht 1: feuert bei Makro-Stagnation
    return False
```

### 2b. `is_stagnating` durch `evaluate()` reichen (SUBSTRATE)
`evaluate()` bekommt den Parameter und gibt ihn an `_should_fire` weiter:
```python
def evaluate(self, idle_minutes=0, pending_intents=0, ci_green=True,
             is_stagnating: bool = False) -> List[SankalpaIntent]:
    ...
    if self._should_fire(strategy, idle_minutes, pending_intents, ci_green, is_stagnating):
```

### 2c. `think()` reicht `is_stagnating` durch (SUBSTRATE)
```python
def think(self, idle_minutes=0, pending_intents=0, ci_green=True,
          is_stagnating: bool = False) -> List[SankalpaIntent]:
    return self._planner.evaluate(
        idle_minutes=idle_minutes, pending_intents=pending_intents,
        ci_green=ci_green, is_stagnating=is_stagnating,
    )
```

### 2d. LAW-Ebene (protocols) — VERIFIZIERT: KEINE Dopplung (P4)
Es gibt KEINE zweite `will.py`. LAW ist nur eine abstrakte Signatur
(`SankalpaOrchestratorProtocol` in `protocols/sankalpa/types.py`). → **Der
_should_fire-Eingriff (2a) geschieht nur EINMAL (Substrat).** Konsistenz-Pflicht:
Falls `SankalpaOrchestratorProtocol` eine `think()`/`evaluate()`-Signatur
deklariert, diese um `is_stagnating: bool = False` erweitern, damit LAW (Versprechen)
und REALITY (Umsetzung) übereinstimmen. Reine Signatur-Anpassung, keine zweite Logik.

### 2e. Steward fragt is_stuck ab + reicht es an think() (REALITY: steward)
**P6-Lösung:** Die AutonomyEngine kennt den Agenten NICHT (nur Callables). KsetraJna
wird als Callable übergeben — KONSISTENT zu vedana_fn/ashrama_fn (NICHT Agent
injizieren, §22c). Bei der Engine-Konstruktion (agent.py ~Z. 205):
```python
self._autonomy = AutonomyEngine(
    ..., vedana_fn=lambda: self.vedana, ashrama_fn=lambda: self._ashrama,
    is_stuck_fn=lambda: self._ksetrajna.is_stuck(),   # NEU, gleiches DI-Muster
)
```
An der think()-Aufrufstelle (autonomy.py:570, P5):
```python
intents = sankalpa.think(
    idle_minutes=idle_minutes, pending_intents=len(active),
    ci_green=campaign_health.ci_green,
    is_stagnating=self.is_stuck_fn(),   # NEU
)
```

### 2f. Stagnations-Diagnose: neuer Detektor + Mission (REALITY: steward)

**Architektur-Erkenntnis (§23):** Fast alle Steward-Intents sind DETEKTOREN (geben
Problem-String, handeln nicht — Ahankara-Prinzip). Ein Detektor, der einen
Problem-String zurückgibt, löst nachgelagert in der FixPipeline einen echten
LLM-Turn aus (autonomy.py:229-257, „LLM only wakes if a real problem needs fixing").
DIESER Turn erzeugt die Drift (Buddhi-Pattern + round + health), die is_stuck
zurücksetzt. → **Das Paradoxon löst sich durch die vorhandene Pipeline, WENN der
Detektor bei Stagnation ein Problem MELDET (nicht None).**

**2f-1: Neuer Intent + Detektor-Handler** (intents.py + intent_handlers.py):
Ein neuer Intent `DIAGNOSE_STAGNATION` mit einem Detektor, der das Stagnations-
Faktum als Problem-String ausgibt — dharmisch stimmig: der feststeckende Steward
meldet sein Feststecken als das zu lösende Problem.
```python
# intents.py: neuer Intent
DIAGNOSE_STAGNATION = "diagnose_stagnation"
# INTENT_TO_CONSCIENCE (Kap 3a): lesende Diagnose → "review_todos" (frei)
# intent_handlers.py: Detektor, der bei Stagnation ein Problem meldet
def execute_diagnose_stagnation(self, task=None) -> str | None:
    """Stagnation detected — report as problem so the FixPipeline reflects. 0 tokens
    im Detektor; der nachgelagerte LLM-Turn erzeugt die Drift, die is_stuck resettet."""
    return ("Agent stagnating: state drift below threshold over recent observations. "
            "Diagnose root cause — review recent tasks, error patterns, and the "
            "blocked-task queue; identify why progress stalled.")
```
Dieser Problem-String triggert `guarded_llm_fix` → echter Reflexions-Turn → Drift →
is_stuck-Reset. Kein Datei-Hack, kein lügender Detektor.

**2f-2: Mission-Strategie** (services.py `_add_steward_missions`):
```python
SankalpaMission(..., priority=MissionPriority.HIGH)   # Blindspot 2 (P10)
SankalpaStrategy(
    ...,
    trigger=SankalpaTrigger(trigger_type=TriggerType.CONDITION_BASED),
    intent_type="diagnose_stagnation",   # der neue Detektor, meldet immer ein Problem
    requires_ci_green=False,
    max_executions_per_day=3,            # Anti-Thrashing, PERSISTENT (P8 ✅)
)
```

> **⚠️ BLINDSPOT 1 — final gelöst (§23):** Der Detektor meldet IMMER ein Problem
> (nicht None) → FixPipeline läuft IMMER an → LLM-Turn → Drift → Reset. Der Turn
> ist die besonnene Diagnose (Sattva, lesend, kein Thrashing), die durch die
> Pipeline-Gates abgesichert ist. `test_diagnosis_resets_stuck` prüft die Wirkung.

---

## 3. DUALE VERIFIKATIONSTABELLE

| Eingriff | LAW (protocols) | REALITY (substrate/steward) | Tests |
|---|---|---|---|
| 2a _should_fire | ggf. 2d | substrate/will.py | CONDITION_BASED feuert bei is_stagnating=True |
| 2b/2c Durchreichen | ggf. 2d | substrate/will.py | Parameter kommt an |
| 2e is_stuck-Abfrage | — | steward/agent.py | is_stuck-Wert erreicht think() |
| 2f Mission | — | steward/services.py | Strategie registriert, lesender Intent |

---

## 4. NEUE TESTS (echte Objekte, KEIN MagicMock)

1. `test_condition_based_fires_when_stagnating`: `_should_fire` mit einer
   CONDITION_BASED-Strategie + `is_stagnating=True` → `True`. Mit `False` → `False`.
   (Die reine Trigger-Logik, das Herz von Naht 1.)
2. `test_condition_based_ignores_idle`: CONDITION_BASED-Strategie feuert NICHT
   wegen idle_minutes (nur wegen is_stagnating) — sauber getrennt von IDLE_BASED.
3. `test_is_stagnating_reaches_planner`: `think(is_stagnating=True)` erzeugt für
   eine registrierte CONDITION_BASED-Mission einen Intent (Durchreichung end-to-end).
4. `test_stagnation_mission_is_diagnostic`: Die registrierte Stagnations-Strategie
   nutzt einen LESENDEN Intent (cross_repo_diagnostic/sense_scan), NICHT einen
   schreibenden (kein heal/commit/pr). Verifiziert Sattva-Design (§20a).
5. `test_conscience_still_gates_stagnation_mission`: Eine durch Stagnation erzeugte
   Mission-Task läuft durch den Dispatch → das Gewissen (Kap. 3a) prüft sie.
   (Diagnostischer Intent → review_todos → erlaubt; beweist: Sicherung greift.)
6. `test_idle_based_regression`: bestehende IDLE_BASED-Missionen feuern weiter
   unverändert (Abwärtskompatibilität durch default is_stagnating=False).
7. `test_max_executions_caps_stagnation`: Anti-Thrashing — die Strategie feuert
   nicht öfter als max_executions_per_day, auch bei Dauer-Stagnation.
8. `test_stagnation_mission_has_high_priority`: Die registrierte Strategie hat
   priority=90 (Blindspot 2 — Diagnose vor Routine-Tasks).
9. `test_diagnosis_resets_stuck` (Blindspot 1, WIRKUNG): Nach Ausführung der
   Diagnose-Mission (die einen LLM-Turn durchläuft) ändern sich last_pattern + round
   → messbare Drift → ein folgender `is_stuck()`-Check ist NICHT mehr True (kein
   Endlos-Loop). Prüft die WIRKUNG (Reset), nicht nur dass die Mission feuert. Falls
   der Intent ein Null-Token-Detektor wäre (keine Pattern-Drift): dieser Test wäre
   rot und deckt es auf → dann reflektierenden Intent wählen.

---

## 5. WAS DIESER EINGRIFF BEWUSST NICHT TUT

- Keine schreibende/aggressive Stagnations-Reaktion (kein BLOCKED-Anprügeln) —
  Thrashing-Schutz, §20a.
- Kein Föderations-Hilferuf (das ist Stufe 2, eigene SENDE-Membran, §20b).
- Keine Tier-Eskalation (das ist Kap. 4 — 3b erzeugt die Diagnose-Mission, 4 gibt
  ihr das stärkere Modell, §20c).
- Keine neue Stagnationserkennung (is_stuck ist bereits makro-fähig, §19e).

---

## 6. ERWARTETE WIRKUNG

- Der Steward reagiert erstmals auf ANHALTENDE Stagnation (nicht nur mikro im Turn):
  er hält inne und startet eine besonnene Diagnose (Sattva).
- Der Regelkreis schließt sich: Erde (Kap.1, kein stiller Tod) + Wasser (Kap.2,
  Stadt-Signale empfangen) + Gewissen (Kap.3a, autorisiert) + Wille (Kap.3b,
  reagiert auf Stagnation) = ein Steward, der wahrnimmt, urteilt und besonnen
  handelt. **Nach diesem Kapitel ist der geschlossene Regelkreis erreicht → Merge +
  Defibrillator werden sinnvoll.**
- CONDITION_BASED ist vollendet — die Verfassung kann jetzt bedingungsbasiert
  feuern, nicht nur zeit-/leerlaufbasiert.

---

*Ende Kap-3b-Spezifikation. Vor Übergabe: Pre-Flight P2-P6 (LAW/REALITY-Dopplung +
KsetraJna-Zugriff verifizieren) + Bestätigung des diagnostischen Intents
(cross_repo_diagnostic vs. sense_scan).*
