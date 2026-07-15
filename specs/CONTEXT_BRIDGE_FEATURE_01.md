# CONTEXT BRIDGE — FEATURE-SPEC 01

## Sicherer kanonischer Publisher und kontrollierte Delivery

> **Status:** G1 APPROVED — CONTRACT COMPLETE; IMPLEMENTIERUNG UND AKTIVIERUNG GESPERRT
> **Datum:** 2026-07-15
> **Gepinnte Basis:** `kimeisele/steward@66a3808205fb757a4c0a5a14eb1befdac24510e6`
> **Basis-Tree:** `2044159ad8791d5b3d203bd8dc49572859203dcf`
> **Constitution-Blob:** `29829be4f77dcaebf970a8ee872de299f0357f1c`
> **CLAUDE-Blob:** `8146a15603c95e5aa1404c9eb7021e3008914b0c`
> **Feature-04-Modul-Blob:** `baa8196d378270725bc5db15db6f5184f06b6e89`
> **Arbeitsmodus:** Spec-only. Keine Implementierung, Aktivierung oder Governance-Änderung.

---

## 1. Zweck und Gate

Feature 01 überführt die bereits implementierte, aber noch unverdrahtete semantische
Contract-Bibliothek in einen kontrollierten End-to-End-Publikationspfad. Der Pfad muss
aus genau einem validierten Snapshot zwei standardmäßig byte-identische Root-Verträge
erzeugen, lokal ehrlich publizieren und remote ausschließlich als geprüfte gemeinsame
Git-Transaktion ausliefern.

Diese Spec darf erst G1 erhalten, wenn ein adversariales Review bestätigt, dass sie:

- Feature 04 konsumiert und weder Modell noch Hash-Domains dupliziert,
- die menschlich reviewte Constitution nicht autonom verändert,
- keine echte Gruppenatomarität zweier Dateien vortäuscht,
- Teilzustände erkennt, Erfolg bei Teilzustand verweigert und deterministisch repariert,
- LLM-, Git-NADI- und generische Worktree-Nebenpublisher schließt,
- Aktivierung, Delivery, GitHub-Governance und Kill-Switch nicht vermischt,
- einen sicheren Bootstrap ohne vorgetäuschten Produktionsbeweis definiert.

**DRAFT 0.2 erteilt keine G2-Freigabe.** Auch ein späteres G1 erlaubt noch keinen Patch.
Jeder Implementierungsschnitt benötigt einen eigenen, auf den dann aktuellen Main-Head
gepinnten G2-Pre-Flight mit exakten Patchpfaden, roten Tests und Rollbackgrenze.

---

## 2. Normative Abhängigkeiten

Diese Spec unterliegt vollständig:

1. `specs/CONTEXT_BRIDGE_SYSTEM_SPEC.md`,
2. `specs/CONTEXT_BRIDGE_FEATURE_00.md`,
3. `specs/CONTEXT_BRIDGE_FEATURE_04.md`,
4. den G0-Evidence-Paketen unter `specs/context_bridge_evidence/`, insbesondere
   OQ-01/OQ-16, OQ-06/OQ-14, OQ-10 und OQ-18/OQ-07,
5. `steward/context_contract.py` als einzige implementierte Quelle für Markerparser,
   PUBLIC_SAFE-Validierung, Normalisierung, Hash-Domains und Compare-Entscheidung.

Bei Widerspruch gewinnt der aktuell verifizierte Code- und Produktionsbeweis. Die ältere
Spec wird dann vor Implementierung korrigiert. Phase 1 bleibt read-only.

---

## 3. Gepinnter Ist-Zustand

### 3.1 Lokale Writer

Am gepinnten Head existieren mindestens zwei direkte Root-Writer:

1. `steward.briefing.write_claude_md()` assembliert erneut Context, rendert über die
   Stage-Pipeline und schreibt ausschließlich `CLAUDE.md` per `Path.write_text()`.
2. `SynthesizeBriefingTool.execute()` assembliert unabhängig, ruft ein LLM auf und schreibt
   standardmäßig Root-`CLAUDE.md` oder einen frei gewählten Pfad.

`AGENTS.md` existiert nicht. Der Kommentar `SINGLE WRITER` ist sachlich falsch.
`_last_hash` ist nur prozesslokal. MTime-basierte CLI- und Intent-Entscheidungen sind keine
persistente Freshness-Garantie.

`OrientationStage` liest die heutige `.steward/conventions.md` nahezu vollständig und
rendert sie je nach Focus verbatim oder komprimiert. Eine Source-Migration vor einem
Legacy-Writer-Fence würde neue Marker und C0-Text sofort durch den alten, ungeprüften
Renderer in `CLAUDE.md` spiegeln.

### 3.2 Snapshot-Skew

Der MOKSHA-Hook ruft zuerst `assemble_context()` für `.steward/context.json` auf. Nach
erfolgreichem Write ruft `write_claude_md()` intern erneut `assemble_context()` auf.
Context-State und Root-Output können daher aus verschiedenen Beobachtungen stammen.

### 3.3 Remote-Delivery

Der Heartbeat-Workflow:

- checkt `main` mit `FEDERATION_PAT` aus,
- führt mehrere autonome Zyklen aus,
- staged im `if: always()`-Post-Step getrackten `.steward/`- und Federation-State,
- rebased und pusht direkt auf `main`.

Zusätzlich kann `GitNadiSync.push()` während MOKSHA committen und direkt pushen. Sein
Fallback `git add -A` erweitert den fachlichen Federation-Pfad auf den gesamten Worktree.
Workflow-Concurrency serialisiert nur gleichnamige Actions-Runs; sie schützt nicht gegen
manuelle Prozesse, Tool-Caller oder den internen Git-NADI-Pfad.

Der Live-Commit `f01a3ec9e7ce903bcc84cbedc5aacc5a8f04bedd` belegt diese Wirkung erneut:
ein einzelner `steward: federation sync`-Commit publizierte `CLAUDE.md`, Raw-Context,
Memory, Sessions und Federation-State gemeinsam.

### 3.4 Statische Quelle

`.steward/conventions.md` ist die einzige beschlossene Constitution-Quelle, enthält aber
noch keine C0-/Orientation-Marker und ist in ihrer heutigen Form nicht publizierbar.
Feature 00 definiert den exakten C0-v1-Text und die Source-/Root-Marker.

### 3.5 Feature 04

`steward/context_contract.py` ist gemergt, vollständig getestet und produktiv unverdrahtet.
Es stellt die reine Contract-Grenze bereit. Es schreibt keine Datei, liest keine Uhr und
kennt weder Git, GitHub, Netzwerk, Environment noch `ServiceRegistry`.

