# PHASE 2 CURRENT — Fresh-Session-Cockpit

**Aktualisiert:** 2026-07-15, 19:51 Europe/Berlin
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

Vertrauenswürdige aktive Arbeitsfläche:

- Code und Dokumentation: `/Users/ss/projects/steward-phase2`

Weitere vorhandene getrennte Klone, deren Zustand vor Nutzung neu geprüft werden muss:

- Code: `/Users/ss/projects/steward-gateway-phase2`
- Agent City: `/Users/ss/projects/agent-city-phase2`

Ein neuer Agent muss vor Nutzung `git status`, Remote, Branch und `origin/main` prüfen.
Bei Unsicherheit einen neuen sauberen Clone oder Worktree anlegen. Lokale Klone sind nur
Arbeitsflächen; die Lesewahrheit kommt über Live-`gh api` aus GitHub.

## 4. Gepinnter Produktionsstand

Code-/Dokument-Snapshot: 2026-07-15 19:51 Europe/Berlin.

### Steward

- Repo: `kimeisele/steward`
- Head: `004ac087cca7b2bd925c40b81b8f000f9541b7d1`
- Tree: `5357c4a583b75f1230d418b843029f6cf0475f4d`
- Commit: `Merge pull request #549 from kimeisele/spec/context-bridge-feature-01c-preflight`
- Slice-A-Merge: `1b1ef63d9d873a08acb812f18ba102b73174838c`
- Slice-B-Merge: `a750e0f3826e0067656062e02c3b7c896db35cde`
- Phase 1: Blob `2f8a8e4e3b9624859c9ae25a754f3cd93120df66`, read-only
- Phase-2-Cockpit vor diesem Update: Blob `a8535fd5ce8e87a2d3d8de366d37c02495414ca8`
- Phase-2-Befund vor diesem Update: Blob `a50fefde3a003b1a51a015951289c9c0c6930d13`

Die folgenden Registry-/Inbox-/Hub-Zahlen sind der letzte verifizierte Federation-Census
vom 14.07., **nicht** automatisch der aktuelle Live-Zustand:
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

### Context Bridge: G0, Feature 00, Feature 04 und Feature 01/Schnitte A–B plus C-Gate

- Master-Spec G0 adversarial geschlossen; Merge
  `7b1b6a221851f51d06191222f5187cc877c04304`.
- Feature 00 Trust-/Consumer-/Governance-Vertrag: PR `#497`, Merge
  `327eca2f8bf275563c5940ba807996b52ca44fa3`.
- Feature 04 kanonisches Modell/Hashvertrag: PR `#498`, Merge
  `44b318408ebd1e73731d38c0c11f241d13761b08`.
- Feature-04-G2-Preflight: PR `#499`, Merge
  `d30a22a60213693d834ffd38f44c0892aa942de3`.
- Reiner semantischer Kern: PR `#505`, Merge
  `c81a1683fd9358eb0c6a91cee157eb5c18fec99a`.
- Neue Fläche: ausschließlich `steward/context_contract.py` und
  `tests/test_context_contract.py`; kein bestehender Caller wurde geändert.
- 64 gezielte Contract-Tests, CI Python 3.11/3.12, Lint und Security grün.
- Vollständiger lokaler Bestand vor letzter Boundary-Härtung: 2.188 passed,
  13 skipped; die abschließenden Änderungen wurden danach erneut gezielt und in CI
  validiert.
- Wichtige neue Widerlegung: `error_pressure` und `context_pressure` sind in Vedana
  invertierte Health-Komponenten (`1.0 = gesund`), während mindestens der heutige
  Briefing-Focus `context_pressure` gegenteilig interpretiert. Feature 04 übernimmt
  diesen Altfehler nicht; beide Felder bleiben im V1-Payload default-deny.
- Feature-01-Master-Spec/G1: PR `#532`, Merge
  `b1f945a66aace9721684ae146ab7f8535e85844a`.
- Slice-A-G2-Preflight: PR `#533`, Merge
  `44c0a77f4fa8eda8ab165e9c901530947a938e86`.
- Legacy-Writer-Fence: PR `#539`, Merge
  `1b1ef63d9d873a08acb812f18ba102b73174838c`.
- Der alte deterministische Root-Writer ist fail-closed; MOKSHA schreibt nur noch rohes
  `.steward/context.json`; `synthesize_briefing` ist Preview-only; der alte Intent ist
  No-op; die autonome Briefing-Strategy ist entfernt.
- Git-NADI besitzt keinen Worktree-weiten Fallback mehr, übernimmt keinen fremd
  vorbereiteten Index und staged nur positiv benannte Federationpfade.
- Kontrollierter Produktionsrun `29432921534` auf dem Merge-Head war grün. Folgecommit
  `1e5b23a8f0ba9d30e39c9fc44fc89595fe6c9afe` änderte 11 bekannte Runtime-/Federation-
  State-Pfade und weder `CLAUDE.md` noch Produktcode.
