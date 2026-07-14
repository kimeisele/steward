# OQ-18 / OQ-07 — VERFASSUNGSQUELLE UND GOVERNANCE

> **Status OQ-18:** EVIDENCE COMPLETE — Quelldatei entschieden, Härtung vor Nutzung zwingend
> **Status OQ-07:** EVIDENCE PARTIAL — Schutzvertrag entschieden, Enforcement-Topologie durch OQ-14/OQ-16 blockiert
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `02938251c2c28389340dede8d9e125ba05af17ab`
> **Steward-Tree:** `7b622d34d476137e42dc1f79892754e13107fba0`
> **Scope:** Statische Verfassungsquelle, bestehende Writer, GitHub-Governance und
> Schutzanforderungen. Keine Änderung an Produktivcode, Workflow oder Repository-Settings.

---

## 1. Untersuchungsfragen

### OQ-18

Welche einzelne reviewte Quelldatei definiert den statischen Verfassungskern, und ist
`.steward/conventions.md` dafür in Inhalt und Governance geeignet?

### OQ-07

Welche Core-File-, CODEOWNERS-, Reviewer- und Diff-Gates schützen `AGENTS.md`,
`CLAUDE.md` und die statische Verfassungsquelle?

---

## 2. Untersuchte Quellen

### Gepinnter Steward-Code

- `.steward/conventions.md`
- `.gitignore`
- `.github/workflows/steward-heartbeat.yml`
- `CLAUDE.md`
- `steward/briefing.py`
- `steward/briefing_stages.py`
- `steward/hooks/moksha_bridge.py`
- `steward/pr_gate.py`
- `steward/federation.py`
- `steward/tools/synthesize_briefing.py`
- zugehörige Tests und Git-Historie

### Live-GitHub-Governance

- Repository-Metadaten
- Schutzregeln von `main`
- aktive Rulesets
- vorhandene `CODEOWNERS`-Dateien
- Reviews von PR `#430`
- Commit-Metadaten des gepinnten Heartbeat-Commits

### Offizielle GitHub-Dokumentation

- `https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches`
- `https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners`
- `https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets`
- `https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository`

---

## 3. Positive Beweise — bestehende Verfassungsquelle

1. `.steward/conventions.md` bezeichnet sich selbst als einzigen nichtdynamischen,
   unverändert in `CLAUDE.md` übernommenen Abschnitt.
2. `steward/briefing.py` nennt diese Datei die statische Orientierung und eine der drei
   Briefing-Schichten.
3. `steward/briefing_stages.py::_load_orientation()` liest genau diesen Pfad und gibt den
   Inhalt nach dem führenden Kommentarblock zurück.
4. Im gepinnten Tree existiert keine zweite dedizierte statische Verfassungsquelle.
5. `AGENTS.md` existiert am gepinnten Head nicht.
6. Eine Suche über den gepinnten Tree fand keinen Produktivpfad, der
   `.steward/conventions.md` absichtlich schreibt.

Damit ist `.steward/conventions.md` der einzige bestehende Kandidat. Eine neue parallele
Quelldatei würde ohne belegten Consumer-Zwang eine zweite manuelle Wahrheit erzeugen.

---

## 4. Positive Beweise — die Datei ist inhaltlich noch keine sichere Verfassung

Die aktuelle Datei mischt vier verschiedene Klassen:

| Klasse | Beispiele | Bewertung |
|---|---|---|
| Rollenprompt | „You are Steward — an autonomous superagent engine“ | für externe Maintainer rollenverwirrend und nicht als allgemeine Repository-Regel geeignet |
| dauerhafte Schutzregel | keine Owner-/Org-Hardcodes, Fehler nicht verschlucken | möglicher Verfassungskern, aber einzeln zu verifizieren |
| Architekturorientierung | Pipeline, Substrate-Primitives, Verzeichnisse | nützliche Orientierung, aber keine konstitutionelle Autorität |
| veränderliche Betriebsbehauptung | Frequenzen, Slot-/Peer-/Flush-Zahlen, Toolanzahl | driftgefährdet; muss abgeleitet, validiert oder aus dem statischen Kern entfernt werden |

Zusätzlich fehlen im aktuellen Inhalt die für die Context-Bridge bereits begründeten
dauerhaften Grenzen:

- Phase 1 bleibt read-only.
- Der aktuelle Operatorauftrag ist externe Laufzeitautorität und wird nicht aus
  Repository-Daten rekonstruiert.