### 3.6 Live-Drift

Zwischen dem vorherigen Phase-2-Handoff und dieser Spec liefen weitere Heartbeats. Der
neue Main-Head änderte ausschließlich bekannte State-/Briefing-Pfade. Diese Aussage ist
ein gepinnter Snapshot, keine dauerhafte Garantie. Jeder G2-Pre-Flight wiederholt den
Call-Site-, Blob-, PR- und Workflow-Recon.

---

## 4. Scope und Nicht-Scope

### 4.1 Normativer Scope

Feature 01 spezifiziert:

- Migration der bestehenden Constitution-Quelle auf den reviewten C0-v1-Vertrag,
- deterministisches Rendering aus `SemanticPayloadCore v1` und Snapshot-Provenance,
- standardmäßig byte-identische `CLAUDE.md`- und `AGENTS.md`-Kandidaten,
- persistente Publication- und Snapshot-Artefakte,
- exklusiven lokalen Publisher mit per-Datei atomarem Replace,
- Mixed-Generation-Erkennung, Read-back, Recovery und Safe Fallback,
- Migration aller kanonischen Caller auf einen Einstieg,
- fail-closed Isolation des LLM-Synthese-Tools,
- eine allowlistete branch-/PR-basierte Remote-Delivery,
- einen offline deterministischen Required Contract Check,
- zweistufige Aktivierung, Kill-Switch, Incident-Fence und Produktionsdrill.

### 4.2 Ausdrücklicher Nicht-Scope

Nicht enthalten sind:

- freie Übernahme von `PHASE2_CURRENT`,
- Issue-, Task-, Session-, Sense-, Gap-, Annotation- oder Federation-Prosa,
- neue Task- oder Issue-Priorisierung,
- Verdrahtung des internen `StewardAgent` als Root-Consumer,
- LLM-Annotationen im kanonischen Output,
- neuer Renderer- oder Plugin-Framework-Layer,
- Symlinks zwischen Consumer-Dateien,
- Git-History-Rewrite,
- versteckte Migration aller Federation- oder State-Formate,
- automatische Aktivierung direkt mit dem letzten Code-PR.

Feature 02/03 bleiben für Continuity und Arbeitspriorisierung zuständig.

---

## 5. Zielarchitektur

```text
ein Publisher-Einstieg
  -> Modus/Fence prüfen
  -> repositoryweiten Lock erwerben
  -> C0-Quelle + Attestation prüfen
  -> Rohquellen genau einmal lesen
  -> Feature-04-Normalisierung
  -> NormalizedSnapshot v1
  -> SemanticPayloadCore v1
  -> PreviousPublishedRecord validieren
  -> decide_publish(...)
       blocked/manual_review/no_op -> keine Root-Mutation
       publish -> render + candidate validation
  -> vier Kandidaten vollständig vorbereiten
  -> pro Pfad atomar ersetzen; Record zuletzt
  -> alle vier Artefakte read-back-validieren
  -> lokale Publication als erfolgreich melden
  -> Delivery-Fence erneut prüfen
  -> allowlisteten Delivery-Branch/PR aktualisieren
  -> Required Check validiert staged/PR bytes
  -> Git-Merge ist Remote-Transaktionsgrenze
```

Vier Artefakte bilden eine Generation:

```text
CLAUDE.md
AGENTS.md
.steward/context-snapshot.json
.steward/context-publication.json
```

`CLAUDE.md` und `AGENTS.md` sind Consumer-Ausgaben. Der Snapshot ist die PUBLIC_SAFE,
normalisierte Provenancebasis. Der Publication Record ist der Commit-Marker der lokal
vollständig validierten Generation. Keines dieser Artefakte ist eine zweite manuelle
Wahrheit.

`.steward/context-publication.lock`, Tempfiles und Recovery-Arbeitsdateien sind lokale,
ignorierte Laufzeitartefakte und werden nie staged.

### 5.1 Einmalige Raw-Assembly und V1-Adapter

Der Publisher erhält genau ein bereits assembliertes Raw-Context-Mapping. Im Heartbeat ist
dies dasselbe Objekt, das der MOKSHA-Hook einmal erfasst und gegebenenfalls um die
vorhandene Live-Vedana ergänzt. Ein zweiter `assemble_context()`-Aufruf ist verboten.

Ein reiner Adapter erzeugt daraus `SourceResult`, `NormalizedObservations` und Comparison-
State für Feature 04. Er folgt exakt
`FEATURE_01_SOURCE_ADAPTER_RECON.md`:

- nacktes `{}`/`[]` oder fehlender Key ist mangels positiver Legacy-Provenance
  `unavailable/provenance_missing`, niemals gesund `empty`,
- Feature-04-`ContractViolation` mappt geschlossen auf `unsafe`, `unsupported` oder
  `invalid`,
- unerwartete interne Exceptions blockieren den gesamten Kandidaten,
- Sessions, Tasks, Issues, Architecture, Annotations und Continuity liefern in V1 nur
  Source-Status; ihre Rohwerte fehlen vollständig in Snapshot und Payload,
- `assembled_at` wird nach dem letzten Raw-Read erfasst und als oberer Beobachtungswert
  der synchronen Assembly übergeben,
- Raw-`timestamp` und lokale Pfade werden nicht übernommen.

Der konservative Adapter darf sichtbar degradieren. Eine spätere typisierte Reader-Härtung
ist ein eigener Schnitt und kein Vorwand, im ersten Publisher fehlende Semantik zu erfinden.

---

## 6. Writer-Fence und statische Source-Migration

### 6.1 Zwingender Legacy-Fence

Die Source darf nicht als erster Produktivschnitt migriert werden. Zuvor muss ein eigener
kleiner PR beweisen:

1. `write_claude_md()` mutiert keine Root-Datei mehr und delegiert noch nicht an einen
   unfertigen neuen Publisher,
2. `synthesize_briefing` liefert ausschließlich expliziten Preview-Output,
3. MTime-/Intent-/Strategy-Texte behaupten keine kanonische LLM-Aktualisierung mehr,
4. Git-NADI staged ausschließlich positiv benannte Federationpfade und besitzt keinen
   `git add -A`-Fallback,
5. ein Source-Diff allein verändert weder `CLAUDE.md` noch eine neue `AGENTS.md`.

Dieser Fence stoppt unsichere Nebenwirkungen. Er erzeugt noch keine neue Root-Payload und
keine Remote-Delivery. Der bestehende Legacy-`CLAUDE.md`-Blob bleibt während des kurzen,
kontrollierten Bootstrap-Fensters unverändert und wird ausdrücklich nicht als neuer
kanonischer Publish bestätigt.

### 6.2 Einmalige menschlich reviewte Migration

