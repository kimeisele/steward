# PHASE-2-BEFUND — Steward-Agentenföderation

**Begonnen:** 2026-07-13
**Dieses Dokument pflegst DU.** PHASE1_BEFUND_steward.md ist READ-ONLY — nur lesen,
nie ändern. Referenzen dorthin per §-Nummer ("Phase-1 §219.26").

---

## §1 — ORIENTIERUNG: WO DU BIST, WAS LÄUFT

### Was das System ist

Eine **Föderation aus 8+ autonomen Agenten-Repos** unter `github.com/kimeisele/`, die über
GitHub Actions laufen und sich per NADI-Protokoll (signierte JSON-Nachrichten über eine
geteilte Inbox) austauschen. Kein Server, kein Cluster — die Knoten kommunizieren über
Dateien in Git-Repos, die per Workflow gepusht und gepullt werden.

**Die relevanten Repos:**

| Repo | Rolle |
|---|---|
| `kimeisele/steward` | Der Hub. Registry (`verified_agents.json`), Inbox (`nadi_inbox.json`), Gateway, Reaper. **Hier liegt dieses Dokument.** |
| `kimeisele/agent-city` | Der größte Knoten. War die Quelle des Hauptdefekts (Phase-1 §219.1). |
| `kimeisele/agent-research`, `agent-internet`, `agent-world`, `agent-template`, `steward-protocol`, `steward-federation` | Weitere Knoten. |

**Wichtig:** Es gibt lokale Klone auf Kims Rechner, aber sie sind **veraltet und
unzuverlässig**. Verlass dich nicht darauf. Die Wahrheit steht auf GitHub. Siehe §2.

### Was Phase 1 erreicht hat

Drei Commits, alle am Produktionslog verifiziert:

| Commit | Repo | Inhalt |
|---|---|---|
| `442afc1` | agent-city | `NODE_PRIVATE_KEY` wird als JSON-Blob geparst (war: `bytes.fromhex()` → ValueError → stiller Fallback auf Wegwerf-Schlüssel) |
| `1f8663d` | agent-city | `_build_federation_nadi` prüft das Secret, bevor es eine Identität generiert |
| `831f5de` | steward | Registry-Purge 64→18 (+ Backup im Repo) |

**Die Wurzel war:** agent-city konnte sein eigenes Secret nicht lesen und hat bei **jedem
Heartbeat eine neue kryptographische Identität erzeugt**, sich damit registriert und sie
weggeworfen. Ergebnis: ~54 Geister in der Registry, eine fehlgeschlagene Key-Rotation, und
ein Knoten, der unter 8 verschiedenen IDs gleichzeitig sendete. Behoben und verifiziert.

### Was JETZT offen ist — dein Startpunkt

**Der Purge ist zerfallen.** Registry ging in einem Zyklus von 18 zurück auf 64. Grund:
die alten `agent_claim`-Nachrichten liegen **noch in der Inbox**, und `dharma.py:441-442`
liest sie bei **jedem** Zyklus erneut und trägt die Geister wieder ein.

Die Registry ist nur ein **Abbild der Inbox**. Der Bypass ist eine Wiederauferstehungsmaschine.

**Reihenfolge (Begründung in Phase-1 §219.23 / §220.2):**

1. **TICKET A — Gateway-Draht.** `steward/hooks/dharma.py:441-442` ersatzlos entfernen.
   Der Patch ist **fertig analysiert** in Phase-1 §219.26. Sicherheit verifiziert in §219.25.
   → **Das ist dein erster Schritt.**
2. **TICKET B' — Inbox + Registry gemeinsam purgen.** Hält erst nach A. Kriterium in §219.18.
3. **TICKET T0c** — ein dritter, unregistrierter Sender in agent-city (§219.16).
4. **TICKET C — Key-Rotation** (§218.3). Vorher prüfen, ob der Zielknoten das Blob-Format parst.
5. **agent-city hat kein CI-Gate** (§219.8) — der Grund, warum der Hauptdefekt wochenlang überlebte.
6. **97 Sender ohne Registry-Eintrag** (§219.20), **2 Knoten mit kaputter Identität** (§219.19).

---

## §2 — ARBEITSWEISE (VERBINDLICH — hart erkauft, siehe Phase-1 §220.4)

