# STEWARD_BLUEPRINT.md — SKELETT (Phase 2, Entwurf zur Kritik)

> **Status:** SKELETT — nur Struktur, noch KEINE verbindliche Detailspezifikation.
> Zweck: Gerüst, das Kim + Opus + Gemini-Pro kritisieren, BEVOR Token in
> Detailarbeit fließen. Erst wenn das Skelett steht, füllen wir Kapitel für Kapitel.
> 
> **Gegründet auf:** `PHASE1_BEFUND_steward.md` (verifizierte Faktenlage) +
> `PHILOSOPHISCHER_SCHLUESSEL.md` (Mantra-als-Spezifikation, Projektionsmodell).
> 
> **Scope-Disziplin:** Dieses Blueprint rettet den STEWARD und schließt die
> Regelkreise. Es gräbt NICHT die Interna von agent-city um (Blackbox mit
> bekannten Ein-/Ausgängen). Erweiterungen auf Stadt/Föderation folgen erst,
> wenn der Steward sie selbst halten kann.

-----

## Kapitel 0 — ARCHITEKTUR-FUNDAMENT & VERBINDLICHE REGELN

Bevor ein einziger Eingriff spezifiziert wird, gelten diese Regeln für ALLE
folgenden Kapitel:

1. **LAW/REALITY-Regel (verbindlicher Standard):** Jeder Eingriff deklariert
   explizit, ob er `protocols/...` (THE LAW), `substrate/...` (THE REALITY) oder
   BEIDE betrifft. Grund: Die Runtime läuft auf der Substrat-Ebene; ein nur in
   der Protokoll-Ebene gemachter Eingriff zieht im Wirkbetrieb wirkungslos
   vorbei. (Belegt: zwei `will.py`, §7c im Befund.)
1. **Verkabeln, nicht neubauen:** Kein Eingriff erfindet neue kognitive Organe.
   Jeder Eingriff verbindet vorhandene, getestete Bausteine. (Kerndiagnose §7b.)
1. **Mantra-als-Spezifikation:** Jede neue Komponente wird gegen ihre
   schriftgemäße Position geprüft (Projektion, nicht 1:1-Übersetzung —
   PHILOSOPHISCHER_SCHLUESSEL §0). Steward = Stellvertreter, nicht Vishnu;
   kein Eigen-Wille (Ahankara), nur autorisierte Mandate.
1. **Test-Disziplin:** Jeder Eingriff nennt die Tests, die ihn absichern
   (Baseline: ~3800 Tests im Substrat, ~1093 in steward). Kein Merge ohne grün.
1. **Token-Budget-Treue:** Eingriffe sind so spezifiziert, dass die kognitive
   Kaskade (Buddhi-Tiers) gewahrt bleibt — teure Modelle nur an der Spitze.
1. **Embryonales Wachstum (Arbeitsprinzip, Kim):** Dieses Skelett ist bewusst
   ZART — eine Struktur zum Entlangwachsen, kein Betongerüst. Die Kapitel werden
   NICHT eines nach dem anderen bis zur Perfektion ausgebaut, sondern in Runden
   GEMEINSAM gereift (erst grobe Form überall, dann verfeinern). Eine Erkenntnis
   in einem späten Kapitel darf bereits Geschriebenes in einem frühen wieder
   verflüssigen. Nichts wird hart, bevor das Ganze stimmig ist. Grund: organische
   Architektur — Festlegungen in Isolation erzeugen Widersprüche, die zu spät
   auffallen. (Wie ein Embryo: Herz schlägt, während die Wirbelsäule noch
   knorpelig ist; alles wächst gekoppelt.)
1. **Feinstofflich/grobstofflich = LAW/REALITY:** Die formale Ebene (Absicht,
   Schrift, `protocols`) und die ausgeführte Ebene (`substrate`, Runtime) müssen
   SYNCHRON wachsen — sonst verpufft das eine. Operationalisiert durch:

**DUALE VERIFIKATIONSTABELLE (Pflichtformat für jede Detailspezifikation):**

|Schritt|Ziel (Code-Pfad)|LAW (protocols)           |REALITY (substrate)       |Tests (Baseline)   |
|-------|----------------|--------------------------|--------------------------|-------------------|
|Kap. 1 |Resilienz       |steward/autonomy          |steward/autonomy          |tests/immune/ (TBD)|
|Kap. 2 |Membran-Intents |steward/intents           |steward/intent_handlers   |TBD                |
|Kap. 3 |Wille           |protocols/sankalpa/will.py|substrate/sankalpa/will.py|tests/will/ (TBD)  |
|Kap. 4 |Kognitions-Naht |steward/buddhi            |steward/loop/engine       |TBD                |

