# FEATURE 01 / SCHNITT D — G2-PRE-FLIGHT

> **Status:** G2 START APPROVED — ausschließlich D1: strikter reiner Persisted-Generation-Read-back nach Merge dieses Dokuments
> **Datum:** 2026-07-16
> **Produktionsbasis:** `kimeisele/steward@ff635f3b05ec225349d776e7ee557119b424bdb5`
> **Produktions-Tree:** `ddb1a833f13a707bfe048fd91575d784fcecf663`
> **Feature-Spec:** `specs/CONTEXT_BRIDGE_FEATURE_01.md` — G1 APPROVED
> **Voraussetzung:** Schnitt C Merge `1d009b6cc7f26adfb5e2d179688c5c8990fe9ede`, Produktionsbeweis `specs/context_bridge_evidence/FEATURE_01_SLICE_C_PRODUCTION.md`
> **Scope:** read-only G2-Pre-Flight und enger Startentscheid; noch keine Produktcodeänderung

---

## 1. Entscheidung

Der heutige Live-Recon bestätigt die Notwendigkeit von Schnitt D, widerlegt aber einen
einzigen kombinierten Publisher-/Recovery-Patch als sicheren nächsten Schritt. Zwischen
den bereits reinen Kandidatenbytes und einem fehlertoleranten Dateisystem-Publisher fehlt
zuerst ein strikter Loader, der eine beliebige bereits persistierte Vier-Artefakt-
Generation ohne Vertrauen in den Publication Record vollständig neu beweist.

Schnitt D wird deshalb ohne Änderung seines End-to-End-Ziels in zwei G2-Etappen geteilt:

1. **D1 — Persisted-Generation-Read-back:** reine Byte-Parser, Envelope-/Root-
   Cross-Validation und Laden eines `PreviousPublishedRecord` ausschließlich aus einer
   vollständig validierten Vier-Artefakt-Generation.
2. **D2 — POSIX-Publisher und Recovery:** Repository-Fences, Thread-/Prozesslock,
   Pfadschutz, durable Prepare/Replace, Record-last, Kaltstartklassifikation und Recovery.

Dieses Dokument autorisiert nach seinem regulären Merge ausschließlich D1. D2 bleibt
vollständig gesperrt und benötigt auf dem dann aktuellen `origin/main` einen eigenen
read-only G2-Pre-Flight. Die Teilung verhindert, dass Parser-, Git-, Lock-, Pfad-,
Durability- und Crashlogik in einem sicherheitskritischen Mega-Patch gleichzeitig
erfunden und getestet werden.

---

## 2. Gepinnte Live-Evidence

### 2.1 Main, Parallelität und Drift

Nach `git fetch origin --prune` galt am gepinnten Head:

- kein offener Pull Request;
- lokaler Arbeitsbaum sauber und bytegleich zu `origin/main`;
- der Drift seit `7aaa905682f88beb027086dce255af012ef81d46` bestand ausschließlich
  aus elf bekannten `.steward/`- und Federation-Runtime-State-Pfaden;
- `steward/context_contract.py`, `steward/context_rendering.py`, ihre Tests, die
  Feature-Spec und `.gitignore` waren von diesem Drift nicht betroffen;
- `steward/context_rendering.py` besitzt keinen Produktivcaller.

Unmittelbar vor dem ersten D1-Patch werden Head, offene PRs und die vier erlaubten
Produkt-/Testpfade erneut geprüft. Ein fachlicher Main-Drift oder ein überlappender PR
stoppt G2.

### 2.2 Aktueller Repository-Zustand

Der reale Tree befindet sich weiterhin in Migrationszustand P1:

| Ziel | Zustand am gepinnten Head |
|---|---|
| `CLAUDE.md` | getrackte reguläre Datei, Blob `8146a15603c95e5aa1404c9eb7021e3008914b0c` |
| `AGENTS.md` | absent |
| `.steward/context-snapshot.json` | absent |
| `.steward/context-publication.json` | absent |
| `.github/context-bridge-policy.json` | absent; effektiver Vertrag bleibt `disabled` |

`.steward/` und `CLAUDE.md` sind keine Symlinks. Beide JSON-Zielpfade, Lockpfade und
Publisher-Tempnamen werden derzeit durch die breite `.steward/`-Regel in `.gitignore`
ignoriert. Die zwei historischen getrackten `.steward/.atomic_*.tmp`-Dateien sind keine
Context-Publisher-Generation und dürfen niemals als Recovery-Signal interpretiert werden.

