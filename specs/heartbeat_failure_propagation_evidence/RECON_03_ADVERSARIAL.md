# HEARTBEAT-FEHLERPROPAGATION — RECON 03: ADVERSARIALES GEGENBEWEIS-REVIEW

> **Status:** EVIDENCE — KERNBEHAUPTUNG HÄLT; BEFUND UMGEDREHT: NICHT FEHLENDE ERKENNUNG,
> SONDERN FEHLENDE AUSSENVERDRAHTUNG
> **Datum:** 2026-07-17
> **Code-Basis:** `kimeisele/steward@bf2fba2075a87463fc8e333f8f57d805fce4d030`
> **Scope:** Read-only. Aktiver Versuch, RECON_01/02 zu WIDERLEGEN (Phase-1 §220.3).
> **Verifikation:** `vedana.py:74–118` und `engine.py:305–369` von Opus direkt gelesen;
> übrige Anker per Sub-Agent (Explore, verbatim) geholt, gegen RECON_01/02 gegengeprüft.

---

## 1. Vorgehen

Getestete Behauptung (**Claim C**): *Der Heartbeat hat KEINEN Mechanismus, der einen
anhaltenden kognitiven/Provider-Kollaps an ein beobachtbares Run-Ergebnis propagiert —
kein Exit-Status, kein fehlschlagender Check, kein Alert, kein von einem Gate/Menschen
konsumiertes Health-Flag, kein separater Monitoring-Workflow.* Ziel war, C zu **kippen**.

## 2. Ergebnis: kein Gegenbeweis

- **Workflows:** `self-heal.yml:20–24` triggert nur auf Workflow `"CI"`, nicht auf den
  Heartbeat. `ci.yml:5–9` läuft nur auf push/PR, liest keinen Heartbeat-State.
  `post-merge.yml`, `publish*.yml`: kein Health-Reader, kein Alert. → kein Gegenbeweis.
- **Tests:** `test_agent.py:677` prüft nur ein internes `ERROR`-**Event** bei Erschöpfung;
  kein Test prüft Exit-Status oder Run-Ausgang. → kein Gegenbeweis.

Claim C **hält** — jetzt belegt, nicht nur behauptet.

## 3. Die Umkehrung (was der Angriff aufdeckte)

Der Versuch, C zu widerlegen, hat das Gegenteil des naiven Bildes gezeigt: **Das Problem
ist nicht fehlende Erkennung — die Erkennung ist überreichlich gebaut.** Provider-Kollaps
wird sehr wohl gemessen:

- `vedana.py:78` `_W_PROVIDER = 0.35` (höchstes Gewicht; Kommentar Z.74: *„Provider health
  is most critical — no provider = agent is dead"*), `vedana.py:115`
  `p_health = provider_alive / max(provider_total, 1)`. 0 lebende Provider → Puls sinkt.
- `dharma.py:56` `if v.health < 0.3: ctx.health_anomaly = True`.

Der Kollaps erzeugt also ein Health-Anomalie-Signal. **Aber jeder Aktuator dieses Signals
zeigt nach INNEN oder ist verwaist** — nichts zeigt nach außen. Das ist exakt „alles
gebaut, nichts verdrahtet", nur präzise lokalisiert.

## 4. Verwaiste / nur-nach-innen verdrahtete Signale (belegt)

| Signal | Erzeugt in | Aktuator / Leser | Nach außen sichtbar? |
|---|---|---|---|
| `health_anomaly`-Flag | `dharma.py:56` | nur `engine.py:310` — kappt Tool-Runden + spielt LLM-Guidance ein | **nein** |
| `AGENT_ERROR`-Signal | `agent_bus.py:180` (SignalBus) | **kein In-Repo-Subscriber** | **nein** |
| `federation_health.json` / `steward_health.json` | `moksha_health.py:39` | **kein Code-Leser** (nur Docs referenzieren) | **nein** |
| Feld im Health-Report | `moksha_health.py:62` — `peers/immune/gateway` | — | **kein Provider-/Kognitions-Feld überhaupt** |

Die reichste Erkennung (`vedana` Provider-Puls) landet im Health-Report **gar nicht**, und
die Flags, die sie setzt, verpuffen nach innen.

## 5. Wiederverwendbares Muster (grep-before-build)

`dharma.py:187–214` erzeugt bei erschöpfter Diagnose bereits ein **GitHub-Issue** (Label
`federation-health`) — aber **scoped auf nicht-responsive Föderations-PEERS**, nicht auf den
eigenen Provider-/Kognitions-Kollaps des Stewards. Das ist ein *vorhandenes* Außensignal-
Muster, das sich für Selbst-Kollaps wiederverwenden ließe, statt neu zu bauen.

## 6. Korrigierte Fix-Richtung (wichtig — ändert RECON_01)

RECON_01 klang nach „der Heartbeat schluckt, also lass ihn rot werden". Der adversariale
Pass korrigiert das:

- Das Schlucken auf Workflow-Ebene ist **plausibel bewusste Resilienz** (ein Daemon soll
  bei transientem Provider-429 nicht sterben). Ein naives `raise` wäre falsch.
- Der eigentliche Defekt ist die **fehlende Aussenverdrahtung einer bereits vorhandenen
  Erkennung.** Zielrichtung daher: das vorhandene `vedana`/`health_anomaly`-Signal bei
  **anhaltendem** Kollaps nach außen sichtbar machen — zuerst als Feld im Health-Report +
  Log, dann optional Gate/Alert über das vorhandene `dharma`-Issue-Muster. **LOGGING
  zuerst**, kein erzwungenes Rot vor Beobachtung.

## 7. Offen (unverändert)

- Zyklus-übergreifende Persistenz des Kollaps-Zustands (anhaltend vs. transient) — welcher
  Zustand hält das über Zyklusgrenzen? (`chamber.stats()` / `_total_failures`.)
- „extern/Post-Action"-Klasse (MOKSHA-Push) noch nicht zerlegt.

## 8. Gate-Wirkung

Recon deutlich gestärkt und korrigiert, aber nicht abgeschlossen (§7 offen). Kein Feature-
Spec-, Implementierungs- oder Aktivierungs-Gate freigegeben. Kein Produktcode berührt.
