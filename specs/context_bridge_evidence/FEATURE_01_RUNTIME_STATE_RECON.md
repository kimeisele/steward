# FEATURE 01 — RUNTIME-STATE-PERSISTENZ RECON

> **Status:** EVIDENCE COMPLETE — ZIELARCHITEKTUR ENTSCHIEDEN; EIGENE FEATURE-SPEC ERFORDERLICH
> **Datum:** 2026-07-15
> **Code-Basis:** `kimeisele/steward@31651bfc52c98bb6be66d7adb6f3055cbc410388`
> **Live-Drift geprüft bis:** `kimeisele/steward@29df3f74ce62c4ce7c0b1edbb649f3f8eff75166`
> **Scope:** Read-only State-, Consumer-, Datenklassen- und Delivery-Recon

---

## 1. Frage

Kann `main` PR-only und Context Bridge auf einen Vier-Artefakt-PR begrenzt werden, ohne
die Restart-Kontinuität des ephemeren Heartbeats oder die Federation-Liveness zu brechen?

---

## 2. Aktuelle Delivery-Realität

Der Workflow staged bei jedem Lauf:

```text
git add -u -- .steward/ data/federation/
git add -- data/federation/
```

Danach committed, rebased und pusht er direkt auf `main`. `GitNadiSync` kann zuvor einen
zweiten Commit erzeugen; wenn sein enges Staging fehlschlägt, verwendet er `git add -A`.

Der Live-Commit `f01a3ec9e7ce903bcc84cbedc5aacc5a8f04bedd` belegt, dass dieser Fallback
gleichzeitig Root-Governance, Cognitive State und Federation-State publiziert.

Der Heartbeat läuft planmäßig ungefähr alle 15 Minuten. Im untersuchten Fenster wurden
zusätzliche `workflow_dispatch`-Runs beobachtet. Erfolgreiche Runs dauerten ungefähr zwei
bis fünf Minuten. Die Workflow-Concurrency verhindert überlappende Actions-Runs, aber
nicht interne Git-NADI-Commits oder externe lokale Prozesse.

---

## 3. Dateninventar

### 3.1 Rekonstruierbare Diagnose

| Pfad | Inhalt | Restart-Notwendigkeit | Datenklasse |
|---|---|---|---|
| `.steward/.context_hash` | gekürzter Raw-Context-Hash | keine; neu berechenbar | intern |
| `.steward/context.json` | Full-fidelity Raw-Context | keine kanonische Notwendigkeit; heutiger Legacy-Cache | enthält lokale Pfade und freie Prosa |
| `.steward/federation_health.json` | aktueller Health-Snapshot | neu ableitbar | öffentliche Aggregate möglich |
| `data/federation/steward_health.json` | duplizierter Health-Snapshot | neu ableitbar | öffentliche Aggregate möglich |

Diese Dateien rechtfertigen keine dauerhafte Main-Persistenz. Insbesondere ist
`context.json` nicht PUBLIC_SAFE und darf weder Context-Artefakt noch öffentlicher
State-Checkpoint bleiben.

### 3.2 Kognitive Kontinuität

| Pfad | Inhalt | Restart-Wirkung | Datenklasse |
|---|---|---|---|
| `.steward/memory.json` | Memory-Einträge, Entities, Resolution-/Toolkontext | `PersistentMemory` lädt bei Boot | freie Prosa, lokale Pfade, potenziell sensible Arbeitsdaten |
| `.steward/sessions.json` | Aufgaben, Summaries, Files, Outcomes | `SessionLedger` lädt bei Boot und erzeugt Prompt-Context | freie Prosa, Agenten-Input |
| `.steward/marketplace.json` | Claims, Trust, TTL | Marketplace lädt bei Boot | strukturierter Runtime-State |

Der gepinnte `memory.json`-Blob enthält zahlreiche lokale absolute Pfade. Ein einfacher
Secret-Regex-Scan fand in den untersuchten aktuellen Blobs kein klassisches Token-/PEM-
Muster; das ist kein Freigabebeweis. Freie Memory-/Sessiondaten bleiben prompt-injection-
und privacy-relevant.

### 3.3 Federation-Kontinuität

| Pfadklasse | Restart-Wirkung | Datenklasse |
|---|---|---|
| `nadi_inbox.json` / `nadi_outbox.json` | lokale Transportpuffer | untrusted Federation-Nachrichten, Signaturen, freie Payloads |
| `relay_seen_ids.json` | verhindert erneute Verarbeitung bereits gezogener Hub-Nachrichten | strukturierte Dedup-IDs |
| `peers.json` | Reaper lädt Liveness, Trust und Fingerprintkontinuität | strukturierte Peer-Metadaten |
| `quarantine/index.json` | Replay-/Audit-Bestand abgelehnter Nachrichten | untrusted IDs; zugehörige lokale Records können Rohdaten enthalten |
| `receipts.json` | Delivery-Kontinuität | strukturierte Federation-Metadaten |
| `discovered_peers.json` / Ledger / Diagnose | Discovery- und Lernkontinuität | gemischter Runtime-State |

