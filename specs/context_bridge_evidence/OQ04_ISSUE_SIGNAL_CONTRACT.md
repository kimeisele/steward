# OQ-04 — ISSUE-SIGNAL-, TRUST- UND PRIORITÄTSVERTRAG

> **Status:** EVIDENCE COMPLETE — Eligibility, Begrenzung und Rangfolge entschieden
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `b2b633cb7f7e9e0f0b2164527034c2426541b7a7`
> **Steward-Tree:** `eed3c2b6a9f15d40323aa9b852633787d29b41de`
> **Context-Blob:** `4908ad1581e5f13cf11b5dac7196640f14bb28f8`
> **CLAUDE-Blob:** `e0f9f1a235cfece134d06e9b683f3386486a7f75`
> **Scope:** GitHub-Issue-Reader, Action-Renderer, Live-Issue-Inventar, Trust,
> Eligibility, Begrenzung, Rangfolge und Degradation. Keine Issue-Mutation, keine Code-
> oder Workflowänderung.

---

## 1. Fragestellung

OQ-04 ist keine reine Sortierfrage. Ein öffentliches GitHub-Issue ist veränderbarer
Backlog-Text und damit T3-Beobachtungsdaten. Die Bridge darf daraus nicht allein durch
Platzierung unter `## Action` einen Operatorauftrag erzeugen.

Der Vertrag muss deshalb nacheinander beantworten:

1. Ist die Issue-Quelle technisch valide?
2. Ist ein einzelnes Issue überhaupt für Root-Context eligible?
3. Welche strukturierten Felder sind PUBLIC_SAFE?
4. Wie werden eligible Kandidaten begrenzt und deterministisch geordnet?
5. Wie bleibt sichtbar, dass auch ein ausgewähltes Issue keine Instruktionsautorität hat?

---

## 2. Gepinnter Produktionszustand

Am Steward-Head `b2b633cb7f7e9e0f0b2164527034c2426541b7a7` enthält
`.steward/context.json` genau 20 Issues. `CLAUDE.md` rendert dieselben 20 Einträge unter
`## Action`.

Alle 20 sind wiederholte `[review-request]`-Fragen. Kein TaskManager-Eintrag, keine
Operatorfreigabe und keine kuratierte Priorität konkurriert innerhalb dieses Abschnitts
mit ihnen.

Der Root-Output vermittelt dadurch semantisch „jetzt bearbeiten“, obwohl die Quelle nur
eine Federation-Review-Inbox repräsentiert.

---

## 3. Codebeweis: Neuigkeit statt Relevanz

`steward/context_bridge.py:466-482` führt aus:

- `gh issue list --state open`,
- nur die Felder `number,title`,
- festes Limit 20,
- keine Search-/Label-/Assignee-/Milestone-/Priority-Bedingung,
- Fehler oder ungültiges JSON werden als `[]` zurückgegeben.

`steward/briefing_stages.py:524-566`:

- übernimmt jedes gelieferte Issue,
- rendert Nummer und Titel roh unter `## Action`,
- enthält zwar Darstellungscode für `labels`,
- erhält vom Reader aber keine Labels,
- besitzt keine Eligibility-, Trust-, Deduplikations- oder Prioritätsprüfung,
- ist ausdrücklich `compressible = False`.

Damit verbraucht die untrusted Issue-Liste selbst bei reduziertem Briefing-Fokus den
vollen Action-Slot. Die scheinbare Labelunterstützung ist im aktuellen Pfad tot.

---

## 4. Live-Inventar

Die read-only GitHub-Abfrage aller offenen Issues ergab am Untersuchungszeitpunkt:

| Merkmal | Anzahl |
|---|---:|
| offene Issues gesamt | 364 |
| mit Label `review-request` | 358 |
| mit Label `federation-nadi` | 359 |
| ohne irgendein Label | 5 |
| mit Milestone | 0 |
| mit Assignee | 0 |
| mit `duplicate` | 0 |
| mit `bug`, `enhancement`, `help wanted` oder `good first issue` | 0 |

