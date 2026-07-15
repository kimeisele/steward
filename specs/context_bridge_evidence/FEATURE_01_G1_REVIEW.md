# FEATURE 01 — ADVERSARIALES G1-REVIEW

> **Status:** CHANGES REQUESTED — DRAFT 0.1 NICHT G1-FÄHIG
> **Datum:** 2026-07-15
> **Spec-Basis:** `specs/CONTEXT_BRIDGE_FEATURE_01.md` DRAFT 0.1
> **Live-Code-Basis:** `kimeisele/steward@31651bfc52c98bb6be66d7adb6f3055cbc410388`
> **Später beobachteter Main-Head:** `29df3f74ce62c4ce7c0b1edbb649f3f8eff75166`
> **Scope:** Read-only Review. Keine Produkt-, Workflow-, Root- oder Governance-Änderung.

---

## 1. Urteil

DRAFT 0.1 setzt die richtige Sicherheitsrichtung, ist aber noch nicht implementierbar.
Vier Blocker und mehrere Präzisierungen müssen vor G1 in die Spec zurückgeführt werden.

Positiv sind insbesondere:

- Feature 04 bleibt reine, einzige Modell-/Hash-Grenze,
- Root-Ausgaben werden als gebundene Generation statt unabhängige Dateien behandelt,
- echte Mehrdatei-Atomarität wird nicht behauptet,
- Publication Record wird zuletzt ersetzt und anschließend read-back-validiert,
- LLM- und Git-NADI-Nebenwege werden ausdrücklich geschlossen,
- Context-Delivery ist von Federation-/Runtime-State getrennt,
- Aktivierung bleibt default-off und benötigt eigene G2-Gates.

G1 bleibt dennoch geschlossen.

---

## 2. Blocker F01-R01 — Source-Migration ist in der vorgeschlagenen Reihenfolge unsicher

### Positive Beweise

`OrientationStage.enrich()` ruft `_load_orientation(cwd)` auf. Der Loader liest die
gesamte `.steward/conventions.md`, entfernt nur einen führenden Headerbereich und gibt den
Rest als Markdown zurück. Bei hohem Focus wird dieser Text verbatim in `CLAUDE.md`
eingefügt; bei geringerem Focus werden Überschriften und ausgewählte Zeilen übernommen.

Der heutige MOKSHA-Pfad ruft diesen Renderer automatisch auf. Git-NADI kann die dadurch
geänderte Root-Datei anschließend per überbreitem Fallback nach `main` pushen.

### Auswirkung

Ein isolierter PR, der nur C0-/Orientation-Marker in `.steward/conventions.md` einführt,
würde vom Legacy-Renderer als gewöhnlicher Orientation-Text verarbeitet. Die neuen
Source-Marker wären damit kein Schutz, sondern könnten in eine weiterhin strukturell
falsche Root-Datei gespiegelt werden.

### Erforderliche Korrektur

Vor Source-Migration müssen alle Legacy-Root-Writes fail-closed gefencet sein:

1. deterministischer Legacy-Writer erzeugt keine Root-Mutation mehr,
2. LLM-Tool kann nur Preview zurückgeben,
3. Git-NADI kann Root-/Governancepfade nicht stagen,
4. ein Test beweist, dass eine Source-Änderung allein keine Root-Datei verändert.

Erst danach darf die Constitution-Quelle migriert werden. Bootstrap folgt als eigener,
reviewter Schritt.

---

## 3. Blocker F01-R02 — Snapshot- und Record-Form sind noch zirkulär beziehungsweise inkompatibel

### Positive Beweise

Feature 04 definiert `snapshot_hash` über die kanonischen Bytes des
`NormalizedSnapshot v1`. `snapshot_id` ist daraus abgeleitet und darf daher nicht in genau
dem gehashten Objekt selbst liegen.

