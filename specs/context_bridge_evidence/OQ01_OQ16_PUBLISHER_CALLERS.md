# OQ-01 / OQ-16 — PUBLISHER-, CALLER- UND CONCURRENCY-LANDSCHAFT

> **Status OQ-01:** EVIDENCE COMPLETE — LLM-Pfad auf fail-closed Preview-Vertrag begrenzt
> **Status OQ-16:** EVIDENCE COMPLETE — lokale Writer und Remote-Delivery-Pfade inventarisiert
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `02938251c2c28389340dede8d9e125ba05af17ab`
> **Steward-Tree:** `7b622d34d476137e42dc1f79892754e13107fba0`
> **Produktionsbeweis:** GitHub-Actions-Run `29326469514`, Heartbeat `#5351`
> **Scope:** Bestehende lokale Root-Writer, Caller, Prozessgrenzen, Git-Staging und
> Remote-Publisher. Keine Änderung an Produktivcode, Workflow oder Repository-Settings.

---

## 1. Untersuchungsfragen

### OQ-01

Wie wird der bestehende LLM-Schreibpfad auf Preview/Annotation begrenzt, ohne unbekannte
produktive Caller still zu brechen?

### OQ-16

Welche Prozesspfade können außerhalb des Heartbeat-Post-Steps parallel oder konkurrierend
publizieren?

---

## 2. Untersuchte Symbole und Produktionsflächen

- `steward.briefing.write_claude_md`
- `steward.briefing.generate_briefing`
- `steward.hooks.moksha_bridge.MokshaContextBridgeHook`
- `steward.tools.synthesize_briefing.SynthesizeBriefingTool`
- `steward.intent_handlers.IntentHandlers.execute_synthesize_briefing`
- `steward.services` — Sankalpa-Strategie `strategy_synthesize_briefing`
- `steward.tool_providers.BuiltinToolProvider`
- `steward.tools.write_file.WriteFileTool`
- `steward.tools.edit.EditTool`
- `steward.tools.bash.BashTool`
- `steward.tools.git.GitTool`
- `steward.actuators.GitActuator`
- `steward.git_nadi_sync.GitNadiSync`
- `steward.hooks.moksha.MokshaFederationHook`
- `steward.phase_hook.PhaseHookRegistry`
- `steward.agent.StewardAgent`
- `.github/workflows/steward-heartbeat.yml`
- übrige Workflows mit Schreibrechten oder Steward-Ausführung
- zugehörige Tests und Produktionscommits

---

## 3. Befund A — deterministischer Root-Writer

`write_claude_md(cwd, force=False)` ist der dedizierte deterministische Writer:

1. Er ruft `generate_briefing(cwd)` auf.
2. Er hasht den fertigen Text nur pro Prozess über `_last_hash`.
3. Er schreibt mit `Path.write_text()` direkt nach Root-`CLAUDE.md`.
4. Er verwendet weder Tempfile noch Lock noch `fsync`.
5. Der einzige Produktivcaller des Symbols ist
   `MokshaContextBridgeHook.execute()`.
6. Der Hook ruft den Writer nur auf, wenn `write_context_json()` in diesem Durchlauf eine
   Änderung meldet.
7. Fehler werden als `debug` geloggt und als nicht fatal verschluckt.

Der Kommentar „Single Writer“ beschreibt nur diesen Codepfad. Er ist keine zutreffende
Systeminvariante.

---

## 4. Befund B — eigenständiger LLM-Root-Writer

`SynthesizeBriefingTool.execute()` ist ein zweiter direkter Writer:

1. Er assembliert Context und Architektur selbst.
2. Er gibt dynamische Daten und validierte Annotationen an einen LLM-Provider.
3. Ohne `output_path` schreibt er standardmäßig Root-`CLAUDE.md`.
4. Mit `output_path` schreibt er einen frei wählbaren relativen oder absoluten Pfad.
5. Nur der Sonderwert `stdout` verhindert einen Dateischreibzugriff.
6. `validate()` enthält keine Pfad- oder Modusprüfung.
7. Der Writer ruft `write_claude_md()` nicht auf und teilt weder dessen Hash noch dessen
   Rendervertrag.
