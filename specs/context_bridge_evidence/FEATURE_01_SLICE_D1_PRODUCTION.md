# FEATURE 01 / SCHNITT D1 — IMPLEMENTIERUNGS- UND PRODUKTIONSBEWEIS

> **Status:** D1 ABGESCHLOSSEN — PERSISTED-GENERATION-READ-BACK VERIFIZIERT
> **Datum:** 2026-07-17
> **G2-Preflight:** `specs/context_bridge_evidence/FEATURE_01_SLICE_D_G2_PREFLIGHT.md`
> **Preflight-PR / Merge:** `#627` / `4d1459c0dbfadf1da95a2582e765f4e367ac2455`
> **Implementierungs-PR / Merge:** `#633` / `5995d7f4dd0688ec1da0f7afded491d9011620be`
> **Verifizierter Folge-Head:** `511f5a8760258ba23b503860ebc865aa97b4b335`

## 1. Gelieferter Scope

Produktcode:

```text
steward/context_contract.py
steward/context_rendering.py
```

Tests:

```text
tests/test_context_contract.py
tests/test_context_rendering.py
```

PR `#633` änderte exakt diese vier durch G2 erlaubten Pfade. Es gab keine Änderung an
Root-Dateien, `.steward/**`, `.gitignore`, Workflow, Caller, Hook, Git-NADI, Policy,
Runtime-State oder Repository-Settings.

## 2. Review- und Commit-Kette

Der D1-G2-Preflight wurde nach einem ersten adversarialen Review korrigiert. Der Review
fand vor Code einen echten Vertragskonflikt: `PreviousPublishedRecord.comparison_state`
war normativ nullable, während die alte private `_valid_previous()`-Logik `None` ablehnte.
Der finale Preflight-Head `f56ad28325c4e4e272e4f9b23151682ed417a74e` wurde danach ohne
blockierende Findings freigegeben und als PR `#627` gemergt.

Die Implementierung bestand aus zwei getrennten Commits:

```text
24bdb0c2f31166d8fe2a8e37f51ab61767c60a2f test: define persisted generation readback
0214e3c871c33cb839293a2d6727382b0c479fac feat: validate persisted context generations
```

Die Tests wurden vor Produktcode committed und scheiterten gegen Main direkt an den zwei
fehlenden öffentlichen APIs. Das finale Code-Review band exakt Head
`0214e3c871c33cb839293a2d6727382b0c479fac` und fand keine blockierenden Findings.

## 3. Gelieferter Vertrag

### 3.1 Materialisierter Previous Record

`validate_previous_published_record()` ist die einzige strukturelle Schemawahrheit für
einen bereits typisiert materialisierten `PreviousPublishedRecord`:

- exakte Record-/Payload-Schemas;
- echter geschlossener `OutputMode`, kein Runtime-String und kein Preview;
- vollständige Hash-, Snapshot-ID- und Consumer-Key-Verträge;
- bytegleiche Consumer-Output-Hashes;
- exakt vier nullable Comparison-Counter über dieselbe bestehende
  `_validate_comparison_state()`-Wahrheit wie das Snapshot-Modell.

`decide_publish()` verwendet denselben Validator. Die frühere falsche Ablehnung valider
Nullable-Records ist korrigiert; malformed Record- oder Mode-Typen bleiben `blocked`.
Der Value-Object-Validator attestiert ausdrücklich keine Artifact-Bytes und keine
persistierte Generation.

### 3.2 Vollständiger Vier-Artefakt-Read-back

`validate_persisted_generation()` akzeptiert nur ein exaktes `PublicationCandidates`-
Viererset. Es beweist:

- geschlossene Größenlimits vor Decode;
- UTF-8 ohne BOM;
- JSON ohne Duplicate Keys, Floats, Non-Finite-Werte oder nichtkanonische Bytes;
- exakte Snapshot-/Publication-Envelopes ohne unbekannte Felder;
- Snapshot-ID/-Hash und domain-separierten Snapshot-Artifact-Hash;
- exakte Targetmap, Repository-/Generator-/Constitution-Provenance;
- C0-, Orientation-, Payload-, Output- und Comparison-State-Bindungen;
- vollständige feste Root-Marker-, Label-, JSON-Fence- und Whitespace-Struktur;
- Bytegleichheit beider Consumer auch bei separat gelesenen, verschiedenen Python-
  `bytes`-Objekten;
- abschließenden byte-identischen Rebuild aller vier Artefakte über den einzigen Renderer.

Publication-Artefaktbytes allein können keinen publisher-vertrauenswürdigen Previous
Record liefern. Erst der vollständige Viererset-Beweis gibt den typisierten Record zurück.

## 4. Test- und Security-Beweis

Gezielte Validierung:

```text
124 passed
```

