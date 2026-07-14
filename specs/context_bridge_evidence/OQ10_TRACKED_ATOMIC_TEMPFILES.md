# OQ-10 — GETRACKTE ATOMIC-TEMPDATEIEN

> **Status:** EVIDENCE COMPLETE — separater Hygiene-Cleanup entschieden
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `18e39055ca347366cd265e9e40c472a81733c80e`
> **Steward-Tree:** `6c6623a8c6b5f04de9d5f660cead8a76d77a2131`
> **Protocol-Head:** `34a8a0efc25c15ef7c07dd4fb50aeb2510c071e8`
> **Scope:** zwei getrackte `.steward/.atomic_*.tmp`-Pfade, erzeugender Atomic-Writer,
> historische und aktuelle Heartbeat-Stagingregeln sowie Cleanup-/History-Grenze. Keine
> Datei-, Code-, Workflow- oder Historyänderung.

---

## 1. Fragestellung

Der aktuelle öffentliche `main`-Tree enthält:

| Pfad | Blob | Größe | Inhalt |
|---|---|---:|---|
| `.steward/.atomic_dnk0k952.tmp` | `e69de29bb2d1d6434b8b29ae775ad8c2e48c5391` | 0 Bytes | leer |
| `.steward/.atomic_r903m386.tmp` | `e8176f82e7009127087fc7ab88cf491a8ae09005` | 23.605 Bytes | valider `PersistentMemory`-Snapshot |

OQ-10 klärt:

- ob diese Dateien Runtime-State oder unvollständige Writer-Artefakte sind,
- wodurch sie trotz `.gitignore` getrackt wurden,
- ob eine Löschung sie erneut entstehen lässt,
- ob die Bereinigung in die Context-Bridge gehört,
- und ob ein Git-History-Rewrite notwendig ist.

---

## 2. Erzeugender Writer

Der Steward-eigene `context_bridge._atomic_write()` verwendet
`tempfile.mkstemp(..., suffix=".tmp")` ohne den Prefix `.atomic_`. Er kann diese beiden
Namen daher nicht erzeugt haben.

Der Heartbeat installiert `steward-protocol` dagegen unpinned vom jeweiligen
Default-Branch. Dessen `vibe_core.utils.atomic_io.atomic_write_text()` verwendet seit
2025:

- Tempdatei im Zielverzeichnis,
- Suffix `.tmp`,
- Prefix `.atomic_`,
- `fsync()`, `close()` und anschließend `rename()`.

`PersistentMemory._save()` schreibt `.steward/memory.json` über genau dieses
`atomic_write_json()`. Der große Tempblob besitzt exakt dessen Schema:

- Top-Level `version`, `entries`, `entities`,
- Version `1`,
- sechs Einträge für Session `steward`,
- unter anderem `files_read`, `session_stats`, `synaptic_weights`, `chitta_summary` und
  `gap_tracker`,
- keine Entities.

Damit ist der große Blob positiv als unvollständig umbenannter
`PersistentMemory`-Write identifiziert. Der leere Blob ist ebenfalls mit einer nach
`mkstemp()` und vor beziehungsweise während des Schreibens abgebrochenen Operation
vereinbar. Seine konkrete Zielstate-Datei ist aus dem leeren Inhalt nicht beweisbar.

---

## 3. Warum Tempdateien liegen bleiben können

Der Protocol-Writer löscht den Tempfile bei einer von Python gefangenen Exception. Ein
Prozessabbruch außerhalb dieses Pfads kann dennoch zwischen `mkstemp()` und `rename()`
erfolgen, zum Beispiel durch Runner-/Jobabbruch oder Prozess-Kill.

Die zwei Dateien über viele Heartbeats hinweg beweisen keinen systematischen Fehler im
erfolgreichen Rename-Pfad. Sie beweisen aber:

> Atomicität der Zieldatei bedeutet nicht, dass ein Crash niemals lokale Temp-Artefakte
> hinterlässt.

Solche Artefakte sind weder Recovery-Manifest noch gültiger State. Aus ihrem bloßen
Vorhandensein darf kein Reader Aktualität oder Vollständigkeit ableiten.

---

## 4. Historische Aufnahme in Git

Die Dateien wurden jeweils durch autonome Heartbeat-State-Sync-Commits eingeführt:

