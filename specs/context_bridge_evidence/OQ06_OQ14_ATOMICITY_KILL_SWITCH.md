# OQ-06 / OQ-14 — ATOMICITY, STOP UND RECOVERY

> **Status OQ-06:** EVIDENCE COMPLETE — vorhandene Garantien und erforderlicher Vertrag entschieden
> **Status OQ-14:** EVIDENCE PARTIAL — realer manueller Containment-Pfad belegt, Drill und dauerhafter Mechanismus offen
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `02938251c2c28389340dede8d9e125ba05af17ab`
> **Steward-Tree:** `7b622d34d476137e42dc1f79892754e13107fba0`
> **Scope:** Dateischreib-, Lock-, Prozessstop-, Credential- und Recovery-Semantik. Keine
> Änderung an Produktivcode, Workflow, Secrets oder Repository-Settings.

---

## 1. Untersuchungsfragen

### OQ-06

Welche Lock-, Tempfile-, Rename-, fsync- und Recovery-Semantik trägt das tatsächliche
Dateisystem und die Prozesslandschaft?

### OQ-14

Welcher reale Kill-Switch stoppt geplante, manuelle und bereits laufende Publisher?

---

## 2. Untersuchte Quellen

- `steward/context_bridge.py`
- `steward/briefing.py`
- `steward/tools/synthesize_briefing.py`
- `steward/hooks/moksha_bridge.py`
- `steward/git_nadi_sync.py`
- `steward/phase_hook.py`
- `steward/agent.py`
- `steward/cetana.py`
- `.github/workflows/steward-heartbeat.yml`
- getrackte `.steward/.atomic_*.tmp`-Artefakte
- Live-Workflow-, Run-, Secret-Metadaten und Branchschutz über GitHub API
- offizieller GitHub-Vertrag:
  - `https://docs.github.com/en/rest/actions/workflows`
  - `https://docs.github.com/en/rest/actions/workflow-runs`
  - `https://docs.github.com/en/actions/how-tos/troubleshoot-workflows`

---

## 3. Positive Beweise — bestehende Schreibsemantik

### 3.1 `context.json` und `.context_hash`

`write_context_json()` schreibt zwei getrennte Pfade nacheinander:

1. `.steward/context.json`
2. `.steward/.context_hash`

Jeder Pfad verwendet `_atomic_write()`:

- Tempfile im selben Parent-Verzeichnis über `tempfile.mkstemp()`;
- ein einzelner `os.write()`;
- `os.close()`;
- `os.replace(temp, ziel)`;
- best-effort Löschen des Tempfiles nur im Exception-Pfad.

Positive Eigenschaft: Das Tempfile liegt im selben Verzeichnis, wodurch ein
Cross-Filesystem-Rename vermieden wird.

Fehlende Garantien:

- kein Lock vor Hashcheck oder Write;
- kein Loop für einen theoretisch partiellen `os.write()`;
- kein `fsync()` des Dateiinhalts;
- kein `fsync()` des Parent-Verzeichnisses nach Rename;
- keine gemeinsame Transaktion über JSON und Hash;
- keine Generation-ID, die einen gemischten Zustand erkennt;
- Hash wird erst nach dem JSON ersetzt; ein Crash dazwischen erzeugt einen alten Hash zu
  neuem JSON;
- zwei konkurrierende Writer können Hashcheck und Replace überlappen.

### 3.2 Root-Dateien

`write_claude_md()` und der LLM-Synthese-Writer verwenden direkt `Path.write_text()`.
Damit fehlen sogar die per-Pfad Tempfile-/Replace-Eigenschaften. `AGENTS.md` existiert
noch nicht und besitzt folglich keinen Schreibvertrag.

### 3.3 Temp-Artefakte

Der gepinnte Tree enthält zwei getrackte `.steward/.atomic_*.tmp`-Dateien aus älteren
Heartbeat-Commits. Diese Namen stammen nicht aus der aktuellen `_atomic_write()`-
Namensform, beweisen aber historisch, dass temporäre Atomic-Write-Artefakte bereits bis in
Git gelangt sind. Sie dürfen nicht als aktueller Crashbeweis der Context-Bridge überdehnt
werden; sie sind ein positiver Beweis für fehlende Tempfile-Publikationshygiene.

