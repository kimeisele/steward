# FEATURE 01 / SCHNITT D2 — G2-PRE-FLIGHT

> **Status:** G2 START APPROVED — ausschließlich D2a: attestierter read-only Repository-State-Readback nach Merge dieses Dokuments
> **Datum:** 2026-07-17
> **Produktionsbasis:** `kimeisele/steward@7e476fe26945c69b5f207da9567a1aacca0e3161`
> **Produktions-Tree:** `0bef6edaed8883c8af46476d12842a96f10011e3`
> **Feature-Spec:** `specs/CONTEXT_BRIDGE_FEATURE_01.md` — G1 APPROVED
> **Voraussetzung:** D1-Merge `5995d7f4dd0688ec1da0f7afded491d9011620be`, Produktionsbeweis `specs/context_bridge_evidence/FEATURE_01_SLICE_D1_PRODUCTION.md`
> **Scope:** read-only G2-Evidence und enger Startentscheid; noch keine Produktcodeänderung

---

## 1. Entscheidung

D1 beweist vier beliebige persistierte Artefaktbytes erneut und gibt erst danach einen
strukturell validierten `PreviousPublishedRecord` zurück. Der heutige D2-Recon findet
danach noch zwei voneinander unabhängige Sicherheitsgrenzen:

1. **Repository-State und externe Attestation:** Git-Basis, Index, Worktree, Pfadtypen und
   vier Artefakte müssen read-only beobachtet, klassifiziert und gegen die außerhalb der
   Generation vorgelegte Constitution-Attestation gebunden werden.
2. **Mutation und Crash-Recovery:** Thread-/Prozesslock, Tempfiles, Journal, `fsync`,
   `replace`, Record-last, Read-back und Reparatur verändern den Worktree und bilden eine
   eigene deutlich größere Failure-Domain.

Ein einzelner D2-Patch würde Git-Plumbing, untrusted Filesystem-Reads, Attestation,
Klassifikation, Locking und Crashzustände gleichzeitig einführen. Das wäre genau der in
Schnitt D bereits verworfene Mega-Patch in neuer Form. D2 wird deshalb ohne Änderung des
End-to-End-Ziels weiter chirurgisch geteilt:

- **D2a — attestierter read-only Repository-State-Readback:** externe Attestation an den
  D1-Generationsbeweis binden; exakte Git-/Index-/Worktree- und Pfadzustände ohne jede
  Mutation beobachten; den Kaltstart deterministisch klassifizieren.
- **D2b — POSIX-Publisher und Recovery:** auf D2a aufbauend Lock, durable Prepare,
  Transaction Journal, per-file Replace, Record-last, Read-back und Recovery
  implementieren.

Nach regulärem Merge und erneuter Live-Prüfung autorisiert dieses Dokument **nur D2a**.
D2b, Bootstrap, Publisher-Caller, Root-Writes, `.gitignore`, Workflow, Delivery,
Repository-Settings und Aktivierung bleiben gesperrt. D2b benötigt auf dem dann aktuellen
Code einen eigenen read-only G2-Pre-Flight.

---

## 2. Gepinnte Live-Evidence

### 2.1 Main, Tree und Parallelität

Nach `git fetch origin --prune` und Fast-forward galt:

- `origin/main` und der saubere Recon-Worktree standen auf
  `7e476fe26945c69b5f207da9567a1aacca0e3161`;
- der zugehörige Tree war `0bef6edaed8883c8af46476d12842a96f10011e3`;
- es gab keinen offenen Pull Request;
- der letzte Drift war Heartbeat `#5686` und änderte ausschließlich neun bekannte
  `.steward/`- und Federation-Runtime-State-Pfade;
- D1-Code, D1-Tests, Feature-Spec, `CLAUDE.md` und `.gitignore` waren davon nicht
  betroffen.

Vor D2a-Code werden Head, offene PRs und alle erlaubten Pfade erneut geprüft. Ein
fachlicher Main-Drift, ein überlappender PR oder ein geänderter Basisblob stoppt G2.

### 2.2 Exakter P1-Zustand

Git-Plumbing und `lstat()` belegten:

| Ziel | HEAD / Index | Worktree |
|---|---|---|
| `CLAUDE.md` | Stage 0, Modus `100644`, Blob `8146a15603c95e5aa1404c9eb7021e3008914b0c` | regulär, Modus `0644`, 4.046 Bytes, ein Link |
| `AGENTS.md` | absent | absent |
| `.steward/context-snapshot.json` | absent | absent |
| `.steward/context-publication.json` | absent | absent |

