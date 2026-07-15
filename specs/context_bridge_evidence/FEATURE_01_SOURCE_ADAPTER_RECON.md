# FEATURE 01 — RAW-SOURCE-ADAPTER RECON

> **Status:** EVIDENCE COMPLETE — V1-ADAPTERVERTRAG ENTSCHEIDEN
> **Datum:** 2026-07-15
> **Code-Basis:** `kimeisele/steward@31651bfc52c98bb6be66d7adb6f3055cbc410388`
> **Scope:** Read-only Assembly-, Reader- und Feature-04-Kompatibilitätsprüfung

---

## 1. Problem

Feature 04 verlangt typisierte `SourceResult`-Objekte mit explizitem Status, Trust-Zone,
Source-Modus, Provenance und Fehlercode. Der bestehende `assemble_context()` liefert
dagegen ein untypisiertes Dictionary. Fast alle Reader fangen breite Exceptions und geben
`{}` beziehungsweise `[]` zurück.

Damit sind im Legacy-Output nicht unterscheidbar:

- erfolgreich gelesen und fachlich leer,
- Service nicht gebootet,
- Quelle nicht konfiguriert,
- Parser-/Schemafehler,
- I/O-/API-/Timeoutfehler,
- Readerexception.

Eine leere Collection ist deshalb **kein** Beweis für `empty` oder `valid`.

---

## 2. Positive Beweise

### 2.1 Doppelassembly

MOKSHA assembliert Raw-Context für `.steward/context.json`. Der heutige Root-Writer ruft
danach `assemble_context()` erneut auf. Feature 01 muss den bereits einmal erfassten,
gegebenenfalls um Live-Vedana ergänzten Raw-Snapshot konsumieren.

### 2.2 Reader-Collapse

`_read_senses`, `_read_health`, `_read_gaps`, `_read_sessions`, `_read_tasks`,
`_read_federation`, `_read_immune`, `_read_campaign` und `_read_cetana` fangen Fehler und
geben leere Mappings zurück. `_read_github_issues` gibt bei Timeout, fehlendem `gh`,
JSON-Fehler, nonzero Exit oder echter Leere dieselbe leere Liste zurück.

### 2.3 Health-Fallback

Der Provider-only-Fallback von `_read_health()` enthält `source=provider_only`, aber keinen
`provider_health`-Wert. `normalize_health()` akzeptiert dieses Schema absichtlich nicht.
Der Adapter darf den Fallback weder ergänzen noch als valid umetikettieren; er wird
`unsupported`/`invalid` und führt zu sichtbarer Degradation.

### 2.4 Feature-04-Grenze

Feature 04 normalisiert nur die V1-Participating-Sources:

```text
constitution, orientation, repository, context_schema,
health, senses, gaps, federation, immune, campaign, cetana
```

Sessions, Tasks, Issues, Architecture, Annotations und Continuity erscheinen in V1 nur
als Source-Provenance; ihre Rohwerte werden weder in Snapshot noch Payload gespeichert.

---

## 3. V1-Adaptervertrag

### 3.1 Input

Der Adapter ist rein und erhält explizit:

- genau ein bereits assembliertes Raw-Context-Mapping,
- ein nach Abschluss der Assembly vom Caller erzeugtes kanonisches `assembled_at`,
- ParsedConventions und ConstitutionAttestation,
- Repositoryname, Repository-Head und Generator-Commit,
- einen validierten vorherigen Publication Record oder `None`.

Er liest keine Datei, Uhr, Registry, Environmentvariable, Git- oder Netzwerkquelle und
ruft keinen Reader erneut auf.

### 3.2 Assembly-Zeit

Das heutige Raw-Feld `timestamp` wird nicht als Source- oder Publication-Provenance
übernommen. Es wird vorerst nur als Legacy-Diagnose validiert oder verworfen. Der Caller
erfasst `assembled_at` **nach** dem letzten Raw-Read und der Live-Vedana-Injection. Alle in
dieser synchronen Assembly erfolgreich gelesenen Live-Quellen erhalten für V1 denselben
`observed_at=assembled_at`-Grenzwert.

Das behauptet keine atomare Weltbeobachtung, aber garantiert `observed_at <= assembled_at`
und verhindert einen zweiten Snapshot.

### 3.3 Statusableitung

Für jede Participating-Source gilt:

1. Key fehlt, Wert `{}`/`[]` oder Werttyp falsch -> `unavailable` mit
   `error_code=provenance_missing`, `value=None`.