Ein zusätzlicher unabhängiger Scan manipulierte 338 über alle vier Golden-Artefakte
verteilte Einzelbytes. Jede Mutation wurde fail-closed abgelehnt.

Der erste vollständige lokale Lauf stoppte nach `274 passed, 1 skipped` an einem
Cetana/Dharma-Teardown-Timeout in
`TestAutonomousFlowE2E.test_run_autonomous_dispatches_federated_task`. Der Stack berührte
keinen geänderten Pfad. Exakt dieser Test lief isoliert anschließend grün:

```text
1 passed
```

Der vollständige Restlauf ohne diesen bereits isoliert bestandenen Test ergab:

```text
2287 passed, 1 skipped, 1 deselected
```

Repositoryweite Checks:

- `ruff check steward/ tests/`: grün;
- `ruff format --check steward/ tests/`: 215 Dateien formatiert;
- `bandit -r steward/ -c pyproject.toml -q`: grün;
- `git diff --check`: grün;
- CI Python 3.11, Python 3.12, Lint und Security: grün.

Zwei während der Vollsuite erzeugte lokale Federation-Health-Diffs wurden vor Push exakt
auf den sauberen Branchzustand zurückgeführt und waren nie Teil des PRs.

## 5. Produktionsbeweis und Nichtaktivierung

Merge-CI-Run `29558191253` lief als `push` auf dem exakten Merge-Head
`5995d7f4dd0688ec1da0f7afded491d9011620be` und endete erfolgreich.

Der bereits seriell eingeplante Folgeheartbeat `29558194430` war an denselben Head
gebunden. Alle Schritte einschließlich autonomem Zyklus und Federation-State-Commit
endeten erfolgreich. Es wurde kein zusätzlicher Run gestartet.

Nach dem Merge erschienen zwei Heartbeat-State-Commits:

```text
ab1f4937d99e1c3f437efa5a2d7a2df44498f50d chore: heartbeat #5683 state sync
511f5a8760258ba23b503860ebc865aa97b4b335 chore: heartbeat #5684 state sync
```

Ihr gemeinsamer Diff gegen den D1-Merge enthält ausschließlich zehn bekannte
`.steward/`- und `data/federation/`-Runtime-State-Pfade. Kein Produkt-, Test-, Root-,
Spec- oder Workflowpfad änderte sich.

Blob-Beweis am Merge und Folge-Head:

```text
.steward/conventions.md:              f428d5856a5c525e002c301890777748effbeb4e
CLAUDE.md:                             8146a15603c95e5aa1404c9eb7021e3008914b0c
steward/context_contract.py:           b5c7410ec9adc8ab8c35485a9238dc1d214e0bc5
steward/context_rendering.py:          3dd923237d6871163e9b45b827a8e0d4b7d963bb
AGENTS.md:                             absent
.steward/context-snapshot.json:        absent
.steward/context-publication.json:     absent
```

GitHub/Git beweisen damit die Remote-Tree-Abwesenheit der drei neuen Artefakte und die
unveränderten Blobs. Sie können keine Aussage über kurzlebige ignorierte Dateien im
ephemeren Runner-Dateisystem machen. Der positive Code-/Call-Site- und Purity-Beweis
schließt diese Lücke für D1: Das Modul importiert weder Filesystem, Git, Clock, Netzwerk,
Environment noch Registry; kein Produktivcaller ruft den Read-back auf.

## 6. Sicherheitsgrenze

D1 ist reine Validierungsfläche und nicht produktiv aktiviert. Weiterhin fehlen bewusst:

- lokaler Publisher und jeder Root-Write;
- Thread-/Prozesslock;
- Pfad-, Git- und Worktree-Fence;
- Temp-/Replace-/fsync-Transaktion;
- Record-last und Crash-/Mixed-Generation-Recovery;
- Policy-/Runtime-Key-Auflösung;
- Bootstrap, Caller-Migration, Delivery und Aktivierung.

Die grüne D1-Implementierung ist keine Erlaubnis, diese Grenzen im selben Patch zu
überspringen.

## 7. Nächster Gate

Der nächste zulässige Schritt ist ausschließlich ein neuer read-only G2-Preflight für
**D2 — POSIX-Publisher und Recovery** auf aktuellem `origin/main`.

Vor jedem D2-Code müssen insbesondere Git-/Index-/Worktree-Fence, P1-Bootstrapklasse,
Lockpfad und `flock`, Temp-Generationsschema, Dateimodi, Short-Write-/EINTR-Vertrag,
File-/Parent-fsync, Record-last, Fehlerklassen und Bootstrap-Recovery exakt festgelegt und
adversarial reviewt werden.

Bis dahin bleiben Publisher, Writer, Root-, Record- und Recovery-Mutation, `.gitignore`,
Workflow, Settings, Delivery und Aktivierung vollständig gesperrt.
