# KAPITEL 2 — DETAILSPEZIFIKATION: Die Membran-Kopplung (Wasser)

> **Charakter:** Ausführbare Spezifikation für Claude Code. Baut DIREKT auf
> Kapitel 1 (Sentinel/BLOCKED, Commit `dd90bed485`) auf.
> **Vorbedingung:** Kap. 1 ist committed; Befund §4i/§4j/§12 + dieser Vorbericht
> gelesen.
> **Ziel:** Die 52 (und künftigen) `bottleneck_escalation`-Signale der Stadt
> endlich verarbeiten, statt sie als BLOCKED liegen zu lassen. Das „Flussbett
> graben”, in das das Wasser (Membran-Signale) fließt.
> **Daten-Beweis:** §12 — 52 reale Bottlenecks empfangen, alle still begraben.

-----

## 0. ARCHITEKTUR-PRINZIP (dharmisch + technisch, NICHT verhandelbar)

**Der Handler führt NICHT aus — er erkennt und meldet.** Alle bestehenden
Handler (`execute_heal_repo` etc.) sind reine deterministische Detektoren:
`() -> str | None`, 0 Tokens, geben einen Problem-String zurück, die eigentliche
Aktion macht die abgesicherte Pipeline (`AutonomyEngine`), die durch den aktiven
Narasimha/ToolSafetyGuard läuft (§4h).

→ **Konsequenz für Ahankara/Sicherheit (Geminis Anforderung, gelöst durch das
vorhandene Muster):** Der Bottleneck-Handler übersetzt das `requested_action: "fix"` der Stadt NICHT in eine Ausführung. Er erzeugt nur einen Problem-String
(„Stadt X meldet kaputte Contracts in Repo Y”). Ob/wie gehandelt wird, entscheidet
die bestehende Pipeline mit ihrer Autorisierung. **Die Stadt liefert das ANLIEGEN,
der Steward behält die HANDLUNGSHOHEIT.** Das Muster erzwingt diese Trennung
bereits — wir bauen sie nicht neu, wir nutzen sie.

-----

## 1. PRE-FLIGHT — was Claude Code ZUERST verifiziert (vor Code)

|# |Check                                                                          |Erwartung                                                           |Wenn anders →                                                           |
|--|-------------------------------------------------------------------------------|--------------------------------------------------------------------|------------------------------------------------------------------------|
|P1|`git log --oneline -1`                                                         |HEAD = `dd90bed485` (Kap. 1)                                        |Erst Kap. 1 sicherstellen                                               |
|P2|`grep -n "_parse_federated_task_description" steward/autonomy.py`              |Funktion existiert (parst description key:value)                    |Falls fehlt: Payload-Parsing-Strategie neu klären                       |
|P3|`grep -n "_execute_heal_repo|def.*heal" steward/autonomy.py`                   |Die echte Heal-Pipeline (nicht nur Detektor) existiert              |Ziel-Pipeline für Bottleneck-Routing bestimmen                          |
|P4|Baseline grün (außer bekanntem test_briefing)                                  |wie Kap. 1                                                          |sonst Baseline klären                                                   |
|P5|`grep -n "handler(" steward/intent_handlers.py` + wie `autonomy.py:229` aufruft|Klärt, ob Payload den Handler erreicht (Handler-Signatur-Frage, §2b)|Entscheidungsbaum in §2b (Fall A/B) befolgen — Ergebnis ZUERST berichten|

-----

## 2. DER EINGRIFF

### 2a. Intents registrieren (REALITY: steward/intents.py)

In `TaskIntent`-Enum (nach den Fed-Monitor-Intents) hinzufügen:

```python
    # --- Membran-Signale (eingehend von Föderation/Stadt) ---
    BOTTLENECK_ESCALATION = "bottleneck_escalation"   # agent-city brain_health/critique
    GOVERNANCE_BOUNTY = "governance_bounty"           # agent-world Legislator
```

> **Scope-Entscheidung:** `CITY_REPORT` NICHT als ausführbaren Intent aufnehmen —
> City-Reports sind Zustandsmeldungen (gespeichert, nicht „bearbeitet”). Sie
> sollen NICHT als Task im KARMA-Dispatch landen. (Falls sie es doch tun: Kap. 1
> fängt sie sicher als BLOCKED — kein stiller Tod. Aber sie gehören nicht hierher.)
> Begründung dokumentieren, damit ein späterer Agent nicht „den dritten Intent
> vergessen” denkt.

