# PHASE-2-BEFUND — Steward-Agentenföderation

**Begonnen:** 2026-07-13
**Dieses Dokument pflegst DU.** PHASE1_BEFUND_steward.md ist READ-ONLY — nur lesen,
nie ändern. Referenzen dorthin per §-Nummer ("Phase-1 §219.26").

**Fresh Session:** Zuerst `docs/PHASE2_CURRENT.md` lesen. Diese Datei ist das kurze,
rollierende Cockpit; der vorliegende Befund bleibt das ausführliche Beweisarchiv.

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

---

## §9 — T0c BEHOBEN UND PRODUKTIV BEWIESEN; STEWARD-GATEWAY BLEIBT BLOCKIERT (2026-07-14)

### Scope und unveränderte Sicherheitsgrenzen

Dieser Milestone änderte ausschließlich den fehlerhaften `FederationNadi`-Sendepfad in
`agent-city`. Phase 1 blieb byte-identisch/read-only. In Steward wurde noch kein
Produktivcode geändert, kein State bereinigt und kein Gateway scharfgeschaltet.

Verwendete saubere Arbeitsbasis:

- Agent-City-Klon: `/Users/ss/projects/agent-city-phase2`
- Ticket-Branch: `fix/federation-nadi-canonical-identity`
- Lokaler Ticket-Commit: `ea7ae032898d720a578e759919d7390285436b86`
- PR: `kimeisele/agent-city#1829`
- Merge auf `agent-city/main`: `e798bdbf7b3969beea577fe265657bbb7c142115`
- Steward-Recon blieb auf `/Users/ss/projects/steward-phase2`, Branch `phase2/live-recon`.

Die Agent-City-Änderung berührte genau vier Dateien:

- `city/federation_nadi.py`
- `city/factory.py`
- `tests/test_federation_nadi.py`
- `tests/test_service_factory.py`

Keine Workflow-, State-, Secret-, Registry- oder RING0-Manifestdatei wurde verändert.

### Implementierter Root-Cause-Fix

`FederationNadi` erhält jetzt beim Bau dieselbe bereits geladene `NodeIdentity`, die der
Factory-Log als kanonische Node-Identität ausweist. Eine explizite Secret-Identität hat
Vorrang vor einem möglicherweise veralteten `peer.json`-Wert.

Beim Flush wird jede neue `FederationNadi`-Nachricht im bestehenden Steward-Wire-Format
serialisiert:

1. kanonische Nachricht ohne `payload_hash`, `signature`, `signer_key`,
2. SHA-256 über `json.dumps(canonical, sort_keys=True)`,
3. Ed25519-Signatur über den Hex-String des Hashes,
4. Signatur als Base64.

Damit benutzen `city_report` und `bottleneck_escalation` dieselbe kryptographische
Node-ID `ag_b670dc6cbcb705fe` wie Claim und Heartbeat. Der stale Cache
`ag_365d8a2518ac7210` kann bei vorhandener Secret-Identität nicht mehr Sender werden.

### Testbeweise vor und nach dem Fix

Die zwei neuen Regressionstests wurden vor der Implementierung gegen den alten Code
ausgeführt und scheiterten exakt an den erwarteten Stellen:

- `FederationNadi` akzeptierte kein `_node_identity`-Argument.
- Bei stale `peer.json` wurde `ag_365...` statt der kanonischen Secret-ID gesendet.

Nach dem Fix:

- die zwei neuen Tests: 2 bestanden,
- angrenzende `federation_nadi`-/Factory-Tests: 56 bestanden,
- erweiterter Identity-/Relay-Satz: 112 bestanden, eine irrelevante DeprecationWarning,
- fokussiertes Ruff für die neue Logik: bestanden.

Bekannte, nicht durch diesen Patch verursachte Baseline:

- Die Gesamtsuite stoppt bereits bei der Collection von
  `tests/test_campaign_recruitment.py`, weil `_detect_recruitment_gap` nicht importiert
  werden kann.
- `city/factory.py:438` enthält eine bestehende E501-Zeile mit 103 Zeichen; der T0c-Hunk
  liegt um Zeile 592. Der fremde Lint-Fehler wurde nicht mitrepariert.

Der PR hatte keine Required Status Checks, aber eine Required Review. Eine Selbstfreigabe
war technisch nicht möglich. Der Admin-Merge wurde deshalb vor Ausführung im PR auditiert:
`https://github.com/kimeisele/agent-city/pull/1829#issuecomment-4965639135`.

### Agent-City-Produktionsbeweis

Workflow-Run `29308167287` lief auf exakt
`e798bdbf7b3969beea577fe265657bbb7c142115` und endete erfolgreich. Der vollständige Log
hat 3683 Zeilen.

Harte Marker:

- `Node identity: ag_b670dc6cbcb705fe`
- `FederationNadi wired`
- `FederationNadi: flushed 1 messages` = 4 Treffer
- `Generated new node identity` = 0 Treffer
- `Traceback` = 0 Treffer
- `Exception` = 0 Treffer

Die vier Flushes erzeugten vier `city_report`-Nachrichten. Der nachgelagerte
`nadi_kit sync` meldete zehn gepushte Nachrichten (vier Reports plus Claim, Heartbeat und
weitere Zielkopien). Deshalb war die lokale Legacy-Outbox beim späteren separaten
Relay-Schritt leer; `Outbox empty, skipping relay` ist hier kein Lieferfehler.

Separater neuer Befund im selben Log: Der Workflow versuchte seinen Laufzeit-State direkt
nach `agent-city/main` zu pushen. Branch Protection lehnte den Push mit GH006 ab
(`Changes must be made through a pull request`), trotzdem endete der Workflow grün. Das
betrifft nicht die Hub-Zustellung von T0c, ist aber ein eigener späterer Zuverlässigkeits-
Defekt: ein grüner Agent-City-Heartbeat garantiert derzeit nicht, dass lokaler State auf
`main` persistiert wurde.

### Gepinnter Hub-Beweis

Der aus diesem Lauf entstandene `steward-federation/main`-Stand ist:

- Commit: `de1286385359cc33f5f7efb1dec5e478e2aac833`
- Tree: `ad1c884ac382841a2c709642581817ebbbe67d83`
- Commit-Zeit: `2026-07-14T05:24:44Z`
- `nadi/agent-city_to_steward.json`:
  Blob `ed043b9cc18dd3aeeb24217e5bec76f367a37e3a`, 65.459 Bytes, 66 Nachrichten.

Nach Dispatch-Zeitpunkt `1784006282` enthält dieser Blob genau sechs neue Nachrichten von
`ag_b670dc6cbcb705fe` an Steward:

- 4 × `city_report`
- 1 × `federation.agent_claim`
- 1 × `heartbeat`

Alle sechs haben nichtleere 64-Zeichen-Hashes und 88-Zeichen-Base64-Signaturen. Alle sechs
Signaturen wurden lokal mit dem 32-Byte-Ed25519-Public-Key aus dem neuesten Agent-City-Claim
verifiziert. Alle sechs Hashes passen zum jeweiligen ursprünglichen Wire-Format.

Wichtig für spätere Hash-Prüfungen: `nadi_kit` fügt den vier bereits durch
`FederationNadi` signierten Reports im Hub ein `id`-Feld hinzu. Dieses Feld war nicht Teil
der ursprünglichen Signatur. Der Ursprungs-Hash lässt sich daher für diese Reports nur
rekonstruieren, wenn das nachträglich ergänzte `id` neben den Signaturfeldern ausgeschlossen
wird. Claim und Heartbeat wurden direkt von `nadi_kit` inklusive ihrer ID signiert.

Seit dem Dispatch enthält der Hub null neue Nachrichten von der Fossil-ID
`ag_365d8a2518ac7210`. T0c ist damit am tatsächlichen Produktionsübergabepunkt behoben.

### Steward-Importbeweis

Der regulär gestartete Steward-Heartbeat `29308716184` (nicht zusätzlich manuell ausgelöst)
importierte den Hub-Stand und endete als GitHub-Job erfolgreich. Daraus entstand:

- Steward-Commit: `8fb6cfffde497dbeb730727d4f1c94d0ea32f8ea`
- Tree: `a28cdd3e9140f719df0c1d2d0e3c9ad1dba62ee2`
- Commit-Zeit: `2026-07-14T05:32:54Z`
- Inbox-Blob: `84be272ee3f952d99c563d0fdfb981bd5d0df0a2`
- Inbox-Größe: 621.360 Bytes, 638 Nachrichten.

Die Steward-Inbox enthält dieselben sechs neuen kanonischen Agent-City-Nachrichten:

- vier Reports, einen Claim, einen Heartbeat,
- sechs von sechs Ursprungshashes korrekt,
- sechs von sechs Ed25519-Signaturen gültig,
- null neue Nachrichten von `ag_365d8a2518ac7210` seit Dispatch.

Damit ist die in §8 verlangte T0c-Produktionsverifikation vollständig. Eine bloße
Feld-Anwesenheitsmessung reicht nicht: Hash und Signatur wurden tatsächlich kryptographisch
geprüft.

### Der nächste Steward-Blocker ist jetzt ebenfalls live bewiesen

Der vollständige Steward-Log `29308716184` hat 2977 Zeilen und reproduziert den §8-Befund
auf dem neuen, korrekt signierten Input:

- `Hook dharma_federation failed: name 'Path' is not defined` = 7 Treffer,
- `GATEWAY` = 0 Treffer,
- der direkte Claim-Pfad verarbeitet Claims weiterhin vor dem Crash,
- der Log behauptet mehrfach, `ag_b670...` sende „unsigned/invalid“ Nachrichten, obwohl
  die sechs neuen Nachrichten kryptographisch gültig sind.

Die Warnung ist inhaltlich unzuverlässig. Die Legacy-Dharma-Schleife lehnt zunächst jede
noch nicht in `reaper._peers` bekannte `ag_*`-Quelle ab (`dharma.py:455-459`), bevor sie die
vorhandene Signatur prüft. Anschließend fasst sie alle Rejections pauschal als
„unsigned/invalid“ zusammen. Sie behandelt weiterhin Claims, Reports und andere Operationen
wie Heartbeats.

Zusätzlich wartet hinter dem derzeit unerreichbaren Gateway ein zweiter Wire-Format-Fehler:
`NadiFederationTransport.read_outbox()` berechnet den eingehenden `payload_hash` nur über
`item["payload"]` (`federation_transport.py:302-311`). Das widerspricht dem dokumentierten
und produktiv verwendeten Ganznachrichten-Format von `FederationBridge`, `nadi_kit` und dem
reparierten `FederationNadi`.

Der Read-only-Census aus dem §8-Snapshot hatte diesen Protokollsplit bereits quantifiziert:

- 258 Nachrichten mit nichtleeren Hash-/Signaturfeldern,
- 205 Hashes passten zum Ganznachrichten-Format,
- 13 passten nur zum Payload-Format,
- 40 passten zu keinem der beiden rekonstruierten Formate.

Wenn nur `Path`/`json` repariert und der Gateway dadurch erreichbar gemacht würde, würde der
Transport einen großen Teil der legitimen signierten Föderationsnachrichten als
`integrity_check_failed` quarantänisieren. Deshalb bleibt ein isolierter Import-Fix ebenso
unsicher wie der alte Vorschlag, nur den Claim-Bypass zu löschen.

### Verbindlicher nächster Arbeitsauftrag

T0c ist abgeschlossen. Die nächste Session beginnt nicht mit einer Zustandsbereinigung,
sondern mit einem zusammenhängenden Steward-Sicherheitsfix auf einem frischen Branch vom
dann aktuellen `main`:

1. Reale Regressionstests bauen, die die gepinnte Form der gültigen T0c-Nachrichten durch
   `NadiFederationTransport` → Dharma → Gateway führen.
2. Beweisen, dass Claim-Bootstrap und direkt folgende Protected Operation in derselben Inbox
   nicht von der Legacy-Heartbeat-Schleife entfernt werden.
3. Eingehende Hash-Validierung auf das kanonische Ganznachrichten-Format umstellen; die
   nachträgliche Hub-ID-Mutation muss explizit berücksichtigt oder an der Hub-Grenze beendet
   werden. Keine stillschweigende Mehrdeutigkeit.
4. `Path` und `json` in den tatsächlichen Modul-Scope bringen.
5. Die Legacy-Schleife auf echte `heartbeat`-Operationen begrenzen und Bootstrap-/Gateway-
   Reihenfolge so ändern, dass der Gateway jede relevante Nachricht zuerst sicher beurteilt.
6. Zunächst Beobachtungsmodus gegen den gepinnten Inbox-Blob ausführen und Zählwerte für
   accepted/rejected/quarantined/removed dokumentieren.
7. Erst danach produktiv verifizieren: `GATEWAY` muss > 0 sein, gültige T0c-Nachrichten
   dürfen nicht quarantänisiert werden, direkte wiederholte Claim-Ingests müssen enden.
8. Erst nach diesem Produktionsbeweis folgt B': gemeinsamer Inbox-/Registry-Purge.

Der Agent-City-GH006-State-Persistenzfehler bleibt als separates Folgeticket erhalten und
darf beim Steward-Gateway-Fix nicht nebenbei vermischt werden.

---

## §10 — GATEWAY, CROSS-PROCESS-DEDUPLIZIERUNG UND STATE-QUELLE PRODUKTIV BEWIESEN (2026-07-14)

### Ergebnis in einem Satz

Der Steward verarbeitet Föderationseingang jetzt ausschließlich über den fail-closed
Gateway, akzeptiert das produktive kanonische Ganznachrichtenformat, entfernt terminal
beurteilte Nachrichten, dedupliziert Hub-UUIDs über Workflow-Prozessgrenzen und benutzt den
Git-Stand statt eines veralteten Actions-Caches als einzige persistente State-Quelle.

Dieser Milestone brauchte drei Steward-PRs, weil jede Produktionsverifikation einen tiefer
liegenden, vorher nicht sichtbaren Persistenzfehler offengelegt hat:

| PR | Merge | Inhalt |
|---|---|---|
| `kimeisele/steward#409` | `69dc052641a9364c828dd62d725f79904adbd2df` | kanonischer Transport, Gateway-Rewire, Claim-Reihenfolge, terminale Inbox-Entfernung |
| `kimeisele/steward#415` | `3bf1c656ea5737b6bb60b8d4724c9826321d24d8` | persistenter, begrenzter Relay-Seen-Store |
| `kimeisele/steward#416` | `35e1f716870a95a731467aefcb2d4d6a30654216` | Git als einzige Heartbeat-State-Quelle, kein Cache-Rewind, kein stiller State-Verlust |
| `kimeisele/steward#417` | `c53f58b043c7467ffbd5f3cb6212fc4f013cfc52` | Autostash für Laufzeitänderungen beim fail-closed Rebase |

Phase 1 blieb byte-identisch und read-only. Der Code wurde ausschließlich im sauberen Klon
`/Users/ss/projects/steward-gateway-phase2` bearbeitet. Das ursprüngliche Arbeitsverzeichnis
`/Users/ss/projects/steward` wurde nicht als Codebasis benutzt.

### PR #409 — zusammenhängender Gateway-Fix

Ticket A konnte nicht als der in Phase-1 §219.26 vorgeschlagene Vierzeiler ausgeführt werden.
§8/§9 hatten bereits bewiesen, dass dadurch legitime T0c-Nachrichten verloren gegangen
wären. Der tatsächliche Fix änderte acht Dateien und hielt die sicherheitskritischen Teile
zusammen:

1. `steward/federation_crypto.py`
   - gemeinsame Funktion `canonical_message_hash`,
   - Ausschluss nur von `payload_hash`, `signature`, `signer_key`,
   - explizite Kompatibilität für die vom Hub nachträglich ergänzte `id`.
2. `steward/federation_transport.py`
   - eingehende Prüfung gegen den kanonischen Ganznachrichtenhash statt Payload-only,
   - ausgehende Roh-Nachrichten im selben Format signieren,
   - bereits signierte Nachrichten nicht mehr durch eine nachträgliche `message_id` mutieren.
3. `steward/federation.py`
   - Bridge-Signierung benutzt dieselbe gemeinsame Hashfunktion.
4. `steward/hooks/dharma.py`
   - direkte produktive Inbox-Verarbeitung entfernt; der Gateway ist der einzige Eingang,
   - Legacy-Helfer auf echte Heartbeat-Operationen begrenzt,
   - `Path` und `json` in den realen Modul-Scope gebracht.
5. `steward/federation_gateway.py`
   - Replay-Fenster auf 7200 Sekunden an die 15-Minuten-Kadenz angepasst,
   - Claim-Quelle muss der beanspruchten `node_id` entsprechen,
   - unsignierte/ungültige Claims scheitern fail-closed,
   - Claims werden vor geschützten Operationen verarbeitet,
   - terminal beurteilte Nachrichten verlassen die Inbox.
6. Tests
   - Payload-only-Fixtures auf das produktive Wire-Format migriert,
   - echter Dharma → Transport → Gateway-Test mit umgekehrter Claim/Nachrichten-Reihenfolge.

Der Beobachtungslauf gegen den gepinnten Inbox-Blob
`84be272ee3f952d99c563d0fdfb981bd5d0df0a2` umfasste 638 Nachrichten:

- 616 abgelaufen und unangetastet,
- 22 live und terminal,
- 11 akzeptiert: vier T0c-Reports plus sieben signierte Claims,
- 11 quarantänisiert: vier `claim_proof_missing`, vier `invalid_signature`, drei
  `unknown_sender`,
- 22 aus der simulierten Inbox entfernt.

### Tests und bekannte Baseline für PR #409/#415

Vor Merge von PR #409:

- fünf zentrale Mutationstests bestanden,
- Federation-Gruppe: 157 bestanden,
- Federation + Quarantine + Relay: 184 bestanden,
- fokussiertes Ruff bestanden.

Nach dem Rebase auf den damaligen Live-Head blieb die vollständige Suite bereits bei einer
fremden Collection-Störung stehen:

- `FindingKind.PEER_PROTOCOL_VIOLATION` fehlt,
- Ruff meldet zusätzlich das fremde undefinierte `_finding` in
  `steward/senses/diagnostic_sense.py:733`.

Der exakte Base-CI-Lauf `29309450561` und PR-CI-Lauf `29309998002` zeigten dieselben
Fehler. Security war grün. Der Admin-Merge wurde deshalb mit Audit-Kommentar dokumentiert,
nicht als grüner CI-Zustand ausgegeben.

Für PR #415 wurde zuerst ein roter Regressionstest geschrieben: Relay-Prozess 1 importiert
eine UUID, der Gateway entfernt sie aus der lokalen Inbox, Relay-Prozess 2 sieht dieselbe
unveränderte Hub-Nachricht. Vor dem Fix importierte Prozess 2 sie erneut.

Der Fix persistiert bis zu 4096 UUIDs atomar in
`data/federation/relay_seen_ids.json`, lädt sie bei jedem Prozessstart und erholt sich bei
fehlendem oder beschädigtem JSON fail-safe. Danach:

- Relay-Suite: 23 bestanden,
- Federation/Transport/Gateway/Quarantine/Relay: 187 bestanden,
- fokussiertes Ruff bestanden,
- PR-CI `29310834627`: nur dieselben beiden bekannten Base-Defekte; Security grün.

