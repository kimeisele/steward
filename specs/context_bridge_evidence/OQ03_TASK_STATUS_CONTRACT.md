# OQ-03 — TASKSTATUS-TYP- UND GRENZVERTRAG

> **Status:** EVIDENCE COMPLETE — Runtime- und Serialisierungsvertrag entschieden
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `b7e3aa3ca519bd1b3cfe233aa2bc7a4fcb9a31cb`
> **Steward-Tree:** `a6043e8fcdbc8dcd673221e3e41412e3870729ec`
> **Context-Blob:** `32843a45fccd3bd57566ff3779168d8ff87bc068`
> **Produktionsrun:** `29328240516` / Heartbeat `#5353`
> **Steward-Protocol-Head im Produktionsrun:**
> `34a8a0efc25c15ef7c07dd4fb50aeb2510c071e8`
> **Steward-Protocol-Tree:** `48897cf33b748855a3d84538357108083bb70d5c`
> **Scope:** TaskStatus-Definition, TaskManager-Erzeugung, Persistenz, Update-Caller,
> Context-Serialisierung und Produktionspayload. Keine Code- oder Workflowänderung.

---

## 1. Fragestellung

OQ-03 fragt, welchen Status der echte TaskManager tatsächlich liefert. Die Antwort muss
die Schichten trennen:

- Runtime-Objekt im TaskManager,
- persistierter Taskzustand,
- normalisierter Context-Output,
- mögliche Testdoubles oder Legacy-Inputs.

Ein Vergleich gegen zufällig gewählte Stringliterale ist kein Typvertrag.

---

## 2. Gepinnter Cross-Repo-Produktionsbeweis

Der Produktionsrun `29328240516`, der Steward-Commit
`b7e3aa3ca519bd1b3cfe233aa2bc7a4fcb9a31cb` erzeugte, protokolliert beim Checkout von
`kimeisele/steward-protocol` den Commit
`34a8a0efc25c15ef7c07dd4fb50aeb2510c071e8`.

Der Workflow setzt für diesen Checkout keinen `ref`. Er holt mit `fetch-depth: 1` den
jeweils aktuellen Default-Branch `main` und installiert ihn editable. Der Steward-Commit
allein reproduziert den verwendeten Taskvertrag deshalb nicht.

Diese Evidence pinnt beide Repositories. Künftige Produktionsprovenance muss das ebenfalls
tun oder einen anderweitig unveränderlichen Protocol-Vertrag belegen.

---

## 3. Kanonische Definition

Am gepinnten Protocol-Commit ist `TaskStatus` ein `str, Enum` mit uppercase Werten:

| Enum | Wert | Lifecycle-Klasse |
|---|---|---|
| `PENDING` | `"PENDING"` | aktiv |
| `IN_PROGRESS` | `"IN_PROGRESS"` | aktiv |
| `COMPLETED` | `"COMPLETED"` | terminal |
| `FAILED` | `"FAILED"` | terminal |
| `BLOCKED` | `"BLOCKED"` | aktiv, aber separat blockiert darzustellen |
| `TIMEOUT` | `"TIMEOUT"` | terminal |
| `ARCHIVED` | `"ARCHIVED"` | terminal |

`TaskStatus.is_active()` klassifiziert `PENDING`, `IN_PROGRESS` und `BLOCKED` als aktiv.
`TaskStatus.is_terminal()` klassifiziert `COMPLETED`, `FAILED`, `TIMEOUT` und `ARCHIVED`
als terminal.

`RUNNING` ist nur ein Eingabealias für `IN_PROGRESS`; es ist kein zusätzlicher
kanonischer Persistenzwert. `normalize_status()` kann Legacy-Schreibweisen und
Groß-/Kleinschreibung normalisieren.

---

## 4. Runtime-Vertrag des echten TaskManagers

Der gepinnte `TaskManager` hält `tasks: Dict[str, Task]`. Das `Task`-Dataclass-Feld ist
als `TaskStatus` typisiert und startet mit `TaskStatus.PENDING`.

