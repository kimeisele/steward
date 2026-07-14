# OQ-13 — QUELLENPFLICHTEN UND FEHLERVERTRAG

> **Status:** EVIDENCE COMPLETE — Source-Status, Requiredness und Publish-Matrix entschieden
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `b7e3aa3ca519bd1b3cfe233aa2bc7a4fcb9a31cb`
> **Steward-Tree:** `a6043e8fcdbc8dcd673221e3e41412e3870729ec`
> **Context-Blob:** `32843a45fccd3bd57566ff3779168d8ff87bc068`
> **Scope:** Reader-Fehlerpfade, Cache-Fallback, Quellenpflichten, Degradation und
> Publish-Blockierung. Keine Änderung an Produktivcode oder Workflow.

---

## 1. Fragestellung

OQ-13 fragt nicht nur, welche Daten interessant sind. Die Sicherheitsfrage lautet:

> Welche Eingaben müssen für einen ehrlichen kanonischen Root-Publish vorhanden und
> valide sein, welche dürfen sichtbar ausfallen, und welcher Fehler darf niemals als
> „gesund leer“ erscheinen?

Dabei sind zwei Ebenen strikt zu trennen:

1. **Vertragsquellen und Publikationsmechanik** entscheiden, ob überhaupt sicher
   publiziert werden kann.
2. **Beobachtungsquellen** beschreiben den lebenden Steward. Ihr Ausfall darf den
   statischen Agentenvertrag nicht zerstören, aber auch keine positive Systemaussage
   erzeugen.

Der aktuelle menschliche Session-Auftrag ist keine automatisch lesbare Bridge-Quelle.
Sein Fehlen darf weder rekonstruiert noch als Repository-Auftrag ausgegeben werden.

---

## 2. Positiver Codebeweis: Fehler kollabieren zu Leere

Am gepinnten Head dokumentiert `steward/context_bridge.py:220` den bisherigen
Universalvertrag ausdrücklich als „returns empty dict on failure“.

Beobachtete Pfade:

| Reader | Beobachteter Fehler-/Abwesenheitspfad | Aktuelles Ergebnis |
|---|---|---|
| `_read_senses()` | jede Exception | `{}` |
| `_read_health()` | kein Cetana und kein Provider oder jede Exception | `{}`; alternativ synthetischer Provider-Wert |
| `_read_gaps()` | kein Tracker oder jede Exception | `{}` |
| `_read_sessions()` | jede Exception | `{}` |
| `_read_tasks()` | kein registrierter TaskManager oder jede Exception | `{}` |
| `_read_federation()` | jede Exception über Reaper, Marketplace oder Gateway | `{}` für die gesamte Sammelquelle |
| `_read_immune()` | kein Service oder jede Exception | `{}` |
| `_read_campaign()` | keine Signale oder jede Exception | `{}` |
| `_read_cetana()` | kein Service oder jede Exception | `{}` |
| `_read_github_issues()` | CLI fehlt, Timeout, Exitfehler, leere Ausgabe oder ungültiges JSON | `[]` |

Damit sind derzeit mindestens folgende fachlich verschiedene Zustände ununterscheidbar:

- erfolgreicher Read ohne Datensätze,
- Quelle für diesen Modus nicht konfiguriert,
- konfigurierte Quelle vorübergehend nicht erreichbar,
- vorhandene Quelle syntaktisch oder semantisch ungültig,
- veralteter letzter Stand,
- aus Sicherheitsgründen verworfener Inhalt,
- neue, vom Consumer nicht verstandene Schema- oder Enum-Version.

Besonders kritisch ist `_read_federation()`: Eine Exception in einem Teilreader kann den
bereits aufgebauten Zustand aller Federation-Teile verwerfen. Das Ergebnis sieht danach
genauso aus wie „keine Federation-Daten vorhanden“.