| Pfad | Commit | Zeitpunkt | Commit |
|---|---|---|---|
| `.steward/.atomic_r903m386.tmp` | `4b18aeb2723a9ea04b859c6966e3313e1061cbbe` | 2026-03-30 18:05:22Z | `chore: heartbeat #1035 state sync` |
| `.steward/.atomic_dnk0k952.tmp` | `7754614ce7d109b5f4dcf9464d92ab807e394314` | 2026-04-16 09:01:58Z | `chore: heartbeat #1878 state sync` |

Beide Commits sind Vorfahren des aktuellen `main`.

Der damalige Workflow führte aus:

`git add -f .steward/ data/federation/ || true`

`-f` überschreibt Ignore-Regeln. Dadurch wurde nicht nur kuratierter State, sondern jeder
zu diesem Zeitpunkt im Verzeichnis liegende Tempfile als neue Git-Datei aufgenommen.

Das ist die direkte Aufnahmeursache. Die Dateien waren nicht ausdrücklich als
Delivery-Artefakte ausgewählt.

---

## 5. Heutige Ignore- und Staging-Semantik

Die aktuelle `.gitignore` ignoriert `.steward/` vollständig und erlaubt nur zwei
explizite State-Ausnahmen. `git check-ignore` bestätigt die Regel auch für beide
existierenden und einen hypothetischen neuen `.atomic_*.tmp`-Pfad.

Der aktuelle Heartbeat enthält zudem das ausdrückliche Verbot von `git add -f` und staged:

- `git add -u -- .steward/ data/federation/`,
- `git add -- data/federation/`.

Die Semantik ist entscheidend:

- `git add -u` aktualisiert oder löscht bereits getrackte Pfade,
- es nimmt keine neuen ignorierten Tempdateien auf,
- der zweite Befehl adressiert ausschließlich `data/federation/`.

Nach einer Git-Löschung der beiden Altdateien kann ein später liegen gebliebener
`.steward/.atomic_*.tmp` deshalb nicht durch den heutigen Workflow neu getrackt werden.

Solange sie getrackt bleiben, konserviert `git add -u` ihren Status hingegen weiter und
würde sogar eine zufällige spätere Änderung derselben Namen als State-Änderung stagen.

---

## 6. Öffentliche Datenwirkung

OQ-17 und die aktuelle GitHub-API belegen, dass `kimeisele/steward` öffentlich ist. Der
große Tempblob ist deshalb bereits ein öffentliches Release-Artefakt.

Er enthält:

- interne Sessionstatistik,
- gelesene und geschriebene Pfade,
- absolute GitHub-Runner-Pfade,
- Gap-/Toolfehler und synaptische Zustandswerte.

Eine strukturelle Prüfung und ein Pattern-Scan fanden im Blob keine:

- Private-Key-Blöcke,
- GitHub-Tokenformate,
- Provider-API-Keyformate,
- Werte für `NODE_PRIVATE_KEY` oder `FEDERATION_PAT`.

Das ist keine universelle Geheimnisfreiheitsgarantie, aber ein positiver Beleg gegen einen
aktuell erkennbaren Credential-Incident. Der Inhalt verletzt Datenminimierung und
Repository-Hygiene; er begründet nach der vorliegenden Evidence keinen destruktiven
History-Rewrite.

---

## 7. Bewertete Optionen

### Option A — Als gültigen Runtime-State behalten

**Bewertung:** VERWORFEN.

Tempnamen sind Implementierungsartefakte. Sie besitzen weder Zielpfadbindung,
Generation-ID noch Commit-/Recoveryvertrag und dürfen nicht als State interpretiert
werden.

### Option B — Im Context-Bridge-Feature löschen

**Bewertung:** VERWORFEN.

Die Dateien wurden nicht vom Context-Bridge-Writer erzeugt. Ihre Löschung ist weder für
den kanonischen Payload noch für Dual-Publishing erforderlich. Die Aufnahme würde einen
Hygienefix in einen sicherheitskritischen Feature-Schnitt mischen.

### Option C — Writer oder Workflow vorsorglich umbauen

**Bewertung:** VERWORFEN.

Der aktuelle Workflow verhindert neue ignored Tempfiles bereits ohne Force-Add. Ein
Runtime-Glob-Cleanup könnte außerdem aktive Tempfiles eines parallelen Writers löschen.
Für die beiden Git-Artefakte ist kein Writer-Rewrite erforderlich.

### Option D — Eigenständiger Tree-Cleanup

**Bewertung:** ANGENOMMEN.

