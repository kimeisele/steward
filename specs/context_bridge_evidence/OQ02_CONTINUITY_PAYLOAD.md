# OQ-02 — MINIMALER CONTINUITY-PAYLOAD

> **Status:** EVIDENCE COMPLETE — Reference-Card-Vertrag entschieden
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `b2b633cb7f7e9e0f0b2164527034c2426541b7a7`
> **Steward-Tree:** `eed3c2b6a9f15d40323aa9b852633787d29b41de`
> **PHASE2_CURRENT-Blob:** `cb3e85c6a02bc776c2611bced87c6e9bf96ee995`
> **Scope:** Consumer-Verhalten, Größenbudget, Pointer, Full-File-Include,
> Markdown-Extraktion und minimaler Continuity-Payload. Keine Änderung an Root-Dateien,
> Cockpit, Code oder Workflow.

---

## 1. Fragestellung

OQ-02 formuliert scheinbar zwei Möglichkeiten:

1. Root-Dateien verweisen nur auf `docs/PHASE2_CURRENT.md`.
2. Root-Dateien übernehmen einen sanitizten, nichtautoritativen Ausschnitt.

Die Evidence zeigt, dass beide Varianten allein unzureichend sind:

- Ein nackter Link liefert einem frischen Consumer zu wenig Zustandsinformation.
- Ein Markdown-Ausschnitt übernimmt weiterhin freie, potenziell stale oder adversariale
  Prosa in den Instruktionsraum.

Die richtige Grenze liegt zwischen Pointer und Prosa: eine kleine, typisierte Reference
Card aus maschinenprüfbaren Metadaten.

---

## 2. Consumer-Beweis aus OQ-11

### Codex

Codex entdeckt `AGENTS.md` hierarchisch. OQ-11 hat keinen nativen `@file`-Importvertrag
für `AGENTS.md` belegt. Ein Markdown-Link auf `docs/PHASE2_CURRENT.md` ist deshalb nur ein
Verweis; sein Ziel wird nicht automatisch als Session-Instruktion geladen.

Ein nackter Pointer garantiert somit keine nahtlose Fresh-Session-Orientierung.

### Claude Code

Claude Code unterstützt `@path`-Imports in `CLAUDE.md`. Ein solcher Import würde aber die
vollständige Zieldatei als Context laden. OQ-15 belegt im aktuellen Cockpit imperative
Prosa, einen Copy-Paste-Prompt und lokale absolute Pfade.

Ein Claude-spezifischer Import wäre daher:

- kein sicherer Auszug,
- nicht byte-identisch zum Codex-Vertrag,
- eine Umgehung der PUBLIC_SAFE- und Trust-Grenze,
- consumerabhängiges Verhalten ohne Notwendigkeit.

OQ-11 verlangt weiterhin byte-identische Root-Dateien, solange kein technischer Zwang
eine minimale Abweichung erfordert. OQ-02 belegt keinen solchen Zwang.

---

## 3. Größen- und Budgetbeweis

Am gepinnten Head:

| Datei | Bytes | Zeilen | Wörter |
|---|---:|---:|---:|
| `CLAUDE.md` | 4.045 | 68 | 562 |
| `docs/PHASE2_CURRENT.md` | 9.948 | 210 | 1.086 |
| `docs/PHASE2_BEFUND.md` | 74.492 | 1.586 | 8.563 |

Das Cockpit allein ist mehr als doppelt so groß wie der gesamte aktuelle Root-Context und
überschreitet bereits Claudes empfohlenen Zielwert von unter 200 Zeilen. Sein Abschnitt
„Exakt nächster Auftrag“ umfasst allein rund 1.523 Bytes; der Copy-Paste-Prompt weitere
rund 1.066 Bytes.

Ein Full-File-Include ist damit nicht nur unsicher, sondern verdrängt den eigentlichen
statischen Verfassungskern und lebende Systemsignale aus dem Contextbudget.

---

## 4. Warum ein sanitizter Markdown-Ausschnitt nicht reicht

Sanitization kann Zeichen, Struktur und Länge kontrollieren. Sie kann nicht zuverlässig
beweisen:

- dass die gewählte Überschrift noch den aktuellen Operatorauftrag beschreibt,
- dass freie Prosa faktisch richtig ist,
- dass ein Satz Orientierung statt Governance enthält,
- dass ein imperativer Satz nicht als Agentenanweisung wirkt,
- dass ein neuer Dokumentaufbau weiterhin denselben Abschnitt bezeichnet,
- dass ein semantisch widersprüchlicher Text durch Escaping ungefährlich wird.

Ein Parser, der beispielsweise `## 6. Exakt nächster Auftrag` ausschneidet, macht die
Überschrift selbst zur unreviewten API. Eine umbenannte, doppelte oder adversarial
eingeschleuste Überschrift könnte die Auswahl kontrollieren.

Darum gilt:

> Freies Markdown wird nicht zur Daten-API der Context-Bridge erklärt.

---

## 5. Warum ein nackter Pointer nicht reicht

Ein reiner Pfad wie `docs/PHASE2_CURRENT.md` sagt nicht:

