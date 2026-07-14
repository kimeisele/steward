# OQ-18 / OQ-07 — VERFASSUNGSQUELLE UND GOVERNANCE

> **Status OQ-18:** EVIDENCE COMPLETE — Quelldatei entschieden, Härtung vor Nutzung zwingend
> **Status OQ-07:** EVIDENCE COMPLETE — PR-only-/Code-Owner-/Contract-Check-Topologie entschieden
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `18e39055ca347366cd265e9e40c472a81733c80e`
> **Steward-Tree:** `6c6623a8c6b5f04de9d5f660cead8a76d77a2131`
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

Mindestens folgende **menschlich gepflegte** Flächen gehören zum späteren Code-Owner-
Schutz:

- `.steward/conventions.md`
- `.github/CODEOWNERS` beziehungsweise der tatsächlich gewählte CODEOWNERS-Pfad
- `.github/workflows/steward-heartbeat.yml`
- `steward/briefing.py`
- `steward/briefing_stages.py`
- `steward/hooks/moksha_bridge.py`
- `steward/tools/synthesize_briefing.py`
- die noch zu definierenden Context-Bridge-Contract-Tests

`CLAUDE.md` und `AGENTS.md` sind dagegen generierte Outputs. Ein Code-Owner-Review auf
Dateiebene würde bei jedem zulässigen dynamischen Update einen Menschen blockierend in
den Heartbeat-Pfad setzen. Diese beiden Dateien werden deshalb durch verpflichtende
Contract-Checks geschützt, die C0-Identität, Blockgrenzen, PUBLIC_SAFE-Schema,
Provenance und erlaubten Diff-Scope prüfen. Eine Änderung außerhalb dieses Vertrags muss
fail-closed sein. GitHub-`CODEOWNERS` kann keine Teilbereiche einer Datei schützen und
darf nicht als Ersatz für diesen Check dargestellt werden.

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

## 11. Finaler Live-Recon und Delivery-Entscheidung

Der erneute Live-Recon am 2026-07-14 belegt unverändert:

- keine `CODEOWNERS`-Datei,
- kein aktives Ruleset,
- keine Pull-Request- oder Reviewpflicht auf `main`,
- `enforce_admins=false`,
- nur drei erforderliche CI-Checks,
- Auto-Merge auf Repositoryebene deaktiviert,
- genau einen direkt eingetragenen Collaborator: den persönlichen Repositoryowner mit
  Adminrechten,
- keine offenen Pull Requests.

GitHubs dokumentierter Plattformvertrag ergänzt:

1. Code Owner benötigen Write-Rechte.
2. Pull-Request-Autoren können ihren eigenen PR nicht freigeben.
3. `required_approving_review_count=0` ist zulässig, während
   `require_code_owner_reviews=true` gezielt nur Änderungen an owned Pfaden blockiert.
4. Auto-Merge kann in einem öffentlichen persönlichen Repository nach bestandenen Checks
   und erforderlichen Reviews ausführen.
5. Branch-Protection-Bypass-Akteure können nur bei organization-owned Repositories
   ausgewählt werden.
6. Branchschutz kann Admins einschließen; ohne diese Option bleibt der Owner ein Bypass.

Daraus folgt die verbindliche Topologie:

### 11.1 `main` ohne Automation-Bypass

- `main` wird PR-only.
- Branchschutz gilt auch für Administratoren.
- Heartbeat, PAT, GitHub Actions und interne Writer erhalten keinen Direct-Push-Bypass.
- Force-Push und Branchlöschung bleiben verboten.
- Der aktuelle direkte Heartbeat-Push muss vor Aktivierung dieser Regel durch einen
  branch-/PR-basierten Delivery-Pfad ersetzt werden.

Ein globaler Automation-Bypass wird verworfen. Git-Credentials autorisieren keine
einzelnen Dateipfade; ein Bypass für State würde auch Governance-Dateien erreichbar
machen.

### 11.2 Selektiver Human-Review

- PR-Review-Schutz verwendet `required_approving_review_count=0` und
  `require_code_owner_reviews=true`.
- `.github/CODEOWNERS` besitzt sich selbst und alle menschlich gepflegten
  Governance-/Publisher-/Workflow-/Contract-Test-Pfade.
- Reviews werden nach neuen Commits verworfen.
- Generierte Root-Ausgaben sind nicht dateiweit codeowned, sondern unterliegen dem
  required Context-Bridge-Contract-Check.

Diese Trennung verhindert sowohl Human-in-the-loop bei jedem Heartbeat als auch
unreviewte Änderungen am Ursprung des Agentenvertrags.

### 11.3 Automatische Delivery

- Der Heartbeat publiziert auf einen nicht geschützten, eindeutig generierten Branch und
  erstellt beziehungsweise aktualisiert einen PR.
- Der PR darf nur den separat allowlisteten generierten Delivery-Scope enthalten.
- Ein auf dem geschützten Base-Branch definierter Required Check validiert Autor,
  Pfadscope, C0, C1-Schema, Provenance, Payload-/Snapshotbindung und Secret-/Injection-
  Grenzen.
- Erst nach grünen Checks und erfüllten Code-Owner-Regeln darf Auto-Merge ausführen.
- Der Publisher kann die Schutzlogik nicht im selben PR ändern, ohne dadurch einen owned
  Pfad und verpflichtenden Human-Review auszulösen.

Die exakte Branchbenennung, Checknamen und GitHub-API-Sequenz gehören in die Delivery-
Feature-Spec. Die Sicherheitsentscheidung selbst ist damit getroffen.

### 11.4 Zwei-Principal-Precondition

Der aktuelle einzelne Collaborator kann einen selbst erstellten Governance-PR nicht als
Code Owner genehmigen. Vor Aktivierung muss deshalb ein realer Zwei-Principal-Pfad
belegt sein:

- Governance-PR wird von einem getrennten, begrenzten Author-Principal erstellt und vom
  menschlichen Owner freigegeben, oder
- ein zweiter ausdrücklich autorisierter menschlicher Collaborator übernimmt den Review.

Die Identität wird nicht aus Federation-Peers erraten. Ohne positiv getesteten
Author/Reviewer-Split darf der Code-Owner-Gate nicht scharfgeschaltet und auch nicht durch
Admin-Bypass abgeschwächt werden.

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
- Welcher zweite Author-/Reviewer-Principal eingesetzt wird, ist noch keine
  Repositorytatsache und bleibt ein explizites G1-Deployment-Input.
- Die Writer-Menge ist im Evidence-Paket OQ-01/OQ-16 dokumentiert; externe, nicht im
  Repository sichtbare Prozesse bleiben naturgemäß unbelegbar.

---

## 14. Gate-Wirkung

- OQ-18 ist geschlossen.
- OQ-07 ist mit einer konkreten PR-only-/Code-Owner-/Contract-Check-Topologie geschlossen.
- OQ-14 und damit G0 bleiben offen; der Operations-Drill ist von der
  Governance-Architektur getrennt.
- Keine Code-, Workflow-, CODEOWNERS-, Branchschutz- oder Ruleset-Änderung ist aus diesem
  Evidence-Paket freigegeben.
- Vor jeder Aktivierung müssen Feature-Spec, Zwei-Principal-Precondition, Required-Check-
  Namen, Migrationsreihenfolge und Rollback positiv reviewt sein.