→ Zwingt bei jedem Eingriff die Synchronisation beider Ebenen. Verhindert den
„Steward-Fehler” (Änderung in LAW, wirkungslos in REALITY). Tabelle wird in der
Detailphase mit exakten Zeilen/Tests gefüllt.

-----

## Kapitel 1 — DAS ANGEBORENE IMMUNSYSTEM (Resilienz-Härtung) ⟵ HÖCHSTE PRIORITÄT

> *Ziel:* Den „stillen Tod” stoppen. Das vorhandene FAILED/Eskalations-Muster
> auf den UNBEKANNT-Fall ausdehnen. (Befund §4j, §4k.)

- **Problem:** `autonomy.py:223-226` — unbekannter Intent → fälschlich
  `COMPLETED`. Maskiert ALLE unbekannten Signale systemweit (nicht nur die zwei
  bekannten Lecks).
- **Eingriff (Skelett, Details folgen):**
  - Unbekannter Intent darf NIE `COMPLETED` werden → stattdessen
    `FAILED`/`SUSPENDED`/Quarantäne (Status-Wahl in Detailphase zu klären).
  - Generische „Entzündungsreaktion”: unspezifische Resilienz-Reaktion auf
    Unbekanntes (Alarm/Log/Quarantäne-Schleife), analog zum angeborenen
    Immunsystem.
  - Wiederverwendung des EXISTIERENDEN Musters (FAILED-Pfad Z. 262-263,
    Hebbian-Eskalation Z. 236-248) — kein Neubau.
- **Warum zuerst:** Fängt gegenwärtige UND zukünftige unentdeckte stille Tode
  auf einmal ab (Kims strategischer Punkt). Schafft das sichere Fundament, auf
  dem Kapitel 2-4 aufsetzen.
- **Schicht:** vermutlich `steward` (autonomy/intents) — TBD in Detailphase.
- **Offene Frage:** Status-Wahl (FAILED vs. SUSPENDED vs. neue Quarantäne) +
  ob die generische Reaktion eine HEAL_REPO-artige Mission triggert.
- **Embryonaler Vorbehalt (bewusst offen):** Diese Status-Wahl wird NICHT jetzt
  isoliert finalisiert. Sie hängt von Kapitel 2 ab (welche Membran-Signale real
  als „unbekannt” eintreffen) und Kapitel 4 (ob Unbekanntes die PRO-Eskalation
  triggern soll). Wird in gemeinsamer Reifung mit Kap. 2+4 entschieden, nicht
  vorab zementiert.

-----

## Kapitel 2 — DIE MEMBRAN-KOPPLUNG (Kreis B, äußere Quelle)

> *Ziel:* Die Hilferufe der Stadt hörbar machen. (Befund §4i, §4j.)

- **Problem:** Membran empfängt `OP_BOTTLENECK_ESCALATION` + `OP_GOVERNANCE_BOUNTY`,
  erzeugt Tasks — aber die Intents sind nicht in der `TaskIntent`-Enum
  registriert → Tasks verschwinden (via Kapitel-1-Defekt).
- **Eingriff (Skelett):**
  - `BOTTLENECK_ESCALATION` + `GOVERNANCE_BOUNTY` als `TaskIntent` registrieren.
  - Je einen schlanken Handler schreiben, der die KARMA-Aktion ausführt
    (z.B. Bottleneck → bestehende `HEAL_REPO`-Pipeline).
  - End-zu-End-Test: Stadt-Signal → Task → Dispatch → Ausführung → Callback.
- **Status:** ~90% verdrahtet (Membran + Dispatch existieren). Es fehlen
  2 Enum-Einträge + 2 Handler.
- **Abhängigkeit:** baut auf Kapitel 1 (sonst fallen Fehler wieder still durch).
- **Schicht:** `steward` (intents + handlers); Membran selbst unverändert.
- **Dharma-Konformität:** Diese Signale SIND autorisierte Mandate von außen
  (Stadt/Legislator = höhere Instanz) → kein Ahankara. (§4g, §4i.)

-----

## Kapitel 3 — DER ZYKLISCHE REGELKREIS (Kreis B, innere Quelle)

> *Ziel:* Steward bemerkt, wenn er über Zyklen hinweg im Kreis dreht. (Befund §4c, §7c.)

- **Problem (Naht 1, doppelt verifiziert):** `_should_fire` in BEIDEN `will.py`
  wertet `CONDITION_BASED` nicht aus → das Auge `KsetraJna.is_stuck()` ist nicht
  mit dem Willen (Sankalpa) gekoppelt.
