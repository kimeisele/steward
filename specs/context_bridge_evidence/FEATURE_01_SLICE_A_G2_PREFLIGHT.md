# FEATURE 01 / SCHNITT A — G2-PRE-FLIGHT

> **Status:** G2 START APPROVED — ausschließlich Legacy-Writer-Fence nach Merge dieses Dokuments
> **Datum:** 2026-07-15
> **Produktionsbasis:** `kimeisele/steward@964e9972bec25b912da71b2e014605592ebab2ae`
> **Produktions-Tree:** `1ac9484f32e9eb0b9a4ddb236f203d19ee5e143c`
> **Feature-Spec:** `specs/CONTEXT_BRIDGE_FEATURE_01.md` — G1 APPROVED
> **Scope:** G2-Pre-Flight und Startentscheid; noch keine Produktcodeänderung

---

## 1. Entscheidung

Schnitt A darf implementiert werden, sobald dieses Dokument regulär auf `main` gemergt
ist und ein frischer Implementierungsbranch vom dann aktuellen `origin/main` erstellt
wurde.

Die Freigabe ist absichtlich negativ und eng. Der Schnitt:

1. stoppt den deterministischen Legacy-Root-Writer,
2. begrenzt die LLM-Synthese auf expliziten Preview-Return,
3. neutralisiert alte MTime-, Intent- und Strategy-Behauptungen,
4. begrenzt Git-NADI auf positiv benannte Federationpfade,
5. erzeugt noch keinen neuen Publisher.

Ein grüner Schnitt A ist nur ein Sicherheitszaun. Er beweist weder Feature 01 insgesamt
noch eine kanonische Context-Publikation, Delivery, Freshness oder Produktionstauglichkeit.

---

## 2. Gepinnte Live-Evidence

Der Recon wurde nach `git fetch origin --prune` auf dem oben gepinnten `origin/main`
durchgeführt.

### 2.1 Parallelität und Drift

- Es existierte kein offener Pull Request.
- Seit dem Feature-01-Merge drifteten ausschließlich bekannte `.steward/`- und
  Federation-Runtime-Dateien.
- Kein Slice-A-Produkt- oder Testpfad änderte sich in diesem Drift.
- Der Pre-Flight-Branch war vor dieser Dokumentation sauber und wurde auf den Live-Head
  rebasiert.

Unmittelbar vor dem ersten Implementierungspatch werden diese Aussagen wiederholt. Ein
neuer überlappender PR, ein geänderter Slice-A-Symbolvertrag oder unbekannter Main-Drift
stoppt G2 fail-closed.

### 2.2 Aktive Legacy-Pfade

Der aktuelle Code besitzt weiterhin alle in Feature 01 belegten Nebenwege:

- `steward.briefing.write_claude_md()` rendert und schreibt Root-`CLAUDE.md` direkt.
- `MokshaContextBridgeHook.execute()` ruft diesen Writer nach einem erfolgreichen
  Raw-`context.json`-Write auf und verschluckt dessen Fehler als nicht fatal.
- `SynthesizeBriefingTool.execute()` schreibt ohne `output_path` Root-`CLAUDE.md` und
  akzeptiert ansonsten einen beliebigen Zielpfad.
- `IntentHandlers.execute_synthesize_briefing()` leitet aus Datei-MTimes eine angebliche
  kanonische Staleness ab und empfiehlt den LLM-Writer.
- `_add_steward_missions()` registriert eine aktivierte autonome
  `strategy_synthesize_briefing`.
- `GitNadiSync.push()` prüft den ganzen Worktree, fällt bei einem fehlgeschlagenen engen
  Stage-Versuch auf `git add -A` zurück und kann bereits fremd gestagte Dateien committen.

Die Root-Dateien, Workflows und Context-Bridge-Source selbst werden in Schnitt A nicht
verändert.

---

## 3. Exakte Patchpfade

### 3.1 Produktcode

Zulässig sind ausschließlich:

```text
steward/briefing.py
steward/hooks/moksha_bridge.py
steward/tools/synthesize_briefing.py
steward/intent_handlers.py
steward/services.py
steward/git_nadi_sync.py
```

### 3.2 Tests

Zulässig sind ausschließlich:

```text
tests/test_briefing.py
tests/test_git_nadi_sync.py
tests/test_intents.py
tests/test_services.py
tests/test_synthesize_briefing.py
tests/test_moksha_context_bridge.py
```