- welcher Blob untersucht wurde,
- auf welchem Repository-Head er lag,
- ob die Datei fehlt, stale, conflicting oder unsafe ist,
- ob ihre Review-Provenance belegt ist,
- ob sie den aktuellen Operatorauftrag enthält,
- ob ein Agent sie lesen sollte oder nur als historischen Snapshot behandeln darf.

Ein Agent könnte aus dem Dateinamen weiterhin falsche Currentness ableiten. Der Pointer
braucht deshalb typisierte Provenance und Status.

---

## 6. Verbindliche Lösung: typisierte Reference Card

Beide byte-identischen Root-Dateien erhalten höchstens eine kompakte, neutrale
Continuity-Card. Ihr semantischer Kern besteht aus allowlisteten Feldern:

| Feld | Zweck | Renderregel |
|---|---|---|
| `source_path` | stabiler Repository-Verweis | exakt `docs/PHASE2_CURRENT.md`; keine lokale Absolutadresse |
| `source_blob` | gelesene Bytes | 40-stelliger Git-Blob-Hash |
| `source_role` | Autoritätsgrenze | festes Enum `advisory_phase_snapshot` |
| `basis_repository` | Snapshotdomäne | normalisierte Repository-Identität |
| `basis_head` | deklarierter Snapshot | validierter Commit-Hash |
| `basis_relation` | Git-Freshness | bekanntes Enum wie `ancestor` oder `diverged` |
| `acquisition_status` | Pfad-/Lesestatus | OQ-15-Enum |
| `integrity_status` | Schema-/Referenzstatus | OQ-15-Enum |
| `review_status` | Review-Provenance | OQ-15-Enum |
| `freshness_status` | Snapshot-/Konfliktstatus | OQ-15-Enum |
| `operator_status` | Session-Autorität | `operator_unknown` ohne authentifizierte Quelle |
| `work_claim_id` | optionaler kuratierter Claim | nur typisiertes co-located Metadatenfeld |
| `work_claim_summary` | optionale Orientierung | einzeilig, neutral, streng begrenzt, nie imperativ |

Die Karte ist Datenrepräsentation. Sie sagt nicht „führe Work Claim X aus“, sondern
„dieser advisory Snapshot behauptet X mit Status Y“.

---

## 7. Co-located Metadaten statt Sidecar oder Body-Parser

Der optionale Work-Claim stammt nur aus einer kleinen versionierten Metadatenhülle
innerhalb derselben kuratierten Datei.

Gründe:

- Ein Sidecar wäre eine zweite manuell zu synchronisierende Wahrheit.
- Ein Body-Parser erhebt freie Überschriften und Absätze zu einer instabilen API.
- Co-located Metadaten werden im selben menschlichen Diff wie der Arbeitsstand reviewt.
- Der Heartbeat liest sie, schreibt sie aber nicht.
- Unbekannte Schemaversionen degradieren nach OQ-13/OQ-15 `unsupported`, statt auf
  heuristische Prosaextraktion zurückzufallen.

Die konkrete Syntax der Hülle wird in Feature-Spec 02 festgelegt. OQ-02 entscheidet nur
die Semantik und verbietet eine zweite Continuity-SSOT.

---

## 8. Verhalten des heutigen Cockpits

Der aktuelle Blob besitzt noch keine versionierte maschinenlesbare Metadatenhülle. Die
Bridge darf deshalb aus seinem freien Abschnitt „Exakt nächster Auftrag“ keinen
`work_claim_id` oder Summary-Text rekonstruieren.

Bis eine separat reviewte Metadatenänderung existiert, wäre die zulässige Card sinngemäß:

- Quelle vorhanden und content-addressed,
- Snapshotreferenzen manuell belegt, automatisches Schema aber noch unsupported,
- Review-Provenance unverified,
- Work-Claim im aktuellen Sessionkontext conflicting,
- Operatorauftrag für die automatische Bridge unknown,
- Dokument nur als advisory Snapshot referenziert.

Das ist ehrlicher als eine scheinbar hilfreiche alte Agenda.

---

## 9. Darstellungsgrenzen

Die spätere Card:

- bleibt als Zielwert unter 20 Zeilen und deutlich unter 1 KiB,
- verwendet keine Markdown-Überschrift oder Liste aus der Quelldatei,
- enthält keine lokalen Pfade,
- enthält keine freien Evidence-Absätze,
- enthält keinen Copy-Paste-Prompt,
- enthält keine dynamisch erzeugten C0-Regeln,
- importiert die Quelldatei weder bei Claude noch bei Codex automatisch,
- ist in `CLAUDE.md` und `AGENTS.md` byte-identisch, solange OQ-11 gilt.

Ein relativer Pfad bleibt für den Menschen und Agenten auffindbar, aber das Öffnen der
Datei ist eine bewusste Folgeaktion innerhalb des aktuellen Sessionauftrags.

---

## 10. Konfliktanzeige

Wenn ein Metadaten-Work-Claim und eine höherwertige Quelle widersprechen, rendert die
Card keine Gewinneragenda. Sie zeigt typisiert:

- advisory Work-Claim vorhanden,
- Conflict-Status,
- welche Evidenzklasse den Konflikt ausgelöst hat,
- Operatorstatus `known` oder `unknown` ohne freien Chatinhalt zu kopieren.

Der tatsächliche aktuelle Operatorauftrag bleibt außerhalb der automatischen Bridge
höherwertig. Ohne authentifizierte Quelle darf die Card ihn weder erraten noch aus Tasks,
Issues oder Dokumentprosa rekonstruieren.

---

## 11. Hash- und Commitsemantik

Für OQ-05 gilt:

- Änderungen an normalisierten OQ-15-Statusfeldern sind C1/C2 und können den
  `payload_hash` ändern.
- Ein neuer `source_blob` allein ist nur dann Root-commitwürdig, wenn sich Card-Semantik,
  Review-, Integrity-, Freshness- oder Work-Claim-Felder ändern.
- Reine Prosaänderungen außerhalb der Metadatenhülle lösen keinen Root-Diff aus.
- Eine geänderte Metadatenhülle muss erneut vollständig validiert werden.
- Der Root-Payload verweist immer auf den Blob, aus dem seine Card erzeugt wurde; er
  behauptet nicht, einen neueren ungeprüften Blob zu repräsentieren.

---

## 12. Fehler- und Fallbackmatrix

| Source-Zustand | Card-Verhalten |
|---|---|
| Datei fehlt | `missing`; kein alter Work-Claim |
| Pfad/Symlink unsafe | `unsafe`; Quelle nicht öffnen/importieren |
| Metadaten fehlen | `unsupported_schema`; nur sichere Git-Referenzfelder |
| Metadaten invalid | `invalid`; kein Body-Parser-Fallback |
| Snapshot stale | Pfad/Blob plus `stale`; kein Summary-Imperativ |
| Work-Claim conflicting | beide Statusrollen neutral zeigen; keine Agenda erzeugen |
| Review unverified | sichtbar `review_unverified`; kein C0-Rang |
| Operatorquelle fehlt | `operator_unknown` |
| Quelle vollständig validiert | typisierte Card; optionaler neutraler Claim |

Fehler der optionalen Card blockieren nicht den statischen Safe Fallback, aber jede
positive Behauptung über den aktuellen Phasenauftrag.

---

## 13. Adversariale Testfolgen

Feature-Spec 02 benötigt mindestens:

1. Codex erhält keinen impliziten Include und trotzdem alle Card-Statusfelder.
2. Claude lädt `PHASE2_CURRENT` nicht über `@path` automatisch.
3. Freie Überschrift im Body kann keinen Work-Claim erzeugen.
4. Mehrere gleichnamige „Next Task“-Abschnitte ändern die Card nicht.
5. Metadaten fehlen oder sind unknown-versioned: `unsupported`, kein Heuristikfallback.
6. Metadaten enthalten imperative Summary, Markdown, Newline, bidi oder Überlänge:
   invalid/unsafe.
7. Lokale absolute Pfade im Body gelangen nicht in die Card.
8. Body ändert sich, Metadaten und Status bleiben semantisch gleich: kein Root-Diff.
9. Work-Claim-Metadaten ändern sich: deterministischer Payload-Diff.
10. Source-Blob und gerenderte Provenance stimmen exakt überein.
11. Missing/stale/conflicting verlieren niemals den vorherigen Claim als aktuellen Text.
12. Beide Consumer-Dateien enthalten dieselben Card-Bytes.

---

## 14. Nicht belegbare Annahmen

OQ-02 legt bewusst noch nicht fest:

- konkrete Syntax der co-located Metadatenhülle,
- konkrete Work-Claim-ID-Namenskonvention,
- exakte Summary-Zeichenlänge innerhalb der harten Card-Grenze,
- wer die Metadaten künftig reviewt,
- wie ein externer Operatorauftrag authentifiziert werden könnte.

Diese Details gehören in Feature-Spec 02 beziehungsweise OQ-07-Governance. Sie ändern
die Payload-Grenze nicht.

---

## 15. Entscheidung

OQ-02 ist geschlossen:

1. Kein Full-File-Include für Claude oder Codex.
2. Keine freie oder überschriftenbasierte Markdown-Extraktion.
3. Kein nackter Pointer ohne Provenance und Status.
4. Beide Root-Dateien erhalten dieselbe kleine typisierte Reference Card.
5. Ein optionaler Work-Claim stammt ausschließlich aus versionierten co-located
   Metadaten derselben kuratierten Datei.
6. Fehlen diese Metadaten, bleibt es beim degradierten Reference-Payload ohne behauptete
   aktuelle Aufgabe.
7. Der aktuelle Operatorauftrag wird nie rekonstruiert; ohne authentifizierte Quelle gilt
   `operator_unknown`.
8. Die Card bleibt unter harter Größen- und Trust-Grenze und macht OQ-15-Status sichtbar.

Diese Entscheidung autorisiert keine Metadatenänderung, keinen Rendererpatch und keinen
Root-Publish. G0 bleibt offen.