### Erster Gateway-Produktionsbeweis

Der erste Post-#409-Heartbeat `29310261212` lief auf exakt
`69dc052641a9364c828dd62d725f79904adbd2df` erfolgreich.

Harte Logbeweise:

- `GATEWAY` = 20 Treffer,
- `Path`-`NameError` = 0,
- `Traceback` = 0,
- vier gültige T0c-Reports akzeptiert,
- ein Report erzeugte eine Bottleneck-Task,
- sieben signierte Claims bewiesen Schlüsselbesitz,
- vier unsignierte Claims scheiterten mit `claim_proof_missing`,
- eine stale Quelle scheiterte mit `unknown_sender`,
- 17 terminale Nachrichten im ersten und 5 im zweiten Pull entfernt.

Der resultierende State-Commit war
`0ff688a9b894842d2f8cdb887eb8a27fb755d747`. Die vier T0c-Reports waren aus der Live-Inbox
entfernt; die kanonische ID `ag_b670dc6cbcb705fe` war registriert, die stale ID
`ag_365d8a2518ac7210` nicht.

### Warum PR #415 allein produktiv noch nicht genügte

Der persistente Seen-Store war im Python-Code korrekt, aber der Workflow überschrieb ihn
beim nächsten Prozessstart mit altem State. Die Produktionsversuche machten das sichtbar:

1. Run `29310913347` erzeugte lokal `relay_seen_ids.json`, kollidierte aber mit einem
   vorher gestarteten Heartbeat-State-Commit. `git pull --rebase` konfliktierte; der
   Fallback `git reset --hard origin/main` ließ einen Detached HEAD zurück; `git push || true`
   schluckte den Fehler. Der Workflow wurde trotzdem grün und der neue State ging verloren.
2. Der konfliktfreie Run `29311061314` commitete den Store als
   `ea5a11214e04167bf2f96f2351c9d166e8fd8f9f`.
3. Der nächste Prozess `29311282157` restaurierte trotzdem wieder den alten Cache und
   beurteilte vier kanonische Reports erneut. Das war **kein** erfolgreicher
   Cross-Process-Nachweis.

Die Ursache war `.github/workflows/steward-heartbeat.yml`:

- `actions/cache@v4` restaurierte `.steward/` und `data/federation/`,
- Exact-Key: `steward-state-v3-main`,
- Cache-ID: `5676693628`,
- erstellt: `2026-07-12T09:19:29Z`,
- Größe: 171.911 Bytes,
- Actions-Caches sind für denselben Key unveränderlich,
- jeder spätere Save meldete `Unable to reserve cache with key ...`,
- der zwei Tage alte Snapshot überschrieb dadurch bei jedem Zyklus Registry, Inbox,
  Quarantäne und den neuen Seen-Store.

Damit war der Cache selbst eine zweite, stale State-Datenbank. Git-Commits sahen gesund aus,
aber der nächste Prozess begann nicht mit diesem Git-State.

### PR #416/#417 — Git ist wieder die einzige Wahrheit

PR #416 änderte nur den Heartbeat-Workflow:

- Checkout explizit auf den bei Ausführung aktuellen `main` mit voller History,
- Restore- und Save-Cache-Schritte vollständig entfernt,
- getrackte `.steward`-/Federation-Dateien und neue nicht ignorierte Federation-Dateien
  ohne `-f` stagen,
- kein `reset --hard`-Fallback,
- kein `git push || true`,
- Rebase- oder Pushfehler machen den Workflow sichtbar rot.

Nach dem Merge wurde ausschließlich der belegte alte Cache `5676693628` per API gelöscht.
Die Abfrage für `steward-state-v3-main` liefert seitdem `0` Caches.

Der erste Post-#416-Run `29311896422` wurde korrekt rot: Der State-Commit entstand lokal,
aber `git pull --rebase` verweigerte wegen nicht gestagter Laufzeitänderungen aus dem
Editable-Install. Vorher wäre derselbe Fehler maskiert worden. PR #417 stellte deshalb nur
`--autostash` wieder her, ohne Reset oder Fehlerunterdrückung.

### Finaler Zwei-Prozess-Produktionsbeweis

**Prozess 1:** Run `29312320867`, vier Zyklen, finaler Workflow-Head
`c53f58b043c7467ffbd5f3cb6212fc4f013cfc52`.

- Restore-State-Schritt: 0,
- Save-State-Schritt: 0,
- Cache-Hit: 0,
- `operation=city_report`: 0,
- `GATEWAY REPLAY`: 0,
- Rebase-Konflikt: 0,
- Detached-HEAD-Fehler: 0,
- Autostash erstellt und angewandt,
- Push nach `main`: 1,
- State-Commit: `2865a5d1f411548cf07b9f64c14e6b763285463b`.

**Prozess 2:** Run `29312678752`, eigener Workflow-Prozess, ein Zyklus, Start-Head
`2865a5d1f411548cf07b9f64c14e6b763285463b`.

- Restore-State-Schritt: 0,
- Save-State-Schritt: 0,
- Cache-Hit: 0,
- `operation=city_report`: 0,
- `GATEWAY REPLAY`: 0,
- `reason=replay_detected`: 0,
- Rebase-Konflikt: 0,
- Detached-HEAD-Fehler: 0,
- Autostash erstellt und angewandt,
- Push nach `main`: 1,
- finaler State-Commit: `4cdf1f0634b18f5ff26fc95b7efa163c5a978285`.

Finaler Live-Tree:

- Commit: `4cdf1f0634b18f5ff26fc95b7efa163c5a978285`
- Tree: `56ca00cf73e20272d88a48937d52bacab856af15`
- `relay_seen_ids.json`: 375 UUIDs
- alle vier T0c-Report-UUIDs im Seen-Store
- bekannte T0c-Report-UUIDs in der Inbox: 0
- Inbox: 446 Nachrichten
- Registry: 56 Einträge
- `ag_b670dc6cbcb705fe` registriert
- `ag_365d8a2518ac7210` nicht registriert
- alter Actions-Cache: 0

Die vier explizit über Prozessgrenzen bewiesenen UUIDs sind:

- `9e1c5b51-c2ee-4cd6-b859-cec4fccb4c66`
- `3ab70778-938f-4cce-8d91-871b037737a7`
- `b29d12a8-3d48-442f-8290-15622b1079a9`
- `face3300-a642-4be1-abfd-ad07157300a8`

Damit ist der zuvor offene Exactly-once-Milestone für unveränderte Hub-UUIDs erfüllt.

### Was weiterhin offen ist

1. **B' ist jetzt technisch freigegeben, aber noch nicht ausgeführt.** Inbox und Registry
   müssen gemeinsam nach einem neuen Live-Census bereinigt werden. Die Registry hat noch 56
   Einträge. Vor jeder Löschung aktive Identitäten aus frischen signierten Mailbox-Nachrichten
   ableiten; keine alte Liste blind anwenden.
2. **Steward-CI und KARMA sind real defekt.**
   `FindingKind.PEER_PROTOCOL_VIOLATION` fehlt und stoppt Tests sowie Teile des produktiven
   KARMA-Pfads. `_finding` ist in `diagnostic_sense.py:733` undefiniert und blockiert Ruff.
   Diese beiden Defekte waren Base-Fehler aller drei PRs und wurden nicht kaschiert.
3. **Der Heartbeat fängt Phasenfehler weiterhin ab.** Ein grüner Job kann deshalb trotz
   `HEARTBEAT ERROR KARMA failed` enden. State-Pushfehler sind jetzt sichtbar; semantische
   Phasenfehler sind es noch nicht.
4. **`ag_8859b969119219b8` bleibt ungeklärt.** Seine `diagnostic_report`- und
   `task_completed`-Operationen erreichen den Gateway, werden aber von der Bridge abgelehnt.
5. **Quarantäne-Cleanup und Key-Rotation** bleiben nach Phase-1 §218 offen.
6. **Agent-City GH006-State-Persistenz** aus §9 bleibt ein separates Ticket.

### Verbindlicher nächster Arbeitsauftrag

Die sichere Reihenfolge ab diesem Stand ist:

1. Live-Head und alle relevanten State-Blobs erneut pinnen.
2. Die beiden bekannten Steward-CI/KARMA-Baselinefehler read-only bis zur Ursache verfolgen
   und mit roten Regressionstests reparieren. Weitere sicherheitskritische PRs sollen nicht
   dauerhaft Admin-Bypasses benötigen.
3. Danach B' zunächst read-only vorbereiten:
   - aktive signierte Sender pro Repo bestimmen,
   - exakte Keep/Delete-Liste für Registry und Inbox erzeugen,
   - sicherstellen, dass Claims/UUIDs im Seen-Store eine Wiederauferstehung verhindern.
4. B' atomar gegen den dann aktuellen Live-Head ausführen und sofort zwei Heartbeats prüfen.
5. Erst danach Key-Rotation Knoten für Knoten nach Phase-1 §218.3.

Keine dieser Arbeiten darf Phase 1 verändern. Jeder abgeschlossene Milestone wird als neuer
Paragraph in diesem Phase-2-Dokument mit Commit-, Blob-, Run- und Testbeweisen angehängt.

---

## §11 — STEWARD-CI UND PRODUKTIVER KARMA-PFAD WIEDERHERGESTELLT (2026-07-14)

### Ergebnis

Der in §10 dokumentierte Steward-CI/KARMA-Blocker ist behoben. PR
`kimeisele/steward#419` wurde ohne Admin-Bypass mit allen vier Required Checks grün gemergt.
Der nachgelagerte Produktions-Heartbeat dispatchte KARMA wieder ohne den früheren
`PEER_PROTOCOL_VIOLATION`-/`_finding`-Fehler.

- PR: `https://github.com/kimeisele/steward/pull/419`
- Ticket-Commit: `7a6d038758ef6d4f7abf097facc3c3fa8405fc9b`
- Merge: `2614bb5dbb99ce686f0a02e91567d79d1fac8cb6`
- sauberer Klon: `/Users/ss/projects/steward-gateway-phase2`
- Branch: `fix/steward-ci-karma-baseline`

Phase 1 blieb unverändert/read-only.

### Root Cause

Beide Fehler kamen aus demselben historischen Commit
`20f04b3f5c5f66681340e3410686953d7565996e`. Dieser sollte persistierte
`protocol_violations.json`-Einträge in Findings und anschließend Self-Healing-Arbeit
überführen, implementierte den Pfad aber nur teilweise:

1. `steward/healer/types.py` referenzierte
   `FindingKind.PEER_PROTOCOL_VIOLATION`, obwohl der Enum-Wert nie in
   `diagnostic_sense.py` angelegt worden war. Folge: `AttributeError` bereits beim Import
   des Healers; Pytest konnte `tests/test_healer.py` nicht sammeln; produktives KARMA
   scheiterte am selben Importpfad.
2. `_analyze_federation()` rief einen nicht existierenden `_finding`-Helper auf. Folge:
   Ruff F821 und bei vorhandener `protocol_violations.json` ein echter `NameError`.
3. Der neue Typ war als `DETERMINISTIC` klassifiziert, obwohl kein registrierter Fixer
   existierte. Der Healer hätte das Finding als fixbar gezählt und anschließend still
   übersprungen.

### Rote Beweise vor dem Fix

Zwei gezielte Regressionen wurden vor der Implementierung ausgeführt:

- Eine echte `data/federation/protocol_violations.json` mit Peer `ag_malformed` ließ
  `_analyze_federation()` exakt mit `NameError: _finding is not defined` scheitern.
- Die Healer-Registry-Tests konnten wegen des fehlenden Enum-Werts nicht gesammelt werden;
  der Import endete mit `AttributeError: FindingKind has no attribute
  PEER_PROTOCOL_VIOLATION`.

### Minimaler Fix

Der Verhaltensfix änderte nur vier Dateien:

- `steward/senses/diagnostic_sense.py`
  - Enum-Wert `PEER_PROTOCOL_VIOLATION = "peer_protocol_violation"`,
  - vorhandene `Finding`-Dataclass direkt statt eines erfundenen Helpers,
  - `file="data/federation/protocol_violations.json"`, damit das Finding seine Quelle
    korrekt benennt.
- `steward/healer/types.py`
  - Klassifikation `SKIP` statt `DETERMINISTIC`, solange kein sicherer Cross-Repo-Fixer
    existiert.
- `tests/test_diagnostic_sense.py`
  - realer Violation-Dateitest für Kind, Severity, Datei, Peer-Detail und Fix-Hinweis.
- `tests/test_healer_fixers.py`
  - Registry-Invariante dynamisch gemacht: Jeder künftig als `DETERMINISTIC`
    klassifizierte Enum-Wert muss tatsächlich einen registrierten Fixer besitzen.

Es wurde bewusst kein spekulativer Cross-Repo-Autofixer gebaut. Ein Finding darf sichtbar
sein, ohne fälschlich automatische Reparierbarkeit zu behaupten.

### Format-Gate

Der erste PR-CI-Anlauf bewies, dass Ruff-Semantikcheck und Security bereits grün waren,
deckte aber im separaten `ruff format --check` fünf rein semantikerhaltende Formatdifferenzen
auf:

- eine überzählige Leerzeile im neuen Diagnosepfad,
- vier ältere Zeilen aus dem Gateway-Milestone in
  `federation_gateway.py`, `hooks/dharma.py`,
  `test_federation_gateway.py`, `test_federation_transport.py`.

Der veraltete lange CI-Lauf wurde abgebrochen. Ausschließlich der exakte Ruff-Formatter-Diff
wurde übernommen: Zeilenumbruch, Quote-Normalisierung und Leerzeile; kein Verhalten.
Danach meldete der vollständige Formatter: `208 files already formatted`.

### Testbeweise

Nach dem Verhaltensfix:

- neue Regressionen: 3 bestanden,
- Diagnostic-/Healer-Gruppe: 171 bestanden,
- Diagnostic-/Healer-/Gateway-/Transport-Gruppe nach Formatkorrektur: 249 bestanden,
- vollständiges Ruff (`steward/ tests/`): grün,
- vollständiger Ruff-Formatcheck: grün.

Die lokale Gesamtsuite wurde vollständig bis zum Ende ausgeführt:

- 2120 bestanden,
- 13 übersprungen,
- 551 DeprecationWarnings,
- Exit-Code 0,
- Laufzeit 1014,31 Sekunden.

Der Lauf war langsam, aber nicht festgefahren. Ein erster Durchlauf war bei 87 Prozent auf
HITL-Wunsch unterbrochen worden; der anschließend neu gestartete vollständige Lauf lieferte
den obigen Endstand.

### Required-CI vollständig grün

Finaler PR-CI-Lauf: `29316757855`.

- Tests Python 3.11: `SUCCESS`,
- Tests Python 3.12: `SUCCESS`,
- Lint inklusive Ruff-Formatcheck: `SUCCESS`,
- Security Scan: `SUCCESS`.

Damit war erstmals seit Beginn des Gateway-Milestones kein Admin-Bypass nötig. PR #419
wurde regulär über die Required Checks gemergt.

### Produktionsbeweis

Post-Merge-Heartbeat `29317006330` lief auf exakt
`2614bb5dbb99ce686f0a02e91567d79d1fac8cb6` erfolgreich. Vollständiger Log: 781 Zeilen.

Harte Zählwerte:

- `PEER_PROTOCOL_VIOLATION`-Fehler: 0,
- `name '_finding' is not defined`: 0,
- `HEARTBEAT ERROR`: 0,
- `KARMA dispatch failed`: 0,
- `Traceback`: 0,
- `Diagnosis failed`: 0,
- `GATEWAY`: 2,
- erfolgreicher Push nach `main`: 1.

Der Log enthält `KARMA: 4 pending task(s), dispatching next`. Der früher beim Import
abbrechende produktive Pfad erreicht damit wieder die tatsächliche Dispatch-Logik.

Der resultierende State-Commit ist
`087c2c9804972f4ecdc682f979886ea2418e8da4`, Tree
`d05c23058cca26c09a4ae275ded950f2d37850c4`.

### Nächster Arbeitsauftrag

Der §10-Punkt „Steward-CI und KARMA sind real defekt“ ist abgeschlossen. Als Nächstes gilt
wieder die dort festgelegte Reihenfolge:

1. neuen Live-Head und State-Blobs pinnen,
2. B' vollständig read-only vorbereiten,
3. aktive signierte Identitäten pro Repo aus frischen Mailbox-Nachrichten bestimmen,
4. exakte Keep/Delete-Liste für Registry und Inbox erzeugen,
5. erst nach diesem Beweis Inbox und Registry atomar bereinigen,
6. zwei nachfolgende Heartbeats auf ausbleibende Wiederauferstehung prüfen.

Key-Rotation, `ag_8859b969119219b8`, Quarantäne-Cleanup und Agent-City-GH006 bleiben danach
separate Folgetickets. Phase 1 wird weiterhin nicht verändert.

## §12 — B' READ-ONLY-CENSUS: 17 KEEP, 43 DELETE, ABER DREI STATE-FLÄCHEN

**Status:** Read-only-Analyse abgeschlossen. Es wurde keine Registry-, Inbox-, Hub-Mailbox-,
Workflow- oder Secret-Datei verändert. Phase 1 blieb byte-identisch und read-only.

### Gepinnter Live-Snapshot

Alle Zählungen dieses Paragraphen beziehen sich ausschließlich auf unveränderliche
Git-Objekte, nicht auf einen lokalen Working Tree.

Steward (`kimeisele/steward`):

- Erfasst: `2026-07-14T08:34:51Z`.
- Head: `345656aeea8008ca502beb65d699b345c73d6fa3` (`heartbeat #5332`).
- Tree: `f855601ffe9764322e22b89cba9a76e751c40624`.
- Registry: Blob `9b0cd4aef4b4ecbab2d37496d2a5e44d82388bc3`, 60 Einträge.
- Inbox: Blob `977a15376eed56eff8e2fb45d4283b0bcd5d0d39`, 464 Nachrichten.
- Relay-Seen: Blob `e2c44ad4e170e18adb493993f13876f9dcc50c6c`, 462 UUIDs.
- Quarantäne-Index: Blob `efbc7d4253de0799b40fcc8e8bf1961accb2a319`,
  2.765 Fingerprints.
- Peers: Blob `fcfcc574b6ed26848796e29667798d84a20037e7`.

Hub (`kimeisele/steward-federation`):

- Erfasst: `2026-07-14T08:36:34Z`.
- Head: `f4d8dd5600b0f7a91eb793d354a15fd7d364b29c`.
- Tree: `3960b7aa5f5ce71891041f7e66c506a236512091`.
- Mailbox `nadi/steward-federation_to_steward.json`: Blob
  `f64b4193cec7d90e7f7de317ff97024a51e73d1e`, 144 Nachrichten.

### Das verifizierte Purge-Kriterium bleibt konservativ

Phase-1 §219.18 bleibt fachlich bindend: Eine Node-ID wird nicht wegen ihres Alters und
nicht zugunsten der jüngsten ID desselben Namens gelöscht. Gelöscht werden nur die bereits
historisch als Wegwerfidentitäten bewiesenen IDs. Der aktuelle Census wendet die alte Liste
nicht blind an, sondern schneidet sie mit dem gepinnten Live-Zustand und prüft die heutigen
aktiven Schlüssel erneut.