D1 liest keine dieser realen Dateien. Die Tabelle bindet nur den Migrationszustand und
beweist, dass dieser PR weder einen Bootstrap noch eine Root-Mutation vorwegnehmen darf.

### 2.3 Vorhandene reine Wahrheit

`steward/context_contract.py` liefert bereits die geschlossenen Modelle, Validatoren und
Hash-Domains. `steward/context_rendering.py` erzeugt daraus genau vier immutable
Kandidatenbytes:

```text
CLAUDE.md
AGENTS.md
.steward/context-snapshot.json
.steward/context-publication.json
```

`validate_publication_candidates()` kann Kandidaten gegen explizit mitgelieferte
Payload-/Snapshot-Modelle durch deterministischen Rebuild prüfen. Es kann aber keine
beliebigen Disk- oder Git-Bytes selbstständig laden und beweisen.

### 2.4 Positive Parserlücke

Der Live-Code besitzt keinen öffentlichen strikten Parser für:

- `steward.context.snapshot-artifact/v1`;
- `steward.context.publication-artifact/v1`;
- den festen Root-Renderervertrag einschließlich C0, Dynamic und Orientation;
- das innere `steward.context.published-record/v1` aus untrusted JSON-Bytes;
- eine vollständige, untereinander gebundene persistierte Generation.

`PreviousPublishedRecord` ist typisiert und `decide_publish()` validiert ihn intern. Die
aktuelle `_valid_previous()`-Logik ist jedoch privat, boolesch und erhält bereits
materialisierte Pythonwerte. Ein späterer Publisher dürfte deshalb heute entweder dem
Record vertrauen oder dieselben Schemas und Hashregeln ein zweites Mal implementieren.
Beides ist unzulässig.

---

## 3. Warum vorhandene I/O-Primitiven D2 nicht freigeben

### 3.1 Legacy-Writer im Steward-Repo

`steward/context_bridge.py::_atomic_write()` verwendet zwar ein Same-Directory-Tempfile
und `os.replace()`, besitzt aber keinen Lock, keinen Partial-Write-Loop, kein File-fsync,
kein Parent-fsync, keinen Pfad-/Symlinkschutz und keine Gruppentransaktion. Der separate
Write von `.steward/context.json` und `.steward/.context_hash` kann gemischt abbrechen.

Der MOKSHA-Hook schreibt nach dem bereits gemergten Writer-Fence nur diesen separaten
Legacy-Raw-State. Er ist kein Caller des neuen Renderers und darf in D1 oder D2 nicht
heimlich zum Root-Publisher werden.

### 3.2 Steward-Protocol-Helfer

Der live installierte beziehungsweise benachbarte Protocol-Code bietet keine hinreichende
Wiederverwendung:

- `vibe_core/utils/atomic_io.py::atomic_write_text()` besitzt File-fsync und Same-Parent-
  Rename, aber keinen vollständigen Write-Loop, Parent-fsync, Lock oder Pfadschutz.
- `vibe_core/task_management/file_lock.py::FileLock` basiert auf Lockfile-Existenz und
  löscht bei Timeout vermeintlich stale Locks. Es verwendet keinen Kernel-`flock` und
  kann einen noch lebenden Writer verdrängen.

Diese Helfer werden für Context Publication nicht wiederverwendet. Insbesondere wird der
existierende `FileLock` nicht durch zusätzliche Publisher-Annahmen „gehärtet“.

### 3.3 Git- und Workflow-Helfer

`GitNadiSync`, `GitTool`, Actuators und Git-Senses sind für andere Trust- und Mutations-
Verträge gebaut. Keiner liefert einen read-only, targetgebundenen Publisher-Fence über
HEAD, Index und Worktree. GitHub-Actions-Concurrency serialisiert nur Workflow-Runs und
nicht lokale CLI-, API-, Daemon- oder Thread-Aufrufe.

D2 benötigt daher später eine kleine eigene, injizierbar testbare Git-Fence-Grenze. Es
darf weder Git-NADI noch den mutierenden allgemeinen Git-Toolpfad importieren.

### 3.4 Plattformbeweis

Die Engineering-Plattform ist Darwin/POSIX, Produktion `ubuntu-latest`/Linux. Python 3.11
und 3.12 sind CI-Vertrag. Auf der lokalen Plattform sind `fcntl.flock`, `os.replace`,
`os.fsync` und `os.O_DIRECTORY` vorhanden; Repository-Root und `.steward/` liegen auf
demselben Device. Das belegt die grundsätzliche POSIX-Fähigkeit, ersetzt aber keine
Failure-Fixtures für beide CI-Versionen.