---

## 4. Positive Beweise — Lock- und Prozessrealität

- Es existiert kein Context-Publisher-Lock.
- `PhaseHookRegistry.dispatch()` ist nicht gelockt.
- `MokshaContextBridgeHook._last_write` ist ein ungeschütztes Zeitfeld.
- `GitNadiSync._last_push` und `_last_pull` sind ungeschützte Zeitfelder.
- `StewardAgent` startet Cetana bereits im Konstruktor als Daemon-Thread.
- Der Produktionsworkflow ruft dieselben Phasen zusätzlich manuell auf.
- API und Telegram serialisieren teilweise ihren Agentenzugriff, bilden aber keinen
  repositoryweiten Publisher-Lock.
- GitHub-Actions-Concurrency serialisiert nur Runs derselben Concurrency Group und setzt
  `cancel-in-progress: false`.
- Andere lokale CLI-, API- oder Daemonprozesse werden dadurch nicht erfasst.

Damit benötigt die spätere Publisher-Grenze sowohl Thread- als auch Interprozess-Schutz.
Ein reiner `threading.Lock` oder eine reine Workflow-Concurrency wäre jeweils unzureichend.

---

## 5. Zwei Root-Dateien sind keine lokale Gruppentransaktion

Ein Replace kann höchstens die Sichtbarkeit eines einzelnen Zielpfads atomar machen.
Zwei reguläre Root-Pfade können nicht als eine einzige Dateisystemoperation ersetzt
werden.

Der Zielvertrag darf deshalb nicht „echte Zwei-Dateien-Atomarität“ versprechen. Er muss
ehrlich unterscheiden:

1. atomare Ersetzung jeder einzelnen Datei,
2. gemeinsame Generation-/Payload-Identität,
3. Erkennung eines gemischten Zustands,
4. kein positiver Publisher-Erfolg bei Teilzustand,
5. deterministische Reparatur beim nächsten exklusiven Lauf,
6. ein Git-Commit als gemeinsame Remote-Snapshot-Grenze.

Ein externer Consumer, der genau zwischen zwei lokalen Replaces liest, kann trotzdem
einen Mischzustand sehen. Dieses Restrisiko muss durch kurze exklusive Publish-Fenster,
Generation-Marker und fail-closed Validierung reduziert und darf nicht wegdokumentiert
werden.

---

## 6. OQ-06 — Entscheidung

OQ-06 ist geschlossen. Jede spätere Feature-Spec muss mindestens folgenden Vertrag
erfüllen:

### 6.1 Exklusivität

- genau ein Publisher-Einstieg;
- pro Prozess ein Thread-Lock;
- repositoryweiter Interprozess-Lock mit begrenztem Timeout;
- Lock umfasst Snapshot, Render, beide Root-Replaces, Manifest/Generation und
  Erfolgsentscheidung;
- Lockfehler publiziert nichts und meldet sichtbare Degradation.

### 6.2 Per-Datei-Schreiben

- Tempfile im Zielverzeichnis;
- vollständiger Write mit geprüfter Byteanzahl;
- Flush und `fsync()` vor Replace;
- per-Pfad atomarer Replace;
- Parent-Verzeichnis nach Replace synchronisieren, soweit Plattformvertrag unterstützt;
- Zielpfad und Parent vor Symlink-/Nichtdatei-Manipulation prüfen;
- Tempfiles bei Fehlern bereinigen und bei Kaltstart als Recovery-Signal behandeln.

### 6.3 Generationsvertrag

- beide Root-Dateien tragen dieselbe `snapshot_id` und denselben `payload_hash`;
- Hash-/Manifest-Metadaten werden nicht als unabhängige Wahrheit vor dem Payload
  veröffentlicht;
- gemischte Generation ist `invalid`, nicht `degraded-but-current`;
- Erfolg erst nach Read-back und Contract-Validierung beider Dateien;
- Remote-Publish nur als ein validierter Git-Commit mit allen Artefakten;
- kein Git-NADI- oder generischer Worktree-Nebenpublisher.