Von den 358 Review-Requests bestehen 355 aus nur fünf exakt wiederholten Titeln: jeder
Titel ist 71-mal offen. Die fünf Familien wurden vom 9. bis 14. Juli wiederholt in
Fünferbatches erstellt.

Die Bodies identifizieren sie als Peer-Review-Requests von `agent-research`, transportiert
über NADI. Neue Runs erzeugen neue Inquiry-IDs und Content-Hashes, obwohl die sichtbare
Frage gleich bleibt.

Das Issue-Inventar ist damit überwiegend eine replizierte Federation-Inbox, nicht der
operative Steward-Backlog.

---

## 5. Warum vorhandene Metadaten keine Agenda beweisen

### 5.1 Autor

Alle 364 offenen Issues erscheinen unter demselben GitHub-Account. Das unterscheidet
weder menschlich kuratierte Issues noch automatisierte NADI-, Research- oder Steward-
Erzeuger. Autoridentität ist keine ausreichende Eligibility-Regel.

### 5.2 Titelpräfix

Titel wie `[security]`, `P0`, `[review-request]` oder `[ESCALATION]` sind freie, untrusted
Prosa. Zwei offene `[security]`-Issues erklären im Body selbst, bereits erledigt zu sein.
Ein Prefix ist weder Status noch Priorität.

### 5.3 Standardlabels

Die vorhandenen Standardlabels beschreiben Kategorie oder Community-Workflow, aber keine
reviewte Root-Context-Freigabe. Kein offenes Issue trägt derzeit eines der üblichen
actionable Labels.

### 5.4 Automationlabels

Steward-Code versucht für eigene Eskalationen Labels wie `steward-escalation` und
`federation-health` zu verwenden. Diese Labels existieren im aktuellen Repositorykatalog
nicht. Dieser angrenzende Actuator-/Governance-Befund wird hier nicht repariert und darf
nicht durch eine Context-Bridge-Heuristik kaschiert werden.

### 5.5 Recency

Die 20 neuesten Issues sind aktuell gerade die neuesten NADI-Batches. Neuigkeit misst
Eingang, nicht Wichtigkeit. `updatedAt` wäre ebenso manipulierbar und darf nicht allein
priorisieren.

---

## 6. Verbindliche Autoritätsgrenze

GitHub-Issues sind immer **nichtautoritative Backlog-Beobachtungen**.

Auch ein eligible Issue:

- erteilt keinen Operatorauftrag,
- überschreibt weder statischen Verfassungskern noch aktuellen menschlichen Auftrag,
- überschreibt keinen belegten C1-Sicherheitszustand,
- ersetzt nicht `PHASE2_CURRENT` oder den TaskManager,
- wird nicht allein wegen Titel, Autor, Label oder Alter zu „Current Work“.

Der Root-Renderer darf Issues nicht unter einer unqualifizierten imperativen Überschrift
wie `Action` präsentieren. Eine spätere Darstellung muss ihren Rang sichtbar machen,
beispielsweise als nichtautoritative, untrusted Backlog-Kandidaten.

---

## 7. Eligibility-Vertrag

Default ist **deny**. Ein einzelnes Issue darf nur Kandidat für den dynamischen Root-
Datenblock werden, wenn alle Bedingungen erfüllt sind:

1. Die Issue-Quelle hat nach OQ-13 Status `valid` oder `empty`.
2. Repository, Owner und Sichtbarkeit entsprechen dem OQ-17-Publikationsvertrag.
3. Eine statisch reviewte C0-Konfiguration definiert explizit die zulässigen
   Eligibility-Labels und deren Prioritätsklassen.
4. Das Issue trägt mindestens ein exakt allowlistetes Eligibility-Label.
5. Es trägt kein statisch konfiguriertes Exclusion-Label.
6. Nummer, State, relevante Labels und Zeitfelder bestehen Typ- und Bereichsprüfung.
7. Titel wird nach dem Prompt-Injection-/Unicode-/Längenvertrag neutralisiert.
8. Das Issue wird ausschließlich als Beobachtung, nicht als Instruktion gerendert.