Die bestehende `.steward/conventions.md` wird in einem eigenen PR chirurgisch aufgeteilt:

1. exakt der in Feature 00 festgelegte C0-v1-Text zwischen C0-Markern,
2. nur positiv klassifizierte Architekturhilfe zwischen Orientation-Markern,
3. keine Persona `You are Steward`, keine Runtime-Identität und kein aktueller Auftrag,
4. keine volatile Frequenz, Healthzahl, Peeridentität oder Agenda,
5. kein dynamischer Root-Block.

Der PR erzeugt noch keinen automatischen Publisher, verändert keine Root-Datei und
aktiviert keine Delivery. Sein nach Governance Amendment 01 vom Operator explizit
freigegebener PR-Head-Commit und der darin enthaltene Source-Blob bilden nach Merge die
externe Attestation-Evidence für den Bootstrap.

### 6.3 ConstitutionAttestation

Die Attestation wird nicht vom Heartbeat erfunden. Der Bootstrap-/Governance-PR bindet:

- den normalisierten C0-SHA-256,
- den Git-Blob der reviewten `.steward/conventions.md`,
- den Commit, an dem die menschliche Reviewentscheidung gilt.

Ein Attestation-Resolver erhält den explizit freigegebenen PR-Head-Commit samt
`approval_mode=single_owner_hitl` als Bootstrap-Input und
prüft über Git/GitHub-Evidence, dass:

- dieser Commit dem eingefrorenen und vom Operator freigegebenen Source-PR-Head entspricht,
- `.steward/conventions.md` an diesem Commit exakt den gebundenen Source-Blob besitzt,
- der aktuell zu publizierende C0-Hash aus genau diesem Blob stammt,
- der aktuelle Source-Blob noch identisch ist.

Der Resolver liefert danach das bestehende Feature-04-Value-Object. Er schreibt keine
Attestation-Datei und setzt `status=verified` nicht allein aufgrund einer lokalen
Konfiguration. Fehlende gebundene Operatorfreigabe oder API-Unverfügbarkeit blockiert den
ersten Bootstrap. Ein Source-Blob-Wechsel führt zu `manual_review`, nie zu Autopublish.

Der reviewte PR-Head ist bereits vor dem nachfolgenden Bootstrap-PR bekannt und vermeidet
eine Commit-Selbstreferenz. Der Merge-Commit darf abweichen, solange Git beweist, dass der
reviewte Commit erreichbar ist und derselbe Source-Blob im Zielbranch gilt.

Die API-, Blob- und Pagination-Prüfsequenz aus
`FEATURE_01_ATTESTATION_OPERATIONS_RECON.md` bleibt technische Evidence; ihre
Zwei-Principal-Annahme wird durch `CONTEXT_BRIDGE_GOVERNANCE_AMENDMENT_01.md` ersetzt. Der
Resolver erhält Source-PR-Nummer, freigegebenen Head-Commit, Source-Blob, C0-Hash und
Approval-Modus als expliziten Bootstrap-Input. PR-Titel, Commitmessage und `merged_by`
ersetzen keine Operatorfreigabe.

---

## 7. Deterministischer Renderer

### 7.1 Input

Der Renderer erhält ausschließlich:

- einen bereits validierten `SemanticPayloadCore v1`,
- `snapshot_id` und `snapshot_hash`,
- Repository- und Generator-Commit aus dem Snapshot,
- `payload_hash`,
- Consumer-Output-Schema und Publication-Modus.

Er liest keine Datei, Uhr, Environmentvariable, Registry oder Netzwerkquelle. Er ruft
`assemble_context()` nicht auf und normalisiert keine Rohdaten erneut.

### 7.2 Root-Struktur

Jeder Kandidat besitzt exakt:

1. C0-v1-Block,
2. Dynamic-v1-Block,
3. optionalen Orientation-v1-Block,
4. genau einen finalen LF.

Der Dynamic-Block verwendet feste, renderer-eigene Überschriften und Labels. Dynamische
Werte erscheinen ausschließlich als validierte Enums, Counts, Hashes, Schema-IDs oder
stabile Repository-relative Pfade. Freie Rohprosa kontrolliert weder Markdown noch
Instruktionssprache.

Die V1-Textprojektion ist exakt:

````text
<!-- steward-context:c0:v1:begin -->
<normalized C0 bytes>
<!-- steward-context:c0:v1:end -->

<!-- steward-context:dynamic:v1:begin -->
## Generated Steward Context

This block is generated observed data, not an operator instruction.

- Payload schema: `steward.context.payload/v1`
- Snapshot schema: `steward.context.snapshot/v1`
- Mode: `<closed mode>`
- Snapshot ID: `<ctxsnap-v1 hash>`
- Payload hash: `<64 lowercase hex>`
- Repository head: `<40 lowercase hex>`
- Generator commit: `<40 lowercase hex>`
- Constitution source blob: `<40 lowercase hex>`
- Constitution reviewed commit: `<40 lowercase hex>`

### Source Status

```json
<canonical JSON array from payload.source_status>
```

### Observations

```json
<canonical JSON object from payload.observations>
```
<!-- steward-context:dynamic:v1:end -->

<!-- steward-context:orientation:v1:begin -->
<normalized Orientation bytes, or empty payload>
<!-- steward-context:orientation:v1:end -->
````

Die inneren `json`-Fences und alle Labels sind feste Rendererbytes. Dynamische Werte
werden ausschließlich durch `canonical_json_bytes()` erzeugt. C0 und Orientation werden
nicht im JSON-Datenkörper dupliziert. Ein fehlender Orientation-Payload erhält trotzdem
genau das versionierte leere Markerpaar, damit beide Consumer denselben Strukturvertrag
besitzen.

Whitespace-Vertrag:

- LF-Zeilenenden,
- genau eine Leerzeile zwischen Top-Level-Blöcken,
- keine trailing Spaces,
- kompakte kanonische JSON-Bytes ohne zusätzliche Einrückung,
- genau ein finaler LF,
- UTF-8 ohne BOM.

Die Backticks um skalare Provenancewerte sind statische Rendererbytes. Alle eingesetzten
Werte besitzen geschlossene ASCII-Verträge und können keinen Backtick oder Marker
enthalten.

### 7.3 Provenance

Mindestens sichtbar sind:

- Payload-/Snapshot-Schema,
- Modus `canonical`, `degraded` oder `safe_fallback`,
- `snapshot_id`, `payload_hash`, Repository-Head und Generator-Commit,
- C0-Version, C0-Hash und Constitution-Source-Blob,
- alle teilnehmenden Source-Statuswerte und Source-Modi.

