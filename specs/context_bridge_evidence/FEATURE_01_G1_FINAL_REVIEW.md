# FEATURE 01 — FINALES G1-REVIEW

> **Status:** G1 APPROVED — CONTRACT COMPLETE; G2 UND AKTIVIERUNG BLEIBEN GESPERRT
> **Datum:** 2026-07-15
> **Reviewte Spec:** `specs/CONTEXT_BRIDGE_FEATURE_01.md` DRAFT 0.2
> **Code-Basis:** `kimeisele/steward@31651bfc52c98bb6be66d7adb6f3055cbc410388`
> **Späterer Live-Drift geprüft bis:** `66a3808205fb757a4c0a5a14eb1befdac24510e6`
> **Scope:** Adversariales Spec-Review. Keine Produkt-, Workflow-, Root- oder Settingänderung.

---

## 1. Urteil

DRAFT 0.2 ist als ausführbarer End-to-End-Vertrag G1-freigegeben. Die erste Reviewrunde
hatte echte Blocker gefunden; sie wurden nicht nur kommentiert, sondern in Sequenz,
Schemas, Testvektoren und Gategrenzen zurückgeführt.

G1 bedeutet hier:

- Architektur und Sicherheitsverträge sind hinreichend präzise für kleine G2-Pre-Flights,
- kein Mega-Patch ist erlaubt,
- keine Implementierung startet automatisch,
- kein kanonischer Root-Publish ist aktiviert,
- keine GitHub-Governance-Precondition wird als erfüllt dargestellt.

---

## 2. Geschlossene Reviewblocker

### 2.1 Source-Reihenfolge

Die unsichere Reihenfolge „Source zuerst“ ist verworfen. Der Vertrag verlangt nun:

1. Legacy-Writer-/LLM-/Git-NADI-Fence,
2. reinen Renderer und Offline-Contract,
3. getrennte reviewte Constitution-Migration,
4. lokalen Publisher disabled,
5. nachgelagerten attestierten Bootstrap.

Damit kann der heutige `OrientationStage` neue Source-Marker nicht automatisch in eine
Legacy-Root-Datei spiegeln.

### 2.2 Hash- und Artifact-Domains

Snapshot und Publication besitzen getrennte versionierte Envelopes. Kein Hash umfasst
sich selbst. Das innere `PreviousPublishedRecord` bleibt exakt Feature-04-kompatibel.
Snapshot-, Payload-, Consumer-Output- und Snapshot-Artifact-Domains sind getrennt.

### 2.3 Deterministischer Root-Vertrag

Die Root-Projektion besitzt feste Marker, Labels, JSON-Fences, Whitespace und finalen LF.
Dynamische Werte stammen ausschließlich aus Feature-04-Canonical-JSON. C0 und Orientation
werden nicht im dynamischen JSON dupliziert. Beide Consumer erhalten standardmäßig exakt
denselben Bytepuffer.

Der normative Vektor wurde mit Python und Ruby unabhängig reproduziert:

```text
Root bytes: 2318
Consumer hash: 9519cfc5867580d041ef7d01c6007a35e7d98b51d559c08b6b941940fcbb6e9d
Snapshot artifact bytes: 4781
Snapshot artifact hash: fb6320ea4e8dd3d2fd8c009d920396c9e5db73aa4403027b5fae2ca3d3719ac3
Publication artifact bytes: 1203
```

### 2.4 Raw-Source-Grenze

Der V1-Adapter konsumiert genau ein Raw-Assembly-Objekt. Legacy-`{}`/`[]` wird ohne
positiven Readbeweis `unavailable/provenance_missing`, nie gesund leer. Normalizerfehler
werden geschlossen typisiert; unerwartete interne Exceptions blockieren. Untrusted
Session-/Task-/Issue-Prosa gelangt nicht in Snapshot oder Payload.

### 2.5 Attestation

`reviewed_at_commit` ist der reviewte Constitution-PR-Head und keine selbstreferenzielle
Merge-/Bootstrap-SHA. Ein commitgebundener Required Check
`Context Constitution Attestation` prüft Review-, Code-Owner-, stale-review-,
Branchschutz- und Blob-Evidence. Der Bootstrap-Resolver verlangt dessen Erfolg sowie
exakte PR-, Review-, Commit- und Source-Daten.

Die aktuellen selbst erstellten/selbst gemergten PRs ohne Reviews werden ausdrücklich
nicht als positive Attestation umgedeutet.