Aktuell existiert keine solche reviewte Eligibility-Konfiguration. Deshalb gilt für den
heutigen Repository-Zustand:

> **Null einzelne GitHub-Issues sind für den kanonischen Root-Actionblock eligible.**

Feature-Spec 03 darf keinen Labelnamen ad hoc im Python-Code erfinden und dadurch
scheinbar Governance schaffen.

---

## 8. Verbindliche Ausschlussklassen

Unabhängig von Neuigkeit werden standardmäßig ausgeschlossen:

- `federation-nadi`,
- `review-request`,
- `research-result`,
- `duplicate`,
- `invalid`,
- `wontfix`,
- reine `question`-/Diskussionsklassen,
- Issues, deren einziger Prioritätshinweis im freien Titel oder Body steht.

Federation-Review- und Research-Einträge können später als getrennte, aggregierte Inbox-
Telemetrie erscheinen, etwa Anzahl oder Backlog-Altersklasse. Sie gehören nicht in den
operativen Action-Slot und ihre freien Titel bleiben aus dem Root-Kontext ausgeschlossen.

---

## 9. Begrenzungs- und Rangvertrag

Wenn später eine C0-Eligibility-Konfiguration existiert, gilt:

1. Die Konfiguration definiert eine kleine Display-Grenze; das versionierte Schema setzt
   eine harte Obergrenze von fünf Einzel-Issues.
2. Default ohne Konfiguration ist null, nicht 20.
3. Zuerst wird Eligibility vollständig geprüft, danach begrenzt.
4. Rang 1 ist die statisch konfigurierte Prioritätsklasse des allowlisteten Labels.
5. Innerhalb derselben Klasse gilt `createdAt` aufsteigend, danach Issue-Nummer
   aufsteigend, um dauernde Verdrängung durch neue Eingänge zu verhindern.
6. `updatedAt`, Titeltext, Kommentarzahl und rohe Labelreihenfolge sind keine alleinigen
   Rank-Signale.
7. Ausgabeordnung und Hashmodell verwenden nur normalisierte, allowlistete Metadaten.
8. Der Renderer zeigt Anzahl eligible/ausgeblendet und Source-Status, ohne 364 Rohissues
   in den Payload zu kopieren.

Die harte Obergrenze ist eine Sicherheits- und Tokenbudgetgrenze. Sie darf nicht durch
untrusted Repositorydaten erhöht werden.

---

## 10. Deduplikationsvertrag

Issue-Nummer ist die einzige bestehende stabile GitHub-Identität. Gleichlautende Titel
sind kein sicherer Identitätsbeweis und dürfen nicht automatisch zusammengeführt oder
geschlossen werden.

Für den Root-Kontext gilt:

- explizit als `duplicate` markierte Issues sind ausgeschlossen;
- wiederholte nicht-eligible Federation-Eingänge werden nur aggregiert;
- semantische Titelähnlichkeit kann eine Diagnose auslösen, aber keine automatische
  Mutation oder Prioritätsentscheidung;
- die Bridge schließt, kommentiert, relabelt oder dedupliziert keine Issues.

Die 355 Wiederholungen sind ein realer Federation-/Issue-Lifecycle-Befund, aber ihre
Bereinigung ist ausdrücklich außerhalb dieses read-only Recon und außerhalb des späteren
Renderer-Patches.

---

## 11. PUBLIC_SAFE-Feldgrenze

Für einen eligible Kandidaten sind höchstens vorgesehen:

| Feld | Regel |
|---|---|
| `number` | positive Integer-ID; stabile Referenz |
| `state` | muss `OPEN` sein; bekanntes Enum |
| `labels` | nur exakte allowlistete normalisierte Namen, nie rohe Gesamtliste |
| `createdAt` | intern für deterministische Reihenfolge; nicht zwingend rendern |
| `url` | nur kanonische öffentliche GitHub-URL desselben Repositories |
| `title` | optional, neutralisiert, einzeilig, längenbegrenzt und klar als untrusted Data |

