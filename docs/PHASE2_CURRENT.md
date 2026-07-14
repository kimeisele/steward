# PHASE 2 CURRENT — Fresh-Session-Cockpit

**Aktualisiert:** 2026-07-14, 11:36 Europe/Berlin  
**Zweck:** Ein neuer Lead-Agent soll mit dieser Datei in wenigen Minuten arbeitsfähig sein.
Der ausführliche Beweis- und Operationsverlauf bleibt in `docs/PHASE2_BEFUND.md`.

## 1. Einstieg für eine frische Session

Lies zuerst ausschließlich diese Datei. Öffne danach im ausführlichen Phase-2-Befund nur
die Paragraphen, die für den nächsten Auftrag verlinkt sind. Phase 1 ist historisches
Arbeitsprotokoll und read-only; sie wird nur bei konkretem Beweisbedarf konsultiert.

**Entscheidungshierarchie:**

1. aktueller Produktionscode, gepinnte Git-Objekte und vollständige Produktionslogs,
2. neueste verifizierte Phase-2-Erkenntnisse,
3. ältere Phase-2-Hypothesen,
4. Phase-1-Befund.

Wenn Live-Realität oder neuer Beweis einer älteren Aussage widersprechen, gilt der neue
Beweis. Phase 1 wird trotzdem nicht umgeschrieben: Phase 2 nennt die alte Aussage, widerlegt
oder präzisiert sie und dokumentiert den Produktionsbeweis. **Read-only bedeutet
Nachvollziehbarkeit, nicht Unfehlbarkeit.**

## 2. Rolle und Sicherheitsvertrag

Du bist der Phase-2-Lead-Senior-Engineer für Steward und die Föderation. Ziel ist nicht,
möglichst viel Code zu schreiben, sondern das Fundament schrittweise beweisbar robust,
resilient, langlebig und skalierbar zu machen.

Verbindlich:

- Vor jedem Patch Live-Head, Tree und relevante Blobs erneut pinnen.
- Große State-Dateien über Git-Trees + Blobs API lesen, nicht über die Contents API.
- Read-only Recon vor jeder Änderung; Hypothesen aktiv zu widerlegen versuchen.
- Gegen echte Klassen, echte Git-Repositories und echte Nachrichten testen, nicht gegen
  bequeme Stubs.
- Rote Regression vor dem Fix; kleinster Root-Cause-Patch; keine Nebenreparaturen.
- Kein Force-Push, keine History-Rewrites, kein Admin-CI-Bypass.
- State-Migrationen nur mit harten Guards, exakter Keep/Delete-Menge und Rollback-Blobs.
- Nach Merge am vollständigen Produktionslog und an neuen Live-Blobs verifizieren.
- Phase 1 niemals verändern.
- Nach jedem abgeschlossenen Milestone diese Datei aktualisieren und den ausführlichen
  Produktionsbeweis als neuen Paragraphen an `PHASE2_BEFUND.md` anhängen.

## 3. Arbeitsumgebung

Der vom Benutzer bereitgestellte Clone `/Users/ss/projects/steward` gilt als schmutzig und
ist **kein Arbeitsclone**.

Vorhandene getrennte Klone:

- Code: `/Users/ss/projects/steward-gateway-phase2`
- Dokumentation: `/Users/ss/projects/steward-phase2`
- Agent City: `/Users/ss/projects/agent-city-phase2`

Ein neuer Agent muss vor Nutzung `git status`, Remote, Branch und `origin/main` prüfen.
Bei Unsicherheit einen neuen sauberen Clone oder Worktree anlegen. Lokale Klone sind nur
Arbeitsflächen; die Lesewahrheit kommt über Live-`gh api` aus GitHub.

## 4. Gepinnter Produktionsstand

Snapshot-Zeit: 2026-07-14 11:36 Europe/Berlin.

### Steward

- Repo: `kimeisele/steward`
- Head: `41635ecdf8183fceb910e318e8aebcf95d2091f6`
- Tree: `c00dedffc6ffda1c7e15c710a7205e770ac5464a`
- Commit: `chore: heartbeat #5344 state sync`
- Phase 1: Blob `2f8a8e4e3b9624859c9ae25a754f3cd93120df66`, read-only
- Phase 2: Blob `c78e5dc3471c1dcfa28472966cbab1dc587f9e2d`
- Registry: Blob `1fbb9f659ecfe493b3120ffe5307a3c6db7e6204`, 17 Einträge
- Inbox: Blob `6cf1334520d8e2696844fd8e26f84b812edcad1b`, 322 Nachrichten
- Relay-Seen: Blob `b663a4c8f09d1892c28952dfd0395f160557d5cf`, 552 UUIDs
- Quarantäne-Index: Blob `5356cd6de4cc432f0cc9413e8355cea9d4a6623b`,
  2.772 Fingerprints