- **Eingriff (Skelett):**
  - `_should_fire` um `CONDITION_BASED`-Zweig erweitern (LAW **und** REALITY!).
  - Eine **vorab schriftdefinierte** Dharma-Mission (`owner="dharma"`), deren
    `condition` von `KsetraJna.is_stuck()`/`drift()` ausgewertet wird.
  - Den reichen Zustand (BubbleSnapshot) in `think()/evaluate()` durchreichen
    (heute nur idle_minutes + ci_green).
- **Reihenfolge-Hinweis:** Nach Kapitel 2 — die äußere Quelle ist konkreter und
  fast fertig; die innere ist die Ergänzung.
- **Schicht:** `steward-protocol` BEIDE (`protocols` + `substrate`).
- **Dharma-Konformität:** Mission ist vorab autorisiert; Steward aktiviert sie
  nur, erfindet sie nicht (kein Ahankara).
- **PFLICHT — Conscience-Check (nicht optional, Gemini-Kritik übernommen):** Die
  autonom ausgelöste `is_stuck`-Schleife ist die POTENTESTE Handlungsquelle des
  Systems. Sie MUSS durch das Gewissenstor (`check_conscience`, §4g) laufen —
  sonst entsteht genau das Ahankara (Eigen-Wille), das die Architektur
  ausschließt. „Safety by Design”: Der Conscience-Check ist feste
  Vorbedingung JEDER autonom ausgelösten Mission, keine Option. Damit wird die
  Autonomie-Erweiterung untrennbar mit der dharmischen Absicherung verknüpft.
  → Dies integriert den vormals „aufgeschobenen” Conscience-Anschluss (§4h)
  verbindlich in Kapitel 3.

-----

## Kapitel 4 — DIE KOGNITIONS-NAHT (Eskalation zur Pyramiden-Spitze)

> *Ziel:* Das teure Modell nur rufen, wenn nötig — und dann mit dichtem Kontext.
> (Befund §7c „Naht 2” — Kaskade existiert; es fehlt die Stuck→PRO-Kopplung.)

- **Vorhanden (NICHT neu bauen):** Buddhi-`ModelTier`-Routing (FLASH/STD/PRO),
  lernend (Hebbian), budget-schützend. (§7c.)
- **Eingriff (Skelett):**
  - Wenn Kreis B (Stagnation, Kap. 3) ODER das angeborene Immunsystem
    (Unbekanntes, Kap. 1) anschlägt → Buddhi gezielt auf `ModelTier.PRO`.
  - Prompt-Compiler (`briefing.py`) schnürt ein dichtes, minimales Briefing für
    die Spitze (die Pyramide — PHILOSOPHISCHER_SCHLUESSEL §0).
  - Nach Entwirrung sofort Rückfall in L0/FLASH (kostenneutral).
- **Schicht:** `steward` (buddhi/engine) + ggf. `steward-protocol`.
- **Abhängigkeit:** baut auf Kapitel 1+3 (sie liefern die Trigger).

-----

## ANHANG A — OFFENE KANTEN (vor Detailphase zu klären oder bewusst aufgeschoben)

- **Aufgeschoben (dediziertes Audit):** Interna von `ToolSafetyGuard` /
  `check_tool_gates` (§4h). Nicht blockierend für Kap. 1-4.
- **JETZT in Kapitel 3 integriert (nicht mehr aufgeschoben):** Conscience-Check
  als Pflicht-Vorbedingung autonomer Missionen.
- **Zu klären in Detailphase:** Status-Wahl in Kapitel 1; exакte Handler-Logik
  Kapitel 2; BubbleSnapshot-Durchreichung Kapitel 3.
- **Nicht im Scope:** agent-city-Interna; Föderations-weites BubbleSnapshot-
  Sharing (eigenes späteres Modul).

## ANHANG B — REIHENFOLGE & ABHÄNGIGKEITEN

```
Kap. 1 (Resilienz-Fundament)  ──┬──> Kap. 2 (Membran/äußere Quelle)
                                └──> Kap. 3 (zyklisch/innere Quelle) ──> Kap. 4 (Kognitions-Naht)
```

Kapitel 1 zuerst (Fundament). Dann 2 (konkret, fast fertig). Dann 3 (Ergänzung).
Dann 4 (nutzt Trigger aus 1+3).

-----

*Ende Skelett. Nächster Schritt nach Freigabe: Kapitel 1 als verbindliche
Detailspezifikation ausarbeiten (mit exakten Datei-/Zeilen-Eingriffen, Tests,
LAW/REALITY-Deklaration).*