Das ist ein **verteiltes System mit laufenden Commits**. Jeder Knoten pusht State-Syncs im
Minutentakt. Ein lokaler Klon ist nach zehn Minuten veraltet.

### Lesen

```bash
# Live gegen den aktuellen Kopf:
gh api repos/kimeisele/steward/contents/steward/hooks/dharma.py --jq '.content' | base64 -d
```

**Große Dateien (>1 MB, z.B. `nadi_inbox.json`):** Die Contents-API liefert dafür **HTML
statt JSON** (`invalid character '<'`). Richtig ist die Blobs-API:

```bash
TREE=$(gh api repos/kimeisele/steward/commits/main --jq '.commit.tree.sha')
SHA=$(gh api "repos/kimeisele/steward/git/trees/$TREE?recursive=1" \
      --jq '.tree[] | select(.path=="data/federation/nadi_inbox.json") | .sha')
gh api "repos/kimeisele/steward/git/blobs/$SHA" --jq '.content' | tr -d '\n' | base64 -d
```

Das `tr -d '\n'` ist nötig — die Blobs-API liefert Base64 mit Zeilenumbrüchen.

### Prüfen

Tarball vom aktuellen SHA ziehen, dort testen. **Prüfstand, kein Arbeitsverzeichnis —
nie von dort pushen.**

```bash
SHA=$(gh api repos/kimeisele/agent-city/commits/main --jq '.sha')
gh api "repos/kimeisele/agent-city/tarball/$SHA" | tar xz -C /tmp/prüfstand --strip-components=1
```

### Schreiben — NIE `git push` aus einer Kopie

Atomar über die Git-Data-API. Der `parent`-SHA ist der Anker: hat jemand zwischenzeitlich
committed, **schlägt das Ref-Update fehl**, statt fremde Arbeit zu überschreiben.

```bash
R=kimeisele/steward
PARENT=$(gh api repos/$R/commits/main --jq '.sha')
BASETREE=$(gh api repos/$R/commits/main --jq '.commit.tree.sha')

BLOB=$(gh api repos/$R/git/blobs --method POST \
        -f content="$(cat datei.py)" -f encoding=utf-8 --jq '.sha')

TREE=$(gh api repos/$R/git/trees --method POST --input - --jq '.sha' << EOF
{"base_tree":"$BASETREE","tree":[
 {"path":"pfad/datei.py","mode":"100644","type":"blob","sha":"$BLOB"}]}
EOF
)

# Commit-Message via python3/json bauen (Heredocs mit Sonderzeichen brechen sonst)
COMMIT=$(gh api repos/$R/git/commits --method POST --input /tmp/msg.json --jq '.sha')

gh api repos/$R/git/refs/heads/main --method PATCH -f sha="$COMMIT" -F force=false
```

So wurden `442afc1`, `1f8663d` und `831f5de` gepusht.

### Verifizieren — nur am Produktionslog

Ein grüner Test beweist, dass der Test grün ist. **Das Log beweist, dass der Knoten läuft.**

```bash
gh workflow run <workflow>.yml --repo kimeisele/<repo>
# selbst pollen — KEIN `gh run watch` (blockiert)
for i in $(seq 1 20); do
  ST=$(gh api "repos/$R/actions/runs/$RID" --jq '.status')
  [ "$ST" = "completed" ] && break
  sleep 30
done
gh run view "$RID" --repo $R --log > /tmp/run.log
```

**Guard, nicht optional:** Ein Log mit weniger als 50 Zeilen ist ein Run, der noch läuft.
Eine Zählung darauf gibt **null Treffer für alles** und sieht aus wie Erfolg. Bin fast
reingefallen (Phase-1 §220.3).

### Zsh-Fallen

URLs mit `?` und Globs wie `*.py` **müssen in einfache Anführungszeichen**. Sonst globbt zsh
sie weg, bevor der Befehl sie sieht — und du bekommst „no matches found" statt eines Ergebnisses.

---

## §3 — METHODIK (die Fehler, die du nicht wiederholen musst)

Phase 1 hat **neun Hypothesen** aufgestellt. **Sechs wurden vom nächsten Recon widerlegt.**
Jede hätte, ungeprüft umgesetzt, Schaden angerichtet:

- *„63 Einträge = Rotationsleck"* → Nein. agent-city sendete **aktiv** unter 7 IDs.
  Ein Umschlüsseln hätte 6 von 7 ausgesperrt.