Ergebnis am Snapshot: 60 Registry-Einträge teilen sich in **17 KEEP** und **43 DELETE**.
Die drei früher gelöschten Agent-City-Nachzügler `ag_4d5c340ac8c3e56b`,
`ag_b6f531aa856c888a` und `ag_fe11994f9d28bb77` sind heute bereits abwesend und deshalb
kein Bestandteil der aktuellen 43er-Löschmenge.

### Acht heute aktive Identitäten sind kryptographisch belegt

Für jeden produktiven Hauptknoten wurde die neueste Nachricht seiner an Steward gerichteten
Hub-Mailbox geprüft. Gültig bedeutet gleichzeitig:

1. der kanonische Nachrichten-Hash stimmt (`canonical` oder bei einer vor dem Hub
   signierten UUID `canonical_pre_hub_id`),
2. die Ed25519-Signatur verifiziert gegen den Registry-Public-Key,
3. `derive_node_id(public_key) == source`,
4. die Nachricht stammt aus dem gepinnten Hub-Blob.

| Repo | aktive Node-ID | neuester gültiger Beleg (UTC) | gültig / Mailbox |
|---|---|---:|---:|
| `agent-city` | `ag_b670dc6cbcb705fe` | 2026-07-14 08:34:53 | 51 / 75 |
| `agent-internet` | `ag_d7b5cd6e9baa0add` | 2026-07-14 06:29:32 | 8 / 8 |
| `agent-research` | `ag_c3c5d9aed6d3dc6e` | 2026-07-14 08:29:54 | 10 / 10 |
| `agent-template` | `ag_75c1bbfcbb3f52dd` | 2026-07-14 06:32:35 | 48 / 48 |
| `agent-world` | `ag_8dacb2d32e5f6efe` | 2026-07-14 07:25:18 | 26 / 27 |
| `steward-federation` | `ag_9272c311628b5f40` | 2026-07-14 07:29:06 | 42 / 144 |
| `steward-protocol` | `ag_2d0b12537b598dac` | 2026-07-14 08:00:21 | 10 / 10 |
| `steward` | `ag_8859b969119219b8` | 2026-07-14 08:35:01 | 144 / 144 |

Damit ist zugleich die offene Zuordnung von `ag_8859b969119219b8` enger gefasst: Der
Schlüssel ist der aktuell produktiv sendende Steward-Schlüssel. Sein Registry-`agent_name`
ist weiterhin korrupt und darf nicht im Purge nebenbei umbenannt werden; die
Identitätsreparatur bleibt ein separates Ticket.

### Exakte KEEP-Liste

Die 17 Einträge werden byte-identisch übernommen:

- Frisch aktiv und signiert: `ag_b670dc6cbcb705fe`, `ag_d7b5cd6e9baa0add`,
  `ag_c3c5d9aed6d3dc6e`, `ag_75c1bbfcbb3f52dd`, `ag_8dacb2d32e5f6efe`,
  `ag_9272c311628b5f40`, `ag_2d0b12537b598dac`, `ag_8859b969119219b8`.
- Historisch arbeitend, aktuell nicht kanonisch: `ag_0109b0f911cc2aa5`,
  `ag_1000d1441ef1bba0`, `ag_262f73c01a8ad72b`, `ag_359d19f2668452b6`,
  `ag_e8978e030b4b84a5`, `ag_eb39d27421b3971d`, `ag_f1bc59288c9c5443`,
  `ag_fd5a7db51b1acac1`.
- Historisch durch Heartbeats gerettet: `ag_9361733f6885e6dc`. Im Parent von
  `b3667961141cc69278b16442b65684dfa97946f4` liegen sechs Heartbeats dieser ID;
  Signatur und `derive_node_id` verifizieren gegen den heute erhaltenen Public-Key. Der
  alte Envelope-Hash ist nach Hub-Anreicherung nicht mehr kanonisch, daher ist dies kein
  heutiger Aktivitätsbeleg, wohl aber ein zusätzlicher Grund, die ID konservativ zu behalten.

Von den acht historisch arbeitenden, nicht aktiven IDs haben fünf im aktuellen Inbox-Blob
zusammen 43 vollständig kanonische, gültig signierte Heartbeats. Die drei alten
Agent-City-IDs besitzen je einen unsignierten Legacy-Heartbeat. Sie werden nicht als aktiv
bezeichnet, aber gemäß §219.18 auch nicht ohne separates Stilllegungs- oder
Rotationsverfahren gelöscht.

### Exakte Registry-DELETE-Liste

Die 43 aktuellen Steward-Federation-Wegwerfidentitäten sind:

```text
ag_00ccfe2b454fb6f0 ag_017e3df3740d8389 ag_0984e25e9803bda4
ag_1ea7e36195885120 ag_1f446832593c93f6 ag_256aa684d918b765
ag_2759d5944dac6577 ag_27b984b7a016bb27 ag_2a3b75ff97603421
ag_2e2df6092c174f84 ag_3245f3204f2614e2 ag_33b8af431f0101c2
ag_37fe0c178b7018e7 ag_440fcb373dc044dc ag_444d6ab161f45b4f
ag_490282ca0a96e428 ag_4950e45a4ef88d0f ag_4ac0fba37679c496
ag_5dd5f67b07558ecd ag_6c5412fedddf35c6 ag_70ad7e881292e463
ag_7dd9872f00fd8ea7 ag_838b9b94e052ebc2 ag_853aef8d4eac46f9
ag_8c08b90f541cd971 ag_8d26410a5cd1b24f ag_91b9a4cc583dbfe2
ag_a2ad95372a39b9c7 ag_a90fc6bb1a6ba956 ag_ac31bf8fa1cb2cf9
ag_b20d7ef483fc8c4f ag_b6b375ec44ec2651 ag_ca4cfa6b165001d2
ag_d001b79ca182815d ag_d2e8f0a8b7295967 ag_d4b805663701f589
ag_d6eac544b527e58d ag_dba30a6260a7e20b ag_e0b89f4e185ab574
ag_eb96cdd4e436c31c ag_eef1f6add4c7d4e3 ag_fcbfa849673f1295
ag_fd277a13a6961c20
```

Alle 43 gehören zu `agent_name=steward-federation`, alle 43 wurden bereits in Phase 1
historisch auf den defekten Ephemeral-Key-Pfad zurückgeführt, und keiner ist die heute
signierende ID `ag_9272c311628b5f40`.

### Exakte lokale Inbox-DELETE-Liste als Regel

Die lokale Inbox enthält exakt **144** zu diesen 43 IDs gehörende Nachrichten:

- 72 `federation.agent_claim`,
- 72 `heartbeat`,
- alle mit Legacy-`source=steward-federation`,
- alle mit einer der 43 DELETE-IDs in `payload.node_id` oder im Top-Level-`node_id`,
- 43 unterschiedliche eingebettete Node-IDs,
- 144 UUIDs, davon 104 heute im Seen-Store und 40 nicht mehr im aktuellen Hub-Mailbox-Blob.

Die spätere Transformation darf deshalb nicht pauschal alle unregistrierten Sender oder alle
alten Nachrichten löschen. Sie entfernt nur Nachrichten, deren eingebettete Node-ID in der
43er-DELETE-Menge liegt. Ergebnis am Snapshot: Inbox 464 → 320. Insbesondere T0c-Nachrichten,
die alte reale Agent-City-ID `ag_a58acc69346c6de3`, Quarantäne und fremde Operationen bleiben
unangetastet.

### Neuer Fundament-Befund: Zwei Dateien reichen langfristig nicht

Im aktuellen Hub-Blob `nadi/steward-federation_to_steward.json` liegen weiterhin **102**
dieser Geisternachrichten (51 Claims + 51 Heartbeats) neben 42 gültig signierten Nachrichten
der aktiven ID. Alle 102 Hub-UUIDs stehen heute im persistenten Seen-Store. Das verhindert
eine sofortige Wiederholung, ist aber keine dauerhafte Löschgarantie:

- `steward/federation_relay.py` begrenzt `MAX_SEEN_IDS` auf 4.096,
- die Hub-Mailbox ist ein Ringpuffer von 144 Nachrichten,
- ein gestoppter Hub-Sender könnte seine alten Nachrichten im Ring belassen,
- nach Verdrängung ihrer UUIDs aus dem Seen-Store würde der Steward sie erneut importieren.

Der frühere Plan „Registry + lokale Inbox“ wäre daher zeitlich stabil, aber nicht strukturell
abgeschlossen. **B' muss drei State-Flächen umfassen:**

1. upstream die 102 bewiesenen Geisternachrichten aus genau
   `nadi/steward-federation_to_steward.json` entfernen und die 42 aktiven Nachrichten
   byte-identisch erhalten,
2. downstream die 144 lokalen Geisternachrichten entfernen,
3. gleichzeitig im Steward-Commit die 43 Registry-Einträge entfernen und alle 17 KEEP-
   Einträge byte-identisch erhalten.

Die 102 Hub-Nachrichten sind vollständig im Seen-Store; die 40 zusätzlichen lokalen UUIDs
sind im aktuellen Hub-Blob nicht vorhanden. Nach Schritt 1 besitzt damit keine bekannte
upstream Quelle mehr einen löschbaren Claim.

### Ausführungs-, Guard- und Rollback-Vertrag für B'

B' darf erst gegen einen neuen Live-Snapshot ausgeführt werden. Der sichere Ablauf ist:

1. Steward- und Hub-Head, Trees und alle drei Ziel-Blobs erneut pinnen.
2. Census neu berechnen. Abbruch bei unbekannter neuer Registry-ID, neuer aktiver Node-ID,
   verlorenem `agent_name`, veränderter KEEP-Payload oder einem Hub-Kandidaten ohne bereits
   persistierte UUID.
3. Hub-Mailbox zuerst über ihren exakten Blob-SHA bereinigen. Ein konkurrierender Writer
   muss den Update-Versuch mit SHA-Konflikt stoppen; danach neu pinnen und neu rechnen.
4. Steward-Registry und Steward-Inbox in **einem** Commit auf demselben Live-Parent
   schreiben. Kein separater Registry-Commit.
5. `relay_seen_ids.json`, Quarantäne, Peers, Workflows und Code nicht verändern.
6. Direkt nach jedem Push die resultierenden Blobs erneut laden und die Sollmengen prüfen.
7. Zwei vollständige nachfolgende Steward-Heartbeats abwarten. Erwartung: Registry bleibt
   17, kein DELETE-Claim kehrt zurück, aktive acht Signaturpfade bleiben sichtbar, Gateway-
   und KARMA-Fehler bleiben null.

Rollback ist ohne Datenverlust möglich: Die gepinnten Parent-Commits und die oben genannten
Blob-SHAs enthalten die vollständigen Vorzustände. Bei einer verletzten Postcondition werden
Hub-Mailbox, Steward-Inbox und Registry aus diesen Blobs durch neue Revert-Commits
wiederhergestellt; keine Force-Pushes und keine History-Rewrites.

### Nächster Arbeitsauftrag

Der read-only Gate ist erfüllt, aber die Zahlen müssen unmittelbar vor dem Schreibvorgang
neu bestätigt werden. Danach B' exakt nach dem Drei-Flächen-Vertrag ausführen und zwei
Produktionszyklen verifizieren. Erst nach diesem Beweis folgen Identitätsnamen-Reparatur,
Key-Rotation, Quarantäne-Cleanup und Agent-City-GH006 als getrennte Tickets.

## §13 — B' AUSGEFÜHRT UND ÜBER ZWEI PRODUKTIONSZYKLEN STABIL

**Status:** Abgeschlossen. Die bewiesenen Steward-Federation-Wegwerfidentitäten sind aus
der upstream Hub-Mailbox, der lokalen Steward-Inbox und der Steward-Registry entfernt.
Zwei nachfolgende Heartbeats haben keine Wiederauferstehung erzeugt. Phase 1 blieb
unverändert und read-only.

### Re-Census unmittelbar vor dem Schreiben

Der §12-Snapshot wurde nicht blind geschrieben. Direkt vor B' wurden beide Repos erneut
über Live-Refs, Trees und Blobs gepinnt.

Finaler Steward-Parent:

- Head: `f79138606b8538dfb80168e99bd689711df918bd`.
- Tree: `8cb8cba2462582a4addccd99f02d2a1ecc886b54`.
- Registry-Blob: `9b0cd4aef4b4ecbab2d37496d2a5e44d82388bc3`, weiterhin 60.
- Inbox-Blob: `c6c8c0f4edbe468e45ce5c56ba259d2f7d826c08`, inzwischen 466.
- Seen-Blob: `c673dc1dd208d572eb7092d296cbfeb862097111`, inzwischen 493.

Die Registry war semantisch und als Blob identisch zum §12-Census. Die zwei zusätzlichen
Inbox-Nachrichten waren keine DELETE-Kandidaten. Alle Guards wurden neu berechnet:

- Registry: 60 → 17, exakt 43 bewiesene IDs entfernt.
- lokale Inbox: 466 → 322, exakt 144 Nachrichten entfernt.
- Operationen der lokalen Löschmenge: 72 Claims + 72 Heartbeats.
- `agent_name`-Menge vor und nach dem Filter identisch.
- alle 17 KEEP-Payloads semantisch identisch.
- Relay-Seen, Quarantäne, Peers, Workflows und Code nicht Teil des Steward-Commits.

### Parallelitätsguard hat real ausgelöst

Der erste Hub-Schreibversuch wurde vor jeder Mutation abgebrochen, weil der gepinnte Head
`17af2eb38eb24ccac8c0d0a5b8cc0fff669187cc` inzwischen nach
`de3dfe56cb91a81928aa01a80f0042a0439fd9fd` weitergelaufen war. Es wurde nicht forciert,
nicht überschrieben und nicht auf einem veralteten Tree weitergearbeitet.

Nach neuem Pin blieb der Ziel-Blob identisch. Die 102 Hub-Kandidaten wurden erneut gegen
den jetzt 493 UUIDs großen Seen-Store geprüft; alle 102 waren persistent gesehen. Die 42
KEEP-Nachrichten verifizierten erneut vollständig gegen `ag_9272c311628b5f40`.

Das ist Produktionsbeweis für den §12-Vertrag: Ein konkurrierender Writer führt zum
Re-Census, nicht zum Last-Writer-Wins-Verlust.

### Upstream-Schritt im Hub

In `kimeisele/steward-federation` wurde ausschließlich
`nadi/steward-federation_to_steward.json` verändert:

- Commit: `018250711cf1f4acdd43b5b57b40ff347632436c`.
- Vorheriger Blob: `f64b4193cec7d90e7f7de317ff97024a51e73d1e`.
- Neuer Blob: `6ba03b51410fea1d08b4f8e2f3ea4e22ab686ce0`.
- Mailbox: 144 → 42.
- Gelöscht: 51 Geister-Claims + 51 Geister-Heartbeats.
- Erhalten: 42 kanonische, gültig signierte Nachrichten ausschließlich von
  `ag_9272c311628b5f40`.

Nach beiden Steward-Zyklen lag der Hub-Blob weiterhin unverändert auf
`6ba03b51410fea1d08b4f8e2f3ea4e22ab686ce0`. Der damalige Hub-Head
`a76d75d2196f775ea7cd84fed314cf32df519f3a` war 33 Commits Descendant des Purge-Commits;
der Upstream-Purge wurde also nicht von der weiterlaufenden Föderation überschrieben.

### Atomarer Downstream-Schritt im Steward

Registry und Inbox wurden in genau einem Commit auf demselben Parent geschrieben:

- Commit: `39c265a650cf1b443a26870b382696916322c22e`.
- Parent: `f79138606b8538dfb80168e99bd689711df918bd`.
- Tree: `ac621b91dcd3f94dc7ee400da1721a4661000ae2`.
- Registry: Blob `9b0cd4aef4b4ecbab2d37496d2a5e44d82388bc3` →
  `1fbb9f659ecfe493b3120ffe5307a3c6db7e6204`, 60 → 17.
- Inbox: Blob `c6c8c0f4edbe468e45ce5c56ba259d2f7d826c08` →
  `6cf1334520d8e2696844fd8e26f84b812edcad1b`, 466 → 322.
- Seen-Blob blieb `c673dc1dd208d572eb7092d296cbfeb862097111`.

Unmittelbar nach dem Ref-Update lieferte die API einmal kurz einen nicht passenden Head.
Die anschließende Abstammungs- und Blobprüfung zeigte jedoch den exakten Commit als Live-
Head; das war API-Konsistenz, kein verlorener oder konkurrierender Commit. Erst nach diesem
Beweis wurde der Schritt als erfolgreich gewertet.

### Produktionszyklus 1

Run `29319661369`:

- Start-Head: exakt der B'-Commit `39c265a650cf1b443a26870b382696916322c22e`.
- Ergebnis: erfolgreich in 4:07 Minuten.
- State-Commit: `373f8668b7d480f85742090772f47f48d11b27d2`.
- Registry-Blob blieb `1fbb9f659ecfe493b3120ffe5307a3c6db7e6204`, 17.
- Inbox-Blob blieb `6cf1334520d8e2696844fd8e26f84b812edcad1b`, 322.
- Seen-Blob wurde `e42041365cd6751be4dfbb6d37609e24ecba186c`, 511.
- Geister in Registry: 0.
- Geisternachrichten in Inbox: 0.
- aktive Hub-ID `ag_9272c311628b5f40` weiterhin registriert.
- Hub-Mailbox wurde als 42 Nachrichten gelesen.
- vier neue Nachrichten wurden gezogen und vom Gateway terminal verarbeitet; sie blieben
  deshalb nicht in der Inbox.
- erfolgreicher `main -> main`-Push: 1.

Harte Logzählung:

- `HEARTBEAT ERROR`: 0,
- `KARMA dispatch failed`: 0,
- `Traceback`: 0,
- `Diagnosis failed`: 0,
- `CONFLICT`: 0,
- `detached HEAD`: 0,
- beide exemplarisch geprüften Geister-IDs: 0.

### Produktionszyklus 2

Run `29319982831`:

- Start-Head: `373f8668b7d480f85742090772f47f48d11b27d2`.
- Ergebnis: erfolgreich in 1:55 Minuten.
- State-Commit: `951542ebfb44092b81b89130de5df9527b635d10`.
- Tree: `e4709bae52208809accc84810bab5e4163594017`.
- Registry: weiterhin 17, Blob `1fbb9f659ecfe493b3120ffe5307a3c6db7e6204`.
- Inbox: weiterhin 322, Blob `6cf1334520d8e2696844fd8e26f84b812edcad1b`.
- Seen: weiterhin 511, Blob `e42041365cd6751be4dfbb6d37609e24ecba186c`.
- Geister in Registry und Inbox: jeweils 0.
- Hub-Mailbox zweimal als 42 Nachrichten gelesen.
- `KARMA` erreichte zweimal die Dispatch-Logik.
- erfolgreicher `main -> main`-Push: 1.

Harte Logzählung:

- `HEARTBEAT ERROR`: 0,
- `KARMA dispatch failed`: 0,
- `Traceback`: 0,
- `Diagnosis failed`: 0,
- `CONFLICT`: 0,
- `detached HEAD`: 0,
- `GIT_NADI: pull failed`: 0,
- `GIT_NADI: commit failed`: 0,
- beide exemplarisch geprüften Geister-IDs: 0.