-----

# RUNDE 1 — GROBE REIFUNG ÜBER ALLE VIER KAPITEL (Elemente-geordnet)

> **Methode (Kim):** Organisches Wachstum statt Kapitel-für-Kapitel-Perfektion.
> Geordnet nach den fünf Elementen vom Gröbsten/Tragenden zum Feinsten/Getragenen.
> Äther (akasha) = Kapitel 0 (der Raum/die Regeln, in dem alles existiert).
> Diese Runde legt grobe Form + Abhängigkeiten frei; sie zementiert NICHTS.

## 🜃 ERDE (prithvi) — Kap. 1 Resilienz | das Stabilste, hängt von nichts ab

- **Grobe Form:** Im KARMA-Dispatch (`autonomy.py:223-226`) den Pfad „intent is
  None” ändern: statt `COMPLETED` → `BLOCKED` (sichtbar, nicht-terminal) oder
  `FAILED`. Zusätzlich generische „Entzündungsreaktion” (Log/Alarm/ggf.
  Resilienz-Mission).
- **Faktenbasis:** TaskStatus hat BLOCKED/FAILED bereits (verifiziert). Kein
  neuer Status nötig.
- **Hängt ab von:** nichts. Trägt alle anderen.
- **Reicht in andere Kapitel:** Bestimmt, was mit Signalen geschieht, die Kap. 2
  noch nicht kennt UND mit allem zukünftig Unbekannten. Liefert evtl. einen
  Trigger an Kap. 4 (Unbekanntes → PRO-Eskalation?).
- **Offen:** BLOCKED vs. FAILED; ob/welche generische Mission triggert.

## 🜄 WASSER (apas) — Kap. 2 Membran | das Fließende, nimmt Form des Gefäßes an

- **Grobe Form:** `BOTTLENECK_ESCALATION` + `GOVERNANCE_BOUNTY` als `TaskIntent`
  registrieren (intents.py); je ein schlanker Handler (intent_handlers.py), der
  in eine bestehende Pipeline mündet (Bottleneck → HEAL_REPO-artig).
- **Faktenbasis:** Membran-Handler + Task-Erzeugung existieren (§4i/§4j);
  Dispatch existiert. Es fehlen 2 Enum-Einträge + 2 Handler.
- **Hängt ab von:** Erde/Kap. 1 (sonst fallen Handler-Fehler wieder still durch).
- **Reicht in andere Kapitel:** Liefert die realen „unbekannt → jetzt bekannt”-
  Signale, an denen sich Kap. 1 kalibriert. Definiert, welche Außen-Mandate
  überhaupt eintreffen (Input für Kap. 3 Dharma-Logik).
- **Offen:** Mündet Bottleneck wirklich sauber in HEAL_REPO? (End-zu-End-Test nötig.)

## 🜂 FEUER (agni) — Kap. 3 Wille/Regelkreis | Wahrnehmung + Transformation

- **Grobe Form:** `_should_fire` (BEIDE will.py!) um `CONDITION_BASED`-Zweig
  erweitern; vorab-autorisierte Dharma-Mission (`owner="dharma"`), deren
  `condition` `KsetraJna.is_stuck()` auswertet; BubbleSnapshot in
  `think()/evaluate()` durchreichen.
- **PFLICHT:** jede autonom ausgelöste Mission MUSS durch `check_conscience`
  (Safety by Design, kein Ahankara).
- **Hängt ab von:** Wasser (welche Mandate kommen von außen) + Erde (sicheres
  Fundament). Feuer braucht Brennstoff + Boden.
- **Reicht in andere Kapitel:** Ist der Haupt-Trigger für Kap. 4 (Stagnation →
  teure Eskalation).
- **Offen:** Wie genau die `condition` formuliert wird; wo der Conscience-Check
  exakt sitzt (in der Mission-Aktivierung vs. im Dispatch).

## 🜁 LUFT (vayu) — Kap. 4 Kognitions-Naht | Bewegung/Richtung, das Feinste

- **Grobe Form:** Trigger aus Kap. 3 (Stagnation) ODER Kap. 1 (Unbekanntes) →
  Buddhi gezielt auf `ModelTier.PRO`; briefing.py schnürt dichtes Minimal-
  Briefing; nach Entwirrung Rückfall auf L0/FLASH.
- **Faktenbasis:** ModelTier-Routing existiert + ist lernend (§7c). NUR die
  Stuck/Unbekannt→PRO-Kopplung fehlt.