Die letzten beiden Testdateien dürfen neu angelegt werden. Falls ein bestehender
Testhelper die Wirkung ohne zusätzliche Abstraktion sauber beweist, darf eine der neuen
Dateien entfallen. Jeder andere Pfad erfordert Stop, dokumentierte Ursachenanalyse und
einen neuen G2-Entscheid.

---

## 4. Ausdrücklich verbotener Scope

Nicht verändern:

```text
CLAUDE.md
AGENTS.md
.steward/**
.github/**
specs/CONTEXT_BRIDGE_FEATURE_01.md
specs/CONTEXT_BRIDGE_FEATURE_04.md
steward/context_bridge.py
steward/context_contract.py
steward/briefing_stages.py
steward/intents.py
steward/tool_providers.py
steward/tools/__init__.py
data/federation/**
```

Ebenfalls verboten:

- neuer Root-, Snapshot-, Record- oder Source-Publisher,
- Delegation des alten Writers an einen unfertigen neuen Publisher,
- Constitution-/Orientation-Migration,
- Änderung der Feature-04-Modelle oder Hash-Domains,
- Workflow-, Branchschutz-, CODEOWNERS- oder GitHub-Settings-Änderung,
- neue Runtime-Abhängigkeit,
- Entfernung des sichtbaren Toolnamens `synthesize_briefing`,
- Entfernung des Enum-Werts `TaskIntent.SYNTHESIZE_BRIEFING`,
- generischer Git- oder Filesystem-Frameworkbau,
- Behauptung, dass Git-NADI nach diesem Schnitt bereits PR-only sei.

---

## 5. Vertrag des Legacy-Writers

### 5.1 Fail-closed statt stilles Dedup

`write_claude_md()` darf vorübergehend als importierbares Kompatibilitätssymbol bestehen,
aber keine Datei mehr lesen, rendern oder schreiben. Es darf insbesondere:

- fehlendes `CLAUDE.md` nicht erzeugen,
- vorhandenes `CLAUDE.md` nicht verändern,
- `force=True` nicht als Bypass akzeptieren,
- keinen neuen Publisher aufrufen,
- ein blockiertes Schreiben nicht als normales `False`-Dedup tarnen.

Der Aufruf schlägt mit einem eigenen, stabilen `RuntimeError`-Untertyp und einer knappen
Migrationsbotschaft fehl. Der genaue Klassenname darf im Patch gewählt werden; Tests
binden Verhalten und Fehlertyp, nicht Marketingtext.

`generate_briefing()` bleibt als reine String-Preview und für bestehende read-only
CLI-Ausgabe erhalten. Hash-Dedup-State und falsche `SINGLE WRITER`-Dokumentation werden
entfernt, soweit sie nach der Fence-Funktion tot oder sachlich falsch sind.

### 5.2 MOKSHA-Caller

`MokshaContextBridgeHook` behält in Schnitt A seine bestehende Raw-State-Funktion:

- einmal `assemble_context(ctx.cwd)`,
- optionale Vedana-Injektion,
- `write_context_json(ctx.cwd, context)`,
- bestehende Rate-Limit-Semantik und Operation für `context_json`.

Der Hook importiert oder ruft `write_claude_md()` nicht mehr auf und fügt keine
`moksha_context_bridge:claude_md`-Operation mehr hinzu. Er erzeugt noch keine
Root-Publikation. Der boolesche Rückgabewert des Raw-Writers wird in diesem Schnitt nicht
als Feature-01-Publishentscheidung umgedeutet.

---

## 6. Vertrag des LLM-Tools

Der Toolname `synthesize_briefing` bleibt registriert und auffindbar. Seine sichere
V1-Kompatibilitätssemantik lautet:

- kein `output_path`: expliziter Preview-Return ohne Write,
- `output_path == "stdout"`: derselbe Preview-Return ohne Write,
- jeder andere `output_path`: Fehler vor Assembly, Provider-Aufruf und Filesystemmutation.

Ein erfolgreicher Preview-Return trägt mindestens:

```json
{"mode": "preview", "canonical": false}
```

Zusätzliche rein diagnostische Metadaten wie eine Wortzahl sind zulässig. Metadaten
enthalten keinen behaupteten Zielpfad. Toolbeschreibung und Parameterschema sagen klar,
dass kein kanonischer oder persistierter Output unterstützt wird.

Der ungültige Write-Parameter wird validiert, bevor untrusted Context gesammelt oder ein
LLM aufgerufen wird. So ist der alte Write-Caller nicht nur wirkungslos, sondern erhält
einen expliziten, tokenfreien Fehler.

Dieser Schnitt bewertet die Prompt-Inhalte nicht neu. Preview-Text bleibt untrusted,
nicht kanonisch und darf von keinem Caller persistiert werden.

