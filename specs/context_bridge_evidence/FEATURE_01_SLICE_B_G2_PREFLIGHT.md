# FEATURE 01 / SCHNITT B — G2-PRE-FLIGHT

> **Status:** G2 START APPROVED — nur reiner Offline-Contract und Renderer nach Merge dieses Dokuments
> **Datum:** 2026-07-15
> **Produktionsbasis:** `kimeisele/steward@5a1dbef7bbdb8bb1085f33b434613b619e6bedfd`
> **Produktions-Tree:** `0345f4e4ec45513b637de71ee84e8c96041d9b92`
> **Feature-Spec:** `specs/CONTEXT_BRIDGE_FEATURE_01.md` — G1 APPROVED
> **Voraussetzung:** Schnitt A Merge `1b1ef63d9d873a08acb812f18ba102b73174838c`, produktiv verifiziert
> **Scope:** G2-Pre-Flight und Startentscheid; noch keine Produktcodeänderung

---

## 1. Entscheidung

Schnitt B darf implementiert werden, sobald dieses Dokument regulär auf `main` gemergt
ist und ein frischer Implementierungsbranch vom dann aktuellen `origin/main` erstellt
wurde.

Die Freigabe umfasst ausschließlich:

1. öffentliche reine Validatoren für die bereits bestehenden Feature-04-Modelle,
2. einen kleinen deterministischen Feature-01-Renderer,
3. byte-identische Root-Kandidaten,
4. kanonische zirkulationsfreie Snapshot-/Publication-Envelopes,
5. reine Candidate-Read-back-Validierung gegen explizite Inputs,
6. isolierte adversariale Tests.

Der Slice liest oder schreibt keine Datei. Er verdrahtet keinen Caller und erzeugt im
Repository weder `CLAUDE.md`, `AGENTS.md` noch `.steward/context-*.json`.

---

## 2. Gepinnte Live-Evidence

### 2.1 Main und Parallelität

Nach `git fetch origin --prune` galt am oben gepinnten Head:

- kein offener Pull Request,
- Slice A war gemergt und sein Folgeheartbeat verifiziert,
- kein Rendering-/Publication-Modul existierte,
- kein Testpfad für Feature-01-Rendering existierte,
- der seit dem vorherigen Docs-Merge beobachtete Drift änderte ausschließlich bekannte
  `.steward/`- und Federation-Runtime-Dateien,
- `steward/context_contract.py` und `tests/test_context_contract.py` waren seit dem
  Feature-04-Merge fachlich unverändert.

Diese Aussagen werden unmittelbar vor dem ersten Implementierungspatch erneut geprüft.
Ein überlappender PR, geänderte Contract-Symbole oder unbekannter Main-Drift stoppen G2.

### 2.2 Vorhandene Feature-04-Wahrheit

`steward/context_contract.py` liefert bereits:

- `ParsedConventions`, `SourceResult`, `ConstitutionAttestation`,
  `PreviousPublishedRecord` und geschlossene Enums,
- `parse_conventions()` und `validate_public_safe_text()`,
- `build_payload_core()` und `build_snapshot()`,
- `canonical_json_bytes()`, `snapshot_hash()`, `payload_hash()` und
  `consumer_output_hash()`,
- `decide_publish()`.

Schnitt B darf diese Modelle, Enums, Hash-Domains und Marker nicht kopieren. Insbesondere
ist `parse_conventions()` bereits der reine Source-Validator; ein bloßer Alias in einem
zweiten Modul wäre unnötige API- und Driftfläche.

### 2.3 Aktuelle Lücke

Die Builder validieren ihre Inputs, aber es existiert noch kein öffentlicher Vertrag, der
ein bereits materialisiertes beliebiges `SemanticPayloadCore v1` oder
`NormalizedSnapshot v1` vollständig und rekursiv gegen dasselbe Schema prüft. Ein neuer
Renderer darf deshalb weder private `_validate_*`-Symbole importieren noch ein zweites
Vokabular führen.

