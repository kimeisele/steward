# FEATURE 01 / SCHNITT C — G2-PRE-FLIGHT

> **Status:** G2 EVIDENCE COMPLETE — IMPLEMENTIERUNGSSTART BLOCKIERT
> **Datum:** 2026-07-15
> **Repository:** `kimeisele/steward`
> **Gepinnter Main:** `12d043467cde783088e8cda041696348e31d1be9`
> **Gepinnter Tree:** `a14ed5ebf312c8654f9be060629b83dbe15cf442`
> **Scope:** Read-only Constitution-, Git-, GitHub- und Testvertragsrecon

## 1. G2-Entscheidung

Schnitt C darf am gepinnten Stand **nicht implementiert oder gemergt** werden.

Der Source-Kandidat und sein Testvertrag sind deterministisch geschlossen. Zwei externe
Preconditions sind jedoch positiv als unerfüllt bewiesen:

1. Es existiert kein anderer menschlicher Repository-Principal, der den Source-PR auf
   exakt seinem finalen Head reviewen kann.
2. Der für eine spätere `ConstitutionAttestation(status="verified")` verpflichtende,
   commitgebundene Check `Context Constitution Attestation` existiert nicht auf der
   geschützten Base. Ebenso fehlen CODEOWNERS, Reviewschutz, stale-review dismissal und
   Admin-Enforcement.

Ein heute gemergter Source-PR könnte deshalb später nicht als die in Feature 01 §6.3
definierte Attestation-Evidence verwendet werden. Ihn trotzdem zu mergen und später erneut
zu migrieren wäre kein chirurgischer Zwischenschritt, sondern eine bewusst wertlose
Governance-Generation.

G2 ist damit nicht „untersucht, aber unklar“, sondern fail-closed entschieden:

```text
recon = complete
implementation_start = blocked
source_pr = forbidden
```

## 2. Gepinnter Ist-Zustand

### 2.1 Source und Root

```text
.steward/conventions.md blob: 29829be4f77dcaebf970a8ee872de299f0357f1c
.steward/conventions.md bytes: 5415
CLAUDE.md blob:              8146a15603c95e5aa1404c9eb7021e3008914b0c
AGENTS.md:                   absent
context snapshot/record:     absent
```

Die Source besitzt weder C0- noch Orientation-Marker. Sie beginnt mit einer Runtime-
Persona und behauptet, verbatim in `CLAUDE.md` übernommen zu werden. Seit Schnitt A ist
letzteres produktiv falsch: Der Legacy-Root-Writer ist fail-closed und kein produktiver
Caller schreibt Root-Context.

### 2.2 GitHub-Governance

Live über die GitHub-API beobachtet:

```text
Repository visibility:              public
Authenticated principal:            kimeisele
Collaborators insgesamt:            1
Collaborator mit Admin/Push:         kimeisele
Offene Collaborator-Einladungen:     0
Required PR reviews auf main:        absent
CODEOWNERS:                          absent
Rulesets:                            absent
enforce_admins:                      false
Required checks:                     Python 3.11, Python 3.12, Lint
Context Constitution Attestation:    absent
```

Die Reviews-API lieferte für die untersuchten PRs `#497`, `#498`, `#499`, `#505`, `#532`,
`#533`, `#539`, `#541`, `#547` und `#548` jeweils eine leere Reviewliste. Diese Merges sind
technische Evidence, aber kein separater Human-Reviewbeweis.

Git-Commit-Autorname, PR-Merger, Chat-Reviewer, Coding-Agent oder Federation-Peer ersetzen
keinen GitHub-Review-Principal. Der GitHub-API-User ist die Autoritätsgrenze.

## 3. Normative Source-Wahrheit

Die spätere Source besitzt genau eine manuell reviewte Datei und zwei statische Klassen:

1. C0-v1 aus `specs/CONTEXT_BRIDGE_FEATURE_00.md` §7,
2. optional komprimierbare Orientation.

