# HEARTBEAT-FEHLERPROPAGATION — FEATURE-SPEC 01

## Sichtbarmachung anhaltenden kognitiven/Provider-Kollaps

> **Status:** DRAFT 0.5 — SCHNITT A AUSFÜHRBAR; DREI ADVERSARIAL-REVIEW-RUNDEN EINGEARBEITET
> (invertiertes Prädikat + Skip-Kollaps-Blindfleck); NICHT G1; IMPLEMENTIERUNG UND
> AKTIVIERUNG GESPERRT
> **Datum:** 2026-07-17
> **Produktionsbasis:** `kimeisele/steward@bf2fba2075a87463fc8e333f8f57d805fce4d030`
> **Herkunft:** Phase-2 §7.3; Recon RECON_01–04; adversariales Review (§12)

---

## 1. Zweck und Gate

Anhaltenden kognitiven/Provider-Kollaps beobachtbar machen, ohne die bewusste Resilienz zu
brechen. LOGGING zuerst; Erzwingen (Run rot) erst nach belegter Beobachtung, nur hinter
Kill-Switch. DRAFT — kein G1 ohne Auflösung der offenen Blocker (§12) und Operator-Go.
**Schnitt A** ist ohne Interpretationsspielraum spezifiziert; **B/C** sind datengesteuert
gegated.

## 2. Normative Abhängigkeiten

RECON_01–04 (`heartbeat_failure_propagation_evidence/`). Alle Zeilenanker gelten auf der
Produktionsbasis oben und sind vor Implementierung erneut zu pinnen.

## 3. Gepinnte Fakten (belegt, mit Anker)

- `chamber.stats()` → `chamber.py:423`; liefert `{"providers":[{"name","alive",…}],
  "total_calls":int, "total_failures":int, …}`. `total_calls`/`total_failures` sind
  prozess-monoton (nur bei frischem Prozess auf 0; `_maybe_reset_daily` `chamber.py:522`
  setzt sie **nicht** zurück).
- **Zählsemantik (gepinnt — jedes Delta-Prädikat hängt daran):** `_total_calls += 1` steht
  **ausschließlich** in `_record_call_success` (`chamber.py:471`) ⇒ `total_calls` = Anzahl
  **gelungener** Invokes, NICHT Versuche. `_total_failures += 1` steht in
  `_record_call_failure` (`chamber.py:495`) und feuert **pro totem Provider** ⇒ ein einzelner
  `invoke()` kann `total_failures` um mehrere erhöhen. Ein toter Provider vor einem guten =
  gesunder Fallback erzeugt Erfolg **und** Failures.
- Chamber ist Service: `SVC_PROVIDER` `services.py:40`; Registrierung `services.py:285`;
  Get-Muster `context_bridge.py:271`.
- Health-Builder `_build_health_report()` `moksha_health.py:62`; Writer `moksha_health.py:
  39–59`; Dateien `.steward/federation_health.json` + `data/federation/steward_health.json`
  (plain `write_text`, **nicht atomar**). Beide git-tracked, per `steward-heartbeat.yml:99`
  committet ⇒ über Runs persistent (unabhängig verifiziert im Review §12).
- Health-Hook registriert `hooks/__init__.py:66`; läuft pro MOKSHA-Zyklus.
- **Kein** Once-per-Run-Hook (bestätigt) ⇒ Streak-Granularität = **pro Zyklus**.
- Erkennung existiert: `vedana.py:78` (`_W_PROVIDER=0.35`, höchstes Gewicht) →
  `dharma.py:56–57` (`health<0.3` → `health_anomaly`); Konsum nur `engine.py:310`.

## 4. Scope und Nicht-Scope

**In Scope (Schnitt A):** ein `cognition`-Instrument-Block im vorhandenen Health-Report, der
sowohl Hard-Down als auch **Degradation** (Zyklus-Delta) misst und über Runs persistiert.
Kein Einfluss auf Run-Exit-Status.