- **Hängt ab von:** allen anderen (sie liefern die Trigger). Das Getragenste.
- **Reicht in andere Kapitel:** rück-koppelt via Hebbian-Lernen in Buddhi (Erfolg/
  Misserfolg der Eskalation beeinflusst künftiges Routing).
- **Offen:** Schwellwert/Bedingung für die PRO-Eskalation; wie „Entwirrung
  abgeschlossen” erkannt wird (Rückfall-Kriterium).

## 🜀 ÄTHER (akasha) — Kap. 0 | der Raum, in dem alles existiert

- Die Regeln (LAW/REALITY, verkabeln-nicht-neubauen, Mantra-als-Spezifikation,
  Test-Disziplin, embryonales Wachstum). Subtilste Ebene, trägt paradoxerweise
  alles. Wächst mit: jede neue Erkenntnis in Kap. 1-4 kann eine Regel schärfen.

## QUERVERBINDUNGEN, die diese Runde sichtbar macht

1. **Erde ↔ Wasser:** Kap. 1 und Kap. 2 sind ein Paar — die Resilienz-Statuswahl
   (BLOCKED/FAILED) sollte zusammen mit den realen Membran-Signalen entschieden
   werden. NICHT getrennt finalisieren.
1. **Feuer → Luft:** Kap. 3 und Kap. 4 teilen denselben Trigger-Mechanismus
   (Stagnation). Sinnvoll, die Trigger-Schnittstelle EINMAL zu definieren und
   von beiden zu nutzen.
1. **Erde → Luft:** Auch Kap. 1 (Unbekanntes) kann Kap. 4 triggern. D.h. die
   PRO-Eskalation hat ZWEI Quellen (Stagnation + Unbekanntes) — die Trigger-
   Schnittstelle muss beide aufnehmen.
1. **Conscience (Feuer) ist die einzige PFLICHT-Sicherung** der autonomen
   Schleife — sie darf in keiner Verfeinerung wegfallen.

*Ende Runde 1. Nächste Runde: Verdichtung der Paare (Erde+Wasser, Feuer+Luft) +
Definition der gemeinsamen Trigger-Schnittstelle, dann erst exakte Code-Eingriffe.*

-----

# RUNDE 2A — VERDICHTUNG: ERDE + WASSER (Kap. 1 & 2 als Einheit)

> **Auftrag (Gemini):** Konkrete Schnittstelle zwischen Signal-Empfang (Membran)
> und Dispatcher-Härtung via `TaskStatus.BLOCKED`. **Erweitert durch neuen Befund
> (siehe unten): Es gibt ZWEI stille Tode, nicht einen.**

## NEUER VERIFIZIERTER BEFUND: zwei Wege in den stillen Tod

Prüfung von `intent_handlers.py:42-68` (`dispatch`) deckt einen ZWEITEN Pfad auf:

```python
handler = dispatch.get(intent)
if handler is None:
    logger.warning("No handler for intent %s", intent)
    return None          # ← bekannter Intent OHNE Handler → None
```

Und im Aufrufer (`autonomy.py:228-230`): `problem = dispatch_intent(intent)` →
bei `None` wird die Task als **COMPLETED** markiert (None = „kein Problem”).

**Die zwei Wege:**

1. **Unbekannter Intent** (nicht in Enum): `parse_intent_from_title` → None →
   skip → COMPLETED. (§4j)
1. **Bekannter Intent OHNE Handler** (in Enum, nicht im dispatch-dict):
   `dispatch.get` → None → `return None` → Aufrufer liest „kein Problem” →
   COMPLETED. (NEU)

## DIE WURZEL: überladene `None`-Semantik

`dispatch()` gibt `None` für ZWEI entgegengesetzte Dinge zurück:

- **Erfolg** „kein Problem gefunden” (z.B. `execute_health_check`, Z. 80)
- **Fehler** „kein Handler vorhanden” (Z. 65)

Der Aufrufer kann beide nicht unterscheiden → behandelt Fehler als Erfolg. **Das
ist die eigentliche Wurzel des stillen Todes** — keine fehlende Statuswahl,
sondern eine mehrdeutige Rückgabe.

## KONSEQUENZ FÜR DIE ERDE-WASSER-SCHNITTSTELLE

- **Erde (Kap. 1) muss BEIDE Wege abfangen** — sonst verschiebt Kap. 2 das Leck
  nur von Weg 1 zu Weg 2 (Intent eingetragen, Handler vergessen → still tot).