Die Lösung dieses Slice ist additive öffentliche Validierung **im bestehenden
Contract-Modul**. Builder und Renderer benutzen danach dieselbe Validierungslogik.

---

## 3. Golden-Evidence

Die gemergten Fixtures wurden am Live-Head erneut mit einer unabhängigen
Python-Standardbibliotheksberechnung reproduziert:

```text
payload_hash:
d3a344af1700b88346695e13833ec5d6f81b66584ef8272542c64f7d4aa4d71a

snapshot_hash:
999ba49ddaea6300f3398159103491915a9b5ce3b7871a9cbd2f7b20b761ceba

root bytes: 2318
consumer_output_hash:
9519cfc5867580d041ef7d01c6007a35e7d98b51d559c08b6b941940fcbb6e9d

snapshot artifact bytes: 4781
snapshot_artifact_hash:
fb6320ea4e8dd3d2fd8c009d920396c9e5db73aa4403027b5fae2ca3d3719ac3

publication artifact bytes: 1203
```

Der Root-Kandidat endet mit genau einem LF. Beide kanonischen JSON-Envelopes besitzen
keinen finalen LF. Produktcode liest keine Fixture und kennt keinen `specs/`-Pfad.

---

## 4. Exakte Patchpfade

### 4.1 Produktcode

Zulässig sind ausschließlich:

```text
steward/context_contract.py
steward/context_rendering.py
```

`steward/context_rendering.py` ist neu. `steward/context_contract.py` darf nur um
öffentliche Modellvalidatoren und die dafür nötige interne Wiederverwendung ergänzt
werden. Bestehende Schema-IDs, Vokabulare, Builderoutputs, Hashbytes und Entscheidungen
dürfen sich nicht ändern.

### 4.2 Tests

Zulässig sind ausschließlich:

```text
tests/test_context_contract.py
tests/test_context_rendering.py
```

`tests/test_context_rendering.py` ist neu. Als read-only Fixtures dürfen ausschließlich
die bereits gemergten Dateien gelesen werden:

```text
specs/context_bridge_evidence/FEATURE_04_HASH_VECTORS.json
specs/context_bridge_evidence/FEATURE_01_PUBLICATION_VECTORS.json
```

Jeder weitere Pfad stoppt G2 und benötigt eine neue Reviewentscheidung.

---

## 5. Ausdrücklich verbotener Scope

Nicht verändern:

```text
CLAUDE.md
AGENTS.md
.steward/**
.github/**
docs/**
specs/CONTEXT_BRIDGE_FEATURE_01.md
specs/CONTEXT_BRIDGE_FEATURE_04.md
specs/context_bridge_evidence/*.json
steward/briefing.py
steward/briefing_stages.py
steward/context_bridge.py
steward/hooks/**
steward/intent_handlers.py
steward/services.py
steward/tools/**
steward/git_nadi_sync.py
```

Ebenfalls verboten:

- Filesystem-, Git-, GitHub-, Clock-, Netzwerk-, Environment- oder Registry-Zugriff,
- `Path`, `open`, `os`, `time`, `datetime`, `subprocess`, `socket` oder
  `ServiceRegistry` im neuen Modul,
- `assemble_context()` oder Raw-Source-Normalisierung,
- Writer, Lock, Tempfile, Replace, fsync oder Recovery,
- neue Plugin-, Pipeline-, Registry- oder Renderer-Frameworkabstraktion,
- Source-Migration oder Attestation-Auflösung,
- Änderung bestehender Feature-04-Goldenwerte,
- Exportänderung in `steward/__init__.py`,
- Root-Consumer-spezifische Hüllen,
- Publication-Zeit im Root-Kandidaten,
- Aktivierung oder Delivery.

---

## 6. Öffentliche Modellvalidatoren

`steward/context_contract.py` darf genau zwei neue logische Fähigkeiten exportieren:

```text
validate_payload_core(model)
validate_snapshot_model(model)
```

Konkrete Rückgabe darf `None` oder das unveränderte validierte Mapping sein. Sie muss im
Testvertrag fest und konsistent sein. Fehler bleiben `ContractViolation` und dürfen keinen
abgelehnten Rohwert spiegeln.

