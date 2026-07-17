# HEARTBEAT-FEHLERPROPAGATION — RECON 02: NONE-KONSUM, FEHLERKLASSEN, ANDOCKPUNKT

> **Status:** EVIDENCE PARTIAL — KONSUM UND KLASSIFIKATION BELEGT; SPEC NOCH NICHT FÄLLIG
> **Datum:** 2026-07-17
> **Code-Basis:** `kimeisele/steward@bf2fba2075a87463fc8e333f8f57d805fce4d030`
> **Scope:** Read-only Recon der offenen Punkte aus RECON_01 §8; keine Code-Änderung
> **Verifikation:** `engine.py:305–369` von Opus direkt gelesen; übrige Anker per Sub-Agent
> (Explore, verbatim) geholt und gegen RECON_01 gegengeprüft.

---

## 1. Fragen (aus RECON_01 §8)

Wo wird `None` aus der Kaskade konsumiert? Welche Fehlerklassen unterscheidet der Code
bereits? Wo ist die richtige Kritisch-Grenze? Existiert ein Andockpunkt statt Neubau?

## 2. None-Konsum — belegt (Präzisierung von RECON_01 L1)

Der Provider wandert in die `AgentLoop` (`agent.py:427–428`), gespeichert in
`loop/engine.py:164`. `.invoke()` wird in `engine.py:805` gerufen. Der Rückgabewert `None`
wird **nicht still verworfen**, sondern als Event ausgegeben (`engine.py:352–365`):

```python
if response is None:
    diag = "LLM returned no response"
    if isinstance(self._provider, ChamberProvider):
        ...
        diag = f"All providers failed ({n_fail} failures / {n_total} calls)"
    yield AgentEvent(type=EventType.ERROR, content=diag)
    return
```

**Präzisierung:** RECON_01 zeigte `return None` in der Kaskade als „geschluckt". Genauer: der
Kollaps wird eine Ebene höher als **`EventType.ERROR`-Event sichtbar gemacht** — aber der
Loop `return`t danach normal (kein `raise`). Das Signal existiert also als Event; die
Verdrahtung zum Run-Exit-Status fehlt weiterhin. Es ist „sichtbar-als-Event, nicht
verkabelt", nicht „komplett stumm". Fünfter Surfacing-Punkt, gleiches Muster.

## 3. Fehlerklassen — der Code klassifiziert bereits (grep-before-build)

Eine transient/non-transient-Unterscheidung existiert schon in der Kaskade:

- `_is_transient(e)` — `chamber.py:85–88`; Transient-Tabelle `chamber.py:47–61`.
- Retry-Klassifikation `chamber.py:289–303`:
```python
except Exception as e:
    last_error = e
    if attempt < _MAX_RETRIES and _is_transient(e):
        continue
    break  # non-transient or retries exhausted → next provider
```
- `QuotaExceededError` (import `chamber.py:30`) → `return None` bei `chamber.py:236–238`.

Heißt: die *degradierbar*-Achse (transient, Fallback greift) ist bereits im Code angelegt.
Was fehlt, ist die *kritisch*-Achse und ihre Propagation.

## 4. Granularität — die Kritisch-Grenze ist im Code lokalisierbar

`invoke()` iteriert über die lebenden Cells (`chamber.py:242 for cell in alive:`).
- Einzel-Provider-Ausfall → `continue` (`chamber.py:316`), nächster Provider.
- **Total-Kaskade erschöpft** → `chamber.py:318–325` (`logger.error("ALL providers
  exhausted…")` + `return None`).

Die natürliche Kritisch-Grenze ist also **nicht** der Einzelausfall (der ist per Design
degradierbar), sondern **Total-Erschöpfung** — und schärfer: Total-Erschöpfung, die über
einen ganzen Zyklus anhält. Der Einzelausfall darf grün bleiben; der anhaltende Kollaps
nicht.

## 5. Andockpunkt — existiert, kein Neubau nötig

Es gibt bereits einen Erkennungs→Verhalten-Kanal für Gesundheit:

- SET: `hooks/dharma.py:57` `ctx.health_anomaly = True`; zurückgelesen `agent.py:790–793`;
  Cetana direkt `agent.py:838`. Feld: `phase_hook.py:52–53`.
- KONSUM (einziger): `engine.py:310–323` — verwendet `health_anomaly` **ausschließlich**,
  um `max_rounds` zu kappen und dem LLM eine USER-Guidance („finish immediately")
  einzuspielen.

**Belegt (von Opus gelesen):** dieser Kanal beeinflusst **nicht** den Exit-Status, `raise`t
nicht, ändert das Run-Ergebnis nicht. Also: der Detektions-Kanal ist vorhanden und verdrahtet
— aber sein Verhalten ist „schneller fertigwerden", nicht „Run rot". Er ist der natürliche
Andockpunkt für eine Kritisch-Propagation (erweitern, nicht neu bauen), im LOGGING-Modus
zuerst.

## 6. Zwischenstand Fehlerklassen-Matrix (Entwurf, nicht normativ)

| Klasse | Beispiel (belegt) | Heute | Zielverhalten (Vorschlag, gehört in Feature-Spec) |
|---|---|---|---|
| degradierbar | transienter Ausfall, Fallback greift (`chamber.py:289–303`) | grün, Fallback | grün + gezählt/sichtbar |
| kritisch | Total-Kaskade über Zyklus (`chamber.py:318–325`) | grün (Exit 0) | sichtbar → später rot (erst LOGGING) |
| extern/Post-Action | (noch nicht zerlegt) | — | getrennt geführt |

## 7. Offen / nächster Schritt

- „extern/Post-Action"-Klasse noch nicht zerlegt (Remote-Delivery, `git`-Push im MOKSHA).
- Anhaltend-über-Zyklus messbar machen: welcher Zustand hält den Kollaps über
  Zyklusgrenzen fest? (`chamber.stats()`/`_total_failures` als Kandidat.)
- Danach — und erst dann — ist die Feature-Spec fällig: kleinster Eingriff am belegten
  Andockpunkt (§5), LOGGING zuerst.

## 8. Gate-Wirkung

Recon weit fortgeschritten, aber nicht abgeschlossen. Kein Implementierungs- oder
Aktivierungs-Gate freigegeben. Kein Produktcode berührt.