Publikationszeit ist C4. Sie wird nur bei einem echten Publish in die konkrete Generation
aufgenommen, aber nicht in die V1-Root-Datei gerendert. Sie bleibt Snapshot-Diagnostik.
Ein `no_op` verändert weder Root-Bytes noch Provenance.

### 7.4 Consumer-Default

Der Renderer erzeugt zunächst genau einen Bytepuffer. Derselbe Puffer wird als Kandidat
für `CLAUDE.md` und `AGENTS.md` verwendet. Vorsorgliche Consumer-Hüllen sind verboten.
Eine spätere Abweichung benötigt den in Feature 00 definierten positiven Consumer-Beweis,
eine Spec-Revision und getrennte Output-Hashes.

---

## 8. Persistente Artefakte

### 8.1 Snapshot

`.steward/context-snapshot.json` ist ein versioniertes Envelope:

```json
{
  "schema": "steward.context.snapshot-artifact/v1",
  "snapshot_id": "ctxsnap-v1:<64 lowercase hex>",
  "snapshot_hash": "<64 lowercase hex>",
  "snapshot": "<exact NormalizedSnapshot v1 object>"
}
```

`snapshot_hash` wird ausschließlich über das innere Snapshot-Objekt nach der Feature-04-
Domain berechnet. Das Envelope und insbesondere `snapshot_id` fließen nicht zurück in
diese Hash-Domain. `snapshot_id` muss exakt aus `snapshot_hash` ableitbar sein.

Das Artefakt enthält keine rohen Quellen, Exceptiontexte oder lokale Pfade. Es wird nur
gemeinsam mit einer tatsächlich publizierten Payload ersetzt; ein C4-only/no-op-Snapshot
wird nicht remote geliefert.

### 8.2 Publication Record

`.steward/context-publication.json` besitzt ebenfalls ein äußeres Envelope:

```json
{
  "schema": "steward.context.publication-artifact/v1",
  "previous": "<exact PreviousPublishedRecord v1 object>",
  "snapshot_artifact_hash": "<64 lowercase hex>",
  "repository_head": "<40 lowercase hex>",
  "generator_commit": "<40 lowercase hex>",
  "constitution": {
    "source_blob": "<40 lowercase hex>",
    "reviewed_at_commit": "<40 lowercase hex>"
  },
  "targets": {
    "agents": "AGENTS.md",
    "claude": "CLAUDE.md",
    "snapshot": ".steward/context-snapshot.json"
  }
}
```

Das innere `previous`-Objekt entspricht exakt dem Feature-04-Schema und wird ohne
Erweiterung in `PreviousPublishedRecord` geladen. `snapshot_artifact_hash` verwendet eine
eigene versionierte Artifact-Domain über die vollständigen kanonischen Bytes des Snapshot-
Envelopes. Der Publication-Record enthält keinen Hash seiner eigenen fertigen Bytes und
erzeugt daher keine Selbstzirkulation.

```text
snapshot_artifact_hash =
  sha256("steward-context-snapshot-artifact-v1\0" || canonical_snapshot_envelope_bytes)
```

Unbekannte Felder auf jeder Envelope-Ebene, falsche Typen oder Hashabweichungen machen das
Artefakt invalid. Es ist keine Autorität über Root-Bytes; Read-back muss alle Bindungen
erneut beweisen.

### 8.3 Gitignore und Staging

Die beiden JSON-Artefakte benötigen eng benannte `.gitignore`-Ausnahmen. Es gibt keine
Ausnahme für Lock-, Temp- oder generische `.steward/*.json`-Pfade. Staging nennt jeden
Delivery-Pfad explizit; `git add -A`, `git add -f` und Verzeichnis-Globs sind verboten.

---

## 9. Lokale Transaktion

### 9.1 Exklusivität

Der einzige Publisher verwendet:

- einen prozessweiten Thread-Lock,
- einen repositoryweiten Interprozess-Lock,
- einen begrenzten Acquire-Timeout,
- einen Lock-Scope von erster Fence-Prüfung bis finaler Read-back-Entscheidung.

V1 unterstützt kanonische Publication ausschließlich auf positiv getesteten POSIX-
Plattformen. Linux-Produktion und macOS-Engineering verwenden einen stdlib-basierten
advisory `flock` auf einem sicher geöffneten Lockfile. Thread- und Prozesslock werden in
fester Reihenfolge erworben und umgekehrt freigegeben. Auf Windows oder einer Plattform
ohne den belegten Lock-/fsync-/Replace-Vertrag ist `canonical` fail-closed `disabled`;
Preview ohne Root-Write bleibt möglich. Feature 01 fügt keine vorsorgliche
Drittanbieterabhängigkeit hinzu.

Der Publisher pinnt Repository-Head und Target-Hashes vor Assembly und prüft beides vor
dem ersten Replace erneut. Ein HEAD-Wechsel, Indexeintrag oder unbekannter Worktree-Diff
an einem der vier Zielpfade blockiert. Der Publisher-Lock wird nicht fälschlich als Lock
für fremde Git-, Editor- oder Agentenprozesse dargestellt.

### 9.2 Pfadschutz

Vor jedem Write wird bewiesen:

- Repository-Root ist der erwartete reale Pfad,
- jeder Zielparent ist der reale Repository-Root beziehungsweise `.steward/`,
- kein Ziel und kein relevanter Parent ist Symlink,
- existierende Ziele sind reguläre Dateien,
- relative Zielnamen enthalten keine Traversal-, URI- oder Backslash-Komponente.

Ein Verstoß blockiert vor dem ersten Replace.

### 9.3 Prepare

Alle vier Kandidaten werden vor Mutation vollständig erzeugt und validiert. Je Ziel wird
ein eindeutiger Tempfile im selben Verzeichnis mit exklusiver Erzeugung angelegt,
vollständig geschrieben, geflusht und `fsync()`-synchronisiert. Byteanzahl und Hash werden
gegen den Kandidaten geprüft.

### 9.4 Commit-Reihenfolge

Zwei oder vier reguläre Dateien sind nicht gemeinsam atomar. Feature 01 verspricht nur:

1. atomaren Replace je Einzelpfad,
2. gemeinsame Generationsidentität,
3. Erkennung jedes Mischzustands,
4. keinen positiven Erfolg vor vollständigem Read-back,
5. deterministische Recovery,
6. gemeinsamen Git-Commit als Remote-Transaktion.

Replace-Reihenfolge:

1. `CLAUDE.md`,
2. `AGENTS.md`,
3. `.steward/context-snapshot.json`,
4. `.steward/context-publication.json` zuletzt.

Der Record ist damit lokaler Commit-Marker, macht frühere Replaces aber nicht rückwirkend
gruppenatomar. Parent-Verzeichnisse werden nach Replace synchronisiert, soweit der
Plattformvertrag dies unterstützt.

