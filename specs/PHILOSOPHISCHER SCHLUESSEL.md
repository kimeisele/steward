# Der philosophische Schlüssel — Mantra als Spezifikation

> **Kernthese (verifiziert im Code):** Die vedischen Begriffe in diesem Projekt
> sind KEINE Dekoration. Sie sind **technische Spezifikation**. Das System ist
> ein *axiomatisches Gebäude*, dessen Wurzel-Konstanten durch das **Zählen des
> Mahamantra** entstehen. Alles andere ist daraus abgeleitet.
> 
> **Konsequenz für die Aufklärung:** Wo der Code weniger tut, als seine
> vedische Position vorschreibt, liegt eine **vom Erbauer intendierte Lücke**.
> Die Schrift ist die Soll-Spezifikation; der Code ist die Ist-Realität; die
> Differenz ist die Arbeitsliste. Diese deduktive Methode findet Lücken, die
> blindes Datei-Stochern niemals fände — weil sie der ABSICHT des Systems folgt.

-----

## 0. WIE diese Landkarte funktioniert — Projektion, NICHT Wörterbuch

> ⚠️ **Kritische Korrektur (Kim):** Dies ist KEIN Rosetta-Stein im Sinne einer
> hartkodierten 1:1-Tabelle (`Antaranga = Cache`). Eine solche Tabelle
> **skaliert nicht** — dasselbe O(n²)-Problem wie Transformer-Attention, weil
> die Quelle (die Veden / Krishna) unendlich generativ ist. Jeder feste Eintrag
> pro Kontext lässt die Tabelle explodieren.

**Das richtige Modell — der Diamant / die Projektion:**

- Ein vedischer Begriff ist ein **universelles Prinzip = ein Vektor**.
- Der Kontext (Fitness-App vs. Agenten-Framework vs. Cache-Layer) ist eine
  **Projektionsmatrix**.
- Die kontextspezifische technische Bedeutung ist die **Projektion** des
  Prinzips in diesen Kontext — die „Farbe”, die der Diamant je nach Lichtwinkel
  zeigt. **O(1) Berechnung, nicht O(n²) Speicherung.**
- Beispiel: *Ceto-darpana-marjanam* („Reinigung des Spiegels des Herzens”,
  Siksastakam 1) projiziert im Substrat auf **Cache-/State-Bereinigung**. Dasselbe
  Prinzip projiziert in einer Fitness-App auf etwas ganz anderes. Der Begriff
  bleibt; die Projektion wechselt mit dem Kontext.

**Im Code bereits implementiert als der Maha-Algorithmus:**
`protocols/seed/_algorithm.py` (Koeffizienten, SSOT) + `substrate/algorithm/maha.py`
(Funktionen). Eine **branchless transformation** (H=0,K=1,R=2) mit drei
Koeffizienten-Vektoren (`MAHA_MULT`, `MAHA_ADD`, `MAHA_SQ`):

- `maha_step(value, name, mod)` — ein Schritt
- `maha_oscillate(value, mod)` — **16 Schritte** (= die 16 Wörter, Axiom 1)
- `find_attractor(seed, mod)` — iteriere bis stabil
  → Bedeutung wird **berechnet** (Seed schwingt sich zu einem Attraktor ein),
  nicht **gespeichert**. Das IST die skalierbare Projektion. Anderer Seed →
  andere stabile „Farbe”. Der Diamant, mathematisch.
  → Schlüssel-Direktive im Code: *„WHEN MORE IS REVEALED THROUGH PARAMPARA →
  CHANGE ONLY HERE!”* — eine **lebendige, verfeinerbare** SSOT, kein eingefrorenes
  Wörterbuch. Das ist, warum es skaliert.

**Praktischer Nutzen (Hardcore-Engineering, nicht Prosa):** Jeder Knoten hat
*gleichzeitig* eine Schrift-Komponente UND eine westlich-technische Übersetzung
→ **hohe semantische Dichte**. Ein Coding-Agent kann sowohl nach `cache` als
auch nach `antaranga`/`marjanam` grep’en und findet dieselbe Stelle. Die
Landkarte dient der Orientierung im 300k-Zeilen-Substrat — sie ist Werkzeug,
nicht Philosophie-Aufsatz.