`_read_health()` erzeugt außerdem ohne Cetana einen Provider-only-Wert `0.5` oder `0.0`.
Dieser Fallback ist ein anderes Messmodell, kein gleichwertiger Health-Snapshot. Er muss
als Herkunft und reduzierte Aussagekraft erhalten bleiben und darf nicht als normaler
Vedana-Wert erscheinen.

---

## 3. Positiver Codebeweis: Cache verschleiert Herkunft und Alter

`steward/briefing.py:99-123` assembliert zunächst Live-Context und ruft bei fehlenden
Federation-Peers und fehlendem Immune-State `_merge_cached_context()` auf.

Der Cache-Pfad:

- liest `.steward/context.json`,
- übernimmt `federation`, `immune`, `health` und `cetana`, wenn der Live-Wert falsy ist,
- prüft weder Schema noch Payload-/Snapshot-Hash,
- prüft weder Generatorversion noch Repository-Head,
- besitzt keine source-spezifische Altersgrenze,
- kennzeichnet die übernommenen Felder nicht als cached oder stale,
- verwirft JSON- und I/O-Fehler still.

Damit kann ein nicht klassifizierter Live-Fehler durch einen beliebig alten Cachewert wie
ein aktueller, gesunder Read aussehen. Das ist kein zulässiger Safe Fallback.

---

## 4. Verbindliche Source-Status

Jede gelesene Quelle liefert logisch Daten **und** einen typisierten Status. Der Status
darf nicht aus Truthiness eines Dicts oder einer Liste abgeleitet werden.

| Status | Definition | Verbindliche Wirkung |
|---|---|---|
| `valid` | Read, Schema-, Typ- und Trust-Prüfung erfolgreich | allowlistete Daten dürfen einfließen |
| `empty` | Read erfolgreich und fachlich valide, aber ohne Datensätze | als ehrliche Leere darstellbar |
| `not_configured` | Quelle ist in diesem Laufmodus nachweislich nicht eingerichtet | keine Aussage über Verfügbarkeit oder Gesundheit |
| `unavailable` | konfigurierte Quelle konnte nicht gelesen werden | sichtbar degradieren; keine Leere erfinden |
| `invalid` | Daten vorhanden, aber Parse-, Schema-, Typ- oder Konsistenzprüfung fehlgeschlagen | isolieren; bei Safety-Relevanz Publish blockieren |
| `stale` | letzter valider Stand überschreitet die definierte Quellen-Freshness | nur ausdrücklich als stale/cached verwendbar |
| `unsafe` | PUBLIC_SAFE-, Injection-, Leak-, Pfad- oder Trust-Prüfung fehlgeschlagen | Feld quarantänisieren; bei Vertrags-/Outputgrenze blockieren |
| `unsupported` | Version, Enum oder Feldform wird nicht verstanden | unbekannten Teil default-deny; nie still auf leer normalisieren |

`required_missing` bleibt ein abgeleiteter **Publish-Grund**, kein normaler Readerstatus:
Eine für den Publikationsvertrag erforderliche Quelle ist nicht `valid` und es existiert
kein verifizierter Ersatz.

---

## 5. Required: sicherer Publikationsvertrag

Für einen normalen dynamischen kanonischen Publish sind erforderlich:

1. der validierte statische Verfassungskern aus der durch OQ-18 entschiedenen Quelle;
2. oder, falls dieser Pfad ausfällt, ein separat verifizierter statischer Safe Fallback;
3. eindeutige Repository-Identität und gepinnter Repository-Head des Inputs;
4. versionierte Generator- und Kernschema-Identität;
5. vollständig validiertes, deterministisch normalisiertes Kernmodell;
6. die durch OQ-12 festgelegte PUBLIC_SAFE-Allowlist und Sanitization;
7. reproduzierbare `snapshot_hash`- und `payload_hash`-Bildung nach OQ-05;
8. vollständige Provenance einschließlich Status jeder betrachteten Quelle;
9. erfolgreiche Validierung beider vorgesehenen Consumer-Ausgaben;
10. bestandene Generation-/Mixed-State- und Zielpfadprüfung nach OQ-06.