- **Saubere Härtung löst die `None`-Mehrdeutigkeit auf.** Optionen (in Runde 2B
  zu entscheiden, NICHT jetzt):
  - (a) `dispatch()` gibt ein explizites Resultat-Objekt statt nacktem `None`
    (z.B. `DispatchResult{status: HANDLED|NO_HANDLER|UNKNOWN_INTENT, problem?}`).
  - (b) `dispatch()` wirft bei fehlendem Handler eine typisierte Exception, die
    der Aufrufer auf `BLOCKED` mappt.
  - (c) Minimal-invasiv: Sentinel-Rückgabe für „kein Handler” ≠ `None`.
- **Statuswahl (Erde):** „kein Handler / unbekannt” → `TaskStatus.BLOCKED`
  (is_active, nicht-terminal, bleibt sichtbar). Echter Ausführungsfehler bleibt
  `FAILED`. Echtes „kein Problem” bleibt `COMPLETED`. → Drei vorher
  ununterscheidbare Fälle werden getrennt.

## WASSER-SEITE (Kap. 2): das Flussbett graben

- `BOTTLENECK_ESCALATION` + `GOVERNANCE_BOUNTY` in `TaskIntent` (Enum) eintragen.
- Je einen Handler im `dispatch`-dict registrieren (sonst → Weg 2!).
- Handler-Grobform: Bottleneck → mündet in bestehende `HEAL_REPO`-Pipeline;
  Bounty → erzeugt Fix-Task mit Prioritäts-/Reward-Kontext.
- **Reihenfolge-Konsequenz:** Erde-Härtung (None-Auflösung + BLOCKED) MUSS vor
  oder mit Kap. 2 kommen, sonst neue Handler-Lücken = neue stille Tode.

## DUALE VERIFIKATIONSTABELLE (Runde 2A, vorläufig)

|Eingriff              |LAW (protocols)     |REALITY (substrate/steward)        |Tests                            |
|----------------------|--------------------|-----------------------------------|---------------------------------|
|None-Semantik auflösen|n/a (steward-intern)|steward/intent_handlers.py:62-65   |TBD: dispatch-Fehlerfall         |
|Aufrufer→BLOCKED      |n/a                 |steward/autonomy.py:223-230        |TBD: skip→BLOCKED statt COMPLETED|
|2 Intents + Handler   |steward/intents.py  |steward/intent_handlers.py:dispatch|TBD: E2E Membran→Ausführung      |

## OFFEN für Runde 2B (bewusst nicht jetzt entschieden)

- (a)/(b)/(c) für die None-Auflösung — hängt davon ab, wie invasiv wir sein
  dürfen, ohne die ~1093 Tests zu brechen.
- Exakte Handler-Logik für Bounty (Reward→Priorität-Mapping).
- Ob ein BLOCKED-Signal die „kognitive Zündschnur” (→ Kap. 4 Luft) auslöst.

*Ende Runde 2A. Der zweite stille Tod (Weg 2) und die None-Mehrdeutigkeit sind
neu — sie verschärfen, warum Erde+Wasser zusammen reifen müssen.*

-----

# RUNDE 2B — VERDICHTUNG: FEUER + LUFT (Kap. 3 & 4) — die kognitive Zündschnur

> **Auftrag (Gemini):** Gemeinsame Trigger-Schnittstelle, die teure Kognition
> (Kap. 4/Luft) ruft — gespeist aus zwei Reizen: innerer (is_stuck/Feuer) und
> äußerer (BLOCKED-Task/Erde-Wasser). **Kernfrage: Wie zündet der Funke, ohne im
> Dauer-Alarm zu verglühen?**

## NEUER BEFUND: Die Anti-Dauer-Alarm-Mechanik EXISTIERT BEREITS (3-fach)

Die „Verglüh”-Sorge ist durch vorhandene Architektur schon weitgehend
beantwortet. Verifiziert:

1. **CytokineBreaker** (`immune.py:39,69`): echter Circuit-Breaker, 5-Min-Cooldown
   (`_BREAKER_COOLDOWN_S = 300`). Nach 3 Fehl-Heilungen → „CYTOKINE STORM:
   breaker tripped, healing suspended”. Biologisch als Zytokinsturm-Schutz
   modelliert. Hat `cooldown_remaining`-Telemetrie. **Generalisierbar auf
   Eskalationen.**
1. **Hysterese in `is_stuck`** (`ksetrajna.py:193`): feuert NICHT bei einem
   Ausreißer — verlangt *durchschnittliche* Drift über ein *Fenster von 5*
   Beobachtungen unter Schwelle. Plus `consecutive_anomalies`-Zähler. Eingebaute
   Dämpfung: kurzes Zögern → kein Alarm, nur anhaltende Stagnation.