---

## 7. Intent- und Strategy-Kompatibilität

### 7.1 Intent

Der Enum-Wert und Dispatch-Eintrag bleiben zur Kompatibilität bestehen. Der Handler wird
zu einem deterministischen No-op und liefert unabhängig von Existenz oder MTime von
`context.json` und `CLAUDE.md` `None`.

Er darf weder Staleness behaupten noch die Erstellung/Aktualisierung einer Root-Datei
empfehlen. Das verhindert auch, dass bereits persistierte alte Sankalpa-Missionen den
LLM-Pfad weiter als Schreibauftrag aktivieren.

### 7.2 Strategy

Die Default-Mission registriert `strategy_synthesize_briefing` nicht mehr. Eine bloße
Umbenennung oder `enabled=False` lässt einen falschen Vertrag als dauerhaftes
Konfigurationsobjekt bestehen und ist nicht nötig.

Alle übrigen Strategien behalten Reihenfolge, IDs und Semantik. Ein neuer gezielter Test
prüft, dass die erzeugte Mission keinen Strategy-Eintrag mit ID oder Intent-Typ
`synthesize_briefing` besitzt. Bereits persistierter Altzustand wird nicht migriert; der
No-op-Intent ist der sichere Kompatibilitätszaun.

---

## 8. Git-NADI-Containment

### 8.1 Positive Allowlist

`GitNadiSync` darf aus seinem `federation_dir` nur Änderungen dieser fachlichen Pfade
stagen und committen:

```text
nadi_inbox.json
nadi_outbox.json
peer.json
reports/**
```

Die Pfade werden als Git-Pathspecs nach `--` übergeben. Fehlende ungetrackte Pfade werden
übersprungen; eine fehlende optionale `reports/`-Directory darf niemals einen breiten
Fallback auslösen. Änderungen oder Löschungen bereits getrackter erlaubter Pfade dürfen
eng gestaged werden.

Die konkrete minimale Kombination aus `git add`, `git add -u` oder vorheriger
Tracked-/Existenzprüfung ist Implementierungsdetail. Unzulässig bleibt jeder Befehl ohne
enge positive Pathspec, insbesondere der aktuelle Worktree-Fallback.

### 8.2 Index-Fence

Vor eigenem Staging prüft der Sync den bestehenden Index. Ist irgendein Pfad bereits
gestaged, blockiert `push()` mit `False`, ohne Index, Worktree, Commit oder Remote zu
verändern. Der Sync übernimmt keine fremde Staging-Area — auch dann nicht, wenn der Pfad
zufällig auf seiner Allowlist liegt.

Nach dem engen Staging liest der Sync die gestagten Namen über Git aus, normalisiert sie
gegen den per `git rev-parse --show-prefix` belegten Repository-Prefix und verifiziert,
dass jeder Eintrag innerhalb der Allowlist liegt. Ein unbekannter, absoluter,
parent-traversierender oder außerhalb des Federation-Prefix liegender Eintrag blockiert
vor Commit.

Die Prüfung erfolgt auf repo-relativen Indexnamen; sie verwechselt
`data/federation/peer.json` nicht mit einem gleichnamigen Root-Pfad.

### 8.3 Change Detection und Retry

`_has_changes()` betrachtet nur die Allowlist. Ein ausschließlich außerhalb der
Allowlist schmutziger Worktree führt zu einem erfolgreichen No-op ohne Commit oder Push.

Unrelated **unstaged** Änderungen dürfen bestehen bleiben. Bei einem späteren
Non-Fast-Forward-Retry schützt die bestehende `--autostash`-Semantik sie; der erzeugte
Commit enthält dennoch ausschließlich erlaubte Federationpfade.

Der bestehende direkte Push bleibt vorläufig erhalten, weil Schnitt A nur seine
Worktree-Reichweite schließt. Er ist kein freigegebener Endzustand. Feature 01 verbietet
ihn spätestens vor PR-only-Aktivierung in einem späteren Delivery-Schnitt.

---

## 9. Red-Test-Reihenfolge

Vor Produktcode werden wirkungsbezogene Tests geschrieben. Der erste gezielte Lauf muss
gegen den aktuellen Code rot sein. Tests binden keine private Hilfsfunktion, wenn dieselbe
Sicherheitswirkung über die öffentliche Fläche beweisbar ist.

### Gruppe A — Legacy-Writer-Fence

