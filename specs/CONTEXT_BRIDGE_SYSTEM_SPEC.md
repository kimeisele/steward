# CONTEXT-BRIDGE — MASTER-SYSTEMSPEZIFIKATION

> **Status:** DRAFT 0.3 — FÜR READ-ONLY G0-EVIDENCE FREIGEGEBEN; IMPLEMENTIERUNG GESPERRT
> **Datum:** 2026-07-14
> **Produktionsbasis:** `kimeisele/steward` auf
> `b2b633cb7f7e9e0f0b2164527034c2426541b7a7`
> **Zweck:** Verbindlichen technischen Vertrag für die dynamische Bereitstellung von
> Projektkontext an wechselnde Anthropic-, OpenAI- und interne Steward-Agenten schaffen.
> **Sperre:** Aus diesem Dokument darf noch kein Produktivpatch abgeleitet werden. Erst
> nach Review dieses Systemvertrags werden kleine, getrennte Feature-Spezifikationen
> erstellt und einzeln freigegeben.

---

## 0. WARUM DIESE MASTER-SPEC EXISTIERT

Die Context-Bridge liegt auf einer sicherheits- und produktivitätskritischen Grenze:

1. Das lebende Steward-System erzeugt maschinenlesbaren Zustand.
2. Ein Renderer verdichtet diesen Zustand zu agentenlesbarem Kontext.
3. GitHub Actions persistiert einen Teil der erzeugten Artefakte auf `main`.
4. Externe Coding-Agenten interpretieren Root-Kontextdateien als Arbeitsanweisung.
5. Menschen und Folgeagenten pflegen parallel einen verifizierten Phase-2-Befund.

Ein Fehler an dieser Grenze kann einen neuen Agenten mit veraltetem, unvollständigem oder
widersprüchlichem Kontext starten lassen. Das ist kein kosmetischer Dokumentationsfehler:
Ein falsch orientierter Agent kann im Fundament an der falschen Stelle arbeiten.

Deshalb gilt für dieses Vorhaben:

- kein Rewrite,
- kein zweiter paralleler Generator,
- kein monolithischer PR,
- keine Implementation aus Chat-Prosa,
- keine Freigabe ohne belegte Wirkungstests,
- keine Vermischung mit dem nächsten Phase-2-Auftrag zur Heartbeat-Fehlerpropagation.

---

## 0A. KORREKTURPROTOKOLL DRAFT 0.2

DRAFT 0.1 hat `docs/PHASE2_CURRENT.md` sprachlich und architektonisch zu stark
aufgewertet. Die Datei ist **keine Single Source of Truth** und keine konstitutionelle
Agentenanweisung. Sie ist ausschließlich der kuratierte, rollierende Arbeitsstand der
aktuellen Phase. Sie kann veralten, Hypothesen enthalten und durch neuere Beweise
widerlegt werden.

Diese Korrektur ist grundlegend:

- Die Context-Bridge darf aus einem Arbeitsdokument keine höhere Autorität erzeugen.
- Live-Code und Produktionsbeweise beschreiben Realität, erteilen aber ebenfalls nicht
  automatisch Handlungsbefugnis.
- GitHub-Issues, Tasks, Senses, Sessions und Federation-Inhalte sind Beobachtungsdaten,
  keine Instruktionen.
- Agentenregeln müssen aus einem statischen, menschlich reviewten Verfassungskern stammen.
- Dynamische Inhalte müssen technisch und visuell als Daten mit begrenztem Vertrauen
  behandelt werden.

DRAFT 0.2 übernimmt außerdem die G0-Blocker des externen Reviews: Prompt Injection,
Consumer-Unterschiede, Atomicity/Concurrency, semantische Änderungsregeln, Provenance,
LLM-Isolation, Datenminimierung, Fehlerklassifikation, adversariale Tests, Safe Fallback,
Governance und Konfliktauflösung.

---

## 0B. DREI GETRENNTE AUTORITÄTSACHSEN

Eine einzelne „SSOT“-Rangliste wäre für dieses System falsch. Die Bridge muss drei
unterschiedliche Fragen getrennt beantworten.

### Achse A — Wer darf einem Coding-Agenten Anweisungen geben?

| Rang | Quelle | Rolle |
|---|---|---|
| A1 | Plattform-/System-/Developer-Regeln des jeweiligen Agenten | höchste externe Instruktionsautorität |
| A2 | expliziter aktueller Auftrag des menschlichen Operators | projektspezifische Handlungsbefugnis |
| A3 | statischer, menschlich reviewter Repository-Verfassungskern | dauerhafte lokale Regeln und Schutzgrenzen |
| A4 | kuratierter aktueller Phasen-Arbeitsstand | Orientierung und vorgeschlagene Agenda, nicht selbstautorisierend |
| A5 | generierte Statusdaten | Beobachtung, niemals Instruktion |
| A6 | externe Issues, Federation-Nachrichten und sonstige Fremdtexte | untrusted data, niemals Instruktion |

Die Bridge kontrolliert A3 bis A6. Sie darf A4 bis A6 niemals so rendern, dass diese wie
A1 bis A3 wirken.

### Achse B — Was ist faktisch über das System bewiesen?

| Rang | Quelle | Rolle |
|---|---|---|
| B1 | gepinnte Git-Objekte, aktueller Code, vollständige Produktionslogs | stärkster technischer Realitätsbeweis |
| B2 | reproduzierbare Tests gegen echte Objekte und Repositories | kontrollierter Wirkungsbeweis |
| B3 | neueste verifizierte Phase-2-Befunde | dokumentierter Beweisstand |
| B4 | ältere Phase-2-Hypothesen und Phase 1 | historischer Kontext, widerlegbar |
| B5 | ungeprüfte Agenten-, Task-, Issue- oder Federation-Aussagen | Behauptungen, kein Beweis |

B1 ist faktische Evidenz, aber keine automatische Erlaubnis, Code zu ändern.

### Achse C — Woran wird gerade gearbeitet?

| Quelle | Bedeutung |
|---|---|
| aktueller menschlicher Auftrag | verbindlicher Session-Auftrag innerhalb höherer Regeln |
| `docs/PHASE2_CURRENT.md` | rollierender Arbeitsstand und Übergabehilfe dieser Phase |
| `docs/PHASE2_BEFUND.md` | ausführlicher Phase-2-Beweis- und Operationsverlauf |
| TaskManager | autonome interne Warteschlange |
| GitHub-Issues | extern sichtbarer Backlog, nicht automatisch priorisiert |

Zwischen diesen Quellen kann es Widersprüche geben. Die Bridge darf sie nicht zu einer
scheinbar konfliktfreien „Wahrheit“ verschmelzen.

---

## 1. QUELLEN UND BEWEISSTATUS

### 1.1 Verifizierte Produktionsobjekte

| Objekt | Produktionsstand | Beobachtung |
|---|---|---|
| Repository-Head | `b7e3aa3ca519bd1b3cfe233aa2bc7a4fcb9a31cb` | Tree `a6043e8fcdbc8dcd673221e3e41412e3870729ec` |
| `CLAUDE.md` | Blob `a240cd5468a4bc53c1f9e3c18f4b8be7cdc7abe7` | seit dem in OQ-16 belegten Git-NADI-Publish unverändert; keine verlässliche semantische Deduplizierung bewiesen |
| `.steward/context.json` | Blob `32843a45fccd3bd57566ff3779168d8ff87bc068` | Rohsnapshot läuft weiter und enthält stark volatile sowie nicht PUBLIC_SAFE Felder |
| `AGENTS.md` | nicht vorhanden | Codex erhält keinen repo-eigenen Root-Vertrag |
| `docs/PHASE2_CURRENT.md` | Blob `cb3e85c6a02bc776c2611bced87c6e9bf96ee995` | kuratierter Arbeitsstand der aktuellen Phase; keine SSOT |
| `docs/PHASE2_BEFUND.md` | vorhanden | ausführliches, fortlaufendes externes Gehirn |
| `docs/PHASE1_BEFUND_steward.md` | Blob `2f8a8e4e3b9624859c9ae25a754f3cd93120df66` | historisch, read-only |

### 1.2 Verifizierte Codequellen