Sie darf keine dritte Persona-/Policy-Datei, keinen dynamischen Root-Block und keinen aus
Chat, Runtime, Issue, Task oder LLM rekonstruierten Operatorauftrag einführen.

### 3.1 Blockweise Klassifikation der alten Source

| Alter Block | Entscheidung für V1 | Begründung |
|---|---|---|
| Kopfkommentare | entfernen | Freitext außerhalb der Marker ist parserwidrig; „verbatim generated“ ist überholt |
| `Identity` | vollständig ersetzen | `You are Steward` und `Your North Star` impersonieren den Runtime-Agenten |
| `Cognitive Pipeline` | nicht übernehmen | optional; einzelne Call-Sites existieren, der Gesamttext ist nicht Teil des C0-Vertrags |
| `Heartbeat` | nicht übernehmen | feste Frequenzen sind volatile Runtimewerte; MURALI-Beschreibung ist für C0 unnötig |
| `Substrate Primitives` | nicht übernehmen | teils externe Implementierung, teils imperative Architekturpräferenz |
| `Federation` | nicht übernehmen | Peer-, Slot- und Flushzahlen sind volatile Betriebs-/Konfigurationswerte |
| `Safety Gates` | nicht übernehmen | C0 enthält die dauerhaften Sicherheitsgrenzen bereits consumerkorrekt |
| `Self-Healing` | nicht übernehmen | mehrere optionale/fallbackende Implementierungen; kein Verfassungstext |
| `Key Directories` | nicht übernehmen | Pfade sind technisch belegt, aber optionale und driftende Orientation |
| `Invariants` | nicht übernehmen | gemischte technische Behauptungen und imperative Regeln ohne Einzelattestation |
| `Development` | nicht übernehmen | Befehle sind nützlich, aber keine Constitution; aktuelle CI ist enger gescoped |

Das ist keine Behauptung, alle alten Architekturhinweise seien falsch. Es ist eine
Default-deny-Entscheidung: Keine optionale Altprosa wird allein wegen Nützlichkeit in die
erste attestierte Governance-Generation übernommen.

### 3.2 Orientation-Entscheidung

Der V1-Source-Kandidat verwendet das versionierte Orientation-Markerpaar mit leerem
Payload. Das ist durch `parse_conventions()` positiv unterstützt und entspricht dem
gemergten Feature-01-Publication-Golden.

Vorteile:

- keine ungeprüfte Runtime- oder Dependency-Architektur wird attestiert,
- keine zweite manuelle Wahrheit entsteht,
- spätere verifizierte Orientation kann einen eigenen reviewten Source-Wechsel auslösen,
- C0 und Consumerrolle werden nicht von optionaler Orientierung abhängig.

Eine fehlende oder leere Orientation bedeutet nicht, dass Fresh-Session-Continuity
entfällt. Der C0 verweist ausdrücklich und sicher auf Phase 1 und den falsifizierbaren
Phase-2-Arbeitsstand. Feature 02 bleibt der getrennte Vertrag für aktuelle Orientierung.

## 4. Exakter Kandidat und unabhängige Reproduktion

Der Kandidat wird nicht frei formuliert. Er entsteht mechanisch aus:

```text
C0_BEGIN
exact Feature 00 §7 markdown payload
C0_END
blank line
ORIENTATION_BEGIN
ORIENTATION_END
final LF
```

Unabhängig mit dem gemergten Parser, `hashlib.sha256` und `git hash-object --stdin`
reproduziert:

```text
C0 UTF-8 bytes:       1860
C0 SHA-256:           f23ab40415edf4947f12fd8ff98cf13aa8f4fbfffe029ae10aa6111fc04976a3
Source UTF-8 bytes:   2023
Source SHA-256:       0afe95c392ba611ad40302e13a5d013913fca1910423fe4ea18c663cd780aff5
Expected Git blob:    f428d5856a5c525e002c301890777748effbeb4e
Orientation payload:  empty string
Orientation version:  orientation/v1
Encoding:             UTF-8, LF-only, no BOM, exactly one final LF
```