8. Das Tool erzeugt Parent-Verzeichnisse und überschreibt vorhandene Dateien direkt.

Der Toolname ist nicht in `_FILE_OP_MAP` des Tool-Dispatchers enthalten. Dadurch wird der
Schreibzugriff nicht als Dateioperation an `ToolSafetyGuard` gemeldet und unterliegt nicht
einmal dessen schwachem Read-before-write-Gate.

---

## 5. Positive Erreichbarkeit des LLM-Pfads

Der LLM-Writer ist kein toter Hilfscode:

- `BuiltinToolProvider` registriert `SynthesizeBriefingTool` für jede reguläre
  `StewardAgent`-Instanz.
- Der Heartbeat-Produktionslog belegt die Registrierung des Tools im realen Agentenlauf.
- `strategy_synthesize_briefing` ist aktiviert, idle-basiert, täglich planbar und auf bis
  zu sechs Ausführungen pro Tag konfiguriert.
- Die Strategie erzeugt einen typisierten `SYNTHESIZE_BRIEFING`-Task.
- Der Intent-Handler prüft die MTimes von `context.json` und `CLAUDE.md`.
- Bei vermeintlicher Staleness liefert er explizit die Anweisung, das Tool zu verwenden.
- Der Intent ist nicht proaktiv. Ein positiver Befund läuft daher über
  `guarded_llm_fix()` im aktuellen Worktree, nicht über einen isolierten PR-Branch.
- Das Tool ist ebenfalls über interaktive CLI-, API- und Telegram-Agentinstanzen
  erreichbar, weil diese denselben Builtin-Provider verwenden.

Es wurden keine direkten Python-Caller von `SynthesizeBriefingTool.execute()` außerhalb
des allgemeinen Tool-Dispatchers gefunden. Der Toolname und seine Parameter sind aber
eine agentisch aufrufbare öffentliche Oberfläche und müssen als Consumer-Vertrag
behandelt werden.

---

## 6. Befund C — generische Root-Writer

Jede reguläre `StewardAgent`-Instanz besitzt zusätzlich:

- `write_file`: überschreibt beliebige Pfade,
- `edit_file`: verändert beliebige vorhandene Pfade,
- `bash`: kann beliebige Shell- und Git-Kommandos ausführen.

Die aktuelle Tool-Safety schützt die Root-Verträge nicht:

- `write_file` und `edit_file` verlangen nur einen vorherigen Read desselben Pfads.
- Es gibt keine deny- oder allowlist für `CLAUDE.md`, `AGENTS.md` oder
  `.steward/conventions.md`.
- Bash wird auf allgemeine Bedrohungsmuster geprüft, aber nicht durch die Protected-Branch-
  Logik von `GitTool` geführt.
- Im Heartbeat-Prozess sind `GH_TOKEN` und die durch Checkout persistierten Git-Credentials
  aus `FEDERATION_PAT` verfügbar. Ein Bash-Aufruf hat daher technisch einen separaten
  Git-/GitHub-Pfad, auch wenn dafür kein produktiver Root-Push beobachtet wurde.

Diese Tools sind keine zulässigen kanonischen Context-Publisher. Sie sind dennoch Teil der
Angriffs- und Concurrency-Fläche, weil andere Delivery-Pfade ihre Änderungen aufsammeln
können.

---

## 7. Befund D — strukturierte Git-Pfade schützen nur teilweise

`GitTool` und `GitActuator` blockieren Commit und Push auf `main`, `master`, `develop`
beziehungsweise `release`. Proaktive Fixes verwenden Feature-Branch und PR.

Diese Schutzklasse deckt das System nicht vollständig ab:

- reaktive `guarded_llm_fix()`-Läufe arbeiten im aktuellen Worktree,
- der Bash-Toolpfad umgeht `GitTool`,
- `GitNadiSync` besitzt eine eigene Commit-/Push-Implementierung ohne Protected-Branch-
  Prüfung,