**Nicht-Scope:** kein `raise` in `chamber`; keine Änderung der Workflow-`try/except`-
Resilienz; Context-Bridge/Identität/Rotation/Quarantäne unberührt. Kein Sammelpatch. Die
Atomicity des Health-Writes wird in A nicht geändert, ist aber **C-Blocker** (§8).

## 5. SCHNITT A — AUSFÜHRBARER VERTRAG (Instrument, nicht nur Hard-Down)

> **Behebt Review-Befund 1:** A misst nicht nur `alive==0`, sondern die real beobachtete
> Degradation (Zyklus lief, keine Kognition gelang). Nur so entstehen die Daten, die C's
> Schwelle begründen sollen.

### 5.1 Beobachtete Rohgrößen (illustrativ; **normativ ist allein §5.3**)
Pro MOKSHA-Zyklus aus `stats()`: `providers_alive`, `providers_total`, `total_calls`,
`total_failures`. Abgeleitet über den Zyklus-Delta zum vorigen Report: `calls_delta`,
`fail_delta`. Zwei Zustände:
- `hard_down` = `providers_total>0 and providers_alive==0` (Total-Ausfall, Momentwert).
- `degraded` = `calls_delta==0 and fail_delta>0` (Failures traten auf, **kein** Erfolg im
  Zyklus — weil `total_calls` laut §3 nur Erfolge zählt) — das Krankheitsbild aus RECON_01
  §4. **Gesunder Fallback (`calls_delta>0`) bleibt bewusst grün**, egal wie viele Failures
  ein toter Vorgänger-Provider erzeugt.

- `skip_collapse` = `providers_usable==0` (alle Provider **übersprungen** statt versucht:
  Quota erschöpft `chamber.py:244`, Breaker OPEN `:251`, Membran zu schwach `:255` — jeweils
  `continue` **ohne** `_record_call_failure`, also `fd=0`). `providers_usable` = pro Provider
  `alive AND breaker≠OPEN AND within_quota`, ableitbar aus `stats()` (Felder `alive`,
  `breaker`, chamber-`quota`). Fängt das schwerste Krankheitsbild — Quota-Erschöpfung über
  einen Tag (RECON_04) und den vertieften Breaker-Steady-State —, das `degraded` (braucht
  `fd>0`) systematisch verfehlt.

**Partial-Failure bleibt bewusst grün:** ein Zyklus mit ≥1 gelungenem Invoke (`cd>0`) gilt
als gesund, egal wie viele Failures ein toter Vorgänger-Provider erzeugt. Das ist die
Auflösungsgrenze, die der C-Prädikat-Designer kennen muss.

`collapsed = hard_down or degraded or skip_collapse` treibt **einen** Streak.

### 5.2 Lesen-vor-Überschreiben (**nur Extraktion**, kein Rechnen — Befund 4)
```
prev = {"consecutive_collapsed_cycles": 0, "total_calls": 0, "total_failures": 0}
try:
    _c = json.loads(Path(".steward/federation_health.json").read_text()).get("cognition", {})
    prev["consecutive_collapsed_cycles"] = _c.get("consecutive_collapsed_cycles", 0)
    prev["total_calls"]    = _c.get("total_calls", 0)
    prev["total_failures"] = _c.get("total_failures", 0)
except (OSError, ValueError, TypeError):
    pass   # fehlende/zerrissene Datei ⇒ Defaults (für A tolerierbar; C-Blocker §8)
```
`execute()` übergibt `prev` an den Builder. `execute()` selbst **inkrementiert nicht**.

