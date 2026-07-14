# OQ-15 — CURRENT-PHASE-INTEGRITÄT UND FRESHNESS

> **Status:** EVIDENCE COMPLETE — Integritäts-, Freshness- und Konfliktvertrag entschieden
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `b2b633cb7f7e9e0f0b2164527034c2426541b7a7`
> **Steward-Tree:** `eed3c2b6a9f15d40323aa9b852633787d29b41de`
> **PHASE2_CURRENT-Blob:** `cb3e85c6a02bc776c2611bced87c6e9bf96ee995`
> **Erzeugender Commit:** `c9cffb5f1d5d3b5e88ab8757da0b7b23b3bdd0bd`
> **Deklarierter Snapshot-Head:** `41635ecdf8183fceb910e318e8aebcf95d2091f6`
> **Scope:** Herkunft, Git-Integrität, Snapshotreferenzen, Freshness, semantischer
> Konflikt, Prompt-/Pfadrisiko und Statusdarstellung. Keine Änderung am Cockpit, an Code
> oder Workflow.

---

## 1. Fragestellung

Der Dateiname `PHASE2_CURRENT.md` beweist nicht, dass der Inhalt aktuell, autorisiert oder
sicher publizierbar ist. OQ-15 trennt deshalb fünf verschiedene Fragen:

1. **Acquisition:** Welche Bytes liegen an welchem gepinnten Git-Pfad?
2. **Git-Integrität:** Sind Pfad, Blob und Commit in der untersuchten History erreichbar?
3. **Review-Provenance:** Ist eine menschlich reviewte Autorisierung nachweisbar?
4. **Freshness:** Ist der deklarierte Snapshot noch als aktueller Arbeitsstand brauchbar?
5. **Semantischer Konflikt:** Widerspricht der Arbeitsclaim Live-Evidenz oder dem aktuellen
   externen Operatorauftrag?

Ein einzelnes Boolean `fresh=true` kann diese Achsen nicht sicher abbilden.

---

## 2. Positiver Herkunftsbeweis

GitHub listet für `docs/PHASE2_CURRENT.md` genau einen pathbezogenen Commit:

- Commit `c9cffb5f1d5d3b5e88ab8757da0b7b23b3bdd0bd`,
- Zeit `2026-07-14T09:39:12Z`,
- Message `docs: add Phase 2 fresh-session cockpit`,
- Parent `41635ecdf8183fceb910e318e8aebcf95d2091f6`,
- Dateiblob `cb3e85c6a02bc776c2611bced87c6e9bf96ee995`,
- 210 Zeilen, 9.948 Bytes.

Der Blob ist am untersuchten Main-Head unverändert. Es existiert im Steward-Code kein
Reader, Writer, Generator oder sonstiger Call-Site-Verweis auf diese Datei. Alle Treffer
liegen in der Datei selbst.

Damit ist sie derzeit ein manuell committed Arbeitsdokument, kein Output des lebenden
Context-Systems und kein automatisch aktualisiertes Cockpit.

---

## 3. Interne Snapshotintegrität

Die Datei deklariert als Steward-Snapshot den Parent ihres eigenen Erzeugungscommits:

- Head `41635ecdf8183fceb910e318e8aebcf95d2091f6`,
- Tree `c00dedffc6ffda1c7e15c710a7205e770ac5464a`.

Diese Wahl vermeidet eine unmögliche Selbstreferenz auf den noch nicht existierenden
Dokumentcommit. Der Basiscommit ist Vorfahr des Erzeugungscommits und des untersuchten
Main-Heads.

Die im Cockpit für diesen Basisstand genannten Steward-Blobs wurden positiv gegen den
Basisbaum geprüft:

| Referenz | Deklarierter und belegter Blob |
|---|---|
| Phase 1 | `2f8a8e4e3b9624859c9ae25a754f3cd93120df66` |
| Phase 2 vor Cockpit-Commit | `c78e5dc3471c1dcfa28472966cbab1dc587f9e2d` |
| Federation Registry | `1fbb9f659ecfe493b3120ffe5307a3c6db7e6204` |
| lokale NADI-Inbox | `6cf1334520d8e2696844fd8e26f84b812edcad1b` |
| Relay-Seen | `b663a4c8f09d1892c28952dfd0395f160557d5cf` |
| Quarantäne-Index | `5356cd6de4cc432f0cc9413e8355cea9d4a6623b` |