- der Workflow-Post-Step pusht ebenfalls unabhängig von `GitTool` und `GitActuator`.

Ein grün erscheinender Protected-Branch-Check in den strukturierten Tools beweist deshalb
keinen geschützten Produktionsbranch.

---

## 8. Befund E — `GitNadiSync` ist ein zweiter Remote-Publisher

`MokshaFederationHook` ruft bei geflushten Federation-Events `GitNadiSync.push()` auf.
Der Service wird mit `data/federation/` als Arbeitsverzeichnis registriert, befindet sich
aber innerhalb des Steward-Worktrees.

Seine Push-Semantik:

1. `_has_changes()` prüft den Status des gesamten Git-Worktrees.
2. Der Code versucht `git add nadi_inbox.json nadi_outbox.json peer.json`.
3. Danach versucht er separat `git add reports/`.
4. `data/federation/reports/` existiert am gepinnten Head nicht.
5. Schlägt einer der Add-Aufrufe fehl, führt der gemeinsame Exception-Handler
   `git add -A` aus.
6. Ohne Pfadspezifikation staged `git add -A` den gesamten Worktree.
7. Danach committed der Pfad mit `steward: federation sync` und pusht direkt den aktuellen
   Branch.
8. Eine Protected-Branch-Prüfung existiert nicht.
9. Bereits vor dem Aufruf gestagte, nicht zur Federation gehörende Änderungen würden auch
   ohne Fallback in den Commit gelangen.

Die Tests instanziieren `GitNadiSync` überwiegend am Root eines künstlichen Minimalrepos.
Sie prüfen Retry und Autostash, aber nicht die reale verschachtelte `data/federation/`-
Position, ein fehlendes `reports/` zusammen mit fremden Worktree-Änderungen oder den
ungewollten Root-Datei-Blast-Radius.

---

## 9. Produktionsbeweis — Heartbeat `#5351`

Run `29326469514` startete am Head
`c437eed490da500626d1c48168dd6282ca08594e` und erzeugte zwei aufeinanderfolgende
Main-Commits:

1. `576d5fda6e4b858e0b19b8632201baafa762db4d` — `steward: federation sync`
2. `02938251c2c28389340dede8d9e125ba05af17ab` —
   `chore: heartbeat #5351 state sync`

Der erste Commit wurde laut Log um `2026-07-14T10:49:43Z` von `GitNadiSync.push()`
erfolgreich gepusht. Er enthält nicht nur Federation-Dateien, sondern unter anderem:

- `.steward/context.json`
- `.steward/.context_hash`
- `.steward/memory.json`
- `.steward/sessions.json`
- `CLAUDE.md`

Der `CLAUDE.md`-Blob wechselte dabei von
`516d909f1b2445eee9e9ec8a366bdb9b12ab9688` zu
`a240cd5468a4bc53c1f9e3c18f4b8be7cdc7abe7`.

Erst danach lief der explizite Workflow-Post-Step, erzeugte den zweiten Commit und pushte
ihn. Der Log zeigt für diesen Push ausdrücklich, dass drei erwartete Statuschecks über den
aktuellen Principal umgangen wurden.

Der aktive `[SYNTHESIZE_BRIEFING]`-Task wurde im selben Run um `10:49:08Z` als „no issues
found“ beendet. Der beobachtete Root-Blob ist daher kein Beweis eines LLM-Toolwrites. Der
Codegraph und die Reihenfolge belegen stattdessen:

- der deterministische MOKSHA-Pfad kann `CLAUDE.md` lokal verändern,
- ein späterer MOKSHA-/Git-NADI-Push nimmt diese Änderung unkontrolliert mit,
- der Workflow-Post-Step ist nicht die einzige Remote-Transaktionsgrenze.

Damit ist der ältere Befund einer dauerhaft nicht publizierten Root-Datei widerlegt. Das
System besitzt keine saubere Publikationslücke, sondern eine **unbeabsichtigte,
überbreite Nebenkanal-Publikation**.