### 6.1 Payload-Core

Der Validator prüft rekursiv:

- exakte Top-Level-Keys und Schema-ID,
- exakte Contract-Keys,
- C0-/Orientation-Version, Typ, PUBLIC_SAFE-Grenze und SHA-256-Bindung,
- geschlossenen Modus einschließlich `preview`; der allgemeine Feature-04-Validator darf
  Preview weiterhin validieren und hashen,
- exakte teilnehmende Source-Menge, Reihenfolge und pro Source geschlossene
  Status-/Mode-/Age-Felder,
- Source-ID-zu-Mode-Bindung aus derselben bestehenden Contract-Wahrheit,
- exakte Observation-Form über die vorhandene `_validate_observations()`-Logik,
- Mode-/Degradation-Konsistenz,
- kanonische Serialisierbarkeit.

`build_payload_core()` ruft am Ende diesen öffentlichen Validator auf. Es entsteht kein
zweiter Builderpfad und kein anderer Output.

### 6.2 Snapshot

Der Validator prüft rekursiv:

- exakte Top-Level- und Nested-Keys sowie Schema-IDs,
- Repositoryname, Repository-Head und Generator-Commit,
- RFC3339-`assembled_at`,
- Constitution-Version, C0-Hash, Source-Blob und Review-Commit,
- Orientation-Hash,
- exakte Comparison-State-Menge und Counts,
- exakte vollständige Source-Menge in deterministischer Reihenfolge,
- Source-ID-zu-Trust-/Mode-Bindung, Timestamps, Age, Schema und Fehlercode,
- keine Source-Beobachtung nach `assembled_at`,
- exakte Observation-Form,
- kanonische Serialisierbarkeit.

`build_snapshot()` ruft am Ende diesen öffentlichen Validator auf. Snapshot-Bytes und
Feature-04-Hash bleiben dadurch identisch.

Private bestehende Helfer dürfen innerhalb desselben Moduls wiederverwendet oder minimal
refaktoriert werden. Der neue Renderer importiert ausschließlich öffentliche Symbole.

---

## 7. Minimale Rendering-API

Das neue Modul besitzt genau eine kleine Datenstruktur und reine Funktionen. Logische
Fähigkeiten:

1. frozen `PublicationCandidates` mit vier `bytes`-Feldern,
2. Root-Kandidat aus validiertem Payload-Core und Snapshot,
3. Snapshot-Artifact-Bytes,
4. Publication-Artifact-Bytes,
5. vollständiger Kandidatenbau,
6. vollständige Kandidatenvalidierung durch deterministischen Rebuild und Bytevergleich.

Konkrete Funktionsnamen dürfen idiomatisch gewählt werden. Es gibt keinen abstrakten
Renderer-Basistyp, keine Registry und keine Klasse mit mutablem Zustand.

`PublicationCandidates` enthält logisch:

```text
claude_md: bytes
agents_md: bytes
snapshot_artifact: bytes
publication_artifact: bytes
```

Alle Hashes und IDs werden aus den expliziten Modellen und erzeugten Bytes abgeleitet.
Der Caller darf weder `payload_hash`, `snapshot_hash`, `snapshot_id`, Output-Hash noch
Snapshot-Artifact-Hash als frei vertrauenswürdigen String einspeisen.

---

## 8. Root-Vertrag

Der Renderer konsumiert ausschließlich bereits durch §6 validierte Feature-04-Modelle.
Er prüft zusätzlich deren Cross-Bindungen:

- Payload-C0-Hash entspricht Snapshot-Constitution-Hash,
- Payload-Orientation-Hash entspricht Snapshot-Orientation-Hash,
- Payload-Modus ist `canonical`, `degraded` oder `safe_fallback`, nie `preview`,
- Snapshot-ID ist exakt `ctxsnap-v1:` plus berechnetem Snapshot-Hash,
- Repository-/Generator-/Constitution-Provenance stammt nur aus dem Snapshot.