Ein kleiner Hygiene-PR löscht exakt die zwei getrackten Pfade. Er verändert keinen Code,
keinen Workflow und keine Ignore-Regel. Die aktuelle Staginglogik nimmt die Löschungen
korrekt über `git add -u` wahr und führt neue ignored Tempfiles nicht wieder ein.

### Option E — Git-History jetzt umschreiben

**Bewertung:** VERWORFEN.

Ein History-Rewrite hätte repositoryweiten Blast Radius und würde bestehende Klone,
Commitreferenzen sowie Evidence-Pins destabilisieren. Ohne nachgewiesenes Secret oder
rechtliche Löschpflicht ist er unverhältnismäßig.

Die Tree-Löschung entfernt den Blob nicht aus historisch erreichbaren Commits. Falls eine
spätere Security-Prüfung doch schützenswerte Daten nachweist, ist das ein eigener Incident
mit eigenem History-Rewrite- und Credential-Rotation-Vertrag.

---

## 8. Verbindlicher Cleanup-Vertrag

Nach G0 erfolgt ein eigener, dokumentierter Hygiene-Schnitt:

1. Basis ist der dann aktuelle `origin/main`.
2. Exakt die aktuell getrackten `.steward/.atomic_*.tmp`-Pfade werden inventarisiert.
3. Die zwei belegten Pfade werden aus dem Git-Tree gelöscht.
4. Produktcode, Workflow, `.gitignore`, Context-Bridge und reguläre State-Dateien bleiben
   unverändert.
5. Der Commit darf keine pauschale Löschung ungetrackter lokaler Tempfiles enthalten.
6. Vor Merge wird verifiziert, dass kein `.steward/.atomic_*.tmp` mehr im resultierenden
   Git-Tree liegt.
7. Nach Merge wird ein regulärer Heartbeat abgewartet und der Produktions-Tree erneut
   geprüft.
8. Eine Wiederaufnahme gilt als Delivery-Regression und nicht als Anlass, Tempfiles als
   legitimen State zu behandeln.

Der Cleanup kann mit dem ebenfalls separaten OQ-09-Dead-Code-Cleanup nur dann gemeinsam
reviewt werden, wenn der PR weiterhin ausschließlich verhaltensneutrale Hygiene enthält.
Bevorzugt bleiben beide Schnitte getrennt, weil sie unterschiedliche Repositorieschichten
und Verifikationen betreffen.

---

## 9. Spätere Verifikation

Der Hygiene-PR muss mindestens belegen:

- `git ls-tree -r --name-only <result-head>` liefert keinen
  `.steward/.atomic_*.tmp`-Pfad,
- `git diff --check` ist leer,
- der Diff enthält ausschließlich die erwarteten Löschungen,
- `.gitignore` ignoriert einen hypothetischen neuen `.steward/.atomic_future.tmp`,
- der aktuelle Workflow enthält kein `git add -f` für `.steward/`,
- nach einem Produktionsheartbeat sind die Pfade remote weiterhin abwesend.

Da keine Runtimefunktion geändert wird, ist kein vollständiger Produkttestlauf für diesen
reinen Tree-Cleanup erforderlich. Die Produktions-Tree-Prüfung ist der relevante Test.

---

## 10. Nicht belegbare Aussagen

Nicht beweisbar ist:

- welcher konkrete Abbruchmechanismus jeden der beiden Tempfiles hinterließ,
- welcher Zielpfad dem leeren Blob zugedacht war,
- ob der große Blob exakt der letzte oder ein Zwischenstand von `memory.json` war,
- ob niemals ein unbekanntes Secretformat im historischen Inhalt vorkommt.

Diese Grenzen werden nicht durch Vermutungen ersetzt. Für die Entscheidung reichen die
positiven Beweise:

- Prefix und JSON-Schema identifizieren Writerklasse und Memory-Pfad,
- die historischen Commits und `git add -f` identifizieren die Git-Aufnahme,
- heutige Ignore-/Stagingregeln verhindern Wiederaufnahme nach Löschung,
- der bekannte Secret-Scan liefert keinen Anlass für History-Rewrite.

---

## 11. Auswirkung auf G0

OQ-10 ist geschlossen und blockiert G0 nicht mehr.

Die Bereinigung ist entschieden, bleibt aber bis zum Ende der read-only G0-Phase
ungeschrieben. Sie ist ein eigenständiger Hygiene-PR und weder Bestandteil noch
Voraussetzung des Context-Bridge-Publishers.
