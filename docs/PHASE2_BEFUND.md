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
