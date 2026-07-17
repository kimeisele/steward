# HEARTBEAT-FEHLERPROPAGATION — FEATURE-SPEC 01

## Sichtbarmachung anhaltenden kognitiven/Provider-Kollaps

> **Status:** DRAFT 0.2 — SCHNITT A AUSFÜHRBAR SPEZIFIZIERT; NICHT G1; IMPLEMENTIERUNG UND
> AKTIVIERUNG GESPERRT
> **Datum:** 2026-07-17
> **Produktionsbasis:** `kimeisele/steward@bf2fba2075a87463fc8e333f8f57d805fce4d030`
> **Herkunft:** Phase-2 §7.3; Recon RECON_01–04 in `heartbeat_failure_propagation_evidence/`

---

## 1. Zweck und Gate

Anhaltenden kognitiven/Provider-Kollaps beobachtbar machen, ohne die bewusste Resilienz
(Daemon stirbt nicht an transienten Fehlern) zu brechen. LOGGING zuerst; Erzwingen (Run rot)
erst nach belegter Beobachtung und nur hinter Kill-Switch.

DRAFT. Kein G1 ohne adversariales Review (§10) und Operator-Go. **Schnitt A** ist hier so
spezifiziert, dass er ohne Interpretationsspielraum umsetzbar ist. **Schnitt B/C** sind
bewusst datengesteuert gegated (nicht geraten).

## 2. Normative Abhängigkeiten

RECON_01–04 (`heartbeat_failure_propagation_evidence/`). Alle Zeilenanker gelten auf der
Produktionsbasis oben und sind vor Implementierung erneut zu pinnen.

## 3. Gepinnte Fakten (belegt, mit Anker)

- `chamber.stats()` → `chamber.py:423`; liefert `{"providers":[{"name","alive",…}],
  "total_calls":int, "total_failures":int, …}`.
- Chamber ist Service: Klasse `SVC_PROVIDER` `services.py:40`; Registrierung
  `services.py:285` (`ServiceRegistry.register(SVC_PROVIDER, provider)`); Get-Muster wie
  `context_bridge.py:271` (`ServiceRegistry.get(SVC_PROVIDER)`).
- Health-Report-Builder `_build_health_report()` `moksha_health.py:62`; Writer/Execute
  `moksha_health.py:39–59`; Zieldateien `.steward/federation_health.json` und
  `data/federation/steward_health.json` (plain `write_text`, **nicht** atomar).
- Health-Hook registriert: `hooks/__init__.py:66` (`MokshaHealthReportHook`). Läuft pro
  MOKSHA-Zyklus.
- **Kein** Once-per-Run/Shutdown-Phasen-Hook (bestätigt); nur Per-Zyklus-Hooks. Prozess-
  `close()` `agent.py:742` ist kein Phasen-Hook → nicht genutzt. ⇒ Streak-Granularität =
  **pro Zyklus**.
- `.steward/federation_health.json` wird vom Heartbeat committet (`steward-heartbeat.yml:99`
  `git add -u -- .steward/`) ⇒ über Runs persistent.

## 4. Scope und Nicht-Scope

**In Scope (Schnitt A):** ein `cognition`-Block im vorhandenen Health-Report inkl. eines über
Runs persistierten Zyklus-Streak-Zählers. **Kein** Einfluss auf Run-Exit-Status.

**Nicht-Scope:** kein `raise` in `chamber`; keine Änderung der Workflow-`try/except`-
Resilienz; keine Atomicity-Änderung am bestehenden Health-Write (vorbestehend, eigener
Hygiene-Punkt); Context-Bridge/Identität/Rotation/Quarantäne unberührt. Kein Sammelpatch.

## 5. SCHNITT A — AUSFÜHRBARER VERTRAG (Sichtbarkeit)

### 5.1 Kollaps-Prädikat (rein aus `stats()`, kein Delta)
```
pstats = ServiceRegistry.get(SVC_PROVIDER).stats()
providers = pstats["providers"]
alive  = sum(1 for p in providers if p.get("alive"))
total  = len(providers)
collapsed = (total > 0 and alive == 0)
```

### 5.2 Persistierter Zyklus-Streak (Lesen-vor-Überschreiben)
Vor dem Überschreiben den vorherigen Streak aus der bestehenden Zieldatei lesen:
```
prev = 0
try:
    prev = json.loads(Path(".steward/federation_health.json").read_text())\
             .get("cognition", {}).get("consecutive_collapsed_cycles", 0)
except (OSError, ValueError):
    prev = 0
streak = prev + 1 if collapsed else 0
```