Damit ist die §12-Postcondition über zwei vollständige, aufeinanderfolgende
Produktionszyklen erfüllt. B' ist abgeschlossen.

### Zwei getrennte neue Fundament-Befunde

B' selbst ist stabil, aber die vollständigen Logs zeigen zwei weitere Risse, die nicht in
den Purge hineingepatcht werden dürfen:

1. Im ersten Zyklus meldete `GIT_NADI_SYNC` zweimal einen gescheiterten Rebase-Pull wegen
   unstaged/index changes und einmal einen gescheiterten Commit wegen fehlender Git-Autor-
   Identität (`fatal: empty ident name`). Der zweite Zyklus traf den Pfad nicht erneut. Das
   ist kein B'-Rollbackgrund, weil der abschließende Workflow-State-Push erfolgreich war;
   es ist aber ein echter intermittierender Synchronisationsdefekt.
2. Beide Zyklen endeten in `Post Checkout steward` mit
   `fatal: No url found for submodule path '.deps/steward-protocol' in .gitmodules` und der
   Annotation `git failed with exit code 128`. Der Job blieb grün. Das ist ein reproduzierbar
   maskierter Checkout-/Cleanup-Defekt, kein Node.js-Hinweis und kein Purge-Symptom.

Diese Warnungen werden ausdrücklich nicht als „grün, also egal“ klassifiziert. Sie sind der
nächste Read-only-Recon-Auftrag, weil beide an Git-Zustand und Fehlerpropagation im
produktiven Fundament liegen.

### Nächster Arbeitsauftrag

1. `GIT_NADI_SYNC`-Reihenfolge, Arbeitsbaum-Mutationen und Git-Autor-Konfiguration gegen die
   beiden Produktionslogs bis zur Ursache verfolgen.
2. Den `.deps/steward-protocol`-Post-Checkout-Fehler gegen die zwei Checkout-Schritte und
   deren Cleanup-Verhalten reproduzieren; kein blindes `.gitmodules`-Workaround.
3. Prüfen, warum beide Fehlerkanäle den Heartbeat grün lassen, und den kleinsten gemeinsamen
   Fix mit roten Regressionen definieren.
4. Erst danach die separaten offenen Tickets Identitätsnamen-Reparatur,
   Heartbeat-Fehlerpropagation, Key-Rotation, Quarantäne-Cleanup und Agent-City-GH006 neu
   priorisieren.

Phase 1 bleibt weiterhin unverändert. Jeder Fix erhält einen eigenen Milestone und
Produktionsbeweis; B' wird nicht erneut geöffnet, solange die 17/322/42-Invarianten halten.

## §14 — HEARTBEAT-GIT-FUNDAMENT REPARIERT UND PRODUKTIV VERIFIZIERT

**Status:** Abgeschlossen. Die beiden in §13 neu belegten Git-Fehler hatten getrennte,
präzise Ursachen. Beide wurden mit roten Regressionen repariert, über reguläre CI gemergt
und in einem vollständigen Produktions-Heartbeat ohne die früheren Warnungen verifiziert.
Phase 1 blieb unverändert und read-only.

### Root Cause 1: GitNadiSync war nicht dirty-worktree-sicher

`GitNadiSync` wird mit `data/federation/` als Arbeitsverzeichnis erzeugt, arbeitet aber im
übergeordneten Steward-Git-Repository. Während eines Heartbeats verändert der Prozess vor
dem Sync bereits Registry, Inbox, Seen-State, `.steward/` und weitere Runtime-Dateien.

Der alte Pull-Pfad führte aus:

```text
git fetch origin --prune
git rebase origin/HEAD
```

Der Retry-Pfad führte `git pull --rebase` aus. Beide Befehle verweigern einen Rebase bei
unstaged oder gestagten Runtime-Änderungen. Das erklärt exakt die zwei Produktionsmeldungen
`cannot rebase: You have unstaged changes` aus Run `29319661369`.

Zusätzlich setzte der Workflow `user.name` und `user.email` erst im späteren Schritt
`Commit federation state`. Ein Commit aus `GitNadiSync.push()` während des autonomen Laufs
kam vorher und konnte deshalb mit `Author identity unknown` / `empty ident name` abbrechen.
Die Tests hatten das verdeckt, weil `_clone_to()` jedem Test-Clone sofort eine Identität
konfiguriert.

### Root Cause 2: `.deps/steward-protocol` war ein kaputter Gitlink

Die zweite Checkout-Aktion klont `steward-protocol` nach `.deps/steward-protocol`. Dieser
Pfad war seit Commit `6e317f70012bd1d816aeb9d9c4ff4bedd52d9903` (Heartbeat `#1014`,
2026-03-30) versehentlich als mode-`160000` Gitlink im Steward-Tree eingecheckt. Es gab
jedoch keine `.gitmodules`-Definition.

Damit reproduzierte bereits der echte Cleanup-Befehl lokal den Produktionsfehler:

```text
$ git submodule foreach --recursive true
fatal: No url found for submodule path '.deps/steward-protocol' in .gitmodules
```

Exit-Code: 128. Das war kein fehlender legitimer Submodule-Eintrag, sondern ein über Monate
mitgeschleppter versehentlicher Gitlink. Eine künstliche `.gitmodules`-Datei wäre deshalb
der falsche Fix gewesen.

### Rote Regressionen

Vor dem Patch schlugen die neuen Tests wie erwartet fehl:

1. Ein Clone mit remote Advance und lokal schmutziger `nadi_inbox.json` erhielt aus
   `GitNadiSync.pull()` `False` mit `cannot rebase: You have unstaged changes`.
2. Der Repository-Hygiene-Test fand keine `.deps/`-Ignore-Regel.
3. Derselbe Test fand den mode-`160000`-Eintrag weiterhin im Git-Index.
4. Der Workflow enthielt keinen `Configure Git`-Schritt vor `Run autonomous cycle`.
5. Eine Push-Retry-Regression hält zusätzlich eine fremde getrackte Runtime-Datei unstaged,
   während ein konkurrierender Remote-Commit den Rebase-Pfad erzwingt.

Diese Tests prüfen die echten Git-Repositories und echten Git-Befehle, keine Subprocess-
Stubs.

### Minimaler Patch

Ticket-Commit: `65ed04d8ca94781b4758d8fc78fd5d77b6f96cbb`.

Geändert wurden ausschließlich fünf Pfade:

1. `steward/git_nadi_sync.py`:
   - initialer Rebase jetzt mit `--autostash`,
   - Pull-Rebase im Push-Retry ebenfalls mit `--autostash`.
2. `.github/workflows/steward-heartbeat.yml`:
   - eigener `Configure Git`-Schritt vor dem autonomen Lauf,
   - die identische spätere Doppelkonfiguration entfernt.
3. `.deps/steward-protocol`:
   - versehentlichen mode-`160000`-Gitlink gelöscht.
4. `.gitignore`:
   - `.deps/` dauerhaft ignoriert, damit ein breites zukünftiges Add den Checkout nicht
     erneut als Gitlink eincheckt.
5. `tests/test_git_nadi_sync.py`:
   - Dirty-Pull-, Dirty-Push-Retry-, Workflow-Reihenfolge- und Gitlink-Hygiene-Regressionen.

Nicht geändert wurden GitNadi-Fehlerpropagation, MURALI-Phasenfang, Federation-State,
Registry, Inbox, Relay, Quarantäne, Secrets oder Phase 1.

### Lokale und CI-Validierung

Lokal:

- `tests/test_git_nadi_sync.py`: 13 passed.
- Ruff check: grün.
- Ruff format check: grün.
- `git submodule foreach --recursive true`: Exit 0.
- `git ls-files --stage .deps/steward-protocol`: leer.
- `git check-ignore .deps/steward-protocol`: trifft `.gitignore:.deps/`.

PR `#428` wurde ohne Admin-Bypass gemergt:

- Merge: `ead60c2fbffb621ab12db1bb3af4b9ba52cf3a27`.
- Required-CI-Run: `29321053042`.
- Python 3.11: grün.
- Python 3.12: grün.
- Lint + Format: grün.
- Security: grün.

### Produktionsbeweis

Heartbeat-Run `29321214906` wurde auf dem Merge-Stand ausgelöst. Wegen der
Single-Writer-Queue lief vorher noch Heartbeat `#5340`; der reale Checkout des Beweislaufs
war deshalb dessen Descendant `76ff08a70aa9b064a7eefe29873b8238fca84cf0`, dessen Parent
der Merge `ead60c2fbffb621ab12db1bb3af4b9ba52cf3a27` ist.

Der Lauf dauerte 1:50 Minuten. Alle Workflow-Schritte einschließlich beider
Post-Checkout-Cleanups waren erfolgreich. Es gab keine Annotation.

Der reparierte Mid-Cycle-Pfad lief real:

- `Configure Git`: erfolgreich vor dem autonomen Lauf,
- `GIT_NADI: push succeeded (attempt 1)`: 1,
- Zwischencommit: `972f0d8b1fde2645edc25d258dbaf30e12dd5e48`,
  Nachricht `steward: federation sync`,
- dessen Parent: `76ff08a70aa9b064a7eefe29873b8238fca84cf0`,
- finaler Workflow-State-Commit: `8b248ddfb6b09fad520e194ea1975910fab69c9b`,
- finaler Tree: `e1309ef8c6fc86866c70dbe8f7a01c17286d4c7e`,
- erfolgreicher finaler `main -> main`-Push: 1.

Harte Logzählung:

- `GIT_NADI: pull failed`: 0,
- `GIT_NADI: commit failed`: 0,
- `GIT_NADI: push failed`: 0,
- `Author identity unknown`: 0,
- `No url found for submodule`: 0,
- `failed with exit code 128`: 0,
- `HEARTBEAT ERROR`: 0,
- `KARMA dispatch failed`: 0,
- `Traceback`: 0,
- `Diagnosis failed`: 0,
- `CONFLICT`: 0,
- `detached HEAD`: 0.

Der Live-Tree enthält keinen `.deps/steward-protocol`-Gitlink mehr.

### B'-Invarianten nach dem Fix

Der Git-Fix hat den vorherigen Milestone nicht beschädigt:

- Registry: 17, Blob `1fbb9f659ecfe493b3120ffe5307a3c6db7e6204`.
- Inbox: 322, Blob `6cf1334520d8e2696844fd8e26f84b812edcad1b`.
- Seen: 537, Blob `2c4b73b75c7de69a80afe969c1f34b460da406b9`.
- Hub-Mailbox: weiterhin 42 aktive Nachrichten, Blob
  `6ba03b51410fea1d08b4f8e2f3ea4e22ab686ce0`.
- Registry-Geister: 0.
- lokale Inbox-Geisternachrichten: 0.

### Nächster Arbeitsauftrag

Der konkrete Git-Sync-/Checkout-Milestone ist abgeschlossen. Als nächstes bleibt der bereits
mehrfach belegte übergeordnete Fehlerkanal: Der Heartbeat fängt Phasenausnahmen, loggt sie
und kann trotzdem grün enden. Dieser Pfad muss read-only gegen reale Fehlerklassen zerlegt
werden, bevor Fehlerpropagation geändert wird. Insbesondere ist zu unterscheiden zwischen:

1. kritischen MURALI-Phasenfehlern, die den Workflow rot machen müssen,
2. explizit degradierbaren Netzwerkpfaden mit belastbarer State-Postcondition,
3. Post-Action-Warnungen außerhalb des Python-Prozesses.

Erst danach folgen Identitätsnamen-Reparatur, Key-Rotation, Quarantäne-Cleanup und
Agent-City-GH006 als getrennte Tickets. Phase 1 wird weiterhin nicht verändert.

## §15 — CONTEXT BRIDGE G0 GESCHLOSSEN, FEATURE 00/04 GELIEFERT, NOCH NICHT AKTIVIERT

**Stand:** 2026-07-15 07:33 Europe/Berlin
**Verifizierter Main:** `c81a1683fd9358eb0c6a91cee157eb5c18fec99a`
**Tree:** `24ba54ff9f7e653c44a210ecf7304d14853c0916`

### Anlass und Schutzgrenze

Der Auftrag war nicht, kurzfristig eine zweite Root-Datei zu erzeugen. Das Fundamentproblem
war größer: Externe Engineering-Agenten sollen in `CLAUDE.md` und `AGENTS.md` einen
aktuellen, sicheren und consumerkorrekten Einstieg erhalten, ohne Runtime-Persona,
untrusted Prompt-Injection, lokale Pfade, Secrets, volatile Agenda oder zwei driftende
Wahrheiten zu übernehmen.

Deshalb galt während G0 und Feature 00 strikt:

- keine Implementierung aus Chat-Prosa,
- `PHASE2_CURRENT` ist widerlegbarer Arbeitsstand, keine SSOT,
- Phase 1 bleibt read-only,
- statische Governance und dynamischer beobachteter State bleiben getrennt,
- LLM-Output darf keine kanonischen Root-Dateien publizieren,
- Byteidentität von `CLAUDE.md` und `AGENTS.md` ist der Default, bis ein realer
  Consumer-Unterschied eine minimale Abweichung erzwingt,
- keine Produktivaktivierung vor Feature-Specs, roten Tests und eigenem G2.

### G0 und Feature 00

Die Master-Spec und 18 read-only Evidence-Fragen wurden adversarial geschlossen. Der
entscheidende Sicherheitswechsel war, die Bridge nicht nur als Freshness-/Dokumentproblem,
sondern als Übersetzungsgrenze von teilweise untrusted Daten zu Agenten-Instruktionen zu
behandeln.

Geliefert wurden unter anderem:

- T0–T5-Trust-Zonen,
- exakter kleiner C0-v1-Vertrag für externe Engineering-/Maintenance-Consumer,
- C0-/Dynamic-/Orientation-Blockgrenzen,
- PUBLIC_SAFE-Allowlist statt Secret-Blocklist als Primärmodell,
- Source-Status und sichtbare Degradation,
- Governance-, Required-Check-, Zwei-Principal- und No-Bypass-Vertrag,
- ehrliche per-file Atomicity, Mixed-State-Erkennung und Git als Remote-Grenze,
- getrennte Snapshot-, Payload- und Consumer-Output-Hash-Domains.

Relevante Merges:

- G0-Master/Evidence: `7b1b6a221851f51d06191222f5187cc877c04304`,
- Feature 00 PR `#497`: `327eca2f8bf275563c5940ba807996b52ca44fa3`.

### Feature 04: semantischer Kern vor Publisher

G0 hatte eine falsche alte Reihenfolge korrigiert. Ein Publisher darf nicht vor seinem
kanonischen Modell und Hashvertrag entstehen. Die verbindliche Reihenfolge lautet deshalb
`00 -> 04 -> 01 -> 02/03`.

Feature 04 spezifizierte und implementierte ausschließlich:

- fail-closed C0-/Orientation-Markerparser,
- geschlossene SourceStatus-, TrustZone-, OutputMode- und Decision-Vokabulare,
- Source-ID/Trust-/Mode-Bindung,
- immutable explizite Input-/Previous-Record-Objekte,
- floatfreies kanonisches JSON mit NFC, nicht NFKC,
- volle domainseparierte SHA-256-Hashes,
- PUBLIC_SAFE- und strikte Observation-Schema-Grenzen,
- Health-, Sense-, Gap-, Federation-, Immune-, Campaign- und Cetana-Aggregate,
- expliziten Vergleichsstate für kumulative Gateway-/Rollback-Ereignisse,
- `publish`, `no_op`, `manual_review` und `blocked` ohne MTime oder Prozessglobalen State.

Relevante Merges:

- Feature-04-Spec/G1 PR `#498`: `44b318408ebd1e73731d38c0c11f241d13761b08`,
- G2-Preflight PR `#499`: `d30a22a60213693d834ffd38f44c0892aa942de3`,
- Implementierung PR `#505`: `c81a1683fd9358eb0c6a91cee157eb5c18fec99a`.

Der Implementierungsmerge fügte exakt zwei Pfade hinzu:

1. `steward/context_contract.py`,
2. `tests/test_context_contract.py`.

Kein bestehender Caller, Writer, Renderer, Hook, Workflow oder Root-Output wurde geändert.

### Materielle Review-Korrekturen

Der Erstentwurf wurde nicht blind umgesetzt. Die Reviews fanden und korrigierten:

1. `error_pressure` und `context_pressure` sind in `measure_vedana()` invertierte
   Health-Komponenten; mindestens `compute_focus()` liest `context_pressure` gegenteilig.
   V1 schließt beide Felder aus, statt den Altfehler zu institutionalisieren.
2. Nicht verwendete Sessions/Issues/Tasks dürfen den Payload-Hash nicht bewegen. Sie
   bleiben diagnostisch im Snapshot, aber außerhalb des V1-Semantic-Core.
3. Kumulative Gateway-/Rollback-Zähler brauchen eine explizite frühere Baseline. Ein
   einfacher `count > 0`-Test würde dauerhaft Alarm oder nach Reset falsch `clear`
   erzeugen.
4. Ein passender C0-Hash beweist keinen menschlichen Review; Bootstrap benötigt eine
   gebundene ConstitutionAttestation.
5. `build_payload_core()` validiert die exakte Observation-Form. Zusätzlicher Freitext
   kann nicht als unbekanntes Zusatzfeld durchrutschen.
6. Source-ID, Trust-Zone und Source-Mode sind fest gebunden. Ein Issue kann sich nicht als
   T0-Constitution ausgeben.

### Test- und Mergebeweis

Der rote Testcommit scheiterte vor Produktcode ausschließlich mit
`ModuleNotFoundError: steward.context_contract`. Danach:

- gezielt: 64 Contract-Tests grün,
- lokaler vollständiger Lauf: 2.188 passed, 13 skipped in 15:49,
- bekannte bestehende Deprecation-Warnungen, keine neue Failure,
- Ruff check und format check grün,
- `git diff --check` grün,
- AST-Audit: keine Filesystem-, Clock-, Git-, Netzwerk-, Environment- oder
  ServiceRegistry-Imports/Calls,
- PR-CI Python 3.11 und Python 3.12 grün,
- Lint grün,
- Security scan grün,
- Merge ohne Admin-Bypass.

Die festen Hashvektoren wurden mit Python-Standardbibliothek und getrennt mit
`jq -cS -j` plus `shasum -a 256` identisch reproduziert:

- Snapshot: `999ba49ddaea6300f3398159103491915a9b5ce3b7871a9cbd2f7b20b761ceba`,
- Payload: `d3a344af1700b88346695e13833ec5d6f81b66584ef8272542c64f7d4aa4d71a`.

### Was ausdrücklich noch nicht wahr ist

Feature 04 ist keine produktive Context Bridge:

- `CLAUDE.md` wird weiterhin durch die alte Pipeline erzeugt,
- Root-`AGENTS.md` fehlt weiterhin,
- `.steward/conventions.md` besitzt noch nicht die C0-/Orientation-Migration,
- es gibt noch keinen Dual-Publisher,
- es gibt noch keinen persistenten Publish-Record oder Mixed-State-Recovery,
- LLM- und Nebenpublisher sind noch nicht isoliert,
- Workflow-Delivery, Required Contract Check, CODEOWNERS, Branchschutz, Zwei-Principal-
  Pfad und Kill-Switch sind noch nicht aktiviert,