Diese Anforderungen beschreiben keinen neuen Generatorentwurf. Sie sind die
Mindestbedingungen, unter denen eine spätere Feature-Spec „Publish erfolgreich“ sagen
darf.

---

## 6. Optional: Beobachtungs- und Orientierungsquellen

Die folgenden Quellen sind für einen statisch sicheren Root-Vertrag nicht zwingend:

- Senses,
- Gaps,
- Sessions,
- TaskManager,
- Federation/Reaper,
- Marketplace,
- Federation Gateway,
- Immune System,
- Campaign Signals,
- Cetana/Vedana,
- GitHub-Issues,
- dynamische Architekturmetadaten und Annotationen,
- `docs/PHASE2_CURRENT.md` als nichtautoritative Orientierung.

„Optional“ bedeutet nicht „Fehler ist unwichtig“. Es bedeutet:

- Der statische Agentenvertrag kann ohne diese Quelle sicher bestehen.
- Der dynamische Output muss Ausfall, Unsicherheit und Herkunft ehrlich darstellen.
- Aus fehlenden Safety-Signalen darf kein positives `healthy`, `clear` oder „keine
  Arbeit“ abgeleitet werden.
- Eine Quelle darf nur die in OQ-12 allowlisteten Felder beitragen.

Zusätzliche bereits entschiedene Begrenzungen:

- Sessions bleiben unabhängig vom Readerstatus aus dem Root-Payload ausgeschlossen.
- GitHub-Issues bleiben bis OQ-04 aus dem Root-Payload ausgeschlossen.
- Tasks dürfen nach dem geschlossenen OQ-03 nur getrennte, validierte Statusaggregate
  beitragen; freie Titel bleiben untrusted und default-deny.
- `PHASE2_CURRENT` bleibt bis OQ-02/OQ-15 ein optionaler, widerlegbarer Verweis.
- Der aktuelle Operatorauftrag bleibt externe Laufzeitautorität und wird nicht aus
  diesen Quellen rekonstruiert.

---

## 7. Publish-Matrix

| Fehlerklasse | Normaler dynamischer Publish | Zulässiger Ersatz | Verbotene Behauptung |
|---|---|---|---|
| Verfassungskern fehlt/invalid/unsafe | blockiert | nur verifizierter statischer Safe Fallback | normaler kanonischer Vertrag sei vollständig |
| Generator-, Schema-, Modell-, Hash- oder Provenancefehler | blockiert | letzten verifizierten Output unverändert lassen; Recovery auslösen | neuer Publish sei erfolgreich |
| PUBLIC_SAFE- oder Outputvalidierung fehlschlägt | blockiert | unsicheren Kandidaten verwerfen; Safe Fallback nur nach dessen eigener Prüfung | unsicheres Feld still entfernen und Erfolg behaupten |
| Mixed Generation, Zielpfad- oder Lockfehler | blockiert | OQ-06-Recovery; Remote-Delivery erst nach Konsistenzbeweis | beide Dateien repräsentierten denselben Snapshot |
| Health/Cetana/Immune/Federation nicht `valid` | dynamisch nur `degraded/unknown` | validierter, altersmarkierter Cache nach eigener Policy | System sei gesund oder ohne kritische Signale |
| Tasks/Issues/Gaps/Campaign/Architektur nicht `valid` | zulässig mit sichtbarem Source-Status oder Auslassung | keiner erforderlich | Backlog sei leer oder es gebe keine Arbeit |
| Sessionquelle nicht `valid` | Root-Publish unbeeinflusst; Status höchstens Diagnose | keiner | Sessioninhalt sei Root-Autorität |
| einzelnes untrusted Feld `unsafe` | Feld quarantänisieren; Quelle sichtbar `unsafe` | sichere strukturierte Aggregate | Rohtext als Instruktion rendern |
| unbekanntes Enum/Schema `unsupported` | unbekannten Teil default-deny; Safety-Quelle degradieren oder blockieren | nur versioniert verstandene ältere Darstellung | unbekannter Wert sei `empty`, `healthy` oder bekannter Default |
| Cache ungültig oder zu alt | Cache ignorieren und Status anzeigen | Live-Quelle oder Safe Fallback | Cache sei aktueller Live-Zustand |