---

## 4. Verbindliche Präzisierungen für D2

Diese Punkte werden durch den Recon entschieden oder als ausdrückliche D2-Gates erhalten.
Sie sind **keine** D1-Implementierungserlaubnis.

### 4.1 Index-Fence

Die Formulierung in Feature 01 §9.1, ein „Indexeintrag“ blockiere, kann nicht wörtlich
„getrackter Pfad vorhanden“ bedeuten: `CLAUDE.md` ist bereits getrackt und nach Bootstrap
sollen alle vier Artefakte getrackt sein. Verbindliche operative Lesart ist:

> Blockierend ist eine Indexabweichung des Zielpfads gegenüber `HEAD`, einschließlich
> staged Add/Modify/Delete, unmerged stages oder unerwartetem Indexformat. Ein identischer
> Stage-0-Eintrag eines regulär getrackten Zielpfads ist kein Fehler.

D2 muss das mit Git-Plumbing und Tests beweisen; ein bloßes `git status`-Stringparsing
reicht nicht.

### 4.2 P1 ist nicht `mixed`

Der heutige exakte P1-Zustand — getracktes unverändertes Legacy-`CLAUDE.md`, drei fehlende
neue Ziele und kein Publication Record — ist ein **reviewter Bootstrap-Ausgangszustand**.
Er ist weder eine valide Generation noch ein Crash-Mischzustand.

Sobald ohne Record eines der folgenden Signale vorliegt, darf der Zustand nicht pauschal
als `absent` gelten:

- generierter Root-Marker in einem Ziel;
- Snapshot-Artefakt;
- Publisher-eigenes Temp-/Generation-Signal;
- von der gepinnten Git-Basis abweichende Rootbytes;
- unerwartete zusätzliche oder fehlende Zielkombination.

Die D2-Kaltstartklassifikation muss daher mindestens `legacy_bootstrap`, `valid`, `mixed`,
`invalid`, `unattested` und `manual_review` unterscheiden. Die grobe Feature-Spec-Klasse
`absent` darf diese Sicherheitsunterschiede nicht verschlucken.

### 4.3 Recovery-Provenance

Ein intern konsistenter Root-/Snapshot-Inhalt beweist nicht, dass er vom Publisher stammt.
Automatische Crash-Recovery benötigt zusätzlich ein enges, publisher-eigenes
Transaktionssignal. D2 muss vor Code exakt entscheiden und testen:

- gemeinsamer zufälliger Transaktions-Identifier für vier Same-Directory-Tempfiles;
- targetgebundene Tempnamen in einem einzigen geschlossenen Namensschema;
- vollständige Candidate-/Hashbindung über den Record-Temp, der wegen Record-last bis zum
  letzten Replace bestehen bleibt;
- kein Löschen verbleibender Recovery-Evidence nach dem ersten erfolgreichen Replace;
- Bereinigung nur nach Erwerb des exklusiven Locks, also wenn kein anderer Publisher
  aktiv sein kann;
- historische `.atomic_*`-Dateien und unbekannte ähnliche Namen bleiben untrusted und
  werden weder promoted noch gelöscht.

Ein zusätzliches Journal ist nur zulässig, wenn der D2-Pre-Flight sein Schema, seine
Durability, Bereinigung und Nicht-Delivery vollständig festlegt. Es darf nicht spontan im
Implementierungspatch entstehen.

### 4.4 Bootstrap-Recovery

Vor Slice E existiert kein vollständiger attestierter Vier-Artefakt-Git-Stand. D2 darf
deshalb keine automatische Rückkehr zu einer nicht vorhandenen Baseline behaupten.

Für den späteren ersten Bootstrap gilt fail-closed: Eine unterbrochene Generation darf
nur mit exakt erneut vorgelegten und validierten Bootstrap-Kandidaten fortgesetzt werden,
oder sie bleibt `manual_review`/`blocked`. Ein neu assembliertes, in Zeit oder Quellen
abweichendes Kandidatenset ist kein Ersatzbeweis.

### 4.5 Git- und Worktree-Fence

D2 muss vor Assembly beziehungsweise Mutation getrennt pinnen:

- realen Repository-Root;
- `HEAD^{commit}`;
- HEAD-Blob oder bestätigte Abwesenheit jedes Zielpfads;
- Stage-0-Indexzustand jedes Zielpfads;
- aktuelle Worktree-Bytes beziehungsweise bestätigte Abwesenheit;
- erkannte valide lokale Generation oder exakte P1-Baseline.