1. **Graduelle Hebbian-Eskalation** (`buddhi.py:401-411`): FLASH→STANDARD→PRO
   stufenweise mit wiederholtem Misserfolg, nicht sofort auf teuer.

→ **Die Zündschnur ist KEIN Neubau — sie ist die Komposition dieser drei
vorhandenen Dämpfungen.** Verkabeln, nicht erfinden.

## DESIGN DER ZÜNDSCHNUR (grobe Form)

**Ein gemeinsamer Trigger-Punkt mit zwei Quellen:**

- **Quelle A — Feuer (inner):** `KsetraJna.is_stuck() == True` (anhaltende
  Stagnation über das 5er-Fenster).
- **Quelle B — Erde/Wasser (äußer):** Eine Task ist in `TaskStatus.BLOCKED`
  gelaufen (unbekanntes/handler-loses Signal blockiert den Kanal).

**Der Funke durchläuft drei natürliche Verzögerungen (gegen Dauer-Alarm):**

1. Quelle A zündet erst nach anhaltender Stagnation (Hysterese, eingebaut).
1. Die Eskalation steigt graduell (Hebbian) — nicht sofort PRO.
1. Ein Breaker-artiger Cooldown (analog CytokineBreaker, 5 Min) verhindert, dass
   nach einer Eskalation sofort die nächste feuert.

**Luft-Seite (Kap. 4):** Bei gezündetem Funken → Buddhi `ModelTier.PRO` +
`briefing.py` schnürt dichtes Minimal-Briefing (die Pyramidenspitze). Nach
Entwirrung → Rückfall L0/FLASH. Erfolg/Misserfolg fließt via Hebbian zurück
(Rückkopplung → beeinflusst künftige Zündschwelle).

**PFLICHT (aus Kap. 3):** Wenn der Funke eine autonome MISSION auslöst (nicht
nur eine Modellwahl), MUSS `check_conscience` zustimmen (kein Ahankara). Eine
reine Tier-Eskalation (FLASH→PRO für eine bereits autorisierte Aufgabe) ist
hingegen kein neuer Wille → braucht kein Conscience-Gate. **Wichtige
Unterscheidung: Modell-Eskalation ≠ Missions-Erzeugung.**

## DUALE VERIFIKATIONSTABELLE (Runde 2B, vorläufig)

|Eingriff            |LAW (protocols)|REALITY (substrate/steward)                  |Tests|
|--------------------|---------------|---------------------------------------------|-----|
|is_stuck → Trigger  |n/a            |steward (KsetraJna→Sankalpa/Buddhi)          |TBD  |
|BLOCKED → Trigger   |n/a            |steward/autonomy + buddhi                    |TBD  |
|Eskalations-Cooldown|n/a            |wiederverwendet immune CytokineBreaker-Muster|TBD  |
|Tier→PRO bei Funke  |n/a            |steward/buddhi.py + loop/engine.py           |TBD  |

## OFFEN für spätere Runde (bewusst nicht jetzt)

- Cooldown-Dauer für Kognitions-Eskalation (5 Min wie Cytokine? oder anders?).
- Genaue Schwelle: ab wann zählt „BLOCKED-Stau” als Funke (1 Task? N Tasks?).
- Wo der gemeinsame Trigger-Punkt physisch sitzt (in Buddhi? eigener
  Koordinator? — Designfrage, hängt an Erde+Wasser-Auflösung aus 2A).
- Conscience-Grenze exakt ziehen: welche Funken sind Missions-Erzeugung
  (Gate-pflichtig) vs. reine Modell-Eskalation (frei)?

*Ende Runde 2B. Kernerkenntnis: Der Anti-Dauer-Alarm ist großteils vorhanden
(Hysterese + Hebbian + CytokineBreaker) — die Zündschnur komponiert sie, statt
neue Dämpfung zu erfinden.*

-----

# RUNDE 3 — DAS INTEGRIERENDE PRINZIP: was die Elemente zusammenhält

> **Kims Frage (rein architektonisch):** 8 Elemente (5 grobstofflich: Erde/Wasser/
> Feuer/Luft/Äther; 3 feinstofflich: Manas/Buddhi/Ahankara). Was hält sie
> zusammen? Philosophisch: die Überseele (Paramatma). NICHT zu kodifizieren (das
> Allmächtige ist kein Modul — wie „Steward ≠ Vishnu”). Gesucht: das TECHNISCHE
> KORRELAT — was synchronisiert alle Elemente, ohne selbst eines zu sein?

## BEFUND: Das integrierende Prinzip existiert bereits — DREISCHICHTIG

