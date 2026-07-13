# PHANTOM-HERZSCHLAG-FIX — SPEZIFIKATION (TTL beim Empfang)

> **Ziel:** Der Steward verwirft abgelaufene Nadi-Nachrichten beim Empfang, statt sie
> als frische Herzschläge zu verbuchen. Behebt den Phantom-Herzschlag (§44-46): tote
> Knoten erscheinen durch nachhallende alte Nachrichten als lebendig, was die gesamte
> Heilkette blockiert (Healer heilt nur suspect/dead Peers, §45b).
> **Prinzip:** Zero-Trust-Empfänger — der Steward prüft die LEBENDIGKEIT (Aktualität)
> der Nachricht selbst, nicht nur die ECHTHEIT (Signatur). Kims Zwei-Achsen (§46c).

---

## 0. KONTEXT (verifiziert, §46/§47)
- Bug-Ort: `steward/hooks/dharma.py`, Heartbeat-Schleife (~Z.358-408), konkret NACH der
  Signaturprüfung (~Z.404), VOR `reaper.record_heartbeat(...)` (Z.405).
- Das TTL-Werkzeug existiert im System (nadi_kit is_expired), wird aber im direkten
  Datei-Empfang von dharma.py NICHT genutzt.
- Felder in echten Nachrichten: `timestamp` (Unix float) meist vorhanden, `ttl_s`
  (float) meist vorhanden — aber NICHT immer (3 heartbeat ohne ttl_s, 2 agent_claim
  ohne timestamp). agent_claim läuft in SEPARATER Schleife (Z.354-356) — NICHT anfassen.

---

## 1. PRE-FLIGHT (nur lesen, kein Code)

| # | Check | Erwartung | Wenn anders |
|---|---|---|---|
| P1 | `git branch --show-current` | sauberer Branch von main | Branch anlegen |
| P2 | dharma.py Z.358-408 nochmal ansehen: exakte Zeile von record_heartbeat + die Variable der aktuellen msg | `msg`-Dict, `record_heartbeat(agent_id=peer_id, source="nadi_inbox")` | an Realität anpassen |
| P3 | Haben ALLE Nachrichten in der Heartbeat-Schleife (op != federation.agent_claim) ein `timestamp`? Prüfe an der echten Inbox: gibt es heartbeat/city_report/etc. OHNE timestamp? | timestamp im Heartbeat-Pfad quasi immer da | wenn viele ohne timestamp: Default-Politik überdenken |
| P4 | Existiert ein bestehender Default-TTL/max-TTL-Wert im Code, den wir wiederverwenden können? `grep -rn "7200\|ttl_s\|DEFAULT_TTL\|MAX_TTL" steward/` | ein Wert wie 7200 (2h) existiert | eigene Konstante definieren |

---

## 2. DER EINGRIFF (dharma.py, Heartbeat-Schleife)

### 2a. TTL-Check nach Signaturprüfung, vor record_heartbeat
```python
import time  # falls nicht schon importiert

# Konstante (oben im Modul oder aus vorhandener Config):
DEFAULT_MESSAGE_TTL_S = 7200.0  # 2h — Default wenn ttl_s fehlt (= vorhandenes max)

# ... in der Heartbeat-Schleife, NACH Signaturvalidierung, VOR record_heartbeat: ...
    ts = msg.get("timestamp")
    if ts is None:
        # Kein Zeitstempel → Alter nicht bestimmbar → fail-closed (Phantom-Schutz)
        logger.debug("FEDERATION: skip heartbeat from %s — no timestamp", peer_id)
        continue
    ttl = msg.get("ttl_s", DEFAULT_MESSAGE_TTL_S)
    age = time.time() - float(ts)
    if age > float(ttl):
        logger.debug(
            "FEDERATION: skip EXPIRED heartbeat from %s (age %.0fs > ttl %.0fs)",
            peer_id, age, ttl,
        )
        continue

    reaper.record_heartbeat(agent_id=peer_id, source="nadi_inbox")  # unverändert
```

### 2b. Bewusst NICHT anfassen
- Die `federation.agent_claim`-Schleife (Z.354-356) — anderer Nachrichtentyp, andere
  Semantik. Der Fix betrifft NUR den Heartbeat-Pfad, der `record_heartbeat` aufruft.
