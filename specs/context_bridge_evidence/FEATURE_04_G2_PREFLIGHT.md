# FEATURE 04 — G2-PRE-FLIGHT

> **Status:** G2 START APPROVED — nur reine Contract-Bibliothek und isolierte Tests
> **Datum:** 2026-07-15
> **Produktionsbasis:** `kimeisele/steward@44b318408ebd1e73731d38c0c11f241d13761b08`
> **Produktions-Tree:** `9b939049fea5509f2b9d23ca29469ec0a0956f29`
> **Feature-Spec:** `specs/CONTEXT_BRIDGE_FEATURE_04.md` — G1 APPROVED
> **G1-Review:** `specs/context_bridge_evidence/FEATURE_04_G1_REVIEW.md`
> **Scope:** Pre-Flight und Startentscheid; noch keine Produktcodeänderung

---

## 1. Entscheidung

Der G2-Start für Feature 04 ist freigegeben, sobald dieses Pre-Flight-Dokument auf
`main` gemergt und der Implementierungsbranch erneut vom dann aktuellen `origin/main`
erstellt wurde.

Die Freigabe ist absichtlich eng:

- ein neues reines Contract-Modul,
- eine neue isolierte Testdatei,
- Nutzung des bereits gemergten Hashvektors,
- keine produktive Integration.

Ein grüner Feature-04-Patch beweist nur die reine Modellbibliothek. Er publiziert keinen
Context und verändert keinerlei Laufzeitverhalten.

---

## 2. Live-Head und Parallelitätsprüfung

Am gepinnten Head:

- `specs/CONTEXT_BRIDGE_FEATURE_04.md` und G1-Evidence sind auf `main`,
- `steward/context_contract.py` existiert nicht,
- `tests/test_context_contract.py` existiert nicht,
- es gibt keinen offenen PR,
- kein paralleler Branch implementiert laut sichtbarem PR-Stand dieselbe Fläche,
- bestehende Writer-/Renderer-/MTime-Pfade sind unverändert und bleiben außerhalb Scope.

Der Implementierungsagent muss diese Aussagen unmittelbar vor dem ersten Patch erneut
prüfen. Neue Überschneidung stoppt G2.

---

## 3. Exakte Patchpfade

Zulässig:

```text
steward/context_contract.py
tests/test_context_contract.py
```

Als read-only Testfixture zulässig:

```text
specs/context_bridge_evidence/FEATURE_04_HASH_VECTORS.json
```

Die Fixture wird nicht kopiert. Tests lesen den gemergten normativen Vektor. Produktcode
kennt den `specs/`-Pfad nicht.

Jeder weitere Produkt- oder Testpfad benötigt einen dokumentierten Stop und neue
G2-Review. Insbesondere ist auch ein vermeintlich kleiner Export in `steward/__init__.py`
vorläufig nicht nötig und daher verboten.

---

## 4. Ausdrücklich verbotene Pfade

Nicht verändern:

```text
CLAUDE.md
AGENTS.md
.steward/**
.github/**
steward/briefing.py
steward/briefing_stages.py
steward/context_bridge.py
steward/hooks/**
steward/intent_handlers.py
steward/__main__.py
steward/tools/synthesize_briefing.py
```

Ebenfalls verboten:

- Root-Writes oder Dateisystem-I/O im neuen Modul,
- Git-, GitHub-, Netzwerk-, Environment- oder ServiceRegistry-Zugriffe,
- aktuelle Uhrzeit innerhalb der Contract-Funktionen,
- globaler mutabler Vergleichsstate,
- Writer-/Heartbeat-Wiring,
- `.context_hash`-Migration,
- C0-Source-Migration,
- LLM-Pfadänderung,
- Task-, Issue- oder Continuity-Inhalte,
- neue Runtime-Abhängigkeit.

---

## 5. Minimale API-Fläche

Das neue Modul darf ausschließlich diese logischen Fähigkeiten bereitstellen; konkrete
Python-Namen dürfen minimal angepasst werden, müssen aber im Review auf diese Liste
zurückgeführt werden:

1. geschlossene Enums für SourceStatus, TrustZone, OutputMode und Decision,
2. frozen Value Objects für ParsedConventions, SourceResult,
   ConstitutionAttestation, PreviousPublishedRecord und ContractDecision,
3. `parse_conventions(source: bytes)` ohne Pfadzugriff,
4. Basistyp-/NFC-/PUBLIC_SAFE-Validierung,
5. `canonical_json_bytes(value)` für bereits validierte Modelle,
6. domain-separierte Snapshot-/Payload-/Consumer-Hashes,
7. reine Normalisierung der in V1 erlaubten Beobachtungsaggregate,
8. reine Vergleichsentscheidung gegen expliziten PreviousPublishedRecord.

Die Implementation darf interne kleine Helfer besitzen. Sie darf keine generische
Framework-, Plugin-, Registry- oder Publisher-Abstraktion einführen.

