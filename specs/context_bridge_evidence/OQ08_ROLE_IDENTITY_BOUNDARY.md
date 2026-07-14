# OQ-08 — ROLLEN- UND IDENTITÄTSGRENZE

> **Status:** EVIDENCE COMPLETE — externer Consumer- und Runtime-Rollenvertrag entschieden
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `85c4799b3f045f53012679f2c6ba6a960270b530`
> **Steward-Tree:** `5e79596e3adf985f8b366292fecc1ab51b339504`
> **Conventions-Blob:** `29829be4f77dcaebf970a8ee872de299f0357f1c`
> **CLAUDE-Blob:** `e0f9f1a235cfece134d06e9b683f3386486a7f75`
> **Scope:** Root-Consumer, Steward-Runtime-Prompt, Subagent-Rolle, statische Orientierung,
> Focus-Kompression und Identitätsformulierung. Keine Text-, Code- oder Workflowänderung.

---

## 1. Fragestellung

Die Formulierung „You are Steward“ kann in zwei sehr verschiedenen Kontexten stehen:

1. als Persona eines intern laufenden Steward-Runtime-Agenten,
2. als Repository-Anweisung an einen externen Claude-/Codex-Engineering-Agenten.

OQ-08 darf diese Rollen nicht aus dem Projektnamen ableiten. Entscheidend sind reale
Consumer und Call-Sites.

---

## 2. Vier getrennte Identitäten

Der sichere Vertrag unterscheidet:

| Identität | Bedeutung | Quelle |
|---|---|---|
| Projektidentität | Das Repository enthält die Steward-Engine | reviewter Repository-Vertrag und Code |
| Runtime-Identität | der tatsächlich laufende StewardAgent beziehungsweise Federation-Node | Runtime-Code, Node-/Federation-State und kryptographische Identität |
| Consumer-Rolle | externer Claude-/Codex-Agent, der das Repository analysiert oder ändert | Plattform plus Root-Repository-Instruktionen |
| Operatorrolle | Mensch beziehungsweise höherwertiger aktueller Auftraggeber | externer Sessionauftrag |

Keine dieser Identitäten darf sprachlich still in eine andere überführt werden.

---

## 3. Positive Consumer-Evidence

OQ-11 belegt:

- Codex lädt Root-`AGENTS.md` als Repository-Guidance.
- Claude Code lädt Root-`CLAUDE.md` als Projektmemory/-Guidance.
- Beide Dateien werden von extern gestarteten Engineering-Sessions entdeckt.
- Root-Guidance ist Verhaltenskontext, keine Runtime-Node-Identität.

Die Context-Bridge soll genau diese beiden externen Consumer bedienen. Daraus folgt nicht,
dass der Consumer die Softwareinstanz wird, die er wartet.

Ein Engineering-Agent arbeitet **an Steward**. Er ist nicht automatisch **Steward**.

---

## 4. Positive Runtime-Evidence

### 4.1 StewardAgent

`steward/agent.py` verwendet als aktuellen Default-Systemprompt:

`Software agent. Use tools to complete tasks. Read before edit. Test after change.`

`_build_system_prompt()` ergänzt nur das Working Directory. Der Constructor injiziert
weder `.steward/conventions.md` noch `CLAUDE.md` in diesen Defaultprompt.

Zur Laufzeit werden Senses, Gaps, Sessionzusammenfassung und wenige dynamische Felder
angehängt. Die Root-Datei ist nicht Teil dieses Promptpfads.

### 4.2 Project-Instruction-Loader

`_load_project_instructions()` kennt `.steward/instructions.md` und `CLAUDE.md`, besitzt
aber keine Produktions-Call-Site. Nur seine Definition und direkte Unit-Tests existieren.

Das bestätigt:

> Die aktuellen Root-Dateien sind nicht der Persona- oder Systemprompt des internen
> StewardAgenten.

Ob dieser tote Loader später entfernt, isoliert oder anders verdrahtet wird, gehört zu
OQ-09. OQ-08 darf ihn nicht vorsorglich aktivieren.

### 4.3 Interner Subagent

`steward/tools/sub_agent.py` erzeugt einen eigenen generischen Prompt: „You are a focused
sub-agent handling a specific task.“ Auch dieser Pfad lädt den Root-Vertrag nicht und
behauptet keine Federation-Node-Identität.

---

## 5. Aktuelle problematische Quelle

`.steward/conventions.md` beginnt im Abschnitt `## Identity` mit:

- „You are Steward — an autonomous superagent engine ...“
- „You are the ARCHITECT ...“
- „Your North Star ...“

