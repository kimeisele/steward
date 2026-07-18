# EXECUTION FOUNDATION — ADR-BACKLOG

> **Status:** MIXED — ADR-02/-06/-07/-08/-09 ACCEPTED; ADR-01/-03/-04/-05/-10 OPEN
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

Vor dem Decision Sprint war jede Frage `OPEN`. Seit Sprint 1 sind nur ADR-02, -06, -07,
-08 und -09 ausdrücklich entschieden; die übrigen Fragen bleiben `OPEN`. Reihenfolge
bedeutet Abhängigkeit, nicht vorweggenommene Antwort.

## Decision Sprint 1 — Ergebnisübersicht

| ADR | Status | Einzelentscheidung |
|---|---|---|
| ADR-02 | ACCEPTED | getrennte ID-Rollen; V1 `correlation_id == delegation_id`, Message-ID pro logischer Message |
| ADR-06 | ACCEPTED | expliziter kanonischer Envelope, SHA-256/Ed25519/base64, `signer_key` gebunden, keine Hub-Mutation |
| ADR-07 | ACCEPTED | vollständiges Wiring-Manifest als Implementierungs-/CI-Gate |
| ADR-08 | ACCEPTED | at-least-once Transport + durable idempotenter Receiver + sichtbares Recovery |
| ADR-09 | ACCEPTED | typisierte Receipt-Stufen von Transport bis Origin-Verification |

Die Einzel-ADRs enthalten Optionen, Auswirkungen, Gegenargument und Implementierungsreife.
Eine `ACCEPTED`-Entscheidung autorisiert noch keinen Produktcode.

## ADR-01 — Kanonische Ausführungsidentität

**Frage:** Welche Identität bleibt über Managed Task, Provider, Tool Call, Federation,
Workflow und Verification hinweg kanonisch, und wo wird sie erzeugt und persistiert?

**Status:** OPEN

**Recon-Bezug:** Truth Map §3; heute existiert keine universelle `execution_id`.

## ADR-02 — Trennung von Execution-, Correlation- und Message-ID

**Frage:** Sind Execution-ID, Correlation-ID und Message-ID zwingend getrennte Identitäten,
und welche Kardinalitäts- und Ableitungsregeln gelten zwischen ihnen?

**Status:** ACCEPTED — Decision Sprint 1; Details: `ADR-02-ID-BOUNDARIES.md`

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

**Status:** ACCEPTED — Decision Sprint 1; Details: `ADR-06-FEDERATION-SIGNATURE.md`

**Recon-Bezug:** Truth Map §7.4; Steward und Agent City verifizieren unterschiedliche Bytes.

## ADR-07 — Capability-Wiring-Definition

**Frage:** Muss jede Federation-Operation Richtung, Emitter, Target, Handler,
Authority-Gate, Result-Operation und End-to-End-Test deklarieren, bevor sie als implementiert
gilt?

**Status:** ACCEPTED — Decision Sprint 1; Details: `ADR-07-CAPABILITY-WIRING.md`

**Recon-Bezug:** Truth Map §7.1–7.3; `ALL_OPERATIONS` kodiert keine Richtung oder Vollständigkeit.

## ADR-08 — Retry- und Recovery-Idempotenz

**Frage:** Welche Idempotenzregeln gelten für Retry, Timeout, Crash-Recovery und doppelte
Nachrichten, insbesondere nach partiell ausgeführten Tool Calls?

**Status:** ACCEPTED — Decision Sprint 1; Details: `ADR-08-RETRY-RECOVERY-IDEMPOTENZ.md`

**Recon-Bezug:** Truth Map §3.2, §5 und §7.5; keine stabile Execution-Korrelation vorhanden.

## ADR-09 — Receipt-Semantik

**Frage:** Welche getrennten Receipts bestätigen Transport, Annahme, Ausführungsbeginn,
terminales Ergebnis und verifizierte Wirkung, und wer darf sie ausstellen?

**Status:** ACCEPTED — Decision Sprint 1; Details: `ADR-09-RECEIPT-SEMANTIK.md`

**Recon-Bezug:** Truth Map §6; heutiges `DeliveryReceipt` bestätigt keine konkrete Wirkung.

## ADR-10 — Statusmodell und Adapter

**Frage:** Welche bestehenden Statusmodelle bleiben fachliche Adapter, welches Modell ist
übergreifend, und welche Übersetzungen sind ausdrücklich verboten oder verlustbehaftet?

**Status:** OPEN

**Recon-Bezug:** Truth Map §4; Managed Task, A2A, Sankalpa und Chitta sind nicht formal übersetzt.

## Gate

ADR-02, -06, -07, -08 und -09 sind durch den Decision Sprint 1 ausdrücklich entschieden;
ihre Einzel-ADRs bleiben bis zur Agent-B-Review und dem Implementierungsreife-Gate
maßgeblich. ADR-01, -03, -04, -05 und -10 bleiben OPEN. Keine Entscheidung darf durch die
Federation Delegation V1 Spec oder eine spätere Execution-Spine-Spec implizit erweitert
werden. Wo ein Contract-Detail von einem offenen ADR abhängt, muss es weiterhin explizit
als Blocker markiert werden.