Die Textprojektion ist bytegenau Feature 01 §7.2. C0 und Orientation werden unverändert
aus dem validierten Payload-Core eingesetzt. Source-Status und Observations werden nur
über `canonical_json_bytes()` gerendert. Kein Rohwert kontrolliert Marker, Überschriften,
Fences oder Labels.

Der Renderer erzeugt einen Bytepuffer und weist exakt dasselbe `bytes`-Objekt beiden
Consumerfeldern zu. Mindestens gilt `claude_md is agents_md`, nicht nur Bytegleichheit.
Damit gibt es im Default keine unbemerkte doppelte Renderausführung.

---

## 9. Envelope-Vertrag

### 9.1 Snapshot-Artifact

Der Builder erzeugt exakt:

```json
{
  "schema": "steward.context.snapshot-artifact/v1",
  "snapshot_id": "ctxsnap-v1:<snapshot_hash>",
  "snapshot_hash": "<snapshot_hash>",
  "snapshot": "<exact validated snapshot>"
}
```

Die Bytes sind `canonical_json_bytes(envelope)` ohne finalen LF. Der Artifact-Hash ist:

```text
sha256("steward-context-snapshot-artifact-v1\0" || snapshot_artifact_bytes)
```

Er enthält weder sich selbst noch Publication-Daten.

### 9.2 Publication-Artifact

Das innere `previous`-Objekt wird ausschließlich aus den berechneten Kandidatenbindungen
erzeugt und entspricht exakt `PreviousPublishedRecord v1`:

- Payload-/Record-Schema,
- berechneter Payload-Hash,
- berechnete Snapshot-ID,
- C0-Hash und geschlossener Modus,
- zwei identische berechnete Consumer-Hashes,
- Comparison-State aus dem validierten Snapshot.

Das äußere Envelope enthält exakt Feature 01 §8.2. Es bindet den berechneten
Snapshot-Artifact-Hash, Repository-/Generator-Commit, Constitution-Source-Evidence und die
festen drei Delivery-Ziele. Es enthält keinen Hash seiner eigenen Bytes und kein Target
für sich selbst. Die kanonischen JSON-Bytes besitzen keinen finalen LF.

### 9.3 Candidate-Validator

Der öffentliche Validator erhält die expliziten Payload-/Snapshot-Modelle und ein
`PublicationCandidates`-Objekt. Er:

1. validiert beide Modelle über §6,
2. baut die erwartete Generation deterministisch neu,
3. vergleicht alle vier Bytes exakt,
4. prüft Identität/Bytegleichheit der Consumer,
5. lehnt unbekannte Typen oder eine nicht-frozen Candidate-Struktur ab.

Er liest keinen Zustand und repariert nichts. Die spätere Publisher-Read-back-Phase darf
ihn mit den im Publish-Vorgang explizit gehaltenen Modellen wiederverwenden. Parser für
beliebige historische Git-Artefakte und Recovery bleiben ein späterer G2-Schnitt.

---

## 10. Red-Test-Reihenfolge

Vor Produktcode entsteht `tests/test_context_rendering.py`; nötige Validator-Regressionen
kommen in `tests/test_context_contract.py`. Der erste gezielte Lauf muss gegen den
aktuellen Code rot sein.

### Gruppe A — Öffentliche Feature-04-Modellvalidierung

- beide gemergten Golden-Modelle werden akzeptiert,
- bestehende Builderoutputs bleiben byte- und hashidentisch,
- unknown Top-Level-, Contract-, Source- und Observation-Felder blockieren,
- fehlende Keys und falsche Basistypen blockieren,
- C0-/Orientation-Hashmismatch blockiert,
- falsche Source-Reihenfolge, Trust-, Mode-, Status- oder Age-Bindung blockiert,
- Snapshot-Source nach `assembled_at` blockiert,
- Preview-Payload wird als Feature-04-Modell validiert, aber vom Renderer als kanonischer
  Kandidat blockiert,
- Fehler enthält nie injizierten Rohwert.

### Gruppe B — Root-Golden und Consumer-Default