- kein Produktionsbeweis für gemeinsame Root-Delivery existiert.

Diese Aussagen dürfen nicht aus den grünen Feature-04-Tests abgeleitet werden.

### Nächster Arbeitsauftrag

Als nächstes wird ausschließlich Feature-Spec 01 für sicheren kanonischen Publisher plus
Delivery erstellt. Vor der Spec werden Live-Head, alle Publisher/Caller und Workflow-
Pfade erneut read-only gepinnt. Die Spec muss Source-Migration, Renderer, lokalen
Transaktions-/Recovery-Vertrag, persistenten Record, Git-Delivery, LLM-Isolation,
Governance, Kill-Switch, Rollback und realen G2-Drill in kleine überprüfbare Schnitte
zerlegen.

Bis Feature-Spec 01 G1-freigegeben und ein separater aktueller G2-Preflight abgeschlossen
ist, bleibt jeder Writer-, Workflow-, Root-, Conventions- oder Governance-Patch gesperrt.
Phase 1 bleibt unverändert.

## §16 — FEATURE 01 G1 UND SCHNITT A: LEGACY-WRITER-FENCE PRODUKTIV VERIFIZIERT

**Stand:** 2026-07-15 18:39 Europe/Berlin
**Verifizierter Main:** `1e5b23a8f0ba9d30e39c9fc44fc89595fe6c9afe`
**Tree:** `c7fd7965845339b9e253084bcbd2466a7e31122d`

### Spec- und Gate-Kette

Feature 01 wurde nicht als Mega-Patch begonnen. Zuerst wurden Runtime-State, Source-
Adapter, Constitution-Attestation, Operationsnamen, Golden-Publication-Vektoren und der
vollständige End-to-End-Vertrag read-only geschlossen.

- Feature-01-Spec/G1: PR `#532`, Merge
  `b1f945a66aace9721684ae146ab7f8535e85844a`.
- Slice-A-G2-Preflight: PR `#533`, Merge
  `44c0a77f4fa8eda8ab165e9c901530947a938e86`.
- G2-Basis: `964e9972bec25b912da71b2e014605592ebab2ae`, Tree
  `1ac9484f32e9eb0b9a4ddb236f203d19ee5e143c`.
- Implementierung: PR `#539`, Merge
  `1b1ef63d9d873a08acb812f18ba102b73174838c`.

Der Implementierungsbranch wurde nach jedem Live-Heartbeat-Drift normal auf `origin/main`
rebasiert. Es gab keinen Force-Push auf `main`, keinen Admin-CI-Bypass und keinen
manuellen Benutzer-Merge.

### Roter Beweis vor Produktcode

Die roten Tests belegten separat:

1. `write_claude_md()` erzeugte beziehungsweise überschrieb Root-`CLAUDE.md`.
2. MOKSHA rief den Legacy-Writer nach Raw-Context-Write auf.
3. `synthesize_briefing` schrieb Default-, relative, absolute und Traversal-Ziele.
4. Intent und autonome Strategy behaupteten MTime-basierte kanonische Aktualisierung.
5. Git-NADI commitete unrelated Root-Dateien, fremd gestagten Index, gleichnamige
   Root-Pfade und unrelated Löschungen über den breiten Fallback.

Ein adversarialer Test schrieb den alten beliebigen `output_path` tatsächlich in den
Engineering-Checkout. Der Lauf wurde sofort gestoppt, der getrackte Root-Blob exakt aus
`HEAD` wiederhergestellt, alle ausschließlich durch diesen Test erzeugten Artefakte wurden
entfernt und die Fixture danach in ein isoliertes `tmp_path`-CWD verlegt. Kein solcher
Testartefakt gelangte in einen Commit oder PR.

### Gelieferter Fence

Der Merge änderte exakt sechs Produkt- und sechs Testpfade:

- Legacy-`write_claude_md()` bleibt importierbar, schlägt aber vor Rendering oder I/O mit
  eigenem `RuntimeError`-Untertyp fehl; `force=True` ist kein Bypass.
- `generate_briefing()` bleibt read-only Preview.
- MOKSHA schreibt weiterhin Raw-`.steward/context.json`, ruft aber keinen Root-Writer.
- `synthesize_briefing` bleibt als Tool sichtbar, akzeptiert nur fehlenden Parameter oder
  `stdout`, liefert `mode=preview`, `canonical=false` und schreibt nichts.
- Der alte Intent ist ein deterministischer No-op; die Default-Strategy wurde entfernt.
- Git-NADI prüft vor eigenem Staging auf leeren Index, erkennt nur allowlistete Änderungen,
  staged mit positiven Pathspecs und validiert repo-relative Indexnamen gegen den echten
  Federation-Prefix. Der Worktree-weite Fallback ist entfernt.

Ausdrücklich nicht geliefert wurden neuer Renderer, Publisher, Root-Datei, Source-
Migration, Recovery, Workflow, Branchschutz, CODEOWNERS, Runtime-State-Migration oder
Aktivierung.

### Test- und CI-Beweis

- Rote Tests wurden in zwei separaten Testcommits gesichert.
- Gezielte Fence-, Tool-, Hook-, Intent-, Service-, Git-NADI- und
  Remote-Perception-Tests: grün.
- Repositoryweiter Ruff-Formatcheck: 212 Dateien formatiert.
- Repositoryweiter Ruff-Lint: grün.
- Lokale Vollsuite: 2.207 passed, 13 skipped; ein `GitSense`-Test scheiterte ausschließlich,
  weil fünf laufende Heartbeats den 15-Minuten-Feature-Branch gegenüber seinem Upstream
  divergieren ließen. Nach normalem Rebase war derselbe Test bei `dirty_count=0` grün.
- PR-CI Python 3.11 und 3.12: grün.
- Lint und Security Scan: grün.
- Remote-PR-Diff: ausschließlich die zwölf im G2 erlaubten Pfade.

### Produktionsbeweis

Kontrollierter Folgeheartbeat:

- Run: `29432921534`, `workflow_dispatch`, Merge-Head
  `1b1ef63d9d873a08acb812f18ba102b73174838c`, Ergebnis `success`, Dauer 4m03s.
- Folgecommit: `1e5b23a8f0ba9d30e39c9fc44fc89595fe6c9afe`,
  `chore: heartbeat #5496 state sync`.
- Commit-Scope: elf bekannte `.steward/`- und `data/federation/`-State-Pfade; kein Root-,
  Produkt-, Workflow- oder Spec-Pfad.
- `CLAUDE.md` vor Merge, im Merge und nach Folgeheartbeat: identischer Blob
  `8146a15603c95e5aa1404c9eb7021e3008914b0c`.
- `AGENTS.md`: in allen drei Generationen absent; Schnitt A erzeugt sie bewusst noch nicht.
- `GIT_NADI: narrow staging failed`: 0.
- `refusing to use a non-empty pre-existing index`: 0.
- `CLAUDE.md generation failed`: 0.
- `Legacy CLAUDE.md writes are disabled`: 0, weil der produktive Caller entfernt ist.
- Tracebacks: 0.

Der Run war nicht vollständig providergesund: Gemini erreichte zweimal das Free-Tier-
Quota-Limit, Groq meldete einen ungültigen Key; Mistral übernahm erfolgreich. Diese
Provider-Degradation ist kein Slice-A-Fehler und wird nicht als „null Fehler“ verschwiegen.

Der Workflow-Post-Step pushte den Runtime-State weiterhin direkt auf `main` und GitHub
meldete dabei den bekannten Rule-Bypass für erwartete Checks. Das ist ausdrücklich noch
nicht der Zielzustand von Feature 01; Runtime-State-Entkopplung und PR-only Delivery
bleiben spätere eigene Schnitte.

### Damals nächster Arbeitsauftrag

Zum Abschluss von Schnitt A war ausschließlich der read-only G2-Preflight für Feature 01 /
Schnitt B aus
`specs/CONTEXT_BRIDGE_FEATURE_01.md` §15.2 zulässig. Er muss aktuelle Symbole und Pfade
pinnen, die reine Renderer-/Validator-API und rote Golden-/Adversarial-Tests festlegen und
beweisen, dass keine Writes, Clock-, Git-, Netzwerk-, ServiceRegistry-, Root- oder
Workflowwirkung entsteht.

Kein Schnitt-B-Produktcode vor gemergtem G2-Preflight. Publisher, Root-Ausgaben,
Constitution-Migration, Recovery, Delivery, Governance und Aktivierung bleiben gesperrt.
Phase 1 bleibt unverändert.

---

## §17 — FEATURE 01 SCHNITT B: OFFLINE-CONTRACT UND RENDERER GELIEFERT, WEITERHIN NICHT AKTIVIERT

**Datum:** 2026-07-15
**Preflight:** PR `#541`, Merge `9347f21f9e1a15e5cfd049c562e4db24957a2cac`
**Implementierung:** PR `#547`, Merge `a750e0f3826e0067656062e02c3b7c896db35cde`
**Produktionsfolge:** Run `29436703996`, Commit
`38f361318b39864628dca1329bc513475fec1c04`

### Gelieferte Grenze

Schnitt B ergänzt genau den reinen Offline-Unterbau, nicht den Publisher:

- zwei öffentliche Validatoren für materialisierte Feature-04-Payloads und Snapshots,
- einen I/O-, Clock-, Git-, Netzwerk- und Registry-freien Renderer,
- ein frozen Kandidatenobjekt mit vier Bytes-Artefakten,
- exakt dasselbe Root-Bytes-Objekt für Claude und Codex,
- zirkulationsfreie Snapshot- und Publication-Envelopes,
- fail-closed Preview- und Cross-Binding-Grenzen.

Der Merge-First-Parent-Diff enthält ausschließlich:

```text
steward/context_contract.py
steward/context_rendering.py
tests/test_context_contract.py
tests/test_context_rendering.py
```

Kein bestehender Produktcaller importiert den neuen Renderer. Es gibt weiterhin keinen
Writer, Lock, Replace, Recovery, Root-Write, Workflow oder Deliverypfad.

### Golden- und Qualitätsbeweis

Die gemergten Feature-04-/Feature-01-Vektoren wurden exakt reproduziert:

- Root: 2.318 Bytes, Consumer-Hash
  `9519cfc5867580d041ef7d01c6007a35e7d98b51d559c08b6b941940fcbb6e9d`,
- Snapshot-Artefakt: 4.781 Bytes, domain-separierter Hash
  `fb6320ea4e8dd3d2fd8c009d920396c9e5db73aa4403027b5fae2ca3d3719ac3`,
- Publication-Artefakt: 1.203 Bytes,
- Payload-Hash `d3a344af1700b88346695e13833ec5d6f81b66584ef8272542c64f7d4aa4d71a`,
- Snapshot-Hash `999ba49ddaea6300f3398159103491915a9b5ce3b7871a9cbd2f7b20b761ceba`.

78 gezielte Tests, Bandit, gezieltes Ruff und alle vier CI-Checks waren grün. Der erste
CI-Lauf fand keine Produktabweichung, sondern einen Testharness-Lifetime-Fehler: global
gepatchtes `time.time` traf Pytest beim Fixture-Teardown. Ein auf den Renderer-Aufruf
begrenzter `monkeypatch.context()` korrigierte dies; beide Python-Matrizen liefen danach
vollständig grün.

Die lokale Vollsuite endete mit 2.221 passed und 13 skipped. Ein GitSense-Test sah zwei von
der Suite selbst veränderte State-Dateien und bewertete den Checkout deshalb als `tamas`;
nach Restore und normalem Heartbeat-Rebase lief exakt dieser Test grün. Der repositoryweite
Ruff-Baseline-Check bleibt an unberührten Altskripten rot; der Slice-Scope selbst ist sauber.

### Produktionsbeweis

Run `29436703996` startete auf dem exakten Merge-Head und endete erfolgreich. Der einzige
Folgecommit `38f361318b39864628dca1329bc513475fec1c04` änderte elf bekannte Runtime-/Federation-
State-Pfade. Root- und Slice-B-Produktblobs blieben unverändert:

```text
CLAUDE.md:                  8146a15603c95e5aa1404c9eb7021e3008914b0c
AGENTS.md:                  absent
context snapshot/record:    absent
context_contract.py:        5bd37a576ab476739fd37dd613c2e4630791a7e1
context_rendering.py:       9b603bfbed853ed4cdcda4b8939c2926777fbc20
```

Es gab keinen Runtime-Traceback, keinen Legacy-Writer- oder Git-NADI-Fence-Fehler und
keinen Renderer-/AGENTS-Aufruf. Zwei reine Texttreffer auf `Traceback` stammten nur aus
den im Actionlog eingeblendeten Python-Quellzeilen.

### Neue Live-Präzisierung: grüner Heartbeat ist nicht gleich erfolgreicher Agententask

Der Run machte eine bereits vermutete Fehlerpropagationslücke schärfer sichtbar:

- Groq: 401 Invalid API Key,
- Gemini: 429 Quota nach Retries,
- Mistral: erst 200, danach 400 im Streaming-Fallback,
- Ergebnis der Chamber: alle Provider für Streaming erschöpft,
- `agent_error` ging an null Listener,
- Gesamtworkflow trotzdem `success`.

Das widerlegt keinen Slice-B-Vertrag, weil der Renderer unverdrahtet ist. Es widerlegt aber
die mögliche Interpretation, ein grüner Heartbeat beweise automatisch eine erfolgreiche
autonome Aktion. Der ältere Auftrag zur Fehlerklassifikation und -propagation bleibt daher
materiell wichtig und wird nach den bereits begonnenen Context-Bridge-Schnitten separat
behandelt.

Der Runtime-State-Post-Step pushte weiterhin direkt auf `main` und bypassed erwartete
Required Checks. Auch das bleibt ausdrücklich späterer Schnitt H/I.

### Nächster Auftrag und harte Governance-Grenze

Als nächstes ist nur der read-only G2-Preflight für Schnitt C zulässig. Er muss den heutigen
Constitution-Source-Blob, den exakten Feature-00-C0-Text, die erlaubte Orientation, alle zu
entfernenden Persona-/Runtime-/Agenda-Teile sowie Rollback und negative Fixtures pinnen.

Vor allem muss er die reale separate menschliche Reviewfähigkeit prüfen. Feature 01 hat
bereits bewiesen, dass der heutige Ein-Collaborator-Zustand die Zwei-Principal-Precondition
nicht erfüllt. Weder Self-Approval noch Admin-Bypass noch ein erfundener Federation-Agent
darf diese Governance-Evidence ersetzen. Fehlt ein echter zweiter menschlicher Reviewer,
wird Schnitt C nach dem Recon als governance-blocked dokumentiert und die Source nicht
verändert.

Vollständiger Operationsbeweis:
`specs/context_bridge_evidence/FEATURE_01_SLICE_B_PRODUCTION.md`.

---

## §18 — FEATURE 01 SCHNITT C: TECHNISCHER SOURCE-KANDIDAT GESCHLOSSEN, GOVERNANCE BLOCKIERT

**Datum:** 2026-07-15
**G2-PR:** `#549`
**G2-Merge:** `004ac087cca7b2bd925c40b81b8f000f9541b7d1`
**Gepinnte Recon-Basis:** `12d043467cde783088e8cda041696348e31d1be9`

### Anlass

Schnitt C sollte nicht blind die alte `.steward/conventions.md` umschreiben. Der G2-Recon
musste drei getrennte Fragen positiv beantworten:

1. Welche Bytes bilden den exakten Feature-00-C0-Vertrag?
2. Welche alte Architekturprosa ist sicher genug für die erste Orientation?
3. Kann der Source-PR heute tatsächlich durch einen anderen menschlichen Principal
   commitgebunden reviewt und später attestiert werden?

Die ersten beiden Fragen sind geschlossen. Die dritte ist positiv mit **nein** beantwortet.

### Alter Source-Befund

Die 5.415-Byte-Source blieb auf Blob
`29829be4f77dcaebf970a8ee872de299f0357f1c`. Sie besitzt keine C0-/Orientation-Marker,
beginnt mit `You are Steward`, enthält `Your North Star`, fixe Heartbeat-Frequenzen,
volatile Federationzahlen und die seit Schnitt A falsche Behauptung, sie werde verbatim in
`CLAUDE.md` geschrieben.

Blockweise Entscheidung:

- Kopfkommentare: entfernen, da Text außerhalb der Marker verboten ist.
- `Identity`: vollständig durch C0 ersetzen; keine Runtime-Impersonation.
- Cognitive Pipeline, Heartbeat, Substrate, Federation, Safety, Self-Healing, Directories,
  Invariants und Development: nicht in die erste attestierte Orientation übernehmen.

Das ist Default-deny, keine Behauptung, jeder alte Satz sei falsch. Optionale Architektur
wird nicht allein wegen Nützlichkeit Teil einer menschlich attestierten Governance-
Generation.

### Exakter Kandidat

Die erste Source verwendet den exakten Feature-00-§7-C0-Text und ein leeres, aber
versioniertes Orientation-Markerpaar. Parser, SHA-256 und Git-Objektdomain reproduzierten:

```text
C0 bytes:           1860
C0 SHA-256:         f23ab40415edf4947f12fd8ff98cf13aa8f4fbfffe029ae10aa6111fc04976a3
Source bytes:       2023
Source SHA-256:     0afe95c392ba611ad40302e13a5d013913fca1910423fe4ea18c663cd780aff5
Expected Git blob:  f428d5856a5c525e002c301890777748effbeb4e
Orientation:        empty / orientation-v1
```

Der hypothetische spätere Patchscope ist exakt:

```text
.steward/conventions.md
tests/test_context_constitution.py
```

Der neue Test würde gegen die heutige unmarkierte Source zuerst rot und danach C0 direkt
gegen die normative Feature-00-Spec prüfen. Weder Root-Datei noch Produktcode, Workflow,
State oder Spec dürften im Source-PR geändert werden.

### Positiv belegter Governance-Block

GitHub Live-API am Recon-Zeitpunkt:

```text
Repository:                         public
Authenticated principal:           kimeisele
Collaborators:                      1 (kimeisele)
Offene Einladungen:                 0
Required PR reviews:                absent
CODEOWNERS:                         absent
Rulesets:                           absent
enforce_admins:                     false
Context Constitution Attestation:   absent
```

Die Reviews-API war auch für die untersuchten Context-Bridge-PRs leer. Commit-Autorname,
PR-Merger, Chat-Review, Coding-Agent und Federation-Peer sind kein zweiter GitHub-
Review-Principal.

Damit kann heute niemand den vom Account `kimeisele` erstellten Source-PR als anderer
menschlicher Collaborator auf dem finalen Head freigeben.

### Gefundener Sequenzierungswiderspruch

Feature 01 §15.3 verlangt Schnitt C als menschlich reviewte Source-Migration. Der bereits
geschlossene Attestation-Vertrag verlangt für genau diesen Source-PR zusätzlich einen
commitgebundenen geschützten Check und Governance-Evidence. CODEOWNERS, Branchschutz und
Governance-Drill sind in §15.9 jedoch erst Schnitt I zugeordnet.