Der Cross-Repo-Nachrichtentransport existiert bereits separat in
`kimeisele/steward-federation`. Der Steward-Relay schreibt dort per-peer Mailboxes und
Legacy-Outbox; andere untersuchte Repositories relayen ebenfalls über diesen Hub.

Read-only Code-Suche fand keinen positiven Beweis, dass öffentliche Schwesterrepositories
Steward-Main-`context.json`, `memory.json`, `sessions.json`, `relay_seen_ids.json` oder
`steward_health.json` direkt konsumieren. Das ist kein Abwesenheitsbeweis für private oder
dynamische Consumer.

### 3.4 Statische öffentliche Federation-Dateien

`data/federation/peer.json`, `verified_agents.json` und ähnliche reviewte Registry-
Artefakte sind nicht automatisch volatile Runtime-State-Dateien. Sie dürfen nicht bei
einer State-Migration pauschal aus `main` entfernt werden. Jeder Pfad benötigt eine
Source-of-Truth- und Writerklassifikation.

---

## 4. Bewertete Optionen

### Option A — Weiterhin direkt auf `main`

**Verworfen.** Verhindert PR-only-Governance, vermischt Code und Runtime, erzeugt hohe
History-Churn und hält den Root-/Worktree-Nebenpublisher offen.

### Option B — State in den Context-Delivery-PR aufnehmen

**Verworfen.** Context Bridge besitzt eine PUBLIC_SAFE-Vier-Artefakt-Grenze. Raw Memory,
Sessions und Federation-Payloads haben andere Trust-, Retention- und Consumerverträge.
Ein gemeinsamer PR würde die gerade geschaffene Sicherheitsgrenze wieder auflösen.

### Option C — Vollständiger Checkpoint auf öffentlichem State-Branch

**Verworfen für kognitiven und rohen Federation-State.** Ein separater Branch entfernt
Code-Churn aus `main`, ändert aber nicht die öffentliche Veröffentlichungsgrenze. Memory,
Sessions, lokale Pfade und untrusted Payloads würden weiterhin öffentlich versioniert.

Ein öffentlicher Branch kann später für ausdrücklich PUBLIC_SAFE Aggregate geeignet sein,
ist aber kein Full-State-Store.

### Option D — Actions Cache oder Workflow-Artefakte als kanonischer Store

**Verworfen als alleinige Wahrheit.** Cache ist eviction-/key-basiert und nicht als
mutierbarer, dauerhaft adressierter Statevertrag ausgelegt. Workflow-Artefakte besitzen
Retention und Runbindung. Beide können Diagnose-/Backuprollen übernehmen, aber keinen
unbegrenzten, crash-konsistenten kanonischen Checkpoint vortäuschen.

### Option E — Verschlüsselter Blob im öffentlichen Repository

**Vorläufig verworfen.** Er führt Key-Rotation, Nonce-, Partial-write-, Recovery- und
History-Probleme ein und hält hochfrequenten Runtime-State weiter im Code-Repository. Ein
neues Kryptoprotokoll ist für diesen Schnitt unnötiges Risiko.

### Option F — Getrennter privater Runtime-State-Store plus öffentlicher Hub

**Gewählt als Zielarchitektur.**

- Cross-Repo-Nachrichten bleiben im bestehenden öffentlichen Federation-Hub und werden
  nicht über Steward-`main` transportiert.
- Vertraulicher oder prompt-relevanter Restart-State liegt in einem getrennten privaten,
  eng berechtigten Store.
- Rekonstruierbare Diagnose wird nicht dauerhaft checkpointed.
- Statische öffentliche Registry-/Descriptor-Dateien bleiben reviewter Code-/Datenbestand
  auf `main`.
- PUBLIC_SAFE Health-/Federation-Aggregate können später über einen eigenen Outputvertrag
  veröffentlicht werden, sind aber nicht Teil des privaten Full-State-Checkpoints.

Die konkrete Store-Implementierung darf ein privates Git-Repository sein, wenn dessen
Branch-, Lease-, Retention-, Credential- und Atomicity-Vertrag die spätere Feature-Spec
erfüllt. Diese Evidence entscheidet die Trust-Grenze, nicht vorschnell den Treiber.

---

## 5. Zielvertrag für die eigene Feature-Spec

### 5.1 Default deny

Kein bestehender getrackter Runtimepfad wird pauschal übernommen. Die Feature-Spec erstellt
eine Feld-/Pfad-Allowlist und klassifiziert jeden Kandidaten als:

- `reconstruct`,
- `private_checkpoint`,
- `public_static`,
- `public_derived`,
- `drop_after_migration`,
- `manual_review_required`.