Positive Pfade:

1. `add_task()` erzeugt neue Tasks mit `TaskStatus.PENDING`.
2. `_load_tasks()` liest den persistierten String über `TaskStatus(...)` zurück in den
   Enum.
3. `update_task()` übernimmt den neuen Status und ruft danach die Taskvalidierung auf.
4. `_validate_status()` akzeptiert ausschließlich `isinstance(status, TaskStatus)`.
5. Die untersuchten Steward-Produktionscaller übergeben bei Statusänderungen
   `TaskStatus.PENDING`, `.IN_PROGRESS`, `.COMPLETED`, `.FAILED` oder `.BLOCKED`.

Damit gilt für den echten, erfolgreich validierten TaskManager am gepinnten Vertrag:

> `task.status` ist zur Runtime ein `TaskStatus`-Enum, kein beliebiger String.

Ein Testdouble kann davon abweichen. Es beweist dann aber nicht die Produktionssemantik.

---

## 5. Persistenz- und Context-Grenze

`Task.to_dict()` serialisiert `self.status.value`. In `.vibe/state/tasks.json` liegt der
Status daher als kanonischer uppercase String.

Der aktuelle Context-Reader übernimmt dagegen das Enum-Objekt direkt in sein Dict. Weil
`TaskStatus` von `str` erbt, serialisiert der JSON-Encoder diesen Wert ebenfalls als
uppercase String.

Die Schichten sind daher bewusst verschieden:

| Schicht | Repräsentation |
|---|---|
| TaskManager Runtime | `TaskStatus`-Enum |
| Task-Persistenz | uppercase JSON-String |
| aktuelles Context-Pythonmodell | derzeit Enum-Objekt ohne explizite Normalisierung |
| `.steward/context.json` | uppercase JSON-String |

Das ist keine zufällige Runtime-Mischung, sondern eine Enum-zu-String-Grenze. Der spätere
Context-Normalizer muss diese Grenze explizit besitzen und darf sie nicht Python-JSON-
Nebenwirkungen überlassen.

---

## 6. Exakter Produktionsfehler

`steward/context_bridge.py:349-371` bezeichnet das Ergebnis als `pending`, iteriert aber
über `task_manager.tasks` und schließt nur folgende lowercase Strings aus:

- `"done"`,
- `"completed"`,
- `"archived"`.

Ein Runtimewert `TaskStatus.COMPLETED` hat den Stringwert `"COMPLETED"` und ist nicht
gleich `"completed"`. Dasselbe gilt für `ARCHIVED`. `FAILED` und `TIMEOUT` werden vom
Filter überhaupt nicht als terminal behandelt.

Der gepinnte Produktionspayload beweist die Wirkung: Unter `tasks.pending` stehen sechs
Einträge mit Status `"COMPLETED"` neben vier tatsächlich `"PENDING"` Einträgen.

Das ist weder ein Cacheartefakt noch nur eine theoretische Enum-Frage. Codevertrag und
Produktionswirkung stimmen überein.

---

## 7. Verbindliche Normalisierung

Für die spätere Feature-Spec gilt:

1. Der Reader akzeptiert vom echten TaskManager nur `TaskStatus`-Instanzen.
2. Er normalisiert einmal explizit über den kanonischen Enumwert, nicht über lowercase
   Literale und nicht über `str(status)`.
3. Bekannte Werte werden in getrennte Klassen überführt:
   `pending`, `in_progress`, `blocked`, `completed`, `failed`, `timeout`, `archived`.
4. `BLOCKED` darf als aktiv gezählt werden, aber nicht als normal ausführbares Pending
   verschleiert werden.
5. Terminale Werte dürfen niemals im Current-Work-/Pending-Aggregat erscheinen.
6. Ein unbekannter Enum- oder Stringwert wird nach OQ-13 `unsupported`; er wird nicht
   automatisch aktiv, terminal oder leer.
7. Legacy-Strings dürfen nur an einer ausdrücklich versionierten Eingabegrenze über den
   kanonischen Protocol-Normalizer behandelt werden.