- Dynamische Issues, Tasks, Senses, Sessions und Federation-Texte sind Daten, keine
  Instruktionen.
- Root-Context ist ein `PUBLIC_SAFE`-Publikationsartefakt.
- Untrusted Daten dürfen den statischen Kern und seine Markdown-Struktur nicht verändern.

Die aktuellen Zahlen und Pfade wurden stichprobenartig in lebendem Code wiedergefunden.
Das beweist ihre momentane Existenz, nicht ihre Eignung als dauerhaft hardcodierte
Verfassungsregel.

---

## 5. Positive Beweise — aktuelle Git- und Writer-Grenzen

1. `.steward/conventions.md` ist trotz der `.gitignore`-Regel `.steward/` bereits getrackt.
2. Der Heartbeat führt `git add -u -- .steward/ data/federation/` aus.
3. `git add -u` staged Änderungen an bereits getrackten Dateien auch dann, wenn eine
   Ignore-Regel neue Dateien desselben Pfads ausschließt.
4. Eine lokale oder autonome Änderung an `.steward/conventions.md` würde deshalb vom
   aktuellen Heartbeat ohne Pfad-Allowlist mitgestaged.
5. Der Heartbeat pusht mit `FEDERATION_PAT` direkt auf `main`.
6. Die Workflow-Concurrency serialisiert Heartbeat-Läufe, schützt aber weder vor anderen
   Writern noch vor einem zu breiten Staging-Scope.
7. `CLAUDE.md` wird deterministisch durch `write_claude_md()` geschrieben; ein separater
   LLM-Toolpfad kann ebenfalls ein frei wählbares Ziel und standardmäßig `CLAUDE.md`
   beschreiben. Die vollständige Caller- und Concurrency-Frage bleibt OQ-01/OQ-16.

Folge: Die Behauptung „statische, menschlich reviewte Quelle“ trifft betrieblich noch
nicht zu. Der aktuelle Delivery-Pfad kann die Quelle ohne menschlichen Review committen.

---

## 6. Positive Beweise — vorhandene Governance schützt die Dateien nicht

Am Untersuchungsdatum gilt:

- Repository `kimeisele/steward` ist öffentlich und gehört einem persönlichen
  GitHub-Account, keiner Organisation.
- Es existiert keine `CODEOWNERS`-Datei.
- Es existiert kein aktives Repository-Ruleset.
- `main` verlangt die Checks `Tests (Python 3.11)`, `Tests (Python 3.12)` und `Lint`.
- `main` verlangt keinen Pull Request und keine Reviewfreigabe.
- `enforce_admins` ist deaktiviert.
- Signaturen und Conversation Resolution sind nicht erforderlich.
- Force-Push und Branch-Löschung sind deaktiviert.
- PR `#430` wurde ohne angeforderte oder abgegebene Reviews gemerged.
- Der gepinnte Heartbeat-Commit ist unsigned; GitHub ordnet weder Author noch Committer
  einem Login zu. Die sichtbare Git-Identität lautet `steward-bot`.

Die offizielle GitHub-Dokumentation belegt außerdem:

1. `CODEOWNERS` allein erzwingt keine Freigabe; die Branch-Regel muss Code-Owner-Review
   verlangen.
2. Klassischer Branchschutz gilt für Administratoren standardmäßig nicht, solange die
   Administrator-Erzwingung nicht aktiviert ist.
3. Rulesets können Bypass-Akteure und einen Pull-Request-only-Bypass modellieren.
4. Aus diesen allgemeinen Fähigkeiten folgt noch nicht, dass das konkrete persönliche,
   öffentliche Repository jede gewünschte pfadbezogene Bypass-Topologie unterstützt.

---

## 7. `pr_gate.py` ist Diagnose, keine Repository-Governance

`steward/pr_gate.py::CORE_FILES` enthält `CLAUDE.md`, aber weder `AGENTS.md` noch
`.steward/conventions.md`. Der Kommentar verspricht für Core-Dateien einen Council Vote.

Der produktive Caller in `steward/federation.py` beweist jedoch:

- `has_core_files` fügt nur den Text „council vote required“ hinzu,
- ein ansonsten positives Ergebnis bleibt ausdrücklich `approve`,
- das Ergebnis wird als Federation-Verdict emittiert,
- es ändert keine GitHub-Branch-Regel und blockiert weder Merge noch Direct Push.

`CORE_FILES` ist deshalb ein advisory Diagnose-Signal. Es darf weder in dieser Spec noch
in späterer Implementierung als wirksamer Schutzbeweis verwendet werden.