### 5.3 Report-Erweiterung (**einzige Inkrement-Stelle** — Befund 4, mit None-Guard — Befund 6)
`_build_health_report(prev: dict | None = None)` (`moksha_health.py:62`) ergänzt vor
`return report`:
```
prev = prev or {"consecutive_collapsed_cycles": 0, "total_calls": 0, "total_failures": 0}
cog = {"providers_alive": 0, "providers_total": 0, "providers_usable": 0,
       "total_calls": 0, "total_failures": 0, "calls_delta": 0, "fail_delta": 0,
       "hard_down": False, "degraded": False, "skip_collapse": False,
       "consecutive_collapsed_cycles": prev["consecutive_collapsed_cycles"]}
provider = ServiceRegistry.get(SVC_PROVIDER)
if provider is not None and hasattr(provider, "stats"):
    ps = provider.stats(); providers = ps.get("providers", [])
    alive = sum(1 for p in providers if p.get("alive")); total = len(providers)
    tc = ps.get("total_calls", 0); tf = ps.get("total_failures", 0)
    # Run-Grenze: frischer Prozess setzt Totals auf 0 -> Delta = aktuelle Totals
    if tc >= prev["total_calls"]:
        cd = tc - prev["total_calls"]; fd = tf - prev["total_failures"]
    else:
        cd = tc; fd = tf
    hard_down = (total > 0 and alive == 0)
    degraded  = (cd == 0 and fd > 0)   # Failures, aber kein Erfolg im Zyklus (§3-Semantik)
    # providers_usable: alive UND breaker≠OPEN UND within_quota. Die exakte Dekodierung von
    # p['breaker'] und ps['quota'] ist an vibe_core get_status() zu PINNEN (§10.4) — NICHT raten.
    usable = sum(1 for p in providers
                 if p.get("alive") and _breaker_ok(p.get("breaker")) and _quota_ok(ps.get("quota")))
    skip_collapse = (total > 0 and usable == 0)
    collapsed = hard_down or degraded or skip_collapse
    cog.update({"providers_alive": alive, "providers_total": total,
                "providers_usable": usable,
                "total_calls": tc, "total_failures": tf,
                "calls_delta": cd, "fail_delta": fd,
                "hard_down": hard_down, "degraded": degraded,
                "skip_collapse": skip_collapse,
                "consecutive_collapsed_cycles":
                    prev["consecutive_collapsed_cycles"] + 1 if collapsed else 0})
report["cognition"] = cog
```

### 5.4 Invariante
Schnitt A ändert **keinen** Kontrollfluss außerhalb `moksha_health.py`, wirft nicht (der
`get(SVC_PROVIDER)`-None-Fall ist geführt), ändert den Run-Exit-Status in **keinem** Fall.

## 6. SCHNITT A — TESTVERTRAG (exakt, echte Klassen; inkl. Disk-Roundtrip — Befund 3)

Datei `tests/test_moksha_health.py`. Gegen echte `ProviderChamber`, via
`ServiceRegistry.register(SVC_PROVIDER, chamber)`. Dateibasierte Tests nutzen ein `tmp_path`
als cwd.

Builder-Ebene:
- `test_cognition_block_healthy`: 2 lebende Cells, `prev` leer → `providers_alive==2`,
  `hard_down False`, `degraded False`, `consecutive_collapsed_cycles==0`.
- `test_hard_down_increments`: alle Cells nicht-alive, `prev.streak=3` → `hard_down True`,
  `consecutive_collapsed_cycles==4`.
- `test_degraded_increments` (**Befund 1**): Cells alive, Totals so gesetzt, dass
  `calls_delta==0 and fail_delta>0` (Failures ohne Erfolg im Zyklus) → `degraded True`,
  Streak +1 — obwohl `hard_down False`.
- `test_healthy_fallback_stays_green` (**Befund 1b — False-Positive-Guard, Runde 2**):
  gesunder Fallback, `calls_delta>0 and fail_delta>0` (toter Vorgänger-Provider) →
  `degraded False`, `consecutive_collapsed_cycles==0` trotz `prev.streak=5`. Fängt die
  invertierte Prädikat-Version ab.
- `test_transient_resets` (**Guard §220.3**): ≥1 Erfolg im Zyklus (`calls_delta>0`)
  → `collapsed False`, `consecutive_collapsed_cycles==0` trotz `prev.streak=5`.