---

## 10. Befund F — reale interne Parallelität

`StewardAgent.__init__()` konstruiert Cetana und startet den Daemon-Thread sofort.
Cetanas Phase-Callback ruft dieselben Methoden `_phase_genesis`, `_phase_dharma`,
`_phase_karma` und `_phase_moksha` auf.

Der Heartbeat-Workflow konstruiert denselben Agenten und ruft zusätzlich in einer eigenen
Schleife genau diese vier Phasen manuell auf. Daraus folgen innerhalb eines einzigen
Workflow-Jobs mindestens zwei Dispatch-Ursprünge:

- Cetana-Daemon-Thread,
- manuelle Workflow-Schleife.

`PhaseHookRegistry.dispatch()` besitzt keinen Lock. Auch die Rate-Limit-Felder von
`MokshaContextBridgeHook` und `GitNadiSync` sind nicht gelockt. Die Workflow-Concurrency
`group: steward-heartbeat` verhindert nur zwei gleichnamige GitHub-Actions-Runs; sie
serialisiert nicht diese internen Threads und nicht andere lokale/API-/Daemon-Prozesse.

Der Produktionslog zeigt ineinander verschachtelte GENESIS-, KARMA- und MOKSHA-Ereignisse
im selben Zeitfenster. Damit ist die interne Mehrfachdispatch-Landschaft nicht nur
theoretisch aus dem Code abgeleitet.

---

## 11. Vollständiges Publisher-Modell am gepinnten Head

| Ebene | Pfad | Semantik | Produktiv belegt |
|---|---|---|---|
| lokaler kanonisch behaupteter Writer | `write_claude_md()` via MOKSHA | deterministisch, direkt, nicht atomar | ja |
| lokaler alternativer Writer | `SynthesizeBriefingTool` | LLM, Standard Root, beliebiger Zielpfad | Erreichbarkeit ja; konkreter Rootwrite in Run #5351 nein |
| generische lokale Writer | write/edit/bash | beliebiger Inhalt und Pfad | verfügbar; Context-Rootwirkung nicht beobachtet |
| strukturierter Branch-Publisher | GitTool/GitActuator | Feature-Branch/PR, Main blockiert | Code belegt |
| Remote-Nebenkanal | `GitNadiSync.push()` | aktueller Branch, Fallback `git add -A` | ja, inklusive `CLAUDE.md` |
| Workflow-Post-Step | Heartbeat YAML | `.steward/` und Federation explizit, Direct Push | ja |
| externe Agentoberflächen | CLI/API/Telegram | teilen Builtin-Tools; Prozess-/Checkout-abhängig | Konstruktion belegt |

`publish-federation.yml` pusht einen separaten `authority-feed`-Branch und ist kein
beobachteter Root-Context-Publisher. `post-merge.yml` triggert den Heartbeat und schafft
keinen dritten eigenen Root-Writer.

---

## 12. OQ-01 — Entscheidung

OQ-01 ist geschlossen:

1. LLM-Ausgabe darf niemals `CLAUDE.md`, `AGENTS.md` oder die statische
   Verfassungsquelle schreiben.
2. Der bestehende Toolname `synthesize_briefing` bleibt während der Migration erhalten,
   weil er die agentisch sichtbare Consumer-Oberfläche ist.
3. Der sichere Übergangsvertrag ist fail-closed:
   - `stdout` beziehungsweise ein ausdrücklich gekennzeichneter Preview-Return bleibt
     zulässig,
   - kanonische Root-Ziele werden abgelehnt,
   - beliebige Dateipfade werden nicht mehr akzeptiert,
   - ein alter Caller erhält einen expliziten Fehler statt eines stillen Rootwrites.
4. Ein späterer persistierter Preview-Pfad benötigt eine eigene PUBLIC_SAFE-, Retention-,
   Staging- und Provenance-Entscheidung. Bis dahin ist reine Rückgabe sicherer als eine
   neue Preview-Datei.