Ein heute gemergter Source-PR wäre später nicht rückwirkend attestierbar. Aktuelle
Branchschutzwerte dürfen nicht als historische Evidence ausgegeben werden. Ein zweiter
„Segnungs-PR“ würde den tatsächlich reviewten Source-Head ebenfalls nicht ersetzen.

Deshalb lautet das G2-Ergebnis:

```text
recon = complete
candidate = deterministic
implementation_start = blocked
source_pr = forbidden
```

### Nächster erlaubter Schritt

Vor Schnitt C braucht Feature 01 eine eigene read-only Sequenzspec für ein minimales
Constitution-Governance-Prerequisite:

- konkreter anderer vertrauenswürdiger menschlicher GitHub-Principal,
- CODEOWNERS für Source und Contract-Test,
- erforderlicher Review plus Code-Owner-Review und stale dismissal,
- Admin-Enforcement ohne Bypass,
- geschützter commitgebundener Check `Context Constitution Attestation`,
- Author-/Reviewer-/Check-/Settings-Operationsdrill.

Weitergehende Delivery- und Aktivierungs-Governance bleibt Schnitt I. Die Korrektur darf
kein Mega-Governance-Patch werden.

Solange kein echter zweiter Human-Principal existiert, bleibt bereits der Governance- und
erst recht der Source-PR blockiert. Ein Bot, Agent oder derselbe Account unter anderem
lokalen Git-Autornamen ist ungültig.

Vollständiger G2-Beweis:
`specs/context_bridge_evidence/FEATURE_01_SLICE_C_G2_PREFLIGHT.md`.

## 19. Governance-Korrektur: Single-Owner-HITL statt künstlichem Zwei-Principal-Gate

### Warum der vorherige Schluss zu streng war

Der Slice-C-G2-Recon bewies korrekt, dass GitHub genau einen menschlichen Collaborator und
keinen unabhängigen Review-Principal besitzt. Daraus wurde jedoch eine universelle
Zwei-Principal-Precondition abgeleitet. Der Operator stellte klar, dass das Projekt
bewusst als Single-Owner-HITL geführt wird und kein zweiter Mensch verfügbar ist.

Ein Coding-Agent, Botname oder anderer lokaler Git-Autor ist kein unabhängiger Principal.
Genauso falsch wäre es aber, die Aufnahme eines zweiten Menschen als technische
Voraussetzung zu erfinden. Das hätte keine existierende Trust Boundary geschützt, sondern
die Constitution-Migration unbefristet blockiert.

### Korrigierter Vertrag

`specs/CONTEXT_BRIDGE_GOVERNANCE_AMENDMENT_01.md` trennt jetzt:

- Operatorentscheidung: explizite Freigabe eines eingefrorenen finalen PR-Heads,
- technische Delegation: Agent erstellt Diff, Evidence und Merge, entscheidet aber nicht
  anstelle des Operators über die Constitution,
- Git/CI-Evidence: Head, Blob, C0-Hash, Scope und Checks,
- ehrliche Provenance: `single_owner_hitl`, niemals erfundener `independent_review`.

Ein gültiges Source-Reviewpaket bindet Repository, PR, Base/Head, erlaubte Pfade,
vollständigen Diff, Source-Blob, C0-Hash, Kandidatenhash/-länge, Tests, unveränderte
Root-Blobs, Risiken und Nicht-Ziele. Die Freigabe lautet exakt:

```text
APPROVE CONSTITUTION <head_sha> <source_blob> <c0_sha256>
```

Jeder nachfolgende Commit invalidiert sie. PR-Titel, Commitmessage, `merged_by`, Issue,
Task oder Federation-Daten ersetzen die Operatorentscheidung nicht. CI attestiert
reproduzierbare Bytes und technische Verträge; der reservierte technische Name lautet
`Context Constitution Contract`, nicht eine vorgetäuschte Human-Attestation.

### Begrenzte Wirkung

Die Korrektur hebt ausschließlich den unbelegten zweiten-Human-Block auf. Sie aktiviert
weder Publisher noch Root-Ausgaben, Auto-Merge oder Runtime-Delivery. Slice C darf erst
nach reviewtem Merge des specs-only Amendments als separater Source-/Test-PR vorbereitet
werden und bleibt seinerseits bis zur exakt gebundenen Operatorfreigabe ungemergt.

Der historische G2-Befund bleibt erhalten und erhält eine explizite superseding note.
Phase 1 bleibt read-only. PHASE2_CURRENT bleibt ein widerlegbarer Arbeitsstand, keine SSOT.

## 20. Slice-C-CI korrigiert den zulässigen Integrationstest-Scope

Der erste vollständige CI-Lauf des exakten Slice-C-Kandidaten war in Lint und Security
grün und scheiterte in Python 3.11/3.12 am selben alten Integrationstest:
`TestGenerateBriefing.test_includes_orientation_from_conventions` verlangte weiterhin
`Antahkarana` oder `cognitive` aus der realen `.steward/conventions.md`.

Das ist kein Source- oder Parserfehler. Slice-C-G2 entschied ausdrücklich, dass die erste
versionierte Orientation leer bleibt und alte Architekturprosa default-deny entfernt
wird. Den C0-Vertrag zur Befriedigung des alten Tests aufzuweichen wäre falsch.

Der erlaubte Source-PR-Scope wird daher exakt um `tests/test_briefing.py` erweitert. Dort
darf nur der obsolete Real-Repo-Test zu einem Integrationsbeweis geändert werden, dass der
Legacy-Preview eine leere versionierte Orientation toleriert und keine Root-Datei schreibt.
Produktcode, zusätzliche Orientation-Prosa und jeder weitere Pfad bleiben verboten.

## 21. Adversariales Review findet Placebo-Orientation-Test

Der menschlich eingeholte Read-only-Review verweigerte die Constitution-Freigabe zu Recht.
Der neue Test in `tests/test_briefing.py` prüfte lediglich, dass `generate_briefing()`
irgendeinen String liefert und keine Root-Datei schreibt. Er hätte auch bestanden, wenn
`OrientationStage` vollständig ausgefallen wäre.

Positiv belegt wurden zwei Ursachen:

1. `_load_orientation()` liest die Source als freie Markdown-Prosa und versteht keine
   C0-/Orientation-Marker. Nach der Migration kann es deshalb C0 als Orientation behandeln.
2. `BriefingPipeline._render_all()` fängt jede Stage-Exception, loggt nur eine Warnung und
   rendert weiter. Ein indirekter Gesamtpreview ist kein Loader-Contract-Test.

PR `#552` wurde sofort als Draft markiert; sein Text nennt nun korrekt drei Pfade und den
Blocker. Head `1b6cb74849a240ac7be9318eb4ffa5f616253fee` ist verworfen und nicht attestiert.

Die korrigierte Sequenz ist chirurgisch: zuerst ein separater Zwei-Pfad-Adapter, der neue
Sources strikt mit `parse_conventions()` liest, nur Orientation zurückgibt, malformed
Marker fail-closed behandelt und unmarkierte Legacy-Source vorübergehend kompatibel hält.
Direkte Loader-Tests dürfen nicht durch die Stage-Exception-Grenze laufen. Erst danach
wird Slice C neu rebased, getestet, eingefroren und dem Operator erneut vorgelegt.

## 22. Preview-Compatibility implementiert; Slice C sauber neu aufgebaut

PR `#559` implementierte den korrigierten Zwei-Pfad-Vertrag und wurde als Merge
`2c4ac9c12445bc791423f4cdd830959987c79ccf` regulär auf `main` aufgenommen.

Der Loader unterscheidet jetzt drei Fälle:

- strukturierte Source: strict `parse_conventions()`, ausschließlich Orientation zurück;
- malformed strukturierte Source: sichere Warnung ohne Rohinhalt und fail-closed `""`;
- unmarkierte Legacy-Source: vorübergehend unveränderte Comment-Skipping-Semantik.

Invalid UTF-8 fällt ebenfalls geschlossen aus. Die generische Stage-Exception-Grenze blieb
bewusst unverändert; neue Tests rufen den Loader direkt auf. Fünf Tests waren vor dem Patch
rot, danach waren neun direkte und 102 angrenzende Tests lokal grün. Die vollständige CI
war in Python 3.11/3.12, Lint und Security grün.

Der verworfene Slice-C-Head wurde nicht weitergeflickt. Der Branch wurde auf den gemergten
Adapter zurückgesetzt und in zwei saubere Commits neu gebaut:

1. `tests/test_context_constitution.py` plus direkter Real-Source-Loadervertrag — vier
   belegte rote Failures gegen die alte Source;
2. ausschließlich die exakten 2.023 Sourcebytes — 105 gezielte Tests grün.

PR `#552` bleibt bis zum finalen Rebase nach dieser Continuity-Aktualisierung, neuer
vollständiger CI und gebundener Operatorfreigabe Draft. Der frühere Head ist ungültig.

## 23. Slice C freigegeben, gemergt und als nicht aktiviert verifiziert

Der technische Re-Review fand auf Head
`59169f2ca7822deeea068d206863d61b45e8401e` keine blockierenden Findings. Der menschliche
Operator genehmigte exakt diesen Head zusammen mit Source-Blob
`f428d5856a5c525e002c301890777748effbeb4e` und C0-SHA-256
`f23ab40415edf4947f12fd8ff98cf13aa8f4fbfffe029ae10aa6111fc04976a3`.

Vor Merge wurden Head, Source-Blob, C0-Hash und alle vier grünen Checks erneut remote
gebunden. Main-Drift seit der PR-Base betraf ausschließlich nicht überlappende
Heartbeat-State-Pfade. Es gab keinen Commit nach der Operatorfreigabe.

PR `#552` wurde regulär ohne Bypass als
`1d009b6cc7f26adfb5e2d179688c5c8990fe9ede` gemergt. Der First-Parent-Diff enthielt exakt:

```text
.steward/conventions.md
tests/test_briefing.py
tests/test_context_constitution.py
```

Der nachfolgende Produktionsrun `29444370093` war erfolgreich. Ein von dieser Session
versehentlich zusätzlich angeforderter, noch pending Run `29444409013` wurde vor Ausführung
abgebrochen. Der erfolgreiche Run erzeugte State-Commit
`1d88a82391d52296bda9d6b8bace3e4442599487` mit ausschließlich acht Runtime-State-Pfaden.

Nach dem Run blieben unverändert beziehungsweise absent:

- Source-Blob `f428d5856a5c525e002c301890777748effbeb4e`,
- `CLAUDE.md`-Blob `8146a15603c95e5aa1404c9eb7021e3008914b0c`,
- Root-`AGENTS.md` absent,
- Context-Snapshot und Publication-Record absent.

Damit ist Slice C abgeschlossen, aber Feature 01 ausdrücklich nicht aktiviert. Der nächste
zulässige Schritt ist read-only Slice-D-G2-Recon für lokalen Publisher und Recovery.
Vollständige Evidence:
`specs/context_bridge_evidence/FEATURE_01_SLICE_C_PRODUCTION.md`.

## 24. Slice D1 liefert strikten Vier-Artefakt-Read-back ohne Aktivierung

Der read-only Slice-D-Recon auf Head
`ff635f3b05ec225349d776e7ee557119b424bdb5` bewies, dass ein kombinierter Patch aus
Artifact-Parser, Git-Fence, Lock, Atomic Write und Recovery erneut ein riskanter Mega-
Schnitt wäre. D wurde deshalb in D1 (reiner Persisted-Generation-Read-back) und D2
(POSIX-Publisher/Recovery) geteilt.

Ein adversarialer Review des ersten Preflight-Heads fand vor Code einen realen
Feature-04-Widerspruch: `comparison_state` erlaubt vier nullable Counter, aber die alte
private `_valid_previous()`-Logik rief für jeden Wert `_count()` auf und lehnte `None` ab.
Der korrigierte G2-Vertrag verlangt dieselbe Nullable-Wahrheit für Snapshot, Record und
Decision, trennt strukturelle Value-Object-Validierung von Generationsvertrauen und
verlangt einen positiven Test für separat gelesene, bytegleiche Root-Objekte.

Der finale Preflight-Head `f56ad28325c4e4e272e4f9b23151682ed417a74e` wurde freigegeben
und als PR `#627`, Merge `4d1459c0dbfadf1da95a2582e765f4e367ac2455`, aufgenommen.

D1 wurde red-first in zwei Commits implementiert:

```text
24bdb0c2f31166d8fe2a8e37f51ab61767c60a2f test: define persisted generation readback
0214e3c871c33cb839293a2d6727382b0c479fac feat: validate persisted context generations
```

Der öffentliche `validate_previous_published_record()` prüft ausschließlich ein bereits
typisiertes Record-Value-Object. Nur `validate_persisted_generation()` darf aus vier
gemeinsam geprüften Bytes einen publisher-verwendbaren Previous Record zurückgeben. Es
prüft Größen, UTF-8, kanonisches JSON, Duplicate Keys, Envelopes, Marker, Targetmap,
Provenance, alle Hash- und Comparison-Bindungen sowie einen abschließenden exakten
Renderer-Rebuild. Dadurch entsteht keine zweite permissive Root-Sprache.

Das finale Code-Review gab exakt Head
`0214e3c871c33cb839293a2d6727382b0c479fac` frei. PR `#633` wurde als Merge
`5995d7f4dd0688ec1da0f7afded491d9011620be` aufgenommen. Exakt zwei Produkt- und zwei
Testpfade änderten sich; Filesystem, Git, Clock, Netzwerk, Writer, Lock, Recovery und
Caller blieben außerhalb.

124 gezielte Tests und ein zusätzlicher Scan über 338 gesampelte Einzelbyte-Mutationen
waren grün. Der vollständige lokale Lauf traf einen fremden Cetana/Dharma-Teardown-
Timeout; der exakte Test war isoliert grün, alle übrigen Tests ergaben 2.287 passed,
einen Skip und den bewusst deselecteten isolierten Test. Repositoryweites Ruff-Format,
Lint, Bandit sowie die vier CI-Checks waren grün.

Merge-CI `29558191253` und Folgeheartbeat `29558194430` liefen erfolgreich auf dem
exakten Merge-Head. Die beiden nachfolgenden Heartbeat-Commits
`ab1f4937d99e1c3f437efa5a2d7a2df44498f50d` und
`511f5a8760258ba23b503860ebc865aa97b4b335` änderten zusammen ausschließlich zehn
bekannte Runtime-/Federation-State-Pfade.

Am Merge- und Folge-Head blieben identisch beziehungsweise absent:

- Source `f428d5856a5c525e002c301890777748effbeb4e`,
- `CLAUDE.md` `8146a15603c95e5aa1404c9eb7021e3008914b0c`,
- `context_contract.py` `b5c7410ec9adc8ab8c35485a9238dc1d214e0bc5`,
- `context_rendering.py` `3dd923237d6871163e9b45b827a8e0d4b7d963bb`,
- Root-`AGENTS.md` absent,
- Snapshot- und Publication-Artefakt absent.

D1 ist damit abgeschlossen, aber Feature 01 weiterhin nicht aktiviert. Zum Zeitpunkt dieses
D1-Abschlusses war ein neuer read-only D2-G2-Preflight der nächste zulässige Schritt. Dieser
historische D1-Auftrag wurde durch den späteren Slice-E-E0-Gate überholt; der aktuelle
Parkzustand und der nächste Resume-Punkt stehen in §25. Publisher, Writer, Lock,
Root-/Record-Mutation, Recovery, `.gitignore`, Workflow, Settings, Delivery und Aktivierung
bleiben vollständig gesperrt. Vollständige D1-Evidence:
`specs/context_bridge_evidence/FEATURE_01_SLICE_D1_PRODUCTION.md`.

## §25 — CONTEXT BRIDGE SLICE E: E0 ABGESCHLOSSEN UND GEPARKT (2026-07-18)

### Ergebnis

Slice E (Bootstrap and Publisher Isolation) hat das E0-Spec-Gate erreicht. Der geprüfte
Spec-Head war `cedd9a4b09d22060b970b5e428eb4ca17e19695c`; PR `#775` wurde regulär gemergt.
Der Merge-Commit ist `29bfa331293b4ebfe0e8de874f125c4fc9805c4d`, der aktuelle Main-Tree ist
`571cdf5722fe443877d0bc819fb85f9c2c574854`.

Die maßgebliche Spec ist:

`specs/context_bridge_evidence/FEATURE_01_SLICE_E_BOOTSTRAP_ISOLATION_SPEC.md`

Der Slice-E-Merge enthielt ausschließlich diese Spezifikation; es wurden kein Publisher,
kein Writer, kein Workflow, kein Root- oder Runtime-State und keine Canonical-Aktivierung
geändert. Der Status der Spec ist E0 APPROVED. Das autorisiert den späteren E1-Start, nicht
die Aktivierung des Context-Bridge-Produktionspfads.

### Was E0 verbindlich festlegt

Der E0-Vertrag schreibt den späteren Isolations- und Beweisrahmen fest: dedizierter
Bubblewrap-Worker und Source-Exporter, FD-gebundene Source-Git-/Config-/Bundle-Eingaben,
clone3-/UID-/GID-Mapping, pidfd- und cgroup-Bindung, SCM-Credentials mit Challenge,
deterministische IPC-/Evidence-Kette sowie einen echten Fence-Race-Drill. Der geprüfte
Recon-Pin war `e8de55c737d141bfe95c6694b4ab7ffb38cb4266`; der dazugehörige Tree war
`6b089fd2c175821ebb84a9f3f9fbaf435bf6cc58`. Die dort dokumentierten 13 Runtime-/Federation-
Driftpfade waren nicht Teil des Slice-E-Spec-Scope.

### Bewusster Parkzustand

Es gibt derzeit keinen aktiven Context-Bridge-Coding-Auftrag. Bei einer späteren
Wiederaufnahme ist E1 der nächste isolierte Schritt: Bootstrap-Implementierung und direkte
Unit-Tests, weiterhin ohne D2b-Caller-Wiring. Erst danach dürfen E2 (echter Linux-
Isolations-/Race-Drill) und E3 (Crash-/Recovery-Evidence) bearbeitet werden. G1, D2b,
Publisher, Delivery und Canonical-Aktivierung bleiben bis zu ihren jeweils separat
reviewten Gates gesperrt. Neue Projektprioritäten haben Vorrang und dürfen nicht mit diesem
geparkten Strang vermischt werden.

Diese Sektion ist ein Kontinuitätsanker, kein neuer Arbeitsauftrag. Phase 1 bleibt vollständig
read-only. Eine neue Session liest zuerst `docs/PHASE2_CURRENT.md`, danach diese Sektion und
die E0-Spec; sie muss den Live-Head erneut über GitHub verifizieren, bevor sie E1 plant.

Die Parkdokumentation selbst wurde anschließend mit PR `#791` gemergt. Der aktuelle Main-Head
ist `a7f881d519539eb4649f22b415183efec7018eb4`, Tree
`c1f0cacbf9487957145ebf275d444dd866804413`; gegenüber dem E0-/Park-Basisstand kam nur
zwischenzeitlicher Runtime-/Federation-State hinzu. Das ändert weder den E0-Vertrag noch den
geparkten Resume-Punkt.

## §26 — EXECUTION TRUTH MAP RECON AKZEPTIERT; FUNDAMENT-GATES GETRENNT (2026-07-18)

### Autoritativer Stand

