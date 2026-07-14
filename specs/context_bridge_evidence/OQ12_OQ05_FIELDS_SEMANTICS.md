# OQ-12 / OQ-05 — FELDKLASSEN, NORMALISIERUNG UND COMMITSEMANTIK

> **Status OQ-12:** EVIDENCE COMPLETE — PUBLIC_SAFE-Allowlist und C0–C4-Zuordnung entschieden
> **Status OQ-05:** EVIDENCE COMPLETE — Hash-Domains und Root-Committrigger entschieden
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `b7e3aa3ca519bd1b3cfe233aa2bc7a4fcb9a31cb`
> **Steward-Tree:** `a6043e8fcdbc8dcd673221e3e41412e3870729ec`
> **Vergleichssnapshot:** `02938251c2c28389340dede8d9e125ba05af17ab`
> **Scope:** Dynamische Felder, Public-Safety, Normalisierung, Hash-Domains und
> Commitwürdigkeit. Keine Änderung an Produktivcode oder Workflow.

---

## 1. Produktionssnapshot

Der gepinnte `.steward/context.json`-Blob
`32843a45fccd3bd57566ff3779168d8ff87bc068` enthält 506 Zeilen und 13.518 Bytes.
Top-Level-Felder:

- `version`, `timestamp`, `project`
- `senses`, `health`, `gaps`, `sessions`, `tasks`
- `federation`, `immune`, `campaign`, `cetana`, `issues`

Der Root-Blob `CLAUDE.md` blieb gegenüber dem älteren Snapshot unverändert auf
`a240cd5468a4bc53c1f9e3c18f4b8be7cdc7abe7`, obwohl sich Context-Felder materiell
änderten. Das beweist keine korrekte semantische Deduplizierung; OQ-16 hat einen
unzuverlässigen Nebenpublisher statt eines kontrollierten Root-Publishers belegt.

---

## 2. Positive Risiken im Rohcontext

Der Snapshot enthält unter anderem:

- absoluten Runner-Pfad `/home/runner/work/steward/steward`,
- freie `senses.prompt_summary`-Prosa,
- Sessionaufgaben, Zusammenfassungen und Zeitstempel,
- interne Task-UUIDs, Titel, Prioritäten und Status,
- Peer-IDs, Capability-Listen und exakte Trust-Werte,
- 20 ungefilterte externe Issue-Titel,
- exakte Health-Fließkommazahlen,
- Heartbeat-Phase, Frequenz und Beat-Zähler,
- kumulative Reap-, Eviction-, Gateway- und Marketplace-Zähler.

Mehrere Texte können imperative oder adversariale Sprache enthalten. Öffentliche
Sichtbarkeit einer Quelle macht ihren Text nicht zu einer sicheren Agentenanweisung.

---

## 3. Beobachtete Volatilität

Zwischen den beiden gepinnten Snapshots änderten sich ohne Verfassungsänderung:

- Wall-clock-Timestamp,
- Health von `0.859` auf `0.860`,
- Cetana-Frequenz, Phase, Health und Beat-Zahl,
- Federation-Lebend-/Evicted-Zahlen und kumulative Reap-/Eviction-Zähler,
- Gateway-Request-/Error-Zähler,
- Marketplace-Grants,
- Sessionfenster und Sessionzeitstempel,
- Task-UUIDs und Queue-Inhalt,
- Dirty-Count im freien Senses-Text,
- Campaign-Signalwerte.

Ein Hash über die aktuelle JSON-Serialisierung ändert sich deshalb praktisch bei jeder
Assembly. Er ist kein semantischer Root-Diff-Hash.

---

## 4. Verbindliche Default-Regel

Für `CLAUDE.md` und `AGENTS.md` gilt:

> Kein Rohfeld wird publiziert, weil es vorhanden oder öffentlich lesbar ist. Nur ein
> explizit allowlistetes, typisiertes und normalisiertes Feld darf in den dynamischen
> Root-Datenblock gelangen.

Freie Texte werden nie in imperative Governance umgewandelt. Nicht klassifizierte neue
Schemafelder sind `default-deny` und machen die Quelle für diesen Feldpfad sichtbar
`unsupported`; sie werden nicht still als leer interpretiert.