`PreviousPublishedRecord` besitzt ein exaktes V1-Schema. DRAFT 0.1 beschreibt
`.steward/context-publication.json` dagegen als denselben Record „plus“ zusätzliche flache
Felder. Ohne Envelope würde der spätere Loader entweder Feature 04 umgehen oder zwei
unterschiedliche Record-Schemata unter demselben Namen akzeptieren.

### Erforderliche Korrektur

Zwei versionierte Envelopes müssen festgelegt werden:

- Snapshot-Artefakt: `snapshot_id`, `snapshot_hash` und darunter exakt das gehashte
  `NormalizedSnapshot v1`.
- Publication-Artefakt: genau ein unverändertes `PreviousPublishedRecord`-Objekt plus
  separat versionierte Artifact-/Read-back-Metadaten.

Kein Hash umfasst sein eigenes Feld. Der Publication-Record umfasst keinen Hash seiner
eigenen fertigen Bytes, sofern keine weitere äußere Envelope eingeführt wird.

---

## 4. Blocker F01-R03 — Attestation-Bootstrap benötigt einen nicht-zirkulären Reviewbeweis

### Positive Beweise

`ConstitutionAttestation` verlangt C0-Hash, Source-Blob und `reviewed_at_commit`. Ein Commit,
der seinen eigenen noch unbekannten Commit-Hash im Inhalt tragen soll, ist nicht
konstruierbar. Eine vom Heartbeat selbst gesetzte `status=verified`-Behauptung beweist
keinen menschlichen Review.

Die Live-Governance besitzt weiterhin keinen belegten Zwei-Principal-Pfad. Der Benutzer
hat technische Ausführung delegiert, aber das ersetzt keinen maschinenprüfbaren separaten
GitHub-Code-Owner-Review.

### Erforderliche Korrektur

Bootstrap muss gestuft werden:

1. Legacy-Writer und Nebenpublisher fencen.
2. Constitution in einem getrennten, tatsächlich reviewten PR migrieren.
3. Nach Review/Merge den exakten **reviewten PR-Head-Commit** und Source-Blob als
   Attestation-Evidence verwenden.
4. Erst ein nachfolgender Bootstrap-PR erzeugt die erste Vier-Artefakt-Generation.
5. Runtime löst Attestation aus positivem GitHub-/Git-Evidence; sie erfindet sie nicht.

Ohne realen Author-/Reviewer-Split können Code und Preview vorbereitet, aber weder
`verified`-Bootstrap noch automatische kanonische Aktivierung behauptet werden.

---

## 5. Blocker F01-R04 — Federation-State darf nicht in den Context-Delivery-Scope rutschen

### Positive Beweise

Der aktuelle Heartbeat schreibt ungefähr alle 15 Minuten State nach `main`; mehrere Runs
wurden zusätzlich per `workflow_dispatch` gestartet. Die letzten erfolgreichen Runs
dauerten ungefähr zwei bis fünf Minuten. Aktuelle PR-CI-Läufe dauerten ungefähr zwei bis
drei Minuten. Ein PR-Pfad ist zeitlich grundsätzlich möglich, aber State-Cadence und
Context-Semantik sind nicht identisch.

Der beobachtete Git-NADI-Commit
`f01a3ec9e7ce903bcc84cbedc5aacc5a8f04bedd` änderte in einem Commit:

- `.steward/context.json`, Memory, Sessions und Health-State,
- `CLAUDE.md`,
- Federation-Inbox/-Outbox, Peers, Quarantine und Relay-State.

`context.json` enthält lokale absolute Runnerpfade sowie freie Session-/Issue-Prosa und
ist kein PUBLIC_SAFE Context-Bridge-Artefakt.

Cross-Repo-Nachrichten werden bereits separat über `kimeisele/steward-federation`
transportiert. Read-only GitHub-Code-Suche fand keinen positiven Beweis, dass andere
öffentliche Repositories Steward-Main-`context.json`, `sessions.json`,
`relay_seen_ids.json` oder `steward_health.json` direkt konsumieren. Das beweist nicht,
dass volatile State-Persistenz entbehrlich ist: der ephemere Heartbeat benötigt weiterhin
einen Restart-/Checkpoint-Vertrag.