| Bereich | Datei | Verifizierte Verantwortung |
|---|---|---|
| State Assembly | `steward/context_bridge.py` | erzeugt `context.json`-Payload aus Senses, Health, Gaps, Sessions, Tasks, Federation, Immune, Campaign, Cetana und Issues |
| Deterministischer Renderer | `steward/briefing.py` | erzeugt Briefing über die Stage-Pipeline und schreibt Root-`CLAUDE.md` |
| Stage-Pipeline | `steward/briefing_stages.py` | priorisiert und komprimiert Briefing-Sektionen |
| Heartbeat-Trigger | `steward/hooks/moksha_bridge.py` | schreibt `context.json`, danach deterministisches `CLAUDE.md` |
| LLM-Synthese | `steward/tools/synthesize_briefing.py` | erzeugt alternativ LLM-Text und schreibt selbst direkt |
| CLI-Reader | `steward/__main__.py` | zeigt `CLAUDE.md`, wenn Datei-MTime jünger als eine Stunde ist |
| Stale-Detektor | `steward/intent_handlers.py` | vergleicht MTimes von `context.json` und `CLAUDE.md` |
| Interner Instruction-Loader | `steward/agent.py` | definiert Loader für `.steward/instructions.md` und `CLAUDE.md`; produktiv unaufgerufen |
| Delivery | `.github/workflows/steward-heartbeat.yml`, `steward/git_nadi_sync.py` | Workflow-Post-Step staged explizit State; Git-NADI-Nebenpfad kann per Fallback den gesamten Worktree committen und direkt pushen |

### 1.3 Beweisregeln für spätere Änderungen

- Zeilennummern sind nur Navigationshilfen; Git-Objekte und Symbolnamen sind die Wahrheit.
- Vor jeder Feature-Spec wird `origin/main` erneut gepinnt.
- Wenn der Live-Code diesem Dokument widerspricht, wird zuerst diese Spec korrigiert.
- Phase 1 bleibt unverändert; Korrekturen werden in Phase 2 und den neuen Specs festgehalten.
- Arbeitsdokumente liefern Kontext, aber keine konstitutionelle Instruktionsautorität.
- Produktionsdaten werden nach Beweisart, Erreichbarkeit und beobachteter Wirkung bewertet.

---

## 2. TECHNISCHER IST-GRAPH

### 2.1 Deterministischer Heartbeat-Pfad

```text
MOKSHA Phase
  -> MokshaPersistenceHook (Priorität 50)
  -> MokshaFederationHook (Priorität 80)
       -> GitNadiSync.push() bei geflushten Federation Events
  -> MokshaContextBridgeHook (Priorität 85)
       -> assemble_context(cwd)
       -> write_context_json(cwd, context)
            -> .steward/context.json
            -> .steward/.context_hash
       -> nur wenn context.json geschrieben wurde:
            -> write_claude_md(cwd)
                 -> generate_briefing(cwd)
                 -> assemble_context(cwd) EIN ZWEITES MAL
                 -> BriefingPipeline.generate(...)
                 -> CLAUDE.md
```

Danach führt der GitHub-Workflow seinen Post-Step aus:

```text
git add -u -- .steward/ data/federation/
git add -- data/federation/
git commit
git pull --rebase --autostash
git push
```

Dieser Post-Step ist nicht die einzige Produktionsgrenze. `MokshaFederationHook` kann
vorher `GitNadiSync.push()` ausführen. Dessen fehlgeschlagenes enges Staging fällt auf
`git add -A` zurück und hat in Heartbeat `#5351` nachweislich `CLAUDE.md` sowie fremden
State in einem separaten Commit auf `main` publiziert.

Folge auf dem aktuellen Produktionsstand:

- `.steward/context.json` wird über mindestens zwei Commitpfade berührt.
- Root-`CLAUDE.md` wird im Workflow-Post-Step nicht explizit staged, kann aber über den
  Git-NADI-Nebenpfad unbeabsichtigt remote gelangen.
- Eine neu erzeugte `AGENTS.md` wäre im Post-Step nicht erfasst, könnte aber ebenfalls von
  einem überbreiten Worktree-Staging aufgenommen werden.
- Die zuvor beobachtete Root-Staleness war ein realer Snapshot, aber keine dauerhafte
  Delivery-Garantie. Der stärkere aktuelle Befund ist eine unkontrollierte Multi-Writer-
  und Multi-Delivery-Landschaft.

### 2.2 Optionaler LLM-Pfad

```text
SynthesizeBriefingTool.execute(...)
  -> assemble_context(cwd)
  -> collect_architecture_metadata()
  -> collect_validated()
  -> provider.invoke(...)
  -> dest.write_text(...)
       -> standardmäßig CLAUDE.md
       -> alternativ frei gewählter Pfad
```

Dieser Pfad ruft den in `briefing.py` deklarierten Single Writer nicht auf. Damit existieren
zwei Publisher mit unterschiedlicher Semantik:

- deterministisch und Stage-basiert,
- LLM-generiert und frei formatierbar.

Die Behauptung „SINGLE WRITER“ ist daher auf dem gepinnten Stand faktisch falsch.

### 2.3 CLI- und Freshness-Pfad

```text
steward --briefing
  -> existiert CLAUDE.md und MTime < 1 Stunde?
       -> ja: committed Datei ausgeben
       -> nein: Briefing im Speicher neu generieren und ausgeben
```

Separat:

```text
execute_synthesize_briefing()
  -> context.json fehlt: nichts tun
  -> CLAUDE.md fehlt: Synthese empfehlen
  -> context.json-MTime > CLAUDE.md-MTime: Synthese empfehlen
```

Freshness wird damit nicht aus Git-Objekten, Inhaltsidentität oder einem gemeinsamen
Snapshot abgeleitet, sondern aus lokaler Dateizeit. Checkouts, Rebases, Kopien und
unterschiedliche Writer können diese Semantik verfälschen.

### 2.4 Interner Steward-Konsument

`_load_project_instructions()` kennt folgende Priorität:

1. `.steward/instructions.md`
2. `CLAUDE.md`

Der Loader wird im produktiven Steward-Code jedoch nicht aufgerufen. Der interne
`StewardAgent` baut seinen effektiven Prompt aus Base-Prompt und Senses, nicht aus
`CLAUDE.md`.

**Befund:** Die Root-Kontextdatei ist aktuell primär ein Artefakt für externe Leser und
Coding-Agenten, nicht die aktive Gedächtnisquelle des internen Steward-Agenten. Die
produktive Erreichbarkeit dieses Loaders und des LLM-Synthesepfads wird getrennt von ihrer
bloßen Codeexistenz bewertet.

### 2.5 Externe Konsumenten

| Konsument | Erwartete Root-Datei | Semantik |
|---|---|---|
| Claude Code / Anthropic-Agent | `CLAUDE.md` | Projektkontext und Arbeitsregeln |
| Codex / OpenAI-Agent | `AGENTS.md` | hierarchisch geltende Repo-Anweisungen |
| Menschlicher Operator | Phase-2-Dokumente | überprüfbarer Operations- und Beweisstand |
| Steward CLI-Nutzer | `CLAUDE.md` oder Live-Render | Cockpit-Anzeige |
| Interner Steward-Agent | aktuell keine Root-Datei | Base-Prompt plus Senses |

Die Root-Dateien müssen deshalb neutral genug für externe Maintainer sein. Formulierungen
wie „Du bist Steward“ sind als interne Identitätsbehauptung für einen externen Coding-Agenten
mehrdeutig und werden in einer Feature-Spec gesondert bewertet.

---

## 3. DATENFLUSS UND SIGNALQUALITÄT

### 3.1 Aktuelle Context-Quellen

| Context-Key | Quelle | Kaltstart möglich | Im Briefing sichtbar |
|---|---|---:|---:|
| `project` | `cwd` | ja | ja |
| `senses` | `SenseCoordinator` | ja | ja |
| `health` | Cetana / Provider-Fallback | teilweise | ja |
| `gaps` | Memory / GapTracker | ja | ja |
| `sessions` | `.steward/sessions.json` | ja | nur Statistik |
| `tasks` | `SVC_TASK_MANAGER` | nein | **nein** |
| `federation` | Reaper, Marketplace, Gateway | teilweise | ja |
| `immune` | Service Registry | teilweise | ja |
| `campaign` | Campaign-State | ja | derzeit nicht klar sichtbar |
| `cetana` | Service Registry | nein | derzeit nicht klar sichtbar |
| `issues` | GitHub CLI | ja, bei Zugang | ja, bis zu 20 ungefiltert |
| Phase-2-Kontinuität | keine Quelle | nein | **nein** |

### 3.2 Aktueller Action-Fehler

`context.json` enthält autonome Tasks, darunter PENDING- und COMPLETED-Zustände. Der
Reader filtert Status gegen Stringwerte wie `done`, `completed` und `archived`. Auf dem
Produktionssnapshot erscheinen trotzdem Einträge mit Status `COMPLETED` unter `pending`.

Zusätzlich ignoriert `ActionStage` den gesamten `tasks`-Key. Es zeigt stattdessen bis zu
20 offene GitHub-Issues ohne belegte operative Priorisierung. Auf dem gepinnten Snapshot
dominieren wiederholte `review-request`-Issues das Briefing.