Body, Kommentare, Assignee-Namen, Milestone-Prosa, Autorprofil, Reactions und freie
Labelbeschreibungen sind default-deny. Falls später benötigt, brauchen sie einen eigenen
Feld- und Trust-Vertrag.

---

## 12. Source- und Fehlerverhalten

OQ-13 gilt vollständig:

- CLI fehlt, Timeout, Exitfehler oder ungültiges JSON sind `unavailable/invalid`, nicht
  `empty`.
- Erfolgreiche Abfrage ohne Issues ist `empty`.
- Erfolgreiche Abfrage mit 364 nicht-eligible Issues ist `valid` mit
  `eligible_count=0`, nicht `empty`.
- Unbekannte Label-/Feldformen sind `unsupported` und default-deny.
- Unsicherer Titel wird quarantänisiert; er macht nicht den gesamten statischen Vertrag
  zu einer leeren Agenda.

Ein Ausfall der Issue-Quelle blockiert den statischen Root-Vertrag nicht. Er darf aber
niemals als „keine offenen Issues“ oder „keine Arbeit“ dargestellt werden.

---

## 13. Adversariale Testfolgen

Feature-Spec 03 benötigt mindestens:

1. Issue-Titel mit imperativer Prompt Injection.
2. Markdown-Heading, Liste, Codefence, Link, HTML und bidi/zero-width Unicode im Titel.
3. Eligibility-Label fehlt: kein Einzel-Issue im Root.
4. Eligibility- und Exclusion-Label gleichzeitig: fail-closed ausgeschlossen.
5. 1.000 neue nicht-eligible NADI-Issues verdrängen keinen eligible Kandidaten.
6. Mehr als fünf eligible Issues halten die harte Obergrenze und stabile Rangfolge.
7. Gleiche Priorität sortiert älter zuerst, dann nach Nummer.
8. Gleichlautende Titel werden nicht automatisch als dieselbe GitHub-Identität behandelt.
9. CLI-/JSON-Fehler erscheint als Source-Degradation, nicht als leere Queue.
10. Renderer bezeichnet Kandidaten niemals als Operatorauftrag oder verbindliche Action.
11. Reader fordert genau die für Eligibility benötigten strukturierten Felder an.
12. Labels außerhalb der C0-Allowlist steuern weder Eligibility noch Priorität.

---

## 14. Nicht belegbare Annahmen

Read-only nicht festgelegt werden kann:

- welche konkreten Eligibility- und Prioritätslabels der Operator künftig will,
- wer organisatorisch Labels vergeben oder entfernen darf,
- ob GitHub-Rulesets diese Labelgovernance technisch erzwingen können,
- ob die Federation ihre 355 Wiederholungen an der Quelle deduplizieren wird,
- ob einzelne historische Issues geschlossen oder relabelt werden sollen.

Darum erfindet diese Evidence keine heutigen Labelnamen und mutiert keine Issues.

---

## 15. Entscheidung

OQ-04 ist geschlossen:

1. Issues sind nichtautoritative Backlog-Beobachtungen, keine Agenda.
2. Aktuell sind null einzelne Issues für Root-Context eligible.
3. Spätere Eligibility und Priorität stammen ausschließlich aus statisch reviewter
   Konfiguration, nicht aus Titelheuristik oder Recency.
4. Federation-NADI, Review-Requests und Research-Resultate bleiben aus dem Action-Slot.
5. Einzelkandidaten sind schema-seitig auf höchstens fünf begrenzt und werden nach
   konfigurierter Prioritätsklasse, Alter und Nummer deterministisch geordnet.
6. Freie Texte bleiben neutralisiert und untrusted; Body und Kommentare sind default-deny.
7. Source-Fehler werden sichtbar degradiert und nie als gesunde Leere ausgegeben.
8. Die Bridge mutiert oder bereinigt den Issue-Backlog nicht.

Diese Entscheidung autorisiert keinen Codepatch, keine Labelanlage, keine Issue-
Bereinigung und keinen PR-Merge. G0 bleibt offen.