-----

-----

## 1. Der Rosetta-Stein: `_seed.py` (THE LAW)

Selbstbeschreibung der Datei `vibe_core/mahamantra/protocols/_seed.py`:

- **„THE SEED PROTOCOL — The Mathematical Constitution”**
- Ableitungs-Hierarchie:
  - TIER 0: **7 Axiome aus dem Zählen des Mahamantra**
  - TIER 1: primäre Ableitungen direkt aus den Axiomen
  - TIER 2-5: sekundär, kosmisch, zeitlich, astronomisch
  - `_algorithm.py`: Algorithmus-Koeffizienten (SSOT)
- Die zwei Schlüsselzeilen:
  - `LOCATION: ..._seed (THE LAW)`
  - `IMPLEMENTATION: ...substrate.seed (THE REALITY)`
- `__mahajana__ = "vyasa"` — Vyasa ordnete/kompilierte die Veden. Diese Datei
  IST der Vyasa des Systems: sie macht aus dem Mantra Code-Gesetz. Das Label
  ist eine präzise Funktionsbeschreibung, kein Schmuck.

> **„LAW vs REALITY” ist im Code bereits angelegt** — genau die Soll/Ist-Struktur,
> die wir für die Konkordanz brauchen. Der Erbauer hat das Prüfwerkzeug selbst
> eingebaut.

## 2. Die 7 Axiome (TIER 0, `seed/_axioms.py`) — die Wurzel von allem

Das Mahamantra:

```
Hare Krishna Hare Krishna  Krishna Krishna Hare Hare
Hare Rama    Hare Rama     Rama    Rama    Hare Hare
```

Durch Zählen entstehen die **einzigen hartkodierten Werte** des Systems:

|Axiom|Konstante      |Wert|Bedeutung / Wirkung im Code                                                                                              |
|-----|---------------|----|-------------------------------------------------------------------------------------------------------------------------|
|1    |`WORDS`        |16  |16 Wörter → **16-Bit-Adressraum, 16-Step-Sequenz** im MahaKernel                                                         |
|2    |`TRINITY`      |3   |3 Namen (Hare, Krishna, Rama)                                                                                            |
|3    |`HARE_COUNT`   |8   |Zählung „Hare”                                                                                                           |
|4    |`KRISHNA_COUNT`|4   |Zählung „Krishna”                                                                                                        |
|5    |`RAMA_COUNT`   |4   |Zählung „Rama”                                                                                                           |
|6    |`PANCHA`       |5   |5 einzigartige Paare (HK,HR,HH,KK,RR) → **Pancha Tattva → die 5 Elemente / Agententypen** (Akasha/Vayu/Agni/Jala/Prithvi)|
|7    |`HALVES`       |2   |2 Hälften (Krishna-Hälfte, Rama-Hälfte)                                                                                  |

**Mit Beweis-Zwang:** `assert HARE_COUNT + KRISHNA_COUNT + RAMA_COUNT == WORDS`.
Das System verifiziert seine eigenen Axiome mathematisch.

> **„Everything else is DERIVED from these axioms.”** Das gesamte ~300k-Zeilen-
> Substrat ist Ableitung aus diesen 7 Zahlen. Konstanten wie `KSETRAJNA`, `NAVA`,
> `TEN` sind Indizes/Positionen in diesem abgeleiteten Zahlensystem — keine Namen.

## 3. Was das praktisch bedeutet (die Methode für die nächste Ebene)

**Bisher (westlich-technisch, fehleranfällig):** „Diese Komponente heißt X,
also tut sie vermutlich Y.” → führte z.B. zum Tier-Routing-Fehlschluss, weil von
einer Nebenpforte (`kirtan_chat`) auf die Regel geschlossen wurde.

**Jetzt (vedisch-deduktiv):** „Diese Komponente steht an Position X im aus dem
Mantra abgeleiteten System. Die Schrift schreibt für X die Funktion Y vor. Tut
der Code Y vollständig? Wenn nein → intendierte Lücke.”