**Wirkung:** „Action“ ist weder eine treue Darstellung des TaskManagers noch eine
verlässliche Wiedergabe des aktuellen Operatorauftrags oder Phasen-Arbeitsstands.

### 3.3 Fehlende Projektkontinuität

`docs/PHASE2_CURRENT.md` enthält bereits:

- Rollen- und Sicherheitsvertrag,
- Entscheidungshierarchie,
- saubere Arbeitsumgebung,
- gepinnten Produktionsstand,
- abgeschlossene Milestones,
- den exakt nächsten Read-only-Auftrag,
- Übergabeanweisung für eine frische Session.

Keine Context-Bridge-Komponente liest oder referenziert dieses Dokument. Ein neuer Agent,
der nur `CLAUDE.md` oder künftig `AGENTS.md` erhält, kann daher nicht wissen, dass ein
separater, rollierender Phase-2-Arbeitsstand existiert. Daraus folgt ausdrücklich nicht,
dass dieser Arbeitsstand autoritativ oder immer aktuell ist.

### 3.4 Dedup- und Volatilitätsproblem

Die dokumentierte Hash-Deduplizierung ist nicht als dauerhafte Inhaltsgarantie belegt:

- `_last_hash` in `briefing.py` lebt nur im Python-Prozess.
- Der Briefing-Footer enthält eine Generierungszeit.
- `assemble_context()` setzt bei jedem Aufruf einen neuen Unix-Timestamp.
- `write_context_json()` hasht die gesamte serialisierte Payload einschließlich Timestamp.
- Der MOKSHA-Pfad assembliert den Context für `context.json` und das Briefing getrennt.

Damit können zwei Artefakte desselben Heartbeats unterschiedliche Snapshot-Zeitpunkte
tragen, und semantisch unveränderter Zustand kann dennoch neue Dateien erzeugen.

### 3.5 Trust-Zonen der Eingabedaten

| Zone | Quellen | Behandlung |
|---|---|---|
| T0 — Constitution | menschlich reviewter statischer Verfassungskern | darf imperative Schutzregeln enthalten; Heartbeat darf Inhalt nicht frei umformulieren |
| T1 — Curated Work State | `PHASE2_CURRENT`, `PHASE2_BEFUND` | Orientierung und Beweisverweise; niemals automatisch zur Verfassung erheben |
| T2 — Local Observations | Health, Senses, Tests, Git-Metadaten | deklarative Daten; Datenqualität und Zeitpunkt ausweisen |
| T3 — Internal Dynamic | TaskManager, Sessions, Gaps, Annotations | deklarative Daten; Status validieren; keine ungeprüfte Imperativsprache |
| T4 — External/Untrusted | Issues, PR-Titel, Federation-Nachrichten, Peer-Felder | allowlisted, begrenzt, normalisiert und eindeutig als untrusted data rendern |
| T5 — LLM Output | Syntheseantworten beliebiger Provider | nicht reproduzierbar; keine kanonische Publikation |

Die Vertrauenszone folgt der Herkunft, nicht dem Dateiformat. Ein Markdown-Dokument ist
nicht automatisch trusted; ein JSON-Feld ist nicht automatisch harmlos.

### 3.6 Prompt-Injection- und Rendergrenze

Die Root-Dateien werden von Agenten als Anweisungskontext interpretiert. Deshalb darf die
Bridge fremdbeeinflussbare Texte nicht roh in den Instruktionsraum kopieren.

Verbindliche Sicherheitsanforderungen:

1. Dynamische Quellen werden über eine explizite Feld-Allowlist ausgewählt.
2. Externe Texte werden als Datenwerte, nicht als Markdown-Struktur gerendert.
3. Überschriften, Listensteuerung, Codefences, Links, HTML und Zeilenumbrüche aus
   untrusted Feldern dürfen die Dokumentstruktur nicht kontrollieren.
4. Unicode-Steuerzeichen, bidirektionale Overrides und unsichtbare Trennzeichen werden
   erkannt und nach einer festzulegenden Policy verworfen oder sichtbar escaped.
5. Jedes variable Textfeld erhält Typ-, Zeichen- und Längenlimits.
6. Untrusted Inhalte dürfen keine imperativen Aufgaben im autoritativen Abschnitt werden.
7. Labels wie „UNTRUSTED OBSERVATION“ sind notwendig, aber allein nicht ausreichend;
   strukturelle Neutralisierung ist ebenfalls erforderlich.
8. Ein Parser-/Sanitizerfehler darf nicht in stilles „keine Daten vorhanden“ kollabieren.

Die genaue Encoding- und Escaping-Regel wird vor Implementation als eigener
maschinenprüfbarer Vertrag spezifiziert.

### 3.7 Datenminimierung und Leak-Schutz

Secret-Scanning allein reicht nicht. Die kanonische Ausgabe verwendet **Allowlisting**:

- nur nachweislich benötigte Felder,
- keine absoluten lokalen Pfade,
- keine Environment-Werte,
- keine Tokens, Credential-Fragmente oder authentifizierten URLs,
- keine rohen Stacktraces,
- keine vollständigen Session-Prompts oder Federation-Payloads,
- keine personenbezogenen oder internen Metadaten ohne begründeten Bedarf,
- keine privaten Repo-/Issue-Daten in öffentlich committed Artefakten ohne geklärten
  Repository- und Sichtbarkeitsvertrag.

Für jede dynamische Quelle muss die Feature-Spec dokumentieren: Zweck, ausgewählte
Felder, maximale Länge, Sanitization, Fallback und Veröffentlichungsrisiko.

### 3.8 Fehler- und Degradationsklassen

| Zustand | Bedeutung | Publish-Verhalten |
|---|---|---|
| `valid` | Quelle verfügbar, Schema und Werte valide | Daten dürfen nach Trust-Policy einfließen |
| `empty` | erfolgreicher, valider Read ohne fachliche Datensätze | ehrliche Leere; nicht mit Fehler gleichsetzen |
| `not_configured` | Quelle ist für diesen Laufmodus nachweislich nicht eingerichtet | als nicht konfiguriert kennzeichnen; keine Verfügbarkeitsaussage erfinden |
| `unavailable` | konfigurierte Quelle nicht erreichbar | degradierter Marker; keine erfundene Leere |
| `invalid` | Quelle vorhanden, aber Typ/Schema/Inhalt widersprüchlich | Quelle isolieren; Fehler sichtbar machen |
| `stale` | Alter/Freshness-Grenze nachweislich überschritten | als stale markieren; nicht als aktuell darstellen |
| `unsafe` | Injection-, Leak-, Symlink- oder Pfadprüfung fehlgeschlagen | kanonischen Publish blockieren |
| `unsupported` | Schema, Enum oder Feldversion wird nicht verstanden | unbekannten Teil default-deny; je nach Sicherheitsrelevanz degradieren oder blockieren |
| `required_missing` | für sicheren Vertrag notwendige Vertragsquelle fehlt | normalen dynamischen Publish blockieren oder verifizierten Safe Fallback verwenden |

Required sind nicht pauschal alle Live-Beobachtungen, sondern der sicherheitsrelevante
Publikationsvertrag: validierter Verfassungskern oder verifizierter Safe Fallback,
Repository-/Generator-/Schemabezug, normalisiertes Modell, Hash-/Provenancebildung,
PUBLIC_SAFE-Validierung und Output-Validierung. Live-Quellen sind observational und
dürfen ausfallen, ohne dass daraus ein gesunder Zustand oder eine leere Agenda erfunden
wird. Die vollständige Entscheidung und Source-Matrix steht im Evidence-Paket OQ-13.
Ein leeres Dict oder eine leere Liste ist kein zulässiger Universal-Fallback.

---

## 4. VERIFIZIERTER PROBLEMKATALOG