### 2b. Handler schreiben (REALITY: steward/intent_handlers.py)

Nach dem Muster der bestehenden Detektoren — reine Übersetzung Payload → Problem-String:

```python
def execute_bottleneck_escalation(self, task: object = None) -> str | None:
    """Membran-Signal der Stadt: ein Bottleneck (kaputte Contracts) wurde
    eskaliert. Detektor-Muster: übersetzt das Anliegen in einen Problem-String;
    die Heilung übernimmt die abgesicherte Pipeline (kein blindes requested_action).
    0 LLM-Tokens.
    """
    # Payload kommt aus der Task-Description (key:value), via
    # _parse_federated_task_description. Falls task/description nicht verfügbar,
    # konservativ einen generischen Problem-String liefern (NICHT None — sonst
    # wäre es wieder ein stiller Erfolg).
    if task is None:
        return "Bottleneck escalation received but task context unavailable — needs review"
    meta = _parse_federated_task_description(getattr(task, "description", "") or "")
    repo = meta.get("target_repo", "unknown-repo")
    return f"City bottleneck escalation: degraded contracts in {repo} — route to heal pipeline"

def execute_governance_bounty(self, task: object = None) -> str | None:
    """Membran-Signal von agent-world Legislator: Policy-Verstoß als Bounty.
    Detektor-Muster wie oben. 0 Tokens.
    """
    if task is None:
        return "Governance bounty received but task context unavailable — needs review"
    meta = _parse_federated_task_description(getattr(task, "description", "") or "")
    repo = meta.get("target_repo", "unknown-repo")
    return f"Governance bounty: policy violation in {repo} — route to heal pipeline"
```

> ⚠️ **OFFENE DESIGN-FRAGE — MUSS in Pre-Flight P5 als Entscheidungsbaum gelöst
> werden (Gemini-Veto übernommen):** Der `task: object = None`-Default oben ist
> eine FALLE: Wenn der Dispatcher die Handler strikt als `return handler()` (ohne
> Argument) aufruft, läuft der Handler IMMER in den „task unavailable”-Zweig —
> wir erkennen das Signal, verlieren aber den Payload (das Repo). Ein halber
> Sieg, der wie ein ganzer aussieht. **Das ist NICHT akzeptabel.**
> 
> Claude Code MUSS vor 2b verifizieren und nach diesem Baum handeln:
> 
> ```
> Prüfe: Wie ruft dispatch() den Handler auf? (grep "handler(" intent_handlers.py)
> und wie ruft autonomy.py:229 dispatch_intent auf — wird ein task-Objekt
> durchgereicht?
> 
> FALL A — Payload erreicht den Handler NICHT (Dispatcher ruft handler() ohne Arg):
>   1. ZUERST Blast-Radius bestätigen: dispatch() + dispatch_intent() haben laut
>      Kap.-1-Audit GENAU EINEN Aufrufer. Verifiziere erneut:
>      grep -rn "\.dispatch(\|dispatch_intent" steward/ | grep -v hooks.dispatch
>   2. NUR wenn weiterhin genau 1 Aufrufer: passe die Kette minimal-invasiv an,
>      sodass das task-Objekt durchgereicht wird:
>      - autonomy.py: dispatch_intent(intent, task) → handlers.dispatch(intent, task)
>      - intent_handlers.py dispatch(intent, task=None): handler(task) für die
>        neuen Handler; bestehende argument-lose Handler weiterhin handler()
>        aufrufen (Abwärtskompatibilität! NICHT alle Handler-Signaturen ändern).
>   3. Falls >1 Aufrufer auftaucht: STOPP, an uns berichten.
> 
> FALL B — Payload steckt bereits im intent/title/description erreichbar:
>   Handler liest den Payload aus dem bereits verfügbaren Kontext (z.B. über den
>   TaskManager via task-ID, oder description ist schon zugänglich). Dann KEINE
>   Signaturänderung nötig.
> 
> In BEIDEN Fällen: Berichte die gewählte Lösung ZUERST, bevor du 2b final baust.
> ```
> 
> → Die Handler-Signatur in 2b an das Ergebnis anpassen. NICHT raten, NICHT den
> `=None`-Default als „gelöst” betrachten.