Der Source-Git-Blob ist ein Kandidatenwert, noch keine Attestation. Erst ein anderer
menschlicher Reviewer auf dem finalen Source-PR-Head und der commitgebundene geschützte
Check könnten ihn zu externer Bootstrap-Evidence machen.

## 5. Hypothetischer Patchscope nach Aufhebung des Blocks

Erlaubt wären ausschließlich:

```text
.steward/conventions.md
tests/test_context_constitution.py
```

`tests/test_context_constitution.py` ist neu. Es liest ausschließlich die echte Source und
die normative Feature-00-Spec. Es dupliziert den C0-Wortlaut nicht.

Jeder weitere Pfad stoppt den Source-PR. Insbesondere verboten:

```text
CLAUDE.md
AGENTS.md
.steward/context-snapshot.json
.steward/context-publication.json
steward/**
.github/**
docs/**
specs/**
data/**
```

Der Source-PR darf keinen Workflow, CODEOWNERS, Branchschutz, Attestation-Resolver,
Publisher, Writer, Root-Output, Runtime-State oder Deliverypfad nebenbei einführen.

## 6. Roter Testvertrag

Vor einer späteren Sourceänderung entsteht der neue Test. Gegen den heutigen Blob muss er
rot sein, weil Marker und exakter C0 fehlen.

Der grüne Vertrag prüft mindestens:

1. `parse_conventions()` akzeptiert die echten Source-Bytes.
2. C0 ist bytegleich mit dem exakt aus Feature 00 §7 extrahierten Markdownblock.
3. C0-Hash, Source-Länge, Source-SHA und Git-Blob entsprechen §4.
4. Orientation ist exakt leer und versioniert als `orientation/v1`.
5. Kein nichtleerer Text steht außerhalb der Marker.
6. Kein Dynamic-Marker befindet sich in der Source.
7. Die alten Phrasen `You are Steward`, `Your North Star`, `0.1Hz`, `0.5Hz`, `2Hz` und
   `write CLAUDE.md` fehlen.
8. CR, BOM, NUL, bidi/zero-width, doppelter oder verschachtelter Marker blockieren.
9. `CLAUDE.md` bleibt exakt der Base-Blob; `AGENTS.md` bleibt absent.
10. Der PR-Diff enthält nur die zwei erlaubten Pfade.

Punkte 9 und 10 sind PR-/Git-Contract-Prüfungen, keine bloßen Unit-Assertions.

## 7. Review- und Attestation-Gate

Ein späterer Source-PR ist nur zulässig, wenn vor Brancherstellung positiv belegt ist:

1. mindestens ein anderer vertrauenswürdiger menschlicher Collaborator besitzt die
   erforderliche Reviewrolle,
2. `.steward/conventions.md` und der Contract-Test sind durch CODEOWNERS geschützt,
3. `main` verlangt PR-Review, Code-Owner-Review und stale-review dismissal,
4. Admin-Bypass ist für diesen Pfad ausgeschlossen,
5. der aus geschützter Base stammende Check `Context Constitution Attestation` existiert
   und läuft auf `pull_request` sowie `pull_request_review`,
6. der PR-Autor kann den eigenen PR nicht freigeben,
7. die wirksame `APPROVED`-Review bindet exakt den finalen Source-PR-Head,
8. nach der Review kommt kein weiterer Commit ohne erneute Approval,
9. der Check bestätigt Author-/Reviewer-Trennung, Reviewerrolle, Reviewstate, Source-Blob,
   C0-Hash, zulässigen Scope und aktuelle Branchschutzwerte,
10. Merge erfolgt regulär ohne Admin-Bypass.

PR-Titel, Commitmessage, `merged_by`, grünes Standard-CI, Chatfreigabe und ein Review durch
einen Bot oder Federation-Agenten sind kein Ersatz.

## 8. Sequenzierungswiderspruch

Feature 01 §15 ordnet Schnitt C vor Schnitt I ein. Gleichzeitig verlangt der bereits
geschlossene Attestation-Vertrag für den Source-PR Governance- und Check-Evidence, die in
§15.9 erst Schnitt I zugeordnet ist.