| ID | Problem | Beweisstatus | Risiko |
|---|---|---|---|
| CB-01 | Root-Dateien werden im Workflow-Post-Step nicht explizit staged, können aber über `GitNadiSync` per Worktree-Fallback unbeabsichtigt publiziert werden | Code plus Produktionsrun `#5351` belegt | unkontrollierte Root-Governance, gemischte Snapshots und potenziell veraltete oder ungeprüfte Sessions |
| CB-02 | `AGENTS.md` fehlt vollständig | Produktion belegt | Codex erhält keinen dynamischen Repo-Vertrag |
| CB-03 | zwei unabhängige Briefing-Publisher | Code belegt | Format- und Inhaltsdrift |
| CB-04 | Phase-2-Cockpit fehlt im Context-Graph | Code-/Output-belegt | Verlust der operativen Kontinuität |
| CB-05 | autonome Tasks werden nicht gerendert | Code belegt | falsche Agenda |
| CB-06 | COMPLETED-Tasks erscheinen als pending | Produktionspayload belegt | falsche Dringlichkeit |
| CB-07 | 20 Review-Issues dominieren Action | Produktionsoutput belegt | Signal-Rausch-Verhältnis kollabiert |
| CB-08 | Freshness basiert auf MTime | Code belegt | Checkout-/Writer-abhängige Fehlentscheidung |
| CB-09 | Prozesslokaler Briefing-Hash ist keine persistente Dedup-Garantie | Code belegt | unnötige Writes / falsches Vertrauen |
| CB-10 | Context wird innerhalb eines Publikationszyklus mehrfach assembliert | Code belegt | Snapshot-Skew |
| CB-11 | interner Instruction-Loader ist unverdrahtet | Call-Site-Suche belegt | Dokumentation überschätzt internen Nutzen |
| CB-12 | Toolbeschreibung nennt `.steward/CLAUDE.md`, Default schreibt Root-Datei | Code belegt | Operator-/Agentenverwirrung |
| CB-13 | keine Trust-Klassifikation dynamischer Quellen | Spec-/Codebefund | Prompt Injection wird zur Agentenanweisung |
| CB-14 | keine allowlist-basierte Datenminimierung | Spec-/Codebefund | Informationsleck trotz Secret-Scanner |
| CB-15 | dynamische Governance und Status sind nicht hart getrennt | Architekturdefizit | Heartbeat kann Agentenvertrag umschreiben |
| CB-16 | keine belegte lokale Transaktions-/Concurrency-Semantik | offene Architektur | halb veröffentlichte oder gemischte Snapshots |
| CB-17 | „semantische Änderung“ ist undefiniert | offene Architektur | falsche Dedup- und Freshness-Entscheidungen |
| CB-18 | Provenance unterscheidet canonical/preview/degraded nicht ausreichend | Outputbefund | Agent kann Herkunft und Gültigkeit nicht bewerten |
| CB-19 | kein verifizierter Kill-Switch oder Safe Fallback | Operationsdefizit | fehlerhafte Governance publiziert weiter |
| CB-20 | Konflikte zwischen Operatorauftrag, Arbeitsstand, Live-Signal und Backlog ungelöst | Architekturdefizit | deterministischer Text, aber falsche Handlungspriorität |
| CB-21 | Heartbeat installiert `steward-protocol` vom jeweils aktuellen Default-Branch ohne Commit-Pin | Workflow und Produktionslog belegt | Cross-Repo-Typverträge können zwischen Steward-Commits driften und sind ohne Protocol-Provenance nicht reproduzierbar |
| CB-22 | Issue-Reader liefert nur Nummer und Titel, während der Renderer nicht gelieferte Labels erwartet; Eligibility und Prioritätsmetadaten fehlen | Code, Live-Issue-Inventar und Produktionsoutput belegt | untrusted Neuigkeit ersetzt kuratierte Relevanz; Labels suggerieren eine nicht existierende Auswahl |
| CB-23 | `PHASE2_CURRENT` besitzt keinen maschinenprüfbaren Rollen-, Freshness-, Review- oder Konfliktvertrag und enthält imperative Prosa sowie lokale absolute Pfade | Git-Historie, Inhalt und fehlende Call-Sites belegt | content-addressierter Snapshot kann fälschlich als aktuelle autoritative Anweisung oder PUBLIC_SAFE-Text erscheinen |

---

## 5. ZIELVERTRAG

### 5.1 Funktionale Ziele

Z1. Ein einziges kanonisches semantisches Kernmodell wird pro Publikationsvorgang erzeugt.

Z2. Root-`CLAUDE.md` und Root-`AGENTS.md` stammen aus demselben **semantischen Kernmodell**.
Solange kein konkreter Consumer-Unterschied eine Abweichung erzwingt, gilt Byteidentität
als bevorzugter Default: eine kanonische Payload, zwei vollständig identische Dateien,
keine vorsorglichen tool-spezifischen Hüllen. Abweichungen benötigen einen belegten
Discovery-, Scope-, Prioritäts- oder Formatgrund, einen eigenen Contract-Test und eine
explizite Reviewentscheidung. Byteidentität bleibt reversibel, wird aber nicht ohne Grund
aufgegeben.

Z3. Eine frische externe Session erkennt innerhalb der ersten Bildschirmseite:

- dass sie an Steward und der Föderation arbeitet,
- dass Phase 1 read-only ist,
- dass `docs/PHASE2_CURRENT.md` nur den rollierenden Arbeitsstand der aktuellen Phase
  dokumentiert und keine SSOT ist,
- dass Live-Realität ältere Befunde korrigieren darf,
- welcher Arbeits- und Sicherheitsvertrag gilt.

Z4. Das Briefing unterscheidet klar zwischen:

- externer Laufzeitautorität des aktuellen Operatorauftrags, die nicht automatisch als
  Bridge-Datenquelle verfügbar ist,
- rollierendem, widerlegbarem Phasen-Arbeitsstand,
- lebendem Systemzustand,
- autonomer Steward-Taskqueue,
- GitHub-Issues,
- historischer Dokumentation.

Z5. Der Heartbeat bindet den Root-Payload über Provenance an genau einen Context-Snapshot.
Ändert sich ein Consumer-Output, werden alle dadurch geänderten Consumer-Dateien und der
zugehörige Context-State explizit im selben Git-Commit ausgeliefert.

Z6. Unveränderter semantischer Output erzeugt keinen unnötigen Root-Datei-Diff.

Z7. Fehler bei der Context-Publikation werden beobachtbar; sie dürfen nicht durch pauschale
`except Exception`-Behandlung unsichtbar werden.

Z8. Ein statischer, menschlich reviewter Verfassungskern ist technisch von dynamischem
Status getrennt. Der Heartbeat darf den Verfassungskern weder durch untrusted Daten noch
durch LLM-Synthese semantisch verändern.

Z9. Jede dynamische Quelle trägt Trust-, Validity-, Freshness- und Provenance-Status.

Z10. Kanonische Publikation verwendet nur allowlistete und sanitizte Datenfelder.

Z11. Ein Publish ist über drei getrennte Grenzen nachvollziehbar: Snapshot-Erzeugung,
lokale Dateipublikation und Git-Delivery.

Z12. Der kanonische Pfad besitzt einen getesteten Safe Fallback und einen operativ
verifizierten Stop-Mechanismus, bevor automatische Governance-Publikation aktiviert wird.

Z13. Fehlt eine ausdrücklich authentifizierte Quelle für einen Operatorauftrag, behauptet
der generierte Repository-Context ausdrücklich nicht, den aktuellen menschlichen
Session-Auftrag zu kennen oder zu repräsentieren.

### 5.2 Nicht-funktionale Ziele

- deterministisch im normalen Heartbeat-Pfad,
- offline/kaltstartfähig mit klar ausgewiesener Datenqualität,
- minimale Tokenlast,
- keine geheimen oder lokalen Pfade im veröffentlichten Output,
- keine Owner-/Org-Hardcodes,
- Git- und Dateischreibvorgänge mit engem Scope,
- rückwärtskompatibler Einstieg für bestehende `write_claude_md()`-Caller,
- testbar ohne echte LLM-Aufrufe,
- allowlist-basierte Datenminimierung statt nachträglicher Blocklist,
- adversarial testbar gegen Injection, Unicode-, Pfad-, Symlink- und Race-Angriffe.

### 5.3 Bewusste Nicht-Ziele

- kein Rewrite der Stage-Pipeline,
- keine Neuentwicklung eines Memory-Systems,
- keine automatische Umschreibung von Phase 1 oder Phase 2,
- keine vollständige Einbettung des 7.761-Zeilen-Phase-1-Befunds,
- keine Lösung der Heartbeat-Fehlerpropagation aus `PHASE2_CURRENT` §6,
- keine Änderung der Föderationsidentität oder NADI-Semantik,
- keine Neustrukturierung aller GitHub-Issues,
- keine sofortige Verdrahtung des internen Steward-Agenten an Root-Kontextdateien.

---

## 6. INVARIANTEN