- `CLAUDE.md` blieb vom Merge über den Folgeheartbeat exakt Blob
  `8146a15603c95e5aa1404c9eb7021e3008914b0c`; Root-`AGENTS.md` fehlt weiterhin.
- Der Run enthielt bekannte Provider-Degradation (Gemini 429, Groq 401), aber Mistral
  übernahm; Tracebacks, Legacy-Writer-Fence-Fehler und Git-NADI-Fence-Fehler: 0.
- Slice-B-G2-Preflight: PR `#541`, Merge
  `9347f21f9e1a15e5cfd049c562e4db24957a2cac`.
- Offline-Contract/Renderer: PR `#547`, Merge
  `a750e0f3826e0067656062e02c3b7c896db35cde`.
- Neue reine Fläche: öffentliche Validatoren in `steward/context_contract.py` und der
  I/O-freie `steward/context_rendering.py`; kein bestehender Produktcaller importiert den
  Renderer.
- Der Renderer erzeugt aus validierten Feature-04-Modellen ein einziges Bytes-Objekt für
  beide Root-Kandidaten sowie zirkulationsfreie Snapshot-/Publication-Envelopes. Golden:
  Root 2.318 Bytes, Snapshot 4.781 Bytes, Publication 1.203 Bytes.
- 78 gezielte Tests, Python-3.11-/3.12-CI, Lint und Security grün. Der erste CI-Lauf fand
  einen Testharness-Fehler durch ein bis zum Pytest-Teardown global gepatchtes `time.time`;
  der Guard wurde auf den Renderer-Aufruf begrenzt, ohne Produktcodeänderung.
- Kontrollierter Produktionsrun `29436703996` auf dem Slice-B-Merge-Head war grün.
  Folgecommit `38f361318b39864628dca1329bc513475fec1c04` änderte ausschließlich elf Runtime-/
  Federation-State-Pfade. Root- und Slice-B-Produktblobs blieben identisch.
- `CLAUDE.md` blieb exakt Blob `8146a15603c95e5aa1404c9eb7021e3008914b0c`;
  Root-`AGENTS.md`, Snapshot- und Publication-Artefakt fehlen weiterhin absichtlich.
- Der Produktionsrun bewies außerdem eine ältere offene Fundamentlücke erneut: Groq 401,
  Gemini 429 und schließlich Mistral 400 erschöpften den Streaming-Fallback, während der
  Gesamtworkflow trotzdem erfolgreich endete. Das ist kein Slice-B-Fehler, aber ein
  relevanter Beweis für den späteren Fehlerpropagationsauftrag.
- Feature 01 ist **nicht produktiv aktiviert**: der neue Renderer ist offline und
  unverdrahtet; kein Publisher, keine Root-Mutation, kein Publish-Record, keine Recovery,
  keine Source-Migration und keine PR-only Delivery.
- Slice-C-G2-Recon: PR `#549`, Merge
  `004ac087cca7b2bd925c40b81b8f000f9541b7d1`.
- Der exakte Source-Kandidat ist geschlossen: 1.860 C0-Bytes aus Feature 00, leeres
  versioniertes Orientation-Payload, 2.023 Source-Bytes, erwarteter Git-Blob
  `f428d5856a5c525e002c301890777748effbeb4e`.
- Slice C ist **implementierungsblockiert**: Das öffentliche Repo besitzt genau einen
  Collaborator (`kimeisele`), keine Einladungen, keine Reviews, keine CODEOWNERS, keinen
  PR-Review-Schutz, `enforce_admins=false` und keinen Check
  `Context Constitution Attestation`.
- Ein heute gemergter Source-PR wäre später nicht als commitgebundene menschlich reviewte
  Attestation verwendbar. `.steward/conventions.md` bleibt deshalb exakt auf Blob
  `29829be4f77dcaebf970a8ee872de299f0357f1c`.
- Normative Dokumente: `specs/CONTEXT_BRIDGE_SYSTEM_SPEC.md`,
  `specs/CONTEXT_BRIDGE_FEATURE_00.md`, `specs/CONTEXT_BRIDGE_FEATURE_04.md` und
  `specs/context_bridge_evidence/**`.
- Ausführlicher Beweis: `PHASE2_BEFUND.md` §§15–18.

## 6. Exakt nächster Auftrag: Constitution-Governance-Sequenzspec

**Keine Constitution-, Setting-, CODEOWNERS- oder Workflowänderung.** Der Slice-C-G2-Recon
ist abgeschlossen und blockiert den Implementierungsstart. Als nächstes ist ausschließlich
eine eigene read-only Spec-/Governance-Sequenzkorrektur zulässig.

Bekannter Ausgangspunkt:

- Feature 01 §15 ordnet die menschlich reviewte Source-Migration in Schnitt C ein.
- Der geschlossene Attestation-Vertrag verlangt für genau diesen Source-PR einen anderen
  menschlichen Reviewer, CODEOWNERS-/Branchschutz-Evidence und den commitgebundenen Check
  `Context Constitution Attestation` aus geschützter Base.
- Feature 01 §15.9 ordnet CODEOWNERS, Branchschutz und Governance-Drill erst Schnitt I zu.
- Damit ist C-vor-I am heutigen Live-Zustand nicht ausführbar, ohne wertlose oder
  rückwirkend erfundene Attestation-Evidence zu erzeugen.
- Fehlende Governance blockiert normale default-off Produktvorbereitung nicht pauschal,
  aber ausdrücklich die als „menschlich reviewt“ definierte Constitution-Migration.

Read-only-Arbeitsauftrag:

1. Aktuellen Feature-01-Vertrag, Slice-C-G2, Attestation-Recon und GitHub-Live-Governance
   gegeneinander pinnen.
2. Einen minimalen prerequisite Governance-Schnitt **vor C** spezifizieren: anderer Human-
   Principal, CODEOWNERS, Reviewschutz, stale dismissal, Admin-Enforcement und geschützter
   Constitution-Check.
3. Weitergehende Delivery-/Aktivierungs-Governance in Schnitt I belassen; keinen Mega-
   Governance-Patch entwerfen.
4. Exakte Settings-, Workflow-/Testpfade, Author-/Reviewer-Reihenfolge, Failure-/Rollback-
   Vertrag und Operationsdrill definieren.
5. Den Spec-Entwurf adversarial reviewen. Noch nichts implementieren und niemanden
   eigenmächtig einladen.

Externe harte Precondition: Vor einem Governance- oder Source-PR muss ein konkreter,
vertrauenswürdiger zweiter menschlicher GitHub-Principal benannt und als Collaborator
verfügbar sein. Ein Bot, Agent, zweiter lokaler Gitautor oder derselbe Account ist ungültig.

Abbruchkriterium: Keine Source-, Root-, Produkt-, Workflow-, CODEOWNERS-, Setting-,
Publisher-, Recovery-, Delivery- oder Aktivierungsänderung vor reviewter Sequenzspec und
realer Human-Principal-Precondition.

## 7. Offene Agenda nach Feature-Spec 01

Reihenfolge ist vorläufig und muss jeweils durch neuen Live-Recon bestätigt werden:

1. Feature 01 erst nach geschlossener Governance-Sequenzkorrektur weiterführen; Schnitt C
   bleibt bis zum realen zweiten Human-Principal blockiert. Danach weiter strikt nach den
   in §15 definierten Einzelschnitten und
   jeweils eigenem aktuellem G2 implementieren; erst nach Required Checks, Governance und
   Operations-Drill aktivieren.
2. Danach Feature 02 (Current-Phase Reference Card) und Feature 03 (Action Signal
   Integrity) getrennt spezifizieren.
3. Heartbeat-Fehlerpropagation read-only gegen kritische, degradierbare und externe/
   Post-Action-Fehlerklassen zerlegen; dieser ältere Auftrag ist nicht aufgehoben, aber
   gegenüber dem bereits begonnenen Context-Bridge-Sicherheitsstrang nachgeordnet.
4. Steward-Identitätsname `ag_8859b969119219b8` sauber zu `steward` migrieren, ohne die
   aktive kryptographische Identität zu verlieren.
5. Key-Rotation knotenweise; vor jeder Rotation Parser-Kompatibilität des Zielrepos prüfen.
6. Quarantäne-Cleanup mit Grundklassen, Aufbewahrung und Rollback statt blindem Löschen.
7. Agent-City-GH006-State-Persistenz separat beheben.
8. Weitere Federation-Invarianten und aktive Repos erneut live inventarisieren.

Keine dieser Arbeiten darf mit Feature 01 oder untereinander in einen Sammelpatch geraten.

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

Feature 01 ist G1-freigegeben; Schnitte A und B sind implementiert und verifiziert.
Slice-C-G2 ist abgeschlossen, aber der Implementierungsstart ist blockiert: genau ein
GitHub-Collaborator, kein Review-Schutz/CODEOWNERS/Attestation-Check und kein anderer
menschlicher Reviewer. Der nächste Auftrag ist ausschließlich die read-only Constitution-
Governance-Sequenzspec aus PHASE2_CURRENT §6. Verändere noch keine Constitution-, Root-,
Produkt-, Workflow-, CODEOWNERS-, Setting-, Publisher-, Recovery-, Delivery- oder
Aktivierungsfläche. Erfinde keinen zweiten Reviewer. Pflege PHASE2_CURRENT als
widerlegbares Cockpit und PHASE2_BEFUND als ausführliches externes Gehirn.
```