- vorhandenes Root-`CLAUDE.md` bleibt bytegleich,
- fehlendes Root-`CLAUDE.md` wird nicht erzeugt,
- `force=True` umgeht den Fence nicht,
- Fehler ist expliziter `RuntimeError`-Untertyp und kein Dedup-`False`,
- `generate_briefing()` liefert weiterhin einen String ohne Root-Mutation.

### Gruppe B — MOKSHA-Isolation

- erfolgreicher Raw-Context-Write ruft keinen Legacy-Root-Writer auf,
- `context_json`-Operation bleibt erhalten,
- `claude_md`-Operation erscheint nie,
- bestehendes Root-`CLAUDE.md` bleibt bytegleich,
- fehlendes Root-`CLAUDE.md` wird nicht erzeugt.

### Gruppe C — LLM-Preview

- fehlender Parameter liefert Preview und mutiert keinen Pfad,
- `stdout` liefert denselben sicheren Modus,
- Erfolg trägt `mode=preview` und `canonical=false`,
- Root-, relative, absolute und traversal-artige Zielpfade scheitern explizit,
- abgelehnter Zielpfad ruft weder Assembly noch Provider auf,
- Providerfehler und leere Antwort bleiben normale Toolfehler ohne Write.

### Gruppe D — Intent und Strategy

- Intent liefert bei fehlenden, älteren und neueren Dateien immer `None`,
- Intent erzeugt keine Schreib- oder Stalenessanweisung,
- Default-Mission enthält weder Strategy-ID noch Intent-Typ
  `synthesize_briefing`,
- alle anderen bisherigen Strategy-IDs bleiben erhalten.

### Gruppe E — Git-NADI-Containment

- erlaubte Inbox-/Outbox-/Peer-Änderung wird allein committed,
- erlaubte Report-Datei wird allein committed,
- fehlendes `reports/` löst keinen breiten Stage aus,
- ausschließlich unrelated unstaged Root-Änderung ist No-op und bleibt unverändert,
- erlaubte plus unrelated unstaged Änderung committet nur den erlaubten Pfad,
- beliebiger vorab gestagter Root-Pfad blockiert ohne Commit/Push,
- vorab gestagter erlaubter Pfad blockiert ebenfalls als fremder Indexzustand,
- gleichnamige Root-`peer.json` wird niemals als Federationpfad akzeptiert,
- Delete/Rename außerhalb der Allowlist wird nicht committed,
- Non-Fast-Forward-Retry erhält unrelated unstaged State und den engen Commit,
- kein ausgeführter Stage-Befehl besitzt eine unbeschränkte Worktree-Pathspec.

---

## 10. Implementierungsreihenfolge

1. frischen Branch vom dann aktuellen `origin/main` erstellen,
2. Live-Head, offene PRs und sechs Produktpfade erneut prüfen,
3. rote Tests für Gruppen A bis E committen oder ihren roten Lauf protokollieren,
4. Legacy-Writer und MOKSHA-Caller einzäunen,
5. LLM-Tool auf Preview-only begrenzen,
6. Intent no-op und Default-Strategy entfernen,
7. Git-NADI-Pathspec- und Index-Fence implementieren,
8. gezielte Tests grün machen,
9. Formatter, Lint und gesamte bestehende CI-Matrix ausführen,
10. adversarialen Scope-/Diff-/Caller-Audit durchführen,
11. regulären PR ohne Bypass prüfen und mergen,
12. Merge-Tree und Folgeheartbeat auf verbotene Root-Mutation prüfen.

Die Reihenfolge darf innerhalb kleiner roter/grüner Gruppen variieren. Kein Schritt darf
einen neuen Publisher oder Source-Migration vorziehen.

---

## 11. Rückwärtskompatibilität

Absichtlich erhalten bleiben:

- Importierbarkeit von `write_claude_md`, aber mit explizitem Fence-Fehler,
- reine `generate_briefing()`-Preview,
- Toolname und Toolregistrierung,
- `TaskIntent.SYNTHESIZE_BRIEFING` und Dispatch-Kompatibilität,
- Raw-`.steward/context.json`-Erzeugung,
- Git-NADI-Pull, Throttle und begrenzter Push/Retry für erlaubte Federationpfade.

Absichtlich nicht erhalten bleiben:

- Root-Schreibwirkung des Legacy-Writers,
- beliebige persistierte LLM-Ziele,
- autonome Briefing-Strategy,
- MTime als Freshness- oder Schreibsignal,
- Übernahme eines fremd vorbereiteten Git-Index,
- Worktree-weites Staging.

Ein externer unbekannter Caller, der auf die alte Schreibwirkung angewiesen ist, erhält
einen sichtbaren Fehler statt stiller Korruption. Das ist der gewollte fail-closed
Kompatibilitätsbruch des Fence.