| ID | Invariante | Verifikation |
|---|---|---|
| I-01 | Beide Root-Dateien sind standardmäßig byte-identische Publikationen einer Payload; Abweichung nur bei positiv belegtem Consumer-Zwang | Bytevergleich als Default; abweichender Consumer-Contract-Test plus Reviewentscheidung |
| I-02 | Es existiert genau ein kanonischer Publisher für Root-Kontext | Call-Graph-Test / Code-Review |
| I-03 | Phase 1 wird nie durch die Bridge verändert | Git-Diff-Gate |
| I-04 | Phase-2-Dokumente bleiben menschlich/agentisch kuratierte Beweisquellen | keine Auto-Writes in `docs/` |
| I-05 | Der Publisher erhält einen einmal assemblierten Snapshot | Unit-/Integrationstest |
| I-06 | Root-Dateien enthalten ausschließlich allowlistete, minimierte und sanitizte dynamische Felder | Schema-, Leak- und adversariale Fixture-Tests |
| I-07 | Workflow-Staging bleibt explizit; kein `git add -A` oder Force-Add | Workflow-Test / Review-Gate |
| I-08 | Fehlende, ungültige und stale Quellen sind unterscheidbar; keine davon erscheint als gesunde Leere | Kaltstart- und Fehlerschematests |
| I-09 | LLM-Ausgabe darf keine kanonische Root-Datei publizieren | negativer Tool-Vertragstest |
| I-10 | Action zeigt keine abgeschlossenen Tasks als offen | echte Statusobjekte im Test |
| I-11 | Review-Issues und andere T4-Daten können weder Verfassung noch Operatorauftrag verdrängen | Trust-/Rendering-Test |
| I-12 | Stable contract paths sind erlaubt; volatile Zustandswerte werden nicht hardcodiert | Spec-/Code-Review |
| I-13 | Der statische Verfassungskern kann nicht durch dynamische Felder strukturell erweitert oder überschrieben werden | Boundary-/Injection-Test |
| I-14 | Beide Outputs weisen Payload-Hash, Generatorquelle, Modus und Degradationsstatus aus | Provenance-Test und Produktionsblob |
| I-15 | Unsichere Zielpfade, Symlinks oder partielle Publikation führen nicht zu stiller Erfolgsbehauptung | Dateisystem-Adversarialtest |
| I-16 | `PHASE2_CURRENT` wird nur als aktueller Arbeitsstand bezeichnet und darf fehlen oder stale sein, ohne zur erfundenen Wahrheit zu werden | Continuity-Degradationstest |
| I-17 | Dynamische Daten dürfen keine rohe Markdown-Dokumentstruktur kontrollieren | Sanitization-/Injection-Test |
| I-18 | Die verbindliche Phase-1-read-only-Regel gehört zum statischen Verfassungskern und hängt nicht von `PHASE2_CURRENT` ab | Constitution-Contract- und Missing-Continuity-Test |
| I-19 | Kanonische Root-Context-Dateien werden als PUBLIC-Release-Artefakte behandelt und enthalten nur bedingungslos öffentlich geeignete Allowlist-Felder | Public-data Contract, unauthenticated artifact audit und negative private-source fixtures |

---

## 7. DESIGNOPTIONEN

### Option A — Zwei getrennte Generatoren

`write_claude_md()` bleibt bestehen; daneben entsteht `write_agents_md()` mit eigener
Logik.

**Vorteil:** kurzfristig einfach.
**Nachteile:** sofortige Driftgefahr, doppelte Tests, widerspricht CB-03 und I-02.
**Bewertung:** VERWERFEN.

### Option B — Symlink `AGENTS.md -> CLAUDE.md`

**Vorteil:** physisch nur eine Datei.
**Nachteile:** plattform-/toolabhängig, unklare Agenten- und GitHub-Darstellung, keine
saubere unabhängige Existenzprüfung.
**Bewertung:** VERWERFEN.

### Option C — Eine Payload, ein Publisher, zwei vollständig dynamische Ziele

Der bestehende deterministische Renderer erzeugt einmal Text. Ein zentraler Publisher
vergleicht und publiziert denselben Text nach `CLAUDE.md` und `AGENTS.md`. Bestehende
Caller werden über einen kompatiblen Wrapper weitergeführt.

**Vorteile:** kleiner Root-Cause-Schnitt, zentrale Tests, kein Renderer-Rewrite.
**Risiken:** Der Heartbeat kontrolliert den gesamten Agentenvertrag; untrusted Daten oder
Rendererfehler können Governance überschreiben. Bytegleichheit kann Consumer-Unterschiede
verdecken.
**Bewertung:** ALS VOLLSTÄNDIG DYNAMISCHES MODELL VERWERFEN.

### Option D — Root-Dateien nur als statische Pointer

Beide Dateien enthalten ausschließlich einen Link auf `PHASE2_CURRENT`.

**Vorteil:** sehr klein.
**Nachteile:** verliert lebenden Systemzustand und bestehende Briefing-Funktionalität.
**Bewertung:** VERWERFEN.

### Option E — Statischer Verfassungskern plus begrenzter generierter Datenblock

Ein menschlich reviewter, versionierter Kern definiert Rolle, Schutzgrenzen, Trust-Zonen
und Leseprioritäten. Der deterministische Publisher erzeugt ausschließlich einen klar
abgegrenzten Status-/Provenance-Block aus allowlisteten Daten. Beide Consumer-Dateien
werden aus demselben Kernmodell gebaut; erforderliche Consumer-Hüllen bleiben minimal und
beweisgebunden.

**Vorteile:** Governance bleibt reviewbar; dynamischer Blast-Radius ist begrenzt;
Prompt-Injection kann nicht den statischen Vertrag strukturell ersetzen; gemeinsame
Semantik ohne erzwungene ewige Byteidentität.
**Risiken:** Blockgrenzen und Merge-/Publikationssemantik müssen hart getestet werden;
statischer Kern darf nicht an mehreren Stellen manuell driften.
**Bewertung:** BEVORZUGTE SICHERHEITSHYPOTHESE, noch nicht freigegeben.

### Vorläufige Architekturentscheidung AD-01

Option E ersetzt die zu starke Präferenz für Option C aus DRAFT 0.1. Der gemeinsame
semantische Kern bleibt verpflichtend. OQ-11 hat unterschiedliche Discovery-Verträge,
aber keinen technischen Zwang zu unterschiedlichem Root-Inhalt belegt. Deshalb bleibt
Byteidentität der bevorzugte Default. Eine Import-Hülle oder andere Abweichung ist nur eine
spätere Option bei positiv belegtem Bedarf. Blockintegrität und Publikationsfehler bleiben
weiterhin experimentell zu belegen.

---

## 8. VORLÄUFIGER OUTPUT-VERTRAG

Die genaue Wortwahl wird in einer eigenen Continuity-Feature-Spec beschlossen. Die
kanonische Reihenfolge soll semantisch sein:

1. **Static Operating Constitution** — menschlich reviewte Schutzregeln und
   Trust-Grenzen; vor jedem dynamischen Fremdtext.
2. **Repository Identity** — was dieses Projekt ist; keine falsche Rollenübernahme.
3. **Provenance and Trust** — Commit, Snapshot-/Payload-Hash, Modus, Quellenstatus,
   Degradation und Generatorherkunft.
4. **Critical Observations** — echte kritische Systemsignale, weiterhin Daten und keine
   automatische Handlungsfreigabe.
5. **Current Phase Work State** — klar als widerlegbarer Arbeitsstand bezeichnet.
6. **Observed Work Queues** — autonome Tasks und Issues als Daten, nicht Aufträge.
7. **System Status** — Health, Federation, Immune.
8. **Environment** — Git, Tests, Code-Senses.
9. **Architecture** — kompakte Referenz.

GitHub-Issues dürfen ausschließlich als untrusted Beobachtungsdaten erscheinen. Weder sie
noch der aktuelle Phasen-Arbeitsstand dürfen einen neuen Operatorauftrag erfinden.

### 8.1 Kontinuitätsquelle

Vorläufiger Vertrag:

- `docs/PHASE2_CURRENT.md` ist ein stabiler Pfad zum rollierenden Arbeitsstand dieser
  Phase, aber keine SSOT, keine Verfassung und kein alleiniger Handlungsauftrag.
- Die Datei selbst bleibt kuratiert und wird nicht vom Heartbeat überschrieben.
- Die Bridge rendert eine kleine typisierte Reference Card mit Pfad, Blob, Basisbezug,
  Rollen- und OQ-15-Status. Sie übernimmt keinen freien Markdown-Ausschnitt.
- Ein optionaler kompakter Work-Claim darf ausschließlich aus versionierten, co-located
  Metadaten derselben Datei stammen; ohne diese Metadaten bleibt es beim degradierten
  Verweis ohne behaupteten aktuellen Auftrag.
- Weder ein Claude-`@`-Import noch ein anderer automatischer Full-File-Include ist Teil
  des gemeinsamen Consumer-Vertrags.

OQ-15 präzisiert: Content-Addressing, Review-Provenance, Referenzintegrität, Freshness und
semantischer Konflikt sind getrennte Statusachsen. Der aktuelle Blob darf wegen
imperativer Prosa und lokalen absoluten Pfaden nicht roh in Root-Dateien übernommen
werden. Ohne authentifizierte Operatorquelle lautet der Session-Auftragsstatus
`operator_unknown`, nicht der aus dem Cockpit rekonstruierte Work-Claim.