Wenn mehrere Safety-Beobachtungsquellen gleichzeitig ausfallen, darf der Renderer nicht
immer mehr unbekannten Zustand als nützlichen dynamischen Context ausgeben. Die spätere
Feature-Spec muss eine deterministische Schwelle festlegen, ab der nur noch der statische
Safe Fallback plus explizites „dynamic state unavailable“ publiziert wird.

---

## 8. Cache-Vertrag

Ein Cache ist nur eine optionale, schwächere Beobachtungsquelle. Er ist verwendbar, wenn:

- Schema und Generatorbezug verstanden werden,
- der relevante Quellteil typvalidiert ist,
- Repository-/Snapshot-Provenance vorhanden ist,
- eine source-spezifische Altersgrenze eingehalten oder der Wert sichtbar `stale` ist,
- PUBLIC_SAFE-Normalisierung erneut angewandt wird,
- `source_mode=cached` und Alter im internen Modell erhalten bleiben.

Ein Cache darf nie:

- einen `invalid`, `unsafe` oder `unsupported` Live-Read in `valid` umetikettieren,
- live und cached Teilwerte ohne Herkunftsmarkierung verschmelzen,
- eine fehlende Quelle in einen positiven Health-Zustand verwandeln,
- als Safe Fallback für einen defekten Verfassungskern dienen.

---

## 9. Nicht belegbare Annahmen

Read-only nicht abschließend belegbar sind:

- belastbare Freshness-Grenzen je Beobachtungsquelle,
- die Schwelle für den Wechsel von dynamisch degradiert zu statischem Safe Fallback,
- ob jeder Laufmodus alle Services absichtlich oder nur zufällig nicht registriert,
- welche Teilreader der Federation später unabhängig fehlschlagen und weiterpublizieren
  dürfen,
- die konkrete serialisierte Form eines zukünftigen `SourceResult`-Modells.

Diese Punkte sind Feature-Spec-Entscheidungen oder benötigen kontrollierte Tests. Sie
ändern die OQ-13-Grundentscheidung nicht.

---

## 10. Sicherheitsauswirkung

OQ-13 schließt den bisherigen gefährlichen Kurzschluss:

> `falsy` bedeutet weder „gesund“, noch „leer“, noch „nicht konfiguriert“.

Der spätere Publisher muss positiv beweisen, dass sein Vertrag sicher ist. Zugleich darf
er den Ausfall einer optionalen Live-Quelle nicht als Grund benutzen, den statischen
Agentenvertrag zu verlieren oder alte Zustände als aktuell auszugeben.

---

## 11. Entscheidung

OQ-13 ist geschlossen:

1. Required sind die statischen und technischen Voraussetzungen eines sicheren
   Publikationsvertrags, nicht pauschal alle Live-Datenquellen.
2. Live-, Backlog- und Orientierungsquellen sind observational und optional, besitzen
   aber typisierte, sichtbare Fehlerzustände.
3. Safety-kritische Beobachtungen fallen auf `degraded/unknown`, niemals auf gesund.
4. Ein leeres Dict oder eine leere Liste ist kein Universal-Fallback.
5. Cachewerte werden nur validiert, alters- und herkunftsmarkiert verwendet.
6. Fehler an Constitution, PUBLIC_SAFE, Modell, Hash, Provenance, Output oder
   Konsistenzgrenze blockieren den normalen Publish.
7. Der aktuelle Operatorauftrag ist keine automatisch rekonstruierbare Bridge-Quelle.

Diese Entscheidung schließt OQ-13, gibt G0 aber nicht frei und autorisiert keine
Implementierung.