Unmittelbar vor dem ersten Replace werden Head, Index, Parent-Inodes und Worktree-
Targetbytes erneut geprüft. Ein legitimer noch nicht gelieferter lokaler Publish darf nur
über den vollständigen D1-Generationsbeweis erkannt werden; allgemeine Dirty-State-
Akzeptanz ist verboten.

### 4.6 Noch offener D2-Detailvertrag

Vor D2-Start müssen im eigenen Pre-Flight außerdem feststehen:

- exakter Modul-/API-Schnitt und Rückgabetypen;
- Prozesslockpfad, Open-Flags, Dateimodus, Timeout und monotone Deadline;
- per-Prozess-Lock-Keying über den realen Repositorypfad;
- vollständiger Write-Loop einschließlich `EINTR` und Short Write;
- Temp- und endgültige Dateimodi;
- Parent-Directory-fsync-Verhalten auf Darwin und Linux;
- Fehlerklassifikation für `ENOSPC`, readonly, `fsync`, `replace` und Read-back;
- Verhalten nach jedem der vier einzelnen Replaces;
- Trennung von `disabled | preview | canonical` Policy-Mode und
  `canonical | degraded | safe_fallback` Content-Mode;
- lokale Canonical-Freigabe ohne authentifizierten Runtime-Key weiterhin fail-closed;
- keine `.gitignore`-Ausnahme vor dem reviewten Slice-E-Bootstrap.

---

## 5. Exakter D1-Patchscope

### 5.1 Produktcode

Nach Merge dieses Dokuments sind ausschließlich erlaubt:

```text
steward/context_contract.py
steward/context_rendering.py
```

`context_contract.py` darf die bestehende private Previous-Record-Prüfung zu genau einem
öffentlichen strikten Validator `validate_previous_published_record()` refaktorieren. Er
gibt bei Erfolg `None` zurück und wirft bei Fehler `ContractViolation`.
`decide_publish()` muss dieselbe Wahrheit weiterverwenden; Record-Schema,
Decision-Ergebnisse und Goldenwerte dürfen sich nicht ändern.

`context_rendering.py` darf genau eine reine Persisted-Generation-Fähigkeit ergänzen:

```text
validate_persisted_generation(PublicationCandidates)
    -> PreviousPublishedRecord
```

Der Rückgabevertrag wird im roten Test festgeschrieben. Er exportiert keine mutable
Payload-/Snapshot-Kopie als zweite Wahrheit. Der Validator erhält alle vier Bytes
gemeinsam; es gibt keinen öffentlichen „Record allein ist gültig“-Shortcut.

### 5.2 Tests

Zulässig sind ausschließlich:

```text
tests/test_context_contract.py
tests/test_context_rendering.py
```

Als read-only Golden-Fixtures bleiben erlaubt:

```text
specs/context_bridge_evidence/FEATURE_04_HASH_VECTORS.json
specs/context_bridge_evidence/FEATURE_01_PUBLICATION_VECTORS.json
```

Jeder weitere Pfad stoppt D1 und benötigt einen neuen Reviewentscheid.

---

## 6. D1-Validierungsvertrag

### 6.1 JSON-Bytes

Die Eingaben besitzen vor Decode und JSON-Parsing folgende inklusive Obergrenzen:

```text
CLAUDE.md:                         65536 Bytes
AGENTS.md:                         65536 Bytes
.steward/context-snapshot.json:   131072 Bytes
.steward/context-publication.json: 16384 Bytes
```

Der Parser:

- verwirft BOM, invalides UTF-8, leere oder überlange Inputs;
- verwirft duplicate object keys auf jeder Ebene;
- verwirft `NaN`, `Infinity`, floats und nicht geschlossene JSON-Typen;
- verlangt exakt die bekannten Envelope-Keys und Schema-IDs;
- verlangt, dass erneute `canonical_json_bytes()` exakt den Eingabebytes entspricht;
- spiegelt keine abgelehnten Rohbytes in Exceptions oder Logs.

Die geschlossene Fachvalidierung bleibt im bestehenden Contract-Modul. D1 erstellt kein
zweites Schemaframework und keine generische JSON-Deserialisierungsbibliothek.

### 6.2 Snapshot-Envelope

Der Validator beweist:

- exaktes `steward.context.snapshot-artifact/v1`-Envelope;
- inneres Snapshot über `validate_snapshot_model()`;
- reproduzierten `snapshot_hash`;
- `snapshot_id == "ctxsnap-v1:" + snapshot_hash`;
- exakte kanonische Envelopebytes.

