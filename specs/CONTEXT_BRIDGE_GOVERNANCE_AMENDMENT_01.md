# Context Bridge Governance Amendment 01 — Single-Owner HITL

Status: **Normative Governance-Korrektur; keine Produkt- oder Aktivierungsfreigabe**

Dieses Amendment korrigiert ausschließlich die unbelegte Annahme, Steward müsse vor
einer Constitution-Sourceänderung einen zweiten menschlichen GitHub-Principal besitzen.
Es lockert weder technische Contract-Checks noch die Sperren für automatische kanonische
Publication.

## 1. Reale Autoritätsgrenze

- Das Repository hat einen menschlichen Owner und Operator.
- Coding-Agenten handeln als technische Delegierte dieses Operators. Derselbe GitHub-
  Account, ein Botname oder ein anderer lokaler Git-Autor erzeugt keinen unabhängigen
  Principal.
- Der aktuelle Chat-/CLI-Auftrag bleibt externe Laufzeitautorität und wird nicht aus
  Repository-Daten rekonstruiert.
- GitHub kann in dieser Topologie Commit, PR, Checks und Merge belegen, aber keine
  unabhängige Trennung zwischen Operator und Agent.

Eine Zwei-Principal-Pflicht würde daher keine vorhandene Sicherheitsgrenze schützen,
sondern das Projekt bis zur Aufnahme einer weiteren Person künstlich blockieren. Falls
später ein zweiter vertrauenswürdiger Maintainer existiert, darf zusätzlicher Review als
Defense-in-Depth aktiviert werden; er ist keine Voraussetzung des heutigen Vertrags.

## 2. Single-Owner-HITL-Vertrag

Eine C0-Sourceänderung ist nur zulässig, wenn diese Reihenfolge vollständig eingehalten
wird:

1. Der Agent erstellt einen eng begrenzten PR ohne Root-, Produkt-, Workflow-, Setting-
   oder Runtime-State-Änderung.
2. Der finale PR-Head wird eingefroren. Danach wird dem Operator ein Reviewpaket mit
   Repository, PR, Base-SHA, Head-SHA, erlaubten Pfaden, vollständigem Diff, Source-Blob,
   C0-SHA-256, Kandidatenhash/-länge, Testergebnissen, unveränderten Root-Blobs, Risiken
   und Nicht-Zielen vorgelegt.
3. Der Operator bestätigt oder verwirft exakt diesen Head im aktiven HITL-Kanal. Eine
   gültige Freigabe nennt mindestens Head-SHA, Source-Blob und C0-SHA-256.
4. Jeder Commit nach der Freigabe verwirft sie. Der Agent muss ein neues Reviewpaket
   vorlegen und eine neue explizite Entscheidung abwarten.
5. Der Agent merged erst nach gültiger Freigabe regulär und ohne Admin-/Check-Bypass.
6. Merge-SHA, tatsächlich gelandeter Source-Blob, C0-Hash, Checks und Operatorentscheidung
   werden anschließend in der Phase-2-Evidence protokolliert.

Die Freigabeform ist:

```text
APPROVE CONSTITUTION <head_sha> <source_blob> <c0_sha256>
```

Andere Zustimmung wird nicht in diese exakte Freigabe hineingedeutet. Der HITL-Beleg ist
eine prozedural vertrauenswürdige Operatorentscheidung, aber kein unabhängig von GitHub
kryptographisch beweisbarer zweiter Review. Diese Grenze muss in späterer Provenance als
`single_owner_hitl` bezeichnet werden; sie darf nicht als `independent_review` erscheinen.

## 3. Technische Attestation

`ConstitutionAttestation` bedeutet in der Single-Owner-Topologie:

- der Operator hat den eingefrorenen PR-Head explizit freigegeben,
- Git bindet diesen Head an den geprüften Source-Blob,
- der normalisierte C0-Hash stammt reproduzierbar aus genau diesem Blob,
- der Source-Blob ist am Bootstrap- und Publication-Zeitpunkt unverändert,
- die verpflichtenden Contract-Checks sind grün.

CI attestiert ausschließlich reproduzierbare Bytes, Scope und technische Verträge. CI
behauptet nicht, die menschliche Absicht selbst erkannt zu haben. Ein späterer Check heißt
daher `Context Constitution Contract`; die frühere Bezeichnung `Context Constitution
Attestation` wird nicht als Beweis eines zweiten Menschen verwendet.

Der Resolver darf die Operatorentscheidung nicht aus PR-Titel, Commitmessage,
`merged_by`, Task, Issue oder Federation-Daten ableiten. Fehlt der explizite gebundene
Bootstrap-Input, lautet der Status `manual_review` beziehungsweise `unattested`.

## 4. CODEOWNERS und Branchschutz

- `CODEOWNERS` ist im heutigen Ein-Owner-Repository optional und darf nicht als
  unabhängiger Reviewbeweis dargestellt werden.
- PR-only `main`, bestehende Required Checks, kein Force-Push und kein Bypass bleiben
  technische Schutzgrenzen.
- Vor automatischer kanonischer Delivery bleibt ein eigener Required Check
  `Context Bridge Contract` verpflichtend.
- Automatische Publication, Auto-Merge und Runtime-Aktivierung bleiben bis zu ihren
  separaten Delivery-, Kill-Switch-, Recovery- und G2-Drills default-off.

## 5. Wirkung auf Slice C

`FEATURE_01_SLICE_C_G2_PREFLIGHT.md` bleibt als korrekter Live-Befund der damaligen
GitHub-Topologie erhalten. Seine Schlussfolgerung, ein zweiter Mensch sei zwingend, wird
durch dieses Amendment ersetzt.

Nach Review und Merge dieses Amendments darf Slice C als eigener Source-/Test-PR
vorbereitet werden. Dieser PR bleibt bis zum exakten Single-Owner-HITL-Reviewpaket und der
gebundenen Operatorfreigabe ungemergt. Dieses Amendment autorisiert keine Root-Ausgabe,
keinen Publisher und keine automatische Delivery.
