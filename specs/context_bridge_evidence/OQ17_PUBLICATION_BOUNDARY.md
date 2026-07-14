# OQ-17 — ÖFFENTLICHKEIT UND VERÖFFENTLICHUNGSGRENZE

> **Status:** EVIDENCE COMPLETE — Entscheidung für Master-Spec DRAFT 0.3
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `c437eed490da500626d1c48168dd6282ca08594e`
> **Steward-Tree:** `13f522ce0dd26110b00b5b8e2e4c709b8b6cfb34`
> **Scope:** Repository-Visibility, anonyme Erreichbarkeit, aktuell committed Context-,
> Session- und Federation-Flächen sowie die Grenze zwischen öffentlich transportierten
> Daten und privilegierter Laufzeitwahrnehmung. Keine Feld-Allowlist im Detail; diese
> folgt in OQ-12.

---

## 1. Positive Beweise — Repository-Visibility

GitHub meldete am Untersuchungsdatum für alle vier Kern-Repositories:

| Repository | Visibility | Private | Archived |
|---|---|---:|---:|
| `kimeisele/steward` | `public` | false | false |
| `kimeisele/steward-federation` | `public` | false | false |
| `kimeisele/agent-city` | `public` | false | false |
| `kimeisele/steward-protocol` | `public` | false | false |

Zusätzlicher anonymer Test ohne GitHub-Token:

- Steward-Repository-Metadaten: HTTP 200,
- Steward-Issues: HTTP 200,
- Federation-Hub-Metadaten: HTTP 200.

Damit sind Repository, Issues und Hub auf dem gepinnten Stand nicht nur für den
privilegierten `gh`-Client, sondern anonym öffentlich erreichbar.

---

## 2. Bereits öffentlich committed Flächen

Am gepinnten Steward-Tree sind folgende Blobs öffentlich abrufbar:

| Pfad | Blob | Bytes |
|---|---|---:|
| `CLAUDE.md` | `516d909f1b2445eee9e9ec8a366bdb9b12ab9688` | 4.046 |
| `.steward/context.json` | `cfca3dde04c37bd8ba4030e55f0a3ad375dc2cf0` | 12.699 |
| `.steward/memory.json` | `cc1d02042c1762a552ac24dc5969fcc3bde66643` | 24.966 |
| `.steward/sessions.json` | `e645b8c3a8d764201eec8749e908de5461a5bf45` | 19.481 |
| `data/federation/nadi_inbox.json` | `72eee9b9c659905bcb6f6bc4c66f1055b85bf47e` | 390.300 |
| `data/federation/nadi_outbox.json` | `e024f1f20f9e32f533cfe5bb2e17975b4eb6ee98` | 44.850 |
| `data/federation/peers.json` | `da9d02dd308e191cd6cef597956488f1d689dfb4` | 27.164 |

`AGENTS.md` existiert am gepinnten Head nicht.

---

## 3. Beobachtete öffentlich sichtbare Datenkategorien

### `.steward/context.json`

Top-Level:

- Projektname und absoluter Runner-Pfad,
- Senses,
- Health,
- Gaps,
- Sessions,
- Tasks,
- Federation,
- Immune,
- Campaign,
- Cetana,
- GitHub-Issues,
- Timestamp und Schemaversion.

Konkrete Kategorien:

- Task-ID, Titel, Priorität und Status,
- Issue-Nummer und Issue-Titel,
- Session-Task, Summary, Outcome, Timestamp, Token-/Round-Zähler, Errors,
  `files_written` und `buddhi_action`,
- Peer-ID, Capabilities, Status und Trust,
- absoluter CI-Runner-Pfad `/home/runner/work/steward/steward`.

### Persistierte State-Dateien

Ohne Rohwerte auszugeben ergab ein rekursiver String-Kategorienscan:

| Datei | Strings | absolute Pfadwerte | URLs | E-Mails | max. Stringlänge |
|---|---:|---:|---:|---:|---:|
| Sessions | 300 | 0 | 0 | 0 | 121 |
| Memory | 289 | 65 | 0 | 0 | 116 |
| Inbox | 6.130 | 0 | 0 | 0 | 134 |
| Peers | 359 | 0 | 0 | 0 | 64 |

Dieser Scan ist nur ein Kategoriensignal. Er beweist nicht die Abwesenheit von Secrets,
personenbezogenen Daten oder sensitiven Freitexten.

### Federation

- `peers.json` enthielt 73 persistierte Peers mit IDs, Fingerprints, Capabilities,
  Heartbeat-/Trust-/Statusdaten und Zeitstempeln.
- Die öffentliche Inbox enthielt 333 Nachrichten und 34 unterschiedliche Payload-Keys.
- Häufigste Operationen: Heartbeats, City Reports, Bottleneck Escalations,
  Agent Claims, World-State Updates und Diagnostic Reports.