---

## 12. Rollbackgrenze

Der Slice-A-PR ist als ein regulärer Merge-Commit revertierbar. Ein Rollback darf nur den
gesamten Slice zurücknehmen; kein partieller Rollback darf etwa den Git-Fence behalten,
aber den LLM-Root-Writer wieder aktivieren.

Vor einem Rollback muss geprüft werden, warum ein Consumer noch die alte Schreibwirkung
benötigt. Ein einfacher Revert reaktiviert bekannte unsichere Root- und Worktree-Wege und
ist deshalb kein neutraler Safe-Fallback. Bei unerwartetem Kompatibilitätsbruch bleibt
Schnitt A bevorzugt aktiv und der betroffene Caller wird separat analysiert.

Da Schnitt A keine neue Root-Datei erzeugt, besteht sein sicherer Betriebszustand aus dem
letzten getrackten Legacy-Blob plus deaktivierten Nebenwritern. Dieser Blob wird nicht als
fresh oder kanonisch bestätigt.

---

## 13. Adversarialer Pre-Flight-Review

Der Vertrag wurde gegen folgende Umgehungen geprüft:

### 13.1 Verdeckter Ersatzpublisher

Ein Wrapper, Hook oder Tool darf nicht „vorübergehend“ einen neuen Ein-Datei-Writer
einführen. Der Patchscope enthält bewusst weder Feature-04-Renderer noch Publishermodul.

### 13.2 Preview als Persistenz

Ein Default-Preview ist nur sicher, wenn fremde `output_path`-Werte vor LLM-Aufruf
scheitern und kein Preview-Ziel angeboten wird. Tool-Metadaten dürfen Preview nicht als
kanonisch bezeichnen.

### 13.3 Persistierte Altmission

Nur die Strategy aus der Default-Mission zu entfernen reicht nicht. Der No-op-Intent
neutralisiert bereits persistierte Altstrategien, ohne State-Migration in diesen Schnitt
zu ziehen.

### 13.4 Git-Index-Smuggling

Eine enge `git add`-Liste reicht nicht, wenn fremde Dateien bereits gestaged sind.
Pre-stage-Leerheit und Post-stage-Allowlist sind deshalb beide erforderlich.

### 13.5 Pathspec-Verwechslung

Da Git-Befehle im Unterverzeichnis laufen, werden Indexnamen repo-relativ ausgegeben.
Der belegte Git-Prefix ist Teil der Validierung; basename-basierte Prüfungen sind verboten.

### 13.6 Falscher Endzustand

Der Slice lässt Git-NADI weiterhin direkt pushen und lässt den alten Root-Blob bestehen.
Beides ist explizit als Zwischenzustand markiert. Kein Test, Log oder PR-Text darf daraus
Feature-01-Abschluss oder PR-only-Delivery ableiten.

Es bleibt kein identifizierter Architekturblocker für den Start dieses engen Fence. Neue
Live-Evidence kann die Entscheidung jederzeit widerlegen und stoppt den Patch.

---

## 14. Abnahmekriterien

- [x] G1-Spec ist auf `main` und der Recon auf einen Live-Head gepinnt.
- [x] offene PRs und Main-Drift wurden geprüft.
- [x] alle aktiven Writer-/Intent-/Strategy-/Git-NADI-Pfade sind benannt.
- [x] erlaubte und verbotene Patchpfade sind exakt.
- [x] Red Tests prüfen Wirkung, Umgehungen und Kompatibilität.
- [x] kein neuer Publisher oder Source-Patch ist erlaubt.
- [x] Git-Index-Smuggling ist neben Pathspec-Containment abgedeckt.
- [x] persistierte Altmissionen sind ohne State-Migration fail-closed.
- [x] Rollback und sicherer Zwischenzustand sind ehrlich begrenzt.
- [x] G2 stoppt bei neuem Main-Drift oder Parallelkonflikt.

---

## 15. Schlussstatus

Nach regulärem Merge dieses Dokuments ist ausschließlich folgender nächste Schritt
freigegeben:

> Einen frischen Implementierungsbranch vom aktuellen `origin/main` erstellen, zuerst die
> roten Slice-A-Tests anlegen und dann ausschließlich die sechs erlaubten Produktpfade bis
> zum hier definierten Legacy-Writer-Fence ändern.

Feature-01-Renderer, Source-Migration, lokaler Publisher, Recovery, Runtime-State,
Delivery, Governance und Aktivierung bleiben gesperrt und benötigen ihre eigenen späteren
G2-Pre-Flights.