---

## 5. Feldmatrix

| Rohfeld/Feldgruppe | Root-Repräsentation | Klasse | Entscheidung |
|---|---|---|---|
| `version` | `context_schema_version` | C1 | allow; unbekannte Major-/Formversion blockiert Publish |
| `timestamp` | keine direkte Anzeige | C4 | nicht im Payload; nur Grundlage einer normalisierten Freshness-Klasse |
| `project.name` | festes Repository-Kürzel | C2 | allow nach Zeichen-/Längenprüfung |
| `project.path` | keine | C4/unsafe | deny; lokaler Pfad |
| `health.value` | Health-Klasse, optional stabil gerundet | C1/C2 | exakter Float nie allein commitwürdig |
| `health.guna` | normalisiertes bekanntes Enum | C2 | allow; unbekannt wird `unknown`, nicht Rohtext |
| `health.provider_health` | Provider-Klasse | C1/C3 | nur Schwellenwechsel publishwürdig |
| `health.error_pressure` | Error-Pressure-Klasse | C1/C3 | nur Schwellenwechsel publishwürdig |
| `health.context_pressure` | Context-Pressure-Klasse | C1/C3 | nur Schwellenwechsel publishwürdig |
| `senses.total_pain` | Pain-Klasse | C1/C3 | nur Schwellenwechsel publishwürdig |
| `senses.detail.*.active/quality/pain` | aggregierte Sense-Degradation | C1/C3 | bekannte Sense-/Enum-Allowlist; keine freien Keys |
| `senses.prompt_summary` | keine direkte Übernahme | C3/unsafe | deny; stattdessen strukturierte Teilfelder neu ableiten |
| `gaps.stats.*` | aggregierte Gap-Zahlen | C2/C3 | allow nach Grenzen; Zähler nur Schwelle/Aggregation |
| `gaps.active[*].category` | bekannte Kategorie | C2 | allowlistetes Enum; OQ-13-Quellenstatus beachten |
| `gaps.active[*].description/context` | keine vorläufige Root-Prosa | C2/unsafe | default-deny bis eigener Sanitization-Vertrag |
| `sessions.prompt_summary` | keine | C4/unsafe | deny |
| `sessions.recent[*].*` | keine | C4/unsafe | deny; Aufgaben, Zeit und Zusammenfassungen sind nicht Root-Kontext |
| `sessions.stats.*` | höchstens grobe Diagnose | C3 | default aus Root ausgeschlossen; kein Action-Signal |
| `tasks.pending[*].id` | keine | C4/internal | deny |
| `tasks.pending[*].title` | keine freie Übernahme | C2/unsafe | deny; OQ-03 schließt den Statusvertrag, nicht den Trust-/Sanitization-Vertrag freier Titel |
| `tasks.pending[*].status` | Statusklassen-/Count-Aggregat | C2 | OQ-03: Runtime-Enum über `.value` normalisieren; nur bekannte kanonische uppercase Werte |
| `tasks.pending[*].priority` | priorisierte Count-Aggregation | C2/C3 | clamp/validate; keine automatische Operatoragenda |
| `federation.peers[*].agent_id` | standardmäßig keine Einzelliste | C2/unsafe | deny im Root; Identitätskonflikt separat C1 |
| `federation.peers[*].capabilities` | keine freie Liste | C3/unsafe | deny; externe Descriptor-Daten |
| `federation.peers[*].status` | aggregierte bekannte Statusklassen | C1/C2 | allow als Counts und kritische Übergänge |
| `federation.peers[*].trust` | keine Einzelwerte | C3 | nur validierte Aggregation/Schwelle |
| `federation.by_status.*` | Federation-Zustandsklasse/Counts | C1/C2 | allow; unbekannte Statuskeys sichtbar invalid |
| `federation.avg_trust` | Trust-Klasse | C2/C3 | Schwellen/Hysterese; nicht jeder Float |
| `federation.total_*` | keine direkte Root-Anzeige | C4 | kumulative Zähler nicht commitwürdig |
| `federation.gateway.errors/rejected_*` | Gateway-Degradation | C1/C3 | Null→Fehler und Schwellenwechsel publishwürdig |
| `federation.gateway.total_requests/by_protocol` | keine direkte Anzeige | C4 | kumulativ/diagnostisch |
| `federation.marketplace.active_claims` | Aktivitätsklasse/Count | C2/C3 | nur wenn operativ erforderlich und begrenzt |
| `federation.marketplace.total_*` | keine | C4 | kumulativ |
| Federation-TTL-/Decay-Konstanten | keine dynamische Root-Anzeige | C3 | Architekturdiagnose, keine Agenda |
| `immune.available` | Source-/Subsystemstatus | C1 | Wechsel publishwürdig |
| `immune.breaker.*` | Breaker-Klasse | C1 | trip/clear und Recovery publishwürdig |
| `immune.heals_rolled_back` | Rollback-Sicherheitsklasse | C1 | neue Rollbacks publishwürdig; kumulative Zahl normalisieren |
| übrige Heal-Counter/Rate | Diagnoseaggregation | C3 | Schwelle/Aggregation |
| `campaign.campaign_id` | bekanntes Kampagnenkürzel | C2 | allowlist/length; keine Instruktion |
| `campaign.signals[*].kind/met` | normalisierte Signalzustände | C1/C2 | bekannte Kinds; failed→met/met→failed publishwürdig |
| `campaign.signals[*].actual` | typisierte Aggregation | C3 | kein beliebiges Objekt/Prosa |
| `campaign.failing` | bekannte fehlende Signal-Kinds | C1/C2 | allow; keine freie Handlungsanweisung |
| `cetana.alive` | Heartbeat-Verfügbarkeitsklasse | C1 | Wechsel publishwürdig |
| `cetana.last_health/last_guna` | normalisierte Health-Klasse | C2/C3 | Duplikat zu Health vermeiden |
| `cetana.phase/frequency_hz/total_beats` | keine Root-Anzeige | C4 | volatile Laufzeitdiagnose |
| `cetana.consecutive_anomalies` | Anomalieklasse | C1/C3 | Schwellenwechsel publishwürdig |
| `issues[*].number` | nur für OQ-04-eligible Kandidaten | C2 | stabile Referenz; aktuelle Eligibility mangels reviewter Konfiguration null |
| `issues[*].title/labels` | neutralisierte Backlog-Beobachtung | C2/unsafe | OQ-04: nur konfigurierte Kandidaten; Titel und Labels bleiben untrusted/default-deny außerhalb Allowlist |