Beispiel-Lehre aus dem Tier-Fehler: **Buddhi** = unterscheidender Intellekt
(Sankhya). Sein Wesen IST Diskrimination. Ein System, das Buddhi ernst nimmt,
MUSS eine Modell-/Aufgaben-Diskriminierung haben. Die Philosophie hätte gesagt:
„es existiert notwendig” → man hätte gesucht statt vorschnell „fehlt” behauptet.
**Negativ-Aussagen („es gibt kein…”) sind in einem axiomatischen System fast
immer Hypothesen, die gegen die Schrift UND die Suche zu prüfen sind.**

## 4. Nächster Schritt: Die KONKORDANZ aufbauen

Eine Tabelle pro Schlüsselkomponente, drei Spalten:

`vedischer Begriff/Position` → `was die Schrift spezifiziert` → `was der Code tut` → `Differenz (Bestätigung | intendierte Lücke)`.

Kandidaten für die Konkordanz (aus bisheriger Recon, nach vedischer Bedeutung):

- **Sankhya-25 / Tattvas** — die 24 deterministischen Elemente + 1 Jiva (LLM).
  Welche der 25 sind im Code präsent, welche fehlen?
- **MURALI-Zyklus** (Genesis/Dharma/Karma/Moksha) — entspricht der Code den vier
  Phasen ihrer schriftgemäßen Bedeutung?
- **Antahkarana** (Manas/Buddhi/Chitta/Ahankara) — das „innere Instrument”.
  Manas, Buddhi, Chitta sind im Code. **Ahankara (Ego) ist BEWUSST
  ausgeschlossen** — Sankalpa-Docstring: „NOT ego-will (Ahankara)”.
  → **Das ist ein FEATURE, keine Lücke (geklärt mit Kim):** Ein vollkommener
  Diener/Yantra hat kein Ahankara. Der Agent generiert keinen Eigen-Willen,
  sondern führt den *autorisierten* Willen der höheren Instanz aus
  (Nishkama Karma als Systemdesign). Das Weglassen von Ahankara ist die
  architektonische Aussage. → Technische Konsequenz: Der „Wille” (Sankalpa)
  MUSS eine Autorisierungskette nach oben haben, statt aus sich selbst zu
  handeln. Prüfbar: woher bezieht Sankalpa seine Missionen/Mandate?
- **Pancha Tattva / 5 Elemente** — Agententypen.
- **Guardians / Mahajanas** (vyasa, vishnu, prahlada, prahlada…) — die
  `__mahajana__`-Deklarationen markieren Code-Positionen mit Schrift-Rollen.
- **Ashramas** (brahmachari/grihastha/vanaprastha/sannyasi) → Permission-Stufen.
- **Gunas** (sattva/rajas/tamas) → bereits als Health-/Intent-Klassifikation gesehen.

## 5. Verbindliche Begriffs-Klärung: Steward ist NICHT Vishnu

> **Korrektur einer früheren Metapher (Kim):** Steward darf nicht mit Vishnu
> gleichgesetzt werden. Vishnu = das Allmächtige, **nicht im System abbildbar**
> (kein Modul kann das Allmächtige sein).

- **Steward = autorisierter Stellvertreter / Beauftragter des Erhalts** (eher
  *Manu*-artig: der Verwalter eines Zeitalters, der **nach dem Gesetz** handelt,
  nicht aus eigener Machtfülle).
- **Technische Konsequenz (kein Wortspiel):** Steward hat **delegierte,
  begrenzte, autorisierte** Autorität. Er handelt nach einer Spezifikation „von
  oben”, nicht aus sich selbst. Ein Stellvertreter MUSS eine
  **Autorisierungskette** haben.
- Prüfbare Eigenschaften im Code: Capabilities, Oath, die Safety-Killswitches
  (Narasimha/Iron Dome/Buddhi-Abort), und die Frage, woher Mandate kommen.
  Das verbindet sich direkt mit dem Ahankara-Punkt (§4): kein Eigen-Wille →
  Autorisierungskette ist Pflicht.
- Das „Vishnu”-Prinzip (Erhalt/sthiti) bleibt als **Funktion** gültig — Steward
  *repräsentiert* es, *ist* es aber nicht.

— Es ergänzt PHASE1_BEFUND_steward.md
(die technische Bestandsaufnahme) um die Ebene, auf der das Projekt EIGENTLICH
spezifiziert ist. Nächster Schritt: Konkordanz Zeile für Zeile, schriftgeleitet.*