### 9.5 Read-back

Erfolg wird erst gemeldet, wenn:

- beide Root-Dateien den vollständigen Blockvertrag erfüllen,
- beide Root-Bytes im Default identisch sind,
- beide Output-Hashes mit dem Record übereinstimmen,
- Snapshot-ID/-Hash und Payload-Hash reproduzierbar sind,
- C0-Bytes, C0-Hash und Attestation zusammenpassen,
- Snapshot und Record dieselbe Generation bezeichnen,
- keine Tempdatei als kanonisches Artefakt interpretiert wird.

Jeder Teilfehler ist sichtbar und nicht erfolgreich.

---

## 10. Recovery und Safe Fallback

### 10.1 Kaltstartklassifikation

Vor neuer Assembly klassifiziert der Publisher den bestehenden Zustand als:

- `absent`: noch kein vollständiges publiziertes Set,
- `valid`: vier Artefakte vollständig gebunden,
- `mixed`: Record und mindestens ein Artefakt widersprechen sich,
- `invalid`: Schema, Pfad, Marker, Hash oder PUBLIC_SAFE-Vertrag verletzt,
- `unattested`: technisch valide C0-Bytes ohne gültige Governance-Attestation.

`mixed`, `invalid` und `unattested` sind nie `degraded-but-current`.

### 10.2 Deterministische Reparatur

Unter Lock gilt:

1. gültigen, attestierten letzten Git-Stand der vier Artefakte prüfen,
2. wenn dieser Stand vollständig ist, eine eindeutig als eigener unterbrochener Publish
   nachweisbare lokale Mischgeneration auf genau diese Bytes zurückführen oder eine neue
   vollständig attestierte Kandidatengeneration publizieren,
3. niemals einzelne alte und neue Artefakte kombinieren,
4. bei fehlender reparierbarer Basis blockieren,
5. Temp-Artefakte nur anhand des eigenen engen Namensschemas und nur außerhalb eines
   aktiven Locks bereinigen.

Die konkrete Git-Read-back-API und der Bootstrap ohne bestehenden gültigen Git-Stand
werden im Recovery-G2-Pre-Flight durch Crash-Fixtures festgelegt. Eine eingebaute zweite
C0-Kopie ist verboten.

Eine unbekannte manuelle oder agentische Änderung an `CLAUDE.md`, `AGENTS.md`, Snapshot
oder Record ist **kein** Recovery-Signal. Sie führt zu `manual_review`/`blocked` und wird
nicht automatisch mit `HEAD` überschrieben. Automatische Recovery benötigt passende
Generation-/Temp-Metadaten des eigenen Publishers oder einen vollständig sauberen
ephemeren Checkout.

### 10.3 Safe Fallback

`safe_fallback` darf nur aus einem zuvor vollständig verifizierten, attestierten C0-
Snapshot derselben Source-Provenance entstehen. Alle dynamischen Beobachtungen werden als
unavailable/unknown ausgewiesen. Alte Agenda, freie Prosa und LLM-Output bleiben draußen.
Ohne verifizierten C0-Snapshot wird blockiert.

Da `NormalizedSnapshot v1` nur C0-Hash und Source-Provenance, nicht den C0-Text speichert,
liest der Fallback die C0-Bytes aus einem zuvor vollständig validierten Root-Output und
prüft sie erneut gegen Record, Snapshot und Source-Blob. Einzelne Root-Dateien oder ein
Hash ohne diese Bindung genügen nicht.

---

## 11. Caller-Migration und LLM-Isolation

### 11.1 Ein kanonischer Einstieg

Alle produktiven Root-Aufrufe enden in genau einem Publisher-Einstieg. Der MOKSHA-Hook
übergibt seinen einmal assemblierten Rohzustand beziehungsweise einen dafür typisierten
Adapter; der Publisher darf keinen zweiten Snapshot erfassen.

Der bestehende Name `write_claude_md()` darf vorübergehend als kompatibler Wrapper bleiben,
aber er darf weder selbst rendern noch nur eine Datei schreiben. Sein Rückgabevertrag wird
explizit auf `published`, `no_op`, `blocked` oder `manual_review` migriert; ein Boolean darf
keine Fehlerklasse verschlucken.

### 11.2 Bestehendes `context.json`

Das rohe `.steward/context.json` ist kein kanonisches Context-Bridge-Artefakt und keine
Quelle für den Publication Record. Seine bestehende Runtime-Funktion wird nicht heimlich
in Feature 01 umdefiniert. Der Hook darf Root-Publikation nicht länger davon abhängig
machen, ob dieser separate Raw-State-Writer zufällig `True` zurückgibt.

### 11.3 LLM-Tool

`synthesize_briefing` bleibt als sichtbarer Toolname erhalten, wird aber fail-closed:

- nur expliziter `stdout`-/Preview-Return,
- kein Root-Ziel,
- kein beliebiger Dateipfad,
- kein persistierter Preview-Pfad ohne eigene spätere Spec,
- klare Metadaten `mode=preview` und `canonical=false`,
- alter Write-Caller erhält einen expliziten Fehler.

Intent-, Strategy- und Toolbeschreibungen dürfen nicht mehr behaupten, das Tool aktualisiere
kanonischen Root-Context.

### 11.4 Git-NADI

`GitNadiSync` darf keine Root-, Constitution-, Publisher-, Workflow- oder Contract-Datei
stagen oder ausliefern. Der `git add -A`-Fallback wird entfernt. Vor Aktivierung von
PR-only `main` darf kein interner Direct-Push-Pfad übrig sein.

Die fachliche Federation-State-Delivery benötigt einen expliziten Allowlist-Vertrag im
Delivery-Schnitt. Feature 01 darf sie nicht stillschweigend löschen; sie darf aber auch
nicht als Rechtfertigung für einen Worktree- oder Admin-Bypass dienen.

---

## 12. Remote-Delivery

### 12.1 Grenzen

Lokale Publication und Remote-Delivery sind getrennte Komponenten und getrennte
Codeänderungen. Lokaler Erfolg bedeutet nur validierte Worktree-Artefakte. Remote-Erfolg
bedeutet ausschließlich einen gemergten, auf Base-Head und Payload gebundenen Git-Commit.

### 12.2 Delivery-Branch

Der Heartbeat verwendet einen stabil benannten Automation-Branch mit genau einem offenen
Delivery-PR. Der endgültige Name wird im Delivery-G2-Pre-Flight gegen bestehende Branches
geprüft. Jeder Lauf:

1. pinnt den aktuellen geschützten Base-Head,
2. verwirft vorbereitete Generationen eines anderen Base-Heads,
3. erstellt oder aktualisiert den Automation-Branch deterministisch,
4. staged ausschließlich den expliziten Delivery-Scope,
5. prüft den staged Diff vor Commit,
6. pusht nur den Automation-Branch,
7. erstellt oder aktualisiert genau den identifizierten PR,
8. aktiviert Auto-Merge erst nach erneuter Fence-Prüfung.

### 12.3 Context-Delivery-Scope

Für Context Bridge sind ausschließlich erlaubt:

```text
CLAUDE.md
AGENTS.md
.steward/context-snapshot.json
.steward/context-publication.json
```

Federation-/Runtime-State ist kein impliziter Teil dieser Allowlist. Wenn der Heartbeat
weiteren State im selben PR liefern soll, benötigt jeder Pfad beziehungsweise eng
definierte Pfadklasse einen eigenen Contract und Leak-Test. Ein Context-PR darf nicht
wegen bestehender breiter State-Praxis zum Worktree-PR werden.

### 12.4 Required Check

Der Anzeigename bleibt exakt `Context Bridge Contract`. Der Check läuft auf jedem PR gegen
`main` und entscheidet intern, ob der Diff relevant ist. Bei relevantem Diff prüft er
offline mindestens:

- erlaubte Autor-/Branch-/Pfadtopologie,
- Source- und Root-Marker,
- exakte C0-Bindung,
- Dynamic-Schema und PUBLIC_SAFE-Grenze,
- Default-Bytegleichheit,
- Snapshot-/Payload-/Output-Hashes,
- Publication-Record-Bindung,
- Base-Head-/Generator-Provenance,
- keine Governanceänderung im Automation-PR,
- keine Lock-, Temp-, Secret- oder unallowlisteten State-Artefakte.

Der Automation-PR kann Validator, Workflow, CODEOWNERS oder Publisher nicht selbst ändern.

#### 12.4.1 Migrationszustände ohne Skip-Loch

Der Check darf nicht schon vor Bootstrap die noch nicht existierende Vier-Artefakt-
Generation verlangen und damit Source-Migration deadlocken. Er darf aber auch keinen
beliebigen „migration mode“ aus einem PR-Input akzeptieren. Der Zustand wird ausschließlich
aus Base-/Head-Tree und geschützter Policy abgeleitet:

1. **P0 Legacy fenced** — Base und Head besitzen keinen Publication Record, Policy ist
   `disabled`, Root-`CLAUDE.md` ist bytegleich zur Base und `AGENTS.md` fehlt. Erlaubt sind
   Fence-/Validator-/Renderer-Pfade; Target-Fixtures müssen grün sein. Source bleibt
   bytegleich zur Base.
2. **P1 Source reviewed** — weiterhin kein Publication Record, Policy `disabled`, beide
   Root-Zustände exakt wie in P0; Constitution-Source ist jetzt vollständig valid. Der
   Check validiert Source, begrenzt den Übergangs-Diff auf den reviewten Source-/Contract-
   Scope und beweist keine Root-Mutation.
3. **P2 Bootstrap transition** — Base besitzt keinen, Head exakt einen neuen validen
   Publication Record und alle vier Artefakte. Vollständiger Contract inklusive externer
   Source-PR-Attestation ist Pflicht.
4. **P3 Steady state** — Base und Head besitzen vollständige Artefakte. Jede relevante
   Änderung erhält den normalen vollständigen Contract; Entfernen oder Zurückfallen auf
   P0/P1 blockiert.

Keine PR-Variable, kein Label, Titel, Committext oder Automation-Input kann diese Zustände
überschreiben. Unerwartete Kombinationen blockieren. Bei irrelevanten PRs läuft weiterhin
die eigene Scope-Prüfung; sie ist ein erfolgreicher deterministischer Check, kein
Workflow-Path-Skip.

### 12.5 Federation-State-Entkopplung

PR-only `main` kann erst aktiviert werden, wenn der bestehende Heartbeat-Post-Step und
Git-NADI nicht mehr direkt pushen. Runtime-/Federation-State wird ausdrücklich **nicht**
in denselben Context-Delivery-PR aufgenommen. Seine hohe Cadence, Restartfunktion und
teilweise freie beziehungsweise lokale Datenklasse besitzen einen anderen Trust-,
Retention- und Leak-Vertrag.

Das Evidence-Paket `FEATURE_01_RUNTIME_STATE_RECON.md` verwirft `main`, den Context-PR
und einen vollständigen öffentlichen State-Branch als Full-State-Store. Zielarchitektur
ist ein minimaler privater Runtime-Checkpoint plus der bestehende öffentliche
Federation-Hub. Ein eigener Feature-/Operations-Schnitt muss vor Aktivierung festlegen
und testen:

- welcher minimale allowlistete State nach einem ephemeren Runner-Restart erforderlich ist,
- welcher private Store und Credential-Scope die belegten Consumerverträge erfüllt,
- wie State vor dem Lauf sicher restored und nach dem Lauf konfliktfrei checkpointed wird,
- welche Daten öffentlich sein dürfen und welche vollständig aus Git entfernt werden,
- wie Retention, Schema, Race, Recovery und Credential-Scope aussehen.

Die read-only Suche fand keinen positiven externen Consumer des Steward-Main-Raw-State,
beweist aber nicht dessen Entbehrlichkeit. Deshalb sind Trust-Grenze und Zieltopologie
entschieden; konkrete Feldallowlist, Storetreiber und Migration bleiben ein
**Aktivierungsblocker**, nicht improvisierter Context-Bridge-Code.

---

## 13. Aktivierung und Kill-Switch

### 13.1 Zwei Schlüssel

Kanonische Publication ist default-off. Aktivierung benötigt gleichzeitig:

1. die menschlich reviewte, code-owned Repository-Konfiguration
   `.github/context-bridge-policy.json` mit Schema `steward.context.policy/v1` und
   geschlossenem Modus `disabled | preview | canonical`,
2. einen separaten Runtime-Enable-Key, der nur weiter einschränken, nie Repository-Policy
   hochstufen darf.

Der Runtime-Key ist die Repository-Actions-Variable `CONTEXT_BRIDGE_RUNTIME_MODE` mit
demselben geschlossenen Vokabular. Fehlend, unbekannt oder ungültig bedeutet `disabled`.
Effektiver Modus ist die strengere der beiden Grenzen: Runtime kann `canonical` zu
`preview`/`disabled` und `preview` zu `disabled` herabstufen, aber niemals hochstufen.

V1-Delivery reserviert nach positiver Kollisionsprüfung:

```text
Branch: automation/context-bridge
PR title: [context-bridge] canonical context publication
PR body marker: <!-- steward-context-delivery:v1 -->
Required check: Context Bridge Contract
Constitution check: Context Constitution Contract
Workflow display name: Context Bridge Delivery
```

PR-Identität wird nicht aus dem Titel allein abgeleitet, sondern aus Base, Head-Repository,
Head-Branch, Automation-Principal und Body-Marker. Mehrdeutigkeit blockiert.

### 13.2 Fence-Zeitpunkte

Der Modus wird mindestens geprüft:

- vor Snapshot/Write,
- nach lokalem Read-back,
- vor Branch-Push,
- vor PR-Erzeugung/-Update,
- vor Auto-Merge-Aktivierung.

`disabled` verbietet Root-Writes, Generationserfolg, Branch-Push, PR-Erzeugung und
Auto-Merge. Read-only Diagnose bleibt zulässig. Ein vor Stop erzeugter Snapshot darf nicht
später ausgeliefert werden.

### 13.3 Incident-Stop

Der Operationsvertrag umfasst weiterhin:

1. Workflow deaktivieren,
2. queued/in-progress Runs force-canceln und terminal verifizieren,
3. Delivery-PRs identifizieren, Auto-Merge entfernen und fencen,
4. Push-Credential beim Aussteller widerrufen/rotieren,
5. PR-only Remote-Fence ohne Admin-/Automation-Bypass prüfen,
6. erzeugte Commits und Blobs inventarisieren,
7. ausschließlich statischen verifizierten Minimal-Fallback zulassen,
8. erst nach Root-Cause-Fix und menschlicher Freigabe neu starten.

Der echte Drill ist G2-Aktivierungsgate, nicht G0-Prosa.

---

## 14. GitHub-Governance

Vor automatischer kanonischer Delivery müssen gelten:

- `main` ist PR-only und Branchschutz gilt für Administratoren,
- Force-Push und Branchlöschung sind verboten,
- keine Automation besitzt Main-Bypass,
- `.steward/conventions.md` benötigt eine gebundene Single-Owner-HITL-Freigabe;
  Konfiguration, Publisher, Renderer, Workflow und Contract-Tests ändern sich nur per PR,
- jeder Commit nach einer Operatorfreigabe verwirft diese Freigabe,
- `Context Bridge Contract` ist required,
- der finale PR-Head, Source-Blob und C0-Hash sind im Reviewpaket gebunden.

Der belegte Ein-Collaborator-Zustand wird ehrlich als Single-Owner-HITL betrieben; Agent,
Bot und lokaler Git-Autor sind keine unabhängigen Reviewer. Automatische Aktivierung bleibt
bis zu Required Check, Delivery-/Kill-Switch-/Recovery-Vertrag und kontrolliertem G2-Drill
gesperrt.

---

## 15. Verpflichtende Implementierungsschnitte

Feature 01 ist ein End-to-End-Vertrag, aber ausdrücklich kein Mega-PR.

### 15.1 Schnitt A — Legacy-Writer-Fence

- deterministischen Legacy-Root-Writer deaktivieren,
- LLM-Tool auf Preview-Return begrenzen,
- MTime-/Intent-/Strategy-Fehlbehauptungen entfernen,
- Git-NADI-`git add -A` und Root-Reichweite schließen,
- noch kein neuer Publisher und keine Source-Migration.

### 15.2 Schnitt B — Offline-Contract und Renderer

- reine Source-/Candidate-Validatoren,
- reiner Renderer aus Feature-04-Modellen,
- identische Root-Kandidaten,
- zirkulationsfreie Snapshot-/Record-Envelopes,
- adversariale Tests,
- noch keine Writes.

### 15.3 Schnitt C — reviewte Constitution-Migration

- C0-/Orientation-Migration erst hinter dem Writer-Fence,
- Source-PR mit separatem menschlichem Review,
- reviewten PR-Head und Source-Blob als Bootstrap-Evidence erfassen,
- keine Root-Mutation oder automatische Delivery.

### 15.4 Schnitt D — lokaler Publisher und Recovery

- Lock, Pfadschutz, Temp/Replace/fsync,
- Record-last und Read-back,
- Crash-/Mixed-Generation-Recovery,
- Modus default `disabled`, keine Delivery.

### 15.5 Schnitt E — reviewter Bootstrap

- Attestation gegen gemergten Source-PR auflösen,
- erste Vier-Artefakt-Generation offline erzeugen,
- Bootstrap-PR separat contract-testen und reviewen,
- noch kein Heartbeat-Autopublish.

### 15.6 Schnitt F — kanonische Caller-Migration

- MOKSHA auf einen Snapshot/einen Publisher,
- alte Wrapper fail-closed,
- Raw-`context.json` vom Root-Trigger entkoppeln,
- weiterhin keine Remote-Aktivierung.

### 15.7 Schnitt G — Context-Remote-Delivery

- expliziter Automation-Branch/PR,
- exakt vier contract-gebundene Context-Artefakte,
- `Context Bridge Contract` in CI,
- Kill-Switch-/Fence-APIs verdrahten.

### 15.8 Schnitt H — Runtime-State-Persistence

- eigener Feature-/Operations-Vertrag für volatile `.steward/`-/Federation-State,
- Restart-, Retention-, PUBLIC-/Leak-, Race- und Recovery-Beweis,
- kein State-Glob im Context-PR,
- alle verbleibenden Main-Direct-Push-Pfade schließen.

### 15.9 Schnitt I — Governance und Aktivierungsdrill

- PR-only Branchschutz/Required Check und optionales CODEOWNERS-Defense-in-Depth,
- Single-Owner-HITL-Bindung und Head-Drift-Invalidierung,
- Disable/Force-Cancel/PR-Fence/Credential-Containment,
- kontrollierter Preview- und Canonical-Drill,
- Produktionsblob- und Folgeheartbeat-Verifikation.

Kein Schnitt darf seine eigene lokale Grünheit als Abschluss von Feature 01 darstellen.

---

## 16. Testvertrag

### 16.1 Unit und Contract

- exakte C0-/Orientation-/Dynamic-Marker und Reihenfolge,
- C0 unabhängig von Budget/Focus/Health unverändert,
- Bytegleichheit beider Consumer,
- feste Renderer-Golden-Bytes,
- Snapshot-/Payload-/Output-Hash-Reproduktion,
- unknown-field/default-deny,
- Secret-, Pfad-, Unicode-, Markdown- und Marker-Injection,
- LLM kann keinen kanonischen Zielpfad schreiben.

### 16.2 Publisher