8. Freie Tasktitel bleiben nach OQ-12 untrusted und default-deny; der Statusvertrag
   autorisiert keine Titel als Agentenagenda.

Die Bridge sollte für Root-Context zunächst getrennte, validierte Statusaggregate
erzeugen. Ob und welche einzelnen Tasks später dargestellt werden dürfen, benötigt
zusätzlich den Trust-, Sanitization- und Prioritätsvertrag der Feature-Spec 03.

---

## 8. Cross-Repo-Kompatibilitätsgrenze

Der aktuelle Heartbeat-Workflow pinnt `steward-protocol` nicht. Dadurch kann ein
unveränderter Steward-Commit in einem späteren Lauf gegen eine andere Enumdefinition,
Loadersemantik oder Validatorversion laufen.

Vor Implementation muss Feature-Spec 03 deshalb einen reproduzierbaren Vertrag wählen:

- entweder den verwendeten Protocol-Commit in Workflow und Provenance unveränderlich
  pinnen,
- oder eine explizite kompatible Protocol-Schema-/Versionsgrenze validieren und bei
  unbekannter Semantik `unsupported`/fail-closed reagieren.

Nur ein unbeschränktes Dependency-Requirement und ein Checkout von `main` reichen nicht.
Diese Entscheidung ist größer als ein Statusfilter und darf nicht im Filterpatch
versteckt werden.

---

## 9. Nicht belegbare Annahmen

Nicht behauptet wird:

- dass künftige Protocol-Commits dieselbe Enumdefinition behalten,
- dass beliebige Testmocks den echten TaskManagervertrag erfüllen,
- dass historische lowercase Taskdateien vom aktuellen Loader zuverlässig migriert
  werden,
- dass jeder aktive Task automatisch Current Work oder Operatoragenda ist,
- dass Tasktitel ohne zusätzlichen Sicherheitsvertrag publizierbar sind.

Insbesondere nutzt `_load_tasks()` direkt `TaskStatus(value)`, nicht den vorhandenen
Legacy-Normalizer. Ein unbekannter oder lowercase Persistenzwert kann den Loadpfad
fehlschlagen lassen; OQ-13 verlangt dafür `invalid/unsupported` statt gesunder Leere.

---

## 10. Testfolgen

Die spätere Feature-Spec benötigt mindestens echte Contract-Tests mit dem gepinnten
Protocol-Paket:

1. Runtime-Tasks für jeden kanonischen Enumwert.
2. Persistenz-Roundtrip Enum → uppercase JSON → Enum.
3. `COMPLETED`, `FAILED`, `TIMEOUT` und `ARCHIVED` fehlen vollständig im offenen
   Work-Aggregat.
4. `BLOCKED` erscheint getrennt von `PENDING` und `IN_PROGRESS`.
5. `RUNNING` wird nur an der zulässigen Legacy-Grenze zu `IN_PROGRESS`.
6. unbekannter Status erzeugt `unsupported`, nicht `pending`.
7. ein String-Mock darf keinen grünen Produktions-Contract-Test ersetzen.
8. Provenance nennt den tatsächlich installierten Protocol-Commit oder die validierte
   kompatible Schema-/Versionsgrenze.

---

## 11. Entscheidung

OQ-03 ist geschlossen:

- Der echte TaskManager liefert zur Runtime `TaskStatus`-Enums.
- Persistenz und JSON-Context tragen kanonische uppercase Stringwerte.
- Der bestehende lowercase-Negativfilter ist typfalsch und in Produktion widerlegt.
- Normalisierung erfolgt einmal an der Bridge-Grenze; unbekannte Werte sind
  `unsupported`.
- Statusaggregation und freie Tasktexte bleiben getrennte Verträge.
- Der unpinned Protocol-Checkout ist eine reproduzierbarkeitsrelevante
  Cross-Repo-Grenze und muss vor Implementation explizit geschlossen werden.

Diese Entscheidung autorisiert keinen Codepatch und gibt G0 nicht frei.