2. Normalizer erfolgreich -> `valid`, `age_bucket=fresh`, normalisierte Observation.
3. `ContractViolation(code="unsafe_content")` -> `unsafe`.
4. `ContractViolation(code="unsupported_version")` -> `unsupported`.
5. andere `ContractViolation` -> `invalid`.
6. unerwartete interne Exception -> Publisher `blocked`; sie wird nicht in einen
   Sourcefehler umetikettiert.

`empty` wird in V1 für einen Legacy-Reader nur gesetzt, wenn dessen nichtleeres Envelope
einen erfolgreichen Read und fachliche Leere positiv beweist. Ein nacktes `{}` oder `[]`
genügt nie.

### 3.4 Statische/abgeleitete Quellen

- `constitution`: `valid/static/fresh` nur nach Parser und Attestation.
- `orientation`: `valid/static/fresh` bei Payload, sonst `empty/static/fresh` aufgrund des
  erfolgreichen Source-Parsers.
- `repository`: `valid/derived/fresh` nur bei validem Name/Head.
- `context_schema`: `valid/derived/fresh` nur für exakt unterstützte V1-Schemata.

### 3.5 Nicht teilnehmende Quellen

- `sessions`, `tasks`, `issues`: `valid/live/fresh` nur wenn das vorhandene Legacy-
  Envelope einen erfolgreichen Read positiv erkennen lässt; sonst `unavailable` mit
  `provenance_missing`.
- `architecture`, `annotations`, `continuity`: bis zu ihren eigenen Features
  `not_configured` mit `value=None`.

Ihre Rohtexte werden nie an `build_snapshot()` oder `build_payload_core()` übergeben.

### 3.6 Comparison-State

Gateway- und Rollback-Counter werden ausschließlich aus den normalisierten Federation-/
Immune-Inputs sowie dem vorherigen Record gebildet. Fehlt bei einem nichtzero Counter die
erforderliche Baseline, bleibt die jeweilige Delta-Klasse `unknown`; ein Counterrückgang
ist `invalid` und kein Reset auf gesund.

---

## 4. Output und Modus

Der Adapter liefert:

- vollständige Mapping aller 17 `SourceResult`-Objekte,
- exakt sieben `NormalizedObservations`-Sektionen,
- neuen Comparison-State,
- durch `derive_output_mode()` bestimmten Modus oder `blocked`,
- keine gerenderte Datei und keine persistente Nebenwirkung.

Wenn alle vier Safety-Gruppen `health`, `federation`, `immune`, `cetana` unbrauchbar sind,
ist normaler canonical/degraded Output unmöglich. `safe_fallback` ist nur mit zuvor
verifiziertem C0 erlaubt. Ist wenigstens eine Safety-Gruppe brauchbar, aber nicht alle,
entsteht `degraded` und jede fehlende Quelle bleibt sichtbar.

---

## 5. Spätere Reader-Härtung

Der konservative Adapter verhindert falsche Gesundheit, repariert aber die
Informationsvernichtung der Legacy-Reader nicht. Ein späterer, eigener Schnitt darf Reader
auf typisierte Ergebnisse umstellen. Dabei müssen bestehende Runtime-Caller migriert und
Fehlerklassen getestet werden.

Feature 01 darf diese größere Reader-Neuarchitektur nicht als Voraussetzung für den ersten
sicheren Publisher erzwingen. Es akzeptiert lieber sichtbare Degradation als erfundene
Source-Semantik.

---

## 6. Tests

- genau ein Assembly-Objekt wird an alle Normalizer weitergereicht,
- Mutation des Raw-Mappings nach Adaptereintritt beeinflusst das Ergebnis nicht,
- `{}`/`[]` wird nie `valid` oder `empty` ohne positives Envelope,
- Provider-only-Health wird nicht künstlich ergänzt,
- jede `ContractViolation`-Klasse mappt exakt,
- unerwartete Exception blockiert,
- untrusted Session-/Task-/Issue-Prosa fehlt vollständig in Snapshot/Payload,
- `assembled_at` liegt nicht vor einer behaupteten Source-Beobachtung,
- Counterbootstrap, Delta und Rückgang entsprechen Feature 04,
- alle 17 Source-Identifier sind exakt einmal vorhanden.

---

## 7. Gate-Wirkung

- Die V1-Assembly-/SourceResult-Grenze ist entschieden.
- Kein zweites `assemble_context()` ist zulässig.
- Leere Legacy-Werte sind default-unavailable, nicht gesund leer.
- Eine größere Reader-Härtung bleibt separates späteres Feature.
- Keine Produktcodeänderung ist durch dieses Evidence-Paket freigegeben.