Repository-Root und `.steward/` sind reale Verzeichnisse, keine Symlinks und liegen auf
demselben Device. Es gibt kein Publisher-eigenes Lock-, Journal- oder Temp-Artefakt. Die
beiden historischen getrackten `.steward/.atomic_*.tmp` gehören nicht zum Context-
Publisher und dürfen weder klassifiziert, validiert noch gelöscht werden.

Dieser Zustand ist **`legacy_bootstrap`**. Er ist weder eine valide Vier-Artefakt-
Generation noch ein Crash-Mischzustand. Die Blob-ID dient als gepinnter Recon-Beweis,
nicht als hardcodierter Produktwert.

### 2.3 D1 ist rein, aber nicht extern attestiert

`validate_persisted_generation()` prüft bereits:

- strikte UTF-8-, Größen-, JSON-, Marker- und Schemagrenzen;
- Snapshot-, Payload-, Root- und Publication-Record-Hashes;
- Gleichheit der separat gelesenen Rootbytes;
- Repository-, Generator-, Constitution- und Comparison-Cross-Bindings;
- vollständigen deterministischen Renderer-Rebuild.

Die Funktion erhält jedoch keine `ConstitutionAttestation`. Sie beweist deshalb nur,
dass `source_blob`, `reviewed_at_commit` und C0-Hash **innerhalb** der vier Artefakte
konsistent behauptet werden. Eine selbstkonsistente Generation kann weiterhin eine
erfundene Source-Provenance tragen.

Der D2-Publisher darf diesen Unterschied nicht durch Vertrauen in den Publication Record
oder durch einen zweiten Parser überbrücken. Vor jeder Verwendung als vorherige
Generation oder Git-Baseline ist ein zusätzlicher reiner, extern attestierter
Generationsbeweis erforderlich.

### 2.4 Vorhandene I/O-Helfer bleiben ungeeignet

- `steward/context_bridge.py::_atomic_write()` besitzt keinen vollständigen Write-Loop,
  kein File-/Parent-`fsync`, keinen Lock, keinen Pfadschutz und keine Gruppenerkennung.
- Protocol `atomic_write_text()` besitzt File-`fsync`, aber keinen vollständigen
  Short-Write-Vertrag, Parent-`fsync`, Lock oder Pfadschutz.
- Protocol `FileLock` ist ein Existenz-/Timeout-Lock, löscht vermeintlich stale Locks und
  kann einen lebenden Writer verdrängen; es verwendet keinen Kernel-`flock`.
- Git-NADI, GitTool, Actuators und Senses besitzen andere Mutations- und Trust-Verträge;
  keiner liefert den benötigten read-only Target-Fence.

Keiner dieser Helfer wird für D2a oder später D2b umgedeutet. Insbesondere wird der
Protocol-`FileLock` nicht wiederverwendet.

### 2.5 POSIX- und Git-Plumbing-Evidence

Die lokale Engineering-Plattform war macOS 13.7.5 mit Python 3.11.13. Produktion und CI
verwenden `ubuntu-latest`; Python 3.11 und 3.12 sind Projektvertrag. Der lokale
kontrollierte Recon belegte:

- `os.O_CLOEXEC`, `os.O_DIRECTORY` und `os.O_NOFOLLOW` sind vorhanden;
- `fsync()` auf geöffnetem Repository-Root und `.steward/` war erfolgreich;
- ein zweiter separater File Descriptor desselben Prozesses konnte einen gehaltenen
  nonblocking exklusiven `flock` nicht erwerben;
- dirfd-relatives `os.replace()` plus Parent-`fsync()` funktionierte in einem temporären
  Verzeichnis.

Das beweist die Grundfähigkeit, nicht alle Crash-/Power-Loss-Garantien. D2b benötigt
später Linux-CI-Fixtures und injizierte Fehler nach jedem Durability-Schritt.

Die folgenden read-only Git-Kommandos lieferten den benötigten exakten Zustand ohne
Porcelain-Stringheuristik:

```text
git rev-parse --path-format=absolute --show-toplevel
git rev-parse --verify HEAD^{commit}
git ls-tree -z --full-tree HEAD -- <vier exakte Zielpfade>
git ls-files --stage -z -- <vier exakte Zielpfade>
git cat-file blob <gepinnte Blob-ID>
```

`git rev-parse --local-env-vars` nennt unter anderem `GIT_DIR`, `GIT_WORK_TREE`,
`GIT_INDEX_FILE`, Object-/Replace-/Common-Dir-Variablen und Config-Parameter. Ein
Publisher darf diese vom Aufrufer geerbten Overrides nicht als Repository-Wahrheit
akzeptieren.