Ein stabiler Dokumentpfad ist kein verbotener Hardcode. Er verleiht dem Dokument jedoch
keine höhere Autorität. Verboten sind volatile
Produktionswerte, Identitäten, Owner, Branch-Heads oder Aufgabeninhalte im Quellcode.

### 8.2 Provenance als Sicherheitsvertrag

Provenance ist kein dekorativer Footer. Jeder kanonische Output muss maschinenlesbar und
für Menschen sichtbar mindestens unterscheiden:

- `mode`: `canonical`, `preview`, `degraded` oder `safe_fallback`,
- Generator-Repository und Generator-Commit,
- Context-Repository und beobachteter Head,
- `snapshot_id` des einmal assemblierten Eingabemodells,
- `payload_hash` des gemeinsamen semantischen Kerns,
- Consumer-Format/Schema-Version,
- Status jeder verwendeten Quelle nach dem vollständigen OQ-13-Vertrag, insbesondere
  `valid`, `empty`, `not_configured`, `unavailable`, `invalid`, `stale`, `unsafe` oder
  `unsupported`,
- Publikationszeit als Provenance, nicht als alleinige Freshness-Wahrheit,
- Hinweis, ob der Output deterministisch oder LLM-beteiligt ist.

Ein Preview darf niemals dieselbe Kennzeichnung wie ein kanonischer Heartbeat-Publish
tragen.

#### 8.2.1 Hash-Domain-Vertrag

Vor Implementation werden drei Domains getrennt spezifiziert:

1. `snapshot_hash`: versioniertes, normalisiertes Eingabemodell,
2. `payload_hash`: versionierter semantischer Ausgabekern vor Consumer-Verpackung,
3. optional `consumer_output_hash`: konkrete Bytes der jeweiligen Root-Datei.

Kein Hash umfasst sich selbst. Publikationszeit und andere C4-Metadaten gehören nicht
automatisch in den semantischen Kern. Feldreihenfolge, Unicode-Normalisierung, Zahlen-,
Null- und Enum-Darstellung sowie Sortierung ungeordneter Mengen müssen deterministisch und
schema-versioniert sein.

### 8.3 Drei Transaktionsgrenzen

„Ein Publisher“ reicht nicht. Der End-to-End-Vertrag umfasst drei Grenzen:

1. **Snapshot-Transaktion:** Alle Renderer erhalten dasselbe immutable normalisierte
   Context-Modell und dieselbe `snapshot_id`. Kein zweites `assemble_context()`.
2. **Lokale Publikation:** Zielpfade werden auf Root-Bindung, reguläre Datei und
   Symlinkfreiheit geprüft. Beide Consumer-Ausgaben werden vollständig vorbereitet,
   validiert und als gemeinsamer Publish-Vorgang behandelt. Partieller Erfolg darf nicht
   als Erfolg gelten; der nächste Lauf muss ihn erkennen und reparieren.
3. **Git-Delivery:** Genau die validierten Root-Dateien und der zugehörige Context-State
   werden gemeinsam staged. Vor Commit werden staged Payload-Hashes gegen den Snapshot
   geprüft. Der Git-Commit ist die Remote-Transaktionsgrenze, nicht der lokale Rename.

Die bestehende GitHub-Actions-Concurrency schützt nur gleichnamige Workflow-Läufe. Sie ist
noch kein Beweis gegen manuelle, lokale oder anderweitig gestartete Publisher. Locking,
Crash-Recovery, Filesystem-Annahmen und Parallelprozesse bleiben G0-Blocker.

Zwei unabhängige Root-Dateien können auf üblichen Dateisystemen nicht als echte atomare
Gruppe ersetzt werden. Der Vertrag verspricht daher nur atomare Ersetzung je Datei,
Erkennung gemischter Generationen, keine positive Erfolgsmeldung bei Teilzustand,
deterministische Reparatur und den gemeinsamen Git-Commit als Remote-Transaktionsgrenze.

### 8.4 Klassen semantischer Änderungen

„Semantisch unverändert“ wird nicht über eine pauschale Ignore-Liste definiert.

| Klasse | Beispiele | Vorläufige Delivery-Semantik |
|---|---|---|
| C0 — Constitution | Schutzregel, Trust-Policy, Consumer-Vertrag | nur menschlich reviewter PR; nie Heartbeat-Autowrite |
| C1 — Safety Critical | critical/degraded/unsafe, Quellenvalidität, Identity-Konflikt | sofort publishwürdig; darf nicht wegdedupliziert werden |
| C2 — Operational | offene Taskmenge, Health-Klasse, Federation-Zustandsklasse | publishwürdig nach definierter Normalisierung |
| C3 — Diagnostic | Zähler, gerundete Metriken, Sessionstatistik | nur bei festgelegter Schwelle oder Aggregation |
| C4 — Volatile Provenance | Wall-clock, last-seen-Sekunden, reine Reihenfolge ohne Bedeutungswechsel | allein kein Root-Diff-Auslöser |

Jedes Feld muss vor Implementation genau einer Klasse zugeordnet werden. Ein Hash darf nur
über kanonisch normalisierte, klassifizierte Daten gebildet werden. Sicherheitsrelevante
Freshness-Felder dürfen nicht pauschal als volatil entfernt werden.

### 8.5 Konflikt- und Prioritätsanzeige

Die Bridge löst keine Governance-Konflikte durch Textreihenfolge. Wenn Quellen
widersprechen, rendert sie den Konflikt explizit:

- Sicherheitskritische Live-Signale werden als Beobachtung vorangestellt, autorisieren
  aber keinen beliebigen Fix.
- Der aktuelle Operatorauftrag bleibt die Handlungsbefugnis der Session.
- `PHASE2_CURRENT` beschreibt nur den bisherigen Arbeitsstand und kann vom Operatorauftrag
  oder neuem B1-Beweis überholt sein.
- TaskManager und Issues bleiben getrennte Queues ohne automatische Prioritätsfusion.
- Ungeklärte Konflikte erzeugen einen `degraded`- oder `conflict`-Marker statt einer
  erfundenen eindeutigen Agenda.

---

## 9. FEATURE-SCHNITT — KEIN MEGA-PR

Nach Freigabe dieser Master-Spec werden getrennte ausführbare Specs
erstellt. Jede Spec erhält eigenen Pre-Flight, rote Regression, Patch-Grenze und Rollout.

### Feature-Spec 00 — Trust-, Consumer- und Governance-Vertrag

**Scope:** Source-Trust-Matrix, statischer Verfassungskern, dynamische Blockgrenze,
Consumer-Discovery/Scope/Priorität, Allowlist, Sanitization und Core-File-Governance.
**Charakter:** zunächst read-only/contract-only; kein Publisher-Code.
**Exit:** Erst wenn dieser Vertrag adversarial geprüft ist, darf Feature 01 beginnen.

### Feature-Spec 01 — Sicherer kanonischer Publisher plus Delivery

**Scope:** ein Snapshot, ein semantisches Kernmodell, statischer Kern plus begrenzter
Datenblock, lokale Transaktion, Provenance, LLM-Publikationsverbot und explizite gemeinsame
Git-Delivery.
**Nicht enthalten:** Phase-2-Inhaltsübernahme, Task-Priorisierung.
**Hinweis:** Publisher und Delivery bleiben getrennte Codeänderungen, teilen aber einen
untrennbaren End-to-End-Abnahmevertrag; keine lokale „fertig“-Behauptung ohne Delivery-Test.

### Feature-Spec 02 — Current-Phase Reference Card

**Scope:** optionale, typisierte und nichtautoritative Reference Card für
`PHASE2_CURRENT` mit co-located Metadaten sowie Freshness-/Missing-/Conflict-Semantik.
Keine freie Markdown-Extraktion und kein automatischer File-Include. Die Phase-1-read-
only-Regel wird hier nur angezeigt, nicht erzeugt; ihre Autorität stammt aus dem
statischen Verfassungskern.
**Nicht enthalten:** TaskManager- oder Issue-Logik.
**Voraussichtliche Berührungsfläche:** `briefing_stages.py`, optional eine kleine
Context-Quelle, Tests und `.steward/conventions.md` nur bei belegter Notwendigkeit.

### Feature-Spec 03 — Action Signal Integrity

**Scope:** Statusnormalisierung echter Task-Objekte, Rendering offener Tasks,
Issue-Begrenzung und Prioritätsregeln.
**Nicht enthalten:** GitHub-Issue-Aufräumoperationen.
**Voraussichtliche Berührungsfläche:** `context_bridge.py`, `briefing_stages.py`, echte
TaskManager-/Status-Tests.

### Feature-Spec 04 — Semantische Freshness und Dedup