### Federation-Hub

- Repo: `kimeisele/steward-federation`
- Head: `02a6e57d001fc4a4a04a20abc8aee2c41e559c2c`
- Tree: `c2b1ff9ea9582ef5ba801fd04a2ae9bfe89b331d`
- Steward-Mailbox: Blob `04b1605ce0c047a6ba845c021285e46556c89575`,
  44 Nachrichten
- Alle 44 Nachrichten stammen von der aktiven ID `ag_9272c311628b5f40`:
  22 Claims + 22 Heartbeats
- Bekannte Steward-Federation-Geister in dieser Mailbox: 0

Der Snapshot ist ein Einstiegspunkt, kein Schreib-Parent. Vor der nächsten Operation erneut
live pinnen, weil die Föderation weiterläuft.

## 5. Abgeschlossene Phase-2-Fundament-Milestones

### Identität, Gateway und State

- Agent-City T0c behoben: PR `agent-city#1829`, Merge
  `e798bdbf7b3969beea577fe265657bbb7c142115`.
- Kanonischer Steward-Eingang: PR `steward#409`, Merge
  `69dc052641a9364c828dd62d725f79904adbd2df`.
- Persistente Relay-Deduplizierung: PR `steward#415`, Merge
  `3bf1c656ea5737b6bb60b8d4724c9826321d24d8`.
- Git als Heartbeat-State-Quelle: PR `steward#416`, Merge
  `35e1f716870a95a731467aefcb2d4d6a30654216`.
- Autostash-Follow-up: PR `steward#417`, Merge
  `c53f58b043c7467ffbd5f3cb6212fc4f013cfc52`.

### CI, KARMA und B'

- Steward-CI/KARMA-Baseline repariert: PR `steward#419`, Merge
  `2614bb5dbb99ce686f0a02e91567d79d1fac8cb6`.
- B' upstream Hub-Purge: Commit `018250711cf1f4acdd43b5b57b40ff347632436c`.
- B' atomarer Steward-Purge: Commit
  `39c265a650cf1b443a26870b382696916322c22e`.
- B' Ergebnis: Registry 60→17, lokale Inbox 466→322, Hub-Mailbox 144→42
  zum Ausführungszeitpunkt; zwei Produktionszyklen ohne Wiederauferstehung.
- Der Hub-Ring wächst danach legitim mit neuen aktiven Nachrichten; entscheidend ist
  `source=ag_9272c311628b5f40` und null bekannte Geister, nicht dauerhaft exakt 42.
- Ausführlicher Beweis: `PHASE2_BEFUND.md` §§12–13.

### Heartbeat-Git-Fundament

- Dirty-Rebase, fehlende Git-Autoridentität und kaputter mode-160000-Gitlink repariert.
- PR `steward#428`, Merge `ead60c2fbffb621ab12db1bb3af4b9ba52cf3a27`.
- Produktionsrun `29321214906`:
  - `GIT_NADI: push succeeded`: 1,
  - GitNadi Pull/Commit/Push-Fehler: 0,
  - Checkout-/Submodule-Exit 128: 0,
  - Heartbeat/KARMA/Traceback/Conflict/detached-HEAD: 0,
  - finaler State-Commit `8b248ddfb6b09fad520e194ea1975910fab69c9b`.
- Ausführlicher Beweis: `PHASE2_BEFUND.md` §14.

## 6. Exakt nächster Auftrag: Heartbeat-Fehlerpropagation

**Noch keinen Patch schreiben.** Zuerst read-only klären, welche Fehler den Workflow rot
machen müssen und welche bewusst degradierbar sind.

Bekannter Ausgangspunkt:

- `.github/workflows/steward-heartbeat.yml` fängt jede Ausnahme jeder MURALI-Phase,
  loggt sie und setzt den Python-Prozess danach fort.
- Der State-Commit-Schritt läuft mit `if: always()`.
- Frühere Logs konnten `HEARTBEAT ERROR ...`, Tracebacks oder interne Warnungen enthalten,
  während der Workflow insgesamt grün blieb.