- `test_no_provider_registered`: SVC_PROVIDER fehlt → Block mit `providers_total==0`,
  Streak == `prev.streak`; kein Fehler.
- `test_skip_collapse_quota` (**Runde 3**): alle Provider im Skip-Zustand (über Quota bzw.
  Breaker OPEN, via passend geformtem `breaker`/`quota`-Status), `cd==0, fd==0`, aber
  `providers_usable==0` → `skip_collapse True`, Streak +1. Fängt den Quota-/Breaker-
  Blindfleck, den `degraded` allein verfehlt.

Disk-Roundtrip-Ebene (**das eigentliche Novum — Befund 3**):
- `test_roundtrip_increment`: Datei mit `cognition.consecutive_collapsed_cycles=N` +
  passenden Totals schreiben → `execute()` bei Kollaps → **Datei zeigt `N+1`**.
- `test_roundtrip_missing_and_torn`: Datei fehlt / enthält torn JSON / hat keinen
  `cognition`-Key → `prev`-Defaults, kein Crash, Run-Ausgang unverändert.
- `test_execute_appends_ok_and_returns_none`: `execute(ctx)` gibt `None`, hängt
  `"moksha_health_report:ok"` an, wirft nicht.

## 7. SCHNITT A — AKZEPTANZ (Produktionslog, nicht grüner Test)

Nach einem Heartbeat-Run enthält `.steward/federation_health.json` den `cognition`-Block mit
allen Feldern (inkl. `calls_delta`/`fail_delta`/`degraded`); bei gesunder Kognition
`consecutive_collapsed_cycles: 0`; Run-Exit-Status unverändert grün. Verifikation am realen
Artefakt über mehrere aufeinanderfolgende Runs (Streak-Verhalten sichtbar).

## 8. SCHNITT B/C — PRÄZISE GEGATED

- **B (Eskalation):** erst nach A-Produktionsdaten. Wiederverwendung `dharma.py:187`
  (Peer-Muster) für Selbst-Kollaps. Eigene G2-Spec. Kein Run-Rot.
- **C (Erzwingen/Run-rot):** GESPERRT bis **alle drei**:
  (i) A-Beobachtung begründet die Schwelle `N` empirisch (§10.1, Einheit Zyklen);
  (ii) Prädikat für C entschieden (Hard-Down vs. Degradation vs. Kombination);
  (iii) **Atomarer Persistenz-Write** hergestellt (Befund 2) — eine Rot-Schwelle darf nicht
  auf einem Zähler ruhen, dessen Datei genau bei Crash/Unhealth still auf 0 resettet.
  Hinter Feature-Flag/Kill-Switch, Default AUS. Eigene G2-Spec + Operator-Go.

## 9. Rollback

Schnitt A: `cognition`-Block + Signaturänderung entfernen. Blast-Radius = ein Datenfeld,
kein Kontrollfluss.

## 10. Offene Fragen

**Geschlossen (DRAFT 0.2/0.3):** Chamber-Erreichbarkeit, Persistenz-Ort, Granularität,
Andockstelle, Degradations-Messung (Befund 1), Inkrement-Eindeutigkeit (Befund 4),
None-Guard (Befund 6).