Die Aussage in `FEATURE_01_ATTESTATION_OPERATIONS_RECON.md`, fehlende Live-Preconditions
blockierten nicht jede default-off Implementierung, gilt für normalen Produktcode. Sie
hebt den speziell für Schnitt C verlangten menschlich reviewten Source-PR nicht auf.

Deshalb ist vor Schnitt C eine explizite Spec-/Sequenzentscheidung nötig. Zulässige
Richtung:

- die minimal nötige Constitution-Governance und den geschützten Attestation-Check als
  eigenes prerequisite Gate vor Schnitt C ziehen,
- die weitergehende Delivery-/Aktivierungs-Governance weiterhin in Schnitt I lassen.

Unzulässig:

- Source jetzt mergen und später so tun, als sei der alte Head attestiert,
- aktuelle Branchschutzwerte rückwirkend als damalige Evidence ausgeben,
- den Source-PR nachträglich durch einen neuen PR „segnen“,
- die Reviewanforderung für Bequemlichkeit aus der Spec entfernen,
- den einzigen Adminaccount als getrennten Author und Reviewer darstellen.

Diese G2-Datei ändert die Feature-Spec noch nicht. Sie dokumentiert den bewiesenen
Widerspruch und blockiert die Implementierung bis zu einer getrennt reviewten
Sequenzkorrektur.

### 8.1 Spätere normative Korrektur

Der Live-Befund dieses Recon bleibt gültig: Es gab genau einen Collaborator und keinen
unabhängigen GitHub-Reviewbeweis. Die daraus abgeleitete Zwei-Principal-Precondition war
jedoch für die reale Single-Owner-Projektgovernance zu streng.

`CONTEXT_BRIDGE_GOVERNANCE_AMENDMENT_01.md` ersetzt deshalb ausschließlich §§7–8 dieses
Dokuments: Der Operator darf den eingefrorenen Source-PR-Head über ein gebundenes
Single-Owner-HITL-Reviewpaket freigeben. Git und CI attestieren Bytes, Scope und Checks;
sie behaupten keinen unabhängigen zweiten Human-Review. Alle übrigen Source-, Test-,
Scope-, Rollback- und No-Autopublish-Grenzen dieses Recon bleiben unverändert.

## 9. Rollback- und Abbruchgrenze

Sollte ein später korrekt gegateter Source-PR vor Merge scheitern, wird der Branch
verworfen; Main bleibt auf Blob `29829be4f77dcaebf970a8ee872de299f0357f1c`.

Nach einem regulär reviewten Merge wäre ein Rückwechsel der Constitution ebenfalls eine
C0-Sourceänderung und kein stiller autonomer Restore. Er benötigt denselben Reviewpfad.
Root-Dateien bleiben während Schnitt C unverändert; der Legacy-Writer-Fence bleibt aktiv.

Sofortiger Abbruch bei:

- neuem Main-Drift außerhalb Runtime-State,
- anderem Source-Blob,
- unbekanntem offenen PR im Source-/Governance-Scope,
- fehlendem oder nicht commitgebundenem Review,
- Review durch PR-Autor oder nicht ausreichenden Principal,
- Scope-Erweiterung,
- Root-/Writer-/Workflow-/State-Mutation,
- Versuch eines Admin- oder API-Bypasses.

## 10. Ergebnis

Der technische Source-Kandidat ist klein, deterministisch und parsergeprüft. Das ist
notwendig, aber nicht hinreichend. Constitution-Autorität entsteht nicht aus korrekten
Bytes allein.

**G2-Start bleibt gesperrt.** Der nächste zulässige Arbeitsgang ist eine eigene read-only
Spec-/Governance-Sequenzkorrektur, die nur die für den menschlich reviewten Source-PR
notwendigen Preconditions vor Schnitt C zieht. Bis zu deren Review und realer Erfüllung
werden weder `.steward/conventions.md` noch Tests oder andere Implementierungspfade
verändert.