- Die Signaturprüfung — bleibt wie sie ist (Echtheit UND Aktualität sind zwei getrennte
  Prüfungen; wir ergänzen die zweite, ersetzen nicht die erste).

---

## 3. SICHERHEITS-LOGIK (warum genau so)
- **Alter über `timestamp`, nicht Vorhandensein von `ttl_s`:** Eine März-Nachricht ist
  auch ohne ttl_s klar abgelaufen (age >> Default). Ein frischer Heartbeat ohne ttl_s
  (age « Default) wird korrekt akzeptiert. (§47c)
- **Fehlt `timestamp` → fail-closed (skip):** genau die Unsterblichkeits-Lücke; ohne
  Zeitstempel kein Alter, also kein Vertrauen. Lehre aus dem fail-open-Fehler (§18b/§47b).
- **Default-TTL großzügig (2h):** verwirft keine legitimen frischen Nachrichten, fängt
  aber alte Phantome (Tage/Monate) sicher.

---

## 4. TESTS (echte Objekte, KEIN MagicMock — WIRKUNG prüfen)
Neue Klasse `TestFederationInboxTTLFilter` in `tests/test_federation.py` (oder wo die
dharma-Inbox-Verarbeitung testbar ist — P-Check). Nutzt einen echten Reaper (oder
hauseigenen Fake mit record_heartbeat), KEIN MagicMock auf eigene Objekte.

1. `test_expired_heartbeat_not_recorded` (WIRKUNG, der Kern): Nachricht mit altem
   `timestamp` (z.B. now - 100000) und `ttl_s: 900` → nach Inbox-Verarbeitung wurde
   `record_heartbeat` für diesen Peer NICHT aufgerufen / last_seen NICHT aktualisiert.
2. `test_fresh_heartbeat_recorded` (Regression): Nachricht mit frischem `timestamp`
   (now) → `record_heartbeat` WIRD aufgerufen.
3. `test_missing_ttl_uses_default` : frischer `timestamp`, KEIN `ttl_s` → akzeptiert
   (Default greift, age < 7200). Alter `timestamp`, kein `ttl_s` → verworfen.
4. `test_missing_timestamp_skipped` (fail-closed): Nachricht ohne `timestamp` im
   Heartbeat-Pfad → NICHT verbucht.
5. `test_agent_claim_unaffected` (Isolation): eine federation.agent_claim-Nachricht
   (andere Schleife) wird vom TTL-Filter NICHT berührt / weiterhin normal verarbeitet.

> Der Test darf NICHT nur prüfen, dass die Funktion durchläuft, sondern ob
> `record_heartbeat` für den Phantom-Peer AUSBLEIBT — das ist die Wirkung, die den Bug
> behebt. Ein grüner Test ohne diese Prüfung wäre ein Placebo.

---

## 5. WAS DIESER FIX BEWUSST NICHT TUT
- Er repariert NICHT den Hub (der abgelaufene Nachrichten weiterhin vorhält). Zero-Trust:
  der Empfänger schützt sich selbst. Hub-GC ist ein separater, späterer Schritt (§45d).
- Er ändert NICHT die Reaper-Logik selbst (die ist korrekt — sie bekam nur vergiftete
  Daten).
- Er baut NOCH NICHT die qualitative Verfassungs-Achse (§40) — das ist die große
  künftige Reifung. Dieser Fix stellt nur die Vitalzeichen-Achse WAHR (echter Puls statt
  Echo).

---

## 6. ERWARTETE WIRKUNG
Nach dem Fix verwirft der Steward abgelaufene Nachrichten. steward-test (dessen letzte
echte Aktivität Juni war) wird NICHT mehr durch März-Phantome am Leben gehalten → beim
nächsten Steward-Lauf sieht der Reaper es als überfällig → SUSPECT. Damit wird die
Heilkette (Reaper→Kirtan→Healer→PR) erstmals AUSLÖSBAR — und das ursprüngliche
Heil-Experiment (§43) wird durchführbar. Der Steward beginnt, Echo von echtem Leben zu
unterscheiden.

---

*Vor Übergabe: Pre-Flight P2-P4. Nach Bau: Wirkungstests grün (besonders #1), volle
test_federation/test_reaper-Suite grün, kein Commit ohne Freigabe.*