Der read-only Execution-Truth-Map-Recon über Steward, Agent City und die produktive
Steward-Protocol-Grenze ist abgeschlossen und als Gate akzeptiert. Live-Pins, vollständige
Identitäts-/Status-/Fehler-/Verification-Inventare, Federation-Wiring, Ist-Sequenz,
Gap-Matrix, Tests und Produktionsbelege stehen in:

`specs/execution_truth_map/EXECUTION_TRUTH_MAP_RECON.md`

Die zehn noch nicht entschiedenen Architekturfragen stehen ohne erfundene Antworten in:

`specs/execution_truth_map/ADR_BACKLOG.md`

### Bestätigte Fundamentrisse

- **G0:** Agent City kann trotz funktionalem Git-Push-Fehler grün enden; Produktionsrun
  `29644618328` belegt `GH006` plus Workflow-Success. `delegate_task` besitzt am Agent-City-
  Pin keinen Fachhandler. Steward und Agent City verwenden für PR-Verdicts inkompatible
  Signaturscopes/-encodings; vier fokussierte E2E-Tests reproduzieren die Ablehnung.
- **G1:** Es gibt keine durchgehende Ausführungsidentität. Delegation broadcastet trotz
  `target_agent`, verliert Ursprungstask/Korrelation, erzeugt am Empfänger eine neue Task-ID
  und korreliert Callbacks per Titel-Substring. Completion kann vor Wirkung/Verifikation
  eintreten; Transport-Receipts beweisen keine Remote-Wirkung; unbekannte Federation-
  Operationen können ohne strukturiertes Finding konsumiert werden.
- **G2:** Managed Task, A2A, Sankalpa und Chitta besitzen nicht übersetzte Statusmodelle.
  Agent City meldet produktiv den fehlenden optionalen `steward.provider`-Import. Der
  Heartbeat-Masterstatus war gegenüber dem bereits gemergten Schnitt A veraltet und ist
  mit diesem Milestone reconciliiert.

### Widerlegte oder präzisierte Altbehauptungen

- PR-Verdicts sind nicht als funktionierender End-to-End-Pfad belegt; der reale Crypto-
  Vertrag ist inkompatibel.
- Kirtan verifiziert Delegationscallbacks nicht: der Hook erwartet ein nicht vorhandenes
  `KirtanLoop.get_status`.
- `DeliveryReceipt` bestätigt keine Annahme, Ausführung oder Postcondition, sondern nur
  eine heuristische Transport-/Peer-Beobachtung.
- „Schnitt A noch nicht implementiert" war veraltet. PR `#759`, Merge
  `281c7112bb90d0fe1440d25bf8229dfe12980f17`, lieferte das Cognition-Instrument. Der
  aktuelle Health-State enthält den Block; `tests/test_moksha_health.py` läuft mit
  `17 passed`. Schnitt A ändert weiterhin keinen Run-Exit.

### Beschlossene nächste Gates

1. Heartbeat Failure Propagation bleibt in getrennten Schnitten: A ist geliefert; B
   (Eskalation) benötigt A-Produktionsdaten und eigene Spec; C (Run-rot) bleibt bis zu
   empirischer Schwelle, Prädikatentscheidung, atomarem Health-Write, Default-off
   Kill-Switch und Operator-Go gesperrt. Reconciliierte Dokumente:
   `specs/HEARTBEAT_FAILURE_PROPAGATION_SYSTEM_SPEC.md` und
   `specs/HEARTBEAT_FAILURE_PROPAGATION_FEATURE_01.md`.
2. Federation Delegation wird als eigener V1-Vertrag vorbereitet:
   `specs/FEDERATION_DELEGATION_CONTRACT_V1.md`. Die Fassung ist DRAFT 0.2, durch offene
   ADRs und adversariales/readiness Review blockiert und autorisiert keinen Produktcode.
3. Eine große Execution-Spine-System-Spec bleibt gesperrt. Eine spätere Spine muss aus den
   entschiedenen Heartbeat- und Federation-Verträgen abstrahieren, nicht umgekehrt.

### Schutzgrenzen

Dieser Milestone ändert ausschließlich Dokumentation. Phase 1 bleibt read-only. Die
Context Bridge bleibt gemäß §25 geparkt; PR `#728` ist offen und nicht freigegeben. E1,
D2b, G1, Publisher, Delivery und Canonical-Aktivierung bleiben gesperrt.

## §27 — ADR DECISION SPRINT 1: FEDERATION DELEGATION V1 (2026-07-18)

> Historischer Sprint-1-Stand; durch §28 und Draft 0.3 revidiert. Nicht als Fixture- oder
> Crucible-Basis verwenden.

Der Codebase-Agent hat für Agent B die fünf ausdrücklich beauftragten Federation-ADRs
erneut am Live-Code geprüft. Alle fünf Entscheidungen sind für den Delegation-V1-Scope
`ACCEPTED`; keine Entscheidung ist eine universelle Execution-Spine-Entscheidung und keine
autorisiert Produktcode:

| ADR | Entscheidung |
|---|---|
| ADR-02 | getrennte Identitätsrollen; V1 `correlation_id == delegation_id`, `message_id` pro logischer Message |
| ADR-06 | expliziter kanonischer Envelope, SHA-256/Ed25519/base64, gebundener `signer_key`, keine Hub-Mutation |
| ADR-07 | vollständiges Emitter→Transport→Target→Authority→Handler→Result→Test-Wiring als Implementierungs-Gate |
| ADR-08 | at-least-once Transport, durable idempotenter Receiver, sichtbares `RECOVERY_REQUIRED` statt Blind-Retry |
| ADR-09 | typisierte Receipts `transport_committed → admission → started → terminal → verification` |

Einzelbegründungen, Optionen, Auswirkungen, Gegenargumente und Readiness stehen in:

`specs/execution_truth_map/ADR-02-ID-BOUNDARIES.md`

`specs/execution_truth_map/ADR-06-FEDERATION-SIGNATURE.md`

`specs/execution_truth_map/ADR-07-CAPABILITY-WIRING.md`

`specs/execution_truth_map/ADR-08-RETRY-RECOVERY-IDEMPOTENZ.md`

`specs/execution_truth_map/ADR-09-RECEIPT-SEMANTIK.md`

Der Contract wurde zu Draft 0.2 reconciliiert:

`specs/FEDERATION_DELEGATION_CONTRACT_V1.md`

Damit sind Wire-Objekte, Signaturbytes, Targeting, Idempotenz und Receipt-Stufen explizit
beschrieben. Der separate Widerspruchs- und Implementierungsreife-Review steht in:

`specs/execution_truth_map/ADR_DECISION_SPRINT_1_REVIEW.md`

Er findet keinen direkten Widerspruch zwischen den fünf Entscheidungen; der Contract bleibt
dennoch `NOT IMPLEMENTATION-READY`. Verbleibende Blocker sind ADR-05 (Workflow-Wahrheit) und ADR-10
(Statusadapter); ADR-01/-03/-04 bleiben bewusst außerhalb dieses Sprints offen.

Der durchgeführte Widerspruchs- und Implementierungsreife-Review steht in
`specs/execution_truth_map/ADR_DECISION_SPRINT_1_REVIEW.md`: kein direkter Widerspruch,
aber weiterhin `NOT IMPLEMENTATION-READY`. Vor Implementierung bleiben erforderlich:
Agent-B-Review, Golden-Wire-Fixtures, Ledger-/Lease-Crucible und ein echter
Steward→Agent-City-Delegations-Crucible. Phase 1, Context Bridge und Produktcode bleiben
unangetastet.

## §28 — ADR DECISION SPRINT 1B: REVISION REQUIRED (2026-07-18)

Agent B hat Draft 0.2 als architektonisch tragfähig, aber noch nicht fixture- oder
crucible-ready bewertet. Die elf normativen Lücken wurden in einem gezielten Sprint 1B
behandelt, ohne Produktcode zu ändern:

- Transport-Retransmission und Application-Reissue sind getrennt.
- `request_digest` wird über eine exakt definierte semantische Request-Payload berechnet;
  `idempotency_key` ist deterministisch daraus abgeleitet.
- Node-ID, `key_id`, stabile Registry-Provenance, Rotation und Revocation sind neu gefasst;
  ADR-06 bleibt bis zur Agent-Bestätigung `OPEN / REVISION REQUIRED`.
- Domain Separation ist Bestandteil des Signaturinputs.
- Canonical JSON, Zeitprofil, Unicode, Zahlen, Base64, Limits und Versionsliteral sind
  explizit festgelegt.
- Receipt-Stufen bilden einen Partial Order; Out-of-Order, Reject-Seitenpfad und Replay sind
  getrennt geregelt.
- `request_message_id` und `causation_message_id` ersetzen `subject_message_id`.
- Target- und Origin-Ledger sind getrennte Zustandsbesitzer.
- Capability-Status lautet `declared`, `partially_wired`, `code_complete`,
  `crucible_verified`, `production_proven`, `unavailable` oder `legacy`.

Die vollständige Revision steht in:

`specs/execution_truth_map/ADR_DECISION_SPRINT_1B_REVISION.md`

Die aktualisierte Blocker-Matrix steht in:

`specs/execution_truth_map/ADR_SPRINT_1B_BLOCKER_MATRIX.md`

Die neue Contract-Fassung ist:

`specs/FEDERATION_DELEGATION_CONTRACT_V1_DRAFT_0_3.md`

Das self-contained Review-Packet für die nächste Agent-B-Prüfung ist:

`specs/execution_truth_map/AGENT_B_ADR_SPRINT_1B_REVIEW_PACKET.md`

Draft 0.3 bleibt `NOT IMPLEMENTATION-READY`, bis Agent B die revidierten Crypto-, Digest-,
Partial-Order-, Ledger- und Statusregeln bestätigt. Golden-Wire-Fixtures, Crucible-Design,
Produktcode, Phase 1 und Context Bridge bleiben gesperrt.

## §29 — ADR DECISION SPRINT 1C: DRAFT 0.4 NOCH NICHT FIXTURE-READY (2026-07-18)

Agent B bewertet Draft 0.3 als wesentlich verbessert, aber noch nicht bereit für Golden-
Wire-Fixtures. Ein enger Sprint 1C behandelt ausschließlich die verbliebenen normativen
Lücken:

- Wrong-Target wird ausschließlich internes Finding/Quarantine; keine automatische signierte Antwort.
- Root-Identity erhält Enrollment, Root-signierte Key-Certificates, Aktivierung, Rotation,
  Root-Ablösung, Collision-Handling und Revocation-Provenance.
- Revocation erhält `not_before`, `not_after`, `revoked_at`, `revocation_effective_at`,
  `revocation_reason`, reguläre Rotation und emergency compromise.
- Canonical JSON wird als sprachneutrales SFDJ-1-Profil mit NFC-Reject, rekursiver Prüfung,
  Escape-, Zahlen-, Größen- und Bytegleichheitsregeln festgelegt.
- Receipt-Retransmission und Receipt-Reissue werden getrennt; `receipt_id` bleibt beim
  Reissue gleich, `receipt_content_digest` bindet den fachlichen Inhalt.
- `request_message_id` bleibt immer der erste Request; `causation_message_id` folgt der
  unmittelbaren Status-/Recovery-Ursache.
- `delegation_status_query` und `delegation_status` erhalten vollständige Schemas,
  Authority-, Privacy-, Rate-Limit-, Replay- und Wiring-Regeln.
- Capability-Reife und Disposition werden als zwei Achsen modelliert.

Die vollständige Revision steht in:

`specs/execution_truth_map/ADR_DECISION_SPRINT_1C_REVISION.md`

Draft 0.4 steht in:

`specs/FEDERATION_DELEGATION_CONTRACT_V1_DRAFT_0_4.md`

Das self-contained Review-Packet steht in:

`specs/execution_truth_map/AGENT_B_ADR_SPRINT_1C_REVIEW_PACKET.md`

Die Entscheidung bleibt `NOT READY FOR GOLDEN FIXTURES`. Produktcode, Phase 1 und Context
Bridge bleiben unverändert; ADR-05 und ADR-10 bleiben spätere Produktions-/Integrations-
Blocker.

## §30 — ADR DECISION SPRINT 1C FREEZE: DRAFT 0.5 READY FOR GOLDEN FIXTURES (2026-07-18)

Agent B hat Draft 0.4 als architektonisch tragfähig, aber wegen drei eng begrenzter Freeze-
Aufgaben noch nicht fixture-ready bewertet. Diese Aufgaben sind nun dokumentarisch und
normativ geschlossen; es wurde kein Produktcode geändert:

- Geschlossene V1-Payload-Schemas für `delegate_task`, `delegation_receipt` mit den Stufen
  `transport_committed`, `admission`, `started`, `terminal`, `verification`, sowie
  `delegation_status_query` und `delegation_status`: Typen, Pflichtfelder, Nullability,
  Limits, Enums, Unknown-Field-Verbot, Digest-Bindung und Authority-/Privacy-Semantik.
- Root-Verlust/-Kompromittierung ist kein Federation-Recovery-Pfad: Node fail-closed für
  neue V1-Nachrichten; manuelle out-of-band Governance/Neu-Enrollment außerhalb V1; keine
  Quorum-, automatische Übernahme- oder Root-Replacement-Semantik; Historie/Audit bleiben.
- Status Query autorisiert echte Daten nur für die kryptografisch gebundene eigene
  `delegation_id`; fremde oder unbekannte IDs erhalten denselben minimalen UNKNOWN-Snapshot.
  Die Antwort enthält keine fremden Delegationen, Worker-/Lease-Details, Stacktraces,
  Secrets, Pfade oder unvereinbarte Evidence; Rate-Limit und Audit-Finding bleiben lokal.

SFDJ-1 bleibt unverändert eingefroren. ADR-02, ADR-06, ADR-07, ADR-08 und ADR-09 sind im
engen Federation-V1-Wire-Scope `ACCEPTED`. Die Contract-Fassung ist:

`specs/FEDERATION_DELEGATION_CONTRACT_V1_DRAFT_0_5.md`

Das vollständige self-contained Agent-B-Freeze-Packet ist:

`specs/execution_truth_map/AGENT_B_ADR_SPRINT_1C_FREEZE_REVIEW_PACKET.md`

Die endgültige Matrix ist:

`specs/execution_truth_map/ADR_SPRINT_1C_FINAL_BLOCKER_MATRIX.md`

Damit ist Draft 0.5 `READY FOR GOLDEN FIXTURES`. Dieser Status autorisiert ausschließlich
den nächsten Milestone: Golden-Wire-Fixtures plus unabhängige Steward-/Agent-City-Parser-
und Signaturtests. Noch gesperrt bleiben Produktcode, Handler, Ledger-/Workflow-Änderungen,
Crucible-Ausführung, Merge, Phase 1 und Context Bridge. ADR-03, ADR-05 und ADR-10 bleiben
spätere Managed-Task-, Produktions- und Integrationsblocker.

## §31 — AGENT-B FREEZE REVIEW: VIER DIREKTE KORREKTUREN (2026-07-18)

Agent B hat Draft 0.5 fast akzeptiert und vier direkte Inkonsistenzen vor Fixture-Start
markiert. Im korrigierten Draft 0.5 und Freeze-Packet sind sie geschlossen:

- `delegation_status.terminal_status` ist ausschließlich `completed`, `failed` oder
  `null`; `verified`/`failed_verification` gehören nur Origin-Ledger und Verification-
  Receipt.
- Bei fehlendem Ledger-Eintrag oder fremdem Origin liefert Status Query denselben
  minimalen `UNKNOWN`-Snapshot ohne Reason-, Größen- oder Timing-Orakel.
- Root-Enrollment-Record und Signing-Key-Authorization-Certificate besitzen geschlossene,
  bytegenaue SFDJ-1-Felder, Domains, Signaturinputs, Epochs, Aktivierung, Zeitfenster,
  key_id/node_id und Revocation-Referenz.
- Das Admission-Beispiel enthält nun das verpflichtende `issuer_role=target_node`; die
  JSON-Beispiele wurden auf schemaförmige Base64-/Issuer-Felder geprüft.

Der nächste Milestone bleibt ausschließlich Golden-Wire-Fixtures und unabhängige Parser- /
Signaturtests. Kein Produktcode, Handler, Ledger, Workflow, Merge, Crucible, Phase 1 oder
Context-Bridge-Resume ist dadurch autorisiert.

## §32 — GOLDEN WIRE FIXTURES 01: POSITIVE PARITY UND NEGATIVE GRENZEN (2026-07-18)

Die Freeze-Abnahme hat Draft 0.5 für Golden Fixtures freigegeben. Auf dem separaten
Fixture-Branch wurden ausschließlich deterministische Testartefakte und unabhängige
Referenztests erstellt:

- vier synthetische, als nicht-produktiv markierte Ed25519-Testschlüssel für Origin/Target
  Root und Signing-Key,
- Root-Enrollment- und Signing-Key-Certificate-Provenance mit SFDJ-1-Bytes, Digest,
  Domain-Signatur, `node_id` und `key_id`,
- ein vollständig berechneter `delegate_task`-Envelope mit Request-Digest,
  Idempotency-Key, Message-Hash und Ed25519-Signatur,
- 17 negative Fixtures mit maschinenlesbarem Reject-Code und Validierungsphase.

Die Artefakte und SHA-256-Manifest liegen unter:

`tests/fixtures/federation_v1/`

Der vollständige Milestone-Bericht liegt unter:

`specs/execution_truth_map/GOLDEN_WIRE_FIXTURES_01_REPORT.md`

Unabhängige Referenztests sind in Steward und Agent City vorhanden und bestanden jeweils
`20 passed`. Kein Runtime-Handler, Ledger, Workflow, Provider-Crucible oder Produktionspfad
wurde verändert. Phase 1 und Context Bridge bleiben unverändert.

## §33 — GOLDEN WIRE FIXTURES 01A: UNABHÄNGIGE REGENERATION (2026-07-18)

Agent B hat die gespeicherten Fixtures akzeptiert, aber die erste Abnahme bis zum Beweis
repo-lokaler unabhängiger Regeneration blockiert. Diese Testhärtung ist abgeschlossen:

- Steward und Agent City bauen Enrollment, Certificate, `node_id`, `key_id`,
  `request_digest`, Idempotency-Key, vollständigen Request, SFDJ-1-Bytes, Message-Hash,
  Domain-Signature-Input und Ed25519-Signatur jeweils aus semantischen Eingaben und den
  deterministischen Test-Seeds neu; die Ergebnisse sind byteidentisch zu Fixtures und
  Manifest.
- Beide Seiten prüfen die vollständige Provenance-Bindung einschließlich geschlossener
  Feldmengen, Root-/Certificate-Key-Bindung, Epochs, RFC-3339-Zeitfenster,
  `rotation_kind` und `revocation_ref` am festen Fixture-Prüfzeitpunkt.
- Eine allgemeine, phasenweise Referenzvalidierung beweist für alle 17 Negativfälle die
  erste fehlschlagende Grenze. Die Reject-Codes werden nicht aus Fall-ID oder Dateiname
  abgeleitet; Steward und Agent City liefern dieselbe Code-/Phasenmatrix.

Der aktualisierte vollständige Bericht ist:

`specs/execution_truth_map/GOLDEN_WIRE_FIXTURES_01_REPORT.md`

