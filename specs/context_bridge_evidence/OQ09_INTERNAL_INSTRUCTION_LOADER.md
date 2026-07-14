# OQ-09 — INTERNER PROJECT-INSTRUCTION-LOADER

> **Status:** EVIDENCE COMPLETE — Nichtverdrahtungs- und Cleanup-Vertrag entschieden
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `85c4799b3f045f53012679f2c6ba6a960270b530`
> **Steward-Tree:** `5e79596e3adf985f8b366292fecc1ab51b339504`
> **Scope:** `_load_project_instructions()`, sein historischer Runtime-Caller, aktuelle
> Call-Sites und direkte Tests. Keine Code-, Test-, Root-Datei- oder Workflowänderung.

---

## 1. Fragestellung

`steward/agent.py` enthält weiterhin den privaten Helper
`_load_project_instructions()`. Er liest zuerst `.steward/instructions.md` und danach
`CLAUDE.md` aus dem Working Directory.

OQ-09 klärt, ob dieser Helper:

- ein versehentlich entkoppeltes, wieder anzuschließendes Feature,
- bewusst dormante Infrastruktur,
- oder irreführender Dead Code ist.

Die Frage ist sicherheitsrelevant. Eine Wiederverdrahtung würde externe
Repository-Guidance unmittelbar in den Systemprompt des internen `StewardAgent` bringen
und damit die durch OQ-08 getrennten Consumerrollen erneut vermischen.

---

## 2. Aktueller Code- und Call-Graph

Am gepinnten Produktions-Head:

- `_load_project_instructions()` ist in `steward/agent.py` definiert.
- Der Helper prüft `.steward/instructions.md` vor `CLAUDE.md`.
- Er gibt den ersten nichtleeren Dateiinhalt unverändert zurück.
- Es existiert keine Produktions-Call-Site.
- Der Helper ist privat, nicht exportiert und in keiner Markdown-Dokumentation als API
  beschrieben.
- Ausschließlich `tests/test_project_context.py` importiert und ruft ihn direkt auf.

Der `StewardAgent` baut seinen Basisprompt stattdessen nur aus dem minimalen
`_BASE_SYSTEM_PROMPT` und dem Working Directory. Die aktuellen Tests verlangen explizit,
dass Projektinstruktionen nicht in diesen Prompt injiziert werden.

Damit existieren zwei unterschiedliche Testaussagen:

1. direkte Helper-Tests konservieren das alte Dateiauswahlverhalten,
2. Runtime-Tests konservieren ausdrücklich die Nichtverwendung dieses Helpers.

Nur die zweite Aussage beschreibt das aktuelle Produktionsverhalten.

---

## 3. Historische Einführung

Der Helper wurde in Commit
`b094f8278ee80af42e3b0d8c5dbc57714ddb2675` vom 2026-03-07 eingeführt:

`feat: Phase 5 — project instructions + git context, v0.5.0 (145 tests)`

Der damalige Vertrag war ausdrücklich:

- `.steward/instructions.md` oder `CLAUDE.md` laden,
- den Inhalt an `_build_system_prompt()` übergeben,
- Projektinstruktionen gemeinsam mit weiteren dynamischen Informationen in den
  Runtime-Systemprompt injizieren.

Zu diesem Zeitpunkt war der Helper keine tote Hilfsfunktion, sondern Teil des
Constructors und des produktiven Promptpfads.

---

## 4. Historische Entkopplung

Commit `ec7f9189ff2f2a0a473c75ee102440ef328813b4` vom 2026-03-09 entfernte die
Verdrahtung bewusst:

`feat: CBR DSP signal processor + minimal system prompt + hardened FakeLLM`

Der Commit:

- ersetzte den langen Steward-Personaprompt durch einen minimalen generischen Prompt,
- entfernte `project_instructions` und weitere dynamische Parameter aus
  `_build_system_prompt()`,
- entfernte den Loader-Aufruf aus dem Constructor,
- änderte die Runtime-Tests so, dass Projektinstruktionen ausdrücklich **nicht** mehr im
  Basisprompt erwartet werden.

Die Commitbeschreibung begründet dies als Architekturwechsel zum minimalen Systemprompt,
nicht als vorläufigen Ausfall oder TODO.

Commit `cfe58619405ec2e5f43994ef59ea7bdb3b209b49` vom 2026-03-15 vereinfachte den
Promptpfad weiter, ließ Helper und direkte Helper-Tests aber stehen.

`git blame` ordnet die aktuellen Helperzeilen weiterhin vollständig dem ursprünglichen
Einführungscommit zu. Es gibt keinen späteren Wiederanschlussversuch.

---

## 5. Bewertung des historischen Vertrags

Die Evidence widerlegt die Hypothese eines versehentlich verlorenen Kernfeatures:

> Der Runtime-Caller wurde absichtlich entfernt; nur die nun irreführende private
> Implementierung und ihre direkten Tests blieben zurück.

Die direkte Testabdeckung beweist lediglich, dass der isolierte Helper weiterhin Dateien
lesen kann. Sie beweist weder Produktnutzung noch einen heute gültigen
Kompatibilitätsvertrag.

Da der Name mit Unterstrich privat ist, kein Export und keine dokumentierte API existiert,
ist kein öffentlicher Python-Kompatibilitätsanspruch belegt.

---

## 6. Sicherheitswirkung einer Wiederverdrahtung

Der historische Loader besitzt keinen der inzwischen für Root-Context erforderlichen
Schutzverträge:

- keine Unterstützung für `AGENTS.md`,
- keine Consumer- oder Rollenklassifikation,
- keine PUBLIC_SAFE-Allowlist,
- keine Prompt-Injection- oder Markdown-Grenze,
- keine Größen- oder Truncationregel,
- keine Provenance oder Freshness,
- keine Schema- oder Inhaltsvalidierung,
- keine Trennung zwischen statischem C0 und dynamischen Daten,
- keine belegte Symlink- oder Root-Containment-Prüfung.

Seine Priorität `.steward/instructions.md` vor `CLAUDE.md` ist zudem ein historischer
interner Dateivertrag und kein belegter Claude-/Codex-Consumervertrag.

Eine Wiederverdrahtung würde daher:

1. externes Engineering-Briefing als internen Runtime-Systemprompt behandeln,
2. „You are Steward“-Rollenfehler aus OQ-08 verschärfen,
3. potenziell untrusted oder dynamische Root-Inhalte auf Systemprompt-Ebene anheben,
4. den minimalen CBR-Promptvertrag ohne eigene Spec verändern.

Das ist als Context-Bridge-Nebenwirkung unzulässig.

---

## 7. Bewertete Optionen

### Option A — Für die Context-Bridge wiederverdrahten

**Bewertung:** VERWORFEN.

Die Root-Dateien adressieren externe Engineering-Consumer. Der interne Steward-Runtime-
Agent ist ein anderer Consumer mit anderer Trust- und Rollenoberfläche.

### Option B — Dauerhaft unverändert liegen lassen

**Bewertung:** VERWORFEN.

Der Helper besitzt zwar keine aktuelle Runtimewirkung, aber Name und direkte Tests
suggerieren weiterhin unterstützte Funktionalität. Das erhöht das Risiko einer späteren
„Reparatur“, die den bewusst entfernten Promptpfad unbemerkt reaktiviert.

### Option C — Jetzt innerhalb des G0-Dokumentationsbranches löschen

**Bewertung:** VERWORFEN.

G0 ist read-only Recon. Eine Löschung von Produktcode und Tests wäre eine unzulässige
Implementierungsänderung und würde den Evidence-Branch kontaminieren.

### Option D — Nach G0 separat verhaltensneutral entfernen

**Bewertung:** ANGENOMMEN.

Ein kleiner eigener Cleanup-Schnitt entfernt ausschließlich:

- `_load_project_instructions()`,
- seine direkten, ausschließlich den toten Helper prüfenden Tests.

Er verändert weder `_build_system_prompt()` noch Constructor, Root-Publisher,
Context-Renderer oder Workflow. Bestehende negative Runtime-Tests bleiben erhalten.

---

## 8. Verbindlicher Vertrag

1. Die Context-Bridge verdrahtet `_load_project_instructions()` nicht wieder.
2. Root-`CLAUDE.md` und `AGENTS.md` bleiben externe Engineering-Verträge und werden nicht
   automatisch zum internen Steward-Systemprompt.
3. Der aktuelle minimale `StewardAgent`-Prompt bleibt außerhalb des Context-Bridge-
   Implementierungsscopes.
4. Der tote Helper und seine direkten Tests werden erst nach G0 in einem separaten,
   eng begrenzten Cleanup-PR entfernt.
5. Diese Entfernung ist verhaltensneutral: Es existiert vorher und nachher keine
   Produktions-Call-Site.
6. Falls Steward künftig interne projektbezogene Runtime-Instruktionen benötigt, erhält
   diese Funktion eine neue, eigenständige Spec mit explizitem Consumer-, Trust-,
   Provenance-, Größen- und Injection-Vertrag. Der tote Helper wird dafür nicht still
   reaktiviert.

OQ-09 ist damit geschlossen. Die spätere Löschung ist entschieden, aber durch den
read-only G0-Status noch nicht zur Ausführung freigegeben.

---

## 9. Spätere Cleanup-Verifikation

Der separate Cleanup-Schnitt muss mindestens beweisen:

- Symbolsuche findet weder Definition noch Produktions-Call-Site,
- direkte Helper-Tests sind entfernt,
- negative Runtime-Tests bestätigen weiterhin, dass Root-/Projektdateien nicht in den
  Basisprompt injiziert werden,
- die übrigen `StewardAgent`-Tests bleiben grün,
- kein Root-Publisher, Renderer oder Workflow wird verändert,
- der PR beschreibt ausdrücklich „dead private helper removal; no runtime behavior
  change“.

Eine neue Runtime-Instruktionsfunktion darf nicht in denselben Cleanup-PR aufgenommen
werden.

---

## 10. Nicht belegbare Aussagen

Nicht belegt ist:

- ob externe Nutzer den privaten Helper trotz fehlendem Export direkt importieren,
- ob ein künftiges Produktkonzept erneut interne Projektinstruktionen benötigt,
- ob `.steward/instructions.md` außerhalb des untersuchten Repositorys manuell genutzt
  wird.

Diese Unsicherheiten ändern die Entscheidung nicht:

- Direkte externe Nutzung einer privaten, undokumentierten Funktion begründet keinen
  belegten Produktvertrag.
- Ein künftiges Feature benötigt wegen der Sicherheitsgrenzen ohnehin eine neue Spec.
- Die Datei selbst wird durch den späteren Cleanup nicht gelöscht; nur der tote
  automatische Loader fällt weg.

---

## 11. Auswirkung auf G0

OQ-09 blockiert G0 nach dieser Evidence nicht mehr.

Für die Context-Bridge gilt ein klarer negativer Vertrag: kein automatisches Laden der
externen Root-Dateien in den internen Runtime-Systemprompt. Der spätere Dead-Code-Cleanup
ist isoliert, verhaltensneutral und keine Voraussetzung für den read-only Abschluss der
verbleibenden OQ-10-Hygienefrage.