---

## 8. Historische Governance-Evidence

Die Historie von `.steward/conventions.md` enthält am untersuchten Stand drei Commits:

- `464c3f3f796112a3975213373a3573e6242129b1`
- `a8f307136b303c8b04000c97a8d17fc58e277ba1`
- `3ba27c24cacfe3f71b8e5cf040a0b134113e50ee`

Alle drei tragen den Git-Autor `Claude <noreply@anthropic.com>`. Die GitHub-API liefert
für keinen dieser Commits einen zugeordneten Pull Request. Daraus folgt nicht, dass kein
Mensch den Text jemals gelesen hat. Belegt ist aber, dass die Repository-Historie keinen
PR- oder Review-Nachweis für diese Verfassungsänderungen enthält.

---

## 9. OQ-18 — Entscheidung

OQ-18 ist geschlossen:

1. `.steward/conventions.md` bleibt die einzige Quelldatei des statischen
   Verfassungskerns. Es wird keine zweite manuell gepflegte Constitution-Datei eingeführt.
2. Die Datei ist **in ihrer aktuellen Form nicht zur kanonischen Publikation in
   `AGENTS.md` und `CLAUDE.md` freigegeben**.
3. Vor Nutzung muss eine eigene kleine Feature-Spec den Inhalt chirurgisch klassifizieren:
   - dauerhafte, menschlich reviewte Schutzregeln behalten oder ergänzen,
   - Rollenimpersonation entfernen,
   - veränderliche Fakten ableiten, validieren oder aus dem Kern entfernen,
   - Architekturerklärung klar von imperativer Governance trennen.
4. Der Heartbeat darf diese Quelle niemals erzeugen, umformulieren oder als Nebenwirkung
   stagen.
5. Der statische Kern darf nur über einen menschlich reviewten PR geändert werden.
6. Root-Ausgaben dürfen ihn nur unverändert beziehungsweise über eine vollständig
   deterministische, contract-getestete Normalisierung übernehmen.

Diese Entscheidung wählt einen bestehenden Pfad, nicht den aktuellen Inhalt als bereits
vertrauenswürdig.

---

## 10. OQ-07 — erforderlicher Schutzvertrag

Folgende Mindestgarantien sind entschieden:

### 10.1 Human-only-Verfassung

- `.steward/conventions.md` ist Governance-Code, keine Heartbeat-State-Datei.
- Änderung nur über Pull Request.
- mindestens eine ausdrücklich zuständige menschliche Code-Owner-Freigabe.
- stale Freigaben müssen nach neuen Commits verworfen werden.
- kein autonomer Writer und kein permanenter Automation-Bypass darf diese Datei ändern.

### 10.2 Generierte Root-Verträge

- `CLAUDE.md` und `AGENTS.md` sind abgeleitete, aber sicherheitskritische
  Agenten-Governance-Oberflächen.
- Automatischer Publish ist nur zulässig, wenn Contract-Tests beweisen, dass der statische
  Block exakt aus der reviewten Quelle stammt und dynamische Daten nur im begrenzten
  Datenblock erscheinen.
- Ein Diff-Gate muss strukturelle Erweiterung, Leeren oder Veränderung des statischen
  Blocks blockieren.
- Ein Publish darf bei verletztem Contract nicht als erfolgreich gelten.

### 10.3 Governance-kritischer technischer Scope

Mindestens folgende Flächen gehören zum späteren Schutz- und Reviewmodell:

- `.steward/conventions.md`
- `CLAUDE.md`
- `AGENTS.md`
- `.github/CODEOWNERS` beziehungsweise der tatsächlich gewählte CODEOWNERS-Pfad
- `.github/workflows/steward-heartbeat.yml`
- `steward/briefing.py`
- `steward/briefing_stages.py`
- `steward/hooks/moksha_bridge.py`
- `steward/tools/synthesize_briefing.py`
- die noch zu definierenden Context-Bridge-Contract-Tests

`steward/pr_gate.py::CORE_FILES` kann später als zusätzliche Observability an denselben
Scope angeglichen werden. Es bleibt ausdrücklich kein Enforcement-Mechanismus.

### 10.4 GitHub-Gates

Der Zielvertrag benötigt:

