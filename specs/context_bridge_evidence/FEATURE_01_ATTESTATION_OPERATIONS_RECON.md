# FEATURE 01 — ATTESTATION UND OPERATIONSVERTRAG

> **Status:** EVIDENCE COMPLETE — VERTRAG ENTSCHEIDEN; LIVE-PRECONDITION NOCH NICHT ERFÜLLT
> **Datum:** 2026-07-15
> **Repository:** `kimeisele/steward`
> **Scope:** Read-only GitHub-/Git-/Konfigurationsrecon; keine Settings- oder Codeänderung

---

## 1. Fragen

1. Wie kann `ConstitutionAttestation.reviewed_at_commit` ohne Commit-Selbstreferenz und
   ohne autonome `verified`-Behauptung entstehen?
2. Welche konkreten Policy-, Runtime-, Branch- und PR-Namen tragen den default-off
   Publishervertrag?
3. Welche Live-Preconditions fehlen weiterhin?

---

## 2. Positive GitHub-Semantik

Offizielle GitHub-Verträge belegen:

- Pull-Request-Reviews liefern `state`, `user`, `commit_id`, `submitted_at` und
  `author_association`.
- Reviews werden chronologisch gelistet.
- Pull-Request-Autoren können den eigenen PR nicht freigeben.
- Branchschutz kann Code-Owner-Review verlangen und stale Freigaben nach neuen Commits
  verwerfen.
- Der Endpoint `GET /repos/{owner}/{repo}/commits/{sha}/pulls` ordnet einem Commit den
  einführenden gemergten PR zu.
- Ein gemergter PR liefert Head-SHA, Base, Mergezeit und Merge-Commit; die Bedeutung von
  `merge_commit_sha` hängt von Merge-, Squash- oder Rebase-Strategie ab.

Normative Referenzen:

- <https://docs.github.com/en/rest/pulls/reviews>
- <https://docs.github.com/en/rest/pulls/pulls>
- <https://docs.github.com/en/rest/commits/commits>
- <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches>
- <https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners>

---

## 3. Live-Governance

Der aktuelle Zustand besitzt:

- keinen Pull-Request-Review-Schutz auf `main`,
- `enforce_admins=false`,
- keine CODEOWNERS-Datei,
- genau einen Collaborator mit Admin-/Pushrechten,
- keine Repository-Actions-Variable,
- Auto-Merge auf Repositoryebene deaktiviert.

Die untersuchten gemergten PRs `#497`, `#498`, `#499`, `#505` und `#506` wurden vom
Account `kimeisele` erstellt und von demselben Account gemergt. Die Reviews-API lieferte
für diese PRs keine Reviews. Diese Commits sind technische Evidence, aber kein positiver
separater Human-Code-Owner-Reviewbeweis.

Folge: Weder Feature-00-Merge noch Feature-04-Merge darf als
`ConstitutionAttestation(status="verified")` ausgegeben werden.

---

## 4. Nicht-zirkulärer Attestation-Resolver

### 4.1 Bootstrap-Input

Der einmalige Bootstrap erhält explizit:

```text
source_pr_number
reviewed_head_commit
expected_source_blob
expected_c0_sha256
```

Diese Werte kommen aus dem getrennten Constitution-Migrations-PR, nicht aus Issues,
Runtime-State, LLM-Text oder dem späteren Root-Output.

### 4.2 Fail-closed Prüfsequenz

Der Resolver führt mit explizit versionierter GitHub-API mindestens aus:

1. `GET /repos/{owner}/{repo}/pulls/{source_pr_number}`.
2. PR ist `merged=true`, Base exakt `main`, nicht Draft und Source-PR-Head exakt
   `reviewed_head_commit`.
3. Source-PR-Dateiliste enthält `.steward/conventions.md` und keinen unzulässigen
   Automation-/Generated-State-Scope.
4. `GET /pulls/{source_pr_number}/reviews`; pro Reviewer zählt nur der letzte wirksame
   submitted State.
5. Mindestens ein wirksames `APPROVED` besitzt `commit_id=reviewed_head_commit`.
6. Reviewer ist nicht PR-Autor und besitzt zum Reviewzeitpunkt eine für den Gate
   ausreichende Repositoryrolle.
7. Auf exakt `reviewed_head_commit` existiert ein erfolgreicher Required Check
   `Context Constitution Attestation`, erzeugt vom erwarteten geschützten GitHub-Actions-
   Workflow. Dieser Check hat Reviewstate, Code-Owner-Zuordnung, Reviewer/Author-Trennung,
   stale-review- und Branchschutzwerte commitgebunden geprüft.
8. Die an `reviewed_head_commit` gelesene `.steward/conventions.md` besitzt exakt
   `expected_source_blob`.
9. `parse_conventions()` liefert exakt `expected_c0_sha256`.
10. Der aktuelle Zielbranch besitzt weiterhin denselben Source-Blob; sonst
    `manual_review`.
11. Der Merge-Commit beziehungsweise aktuelle Main-Head ist nachweislich Nachfolger des
    gemergten Source-PRs.

Ein API-Fehler, Pagination-Lücke, unbekannter Reviewstate, mehrere widersprüchliche PRs,
fehlender Attestation-Check/Branchschutzbeweis oder Blob-Mismatch blockiert. Der Resolver fällt nicht auf
lokale Commitmessage, PR-Titel oder `merged_by` als Reviewersatz zurück.

### 4.3 Output

Nur nach allen Prüfungen entsteht:

```text
ConstitutionAttestation(
  c0_sha256=expected_c0_sha256,
  source_blob=expected_source_blob,
  reviewed_at_commit=reviewed_head_commit,
  schema="steward.context.constitution-attestation/v1",
  status="verified",
)
```

`reviewed_at_commit` bezeichnet damit den tatsächlich freigegebenen PR-Head, nicht den
später noch unbekannten Bootstrap- oder Merge-Commit. Das Snapshot-Artefakt persistiert
diese Evidence. Solange der Source-Blob unverändert bleibt, dürfen Folgeläufe dieselbe
Attestation aus dem validierten vorherigen Snapshot übernehmen; ein Source-Wechsel
erzwingt einen neuen Reviewpfad.

### 4.4 Vertrauensgrenze

Der Resolver beweist GitHub-Ereignisse innerhalb der Repository-Governance. Er liefert
keinen kryptographischen Beweis, dass ein Administrator die Schutzregel niemals kurzzeitig
verändert hat. Governance-Änderungen selbst müssen deshalb auditierbar und codeowned sein;
der Aktivierungsdrill pinnt die gelesenen Settings und PR-Evidence.

Der commitgebundene Check reduziert die historische API-Lücke: aktuelle Branchschutzwerte
werden nicht rückwirkend als damaliger Zustand ausgegeben. Der Check-Workflow läuft bei
Source-PRs auf `pull_request` und nach eingereichtem Review erneut auf
`pull_request_review`; vor wirksamer Freigabe bleibt sein Ergebnis non-success. Sein Code
stammt vom geschützten Base-Branch, nicht aus dem zu attestierenden Automation-Diff.

---

## 5. Konkreter Mode-Vertrag

### 5.1 Geschützte Repository-Policy

Pfad:

```text
.github/context-bridge-policy.json
```

V1-Schema:

```json
{
  "schema": "steward.context.policy/v1",
  "mode": "disabled"
}
```

Erlaubte Modi sind exakt `disabled`, `preview`, `canonical`. Unbekannte Felder, fehlende
Datei, ungültiges JSON oder unbekannter Wert bedeuten `disabled`. Die Datei ist
CODEOWNERS-geschützte Governance und kann von keinem Automation-PR geändert werden.

### 5.2 Runtime-Key

Repository-Actions-Variable:

```text
CONTEXT_BRIDGE_RUNTIME_MODE
```

Auch hier sind nur `disabled`, `preview`, `canonical` gültig. Fehlend oder ungültig
bedeutet `disabled`. Die Variable darf Policy nur herabstufen:

| Policy | Runtime | effektiv |
|---|---|---|
| disabled | beliebig | disabled |
| preview | disabled/missing | disabled |
| preview | preview/canonical | preview |
| canonical | disabled/missing | disabled |
| canonical | preview | preview |
| canonical | canonical | canonical |

Ein Runtime-Administrator kann damit schnell stoppen, aber keine reviewte Policy
hochschalten.

### 5.3 Lokale Aufrufe

Außerhalb des GitHub-Workflows ist der Runtime-Key standardmäßig nicht authentifiziert.
Lokale `canonical`-Aufrufe bleiben daher disabled, sofern ein eigener G2-Drill nicht einen
expliziten, kurzlebigen Operator-Input und dieselben Attestation-/Fence-Prüfungen vorsieht.
Ein Environmentwert allein ist keine Aktivierung.

---

## 6. Konkrete Delivery-Identität

Nach Live-Kollisionsprüfung sind für V1 reserviert:

```text
Branch: automation/context-bridge
PR title: [context-bridge] canonical context publication
Required check: Context Bridge Contract
Constitution check: Context Constitution Attestation
Workflow display name: Context Bridge Delivery
```

Es existiert aktuell kein gleichnamiger Branch, offener PR, Workflow oder Required Check.

Der Branchname ist ein Identifier, keine Autorität. Der Delivery-Controller identifiziert
den PR zusätzlich über Base, Head-Repository, exakten Head-Branch, erwarteten Automation-
Principal und einen versionierten Body-Marker. Titeltext allein genügt nicht.

Body-Marker:

```text
<!-- steward-context-delivery:v1 -->
```

Mehrere passende offene PRs, fremder Head-Owner oder Scope-Abweichung blockieren und
erzeugen keinen weiteren PR.

---

## 7. Aktueller Gate-Status

Entschieden sind:

- nicht-zirkulärer Attestation-Input und API-Prüfsequenz,
- `reviewed_at_commit` als reviewter Source-PR-Head,
- Policy-Pfad und Mode-Lattice,
- Runtime-Key,
- Branch-, PR-, Check-, Workflow- und Body-Marker-Namen.

Nicht erfüllt sind:

- separater menschlicher Reviewer/Code Owner,
- CODEOWNERS und PR-Review-Governance,
- enforce-admins/no-bypass,
- Repository-Actions-Variable,
- Auto-Merge-Freigabe,
- realer Attestation- und Kill-Switch-Drill.

Diese fehlenden Live-Preconditions blockieren Bootstrap/Activation, aber nicht die
spec-getriebene, default-off Implementierung nach eigenen G2-Gates.

---

## 8. Gate-Wirkung

- Attestation- und Operationsnamen sind für Feature 01 geschlossen.
- DRAFT 0.2 kann diese Entscheidungen übernehmen.
- G1 darf weiterhin keine Aktivierung behaupten.
- Kein GitHub-Setting, Secret, Variable, Branch, PR, Workflow oder Produktcode wurde durch
  dieses Recon verändert.