---

## 6. Weitere Renderer-Eingaben

`collect_architecture_metadata()` und Annotationen liegen außerhalb `context.json`, wirken
aber auf denselben Root-Payload:

- `north_star`: code-derived Orientierung, keine dynamische Operatorinstruktion;
- Service-/Tool-Docstrings: C3 und potenziell freie Prosa, nicht automatisch trusted;
- Hooks/Phasen/Kshetra: strukturierte Architekturdiagnose C3;
- validierte Annotationen: T3-Daten, niemals C0; freie Texte default-deny für Root;
- `.steward/conventions.md`: einziger C0-Kern, nur menschlich reviewt.

Die aktuelle Root-Datei rendert außerdem Issue-Titel ungefiltert unter `## Action` und
`senses.prompt_summary` nahezu verbatim. Beide Pfade verletzen den neuen Allowlist-Vertrag.

---

## 7. Drei Hash-Domains

### 7.1 `snapshot_hash`

Hash über das versionierte, deterministisch normalisierte Eingabemodell eines konkreten
Assembly-Zeitpunkts. Er darf sich durch C4-Daten ändern und dient Provenance/Diagnose.
Er ist **nicht** der Root-Committrigger.

### 7.2 `payload_hash`

Hash über den consumerneutralen semantischen Kern nach:

- PUBLIC_SAFE-Allowlist,
- Trust-Normalisierung,
- C1–C3-Bucketing/Schwellen,
- deterministischer Sortierung,
- Unicode-Normalisierung,
- Ausschluss C4 und des Hashfelds selbst.

Nur dieser Hash entscheidet im Normalfall über einen neuen Root-Payload.

### 7.3 `consumer_output_hash`