- exakt 2318 UTF-8-Bytes,
- exakter Consumer-Hash `9519cfc...6e9d`,
- `agents_md is claude_md`,
- feste Marker und Blockreihenfolge genau einmal,
- LF-only, kein BOM, keine trailing Spaces, genau ein finaler LF,
- leeres Orientation-Markerpaar beim Golden-Modell,
- nichtleere Orientation wird unverändert zwischen feste Marker gesetzt,
- keine Publikationszeit und kein Consumer-Hashfeld im Root,
- Source-Status und Observations sind kompakte kanonische JSON-Bytes,
- Payload-/Snapshot-C0-, Orientation-, Modus- oder Provenance-Mismatch blockiert.

### Gruppe C — Snapshot-Envelope

- exakt 4781 kanonische Bytes ohne finalen LF,
- exakte Snapshot-ID und Snapshot-Hash-Bindung,
- exakter Artifact-Hash `fb6320ea...9ac3`,
- Snapshot-ID/Hash fließen nicht in den inneren Snapshot-Hash zurück,
- Mutation, unknown field, falsche ID oder nichtkanonische Serialisierung blockiert.

### Gruppe D — Publication-Envelope

- exakt 1203 kanonische Bytes ohne finalen LF,
- exakte PreviousPublishedRecord-Keys und Werte,
- identische berechnete Consumer-Hashes,
- exakte Comparison-State-Übernahme,
- feste Targets und kein Publication-Self-Target,
- Snapshot-Artifact-Hash bindet vollständige Snapshot-Envelope-Bytes,
- Mutation jedes Hashs, Targets, Source-Blobs oder Commits blockiert,
- keine Selbstzirkulation und kein Publication-Output-Hashfeld.

### Gruppe E — Adversarial und Purity

- Markdown-/Marker-/Fence-Injection in untrusted Modellfeldern blockiert bereits der
  Feature-04-Validator,
- bidi, zero-width, BOM, NUL, CRLF und ungültiges UTF-8 blockieren,
- Float, NaN, Infinity, unbekanntes Enum und übergroßer Count blockieren,
- mutable Candidate-Ersetzung kann keine frozen Struktur verändern,
- AST-/Import-Audit findet keine verbotene I/O-, Clock-, Git-, Netzwerk- oder
  Registry-Abhängigkeit,
- monkeypatchte `Path.open`, `open`, `subprocess.run`, Clock und ServiceRegistry werden
  bei vollständigem Kandidatenbau nie aufgerufen,
- Produktmodul enthält keinen `specs/`-Pfad,
- bestehende Root-Dateien und `.steward/` bleiben im Testcheckout unberührt.

---

## 11. Implementierungsreihenfolge

1. frischen Branch vom dann aktuellen `origin/main` erstellen,
2. Live-Head, offene PRs und vier Patchpfade erneut prüfen,
3. rote Validator-/Renderer-Tests anlegen und Fehlschlag protokollieren,
4. öffentliche Modellvalidatoren im bestehenden Contract-Modul ergänzen,
5. bestehende Builder auf dieselben Validatoren zurückführen,
6. frozen Candidate-Struktur und Root-Renderer implementieren,
7. Snapshot- und Publication-Envelopes implementieren,
8. deterministischen Candidate-Rebuild-Validator implementieren,
9. Golden-, adversariale und bestehende Feature-04-Tests grün machen,
10. repositoryweiten Format-, Lint- und vollständigen Testlauf ausführen,
11. AST-/Scope-/Import-/Diff-Audit durchführen,
12. regulären PR ohne Bypass prüfen und mergen.

Kein Schritt darf einen Caller oder Writer in den Patch ziehen.

---

## 12. Rückwärtskompatibilität und Rollback

Bestehende Feature-04-Builder, Hashfunktionen, Enums, Value Objects und Entscheidungen
behalten ihren Outputvertrag. Die Golden-Hashes müssen unverändert bleiben. Neue
Validatoren dürfen bestehende gültige Builderoutputs nicht ablehnen.