### 6.4 Recovery

- Halbzustand wird beim nächsten Lauf erkannt und repariert;
- bei nicht reparierbarem Zustand bleibt beziehungsweise entsteht der statische
  Minimal-Fallback;
- alte dynamische Agenda wird nicht automatisch zurückgerollt und als aktuell ausgegeben;
- Recovery ist idempotent und benötigt keinen LLM-Pfad.

Die konkrete Lockbibliothek und Manifestform gehören in Feature-Spec 01. Die hier
entschiedenen Garantien sind lösungsneutral, aber verbindlich.

---

## 7. Positive Beweise — aktuelle Stop-Oberflächen

### 7.1 Im Prozess

- Cetana reagiert auf `SIGTERM` und `SIGINT`, indem es sein Stop-Event setzt.
- `StewardAgent.close()` stoppt Cetana und wartet höchstens fünf Sekunden auf den Thread.
- Ein weiterlaufender Thread wird nur gewarnt; es gibt keinen Publisher-spezifischen
  Drain- oder Fence-Vertrag.
- Es gibt keinen Environment-, Repository-Variable- oder Feature-Flag-Schalter für
  Context-Publish oder `GitNadiSync`.

### 7.2 Auf GitHub

- Workflow `Steward Heartbeat`, ID `246208277`, war beim Recon `active`.
- Trigger sind Schedule alle 15 Minuten und `workflow_dispatch`.
- Der Commit-Step trägt `if: always()`.
- Am Abfragezeitpunkt gab es keine queued oder in-progress Runs.
- `FEDERATION_PAT` existiert als Repository-Secret; sein Wert und Principal sind nicht
  sichtbar.
- Der Operator ist als `kimeisele` mit den Scopes `repo` und `workflow` authentifiziert.
- Die GitHub-API bietet einen Workflow-Disable-Endpunkt und normale sowie Force-Cancel-
  Endpunkte.
- Laut offizieller Dokumentation verhindert Disable neue Trigger, beendet aber nicht als
  eigener Vertrag bereits laufende Runs.
- Laut offizieller Dokumentation umgeht Force-Cancel Bedingungen wie `always()`, die eine
  normale Cancellation weiterlaufen lassen können.

---

## 8. Reale Gefahr eines unvollständigen Stops

Ein einzelner Schritt reicht nicht:

- Nur Workflow disable: laufende oder bereits gequeuete Runs bleiben zu behandeln.
- Nur normal cancel: `if: always()` kann den Commit-/Push-Step weiter ausführen.
- Nur Cetana stop: manuelle Workflow-Schleife, Git-NADI und Post-Step bleiben außerhalb.
- Nur Secret löschen: ein laufender Checkout kann Credentials bereits lokal persistiert
  haben; das zugrunde liegende PAT bleibt außerhalb des Secret-Stores gültig.
- Nur Branchschutz: der aktuelle Principal hat in Produktion erwartete Checks bereits
  umgangen; Administrator-Erzwingung ist aus.
- Nur Revert: der nächste aktive Publisher kann den Zustand erneut überschreiben.

---

## 9. OQ-14 — vorläufiger manueller Containment-Vertrag

Ein heute real ausführbarer Notstopp muss in dieser Reihenfolge erfolgen:

1. **Neue Starts sperren:** Workflow `246208277` über GitHub API beziehungsweise
   `gh workflow disable steward-heartbeat.yml` deaktivieren und Zustand
   `disabled_manually` verifizieren.
2. **Aktive Arbeit stoppen:** queued und in-progress Runs erneut listen; wegen
   `if: always()` für nicht zuverlässig stoppende Runs den offiziellen Force-Cancel-
   Endpoint verwenden; bis zum terminalen Status pollen.
3. **Push-Autorität entziehen:** `FEDERATION_PAT` beim tatsächlichen Aussteller widerrufen
   oder rotieren und danach das Repository-Secret entfernen/ersetzen. Secret-Löschung
   allein ist keine Revocation des Tokens.