- Nicht jeder Netzwerkfehler darf automatisch den gesamten Steward stilllegen; ein grüner
  Lauf darf aber auch keinen kritischen Phasenabbruch verschweigen.

Read-only-Arbeitsauftrag:

1. Workflow, `StewardAgent`-Phasen, Hook-Aufrufer und Rückgabewerte vollständig verfolgen.
2. Reale historische Logs nach Fehlerklasse zerlegen, nicht nur Treffer zählen.
3. Eine Matrix erstellen:
   - **kritisch:** Workflow muss rot werden,
   - **degradierbar:** Workflow darf nur bei bewiesener State-Postcondition grün bleiben,
   - **Post-Action/extern:** separat sichtbar und nicht vom Python-Fänger maskierbar.
4. Prüfen, welche Fehler bereits als Exception auftreten und welche nur `False` oder Warning
   zurückgeben.
5. Erst danach roten Regressionstest und minimalen Propagationsvertrag entwerfen.

Abbruchkriterium: Kein Patch, solange eine reale Fehlerklasse nicht eindeutig klassifiziert
ist oder der vorgeschlagene Vertrag legitime degradierte Federation-Kommunikation unnötig
zum Totalausfall machen würde.

## 7. Offene Agenda nach Fehlerpropagation

Reihenfolge ist vorläufig und muss jeweils durch neuen Live-Recon bestätigt werden:

1. Steward-Identitätsname `ag_8859b969119219b8` sauber zu `steward` migrieren, ohne die
   aktive kryptographische Identität zu verlieren.
2. Key-Rotation knotenweise; vor jeder Rotation Parser-Kompatibilität des Zielrepos prüfen.
3. Quarantäne-Cleanup mit Grundklassen, Aufbewahrung und Rollback statt blindem Löschen.
4. Agent-City-GH006-State-Persistenz separat beheben.
5. Weitere Federation-Invarianten und aktive Repos erneut live inventarisieren.

Keine dieser Arbeiten darf mit der Fehlerpropagation in einen Sammelpatch geraten.

## 8. Quota-sparender Arbeitsmodus

- Ein Lead-Agent, ein klar begrenzter Milestone; kein breiter Dispatch ohne unabhängige,
  konkret begrenzte Teilaufträge.
- Diese Datei zuerst lesen; Phase 2 nur paragraphenweise; Phase 1 nur beweisbezogen.
- Read-only Recon und Patch in getrennten Schritten.
- Routineaufgaben wie Logzählung, Format und Docs können mit niedrigerer Denkstufe laufen;
  Identität, Kryptographie, State-Migration und Produktionsschreiben bleiben auf Medium.
- Nach einem sauberen Produktionsbeweis stoppen, dokumentieren und bei großem Restkontext
  lieber eine frische Session beginnen.
- Kein Versuch, Quoten technisch zu umgehen; Kontextverbrauch durch präzise Arbeitsgrenzen
  reduzieren.

## 9. Copy-Paste-Prompt für die nächste Session

```text
Du bist der Phase-2-Lead-Senior-Engineer für Steward und die Agentenföderation.

Arbeite zunächst strikt read-only. Lies als Erstes:
  /Users/ss/projects/steward-phase2/docs/PHASE2_CURRENT.md

Der Clone /Users/ss/projects/steward ist schmutzig und darf nicht als Arbeitsclone benutzt
werden. Prüfe oder erstelle eine saubere Arbeitsumgebung. Lies Live-Zustand über gh api und
pinne Head, Tree und relevante Blobs neu, bevor du Aussagen über Produktion triffst.

Phase 1 ist read-only und historisch, aber nicht unfehlbar. Live-Code, Git-Objekte,
Produktionslogs und neuere Phase-2-Beweise haben Vorrang. Widersprüche werden in Phase 2
explizit korrigiert, niemals durch blindes Befolgen alter Aussagen.

Der nächste Auftrag ist der read-only Root-Cause-Recon zur Heartbeat-Fehlerpropagation aus
PHASE2_CURRENT §6. Schreibe noch keinen Patch. Erstelle zuerst eine belegte Matrix aus
kritischen, degradierbaren und externen/Post-Action-Fehlern. Pflege PHASE2_CURRENT als
rollierendes Cockpit und PHASE2_BEFUND als ausführliches externes Gehirn.
```