### 5.3 Report-Erweiterung
`_build_health_report()` (`moksha_health.py:62`) erhält Signatur
`_build_health_report(prev_streak: int = 0)` und ergänzt vor `return report`:
```
provider = ServiceRegistry.get(SVC_PROVIDER)
report["cognition"] = {"providers_alive": 0, "providers_total": 0,
                       "total_calls": 0, "total_failures": 0,
                       "collapsed": False, "consecutive_collapsed_cycles": prev_streak}
if provider is not None and hasattr(provider, "stats"):
    ps = provider.stats()
    providers = ps.get("providers", [])
    alive = sum(1 for p in providers if p.get("alive"))
    total = len(providers)
    collapsed = (total > 0 and alive == 0)
    report["cognition"] = {
        "providers_alive": alive, "providers_total": total,
        "total_calls": ps.get("total_calls", 0),
        "total_failures": ps.get("total_failures", 0),
        "collapsed": collapsed,
        "consecutive_collapsed_cycles": (prev_streak + 1 if collapsed else 0),
    }
```
`execute()` (`moksha_health.py:39`) liest `prev` (5.2) und ruft
`_build_health_report(prev_streak=prev)`. Writer und Dateien **unverändert**.

### 5.4 Invariante
Schnitt A ändert **keinen** Kontrollfluss außerhalb `moksha_health.py`, wirft nicht, ändert
den Run-Exit-Status in **keinem** Fall. Nur ein zusätzliches Datenfeld.

## 6. SCHNITT A — TESTVERTRAG (exakt, echte Klassen, kein Stub)

Datei `tests/test_moksha_health.py` (neu oder erweitert). Gegen echte `ProviderChamber`
(`build_chamber()`-artig konstruiert), via `ServiceRegistry.register(SVC_PROVIDER, chamber)`.

- `test_cognition_block_present_and_healthy`: 2 lebende Cells → `report["cognition"]`
  existiert; `providers_total == 2`; `providers_alive == 2`; `collapsed is False`;
  `consecutive_collapsed_cycles == 0`.
- `test_collapse_increments_streak`: alle Cells nicht-alive → `collapsed is True`;
  `_build_health_report(prev_streak=3)` ⇒ `consecutive_collapsed_cycles == 4`.
- `test_transient_resets_streak` (**Guard §220.3**): ≥1 lebende Cell, `prev_streak=5`
  ⇒ `collapsed is False`; `consecutive_collapsed_cycles == 0`.
- `test_no_provider_registered`: SVC_PROVIDER nicht registriert ⇒ `cognition`-Block mit
  `providers_total == 0`, `consecutive_collapsed_cycles == prev_streak`; kein Fehler.
- `test_execute_appends_ok_and_returns_none`: `execute(ctx)` gibt `None`, hängt
  `"moksha_health_report:ok"` an `ctx.operations` an, wirft nicht (Invariante 5.4).

## 7. SCHNITT A — AKZEPTANZ (Produktionslog, nicht grüner Test)

Nach einem Heartbeat-Run gilt: `.steward/federation_health.json` enthält den `cognition`-
Block mit den sechs Feldern; bei lebenden Providern `consecutive_collapsed_cycles: 0`; der
Run-Exit-Status ist unverändert grün. Verifikation am realen Artefakt + Run-Log.

## 8. SCHNITT B/C — PRÄZISE GEGATED (nicht geraten)

- **B (Eskalation):** erst nachdem A in Produktion Daten geliefert hat. Wiederverwendung des
  vorhandenen Issue-Musters (`dharma.py:187`, heute Peer-scoped) für Selbst-Kollaps. Eigene
  G2-Spec. Ändert Run-Ausgang **nicht**.
- **C (Erzwingen/Run-rot):** GESPERRT bis (i) A-Beobachtung die Schwelle `N`
  (`consecutive_collapsed_cycles ≥ N`) empirisch begründet und (ii) das Prädikat (5.1)
  ggf. auf „keine erfolgreiche Kognition" verschärft ist. Hinter Feature-Flag/Kill-Switch,
  Default AUS. Eigene G2-Spec + Operator-Go.

## 9. Rollback

Schnitt A: `cognition`-Block + Signaturänderung entfernen. Blast-Radius = ein Datenfeld,
kein Kontrollfluss.

## 10. Offene Fragen

**Geschlossen durch DRAFT 0.2:** Chamber-Erreichbarkeit (SVC_PROVIDER), Persistenz-Ort
(bestehende committete `federation_health.json`), Granularität (pro Zyklus, da kein
Once-per-Run-Hook), Andockstelle (`moksha_health.py`).

**Bewusst offen — datengesteuert, NICHT vor Beobachtung entscheidbar (Angriffsfläche fürs
Review):**
1. Schwelle `N` für „kritisch" — muss aus A-Produktionsdaten kommen, darf nicht geraten
   werden. Sperrt C.
2. Prädikat-Verschärfung „alive==0" → „keine erfolgreiche Kognition im Zyklus" (braucht
   Zyklus-Delta von `total_calls`/`total_failures`) — für C, nicht für A.
3. Nicht-Atomicity des bestehenden Health-Writes (`write_text`) — vorbestehend; als eigener
   Hygiene-Punkt zu führen, nicht in dieser Feature.

## 11. Schlussstatus

DRAFT 0.2. Schnitt A ausführbar; B/C korrekt gegated. Kein G1, keine Implementierung, keine
Aktivierung ohne adversariales Review von §5/§8/§10 und Operator-Go.