**Scope:** Feldklassifikation C0-C4, Normalisierung, Snapshot-/Payload-Hash,
persistente Inhaltsprüfung statt MTime- oder rein prozesslokaler Dedup-Annahme.
**Nicht enthalten:** allgemeine Heartbeat-Fehlerpropagation.
**Voraussichtliche Berührungsfläche:** erst nach Feature 00/01 festzulegen.

Die Reihenfolge ist `00 -> 01 -> 02/03 -> 04`. Feature 01 darf trotz Aufteilung in kleine
Commits erst nach gemeinsamer End-to-End-Produktionsabnahme als abgeschlossen gelten.

---

## 10. TESTVERTRAG FÜR DIE SPÄTEREN FEATURE-SPECS

### 10.1 Erforderliche Testebenen

| Ebene | Wirkung |
|---|---|
| Unit | Renderer/Publisher erzeugt erwartete deterministische Payload |
| Contract | beide Consumer-Ausgaben entsprechen demselben semantischen Kern; Byteidentität nur bei belegtem identischem Consumer-Vertrag |
| Integration | ein einmal assembliertes Context-Objekt fließt in beide Outputs |
| Workflow | explizites Staging nimmt genau erlaubte Root-/State-Dateien auf |
| Cold Start | fehlende Services erzeugen brauchbaren, ehrlich degradierten Kontext |
| Regression | bestehende `CLAUDE.md`-Caller bleiben funktionsfähig |
| Production | neuer Heartbeat-Commit enthält Context und beide Root-Dateien gemeinsam |
| Adversarial | Injection, Unicode, Symlink, Pfad, Race, Partial Write und Leak werden abgewehrt |

### 10.2 Unzulässige Placebo-Tests

- nur prüfen, dass zwei Dateien existieren,
- zwei getrennte Generatoren mit derselben Fixture füttern und Textgleichheit annehmen,
- Mocks verwenden, die echte Enum-/TaskStatus-Semantik verdecken,
- nur lokale MTimes vergleichen,
- nur einen manuellen CLI-Lauf testen, nicht den Heartbeat-Delivery-Pfad,
- Produktionsverifikation durch erfolgreichen Workflow-Status ersetzen.

### 10.3 Verpflichtende adversariale Fixtures

- Issue-/Tasktext mit „ignore previous instructions“ und Löschauftrag,
- eingeschleuste Markdown-Überschrift, Liste, Codefence, Link und HTML-Kommentar,
- bidi override, zero-width characters und ungewöhnliche Unicode-Zeilenzeichen,
- überlange Felder und unerwartete Container-/Skalartypen,
- unbekannter echter TaskStatus-Enum-Wert,
- private URL, absoluter Benutzerpfad, Token-artiger und personenbezogener Inhalt,
- `CLAUDE.md` oder `AGENTS.md` als Symlink beziehungsweise readonly Ziel,
- Schreibfehler beim zweiten Ziel, `ENOSPC` und Prozessabbruch zwischen Publikationsschritten,
- zwei konkurrierende Publisher mit verschiedenen Snapshot-IDs,
- Git-Änderung/Rebase zwischen Snapshot, lokalem Publish und Commit,
- manipuliertes, fehlendes oder veraltetes `PHASE2_CURRENT`,
- LLM-Tool versucht kanonische Root-Dateien zu überschreiben,
- gleiche Sekunde bei unterschiedlichem Inhalt und rückwärts springende Uhr.

### 10.4 Kernwirkungen

Spätere Tests müssen mindestens beweisen:

1. Fehlt eine Consumer-Datei, repariert ein Publikationslauf den gemeinsamen Kern, ohne
   Consumer-spezifische Vertragsregeln zu verletzen.
2. Weichen Payload-Hashes ab, wird partieller Publish erkannt und nicht als Erfolg gemeldet.
3. Ein abgeschlossener echter Task erscheint nicht unter Current Work.
4. Der Phase-2-Verweis bleibt als nichtautoritativer Arbeitsstand erkennbar und kann als
   missing/stale/conflicting degradieren.
5. Ein Heartbeat-Commit enthält `context.json`, `CLAUDE.md` und `AGENTS.md` gemeinsam,
   wenn sich der semantische Briefing-Inhalt geändert hat.
6. Private/ignorierte Dateien werden durch das Staging nicht aufgenommen.
7. Untrusted Text kann weder den statischen Verfassungskern noch die Markdown-Struktur
   kontrollieren.
8. Preview-, degraded-, fallback- und canonical-Outputs sind anhand Provenance eindeutig
   unterscheidbar.

---

## 11. ROLLOUT- UND ROLLBACK-VERTRAG

Für jede Feature-Spec gilt:

1. Live-Head und relevante Blobs pinnen.
2. Sauberen Feature-Branch vom aktuellen `origin/main` erstellen.
3. Rote Wirkungstests vor dem Fix dokumentieren.
4. Nur die in der Feature-Spec freigegebene Berührungsfläche ändern.
5. Gezielte Tests, dann relevante Suite, dann CI.
6. PR ohne Admin-Bypass; kein direkter Push auf `main`.
7. Nach Merge neuen Produktions-Heartbeat beobachten.
8. Git-Commit und Blobs der drei Context-Artefakte vergleichen.
9. Bei Divergenz oder Context-Verlust den **vorher verifizierten** Stop-Mechanismus
   auslösen, Ursache belegen und Revert-PR statt improvisierter Hotfix-Kaskade nutzen.
10. Ergebnis in `PHASE2_CURRENT` und `PHASE2_BEFUND` dokumentieren.

### 11.1 Noch fehlender Stop-Vertrag

„Heartbeat stoppen“ ist auf dem aktuellen Spec-Stand keine ausführbare Anweisung. Vor G1
muss read-only belegt werden:

- welcher existierende Kill-Switch geplante und manuelle Runs verhindert,
- welche Berechtigung dafür nötig ist,
- wie bereits laufende Jobs behandelt werden,
- wie Parallelpublisher gestoppt werden,
- wie und durch wen der Betrieb wieder freigegeben wird.

Existiert kein geeigneter Mechanismus, ist dessen minimale Ergänzung eine eigene
Operations-Spec und Voraussetzung für automatischen Context-Publish.

### 11.2 Safe Fallback

Ein Revert auf einen alten dynamischen Context ist nicht automatisch sicher. Vor Rollout
muss ein menschlich reviewter Minimal-Fallback feststehen, der:

- nur den statischen Verfassungskern enthält,
- dynamische Daten ausdrücklich als nicht verfügbar kennzeichnet,
- keine alte Agenda als aktuell darstellt,
- Preview-/LLM-Output ausschließt,
- ohne externe Quellen reproduzierbar ist,
- einen klaren manuellen Recovery-Pfad nennt.

---

## 12. OFFENE FRAGEN — IMPLEMENTIERUNG BLEIBT BIS ZUR KLÄRUNG GESPERRT