### 2.6 Atomicity und Recovery

Der Vertrag verspricht nur per-Datei Atomic Replace, Mixed-Generation-Erkennung,
Record-last, vollständigen Read-back und gemeinsame Git-Delivery. Unbekannte manuelle
Root-Edits werden nicht als Crash-Recovery überschrieben. HEAD-/Target-Drift blockiert.
Safe Fallback benötigt vollständig gebundene frühere C0-Bytes, nicht nur einen Hash.

### 2.7 Runtime-State

Context-PR, `main` und vollständiger öffentlicher State-Branch sind als Full-State-Store
verworfen. Die Zieltopologie trennt:

- vier PUBLIC_SAFE Context-Artefakte im Context-PR,
- öffentlichen Cross-Repo-Transport im bestehenden Federation-Hub,
- minimalen privaten Restart-Checkpoint in einer eigenen Feature-Spec,
- rekonstruierbare Diagnose ohne dauerhafte Main-Persistenz,
- statische öffentliche Registrydaten als reviewten Main-Bestand.

Damit wird Raw-Memory/-Session/-Federation-State nicht durch einen vermeintlich bequemen
gemeinsamen PR in die Context-Governance eingeschleust.

### 2.8 Migrationscheck

`Context Bridge Contract` besitzt P0/P1/P2/P3-Zustände, die ausschließlich aus Base-/Head-
Tree und geschützter Policy abgeleitet werden. Dadurch kann der Check vor Bootstrap
required sein, ohne Legacyzustand als dauerhaft gültig zu erklären oder den Source-
Bootstrap zu deadlocken.

---

## 3. Konkrete Operationsidentität

Festgelegt sind:

```text
Policy: .github/context-bridge-policy.json
Runtime key: CONTEXT_BRIDGE_RUNTIME_MODE
Branch: automation/context-bridge
PR title: [context-bridge] canonical context publication
PR marker: <!-- steward-context-delivery:v1 -->
Contract check: Context Bridge Contract
Constitution check: Context Constitution Attestation
Workflow: Context Bridge Delivery
```

Policy und Runtime bilden eine Herabstufungsmatrix. Fehlend/ungültig ist `disabled`.
Runtime kann Repository-Policy nie hochstufen.

---

## 4. Bewusst nachgelagerte Gates

Folgende Punkte widerlegen G1 nicht, blockieren aber ihre jeweilige spätere Phase:

1. Jeder Code-Schnitt benötigt einen eigenen aktuellen G2-Pre-Flight.
2. Bootstrap benötigt Crash-/Absent-/Mixed-/Invalid-Fixtures und reale Attestation.
3. Runtime-State benötigt eine eigene Store-/Migration-/Credential-Spec vor Aktivierung.
4. Canonical Activation benötigt einen echten zweiten Human-Principal/Code Owner.
5. Branchschutz, Required Checks, Variable, Auto-Merge und Kill-Switch müssen vor
   Activation real gesetzt und gedrillt werden.

Keiner dieser Punkte darf durch Admin-Bypass, Self-Approval, Federation-Identität oder
Chat-Prosa simuliert werden.

---

## 5. Scope- und Formalaudit

- ausschließlich neue Spec-/Evidence-Dateien,
- keine Änderung an Produktcode, Tests, Workflow, Root-Dateien, Constitution oder Settings,
- JSON-Vektor syntaktisch valide,
- Markdown-Fences ausgeglichen,
- `git diff --check` ohne Befund,
- Feature-04-Modell-/Hashcode wird konsumiert und nicht dupliziert,
- Phase 1 bleibt unverändert.

---

## 6. G2-Grenze

G1 autorisiert nicht den gesamten Feature-01-Patch. Als nächstes ist ausschließlich ein
Spec-/Evidence-Commit zulässig:

> G2-Pre-Flight für Schnitt A — Legacy-Writer-Fence — auf aktuellem `origin/main`.

Dieser Pre-Flight muss exakte Produkt-/Testpfade, alte Caller, Red-Tests, Compatibility,
Deploymentwirkung und Revert benennen. Source-Migration, neuer Publisher, Root-Writes,
Delivery, Runtime-State und GitHub-Settings bleiben darin verboten.

---

## 7. Schlussstatus

Feature 01 ist **G1 APPROVED**. Implementierung ist **nicht** pauschal freigegeben.
Canonical Publication und Aktivierung bleiben **OFF** bis alle separaten G2- und
Governance-Gates bestanden sind.