Auch die drei Federation-Hub-Objekte sind weiterhin über GitHub erreichbar:

- Commit `02a6e57d001fc4a4a04a20abc8aee2c41e559c2c`,
- Tree `c2b1ff9ea9582ef5ba801fd04a2ae9bfe89b331d`,
- Mailbox-Blob `04b1605ce0c047a6ba845c021285e46556c89575`.

Die historischen Snapshotreferenzen sind damit content-addressed und intern konsistent.
Das beweist den damaligen Snapshot, nicht die heutige Wahrheit jeder Prosa-Aussage.

---

## 4. Review- und Authentizitätsgrenze

Der Erzeugungscommit:

- ist GitHub-seitig dem Account `kimeisele` zugeordnet,
- wurde direkt auf der Main-History erreicht,
- ist unsigned (`verified=false`, Grund `unsigned`),
- besitzt keinen belegten PR-Review.

Die aktuelle Main-Protection verlangt drei Statuschecks, aber keine Pull-Request-Reviews;
`enforce_admins` ist deaktiviert. Es existiert kein Ruleset, das für dieses Dokument eine
spezielle Reviewkette beweist.

Daraus folgt:

> Git beweist die exakten Bytes und ihre History-Position. Git beweist hier nicht, dass der
> Inhalt kryptographisch signiert, von einem zweiten Menschen reviewt oder als aktuelle
> Operatoranweisung autorisiert wurde.

Ein `blob_hash` ist Integrität, keine Wahrheit und keine Instruktionsautorität.

---

## 5. Beobachtete Freshness

Das Cockpit nennt `2026-07-14 11:36 Europe/Berlin` als Snapshotzeit. Sein Basiscommit ist
am untersuchten Main-Head 14 Commits zurück; seit dem Cockpit-Erzeugungscommit folgten 13
Heartbeat-Commits.

Seit dem Cockpit-Commit änderten sich im Vergleich ausschließlich Runtime-/State-Artefakte
wie Context, Federation-State und `CLAUDE.md`; kein Produktivcode und kein Workflow. Diese
Commitanzahl allein widerlegt daher nicht automatisch die kuratierte Agenda.

Gleichzeitig ist der enthaltene Arbeitsclaim nicht aktuell:

- Das Cockpit nennt Heartbeat-Fehlerpropagation als „exakt nächsten Auftrag“.
- Der aktuelle explizite Operatorauftrag dieser Untersuchung ist der read-only G0-
  Abschluss der Context-Bridge.
- Dieser Session-Auftrag ist absichtlich keine automatisch aus dem Repository ableitbare
  Quelle.

Das Dokument ist deshalb für seinen historischen Snapshot valide, aber sein Current-Work-
Claim steht im beobachteten Sessionkontext in Konflikt. Ein automatischer Heartbeat hätte
diesen Konflikt ohne authentifizierte Operatorquelle nicht selbst erkennen können.

---

## 6. Raw-Publication ist unzulässig

Die Datei enthält unter anderem:

- imperative Formulierungen wie „Lies zuerst“, „Du bist“, „Verbindlich“ und „Schreibe
  noch keinen Patch“,
- einen vollständigen Copy-Paste-Prompt,
- drei absolute lokale Pfade unter `/Users/ss/projects/...`,
- rollen- und governanceähnliche Regeln,
- einen konkreten nächsten Arbeitsauftrag.

OQ-12 verbietet lokale absolute Pfade im PUBLIC_SAFE-Root-Payload. OQ-18 trennt den
statischen Verfassungskern von kuratiertem Arbeitsstand. Deshalb darf das Dokument weder
roh inkludiert noch als C0-Governance behandelt werden.

Selbst ein später reviewtes Cockpit bleibt A4-Orientierung, nicht A3-Verfassung.

---

## 7. Verbindliche Statusachsen

Eine spätere Continuity-Quelle benötigt getrennte Statusfelder.

### 7.1 Acquisition-Status

| Status | Bedeutung |
|---|---|
| `present` | Pfad liegt als reguläre Datei am gepinnten Tree vor |
| `missing` | Pfad fehlt |
| `unsafe_path` | Symlink, falscher Dateityp, Pfadwechsel oder Größenlimit verletzt |
| `unreadable` | Blob/Encoding kann nicht sicher gelesen werden |

### 7.2 Git-/Review-Provenance