5. Die aktive Sankalpa-Strategie und der MTime-Intent dürfen nicht weiter behaupten, das
   LLM-Tool aktualisiere den kanonischen Root-Context. Ihre Migration gehört in dieselbe
   kleine Feature-Spec wie der Toolvertrag.
6. Die deterministische kanonische Payload darf optional LLM-Annotationen nur als
   untrusted Preview-Daten konsumieren, niemals umgekehrt.

Diese Entscheidung erhält Discovery und explizites Scheitern für unbekannte Caller. Sie
erhält bewusst nicht die unsichere Schreibwirkung.

---

## 13. OQ-16 — Entscheidung

OQ-16 ist geschlossen:

1. Das System hat am gepinnten Head mindestens zwei direkte Root-Writer.
2. Das System hat mindestens zwei Remote-Delivery-Wege innerhalb desselben Heartbeats.
3. `GitNadiSync` ist ein nachgewiesener überbreiter Main-Publisher und muss in jedem
   Concurrency-, Kill-Switch- und Recovery-Vertrag berücksichtigt werden.
4. Der aktuelle GitHub-Workflow erzeugt zusätzlich interne Parallelität, weil Cetana beim
   Agentenbau startet und dieselben Phasen manuell aufgerufen werden.
5. Generische Agententools sind keine kanonischen Publisher, können aber Root-Änderungen
   erzeugen, die der Git-NADI-Nebenkanal remote publiziert.
6. Die spätere Architektur darf genau einen kanonischen lokalen Publisher und genau eine
   kontrollierte Remote-Delivery-Grenze besitzen.
7. Bevor diese Grenze implementiert wird, muss OQ-14 einen Kill-Switch definieren, der
   Cetana, manuelle Phasen, Git-NADI-Push, Workflow-Post-Step und bereits laufende Jobs
   ehrlich abdeckt.

---

## 14. Sicherheitsauswirkung

- LLM- oder generische Worktree-Änderungen können über einen fachfremden Federation-Push
  auf `main` gelangen.
- Der dokumentierte Single-Writer-Vertrag ist sowohl lokal als auch remote falsch.
- `git add -A` im Fallback erweitert einen schmal benannten Federation-Publisher auf den
  gesamten Repository-Worktree.
- Branchschutz in `GitTool` vermittelt falsche Sicherheit, weil produktive Pushpfade ihn
  nicht verwenden.
- Mehrfachdispatch ohne Lock kann zwei Snapshots, Writes oder Git-Operationen überlappen.
- Der Workflow kann trotz erfolgreichem Abschluss einen nicht reviewten Root-Agentenvertrag
  und erwartete, aber noch nicht gelaufene Checks publizieren.

---

## 15. Nicht belegbare Annahmen

- Der konkrete GitHub-Account hinter `FEDERATION_PAT` bleibt unbekannt.
- Es ist nicht belegt, dass Bash oder generische File-Tools bereits einen Root-Vertrag
  remote verändert haben; nur die technische Erreichbarkeit ist belegt.
- Der Run `#5351` beweist keinen LLM-generierten Root-Inhalt.
- Externe Prozesse außerhalb der untersuchten Repository-Entry-Points können nicht aus
  dem Code inventarisiert werden.
- Die genaue Lock-, Rename-, fsync- und Crash-Recovery-Lösung bleibt OQ-06.
- Der vollständige Stop-/Credential-/Already-running-Vertrag bleibt OQ-14.

---

## 16. Gate-Wirkung

- OQ-01 ist geschlossen.
- OQ-16 ist geschlossen.
- OQ-07 bleibt bis OQ-14 und einer gewählten Delivery-Governance teilweise offen.
- G0 bleibt offen.
- Keine Writer-, Workflow-, Git-NADI-, Tool-, Credential- oder Branchschutzänderung ist
  durch dieses Evidence-Paket freigegeben.
- Der nächste isolierte Recon ist OQ-06/OQ-14: Dateisystem-, Lock-, Prozessstop-,
  Credential- und Recovery-Realität.