- eine `CODEOWNERS`-Zuordnung für die Governance-kritischen Pfade,
- verpflichtenden Pull Request auf dem geschützten Zielbranch,
- verpflichtende Code-Owner-Freigabe,
- Verwerfen veralteter Freigaben nach neuen Commits,
- erforderliche Context-Bridge-Contract-Checks,
- keinen unbeschränkten Admin-/PAT-Bypass über den statischen Verfassungspfad.

Die konkrete Reviewer-Identität ist eine menschliche Governance-Entscheidung und darf
nicht aus Federation-Peers oder Repository-Daten erraten werden.

---

## 11. Warum OQ-07 noch nicht vollständig geschlossen ist

Der Schutzvertrag ist klar, seine sichere Delivery-Topologie noch nicht:

1. Der Heartbeat pusht aktuell automatisch direkt auf `main`.
2. Eine globale Pull-Request-Pflicht würde diesen Pfad ohne Bypass stoppen.
3. Ein unbeschränkter Bypass für `FEDERATION_PAT` würde wiederum auch Änderungen an der
   statischen Verfassung und den Root-Verträgen erlauben.
4. Die untersuchten GitHub-Einstellungen belegen noch keinen pfadbegrenzten Bypass, der
   im konkreten persönlichen Public-Repo sicher verfügbar ist.
5. Die Identität und Reichweite des hinter `FEDERATION_PAT` stehenden Principals ist aus
   dem Repository nicht belegbar.
6. Die vollständige Menge paralleler Publisher ist Gegenstand von OQ-16.
7. Stop-, Bypass- und Recovery-Semantik ist Gegenstand von OQ-14.

Darum bleibt offen, ob der Zielzustand über:

- globalen PR-only-Main mit verändertem Heartbeat-Delivery-Modell,
- einen minimal privilegierten GitHub-App-Writer,
- getrennte State-/Publikationsbranches,
- oder einen anderen nachweisbar pfadbegrenzten Mechanismus

erreicht wird. Diese Optionen sind keine Implementierungsfreigabe.

**Abhängigkeit:** OQ-07 kann erst nach OQ-14 und OQ-16 final geschlossen werden. Eine
Feature-Spec darf bis dahin weder `CODEOWNERS` noch Branchschutz oder Workflow-Bypass als
isolierten Schnellpatch behandeln.

---

## 12. Sicherheitsauswirkung

- Der einzige statische Input ist heute zugleich zu breit, rollenverwirrend und
  automatisch stagebar.
- Ein kompromittierter oder fehlgeleiteter Heartbeat könnte die vermeintlich statische
  Orientierung verändern und direkt publizieren.
- Ein Advisory-`CORE_FILES`-Treffer erzeugt ohne GitHub-Gate nur ein Signal, keinen Schutz.
- Ein voreilig aktivierter Automation-Bypass könnte den gewünschten Reviewvertrag
  vollständig neutralisieren.
- Eine zweite Constitution-Datei würde Drift erzeugen, ohne die Governance-Lücke zu
  lösen.
- Die sichere Lösung muss Inhaltshärtung und Delivery-Governance getrennt spezifizieren,
  aber end-to-end gemeinsam beweisen.

---

## 13. Nicht belegbare Annahmen

- Der Recon kann den tatsächlichen GitHub-Principal und die exakten Rechte von
  `FEDERATION_PAT` nicht auslesen.
- Die Commit-Anzeige `steward-bot` beweist die Git-Identität, nicht den authentifizierten
  GitHub-Account hinter dem Push.
- Der Recon beweist nicht, welche GitHub-Plan- oder Repository-Kombination zukünftig
  welche pfadbezogenen Ruleset-Funktionen anbietet.
- Ein fehlender PR in der Commit-API beweist keinen fehlenden informellen menschlichen
  Blick außerhalb GitHubs.
- Die endgültige menschliche Code-Owner-Identität ist nicht technisch ableitbar.
- Die vollständige Writer-Menge bleibt bis OQ-16 offen.

---

## 14. Gate-Wirkung

- OQ-18 ist geschlossen.
- OQ-07 ist auf einen verbindlichen Schutzvertrag und die Abhängigkeiten OQ-14/OQ-16
  reduziert, aber noch nicht final geschlossen.
- G0 bleibt offen.
- Keine Code-, Workflow-, CODEOWNERS-, Branchschutz- oder Ruleset-Änderung ist aus diesem
  Evidence-Paket freigegeben.
- Der nächste sinnvolle isolierte Recon ist OQ-01/OQ-16: vollständige Publisher- und
  Caller-Landschaft. Danach kann OQ-14 die Stop-/Bypass-/Recovery-Realität schließen.