---

## 3. D2a — exakter freigegebener Vertrag

### 3.1 Attestierter D1-Generationsbeweis

Erlaubt ist genau eine neue öffentliche reine Funktion:

```python
validate_attested_persisted_generation(
    candidates: PublicationCandidates,
    attestation: ConstitutionAttestation,
) -> PreviousPublishedRecord
```

Der Vertrag lautet:

1. `candidates` und `attestation` müssen exakte erwartete Runtime-Typen besitzen.
2. Die Attestation muss Schema `steward.context.constitution-attestation/v1`, Status
   `verified` und gültige Hash-/Commitfelder besitzen.
3. Die Funktion verwendet denselben privaten D1-Parse-/Rebuild-Durchlauf; sie darf die
   vier Artefakte nicht ein zweites Mal mit einer permissiveren Sprache parsen.
4. Zusätzlich müssen exakt übereinstimmen:
   - `attestation.c0_sha256` mit validiertem Snapshot, Root und Previous Record;
   - `attestation.source_blob` mit validiertem Snapshot und Publication Envelope;
   - `attestation.reviewed_at_commit` mit validiertem Snapshot und Publication Envelope.
5. Bei Erfolg wird nur der bereits vollständig validierte `PreviousPublishedRecord`
   zurückgegeben. Snapshot-, Publication- oder Root-Inhalte werden nicht als neue
   öffentliche mutable Datenstruktur exponiert.
6. Bei jeder Abweichung entsteht `ContractViolation`, ohne untrusted Rohbytes oder
   lokale Pfade in der Fehlermeldung.

`validate_persisted_generation()` bleibt als interner-Konsistenzbeweis kompatibel. Es
wird nicht nachträglich als Attestation bezeichnet. Ein Publication-Artefakt allein und
ein `PreviousPublishedRecord` allein bleiben unzureichend.

Falls die bestehende private `_validate_attestation()` refaktoriert wird, ist höchstens
ein öffentlicher reiner `validate_constitution_attestation()`-Wrapper mit demselben
strikten Vertrag zulässig. Es darf keine zweite Attestation-Sprache entstehen.

### 3.2 Neues read-only Modul

D2a darf `steward/context_publisher.py` neu anlegen. Trotz des späteren Modulzwecks darf
dieser Schnitt ausschließlich Beobachtung und Klassifikation enthalten. Er besitzt:

- keine Schreibfunktion;
- keinen `open()`-Modus mit Schreibflag;
- kein `fcntl`, `flock`, Tempfile, `replace`, `unlink`, `chmod` oder `fsync`;
- keinen Git-Befehl, der Index, Worktree, Ref, Branch, Commit oder Remote verändert;
- keinen Candidate-Assembler, Caller oder Heartbeat-Hook;
- keinen Import von Git-NADI, GitTool, Actuators, Senses, Agent oder ServiceRegistry.

Die einzige öffentliche Repository-Grenze lautet sinngemäß:

```python
inspect_repository_generation(
    repository_root: Path,
    attestation: ConstitutionAttestation,
) -> RepositoryGenerationObservation
```

Der endgültige Bezeichner darf stilistisch angepasst werden, der semantische Vertrag
nicht. Es gibt keine frei vom Aufrufer wählbaren Zielpfade. Die vier V1-Ziele sind
geschlossen und exakt.

### 3.3 Git-Prozessgrenze

D2a verwendet nur die in §2.5 belegten Plumbing-Kommandos. Verbindlich sind:

- ausführbare Datei und Argumente werden als Liste ohne Shell ausgeführt;
- fester `cwd` ist der zuerst real aufgelöste erwartete Repository-Root;
- `LC_ALL=C`, `GIT_OPTIONAL_LOCKS=0` und `GIT_NO_REPLACE_OBJECTS=1` werden gesetzt;
- System- und Global-Config-Discovery werden über explizite Null-Config-Grenzen
  deaktiviert; für die Plumbing-Aufrufe ist keine benutzerdefinierte Git-Konfiguration
  erforderlich;
- alle durch `git rev-parse --local-env-vars` bekannten Repository-/Index-/Object-/Config-
  Overrides werden aus der Kindprozessumgebung entfernt; dynamische
  `GIT_CONFIG_KEY_<n>`-/`GIT_CONFIG_VALUE_<n>`-Paare werden zusammen mit ihrem Count
  entfernt;