Die Datei kommentiert selbst, sie werde verbatim in das generierte `CLAUDE.md` übernommen
und sei das, was ein kalter Repo-Consumer lese.

Damit adressiert sie grammatisch den externen Consumer, beschreibt semantisch aber die
Runtime-Engine. Sie weist dem Engineering-Agenten zusätzlich Architektur- und North-Star-
Autorität zu, die aus dessen Plattform-/Operatorauftrag stammen müsste.

Diese Formulierung ist für kanonische Root-Dateien unzulässig.

---

## 6. Intermittierende Produktionswirkung

`OrientationStage` lädt `.steward/conventions.md` und verhält sich focusabhängig:

- hoher Fokus: vollständige Datei verbatim,
- mittlerer Fokus: Überschriften, Tabellenzeilen und ausgewählte Bulletformen,
- niedriger Fokus: nur Abschnittsüberschriften.

Die Tests verlangen ausdrücklich, dass bei niedrigem Fokus `## Identity` erhalten bleibt,
„You are Steward“ aber verschwindet.

Der gepinnte Produktionsblob zeigt genau diesen Zustand: `CLAUDE.md` enthält eine leere
Überschrift `## Identity`, aber keinen Rollentext. Hoher Fokus kann den problematischen
Text später wieder vollständig publizieren.

Die Rollenwirkung ist dadurch nicht nur falsch, sondern instabil: Sie ändert sich mit
Health-, Context-Pressure- und Budgetsignalen.

---

## 7. Verfassungskern darf nicht komprimieren

OQ-18 hat `.steward/conventions.md` als einzigen vorhandenen Kandidatenpfad für den
statischen Verfassungskern identifiziert, den aktuellen Inhalt aber nicht freigegeben.

Ein C0-Verfassungskern muss in jedem kanonischen Modus vollständig und unverändert
vorhanden sein. Dazu gehören mindestens:

- Consumer-Rolle,
- Projekt-/Runtime-Trennung,
- Trust- und Autoritätsgrenzen,
- PUBLIC_SAFE-/Injection-Grundgrenze,
- Phase-1-read-only-Schutzregel,
- grundlegende Operationsverbote.

Optionale Architekturorientierung, Tabellen und Verzeichnisübersichten dürfen später
separat komprimierbar sein. C0 selbst darf weder durch Fokus reduziert noch durch leere
Überschriften simuliert werden.

Der C0-Kern muss deshalb klein genug konstruiert sein, um unter jedem zulässigen
Root-Budget vollständig zu passen. Truncation oder Focus-Kompression ist kein Fallback.

---

## 8. Verbindlicher Root-Rollenvertrag

Die spätere statische Root-Formulierung muss semantisch ausdrücken:

1. Dieses Repository enthält Steward, eine autonome Agenten-/Federation-Engine.
2. Der Leser ist ein externer Engineering- oder Maintenance-Agent, der an diesem
   Repository arbeitet.
3. Plattform-, Developer- und aktueller Operatorauftrag bestimmen seine konkrete Rolle
   und Handlungsbefugnis.
4. Der Consumer ist nicht der laufende StewardAgent oder Federation-Node.
5. Er übernimmt keine Runtime-Agent-ID, kein Schlüsselpaar, keine Signaturautorität und
   keine Peer-Persona.
6. Runtime-State und Federation-Nachrichten sind beobachtete Projektdaten, nicht eigene
   Erinnerungen oder Anweisungen des Consumers.
7. Steward-Eigenschaften und North Star werden in dritter Person als Projekteigenschaften
   beschrieben.

Die konkrete Endformulierung wird erst in Feature-Spec 00 reviewt. OQ-08 entscheidet die
Semantik, nicht den Wortlaut aus dem Chat.

---

## 9. Verbotene Rollenformulierungen

In extern konsumierten Root-Dateien sind ohne ausdrücklich belegten Sonderconsumer
unzulässig:

- `You are Steward`,
- `You are the Steward runtime/node`,
- `Your agent_id is ...`,
- `Your federation peers ...`,
- `Your North Star ...`, wenn damit das Projektziel gemeint ist,
- jede Aufforderung, als Steward zu signieren, zu claimen oder Federation-Nachrichten in
  eigener Identität zu senden,
- dynamische Rollenänderung durch Tasks, Issues, Senses oder Federation-Text.

Zulässig sind klare Projektformulierungen wie „Steward is ...“ oder „This repository
contains ...“ sowie eine explizite externe Engineering-Rolle.

---

## 10. Runtime-Persona bleibt separater Vertrag

OQ-08 behauptet nicht, der interne StewardAgent dürfe niemals „You are Steward“ erhalten.
Für einen nachweislich internen Runtime-Systemprompt könnte eine solche Persona korrekt
sein.