### 6.3 Publication-Envelope und Previous Record

Der Validator beweist:

- exaktes `steward.context.publication-artifact/v1`-Envelope;
- exakte konstante Targetmap;
- `snapshot_artifact_hash` über die bestehende versionierte Domain;
- Repository-Head, Generator-Commit und Constitution-Provenance gegen das Snapshot;
- geschlossen geladenes `OutputMode`-Enum;
- vollständigen `PreviousPublishedRecord` über den einen öffentlichen Contract-Validator;
- Snapshot-ID, C0-Hash und Comparison-State gegen Snapshot;
- keine Autorität des Record über abweichende Root- oder Snapshotbytes.

### 6.4 Root-Vertrag

Beide Root-Bytes werden unabhängig streng zerlegt. Akzeptiert wird ausschließlich die
bereits normative feste Rendererprojektion:

1. genau ein vollständiger C0-Block;
2. genau ein vollständiger Dynamic-v1-Block mit festen Labels und Reihenfolge;
3. exakt kanonisches `source_status`-Array und `observations`-Objekt in den vorgesehenen
   JSON-Fences;
4. genau ein vollständiger Orientation-v1-Block;
5. keine Präfix-, Suffix-, Zusatzheading-, Marker- oder Whitespacebytes;
6. genau ein finaler LF;
7. byte-identische `CLAUDE.md`- und `AGENTS.md`-Outputs.

Aus den streng extrahierten Contract-/Dynamic-Werten wird der Payload-Core rekonstruiert
und mit `validate_payload_core()` geprüft. Danach erzeugt
`build_publication_candidates()` aus rekonstruiertem Payload und validiertem Snapshot die
Sollgeneration. Alle vier Eingaben müssen mit diesem Rebuild byte-identisch sein. Damit
bleibt der Renderer die einzige Projektion und der Parser kann keine lockerere zweite
Sprache akzeptieren.

### 6.5 Fehlervertrag

Alle fachlichen Ablehnungen sind `ContractViolation` mit geschlossenem Fehlercode und
Feldpfad. Unerwartete JSON-, Unicode-, Enum- oder Mappingfehler werden an der öffentlichen
Grenze fail-closed in diesen Vertrag übersetzt. Kein Fehler darf teilweise validierte
Recorddaten zurückgeben.

---

## 7. Verpflichtende rote und adversariale Tests

Vor Produktcode werden direkte rote Tests gegen die neue öffentliche API committed. Sie
dürfen nicht über Pipeline-, Hook- oder Exception-swallowing-Pfade laufen.

Mindestens erforderlich:

1. Golden-Viererset liefert den exakt erwarteten `PreviousPublishedRecord`.
2. Publication Record allein besitzt keine Validierungs-API.
3. Jede einzelne der vier Bytefolgen wird separat manipuliert und blockiert.
4. Root-Consumer unterscheiden sich um ein Byte und blockieren.
5. falsche Markerreihenfolge, doppelter Marker, Zusatztext und fehlender finaler LF
   blockieren.
6. manipulierte Dynamic-Provenance, Source-Status oder Observations blockieren.
7. falscher Snapshot-Hash/-ID und falscher Snapshot-Artifact-Hash blockieren.
8. falscher Payload-/Output-/C0-/Orientation-Hash blockiert.
9. unbekannte Envelope- oder Previous-Keys blockieren.
10. duplicate JSON keys, nichtkanonischer Whitespace, BOM, invalides UTF-8, `NaN`, Float
    und überlanges Input blockieren.
11. falsche Targetmap oder Consumer-Keymenge blockiert.
12. mutierter `comparison_state` zwischen Snapshot und Record blockiert.
13. der öffentliche Previous-Record-Validator und `decide_publish()` teilen nachweislich
    dieselbe Record-Wahrheit.
14. ein Purity-Test prüft direkt, dass der D1-Produktpfad weder Filesystem, Git,
    Subprocess, Environment, Clock, Netzwerk noch Registry importiert oder aufruft.

Tests dürfen keine private Implementierungsfunktion als Ersatz für die öffentliche
Sicherheitsgrenze prüfen. Ein Test, der auch bei ausgelassener Root-Zerlegung oder
fehlendem Envelope-Parser grün bliebe, ist Placebo und blockiert Review.

---

## 8. Ausdrücklich verbotener Scope

D1 darf nicht verändern oder erzeugen:

```text
CLAUDE.md
AGENTS.md
.steward/**
.gitignore
.github/**
docs/**
specs/CONTEXT_BRIDGE_FEATURE_01.md
steward/context_bridge.py
steward/briefing.py
steward/briefing_stages.py
steward/hooks/**
steward/git_nadi_sync.py
steward/tools/**
```

Ebenfalls verboten:

- neuer Publisher oder Writer;
- `Path`, `open`, `os`, `fcntl`, `tempfile`, `subprocess`, `time`, `socket` oder
  `ServiceRegistry` im D1-Produktpfad;
- Lock, Tempfile, Rename, Replace, fsync, chmod oder Cleanup;
- Git-Status, Git-Baseline oder Worktree-Klassifikation;
- Policy-/Runtime-Key-Lesen;
- Bootstrap-, Recovery-, Safe-Fallback-, Delivery- oder Callerlogik;
- neuer Root- oder Publication-Record im Repository;
- Änderung von Source, Attestation, Goldenbytes oder Hash-Domains;
- LLM- oder Providerzugriff;
- Exportänderung in `steward/__init__.py`;
- allgemeines Parser-/Serializer-Framework.

---

## 9. Deployment-, Revert- und Produktionsvertrag

D1 besitzt keine Deploymentwirkung:

- kein Produktivcaller;
- keine Dateisystem- oder Git-Seiteneffekte;
- Policy bleibt mangels Repository-Policy und Runtime-Autorisierung effektiv disabled;
- Heartbeat darf weiterhin nur den bekannten Legacy-Raw-State schreiben;
- Root- und Publication-Blobs bleiben unverändert beziehungsweise absent.

Revert ist ein normaler PR-Revert des D1-Produktcommits. Da D1 nichts persistiert, gibt es
keine Datenmigration und keine Recoveryaktion. Nach Merge muss ein erfolgreicher
Folgeheartbeat per GitHub API beweisen, dass `CLAUDE.md` unverändert, `AGENTS.md` absent
und beide JSON-Artefakte absent blieben.

---

## 10. D1-Abbruch- und Re-Review-Kriterien

G2 stoppt vor oder während D1 bei:

- neuem fachlichem Main-Drift in den vier Patchpfaden;
- überlappendem offenen PR;
- notwendigem fünften Produkt-/Testpfad;
- Änderung bestehender Goldenbytes, Hash-Domains oder Rendererbytes;
- Bedarf an Filesystem-, Git- oder Policyzugriff;
- permissivem Rootparser, Record-only-Vertrauen oder Schema-Duplikation;
- nicht direkt roten Tests;
- verdeckter Writer-, Caller-, Bootstrap- oder Recoverylogik;
- mehr als dem einen beschriebenen Previous-Record-Validator und der einen
  Persisted-Generation-Fähigkeit.

Jeder dieser Fälle benötigt neuen read-only Recon und eine dokumentierte
Reviewentscheidung.

---

## 11. Checkliste

- [x] Aktueller Remote-Head und Tree gepinnt.
- [x] Offene PRs und fachlicher Main-Drift geprüft.
- [x] Bestehende Writer, Caller, Git-, Lock- und Atomic-Write-Helfer inventarisiert.
- [x] Aktueller P1-Zielzustand und `.gitignore`-Realität verifiziert.
- [x] Fehlender strikter Persisted-Generation-Loader positiv bewiesen.
- [x] Wörtlich unmögliche Index-Fence-Lesart präzisiert.
- [x] P1-Bootstrap von Mixed-Recovery getrennt.
- [x] Full-Slice-D-Mega-Patch verworfen und D1/D2 getrennt.
- [x] D1-Pfade, öffentliche Grenze, rote Tests und verbotener Scope festgelegt.
- [x] D2 bleibt ohne eigenen aktuellen G2 vollständig gesperrt.

---

## 12. Schlussstatus

Der read-only Slice-D-Recon ist für den heutigen Head abgeschlossen. Nach regulärem Merge
dieses Dokuments darf ausschließlich D1 als kleiner reiner Contract-Patch beginnen.

**Nicht freigegeben** sind lokaler Publisher, Writer, Lock, Pfadmutation, Persistenz,
Record-last, Recovery, Bootstrap, `.gitignore`, Caller, Workflow, Settings, Delivery und
Aktivierung. Der nächste Schritt nach einem verifizierten D1-Merge ist ein neuer aktueller
read-only D2-G2-Pre-Flight, kein direktes Publisher-Coding.