- Exitcode, Größenlimit, Timeout und NUL-getrennte Ausgabe werden strikt geprüft;
- `show-toplevel` muss bytegenau zum erwarteten realen Root passen;
- HEAD muss exakt ein Commit sein;
- unerwartete Stages, doppelte Einträge, falsche Modi oder nicht angeforderte Pfade
  blockieren;
- Blobbytes werden mit `git cat-file blob <oid>` gelesen, nicht über Checkout, Filter,
  `git show <rev>:<path>` oder Worktree-Fallback;
- stderr oder Exceptiontexte werden nicht ungefiltert in Contract-Fehler übernommen.

Ein bloßes `git status`-Parsing, `Path.read_text()`, libgit-ähnliche Zusatzabhängigkeit
oder Import eines mutierenden Steward-Git-Wrappers ist verboten.

### 3.4 Pfad- und Bytegrenze

Vor jedem Worktree-Read wird per `lstat`/sicherem Descriptor geprüft:

- Repository-Root und `.steward/` sind reale Verzeichnisse und keine Symlinks;
- Zielparent ist exakt einer dieser beiden gepinnten Parents;
- ein existentes Ziel ist regulär, nicht Symlink, besitzt genau einen Hardlink und
  überschreitet sein D1-Größenlimit nicht;
- ein nach dem Open durch `fstat()` beobachteter Descriptor stimmt mit dem vorher
  geprüften Objekt überein;
- vollständige Byteanzahl und EOF werden geprüft; keine implizite Textdekodierung;
- Parent- und Target-Inodes werden nach dem Read erneut geprüft.

Nach allen Git- und Worktree-Reads werden HEAD und Index ein zweites Mal mit derselben
Plumbing-Grenze gelesen. Nur identische Anfangs- und End-Evidence darf klassifiziert
werden; beobachteter Drift ist `manual_review` und kein best-effort Snapshot.

Die Größenlimits haben genau eine Code-Wahrheit. D2a darf sie aus D1 kontrolliert
exportieren oder über einen einzigen D1-Loader verwenden, aber keine abweichenden
Zahlenwerte duplizieren.

Eigene Publishernamen werden nur erkannt, niemals gelöscht oder geöffnet:

```text
.steward/.context-publish-v1.lock
.steward/.context-publish-v1.<32 lowercase hex>.txn
.context-publish-v1.<32 lowercase hex>.claude.tmp
.context-publish-v1.<32 lowercase hex>.agents.tmp
.steward/.context-publish-v1.<32 lowercase hex>.snapshot.tmp
.steward/.context-publish-v1.<32 lowercase hex>.publication.tmp
```

Die feste Lockdatei ist keine Generations- oder Recovery-Provenance. Vor D2b ist auch ihre
Existenz unerwartet und führt fail-closed zu `manual_review`; D2b muss die D2a-
Klassifikation später ausdrücklich um den sicher geprüften persistenten Lock-Inode
erweitern. Ein exakt grammatisches Transaction Journal oder Tempfile ist ein
Generationssignal und ergibt mindestens `mixed`; mehrere, malformed oder unbekannte
Signale ergeben `manual_review`. Historische `.atomic_*`, ähnliche Fremdnamen und
unbekannte `.context-publish-*`-Namen werden nie als Publisher-Provenance akzeptiert.

### 3.5 Index-Fence

Ein normaler Stage-0-Eintrag, der HEAD-Modus und HEAD-Blob entspricht, ist erlaubt. Es
blockieren beziehungsweise führen zu `manual_review`:

- staged Add/Modify/Delete relativ zu HEAD;
- unmerged Stage 1/2/3;
- Gitlink, Symlink oder anderer unerwarteter Modus;
- doppelter oder nicht zum angeforderten Pfad gehörender Eintrag;
- Indexeintrag bei erwarteter HEAD-Abwesenheit;
- HEAD-Eintrag bei unerwarteter Index-Abwesenheit.

Damit bedeutet „Index-Fence“ exakt **keine Zielpfadabweichung zwischen Index und HEAD**,
nicht „getrackte Datei verboten“.

### 3.6 Kaltstartklassen und Priorität

Die öffentliche Beobachtung verwendet ein geschlossenes Enum mit mindestens:

| Klasse | Exakter Sicherheitsinhalt |
|---|---|
| `legacy_bootstrap` | HEAD/Index besitzen nur ein unverändertes reguläres `CLAUDE.md`; drei neue Ziele fehlen; Worktree entspricht exakt; keine generierten V1-Marker und keine Publisher-eigenen Signale |
| `absent` | alle vier Ziele fehlen in HEAD, Index und Worktree; keine Publisher-eigenen Signale |
| `valid` | alle vier Worktreebytes bilden eine D1-valide und extern attestierte Generation; Index entspricht HEAD; Pfade sind sicher |
| `unattested` | vollständige intern valide Vierergruppe, deren externe Attestation fehlt oder abweicht |
| `mixed` | unvollständige Kombination aus V1-Artefakten, V1-Markern oder exakt grammatischem Publisher-Transaktionssignal |
| `invalid` | alle vier behaupteten Artefakte sind vorhanden, aber der strikte D1-Beweis scheitert |
| `manual_review` | unsicherer Pfadtyp, Indexkonflikt, unbekannte Zielbytes, mehrdeutige/mehrfache Transaktionssignale, Race oder nicht sicher klassifizierbarer Zustand |

Fail-closed Priorität:

1. Pfad-, Git-, Index-, Race- oder Prozessfehler → `manual_review`;
2. unbekannte oder mehrere Publisher-Signale → `manual_review`;
3. exakt ein späteres eigenes Transaktionssignal plus Teilzustand → `mixed`;
4. vollständige Vierergruppe → `valid`, `unattested` oder `invalid`;
5. erst danach dürfen `legacy_bootstrap` oder `absent` erkannt werden.

Ein intern valider Record darf keine unsichere Pfad- oder Gitklasse überstimmen. Die
Beobachtung ist Diagnose, keine Publish-Entscheidung und keine Recovery-Autorität.

### 3.7 Rückgabevertrag

`RepositoryGenerationObservation` ist immutable und enthält nur typisierte, minimierte
Evidence:

- Klassifikation und stabilen Reason-Code;
- realen Repository-Root;
- gepinnten HEAD-Commit;
- pro Ziel HEAD-/Index-/Worktree-Abwesenheit oder Modus plus Blob-/Bytehash;
- bei `valid` den attestiert geladenen `PreviousPublishedRecord`;
- boolesche Publisher-Signal-/Race-Indikatoren ohne untrusted Freitext.

Es enthält keine Rootbytes, kein Snapshotobjekt, kein Publication-JSON, kein Git-stderr,
keine Environmentwerte und keine absolute Fremdpfad-Prosa. D2a trifft weder
`PUBLISH`/`NO_OP` noch Cleanup-/Rollbackentscheidungen.

---

## 4. D2a — exakter Patchscope

### 4.1 Produktcode

Nach Merge dieses Dokuments und erneuter Live-Prüfung sind ausschließlich erlaubt:

```text
steward/context_contract.py
steward/context_rendering.py
steward/context_publisher.py
```

- `context_contract.py`: höchstens bestehende Attestation-Validierung rein und öffentlich
  wiederverwendbar machen.
- `context_rendering.py`: attestierten D1-Generationsbeweis ergänzen und gegebenenfalls
  eine einzige Größen-/Loader-Wahrheit exportieren.
- `context_publisher.py`: ausschließlich read-only Git-/Filesystem-Beobachtung und
  Klassifikation gemäß §3.

Jeder weitere Produktpfad stoppt G2 und benötigt eine neue Reviewentscheidung.

### 4.2 Tests

Erlaubt sind ausschließlich:

```text
tests/test_context_contract.py
tests/test_context_rendering.py
tests/test_context_publisher.py
```

Ein Testpfad darf entfallen, wenn sein Produktmodul nicht geändert wird. Fixtures bleiben
in diesen Testdateien; neue globale Testinfrastruktur ist nicht freigegeben.

### 4.3 Ausdrücklich verboten

In D2a verboten sind Änderungen an:

- `CLAUDE.md`, `AGENTS.md` oder `.steward/**`;
- `.gitignore`;
- `steward/context_bridge.py`, Hooks, Agent, Briefing, Tools oder Caller;
- Git-NADI, GitTool, Senses, Actuators oder Federation;
- `.github/**`, Workflows, Branchschutz, Secrets oder Repository-Settings;
- Feature-/Master-Spec, Phase 1, Phase-2-Cockpit oder Befund im Code-PR;
- Dependency- oder Packaging-Konfiguration;
- jede Write-, Lock-, Journal-, Recovery-, Bootstrap-, Delivery- oder Aktivierungslogik.

---

## 5. Verpflichtende rote D2a-Tests

Vor Produktcode müssen mindestens folgende Tests rot sein.

### 5.1 Attestation