4. **Remote fence setzen:** Main-Schreibbarkeit so einschränken, dass der bisherige
   Automation-Principal keine Direct-Push-/Check-Bypass-Wirkung mehr besitzt; konkrete
   Branch-/Ruleset-Änderung benötigt eine reviewte Governance-Operations-Spec.
5. **Zustand prüfen:** Main-Head und alle seit Start des Incidents erzeugten Commits gegen
   erlaubte Pfade und Blobs verifizieren.
6. **Sicherer Fallback:** bei invalidem Root-Context nur den menschlich reviewten statischen
   Minimalvertrag publizieren; keine alte dynamische Agenda als aktuell restaurieren.
7. **Wiederanlauf:** erst nach Root-Cause-Fix, Contract-Checks, Credential-Minimierung und
   expliziter menschlicher Freigabe Workflow und Writer wieder aktivieren.

Diese Schritte sind ein Containment-Runbook, kein bereits getesteter Ein-Klick-Kill-Switch.

---

## 10. Warum OQ-14 noch nicht geschlossen ist

- Der Disable-/Force-Cancel-/Revocation-Ablauf wurde aus Sicherheitsgründen nicht
  destruktiv gegen Produktion ausgeführt.
- Der Principal und Aussteller von `FEDERATION_PAT` sind unbekannt.
- Es existiert kein minimal privilegierter, publisher-spezifischer Credential-Vertrag.
- Es existiert kein in-repo Feature-Flag, das alle lokalen Writer und Delivery-Pfade vor
  jeder Seiteneffektgrenze fail-closed stoppt.
- Ein Branch-/Ruleset-Fence ist wegen OQ-07 noch nicht als konkrete, getestete
  Governance-Topologie entschieden.
- Der statische Minimal-Fallback ist konzeptionell beschrieben, aber noch nicht als
  reviewtes Artefakt und Drill verifiziert.

OQ-14 kann erst schließen, wenn ein kontrollierter Operations-Drill mindestens Disable,
Run-Inventar, Force-Cancel-Semantik, Credential-Revocation/Fence und sicheren Wiederanlauf
belegt. Dieser Drill darf nicht beiläufig während der G0-Recon erfolgen.

---

## 11. Sicherheitsauswirkung

- Ein normaler Cancel kann wegen `always()` noch genau den gefährlichen Push-Step
  erreichen.
- Ein Crash zwischen Payload und Hash erzeugt einen logisch widersprüchlichen, aber lokal
  vollständig lesbaren Zustand.
- Direkte Root-Writes können Leser mit partiellen Dateien konfrontieren.
- Ohne Interprozess-Lock konkurrieren Cetana, manuelle Phasen und externe Prozesse.
- Ohne Credential-Revocation kann ein deaktivierter Workflow die eigentliche
  Schreibautorität außerhalb GitHubs nicht entziehen.
- Ohne getesteten Fallback kann ein Revert veraltete Handlungsdaten erneut autoritativ
  erscheinen lassen.

---

## 12. Nicht belegbare Annahmen

- Das konkrete Dateisystem des jeweils nächsten GitHub-Hosted-Runners ist nicht als
  stabiler Projektvertrag belegt.
- Die aktuelle Implementierung beweist keine Power-Loss-Durability trotz `os.replace()`.
- Die Rechte und globale Lebensdauer von `FEDERATION_PAT` sind unbekannt.
- Ein API-verfügbarer Force-Cancel-Endpunkt beweist ohne Drill nicht die gesamte
  betriebliche Reaktionszeit.
- Externe, nicht im Repository sichtbare Daemons müssen beim Incident zusätzlich
  inventarisiert werden.

---

## 13. Gate-Wirkung

- OQ-06 ist geschlossen.
- OQ-14 bleibt teilweise offen.
- OQ-07 bleibt bis OQ-14 und der Delivery-Governance teilweise offen.
- G0 bleibt offen.
- Keine Lock-, Writer-, Workflow-, Secret-, Branchschutz- oder Recovery-Änderung ist aus
  diesem Evidence-Paket freigegeben.
- Der nächste isolierte Recon ist OQ-12/OQ-05: Feldklassen, Normalisierung, Hash-Domains
  und semantische Commitwürdigkeit.