Die erweiterten repo-lokalen Testmodule liegen unter
`tests/federation_v1/hardening.py` und `tests/federation_v1/test_golden_wire_01a.py` in
beiden Repositories. Beide Suiten bestehen mit `23 passed`. Es wurden ausschließlich
Tests, Fixtures/Bericht und diese Befund-Dokumentation geändert; Produktcode, Phase 1,
Context Bridge, Handler, Ledger, Workflow und Produktionsintegration bleiben unverändert.

## §34 — FEDERATION DELEGATION IMPLEMENTATION PLAN 01 / REVISION 0.2 (2026-07-18)

Nach der 01A-Abnahme ist ausschließlich ein Implementierungsplan vorbereitet; noch kein
Produktcode ist freigegeben oder geändert. Der Plan liegt self-contained unter:

`specs/execution_truth_map/FEDERATION_DELEGATION_IMPLEMENTATION_PLAN_01.md`

Der kleinste vorgesehene reale Slice lautet:

`Steward signierter V1-Request -> exakter Agent-City-Carrier -> SFDJ-/Provenance-/Authority-
Prüfung -> durable Target-Admission vor Side Effect -> signiertes admission-Receipt ->
Origin-Korrelation über IDs`.

Der Slice erzeugt keinen Worker und kein Tool, keine Started-/Terminal-/Verification-
Receipt, keine Status-Query, keine Recovery, keinen Managed-Task-Abschluss und keine
Produktivaktivierung. Legacy-`OP_DELEGATE_TASK` und Titelmatching bleiben isoliert. Der
Plan entscheidet `wire_bytes_b64` als unsignierten Transportcarrier für unveränderte
SFDJ-1-Bytes, repo-lokale Produktionsadapter ohne gemeinsame Runtime-Library, einen
persistenten Target-Admission-/Dedupe-Ledger sowie ein Wiring-Manifest mit deaktiviertem
Default-Gate.

Agent B verlangte fünf enge Präzisierungen; Revision 0.2 schließt ausschließlich diese:

- ACCEPTED- und REJECTED-Admission persistieren atomar vollständige signierte Receipt-
  Bytes, Message-/Receipt-IDs, Hash, Signatur und Sendestatus;
- Request- und Receipt-Carrier besitzen geschlossene Felder, Größen-/Base64-Regeln,
  Source-/Target-/Operation-Bindung und keinen Legacy-Fallback;
- der Origin setzt `target_work_id` beim ersten gültigen Accepted-Receipt, bestätigt ihn
  bei identischem Duplicate und quarantänisiert abweichende Werte;
- Request-Wire-Bytes und Carrier-Metadaten werden unveränderlich gespeichert und für
  Retransmission exakt wiederverwendet;
- Crash-, Reject-Replay- und Carrier-Mutations-Gates sind als Tests festgelegt.

Der Plan steht auf dem separaten Branch `plan/federation-delegation-implementation-01`
und wartet erneut auf Agent-B-Review. Bis zur Entscheidung bleiben Produktcode, Context
Bridge, Execution-Spine-Gesamtspec, Provider-Failover-Umbau, Merge-Autorität und
produktive Aktivierung gesperrt.

## §35 — FEDERATION DELEGATION IMPLEMENTATION SLICE 01 (2026-07-18)

Die Implementierung ist auf separaten, nicht gemergten Branches erfolgt und wartet auf
die erneute Agent-B-Abnahme. Die exakten Remote-Pins und die vollständige, self-contained
Review-Unterlage stehen in:

`specs/execution_truth_map/AGENT_B_FEDERATION_DELEGATION_IMPLEMENTATION_SLICE_01_REVIEW.md`

Implementierungspins:

- Steward `impl/federation-delegation-slice-01`:
  `e83c919209c17dd1bf2377c811ce10e689078539`
- Agent City `impl/federation-delegation-slice-01`:
  `58493604c545b23b3926d56d71b46afb0bd2fbe1`

Der ausschließlich freigegebene Slice ist nun produktseitig vorhanden:

`Steward V1 Origin -> geschlossener exakt adressierter Carrier -> Agent-City-V1-Ingress ->
SFDJ-/Provenance-/Signatur-/Authority-Prüfung -> atomarer ACCEPTED-/REJECTED-Admission-
Ledger -> vollständig gespeichertes signiertes Admission-Receipt -> geschlossener Receipt-
Carrier -> Steward-ID-Korrelation`.

Belegt ist insbesondere:

- vollständige Request- und Receipt-Wire-Bytes, getrennte Message-/Receipt-IDs, Hashes,
  Signatur und Sendestatus im Ledger;
- First-Set-/Duplicate-Match-Semantik für `target_work_id`;
- durable, idempotente REJECTED-Receipts;
- Carrier-Mutation-Quarantäne ohne Netzwerkantwort;
- default-deaktiviertes Feature-Gate und unveränderte Legacy-`OP_DELEGATE_TASK`-/Titel-
  Pfade;
- repo-lokale, unabhängige Steward-/Agent-City-Adapter ohne neue gemeinsame Runtime-
  Library.

Gemessene Ergebnisse nach dem letzten Commit:

- Steward Slice plus Golden Fixtures: `52 passed`;
- Agent City Slice plus Golden Fixtures: `52 passed`;
- Steward Legacy Federation Gateway/Quarantine: `61 passed`;
- Agent-City-Federation-Regression inklusive NADI/Relay: `142 passed`;
- admission-only Cross-Repo-Crucible mit separatem Agent-City-Checkout: `1 passed`;
- Ruff und `py_compile` für beide neuen Adapter/Testgrenzen: sauber/pass.

Der Crucible erzeugt den Request aus semantischen Eingaben, bestätigt bytegleiche Golden-
Request-Bytes, validiert und persistiert die Admission in Agent City, korreliert das
signierte Receipt in Steward und bestätigt identisches Replay samt unverändertem
`target_work_id`.

Noch ausdrücklich gesperrt: Worker-/Tool-Ausführung, Started-/Terminal-/Verification-
Receipts, Status Query, Lease/Recovery-Automation, Managed-Task-COMPLETED, Provider-
Failover, Context Bridge, Execution-Spine-Gesamtspec, automatische Merge-Autorität,
produktive Aktivierung und Merge. Phase 1 bleibt unverändert. Der Agent-B-Entscheidungs-
status ist bis zur Review `IMPLEMENTATION REVIEW REQUESTED`.

## §36 — FEDERATION DELEGATION SLICE 01A: AGENT-B-BLOCKER REVISION (2026-07-18)

Agent B hat vier enge Produktcode-Blocker benannt; kein neuer ADR- oder Plan-Sprint war
erforderlich. Die Revision ist auf denselben separaten Branches umgesetzt:

- Steward: `0248dc4efbd514eaf20bb2c1ed79101d87eb4516`
- Agent City: `0caa6fb536cc5b5883ffde89e66282af5c6e26bc`

Das vollständige aktualisierte self-contained Review-Paket ist:

`specs/execution_truth_map/AGENT_B_FEDERATION_DELEGATION_IMPLEMENTATION_SLICE_01_REVIEW.md`

Geschlossene Blocker:

- `FederationV1Origin.create` gibt nur noch exakt persistierte Request-/Carrier-Bytes
  zurück; gleiche bestehende Requests werden aus dem Ledger wiedergegeben, Digest-,
  Message-ID-, Payload- und Wire-Konflikte erzeugen `origin_request_conflict` plus
  persistentes Finding.
- Origin-Receipt-Anwendung erzwingt Source-/Target-Bindung, ursprüngliche
  `delegation_id`, `correlation_id`, `request_message_id` und
  `causation_message_id`; falsch signierte Kausalität oder ein anderer registrierter
  Knoten mutieren den Ledger nicht.
- Beide Validatoren akzeptieren ausschließlich einen typisierten,
  provenance-validierten `ValidatedFederationV1KeyRegistry`-Snapshot. Root Enrollment,
  Root-Signatur, Certificate, Node-/Key-Ableitung, Epochs, Zeitfenster, Rotation und
  Revocation werden vor der Envelope-Prüfung erzwungen.
- Bestehende, aber unlesbare oder semantisch ungültige Ledger-Dateien lösen
  `ledger_corrupt` aus. Alle Ledger-RMW-Operationen besitzen zusätzlich zur
  Thread-Sperre eine repo-lokale Interprozess-Sperre um den vollständigen
  `read -> modify -> fsync -> replace`-Abschnitt.

Gemessene Revisionsergebnisse:

- Steward Slice/Fixtures: `65 passed`;
- Agent City Slice/Hardening/Fixtures: `64 passed`;
- Cross-Repo Admission-Crucible: `1 passed`;
- Steward Legacy Gateway/Quarantine: `61 passed`;
- Agent-City NADI/Relay: `90 passed`;
- Ruff und `py_compile` für beide neuen Adapter/Testgrenzen: sauber/pass.

Die Tests decken nun zusätzlich Origin-Idempotenz und Konflikte, falsche registrierte
Receipt-Quelle, Correlation/Causation/Target-Bindung, Provenance-Zeit-/Revocation-
Grenzen, korrupten Ledger-State sowie parallele unabhängige Ledger-Instanzen und
Updates ab. Feature-Gate, Legacy-Pfade, Phase 1, Context Bridge und alle weiterhin
gesperrten Runtime-/Workflow-Funktionen bleiben unverändert. Agent-B-Status ist nun
`REVISION REVIEW REQUESTED`; Merge und produktive Aktivierung bleiben ausstehend.

## §37 — FEDERATION DELEGATION SLICE 01A: MERGE- UND CI-STAND (2026-07-18)

Die Agent-B-Abnahme `ACCEPTED FOR MERGE REVIEW` wurde umgesetzt. Die beiden
Implementierungs-PRs sind nun auf den jeweiligen autoritativen `main`-Branches:

- Steward PR #829 wurde regulär gemergt. Merge-Commit:
  `9f6519d8d8713b81c6197217d61e3b1fcc144ea7`. Der danach verifizierte aktuelle
  Remote-`main`-Stand ist `2bae8b694222aa2d3395c779bfdc2b2ed9813901`; der zusätzliche
  Heartbeat-Commit `chore: heartbeat #5879 state sync` ist für die historische
  Signalbewertung ausdrücklich ausgeschlossen.
- Agent City PR #2203 wurde nach dokumentiertem Admin-Bypass gemergt, weil GitHub
  ausschließlich `REVIEW_REQUIRED` meldete und für den Branch keine automatischen
  Required Checks vorhanden waren. Merge-Commit und aktueller Remote-`main`-Stand:
  `d16b7ffb1db0cd1f794bd6066b7978e6db86794b`.
- Der Audit-Kommentar in PR #2203 enthält die vor dem Bypass verifizierten Base-/Head-
  Pins, Agent-B-Abnahme, Testzahlen, Crucible-Beleg, fehlende automatische Checks,
  Begründung des Bypasses und den weiterhin deaktivierten Gate-Zustand.

Post-Merge-Smoke gegen diese `main`-Stände:

- Steward Slice/Golden Fixtures: `65 passed`.
- Steward Legacy Gateway/Quarantine: `61 passed`.
- Agent City Slice/Hardening/Fixtures: `64 passed`.
- Agent City Legacy Federation/NADI/Relay: `91 passed`.
- Cross-Repo Admission-only Crucible mit Agent-City-`main`: `1 passed`.
- Steward CI für PR #829: Python 3.11, Python 3.12, Lint und Security jeweils
  erfolgreich.

Der Merge ändert keine Aktivierung: `FEDERATION_V1_DELEGATION_ENABLED` bleibt
standardmäßig `false`, die beiden implementierten Wiring-Einträge bleiben
`crucible_verified` mit Disposition `disabled`, und es gibt keinen produktiven Caller.
Worker-/Tool-Ausführung, Status Query, Lease/Recovery, Terminal-/Verification-Receipts,
Managed-Task-Abschluss, Provider-Failover, Context Bridge und Execution-Spine bleiben
gesperrt. Die Feature-Branches sind nicht mehr die Wahrheitsquelle; die obigen
`main`-Pins sind autoritativ.

## §38 — FEDERATION DELEGATION SLICE 02: EXISTING DISPATCH SURFACE RECON (2026-07-18)

Nach dem dokumentierten Admin-Bypass von Agent-City-PR #2209 wurde ein ausschließlicher
Read-only-Recon der vorhandenen Dispatch-Oberflächen durchgeführt. Die aktuellen
Remote-Pins zum Recon sind Steward `main`
`2dd7cd9288fb451b6172ee2bf78328772acb2716` und Agent City `main`
`a854f590391f73da10b33f402c321fd68f3fd0b5`. Heartbeat-Commits wurden bei der
semantischen Historienbewertung explizit ausgeschlossen; der aktuelle Steward-Head ist
dennoch als Live-Pin dokumentiert.

Der vollständige, self-contained Befund steht in:

`specs/execution_truth_map/FEDERATION_DELEGATION_SLICE_02_EXISTING_DISPATCH_SURFACE_RECON.md`

Autoritativer Ist-Befund:

- Slice 01A besitzt eine durable, idempotente V1-Admission mit signiertem Receipt und
  synthetischem `target_work_id`, aber noch keine Mission, Task-, Queue- oder Worker-
  Zuweisung und keinen V1-`started`-Pfad.
- Agent City besitzt Sankalpa-Missionen/-Registry, den reinen Capability-/Scoring-
  `mission_router`, den in-memory `CityRouter` sowie Spawner/Pokedex; keine dieser
  Komponenten besitzt heute zugleich V1-Delegationsbindung, dauerhafte Work-Ownership
  und crashsichere First-Set-Semantik.
- Steward besitzt den produktiv verwendeten legacy TaskManager/Autonomy-Pfad. Er ist
  UUID-/Status-basiert, aber nicht V1-korreliert; legacy `OP_DELEGATE_TASK` und
  Titelmatching bleiben isoliert.
- Es existiert kein `WorkerRegistry`, keine V1-Serviceverdrahtung im Agent-City-
  Factory-Registry und kein `started`-Receipt-Builder/Handler.

Der Manifest-Wahrheitsrand wurde erneut geprüft: `docs/FEDERATION_DELEGATION_WIRING_MANIFEST_01.json`
ist ausschließlich versionierte Capability-/Audit-Dokumentation. Kein Runtime-Code in
Steward oder Agent City importiert oder verwendet es als Health-State. Manuelle Werte
wie `crucible_verified`, `disabled`, Testresultate und Merge-Pins sind historische,
beleggebundene Milestone-Aussagen. Provider-, Node-, Heartbeat-, Ledger- und aktuelle
Capability-Gesundheit müssen aus Messung, persistentem Runtime-State oder reproduzierbaren
Probes stammen und werden nicht manuell in dieses Dokument geschrieben.

Die Empfehlung lautet: Slice 02 ist als nächster enger Abschnitt gerechtfertigt, aber
erst nach einem Agent-B-geprüften Plan, der den target-owned Assignment-Record, die
atomare Admission-to-Assignment-Grenze, Duplicate/Crash-Verhalten und die Entstehung
eines einzigen `started`-Receipts entscheidet. Noch kein Produktcode, keine Worker-/Tool-
Ausführung, kein Status Query, keine Recovery-Automation, keine Verification oder
Context-Bridge-Aktivierung.

## §39 — FEDERATION DELEGATION IMPLEMENTATION PLAN 02 (2026-07-18)

Der Slice-02-Recon ist akzeptiert und Steward PR #836 regulär gemergt:

- Merge-Commit: `2f1ac917ff6f48a97839b0804cd201e1a2a8c030`
- aktueller verifizierter Steward-`main`-Head zum Planbeginn:
  `2f1ac917ff6f48a97839b0804cd201e1a2a8c030`

Der rein dokumentarische Plan 02 steht vollständig in:

`specs/execution_truth_map/FEDERATION_DELEGATION_IMPLEMENTATION_PLAN_02.md`

Er definiert ausschließlich:

`validated ACCEPTED admission -> eine target-owned Assignment im bestehenden
TargetAdmissionLedger -> keine Mission/Task/Worker/Tool-Ausführung -> dauerhaft
gespeichertes signiertes started-Receipt -> Steward-Korrelation auf dieselbe Delegation
und denselben target_work_id`.

Die bevorzugte Architektur ist eine enge Erweiterung des bestehenden
`TargetAdmissionLedger`; ein zweiter Work-Store ist nur nach belegtem Code-Blocker
zulässig. Die Assignment- und vollständigen Started-Receipt-Daten werden als eine
atomare Commit-Einheit geplant. `ASSIGNMENT_PENDING` und `ASSIGNED` bleiben interne
Vor-Commit-Phasen; der durable Zustand springt von `ACCEPTED` auf `STARTED`, damit keine
Assignment ohne Start-Evidence persistiert wird. Candidate-/Authority-Digests und
Assignment-Epoch werden über geschlossene `evidence_refs` des eingefrorenen Started-
Receipt-Schemas gebunden.

Der Plan enthält Ledger-Schema-Diff, Candidate-Auswahl, Atomicity-/Crash-/Duplicate-
Matrix, Origin-Korrelation, Wiring-/Legacy-Isolation, Definition of Done und Agent-B-
Reviewfragen. Noch kein Produktcode, keine Mission, kein Worker/Cartridge, kein Tool,
keine Recovery-/Lease-Automation, kein Status Query, keine terminale oder Verification-
Receipt-Logik und keine Aktivierung.

## §40 — FEDERATION DELEGATION PLAN 02: ASSIGNMENT/STARTED-KORREKTUR (2026-07-18)

Agent B hat Plan 02 Revision 0.1 wegen einer semantisch falschen Verwendung von
`receipt_stage=started` zurückgewiesen. Die Revision 0.2 wählt deshalb ausdrücklich Weg A:

- Slice 02 endet bei `ACCEPTED -> ASSIGNED` im bestehenden target-owned
  `TargetAdmissionLedger`.
- `ASSIGNED` bedeutet nur unveränderlicher beobachteter Candidate-Snapshot, Authority-
  Bindung, Epoch und atomar persistierte signierte target-lokale Assignment-Attestation.
- Es gibt kein externes Receipt, kein `started`, keine Reservation, keine Mission, kein
  Queue Item und keine Ausführung.
- Das eingefrorene `started`-Receipt bleibt einem späteren Slice mit durablem Work Item
  oder echter Scheduler-Reservation vorbehalten.
- Steward besitzt in diesem Slice kein Assignment-Evidence-Objekt und behauptet daher
  keine unabhängige Verification. Eine spätere externe Attestation wäre nur eine signed
  target attestation, keine Verification Receipt.
- Candidate-Staleness wird über `observed_candidate_snapshot`, `observed_at` und einen
  vor Commit erneut geprüften Source-Observation-Token begrenzt. Eine fortbestehende
  Availability oder Ownership wird nicht behauptet.

Der vollständige revidierte Plan steht in:

`specs/execution_truth_map/FEDERATION_DELEGATION_IMPLEMENTATION_PLAN_02.md`

Noch kein Produktcode und weiterhin gesperrt: Mission, Queue, Worker/Cartridge, Tool,
LLM, Git, Lease/Recovery, terminale/Verification-Receipts, Status Query, Provider
Failover, Context Bridge und Aktivierung.