### 5.2 Restore vor Boot

Der Heartbeat darf den Agenten erst booten, nachdem:

- Store-Identität und erwartetes Schema validiert sind,
- ein generationsgebundener Checkpoint vollständig gelesen wurde,
- jeder Pfad relativ, symlinkfrei und allowlistet ist,
- Hash/Manifest und Größenlimits stimmen,
- untrusted Inhalte nicht zu Konfiguration oder Code werden,
- fehlender oder invalider State als sichtbarer Cold Start gilt.

Ein State-Fehler darf niemals beliebige Repository-Dateien überschreiben.

### 5.3 Checkpoint nach dem Lauf

Checkpoint benötigt:

- einen exklusiven Lease-/Generation-Vertrag,
- per-Datei und Manifestbindung,
- Record-last oder äquivalente Commitsemantik,
- explizite Maximalgrößen und Retention,
- Secret-/Pfad-/Schema-Validierung nach Datenklasse,
- keine Worktree-Globs,
- keine Code-, Workflow-, Constitution- oder Root-Datei,
- keine gemeinsame Push-Credential mit unbeschränktem Main-Bypass.

### 5.4 Federation

Vor Entfernung lokaler Git-NADI-Persistenz müssen Tests beweisen:

- Hub-Pull rekonstruiert neue Inbound-Nachrichten,
- persistierte Seen-IDs verhindern Replay über Runner-Restarts,
- Outbound wird erst nach bestätigtem Hubwrite geleert,
- ein fehlgeschlagener Hubwrite verliert keine Nachricht,
- Reaper-/Trust-/Quarantine-Kontinuität bleibt erhalten oder besitzt eine explizite neue
  Semantik,
- Git-NADI ist danach nicht mehr als heimlicher Main-Transport erforderlich.

---

## 6. Migration und Historie

Eine spätere Migration muss:

1. neuen privaten Store und Credentials ohne Main-Bypass bereitstellen,
2. aktuellen State unter kontrolliertem Stop einmalig klassifizieren und migrieren,
3. Restore/Checkpoint im Preview testen,
4. Git-NADI und Workflow-Main-State-Push deaktivieren,
5. nur ausdrücklich statische Pfade auf `main` behalten,
6. volatile getrackte Pfade in einem separaten Hygiene-PR aus dem Main-Tree entfernen,
7. Folgeheartbeats auf Wiederaufnahme prüfen.

Historienrewrite ist nicht automatisch erforderlich. Der aktuelle Scan fand keinen
positiven klassischen Secret-Treffer, aber lokale Pfade und freie Prosa sind bereits
öffentlich. Ein späterer positiver Credential-/Private-Key-Befund löst ein eigenes
Incident- und History-Purge-Verfahren aus; er wird nicht durch normale Migration
verschleiert.

---

## 7. Sicherheitsauswirkung

- `main` kann erst nach State-Entkopplung ehrlich PR-only werden.
- Context Bridge darf vorher implementiert, getestet und disabled gemergt werden, aber
  nicht automatisch canonical publizieren.
- Ein privater Store reduziert Veröffentlichungsblast-radius, macht restored Memory aber
  nicht vertrauenswürdig; Schema- und Prompt-Grenzen bleiben nötig.
- Der öffentliche Federation-Hub bleibt Transport, nicht kognitive Memory-Datenbank.
- Das bestehende `FEDERATION_PAT` ist zu breit für eine dauerhafte Trennung; Credential-
  Minimierung gehört in die Operations-Spec.

---

## 8. Nicht belegbare Annahmen

- Kein externer Consumer des Steward-Main-Runtime-State konnte positiv belegt werden; ein
  privater oder dynamischer Consumer kann mit Code-Suche nicht ausgeschlossen werden.
- Der konkrete private Store und dessen Betreiber-/Ownerpfad sind noch nicht freigegeben.
- Welche Memory-/Sessionfelder langfristig überhaupt persistiert werden sollten, benötigt
  eine eigene semantische Datenminimierung.
- Die Auswirkungen eines vollständigen Cold Starts auf autonome Lernqualität sind noch
  nicht in Produktion gemessen.

---

## 9. Gate-Wirkung

- Die Trennung `Context-Delivery != Runtime-State-Delivery` ist entschieden.
- Vollständiger öffentlicher State-Branch und Context-PR sind verworfen.
- Ziel ist privater minimaler Checkpoint plus bestehender öffentlicher Federation-Hub.
- Eine eigene Feature-Spec mit Feldklassifikation, Store-, Restore-, Checkpoint-,
  Credential-, Migration- und Drillvertrag ist vor Feature-01-Aktivierung zwingend.
- Keine Produkt-, Workflow-, Repository-, Secret- oder GitHub-Setting-Änderung ist durch
  dieses Evidence-Paket freigegeben.