Der gesamte Slice ist ein reiner, unverdrahteter Code- und Testmerge. Rollback ist ein
normaler Revert des Slice-B-Mergecommits. Es existiert keine Runtime-, Root-, State- oder
Delivery-Migration zurückzunehmen.

Ein Revert darf nicht die bereits produktiv verifizierte Slice-A-Fence zurücknehmen.

---

## 13. Adversarialer Pre-Flight-Review

### 13.1 Zweites Modell

Ein neues Modul mit kopierten Source-IDs, Observation-Enums oder Hash-Domains würde
Feature 04 duplizieren. Deshalb bleiben rekursive Modellvalidatoren im bestehenden
Contract-Modul; der Renderer importiert nur dessen öffentliche API.

### 13.2 Validiert behauptete Dicts

Python-Mappings tragen keinen Herkunftstyp. Der Renderer darf nicht allein dem Kommentar
„bereits validiert“ vertrauen. Er ruft die öffentlichen rekursiven Validatoren selbst auf
und prüft Cross-Bindungen, bevor Bytes entstehen.

### 13.3 Hash-Selbsteingabe

Frei übergebene erwartete Hashstrings könnten falsche Modelle legitimieren. Alle IDs und
Hashes werden intern aus Modell oder Kandidatenbytes berechnet; der Caller liefert keine
Hashbehauptung.

### 13.4 Doppelte Consumer-Renderings

Zwei getrennte Renderaufrufe könnten später unbemerkt divergieren. Der Default verwendet
ein einziges `bytes`-Objekt für beide Candidate-Felder. Consumerabweichung bleibt ohne
Spec-Revision verboten.

### 13.5 Versteckter Writer

Ein „Candidate Builder“, der testweise Tempfiles oder Root-Preview schreibt, wäre bereits
Publisherlogik. Der Import-/Monkeypatch-Audit blockiert jede I/O-Wirkung.

### 13.6 Zu frühe Recovery

Der Rebuild-Validator vergleicht explizite In-Memory-Modelle mit Kandidaten. Er parst
keine beliebige historische Generation und repariert keinen Mischzustand. Git-Read-back,
Bootstrap und Recovery bleiben Schnitt D und dessen eigenem G2 vorbehalten.

Es bleibt kein identifizierter Architekturblocker für diesen engen reinen Slice. Neue
Live-Evidence kann die Entscheidung jederzeit widerlegen.

---

## 14. Abnahmekriterien

- [x] Slice A ist gemergt und produktiv verifiziert.
- [x] G1-Spec und Live-Head sind konkret gepinnt.
- [x] offene PRs und Main-Drift wurden geprüft.
- [x] Feature-04-APIs und bestehende Importgraphen sind inventarisiert.
- [x] Golden-Bytes und Hashes wurden am aktuellen Code erneut reproduziert.
- [x] erlaubte und verbotene Patchpfade sind exakt.
- [x] Modellvalidierung bleibt in der bestehenden Contract-Wahrheit.
- [x] Renderer-/Envelope-API ist klein, rein und zirkulationsfrei.
- [x] Red Tests decken Golden-, Cross-Binding-, Injection- und Purity-Grenzen.
- [x] kein Write, Caller, Source-Patch oder Aktivierungspfad ist erlaubt.
- [x] G2 stoppt bei neuem Main-Drift oder Parallelkonflikt.

---

## 15. Schlussstatus

Nach regulärem Merge dieses Dokuments ist ausschließlich folgender nächste Schritt
freigegeben:

> Einen frischen Implementierungsbranch vom aktuellen `origin/main` erstellen, zuerst die
> roten Slice-B-Validator-/Renderer-Tests anlegen und dann ausschließlich die vier
> erlaubten Produkt-/Testpfade bis zum hier definierten reinen Offline-Contract ändern.

Source-Migration, Publisher, Root-Mutation, Snapshot-/Record-Persistenz, Recovery,
Delivery, Runtime-State, Governance und Aktivierung bleiben gesperrt und benötigen ihre
eigenen späteren G2-Pre-Flights.