Die Federation-Daten sind damit aktuell öffentlich transportiert. Das macht sie nicht zu
trusted Instructions und erlaubt nicht automatisch, jedes Payload-Feld in den besonders
salienten Root-Agentencontext zu kopieren.

---

## 4. Codebeweis — Collector-Grenzen

Am gepinnten Head:

1. `assemble_context()` übernimmt `cwd` direkt als `project.path`.
2. `_read_github_issues()` ruft `gh issue list` im übergebenen `cwd` auf und verwendet
   dabei die aktive GitHub-Authentifizierung des Prozesses.
3. Der Reader prüft nicht selbst, ob das Zielrepository public ist.
4. `GitSense` erfasst Branch, bis zu 500 Zeichen Dirty-File-Output, Stash-Anzahl,
   Recent-Commit-Texte und Remote-/CI-Zustand.
5. `_read_sessions()` übernimmt Task, Summary, Errors, `files_written` und
   `buddhi_action` aus dem SessionLedger.
6. `_read_tasks()` übernimmt dynamische Tasktitel.
7. `FederationInsightStage` kann Summary-/Titel-Freitext aus Inbox-Payloads rendern.

Der Collector ist damit generisch und kann bei lokalem oder privilegiertem Lauf Daten
sehen, die nicht allein deshalb öffentlich freigegeben sind, weil der aktuelle
Produktionslauf in einem öffentlichen Repository stattfindet.

---

## 5. Beweisgrenzen

Nicht bewiesen ist:

- dass zukünftige Federation-Nachrichten ausschließlich öffentliche Informationen
  enthalten,
- dass ein privilegierter `GH_TOKEN` niemals private Issues eines anderen Remotes sieht,
- dass lokale Branch-, Pfad-, Session- oder Fehlermetadaten öffentlich geeignet sind,
- dass ein einfacher String-/Secret-Scan alle sensitiven Daten erkennt,
- dass die Repository-Visibility dauerhaft public bleibt,
- dass bereits öffentlich committed State nachträglich als sicher klassifiziert werden
  kann.

„Bereits öffentlich“ ist ein Befund über Exposition, keine nachträgliche
Sicherheitsfreigabe.

---

## 6. Sicherheitsauswirkung

- Root-Context-Dateien sind hochsaliente Instruktionsartefakte und erhöhen Auffindbarkeit
  und Wirkung eingebetteter Daten, selbst wenn Rohdaten bereits irgendwo öffentlich sind.
- Der aktive `GH_TOKEN` ist eine Lesebefugnis, keine Veröffentlichungserlaubnis.
- Ein generischer lokaler Lauf kann private Arbeitsbaum-, Pfad-, Branch-, Issue- oder
  Sessiondaten wahrnehmen.
- Blocklisting oder Secret-Scanning reicht nicht, weil sensible Informationen nicht wie
  klassische Secrets aussehen müssen.
- Ein späterer Wechsel des Repositories von private zu public darf keine zuvor
  freigegebenen privaten Felder exponieren.

---

## 7. Entscheidung

1. Kanonische `CLAUDE.md`-/`AGENTS.md`-Outputs werden unabhängig von der momentanen
   Repository-Visibility als **PUBLIC-Release-Artefakte** klassifiziert.
2. Zulässig sind nur Felder, die bedingungslos für öffentliche Veröffentlichung geeignet
   und in einer expliziten Allowlist freigegeben sind.
3. Privilegierter Zugriff, lokale Sichtbarkeit oder Vorhandensein in `context.json`
   begründet keine Root-Publish-Erlaubnis.
4. Private oder unbekannt klassifizierte Issue-, Session-, Pfad-, Fehler-, Federation-
   und Annotationstexte sind default-deny.
5. Issue-Daten dürfen nur aus einer verifizierten öffentlichen Repository-Identität
   stammen; ein vorhandener `GH_TOKEN` reicht nicht.
6. Federation-Metadaten benötigen in OQ-12 eine explizite PUBLIC-Allowlist. Rohe
   Payload-Summaries sind nicht standardmäßig freigegeben.
7. Absolute Pfade, Dirty-Filenames, rohe Sessiontexte, Errors, `files_written` und
   authentifizierte URLs sind nicht standardmäßig Root-publishfähig.
8. Fehlt eine verlässliche Klassifikation, wird das Feld ausgelassen und die Quelle als
   degraded/withheld ausgewiesen; es wird keine gesunde Leere behauptet.
9. Bereits öffentlich exponierte problematische State-Felder werden als eigener
   bestehender Befund behandelt und nicht nebenbei im Context-Bridge-Feature bereinigt.

**OQ-17 ist geschlossen.** Die konkrete Feldmatrix bleibt ausschließlich OQ-12.