---

## 6. Red-Test-Reihenfolge

Vor Produktcode werden in `tests/test_context_contract.py` wirkungsbezogene Tests
hinzugefügt. Der erste Lauf muss wegen fehlendem Modul oder fehlenden Symbolen rot sein.
Danach werden die Tests in kleinen Gruppen grün gemacht.

### Gruppe A — Marker und Basistypen

- exaktes C0/Orientation-Parsing,
- CRLF-Normalisierung und genau ein finaler LF,
- fehlende, doppelte, verschachtelte, vertauschte und unbekannte Marker blockieren,
- 4096/4097- und 32768/32769-Byte-Grenzen,
- ungültiges UTF-8, BOM, NUL, bidi, zero-width und Zeilentrenner blockieren,
- Float, Boolean-als-Integer, NaN, Infinity, negative/übergroße Counts blockieren.

### Gruppe B — PUBLIC_SAFE und Default-Deny

- Secret-/Token-/PEM-Fixtures,
- POSIX-, Windows- und UNC-Absolutpfade,
- private URL/Userinfo,
- Marker/Markdown in Identifierfeldern,
- verworfener Rohwert fehlt in Exceptiontext und Modell,
- untrusted Issue-/Task-/Sense-Prosa gelangt nicht in Snapshot/Core.

### Gruppe C — Kanonisierung und Hashes

- Canonical-JSON-Basisvektor,
- vollständiger Snapshot-Hash,
- vollständiger Payload-Hash,
- gleiche Menge bei anderer Eingabereihenfolge,
- NFC-Äquivalenz, keine NFKC-Faltung,
- Snapshotzeit ändert Snapshot-Hash, aber nicht Payload-Hash,
- Generator-Commit ändert Snapshot-Hash, aber nicht Payload-Hash,
- Consumer-Hash ist domainsepariert und voll.

### Gruppe D — Normalisierung

- Health-Grenzen exakt bei 0.3, 0.5, 0.7 und 0.8,
- Guna-Inkonsistenz invalid,
- Provider-Ratio `0`, zwischen `0/1`, `1`,
- Sense-Pain-Grenzen und feste Sense-Allowlist,
- Federation-Priorität dead vor suspect vor alive vor empty,
- unbekannte Federationstatus invalid,
- Gateway-/Rollback-Delta, Bootstrap und Counter-Rückgang,
- Campaign-/Gap-Allowlist und deterministische Sortierung,
- cached bleibt stale und trägt keine Beobachtung.

### Gruppe E — Vergleichsentscheidung

- fehlende/abweichende C0-Attestation -> manual_review/blocked,
- identischer Payload über Prozessneustart -> no_op,
- C1/C2/C3-Core-Wechsel -> publish,
- reine C4-Änderung -> no_op,
- C0-Wechsel -> manual_review,
- Preview -> kein kanonischer Publish,
- ungültiger PreviousPublishedRecord -> blocked,
- alle Safety-Gruppen unbrauchbar -> safe_fallback nur mit verifiziertem C0.

---

## 7. Implementierungsreihenfolge

1. roten Test-Skeleton-Commit erstellen und Fehlschlag dokumentieren,
2. Enums, Fehler und frozen Value Objects,
3. Marker-/Textvalidator,
4. kanonische Serialisierung und feste Hashvektoren,
5. Source-/Observation-Normalisierung,
6. Compare-/No-op-Entscheidung,
7. gezielte Tests vollständig grün,
8. gesamte bestehende CI-Matrix,
9. Scope-/Diff-/Import-Audit,
10. PR ohne Bypass mergen.

Kleine Implementierungscommits sind erlaubt. Keine Gruppe zieht einen Caller in den
Patch.

---

## 8. Abnahmekriterien

- [x] G1-Spec ist auf `main` und auf einem konkreten Live-Head gepinnt.
- [x] neue Modul-/Testpfade sind frei.
- [x] erlaubte und verbotene Patchpfade sind exakt.
- [x] Red Tests sind wirkungsbezogen und nach Gruppen geordnet.
- [x] Produktive Integration bleibt vollständig außerhalb Scope.
- [x] Hashvektor ist bereits gemergt und kreuzgeprüft.
- [x] keine zusätzliche Runtime-Abhängigkeit ist nötig.
- [x] G2 kann durch einen neuen Main-Drift oder Pfadkonflikt fail-closed stoppen.

---

## 9. Schlussstatus

Nach Merge dieses Dokuments ist der nächste erlaubte Schritt:

> Freshen Implementierungsbranch vom aktuellen `origin/main` erstellen, exakt die rote
> Testdatei hinzufügen, den erwarteten Fehlschlag belegen und anschließend ausschließlich
> `steward/context_contract.py` implementieren.

Feature 01 und jede produktive Context-Publikation bleiben gesperrt.
