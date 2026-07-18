# EXECUTION FOUNDATION — ADR-BACKLOG

> **Status:** OPEN — FRAGEN INVENTARISIERT, KEINE ENTSCHEIDUNGEN
> **Datum:** 2026-07-18
> **Quelle:** akzeptierter `EXECUTION_TRUTH_MAP_RECON.md`
> **Regel:** Dieses Backlog stellt Fragen. Es beantwortet sie nicht und autorisiert keine
> Implementierung.

---

## Nutzung

Jede Frage wird später in einem eigenen ADR entschieden. Ein ADR braucht mindestens:

- Live-Pins und betroffene Verträge,
- mindestens zwei realistische Optionen,
- Auswirkungen auf Recovery, Idempotenz, Authority und Migration,
- adversariales Review,
- expliziten Status `accepted`, `rejected` oder `superseded`.

Bis dahin ist jede Frage `OPEN`. Reihenfolge bedeutet Abhängigkeit, nicht vorweggenommene
Antwort.

## ADR-01 — Kanonische Ausführungsidentität

**Frage:** Welche Identität bleibt über Managed Task, Provider, Tool Call, Federation,
Workflow und Verification hinweg kanonisch, und wo wird sie erzeugt und persistiert?

**Status:** OPEN

**Recon-Bezug:** Truth Map §3; heute existiert keine universelle `execution_id`.

## ADR-02 — Trennung von Execution-, Correlation- und Message-ID

**Frage:** Sind Execution-ID, Correlation-ID und Message-ID zwingend getrennte Identitäten,
und welche Kardinalitäts- und Ableitungsregeln gelten zwischen ihnen?

**Status:** OPEN

**Recon-Bezug:** Truth Map §3; mehrere Transport-IDs existieren, Correlation ist häufig leer.

## ADR-03 — Terminale Completion

**Frage:** Darf ein Task `COMPLETED` ausschließlich nach erfolgreicher, unabhängiger
Postcondition-Verifikation werden, oder existieren zulässige schwächere Completion-Klassen?

**Status:** OPEN

**Recon-Bezug:** Truth Map §4.1 und §6; heutige Pfade markieren vor Verifikation completed.

## ADR-04 — Totale Provider-Erschöpfung

**Frage:** Ist totale Provider-Erschöpfung eine Exception, ein terminales strukturiertes
Outcome, ein Health-Signal oder eine verbindliche Kombination davon?

**Status:** OPEN

**Recon-Bezug:** Truth Map §5.1; Heartbeat Schnitt A beobachtet, propagiert aber nicht zum Exit.

## ADR-05 — Workflow-Wahrheit

**Frage:** Welche Fehlerklassen müssen einen GitHub-Workflow rot machen, welche dürfen nur
`degraded` werden, und welches maschinenlesbare Ergebnis muss ein tolerierter Fehler tragen?

**Status:** OPEN

**Recon-Bezug:** Truth Map §5.2 und §8 G0; Agent City zeigt live einen maskierten Pushfehler.

## ADR-06 — Federation-Signaturvertrag

**Frage:** Welches kanonische Federation-Signaturformat gilt für Signaturscope, Hash,
Encoding, Key-Provenance und Hub-Mutationen?

**Status:** OPEN

**Recon-Bezug:** Truth Map §7.4; Steward und Agent City verifizieren unterschiedliche Bytes.

## ADR-07 — Capability-Wiring-Definition

**Frage:** Muss jede Federation-Operation Richtung, Emitter, Target, Handler,
Authority-Gate, Result-Operation und End-to-End-Test deklarieren, bevor sie als implementiert
gilt?

**Status:** OPEN

**Recon-Bezug:** Truth Map §7.1–7.3; `ALL_OPERATIONS` kodiert keine Richtung oder Vollständigkeit.

## ADR-08 — Retry- und Recovery-Idempotenz

**Frage:** Welche Idempotenzregeln gelten für Retry, Timeout, Crash-Recovery und doppelte
Nachrichten, insbesondere nach partiell ausgeführten Tool Calls?

**Status:** OPEN

**Recon-Bezug:** Truth Map §3.2, §5 und §7.5; keine stabile Execution-Korrelation vorhanden.

## ADR-09 — Receipt-Semantik

**Frage:** Welche getrennten Receipts bestätigen Transport, Annahme, Ausführungsbeginn,
terminales Ergebnis und verifizierte Wirkung, und wer darf sie ausstellen?

**Status:** OPEN

**Recon-Bezug:** Truth Map §6; heutiges `DeliveryReceipt` bestätigt keine konkrete Wirkung.

## ADR-10 — Statusmodell und Adapter

**Frage:** Welche bestehenden Statusmodelle bleiben fachliche Adapter, welches Modell ist
übergreifend, und welche Übersetzungen sind ausdrücklich verboten oder verlustbehaftet?

**Status:** OPEN

**Recon-Bezug:** Truth Map §4; Managed Task, A2A, Sankalpa und Chitta sind nicht formal übersetzt.

## Gate

Kein ADR ist durch die Federation Delegation Contract V1 Spec oder eine spätere
Execution-Spine-Spec implizit beantwortet. Wo die Federation-Spec von einer offenen Frage
abhängt, muss sie den ADR als Blocker nennen und darf keinen Default erfinden.