- konkurrierende Threads und Prozesse,
- Lock-Timeout ohne Mutation,
- Symlink an jedem Ziel und Parent,
- readonly Ziel/Parent, kurzer Write, `ENOSPC`, fsync-/replace-Fehler,
- Prozessabbruch nach jedem einzelnen Replace,
- alter Record/neue Roots und neue Roots/alter Snapshot,
- Record zuletzt, vollständiger Read-back,
- identischer PreviousPublishedRecord über Prozessneustart -> no-op,
- safe fallback nur mit verifiziertem C0.

### 16.3 Delivery

- Branch basiert auf gepinntem Main-Head,
- unallowlisteter Pfad blockiert vor Commit,
- kein `git add -A`, `-f` oder Verzeichnisfallback,
- stale Base, zweiter Heartbeat und bestehender PR,
- Pushfehler, PR-API-Fehler, Checkfehler und Mergekonflikt,
- disable zwischen Write/Push/PR/Auto-Merge,
- Automation-PR kann Validator/Governance nicht ändern,
- Git-Commit enthält genau eine gebundene Generation.

### 16.4 Produktion

- Merge-Commit und vier Blobs per GitHub API prüfen,
- Root-Dateien bytevergleichen,
- Hashes unabhängig aus Blobs reproduzieren,
- Folgeheartbeat erzeugt bei semantischem No-op keinen Diff,
- C1-Wechsel erzeugt genau einen allowlisteten PR,
- Kill-Switch stoppt neue und bereits vorbereitete Delivery,
- kein Git-NADI- oder Post-Step-Direct-Push auf `main`,
- kein Temp-/Lock-Artefakt im Remote-Tree.

Ein grüner lokaler Testlauf ersetzt keinen Produktionsbeweis.

### 16.5 Normativer Golden-Vektor

`specs/context_bridge_evidence/FEATURE_01_PUBLICATION_VECTORS.json` bindet die V1-
Textprojektion und beide Artifact-Envelopes an den bereits gemergten Feature-04-
Snapshot-/Payload-Vektor. Erwartet sind:

```text
Root UTF-8 bytes: 2318
Consumer output hash: 9519cfc5867580d041ef7d01c6007a35e7d98b51d559c08b6b941940fcbb6e9d
Snapshot artifact UTF-8 bytes: 4781
Snapshot artifact hash: fb6320ea4e8dd3d2fd8c009d920396c9e5db73aa4403027b5fae2ca3d3719ac3
Publication artifact UTF-8 bytes: 1203
```

Die Werte wurden unabhängig mit Python und Ruby aus demselben normativen Feature-04-
Input reproduziert. Tests lesen die Fixture; Produktcode kennt keinen `specs/`-Pfad.

---

## 17. Rollback

Jeder Schnitt besitzt einen eigenen Revert. Bei Incident gilt zuerst Containment, danach
Revert. Rollback darf nicht:

- einen alten dynamischen Context als aktuell darstellen,
- C0 aus einer eingebauten Kopie rekonstruieren,
- Direct-Push oder Admin-Bypass reaktivieren,
- beide Root-Dateien unabhängig reparieren,
- offene Auto-Merge-PRs weiterleben lassen.

Der sichere Zustand ist `disabled` plus letzter vollständig verifizierter statischer
Vertrag oder blockierte Publication. Verfügbarkeit rechtfertigt keine falsche Governance.

---

## 18. Post-G1-Gates und Deployment-Preconditions

DRAFT 0.2 schließt die Architekturentscheidungen. Folgende nachgelagerte Gates bleiben
bewusst getrennt:

1. **Runtime-State-Persistence:** Zieltopologie ist entschieden; Feldallowlist, privater
   Store, Credential-, Retention-, Restore- und Recovery-Vertrag benötigen die eigene
   Feature-Spec vor Aktivierung.
2. **Bootstrap-Fixtures:** erste gültige Vier-Artefakt-Generation nach reviewter Source,
   einschließlich absent/mixed/invalid-Kaltstart.
3. **Governance-Entscheidung:** gebundener Single-Owner-HITL-Pfad nach Governance
   Amendment 01; ein unabhängiger Reviewer bleibt optionale spätere Defense-in-Depth.

Diese Punkte dürfen nicht im Code improvisiert werden. Punkt 1 benötigt eine eigene
Feature-Spec vor Aktivierung. Punkt 2 gehört in die roten Tests des Bootstrap-G2-
Pre-Flights. Punkt 3 ist eine externe Live-Governance-Precondition und kann nicht durch
Code ersetzt werden.

---

## 19. Adversariales G1-Review

Das Review muss mindestens fragen:

- Kann untrusted Input irgendeine imperative oder Markdown-Struktur kontrollieren?
- Kann ein Crash eine positive Erfolgsbehauptung bei Mischgeneration erzeugen?
- Kann ein alter Record neue Root-Bytes legitimieren?
- Kann ein C0-Source-Wechsel ohne menschliche Attestation publiziert werden?
- Kann LLM-, Git-NADI-, CLI-, Intent- oder generisches Tooling die Root-Grenze umgehen?
- Kann der Automation-PR seinen eigenen Validator oder Governance-Scope ändern?
- Kann Runtime-Enable geschützte Repository-Policy hochstufen?
- Kann ein No-op trotzdem Timestamp-, Snapshot- oder Heartbeat-Rauschen committen?
- Bleibt Federation-Liveness erhalten, ohne einen breiten Worktree-Publisher zu behalten?
- Ist jeder behauptete Plattform-/GitHub-Vertrag positiv belegt und drillbar?

Das finale Review hat diese Fragen gegen DRAFT 0.2 geprüft. Neue Code- oder
Produktionsevidence kann die Freigabe weiterhin widerlegen und erzwingt dann eine
Spec-Revision vor Fortsetzung.

---

## 20. Schlussstatus

Feature 01 besitzt mit DRAFT 0.2 einen G1-freigegebenen chirurgischen End-to-End-Vertrag,
aber noch keine Implementierungsfreigabe. Die Grundrichtung lautet:

> Ein Feature-04-Modell, ein deterministischer Renderer, ein exklusiver lokaler Publisher,
> vier gebundene Generation-Artefakte, ein allowlisteter PR-Delivery-Pfad und kein
> kanonischer LLM- oder Direct-Push-Nebenweg.

Der nächste erlaubte Schritt ist ausschließlich:

> Einen auf den dann aktuellen `origin/main` gepinnten G2-Pre-Flight ausschließlich für
> Schnitt A — Legacy-Writer-Fence — erstellen. Er benennt exakte Patchpfade, rote Tests,
> Rückwärtskompatibilität und Rollback. Vor dessen separatem Merge beginnt kein Code.

Produktcode, Workflow, Root-Dateien, Constitution, GitHub-Settings und Aktivierung bleiben
bis zu geschlossenem G1 und separatem G2-Pre-Flight gesperrt.