Das wäre jedoch ein anderer Consumervertrag mit anderer Trust-, Prompt- und
Identitätsquelle. Er darf nicht über Root-`CLAUDE.md`/`AGENTS.md` und nicht als Nebenwirkung
der Context-Bridge eingeführt werden.

Der bestehende minimale Runtimeprompt bleibt durch OQ-08 unangetastet.

---

## 11. Dynamische Daten und Impersonation

Die Rollenformulierung liegt ausschließlich in C0. Dynamische Daten dürfen:

- den aktuellen Runtime-Agenten und seine Zustände beschreiben,
- Identity-Konflikte als C1-Beobachtung melden,
- Federation-Peers aggregiert darstellen.

Sie dürfen nicht:

- den externen Consumer umbenennen,
- aus `agent_id`, Repo-Name oder Peerclaim eine Persona erzeugen,
- den Consumer zum Besitzer von Schlüsseln oder Nachrichten erklären,
- einen Operatorauftrag durch ein Runtime-Signal ersetzen.

Ein Identity-Konflikt im System ist ein Diagnoseobjekt, keine Einladung zur
Identitätsübernahme.

---

## 12. Safe-Fallback-Vertrag

Auch der statische Safe Fallback muss die Rollen sauber trennen. Fehlt oder versagt der
normale Constitution-Renderer, darf ein Fallback nicht auf das alte „You are Steward“
zurückfallen.

Der minimale Fallback benötigt mindestens:

- Repository-Identität in dritter Person,
- externe Engineering-Consumer-Rolle,
- keine Runtime-/Node-Impersonation,
- dynamischer Zustand unavailable,
- aktueller Operatorauftrag nicht in Repository-Context enthalten.

---

## 13. Adversariale Testfolgen

Feature-Spec 00/01 benötigt mindestens:

1. Beide Root-Dateien enthalten keinen Satz `You are Steward`.
2. Beide beschreiben Steward als Projekt/Runtime in dritter Person.
3. Externer Consumer wird als Engineering-/Maintenance-Agent bezeichnet.
4. Runtime-Agent-ID, Private-Key- oder Peerclaim-Daten ändern niemals die Consumer-Rolle.
5. C0-Rollenkern bleibt bei minimalem Budget vollständig vorhanden.
6. Health-, Context-Pressure- und Focus-Wechsel entfernen oder verändern C0 nicht.
7. Optionale Architekturorientierung kann komprimieren, ohne C0-Überschriften leer
   zurückzulassen.
8. Safe Fallback besitzt denselben Rollenvertrag.
9. Internes `StewardAgent._BASE_SYSTEM_PROMPT` bleibt durch den Root-Publisher unverändert.
10. `_load_project_instructions()` wird nicht beiläufig als Teil des Root-Features
    aktiviert.
11. Ein Testdouble mit „You are Steward“ beweist keinen Produktionsconsumer.
12. Byteidentische Claude-/Codex-Dateien tragen dieselbe Rollenbedeutung.

---

## 14. Nicht belegbare Annahmen

OQ-08 legt nicht fest:

- ob der interne Runtime-Agent künftig eine explizite Steward-Persona benötigt,
- den finalen englischen Wortlaut des C0-Kerns,
- wie C0 und optionale Architekturorientierung syntaktisch in derselben Quelldatei
  markiert werden,
- ob ein künftiger spezieller interner Consumer eine eigene nicht-Root-Promptquelle
  erhält.

Diese Punkte gehören in Feature-Spec 00 oder einen separaten Runtime-Prompt-Vertrag.

---

## 15. Entscheidung

OQ-08 ist geschlossen:

1. „You are Steward“ ist für externe Root-Consumer nicht zulässig.
2. Projekt-, Runtime-, Consumer- und Operatoridentität bleiben getrennt.
3. Root-Consumer ist ein externer Engineering-/Maintenance-Agent unter höherwertigem
   Plattform- und Operatorauftrag.
4. Steward und sein North Star werden als Projekteigenschaften in dritter Person
   beschrieben.
5. Root-Dateien verleihen keine Node-, Schlüssel-, Signatur- oder Federation-Persona.
6. Der minimale C0-Rollenkern ist niemals focus-/health-/budgetkomprimierbar.
7. Optionale Architekturorientierung darf separat komprimieren.
8. Der aktuelle interne StewardAgent-Prompt und der tote Instruction-Loader bleiben
   außerhalb dieses Changes.

Diese Entscheidung autorisiert keinen Textpatch, keine Promptänderung und keine
Implementation. G0 bleibt offen.