- *„Jüngste node_id behalten"* → Das war der **Wegwerf-Schlüssel**. Hätte den Geist kanonisiert.
- *„47% der Nachrichten werden blockiert"* → Mess-Artefakt eines selbstgebauten Stubs.
- *„Die Quelle ist versiegt"* → Nein, ein zweiter Aufrufer fehlte noch.
- *„Der Purge hält"* → Nein, die Inbox belebt ihn wieder.

**Was die Fehler gefangen hat:**

1. **Gegen die echte Klasse messen, nie gegen einen Stub.** Ein Stub misst deinen eigenen Fake.
2. **Kommentare im Code sind keine Quelle.** §209a stand sechs Wochen falsch im Befund, weil
   ein Kommentar das Gegenteil des Codes drei Zeilen darunter behauptete. Nur der Code zählt.
3. **Eine Zahl ist keine Ursache.** „78 unsignierte Claims" waren 74× der Steward selbst.
   Immer zerlegen, bevor du schließt.
4. **Guards, die abbrechen.** Der Purge-Guard („bricht ein `agent_name` weg?") hat genau den
   einen echten Knoten gerettet, den die Simulation löschen wollte.
5. **Diese Codebase ist nicht unfertig, sie ist UNVERKABELT.** „Alles da, nichts verbunden" —
   zehnmal gesehen. **Bevor du etwas neu baust: grep, ob es schon existiert.** Der Fix für
   den Hauptdefekt war eine Funktion, die es fast schon gab, mit der falschen Signatur.

**RING0:** Manche Dateien sind hash-geschützt (`scripts/governance/core_hashes.json` in
agent-city, `kernel_hashes.json` in steward). Vor jedem Edit prüfen. Keys niemals ins Log.

---

## §4 — DEIN ERSTER SCHRITT

**Nicht sofort patchen.** Erst orientieren:

1. Lies **Phase-1 §220** (ganz) und **§219** (ganz). Das sind ~200 Zeilen und ersetzen
   sechs Wochen Arbeit.
2. Verifiziere den **Live-Zustand** — mein Bild ist vom 13.07., und die Föderation läuft weiter:
   - Wie viele Einträge hat `verified_agents.json` jetzt?
   - Steht `dharma.py:441-442` noch da (der Bypass)?
   - Hat jemand seit `831f5de` in steward committed?
3. **Dann** Ticket A. Der Patch steht wortwörtlich in Phase-1 §219.26. Die Sicherheitsanalyse
   in §219.25 (der Gateway liest dieselbe Inbox, dedupliziert, quarantänisiert, und endet in
   demselben `_handle_agent_claim` → `reaper.record_heartbeat`).
4. **Nach dem Patch:** Heartbeat triggern. Im Log muss `BRIDGE: agent_claim identical —
   skipped` **verschwinden** (das war das Symptom) und `GATEWAY:`-Zeilen müssen **erstmals
   auftauchen** (bisher: null Treffer).

**Wenn die Erwartung nicht eintritt: Rollback, nicht nachhelfen.** Der Knoten läuft produktiv.

---

## §5 — DOKUMENTATIONS-PFLICHT

**Dieses Dokument ist dein externes Gedächtnis.** Wenn dein Kontext kollabiert, ist es alles,
was bleibt. Phase 1 hat gezeigt, was passiert, wenn es nicht gepflegt wird: eine falsche
Aussage (§209a) wurde sechs Wochen lang von Session zu Session weitergetragen und hätte
beinahe zu einem zerstörerischen Fix geführt.

**Nach jedem Milestone:**
- Neuen § anhängen. Nummeriert, mit Datum und Commit-SHA.
- **Was gemessen wurde**, nicht was du vermutest. Rohe Zahlen, rohe Log-Zeilen.
- **Was sich als falsch herausgestellt hat.** Widerlegte Hypothesen sind wertvoller als
  bestätigte — sie verhindern, dass der Nachfolger denselben Weg geht.
- Committen. Nicht nur lokal halten.

**Ablageort:** Dieses Dokument gehört ins `steward`-Repo. Phase 1 liegt vermutlich unter
`docs/` oder `specs/` — prüfe, wo, und leg Phase 2 daneben. Falls dort eine veraltete
Version von Phase 1 liegt: die aktuelle (Stand §220) überschreibt sie.

---

## §6 — LOG

*(Hier deine Einträge. Format: `## §7 — <Titel> (YYYY-MM-DD, commit <sha>)`)*

---

## §7 — PHASE 2 ÜBERNOMMEN: SAUBERE ARBEITSBASIS (2026-07-13, Merge `5ec734361a`)

### Dokumente konserviert

PR `#383` hat das externe Projektgedächtnis auf `main` gesichert:

- Phase 1 liegt vollständig bis §220 unter `docs/PHASE1_BEFUND_steward.md` und bleibt
  ab jetzt unverändert (read-only).
- Dieses Phase-2-Dokument ist das einzige fortlaufende Arbeitsjournal.
- Sieben frühere Spezifikations- und Blueprint-Dokumente liegen unter `specs/`.
- Alle neun Quelldateien wurden vor dem Commit per SHA-256 byte-identisch verifiziert.
- `.DS_Store` wurde ausgeschlossen; ein High-confidence Secret-Pattern-Scan hatte null Treffer.

### Saubere Arbeitsumgebung

Der alte Klon `/Users/ss/projects/steward` ist keine Arbeitsbasis: Er stand auf
`fix-phantom-heartbeat-ttl`, war gegenüber `origin/main` 982 Commits zurück und enthielt
laufzeitgenerierte, uncommittete Federation-State-Dateien.

Die verbindliche Phase-2-Arbeitsbasis ist:

- Klon: `/Users/ss/projects/steward-phase2`
- Remote: `git@github.com:kimeisele/steward.git`
- Recon-Branch: `phase2/live-recon`
- Ausgangspunkt: Merge `5ec734361a84a3c258459a4b3aebcf911b5e9818`

Vor jedem Ticket wird der Live-Head erneut über GitHub gelesen. Schreibarbeit erfolgt auf
einem frischen Ticket-Branch vom dann aktuellen `main`, niemals aus dem alten Klon.

### Live-Snapshot vor Übernahme

SHA-genau auf `24ca47e711f18ce30e5a60e13b9c2980e3988bf1` gemessen:

- `verified_agents.json`: 64 Einträge.
- Der direkte `agent_claim`-Bypass in `dharma.py:439-442` war weiterhin vorhanden.
- Seit Purge `831f5de` lagen 13 weitere Commits vor; alle waren Heartbeat-State-Syncs.
- Der Purge war damit weiterhin zerfallen; Ticket A war noch nicht ausgeführt.

### CI-Baseline ist bereits rot

Der Dokumentations-PR änderte ausschließlich Markdown. Trotzdem waren Required Checks rot.
Vergleich mit dem unmittelbar vorherigen `main`-Run `29281821279` auf demselben Base-SHA
bewies identische Bestandsfehler:

- Ruff: `Path` und `json` in `steward/hooks/dharma.py` undefiniert.
- Ruff: `_finding` in `steward/senses/diagnostic_sense.py` undefiniert.
- Pytest-Collection: `FindingKind.PEER_PROTOCOL_VIOLATION` fehlt.

Security Scan war grün. Der Admin-Bypass für PR `#383` wurde im PR mit dieser Baseline
dokumentiert; die CI-Defekte wurden nicht als Teil des Dokumentations-Merges kaschiert.

### Sicherheitsgrenze vor Ticket A

Noch kein Produktivcode wurde in Phase 2 geändert. Vor Ticket A bleiben zwei Punkte zwingend:

1. Die in Phase-1 §220.2 genannten 97 Sender ohne Registry-Eintrag live zerlegen und klären.
2. Die Reihenfolgeabhängigkeit aus Phase-1 §219.26 gegen den echten Codepfad prüfen:
   Ein neuer Knoten könnte sonst seinen ersten Heartbeat vor Verarbeitung seines Claims verlieren.

Erst danach folgt eine Patch-Entscheidung. Vermutung ist kein Freigabekriterium.

---

## §8 — READ-ONLY RECON: TICKET A IN DER BISHERIGEN FORM IST NICHT SICHER (2026-07-13)

### Messbasis

Alle Steward-Dateien und Zustandsdaten stammen aus demselben Live-Snapshot:

- Commit: `01e34a32b603ce92c7c9c35810648dd8dd758457`
- Tree: `1ea13e9f820219916499641ef458c3c268f15c2b`
- Inbox-Blob: `fd5cef74874490da83daafa691daaa369bd635c4`
- Registry-Blob: `a2bc477427e0ba38ba48d7dee4b8a2bac1aca646`
- Produktionslog: Steward Heartbeat Run `29282815952` (2146 Zeilen)

`agent-city` wurde separat auf seinem Live-Head fixiert:

- Commit: `1f8663d7be25abc929fa1e0dee8fb18fecbc0749`
- Produktionslog: Agent City Heartbeat Run `29282840554` (1986 Zeilen)

### Die 97 Sender sind jetzt vollständig zerlegt

Inbox: 576 Nachrichten von 117 unterschiedlichen String-Quellen. Registry: 64 Einträge.
Davon kamen 320 Nachrichten von genau 97 Quellen, deren `source` kein Registry-Key war.

- 96 der 97 Quellen waren Fossilien (letzte Nachricht älter als sieben Tage; der jüngste
  dieser Fossil-Sender war bereits rund 77 Tage alt).
- Genau eine unregistrierte Quelle war aktuell: `ag_365d8a2518ac7210`.
- Diese Quelle hatte neun Nachrichten innerhalb der letzten 24 Stunden:
  `city_report` und `bottleneck_escalation`.
- Alle neun hatten leere `signature`- und `payload_hash`-Werte. Eine erste Messung hatte
  fälschlich nur auf Feld-Anwesenheit statt auf nichtleeren Inhalt geprüft und sie dadurch
  als signiert gezählt. Diese Messung ist hiermit korrigiert.
- Beim Transport-TTL-Filter waren im Snapshot noch zwei T0c-Nachrichten gültig; der Rest
  war bereits älter als die deklarierte TTL von 7200 Sekunden.

Ergebnis: Phase-1 §219.20 ist geklärt. Es gibt nicht 97 potentiell lebende unbekannte
Knoten, sondern 96 Fossilquellen und einen lebenden, unregistrierten Parallel-Sender aus
`agent-city`.

### T0c ist kein dritter Knoten, sondern ein veralteter zweiter Sendepfad in agent-city

Der `agent-city`-Snapshot beweist die Kette:

1. `data/federation/peer.json` enthält die alte ID `ag_365d8a2518ac7210`.
2. `FederationNadi.__post_init__()` liest und cached diese ID als `_city_id`.
3. `_build_federation_nadi()` lädt zwar das echte `NODE_PRIVATE_KEY` und kennt dessen
   kanonische ID `ag_b670dc6cbcb705fe`, übergibt die Identität aber nicht an
   `FederationNadi` und aktualisiert dessen Cache nicht.
4. Erst danach patcht ein anderer Identity-Service `peer.json` auf `ag_b670...` — zu spät
   für das bereits konstruierte `FederationNadi`-Objekt.
5. `FederationNadi.emit()` überschreibt jede Caller-Quelle mit der gecachten alten ID.
6. `FederationMessage.to_dict()` schreibt leere Signaturfelder; dieser Pfad signiert nicht.

Das Produktionslog bestätigt die zeitliche Reihenfolge:

- `20:33:52`: `Node identity: ag_b670dc6cbcb705fe`
- `20:33:52`: `FederationNadi wired`
- `20:33:53`: `Patched peer.json with node_id=ag_b670dc6cbcb705fe`
- später: `FederationNadi: flushed 1 messages`

Parallel sendet `city.federation.FederationRelay` Claim und Heartbeat korrekt signiert unter
`ag_b670...`. `city_report` und `bottleneck_escalation` laufen jedoch über das alte
`FederationNadi`. T0c ist damit ein Identitäts- und Signatur-Split innerhalb desselben Repos.

### Der Gateway ist nicht nur umgangen — der Dharma-Hook crasht vor ihm

Der bisherige Plan nahm an, dass nach dem direkten Claim-Bypass zuverlässig
`gateway.process_inbound(transport)` folgt. Produktion beweist das Gegenteil:

- Run `29282815952`: `GATEWAY` = 0 Treffer.
- `BRIDGE: agent_claim identical` = 858 Treffer.
- `Hook dharma_federation failed: name 'Path' is not defined` = 7 Treffer.
- Der Hook importiert `Path` und `json` lokal im Aufrufer `_federation_heartbeat()`. Diese
  Namen sind in der separaten Methode `_process_inbox_messages()` nicht sichtbar.
- Sobald Protocol-Offender existieren, scheitert `_process_inbox_messages()` beim Schreiben
  von `protocol_violations.json` an `Path` (danach wäre auch `json` undefiniert).
- Dadurch werden Quarantäne, `remove_inbox_messages()` und der spätere Gateway-Aufruf in
  jedem Zyklus übersprungen.

Das erklärt gleichzeitig die CI-Baseline aus §7 und die Laufzeit: Ruff hatte genau diese
beiden undefinierten Namen bereits gemeldet. Der Lint-Fehler ist ein produktiver Circuit
Breaker, kein kosmetischer Befund.

### Die Legacy-Schleife behandelt jede Operation wie einen Heartbeat

`_process_inbox_messages()` iteriert in der zweiten Schleife über alle Inbox-Nachrichten,
ohne `operation == heartbeat` zu verlangen. Damit werden auch `agent_claim`, `city_report`,
`bottleneck_escalation` und andere Operationen durch den Legacy-Heartbeat-Validator gezogen.

Für eine neue kryptographische ID gilt dort:

- `peer_id = source` (also `ag_*`).
- Ist diese ID noch nicht in `reaper._peers`, wird die Nachricht abgelehnt.
- Wenn der `Path`-Crash repariert wäre, würde die Nachricht anschließend quarantänisiert
  und physisch aus der Inbox entfernt — bevor der Gateway sie später lesen kann.

Der bestehende Claim-Test bildet das nicht ab: Sein künstlicher Claim hat kein `source`.
Dadurch entsteht weder ein echter `ag_*`-Bootstrap-Pfad noch der Protocol-Offender/`Path`-
Fehler. Ein Ende-zu-Ende-Test für Dharma → Transport → Gateway existiert nicht.

### Korrektur an Phase-1 §219.25/§219.26

Der vorgeschlagene Patch „nur Zeilen 439-442 löschen“ darf nicht ausgeführt werden:

1. Der `Path`-Crash bliebe bestehen; der Gateway würde weiterhin nicht laufen.
2. Ein isolierter Import-Fix würde den bisher unerreichbaren Fail-closed-Gateway aktivieren
   und T0cs einzige `city_report`/`bottleneck_escalation`-Leitung blockieren.
3. Neue Claims könnten vom vorgelagerten Legacy-Validator entfernt werden, bevor der
   Gateway den öffentlichen Bootstrap-Pfad ausführt.
4. `FederationTransport._seen` dedupliziert nur im Prozessspeicher. Erfolgreiche Nachrichten
   bleiben auf Disk und werden in einem neuen Workflow-Prozess erneut gesehen; das ist keine
   dauerhafte Inbox-Bereinigung.

### Neue sichere Reihenfolge

1. **T0c zuerst:** `agent-city` muss `FederationNadi` aus der kanonischen Secret-Identität
   initialisieren und `city_report`/`bottleneck_escalation` im Steward-Wire-Format signieren.
   Produktionsbeweis: Quelle `ag_b670...`, nichtleere `payload_hash`/`signature`, keine neue ID.
2. **Echter Integrationstest:** Mit realem Transport, realem Gateway und realem Dharma-Hook
   beweisen, dass Claim und geschützte Nachricht genau einmal und in richtiger Reihenfolge
   verarbeitet werden. Kein Stub und kein Claim ohne `source`.
3. **Gateway-Rewire als zusammenhängender Steward-Fix:** `Path`/`json` reparieren, Legacy-
   Heartbeat-Verarbeitung auf echte Heartbeats begrenzen oder nach dem Gateway anordnen und
   sicherstellen, dass Bootstrap-Claims nicht vor dem Gateway entfernt werden.
4. **Zuerst Beobachtungsmodus:** Blockentscheidungen und erwartete Auswirkungen am echten
   Inbox-Snapshot protokollieren, bevor Fail-closed für alle Protected Operations scharf wird.
5. **Produktionsverifikation:** `GATEWAY`-Zeilen müssen erscheinen; direkte wiederholte
   Claim-Ingests müssen verschwinden; T0c-Signale dürfen nicht verloren gehen.
6. **Danach B':** Inbox und Registry gemeinsam nach dem verifizierten Kriterium purgen.

Bis diese Reihenfolge erfüllt ist, bleibt Ticket A blockiert. Es wurde in Phase 2 kein
Produktivcode verändert.