| Status | Bedeutung |
|---|---|
| `content_addressed` | Blob und Commit sind exakt gepinnt und erreichbar |
| `history_diverged` | deklarierter Basiscommit ist kein Vorfahr des untersuchten Heads |
| `review_verified` | definierte Review-/Signaturpolicy ist positiv belegt |
| `review_unverified` | Git-Herkunft vorhanden, aber erforderliche Review-/Signaturkette nicht belegt |

### 7.3 Schema-/Referenzintegrität

| Status | Bedeutung |
|---|---|
| `valid_snapshot` | Rolle, Basis und deklarierte Objektverweise sind maschinenprüfbar konsistent |
| `invalid_schema` | notwendige Metadaten fehlen oder sind typfalsch |
| `broken_reference` | Commit, Tree, Pfad oder Blob widerspricht der Deklaration |
| `unsupported_schema` | Schema-/Rollenversion ist unbekannt |

### 7.4 Freshness-/Konfliktstatus

| Status | Bedeutung |
|---|---|
| `current_verified` | explizite Freshness- und Konfliktbedingungen sind positiv erfüllt |
| `snapshot_only` | historisch valide, aktuelle Gültigkeit aber nicht positiv beweisbar |
| `stale` | reviewte Alters-/Änderungsgrenze überschritten oder referenzierter Arbeitsstand nachweislich überholt |
| `conflicting` | B1/B2-Evidenz oder authentifizierter aktueller Operatorauftrag widerspricht dem Work-Claim |
| `operator_unknown` | Bridge besitzt keine authentifizierte Quelle für den aktuellen Session-Auftrag |

Diese Achsen dürfen nicht zu einem einzigen Status kollabieren. Beispielsweise kann ein
Blob `content_addressed`, aber gleichzeitig `review_unverified` und `conflicting` sein.

---

## 8. Minimaler maschinenprüfbarer Metadatenvertrag

Vor Feature-Spec 02 muss eine kleine, versionierte Metadatenhülle festgelegt werden. Sie
benötigt mindestens:

- Schema- und Rollenkennung,
- Phase-/Dokumentkennung,
- kuratierten Zeitstempel,
- Basis-Repository, Basiscommit und Basistree,
- explizite relevante Pfad-/Blob-Referenzen,
- optionalen Vorgängerblob für eine Continuity-Kette,
- Kurationsmodus und nachweisbare Review-Provenance,
- einen typisierten Work-Claim-Identifier statt ausschließlich freier Überschrift.

Der eigene spätere Dokumentcommit darf wegen Selbstreferenz nicht als Inhaltsfeld
verlangt werden. Der Publisher pinnt den tatsächlichen Dokumentblob aus dem gelesenen
Git-Tree in seiner Provenance.

Altersgrenzen stammen aus statisch reviewter Konfiguration, nicht aus dem möglicherweise
manipulierten Arbeitsdokument selbst.

---

## 9. Freshness-Entscheidungsfolge

Die spätere Bridge muss in dieser Reihenfolge prüfen:

1. Live-Repository-Head und Tree pinnen.
2. Pfadmodus, Blobgröße, Encoding und Symlinkfreiheit prüfen.
3. Metadatenschema und Dokumentrolle validieren.
4. Existenz von Basiscommit/-tree und Ancestor-Beziehung prüfen.
5. deklarierte Pfad-/Blob-Referenzen am Basisbaum verifizieren.
6. Review-/Signaturprovenance unabhängig klassifizieren.
7. Änderungen seit Basis nach relevanten und volatilen Pfadklassen auswerten.
8. reviewte Altersgrenze nur als zusätzliches Freshness-Signal anwenden.
9. maschinenprüfbare Claims gegen neuere B1/B2-Evidenz vergleichen.
10. falls eine authentifizierte Operatorquelle existiert, Work-Claim vergleichen;
    andernfalls `operator_unknown` ausgeben.

Weder Datei-MTime, Dateiname, Commitanzahl noch Wall-clock-Alter allein beweisen
semantische Veraltung.

---

## 10. Konflikt- und Fallbackverhalten

| Zustand | Zulässige Darstellung | Verboten |
|---|---|---|
| Datei fehlt | Continuity unavailable/missing | alten Work-Claim aus Cache als aktuell ausgeben |
| Schema/Referenz ungültig | invalid; Quelle isolieren | freie Prosa als Ersatz parsen |
| Review unverified | Herkunft sichtbar unverified | als human-reviewed oder C0 behandeln |
| Snapshot valide, Currentness unbekannt | historischer/verifizierter Snapshot-Verweis | „current task“ behaupten |
| stale | Stale-Marker plus Basisreferenz | alte Agenda imperativ rendern |
| conflicting | beide Claims und Evidenzrang neutral benennen | Konflikt durch Prioritätsheuristik verstecken |
| unsafe/raw injection | Inhalt nicht übernehmen | Copy-Paste-Prompt oder lokale Pfade publizieren |