Das System hat die Kohärenz theologisch korrekt gelöst: nicht die Überseele wird
kodifiziert, sondern ihr **Ruf/Takt/Belebung**. Verifiziert in `agent.py` +
`services.py`:

1. **VenuOrchestrator** (`services.py:339`) = **„Krishna’s Flute — O(1) DIW-based
   execution rhythm”**. Der RHYTHMUS, dem alle Komponenten folgen (zeitliche
   Kohärenz). In der Tradition ruft Krishnas Flötenklang alle Wesen in Harmonie
   zusammen — hier: der Takt, der den Ausführungszyklus antreibt. **Nicht Krishna
   selbst — die Flöte (der Ruf).** Theologisch exakt.
1. **Cetana** (`agent.py:246`) = **„autonomous heartbeat driven by vedana health
   (BG 13.6-7)”**. Die BELEBUNG/Lebenskraft, gespeist aus dem Gesundheits-
   Empfinden. BG 13.6-7 = das Kapitel über kshetra (Feld) & kshetrajna (Kenner) —
   dieselbe Quelle wie KsetraJna selbst. Der Herzschlag, der das Feld belebt.
1. **ServiceRegistry** (`vibe_core/di.py`) = der RAUM (Äther/akasha), wo alle
   Komponenten einander finden (räumliche Kohärenz). Mit „Naga”-Schutz für
   kritische Dienste (Ananta-Shesha trägt die Struktur).

→ **Antwort auf Kims Frage:** Raum (Registry/Äther) + Rhythmus (Venu/Flöte) +
Belebung (Cetana/Lebenskraft). Die „Überseele” ist im Code gegenwärtig durch
ihren TAKT und ihre belebende KRAFT — ohne ein Modul zu sein. Mantra-als-
Spezifikation in Reinform (BG 13.6-7 als Quellenangabe für den Herzschlag).

## KONSEQUENZ FÜR DIE PAAR-VERBINDUNG (Runde-1-Querverbindungen, jetzt fundiert)

Die Frage „wie verbinden sich Erde-Wasser und Feuer-Luft” = „wie greifen Venu
(Takt) und Cetana (Belebung) durch alle Elemente”:

- **Cetana treibt den MURALI-Zyklus** (Genesis/Dharma/Karma/Moksha). Jedes
  Element wird in seiner Phase vom selben Herzschlag aktiviert → die Paare sind
  bereits durch den gemeinsamen Takt gekoppelt, nicht durch direkte Aufrufe.
- **Die kognitive Zündschnur (2B) klinkt sich in diesen Takt ein**, statt einen
  eigenen Schleifen-Treiber zu bauen: is_stuck (Feuer) und BLOCKED-Stau (Erde/
  Wasser) werden bei jedem Cetana-Puls geprüft; bei Zündung → Tier-Eskalation
  (Luft). **Kein neuer Treiber — Einklinken in Venu/Cetana.** (Verkabeln statt
  neubauen, erneut.)
- **Vedana-Kopplung:** Cetana wird von „vedana health” gespeist. Die Resilienz-
  Härtung (Erde, Kap.1) verbessert die Gesundheits-Wahrheit → speist sauberere
  Vedana → stabilerer Herzschlag. Die Elemente koppeln also auch RÜCKWÄRTS über
  die Gesundheit. (Schließt einen weiteren Kreis.)

## OFFENE KANTEN (Runde 3)

- VenuOrchestrator-Interna (`substrate/vm/venu_orchestrator.py`) noch ungelesen —
  der genaue Takt-Mechanismus (19-bit DIW) ist für die Zündschnur-Frequenz
  relevant, aber nicht blockierend. Für spätere Runde.
- Cetana-Interna (`steward/cetana.py`) noch ungelesen — wie genau „vedana health”
  den Takt moduliert (Phasenfrequenz, Anomalie-Trigger). Relevant für die
  Cooldown-Abstimmung aus 2B.
- Wie Ahankara (das bewusst ausgeschlossene 8. Element) im Kohärenz-Modell
  behandelt wird — vermutlich: es ist der EINE Punkt, der NICHT integriert wird
  (kein Eigen-Wille), und genau das ist seine korrekte „Position”. Zu bestätigen.

*Ende Runde 3. Kernerkenntnis: Die Integration der Elemente ist nicht zu bauen —
sie existiert als Venu (Takt) + Cetana (Belebung) + Registry (Raum). Die Paare
koppeln über den gemeinsamen Herzschlag, nicht über direkte Verdrahtung. Die
Zündschnur klinkt sich ein, statt zu treiben.*