### Erforderliche Korrektur

- Context-Delivery bleibt exakt auf vier PUBLIC_SAFE Artefakte begrenzt.
- Runtime-/Federation-State erhält vor PR-only-Main eine eigene Persistence-/Delivery-
  Entscheidung, wahrscheinlich außerhalb des Main-Codebranches.
- Kein offener State-Entscheid darf durch `git add -A`, Verzeichnis-Staging oder einen
  gemeinsamen ungeprüften PR verdeckt werden.
- Feature 01 kann vorbereitet, aber nicht automatisch aktiviert werden, solange dieser
  Main-Direct-Push-Blocker offen ist.

---

## 6. Präzisierung F01-R05 — Exakter Root-Rendervertrag fehlt

DRAFT 0.1 benennt Blockreihenfolge und erlaubte Typen, aber noch keine vollständige
deterministische Textprojektion. Vor G1 müssen feststehen:

- feste Überschriften und Labels,
- Darstellung aller Provenancefelder,
- Darstellung von Source-Status und Observations,
- JSON-/Markdown-Escaping,
- Whitespace und finaler LF,
- Golden-Bytes und Output-Hash.

Ein kanonischer JSON-Datenkörper innerhalb renderer-kontrollierter Markdown-Struktur ist
zulässig, wenn C0 und Orientation nicht dupliziert werden und dynamische Werte niemals
die Fence-Struktur kontrollieren.

---

## 7. Präzisierung F01-R06 — Publication-Zustand und bestehender Raw-State sind getrennt

`PreviousPublishedRecord` ist persistente semantische Vergleichsbasis. Das heutige
`.context_hash` ist nur ein gekürzter Hash über raw `context.json` und kann nicht migriert
oder wiederverwendet werden.

`context.json` darf weiter eine interne Runtimefunktion haben, aber:

- sein Write-Erfolg darf Root-Publication nicht triggern,
- es darf nicht im Context-Delivery-PR liegen,
- es darf nicht als PUBLIC_SAFE Snapshot ausgegeben werden,
- seine MTime darf keine kanonische Freshnessentscheidung treffen.

---

## 8. Präzisierung F01-R07 — Lock-Plattform muss fail-closed sein

Das Projekt deklariert Python `>=3.11`, aber keinen positiven Windows-Publishervertrag und
keine Lock-Abhängigkeit. CI und Produktion laufen auf Linux; die aktuelle Engineering-
Umgebung auf macOS. Beide besitzen POSIX-`flock`.

Die Spec darf für V1 einen stdlib-basierten POSIX-Publisher festlegen und auf nicht
belegten Plattformen canonical fail-closed deaktivieren. Eine scheinbar portable
Lock-Abstraktion ohne Testmatrix wäre schwächer. Die konkrete Wahl bleibt G2-Patchgrenze,
muss aber vor G1 als Plattformvertrag formuliert werden.

---

## 9. Nicht belegbare Annahmen

- GitHub-Code-Suche beweist nicht die Abwesenheit privater oder dynamischer Consumer.
- Der beste langfristige Persistenzort für Runtime-State ist noch nicht entschieden.
- Ein dedizierter State-Branch ist plausibel, aber noch nicht auf Restart, Leak-Scope,
  Retention, Race und Recovery geprüft.
- Ein echter Zwei-Principal-Code-Owner-Pfad existiert noch nicht.
- Die exakte Attestation-Resolver-API ist noch nicht festgelegt.

---

## 10. Gate-Wirkung

- DRAFT 0.1: **CHANGES REQUESTED**.
- G1: **OFFEN**.
- Keine Implementation oder Aktivierung ist freigegeben.
- Nächster Schritt: DRAFT 0.2 mit korrigierter Sequenz, Envelopes, Root-Golden-Vertrag,
  Attestation-Bootstrap und explizitem State-Persistence-Aktivierungsblocker.