Fehler dieser optionalen Continuity-Quelle blockieren nicht den statischen Safe Fallback.
Sie blockieren aber jede positive Behauptung, die Bridge kenne den aktuellen Phasenauftrag.

---

## 11. Aktuelle Klassifikation

Für den gepinnten Zustand lautet die mehrdimensionale Bewertung:

| Achse | Ergebnis |
|---|---|
| Acquisition | `present` |
| Git-Integrität | `content_addressed` |
| Snapshotreferenzen | `valid_snapshot` |
| Review-Provenance | `review_unverified` |
| Current-Work-Freshness | `conflicting` im aktuellen Sessionkontext |
| automatisches Operatorwissen | `operator_unknown` |
| rohe Root-Publikation | unzulässig / `unsafe` |

Die Datei bleibt als historischer, nützlicher Arbeitsstand erhalten. Diese Klassifikation
ist kein Auftrag, sie umzuschreiben oder zu löschen.

---

## 12. Adversariale Testfolgen

Feature-Spec 02 benötigt mindestens:

1. fehlender Pfad,
2. Root-/Subdirectory-Symlink statt regulärer Datei,
3. ungültiges UTF-8, Übergröße und unbekannte Schemaversion,
4. Basiscommit fehlt oder ist kein Ancestor,
5. deklarierter Blob stimmt nicht mit dem Basisbaum überein,
6. unsigned/unreviewed Commit wird nicht als review-verified ausgegeben,
7. nur volatile Heartbeat-Commits machen den Work-Claim nicht automatisch stale,
8. relevante neuere Evidenz erzeugt stale/conflicting,
9. fehlende Operatorquelle erzeugt `operator_unknown`, nicht rekonstruierten Auftrag,
10. expliziter Operatorauftrag widerspricht dem Work-Claim,
11. Copy-Paste-Prompt, Markdown-Injection und lokale Pfade werden nie roh publiziert,
12. Cache enthält ältere Datei, Live-Pfad fehlt oder divergiert,
13. Wall-clock springt rückwärts,
14. gleiche Blobbytes an anderem unreviewten History-Pfad erhalten keine höhere
    Autorität.

---

## 13. Nicht belegbare Annahmen

Read-only nicht positiv belegbar sind:

- dass der GitHub-Account hinter dem Commit in diesem Moment der menschliche Operator war,
- dass der Inhalt außerhalb GitHubs separat reviewt wurde,
- welche zeitliche Maximalfrist für ein Cockpit fachlich richtig ist,
- welche späteren Pfadänderungen jeden konkreten Work-Claim invalidieren,
- wie ein aktueller Chatauftrag künftig authentifiziert ins Repository gelangen soll,
- welche Syntax die spätere Metadatenhülle verwendet.

Darum behauptet OQ-15 keine automatische semantische Vollprüfung freier Markdown-Prosa.

---

## 14. Entscheidung

OQ-15 ist geschlossen:

1. `PHASE2_CURRENT` ist optionale A4-Orientierung und keine SSOT oder C0-Quelle.
2. Git-Integrität, Review-Provenance, Referenzintegrität, Freshness und semantischer
   Konflikt werden getrennt klassifiziert.
3. Der heutige Blob ist ein intern konsistenter historischer Snapshot, aber reviewseitig
   unverified und im aktuellen Session-Work-Claim conflicting.
4. Ohne authentifizierte Operatorquelle muss die Bridge `operator_unknown` sagen.
5. MTime, Alter, Dateiname oder Commitanzahl allein beweisen keine Currentness.
6. Raw-Include ist wegen imperativer Prosa, Rollenregeln und lokalen Pfaden verboten.
7. Missing, invalid, stale und conflicting degradieren sichtbar und erzeugen niemals eine
   alte Agenda als aktuelle Instruktion.
8. Feature-Spec 02 benötigt vor Code einen kleinen versionierten Metadaten- und
   Reviewvertrag.

Diese Entscheidung ändert `PHASE2_CURRENT` nicht, autorisiert keine Implementation und
gibt G0 nicht frei.