**Bewusst offen — datengesteuert:**
1. **Schwelle `N` — Einheit ist Zyklen** (Befund 5): ein Run addiert bis zu `CYCLES`
   (Default 4) Zyklen; `N` muss run-sprung-bewusst definiert werden (z. B. „≥N kollabierte
   Zyklen über ≥M aufeinanderfolgende Runs"), nicht naiv als „N Runs". Aus A-Daten.
2. Prädikat-Wahl für C (Hard-Down / Degradation / kombiniert) — aus A-Daten.
3. Atomicity des Health-Writes — **jetzt als C-Blocker (iii) §8 verdrahtet** (Befund 2), nicht
   mehr nur „separate Hygiene".
4. **vibe_core-Statusformen pinnen (Runde 3):** die exakte Dekodierung von `p['breaker']`
   (get_status → wann OPEN), `ps['quota']` (wann erschöpft) und `MahaCellUnified.is_alive`
   liegt in `vibe_core` (hier nicht installiert). `providers_usable`/`skip_collapse` und der
   `hard_down`-Backstop hängen daran — vor Implementierung gegen die echten Formen pinnen,
   **nicht raten** (das war die Fehlerklasse der Runden 2/3). Die Helfer `_breaker_ok`/
   `_quota_ok` in §5.3 sind Platzhalter für genau diese Dekodierung.

## 11. Schlussstatus

DRAFT 0.5. Schnitt A misst Hard-Down, Degradation UND Skip-Kollaps; B/C korrekt gegated.
Einzige tragende ungeprüfte Annahme: die vibe_core-Statusformen (§10.4). Kein G1, keine
Implementierung, keine Aktivierung ohne erneutes Review von §5/§6/§8 und Operator-Go.

## 12. Review-Historie

- **Adversariales Design-Review (2026-07-17):** 6 Befunde. Fakten-Fundament unabhängig
  bestätigt (Anker, `stats()`-Form, `SVC_PROVIDER`, git-tracked Persistenz). Design-Befunde:
  1 (HIGH, A maß nur Hard-Down statt Degradation) → §5 neu; 2 (HIGH, Non-Atomicity als
  C-Blocker) → §8(iii)/§10.3; 3 (HIGH, Roundtrip ungetestet) → §6 Roundtrip-Tests; 4 (MED,
  Doppel-Inkrement) → §5.2 nur Extraktion, §5.3 einzige Inkrement-Stelle; 5 (MED, Einheiten)
  → §10.1; 6 (LOW, §5.1 vs §5.3 normativ) → §5.1 als illustrativ markiert. G1 blieb korrekt
  verwehrt.
- **Zweite Runde (2026-07-17, Review von DRAFT 0.3):** 1 neuer HIGH-Befund — der Fix für
  Befund 1 hatte ein **invertiertes** `degraded`-Prädikat eingebaut. Am Code verifiziert:
  `total_calls` zählt nur Erfolge (`chamber.py:471`), `total_failures` pro totem Provider
  (`chamber.py:495`). Das alte `cd>0 and fd>=cd` hätte auf gesundem Fallback
  (Groq-tot→Gemini-ok: `cd=1,fd=1` je Zyklus) **Dauerfehlalarm** erzeugt und das reale
  Krankheitsbild (`cd==0`) verfehlt. Fix: §3 pinnt jetzt die Zählsemantik; §5 Prädikat
  korrigiert auf `cd==0 and fd>0`; §6 neuer `test_healthy_fallback_stays_green`. Die 5
  handwerklich sauberen Befunde (2,3,4,5,6) wurden bestätigt. G1 weiterhin verwehrt.
- **Dritte Runde (2026-07-17, Review von DRAFT 0.4):** 1 neuer HIGH-Befund — `degraded`
  (`cd==0 and fd>0`) ist blind für **Skip-Kollaps**: die `continue`-Pfade Quota
  (`chamber.py:244`), Breaker OPEN (`:251`), Membran (`:255`) überspringen Provider **ohne**
  `_record_call_failure` → `fd=0`. Universeller Skip (v. a. Quota-Erschöpfung über einen Tag,
  das RECON_04-Krankheitsbild) las sich gesund; `hard_down` fängt es nicht, weil Breaker/Quota
  `is_alive` nicht anfassen. Am Code verifiziert (Skip-Pfade, Breaker/Lifecycle-Trennung).
  Fix: neuer Zustand `skip_collapse = providers_usable==0` (§5); Test `test_skip_collapse_quota`
  (§6); vibe_core-Statusformen als Pin-Pflicht §10.4. `is_alive` bleibt die einzige
  ungeprüfte tragende Annahme (vibe_core nicht installiert). G1 weiterhin verwehrt.