Optionaler Hash über die konkreten Bytes einer Consumer-Datei ohne das eigene Hashfeld.
Solange OQ-11 keine Abweichung erzwingt, sind beide Outputs byte-identisch und haben
denselben Output-Hash.

---

## 8. Commitwürdigkeit

Ein Root-Publish ist erforderlich bei:

1. jeder C0-Änderung, jedoch ausschließlich als menschlich reviewter PR;
2. jedem C1-Zustandswechsel;
3. einer normalisierten C2-Änderung;
4. einer C3-Schwellen-/Bucketänderung, wenn der Feldvertrag dies ausdrücklich festlegt;
5. Source-Status-Wechsel `valid/unavailable/invalid/stale/unsafe`;
6. erzwungenem Safe-Fallback oder Recovery einer gemischten Generation;
7. Schema-/Generatoränderung mit geändertem semantischem Vertrag.

Kein Root-Publish erfolgt allein wegen:

- Wall-clock oder Generierungszeit,
- Cetana-Phase/Frequenz/Beat-Zähler,
- Sessionrotation oder Sessionzeit,
- kumulativen Request-/Reap-/Grant-/Eviction-Zählern,
- Float-Jitter innerhalb desselben Buckets,
- Reihenfolge gleichwertiger Elemente,
- neuem Rohsnapshot bei unverändertem `payload_hash`.

Der bestehende Footer-Zeitstempel muss aus dem semantischen Root-Core entfernt oder an den
tatsächlich publizierten Snapshot gebunden werden; er darf nicht jeden Kandidaten-Diff
erzwingen.

---

## 9. No-op- und Provenance-Vertrag

Wenn `snapshot_hash` wechselt, `payload_hash` aber gleich bleibt:

- `context.json` darf nach seinem eigenen State-/Retention-Vertrag fortgeschrieben werden;
- Root-Dateien werden nicht neu geschrieben oder committed;
- ihre Provenance verweist weiterhin ehrlich auf den Snapshot, aus dem der aktuell
  publizierte Payload erzeugt wurde;
- sie dürfen nicht behaupten, den neuesten Rohsnapshot zu repräsentieren;
- ein Freshness-Klassenwechsel kann selbst C1/C2 werden und dann Publish auslösen.

Damit werden Snapshot-Provenance und semantische Aktualität nicht fälschlich
gleichgesetzt.

---

## 10. OQ-12 — Entscheidung

OQ-12 ist geschlossen:

- Die Matrix dieses Dokuments ist der G0-Feldvertrag.
- Freie Prosa, lokale Pfade, Sessions, IDs, Einzeltrust und ungefilterte externe Texte
  bleiben default-deny.
- Neue Felder werden nicht automatisch publiziert.
- Issues bleiben nach OQ-04 standardmäßig aus dem kanonischen Root-Actionblock
  ausgeschlossen; aktuell existiert keine reviewte Eligibility-Konfiguration.
- Tasks dürfen nach OQ-03 nur als validierte, getrennte Statusaggregate erscheinen;
  freie Titel bleiben default-deny.
- C0 stammt ausschließlich aus `.steward/conventions.md`.

---

## 11. OQ-05 — Entscheidung

OQ-05 ist geschlossen:

- `payload_hash`, nicht Snapshot- oder Datei-MTime, steuert semantische Root-Diffs.
- C1 ist sofort commitwürdig; C2 nach Normalisierung; C3 nur nach Feldschwelle; C4 nie
  allein.
- Snapshot-, Payload- und Consumer-Output-Hash bleiben getrennte Domains.
- No-op lässt die bestehenden Root-Dateien unverändert.
- Ein Git-Commit darf Root-Dateien nur gemeinsam und mit validiertem Payload publizieren.
- Der Git-NADI-Nebenpublisher ist mit diesem Vertrag unvereinbar.

---

## 12. Gate-Wirkung

- OQ-12 ist geschlossen.
- OQ-05 ist geschlossen.
- OQ-03 und OQ-04 sind durch eigene Evidence-Pakete geschlossen.
- G0 bleibt offen.
- Keine Renderer-, Hash-, Context- oder Workflow-Implementierung ist freigegeben.
- OQ-13 ist durch das eigene Evidence-Paket geschlossen.