- dieselben vier validen Bytes plus exakt passende externe Attestation werden akzeptiert;
- falscher C0-Hash blockiert;
- falscher Source-Blob blockiert;
- falscher Reviewed-Commit blockiert;
- falscher Attestation-Runtime-Typ, Schema oder Status blockiert;
- intern konsistente, aber frei erfundene Constitution-Provenance wird als
  `unattested` klassifiziert;
- Publication-Bytes oder Previous Record allein besitzen keinen Attestation-Shortcut;
- ein einziger interner Parse-/Rebuild-Pfad wird durch direkten Test oder strukturelle
  Assertion abgesichert.

### 5.2 Git und Environment

- exakter Head-/Indexzustand wird aus NUL-getrennter Plumbing-Ausgabe geladen;
- Stage-0 identisch zu HEAD wird akzeptiert;
- staged Add/Modify/Delete und Stage 1/2/3 blockieren;
- unerwarteter Modus, doppelter oder fremder Pfad blockiert;
- `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, Object-/Replace- und Config-Overrides
  werden nicht an Git vererbt;
- Headwechsel zwischen zwei Beobachtungspunkten ergibt `manual_review`;
- Timeout, nonzero Exit, malformed NUL-Ausgabe und übergroße Ausgabe blockieren ohne
  ungefiltertes stderr;
- Blobbytes kommen aus `cat-file`, nicht aus Worktree oder Filter.

### 5.3 Pfade und Reads

- Root-, `.steward`-, Ziel- und Parent-Symlink blockieren;
- Directory, FIFO, Socket, Device und mehr als ein Hardlink blockieren;
- Zieltausch zwischen `lstat`, `open`, `fstat` und finaler Prüfung blockiert;
- zu große Datei, Short Read, unerwartetes Wachstum und Readfehler blockieren;
- separat gelesene bytegleiche Roots bleiben valide;
- keine Fehlermeldung enthält Zielbytes, Git-stderr oder fremde absolute Pfade.

### 5.4 Klassen

- der gepinnte P1-Shape wird ohne hardcodierten Blob als `legacy_bootstrap` erkannt;
- vierfach absent wird separat als `absent` erkannt;
- vollständige attestierte Generation wird `valid`;
- vollständige intern valide Generation mit externer Abweichung wird `unattested`;
- vollständige malformed Generation wird `invalid`;
- jede Teilkombination aus Record, Snapshot und generiertem Root wird `mixed` oder
  strenger `manual_review`, niemals `absent`/`legacy_bootstrap`;
- exakt grammatisches einzelnes künftiges Transaktionssignal wird nicht als valide
  Generation interpretiert;
- mehrere, malformed oder unbekannte Publishernamen ergeben `manual_review`;
- historische `.atomic_*` werden weder gelöscht noch als Context-Generation verwendet;
- unsicherer Pfad oder Indexkonflikt gewinnt immer gegen inhaltliche Validität.

### 5.5 Purity

Während Import und Ausführung von D2a werden schreibende `open`-Modi, `os.write`,
`os.replace`, `os.rename`, `os.unlink`, `Path.write_*`, `tempfile`, `fcntl.flock`,
mutierende Git-Kommandos, Clock, Netzwerk und ServiceRegistry durch Fakes verboten. Der
Test muss die echte `inspect_repository_generation()`-Grenze aufrufen; eine bloße
Source-String-Assertion genügt nicht.

---

## 6. D2b — jetzt entschiedene Leitplanken, weiterhin gesperrt

Dieser Abschnitt verhindert spätere spontane Architektur im Writer-Patch. Er autorisiert
keinen Code.

### 6.1 Lock

- fester Pfad `.steward/.context-publish-v1.lock`;
- `O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW`, Modus `0600`;
- nach Open: regulär, ein Hardlink, Owner gleich effektiver Prozess-UID und sicherer
  Parent;
- Lockdatei bleibt bestehen und wird nie als Unlock-Operation gelöscht; dadurch entsteht
  kein zweites Lock-Inode für konkurrierende Prozesse;
- pro realem Repository-Root ein Thread-Lock, danach exklusiver POSIX-`flock`;
- monotone begrenzte Deadline; feste Acquire-, reverse Release-Reihenfolge;
- Scope von erster D2a-Fence bis finalem Read-back, finaler Git-Refence und
  Erfolgsentscheidung.

Unter dem erworbenen Lock wird nach der ersten D2a-Fence genau eine Candidate-Factory
aufgerufen. Sie assembliert genau einen Snapshot und rendert genau eine immutable
Vierergruppe; ein zweites `assemble_context()` oder Re-Render zwischen den Replaces ist
verboten. Unmittelbar vor dem ersten Replace folgt die zweite vollständige Fence.

### 6.2 Durable Transaction Journal

Record-last allein beweist nach dessen Replace keinen Eigentümer mehr. D2b benötigt daher
ein lokales, nicht ausgeliefertes Journal:

```text
.steward/.context-publish-v1.<32 lowercase hex>.txn
```

Das Journal ist kanonisches striktes JSON, exklusiv erstellt, Modus `0600`, file- und
parent-`fsync`ed, bevor ein Zieltemp vorbereitet oder ein Ziel ersetzt wird. Es bindet
mindestens:

- versioniertes Schema und zufällige Transaction-ID;
- gepinnten Repository-Root-Identifier und HEAD-Commit;
- exakt vier geschlossene Zielpfade;
- pro Ziel Baseline-Abwesenheit oder HEAD-Blob, Modus und Baseline-Bytehash;
- pro Ziel Candidate-Bytehash und Größe;
- Candidate-`snapshot_id`, `payload_hash`, C0-Hash, Source-Blob und Reviewed-Commit;
- beabsichtigte feste Replace-Reihenfolge.

Es enthält keine Rohbytes, Environmentwerte, Exceptiontexte, Token oder absolute
Fremdpfade. Es bleibt bis nach vollständigem Read-back und finaler Refence bestehen.
Erst danach wird es entfernt und `.steward/` erneut synchronisiert.

### 6.3 Tempnamen und Prepare

Alle vier Temps teilen dieselbe Journal-ID:

```text
.context-publish-v1.<txid>.claude.tmp
.context-publish-v1.<txid>.agents.tmp
.steward/.context-publish-v1.<txid>.snapshot.tmp
.steward/.context-publish-v1.<txid>.publication.tmp
```

- Same-Parent, `O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW`, Modus `0600`;
- vollständiger EINTR-/Short-Write-Loop;
- File-`fsync`, Temp-Read-back, Größen- und Hashvergleich;
- alle vier Temps sind validiert und durable, bevor der erste Replace erfolgt;
- finale Zielmodi sind deterministisch `0644` und werden am vorbereiteten Inode gesetzt;
- ein neuer D2b-Preflight entscheidet die engsten Root-Temp-Ignore-Regeln; die beiden
  JSON-Ziele bleiben bis Slice E ohne Tracking-Ausnahme.

### 6.4 Replace, Erfolg und Race

Feste Reihenfolge:

1. `CLAUDE.md`,
2. `AGENTS.md`,
3. `.steward/context-snapshot.json`,
4. `.steward/context-publication.json` **last**.

Jeder einzelne Replace ist dirfd-relativ; Parent-Inode und Zielzustand werden vor dem
Replace erneut gebunden; danach folgt Parent-`fsync`. Erfolg wird erst gemeldet, wenn:

- alle vier finalen Bytes separat zurückgelesen wurden;
- D1 plus externe Attestation die Generation erneut vollständig beweist;
- HEAD und Zielindex weiterhin der ersten Fence entsprechen;
- Parent-/Targettypen weiterhin sicher sind;
- Journalentfernung durable abgeschlossen ist.

Ein Fremdprozess kann trotz Publisher-Lock Git oder Zielpfade verändern. Drift nach dem
ersten Replace darf daher nie als Erfolg gelten; das Journal bleibt Recovery-Evidence.

### 6.5 Recovery-State-Machine

Automatische Recovery ist nur unter exklusivem Lock und mit genau einem strikten,
vollständig validen Journal erlaubt. Jeder aktuelle Zielpfad muss bytegenau entweder der
im Journal gebundenen Baseline oder dem gebundenen Candidate entsprechen. Andere Bytes,
unsichere Pfade, mehrere Journale oder unbekannte Temps ergeben `manual_review` ohne
Mutation.

- **Alle vier Candidatebytes vorhanden und attestiert valide:** finalen Read-back und
  Refence wiederholen; danach Journal/Temps bereinigen.
- **Teilzustand mit vollständig attestierter Vier-Artefakt-Git-Baseline:** alle vier
  Ziele deterministisch auf diese Baseline zurücksetzen, Publication Record last; danach
  vollständiger D1-/Attestation-Read-back.
- **Teilzustand auf vollständig sauberer vierfach-absenter ephemerer Baseline:** nur
  journalgebundene Candidatebytes entfernen und vierfach absent erneut beweisen.
- **`legacy_bootstrap` oder andere Baseline ohne attestierte Vierergruppe:** keine
  automatische Reparatur. Zustand bleibt `manual_review`/`bootstrap_requires_review`.
- **Alle vier Baselinebytes, Journal blieb nur nach erfolgreichem Rollback liegen:**
  Baseline erneut attestieren, dann Journal/Temps bereinigen.

Unbekannte manuelle Rootänderungen, historische `.atomic_*`, ein Record ohne passendes
Journal oder neu assemblierte „ähnliche“ Kandidaten sind keine Recovery-Provenance.

### 6.6 Bootstrap bleibt außerhalb D2

Der aktuelle P1-Stand besitzt keine attestierte Vier-Artefakt-Git-Baseline. D2b darf ihn
daher nicht automatisch überschreiben. Der erste kanonische Bootstrap benötigt Slice E
mit exakt erneut präsentierten, reviewten Kandidaten, Attestation, Tracking-/Delivery-
Vertrag und eigenem Gate. Eine frische Assembly ist kein Ersatz für diese Freigabe.

### 6.7 Policy-Mode bleibt fail-closed

Der spätere Publisher-Policy-Mode `disabled | preview | canonical` bleibt vom bereits
existierenden Content-`OutputMode` getrennt. Fehlend, unbekannt oder ungültig bedeutet
`disabled`. D2b darf höchstens die lokale Transaktionsprimitive implementieren; es darf
keine Repository-Variable, Environmentvariable, Workflow- oder Caller-Aktivierung
einführen. Die Policy wird vor Assembly und erneut vor dem ersten Replace geprüft.
`disabled` und `preview` schreiben keine der vier Ziel- oder Transaktionsdateien.

---

## 7. D2a-Abbruchkriterien

G2 stoppt vor oder während D2a bei:

- fachlichem Main-Drift an den erlaubten Modulen, Tests oder Feature-Verträgen;
- neuem überlappendem PR;
- notwendigem Produktpfad außerhalb §4;
- Bedarf an Writer, Lock, Journal, `.gitignore`, Caller oder Workflow;
- zweiter Parser-/Attestation-/Größen-Wahrheit;
- Git-Porcelain-Parsing oder mutierendem Git-Helfer;
- nicht deterministisch klassifizierbarem P1-Zustand;
- Test, der nur Stringpräsenz statt der echten öffentlichen Grenze beweist;
- Linux-CI-Abweichung des read-only Git-/Filesystem-Vertrags;
- Versuch, D2a als Publish-, Recovery- oder Bootstrap-Autorität zu verwenden.

Nach Code-PR sind erforderlich:

- adversariales Review auf einen exakt gepinnten Head;
- Python 3.11, Python 3.12, Lint und Security grün;
- `git diff --check` und exakte Pfadprüfung;
- erneuter Basisblobvergleich gegen den G2-Pin;
- Bestätigung, dass kein Ziel, Runtime-State, Workflow oder Setting verändert wurde;
- regulärer Merge erst nach Review; anschließend Produktions-CI- und
  Nichtaktivierungsbeweis.

---

## 8. Nicht belegbare Annahmen

- Lokale Darwin-Ergebnisse beweisen keine Power-Loss-Durability auf jedem späteren
  GitHub-Runner-Dateisystem.
- Advisory `flock` sperrt keine fremden Editoren oder Git-Prozesse.
- Git-Plumbing beweist Repository-State nur an seinen Beobachtungspunkten; D2b benötigt
  deshalb Re-Fences und Recovery.
- Das aktuelle Fehlen eines Publishers beweist nicht, dass kein externer unbekannter
  Prozess Root-Dateien verändern kann.
- Vor Slice E existiert keine positive Produktionsfixture für eine getrackte,
  attestierte Vier-Artefakt-Baseline.
- Ein lokal vorhandenes Journal wäre erst nach D2b-Code und dessen eigener Review
  authentische Publisher-Provenance.

---

## 9. Gate-Wirkung

- Der read-only D2-Recon ist für den heutigen Basisstand abgeschlossen.
- D1s externe Attestation-Lücke ist positiv belegt und Bestandteil von D2a.
- Git-/Index-/Worktree-, Pfad- und Kaltstartvertrag sind für D2a geschlossen.
- Lock-, Journal-, Durability- und Recovery-Leitplanken sind für den späteren D2b-
  Preflight gebunden, aber noch nicht implementierungsfreigegeben.
- Nach Merge dieses Dokuments darf ausschließlich der kleine D2a-Code-PR beginnen.
- D2b, Bootstrap, Publisher, Writes, Caller, Workflow, Delivery, Settings und Aktivierung
  bleiben vollständig gesperrt.
- Kein Code beginnt vor adversarialer Review und regulärem Merge dieses G2-Dokuments.