### 2c. Handler registrieren (REALITY: steward/intent_handlers.py, dispatch-Dict)

```python
    TaskIntent.BOTTLENECK_ESCALATION: self.execute_bottleneck_escalation,
    TaskIntent.GOVERNANCE_BOUNTY: self.execute_governance_bounty,
```

### 2d. Verbindung zur Heal-Pipeline (REALITY: steward/autonomy.py) — bedingt

Prüfen (P3), wie ein Problem-String aus `execute_heal_repo` heute zur echten
Heilung führt (`_execute_heal_repo`?). Falls Bottleneck dieselbe Pipeline nutzen
soll: sicherstellen, dass der Problem-String aus 2b vom selben Mechanismus
aufgegriffen wird. **Falls das nicht trivial ist: in dieser Iteration NUR
Detektion (Problem-String) liefern; das Routing in die Heilung ist ein separater,
kleiner Folgeschritt.** (Embryonaler Vorbehalt: erst Signal sichtbar+benannt
machen, dann Heilung verdrahten.)

-----

## 3. DUALE VERIFIKATIONSTABELLE

|Eingriff       |LAW (protocols)|REALITY (steward)                       |Tests                            |
|---------------|---------------|----------------------------------------|---------------------------------|
|2a Intents     |—              |steward/intents.py                      |Enum enthält beide neuen Werte   |
|2b Handler     |—              |steward/intent_handlers.py              |je 1 Test: Payload→Problem-String|
|2c Dispatch    |—              |steward/intent_handlers.py dispatch-Dict|dispatch(BOTTLENECK) ≠ NO_HANDLER|
|2d Heal-Routing|—              |steward/autonomy.py (bedingt)           |E2E falls verdrahtet             |


> LAW-Spalte leer: rein steward-intern, kein protocols/substrate-Dual.

-----

## 4. NEUE TESTS

1. `test_bottleneck_intent_registered`: `TaskIntent["BOTTLENECK_ESCALATION"]` existiert.
1. `test_governance_bounty_intent_registered`: dito.
1. `test_bottleneck_handler_returns_problem_not_sentinel`: Dispatch eines
   BOTTLENECK-Intents gibt einen Problem-String zurück, NICHT `NO_HANDLER`.
1. `test_bottleneck_handler_extracts_repo`: Handler liest `target_repo` aus der
   Description korrekt aus.
1. **Regression (Kap. 1 bleibt intakt):** ein WIRKLICH unbekannter Intent gibt
   weiterhin `NO_HANDLER` → BLOCKED.
1. **E2E (falls 2d verdrahtet):** simulierte Bottleneck-Task → Dispatch →
   Problem-String → (Heal-Pipeline aufgerufen).

-----

## 5. WAS DIESER EINGRIFF BEWUSST NICHT TUT

- **Führt kein `requested_action: "fix"` blind aus** (§0 — Handlungshoheit bleibt
  bei der abgesicherten Pipeline).
- **Behandelt CITY_REPORT nicht** als ausführbaren Intent (Zustandsmeldung).
- **Reaktiviert KEINE GitHub-Workflows** — das ist der spätere „Defibrillator”,
  separat und nach dem Merge von Kap. 1+2.
- **Baut kein Live-Monitoring** — die Boten schlafen (§12b); getestet wird mit
  historischen/simulierten Payloads.

-----

## 6. ERWARTETE WIRKUNG

- Eingehende `bottleneck_escalation` werden zu sichtbaren, benannten Problemen
  statt zu BLOCKED (Kap. 1) oder still begraben (Vor-Zustand).
- Zusammen mit Kap. 1: der vollständige Pfad Stadt-Ruf → Erkennung → (Heilung)
  ist geschlossen. Erde + Wasser stehen.
- Bereit für den Merge von Kap. 1+2 und danach die Workflow-Reaktivierung.

-----

*Ende Kapitel-2-Spezifikation. KRITISCH vor Implementierung: Pre-Flight P5 (Handler-
Signatur mit/ohne task-Param) — davon hängt 2b ab. Danach Claude Code wie bei
Kap. 1: implementieren, vollständiger Testlauf (mit –timeout!), Bericht, STOPP
vor Commit.*