| ID | Frage | Warum entscheidend |
|---|---|---|
| OQ-01 | GESCHLOSSEN: Wie wird der bestehende LLM-Schreibpfad auf Preview/Annotation begrenzt, ohne unbekannte produktive Caller zu brechen? | Evidence-Paket OQ-01/OQ-16; Toolname bleibt, kanonische und beliebige Dateiwrites scheitern explizit fail-closed |
| OQ-02 | GESCHLOSSEN: Soll Current Phase Work State nur auf `PHASE2_CURRENT` verweisen oder einen sanitizten, nichtautoritativen Ausschnitt übernehmen? | Evidence-Paket OQ-02; typisierte Reference Card plus optionaler Metadaten-Claim, niemals freie Markdown-Extraktion oder Full-File-Include |
| OQ-03 | GESCHLOSSEN: Welche TaskStatus-Typen liefert der echte TaskManager dauerhaft: Enum, String oder gemischt? | Evidence-Paket OQ-03; Runtime ist kanonischer `TaskStatus`-Enum, Persistenz/Context sind uppercase Strings, Protocol-Commit muss Provenance tragen |
| OQ-04 | GESCHLOSSEN: Nach welcher Regel werden GitHub-Issues begrenzt und priorisiert? | Evidence-Paket OQ-04; Issues bleiben nichtautoritative Backlog-Beobachtungen, aktuelle Eligibility ist null, spätere Kandidaten benötigen reviewte Konfiguration und harte Begrenzung |
| OQ-05 | GESCHLOSSEN: Welche Briefing-Änderungen sind semantisch commitwürdig? | Evidence-Paket OQ-12/OQ-05; `payload_hash` und C1–C4-Trigger entschieden |
| OQ-06 | GESCHLOSSEN: Welche Lock-, Tempfile-, Rename-, fsync- und Recovery-Semantik trägt das tatsächliche Dateisystem und die Prozesslandschaft? | Evidence-Paket OQ-06/OQ-14; per-Pfad Atomicity, Doppel-Lock, Generationserkennung und Recovery-Vertrag entschieden |
| OQ-07 | TEILGESCHLOSSEN: Welche Core-File-, CODEOWNERS-, Reviewer- und Diff-Gates schützen `AGENTS.md`, `CLAUDE.md` und die statische Verfassungsquelle? | Evidence-Paket OQ-18/OQ-07; Writer-Landschaft durch OQ-16 belegt, Enforcement-Topologie bleibt durch OQ-14 und Delivery-Governance blockiert |
| OQ-08 | Ist die Formulierung „You are Steward“ für externe Maintainer zulässig? | Rollen- und Sicherheitsklarheit |
| OQ-09 | Wann und wie wird der derzeit tote interne Instruction-Loader behandelt? | Scope-Trennung; kein versehentlicher Prompt-Umbau |
| OQ-10 | Sollen die versehentlich getrackten `.steward/.atomic_*.tmp`-Dateien separat bereinigt werden? | Hygieneproblem, aber nicht in Context-Feature hineinziehen |
| OQ-11 | GESCHLOSSEN: Welche Discovery-, Hierarchie-, Prioritäts- und Include-Regeln gelten aktuell für Claude Code und Codex? | Evidence-Paket OQ-11; byte-identischer Root-Inhalt bleibt Default |
| OQ-12 | GESCHLOSSEN: Welche dynamischen Felder sind öffentlich zulässig und welchem C0-C4-Typ gehören sie an? | Evidence-Paket OQ-12/OQ-05; PUBLIC_SAFE-Allowlist und Default-Deny-Feldmatrix entschieden |
| OQ-13 | GESCHLOSSEN: Welche Quellen sind required, optional oder publish-blocking? | Evidence-Paket OQ-13; Vertragsquellen blockieren, Beobachtungsquellen degradieren ehrlich statt als gesunde Leere |
| OQ-14 | TEILGESCHLOSSEN: Welcher reale Kill-Switch stoppt geplante, manuelle und bereits laufende Publisher? | Evidence-Paket OQ-06/OQ-14; manueller Disable/Force-Cancel/Revocation/Fence-Pfad belegt, Operations-Drill und dauerhafter Schalter offen |
| OQ-15 | GESCHLOSSEN: Wie wird ein veralteter oder manipulierter Current-Phase-Arbeitsstand erkannt und angezeigt? | Evidence-Paket OQ-15; Git-Integrität, Review-Provenance, Referenzintegrität, Freshness und semantischer Konflikt bleiben getrennte Statusachsen |
| OQ-16 | GESCHLOSSEN: Welche Prozesspfade können außerhalb des Heartbeat-Workflows parallel publizieren? | Evidence-Paket OQ-01/OQ-16; zwei Root-Writer, Git-NADI-Nebenpublisher, Post-Step und interner Cetana-/Workflow-Mehrfachdispatch belegt |
| OQ-17 | GESCHLOSSEN: Ist das Repository und sind alle einbezogenen Issue-/Federation-Daten öffentlich? | Evidence-Paket OQ-17; Root-Output ist immer PUBLIC_SAFE, privilegierte/runtime Daten default-deny |
| OQ-18 | GESCHLOSSEN: Welche einzelne reviewte Quelldatei definiert den statischen Verfassungskern, und ist `.steward/conventions.md` dafür in Inhalt und Governance geeignet? | Evidence-Paket OQ-18/OQ-07; bestehender Pfad bleibt einzige Quelle, aktueller Inhalt ist vor Härtung nicht freigegeben |

---

## 13. FREIGABEGATES

### Gate G0 — Master-Spec Review

- Ist-Graph korrekt?
- Problemkatalog vollständig genug?
- Ziele und Nicht-Ziele akzeptiert?
- Feature-Schnitt klein genug?
- Offene Fragen korrekt und ehrlich?
- Trust-Zonen, Injection- und Datenminimierungsmodell vollständig?
- statischer Verfassungskern klar vom dynamischen Datenblock getrennt?
- Consumer-Verträge statt Bytegleichheitsannahme belegt?
- Transaktions-, Concurrency- und Provenance-Vertrag entscheidungsreif?
- Safe Fallback und realer Kill-Switch verifiziert?
- C0-C4-Feldklassifikation und Source-Fehlerklassen vollständig?

**Aktueller Status:** OFFEN.
**Freigabewirkung:** BLOCKIERT, solange die noch offenen OQ-Fragen und G0-Sicherheitsfragen nicht
mit Beweisen oder expliziten, reviewten Entscheidungen geschlossen sind.

### Gate G1 — Feature-Spec Review

Für jedes Feature existiert eine eigene ausführbare Spec mit:

- erneut gepinntem Live-Stand,
- exakten Symbolen und Berührungsflächen,
- verworfenen Alternativen,
- roten Regressionstests,
- Rollout-/Rollback-Beweis.

**Aktueller Status:** NICHT BEGONNEN.

### Gate G2 — Implementierungsfreigabe

Erst nach expliziter Freigabe einer einzelnen Feature-Spec darf Code geändert werden.

**Aktueller Status:** GESPERRT.

---

## 14. VORLÄUFIGE EMPFEHLUNG

Die bestehende Context-Bridge soll nicht ersetzt werden. Der robuste Weg ist:

1. bestehenden deterministischen Renderer behalten,
2. zuerst Trust-, Consumer- und Governance-Vertrag positiv beweisen,
3. statischen Verfassungskern vom begrenzten dynamischen Datenblock trennen,
4. LLM-Publikation kanonischer Root-Dateien verbieten,
5. einen Snapshot über einen Publisher und eine gemeinsame Delivery-Grenze führen,
6. den aktuellen Phasen-Arbeitsstand nur als widerlegbare Orientierung referenzieren,
7. Task- und Issue-Signale separat korrigieren,
8. Provenance, Safe Fallback, Kill-Switch und adversariale Wirkung in Produktion beweisen.

Diese Empfehlung ist eine Architekturhypothese, keine Implementierungsfreigabe. Die
offenen Fragen und jede Feature-Spec dürfen sie widerlegen oder verfeinern.

---

## 15. REVIEW-TRACEABILITY DRAFT 0.2

| Reviewpunkt | Aufnahme in DRAFT 0.2 | Status |
|---|---|---|
| Prompt Injection / Trust Boundaries | §§0B, 3.5-3.8, I-13/I-17, adversariale Fixtures | als G0-Blocker aufgenommen |
| Byteidentität nicht bewiesen | Z2, I-01, Option E, OQ-11 | zur reversiblen Hypothese herabgestuft |
| Atomicity / Concurrency | §8.3, I-15, OQ-06/OQ-16 | Garantievertrag und Writer-Landschaft entschieden; Implementierung weiterhin gesperrt |
| semantische Änderung undefiniert | §8.4, OQ-05/OQ-12 | C0-C4-Modell, PUBLIC_SAFE-Feldmatrix und Hash-/Committrigger entschieden |
| Provenance zu schwach | §8.2, I-14 | Sicherheitsvertrag statt Footer |
| LLM-Publikationspfad | T5, I-09, OQ-01 | fail-closed Preview-Vertrag entschieden; Implementierung weiterhin gesperrt |
| sensible Nicht-Secret-Daten | §3.7, I-06, OQ-17 | Allowlisting verpflichtend |
| Fehler / sichtbare Degradation | §3.8, I-08, OQ-13 | sechs Zustände eingeführt |
| Befund und Schlussfolgerung vermischt | §2.1, CB-01, §2.4 | Beweisart/Erreichbarkeit/Wirkung getrennt |
| Feature-Reihenfolge / E2E | §9 Feature 00/01 | Publisher und Delivery gemeinsamer Exit-Vertrag |
| adversariale Tests fehlen | §10.3 | verpflichtender Fixture-Katalog aufgenommen |
| Rollback unbestimmt | §§11.1-11.2, OQ-14 | Kill-Switch und Safe Fallback G0-Blocker |
| `AGENTS.md` Governance-Blast-Radius | Z8, Option E, Feature 00, OQ-07/OQ-18 | statischer Kern und Review-Gates gefordert |
| ein Publisher ist keine Wahrheit | §§0B, 8.5 | Konflikte werden angezeigt, nicht verschmolzen |
| `PHASE2_CURRENT` als Single Point of Failure | §§0A/0B, I-16, OQ-15 | ausdrücklich keine SSOT; optional/degradierbar |

---

*DRAFT 0.3 endet hier. Freigegeben ist nur die read-only Evidence-Phase. Keine
Codeänderung, kein Implementierungs-Commit und kein Implementierungs-PR ohne G0/G1/G2.*
