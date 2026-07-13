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
