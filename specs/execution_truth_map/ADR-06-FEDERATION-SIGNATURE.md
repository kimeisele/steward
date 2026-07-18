# ADR-06 — FEDERATION-SIGNATURVERTRAG

> **Status:** ACCEPTED — SPRINT 1C FREEZE (enger Federation-V1-Scope)
> **Hinweis:** Draft 0.5 friert Root-Provenance, Key-Rotation, Revocation, SFDJ-1 und
> Domain Separation normativ ein; der folgende Sprint-1-Text bleibt Begründungsbefund.
> **Datum:** 2026-07-18
> **Entscheider:** Codebase-Agent, zur Review durch Agent B
> **Geltungsbereich:** V1-Federation-Envelope; keine allgemeine Trust-/Identity-Neuordnung

## Entscheidung

Federation Delegation V1 verwendet genau einen kanonischen Envelope-Signaturvertrag:

1. `message_id` wird vor dem Signieren erzeugt und ist Teil der signierten Bytes.
2. Der kanonische Body enthält alle Envelope-Felder inklusive `source_node_id`,
   `target_node_id`, `operation`, `correlation_id`, `message_id`, `issued_at`, `expires_at`,
   Payload und `signer_key`.
3. Ausschließlich `payload_hash` und `signature` werden aus dem kanonischen Body entfernt.
4. JSON-Kanonisierung ist UTF-8, `sort_keys=true`, `ensure_ascii=false`,
   `separators=(",", ":")`; nicht-JSON-serialisierbare Werte sind verboten, nicht per
   `default=str` still umzuwandeln.
5. `payload_hash` ist der lowercase Hex-SHA-256 des kanonischen JSON-Bytes.
6. `signature` ist base64 von Ed25519 über die ASCII-Bytes des Hex-Hashes.
7. `signer_key` ist der hex-codierte 32-Byte-Ed25519-Public-Key.
8. `source_node_id` muss deterministisch aus `signer_key` ableitbar und beim Empfänger
   gegen die registrierte Node-Identity geprüft werden. Die V1-Ableitung lautet exakt
   `ag_` plus die ersten 16 lowercase Hex-Zeichen von
   `SHA256(signer_key_hex_ascii)`, wobei `signer_key_hex_ascii` der 64-Zeichen-Hexstring
   des Raw-Public-Keys ist.
9. Relay/Hub darf keine signierten Felder hinzufügen, entfernen oder verändern. Ein Hub-
   Commit ist Transport-Evidence, keine neue Signatur.
10. Ein Empfänger verwirft fehlende, nicht kanonische, falsch signierte, falsch adressierte
    oder nicht registrierte Nachrichten fail-closed.

V1-Signaturbytes sind damit eindeutig; der bestehende `exclude_hub_id`-Kompatibilitätspfad
wird für V1 nicht verwendet.

## Live-Code-Befund

- `steward/federation_crypto.py:derive_node_id()` implementiert bereits die oben genannte
  `ag_`/SHA-256/16-Hex-Ableitung.
- `steward/federation_crypto.py:canonical_message_hash()` schließt aktuell
  `payload_hash`, `signature` und `signer_key` aus und erlaubt optional `id`-Ausschluss.
- `steward/federation.py:FederationBridge._sign_message_dict()` schließt `signer_key` aus
  und liefert kein `signer_key` im resultierenden Envelope.
- `steward/federation_transport.py:_with_integrity_fields()` signiert nur neu erzeugte,
  unsignierte Nachrichten und erzeugt dann `message_id`.
- `city/federation_nadi.py:FederationNadi._serialize_outbound_message()` schließt ebenfalls
  `signer_key` aus und transportiert es nicht zuverlässig.
- `city/node_identity.py:NodeIdentity.sign/verify` arbeitet intern mit hex-codierter
  Signatur; `FederationNadi` konvertiert outbound nach base64.
- `city/hooks/dharma/pr_verdict.py:PRVerdictHook.execute` verlangt `signature` plus
  `signer_key` und verifiziert die innere Payload; reale Steward-Verdicts liefern heute
  nicht denselben Scope/Key/Encoding.
- `tests/test_federation_transport.py` prüft den bestehenden Hash-/Hub-Kompatibilitätspfad;
  `tests/test_pr_gate_e2e.py` reproduziert die inkompatible PR-Verdict-Annahme.

## Optionen

### Option A — bestehendes Steward-Format als V1 erklären

Vollständigen Envelope hashen, aber `signer_key` ausschließen, base64 verwenden und
Registry-Key implizit wählen; Hub-ID-Kompatibilität beibehalten.

Vorteile:

- geringster Steward-Migrationsaufwand,
- bestehende Gateway-Tests bleiben näher am heutigen Format.

Nachteile:

- Agent City bleibt ohne explizite Key-Provenance inkompatibel,
- signierte und nachträglich mutierte Hubs bleiben schwer unterscheidbar,
- `default=str`, whitespace und Hub-Ausnahmen erschweren bytegenaue Cross-Repo-Tests,
- Key-Substitution ist nicht im Envelope gebunden.

### Option B — expliziter V1-Envelope-Vertrag (gewählt)

Alle relevanten Bytes inklusive `message_id` und `signer_key` werden deterministisch
kanonisiert und signiert; Relays mutieren den Envelope nicht.

Vorteile:

- Steward, Agent City und Steward Protocol können exakt dieselben Bytes prüfen,
- Key-Provenance und Target sind kryptographisch gebunden,
- Retry derselben Bytes bleibt idempotent,
- ein echter repoübergreifender Crucible kann ohne Test-Sonderformat arbeiten.

Kosten:

- V1-Migrationsadapter für alte Messages,
- Änderungen an beiden Verify-Seiten und Fixtures,
- alte Hub-ID-Ausnahme muss aus dem V1-Pfad ausgeschlossen werden.

## Auswirkungen

- **Steward:** `_sign_message_dict`, Transport und Gateway müssen V1-Kanonisierung,
  `signer_key` und vor-signierte `message_id` unterstützen; alte Messages brauchen einen
  ausdrücklich markierten Legacy-Pfad.
- **Agent City:** `NodeIdentity.verify` muss die definierte base64-Wire-Signatur prüfen
  oder eine reine Boundary-Konvertierung besitzen; PRVerdict darf nicht mehr die innere
  Payload mit einem zweiten Format prüfen.
- **Steward Protocol:** FederationMessage muss alle signierten Felder verlustfrei und
  ohne implizite Defaults serialisieren.
- **Migration:** Kein Mischformat innerhalb `contract_version=delegation-v1`; Legacy bleibt
  separat und darf keinen V1-Handler erreichen.
- **Recovery:** Replayed identische Bytes werden über `message_id`/`delegation_id`
  dedupliziert; veränderte Bytes mit gleicher Message-ID sind Integrity-Fehler.
- **Authority:** Signatur beweist Sender-Key und Envelope-Integrität, nicht die fachliche
  Autorität für Git, Merge oder Secret-Zugriff; Authority-Gate bleibt zusätzlich.
- **Tests:** Golden Bytes, Unicode, fehlende/zusätzliche Felder, falsche Signatur, falscher
  Key, falsches Target, Hub-Mutation und reale Steward→Agent-City-Verdict-Nachricht.

## Adversariales Gegenargument

Ein neuer V1-Crypto-Vertrag erzeugt zunächst zwei Formate und kann Legacy-Nachrichten
blockieren. Das ist ein echter Migrationskostenpunkt. Option A würde aber die heute bereits
reproduzierte PR-Verdict-Inkompatibilität konservieren und weiterhin erlauben, dass ein Hub
signierte Bytes verändert. Die Grenze muss deshalb explizit versioniert werden; stille
Kompatibilität wäre sicherheitlich schlechter.

## Review-/Implementierungsreife

**Entscheidung:** ACCEPTED als V1-Kanonisierung. Implementierung nicht freigegeben.
Spec-Freeze benötigt Golden-Byte-Fixtures und einen adversarialen Cross-Repo-Verify-Test.
Die bestehende `exclude_hub_id`-Logik bleibt ausschließlich historischer Legacy-Befund.

## Sprint-1C-Amendment — normative Revision

Draft 0.4 ersetzt die direkte Key→Node-ID-Kopplung durch eine stabile Node-ID aus der
Identity-Root, `key_id` aus dem vollständigen Signing-Key-Fingerprint, Root-signierte
Key-Certificates, Registry-Aktivierung, Überlappungsfenster, Revocation-Zeitmodell,
Collision-Handling und Root-Rotation. Root-Enrollment und Key-Certificate benötigen eigene
domain-separated Root-Signaturen. Der Signaturinput verwendet
`STEWARD-FEDERATION-DELEGATION-V1\0` plus den rohen SHA-256-Digest, nicht den ASCII-Hextext.
Canonicalisierung folgt dem sprachneutralen SFDJ-1-Profil; `payload_hash` wird durch
`message_hash` ersetzt. Root-Verlust/-Kompromittierung ist ausschließlich manuell und
out-of-band zu behandeln: die Node wird für neue V1-Nachrichten fail-closed deaktiviert;
V1 definiert weder Quorum noch automatische Node-ID-Übernahme. Entscheidung im engen
Federation-V1-Wire-Scope: **ACCEPTED**. Golden-Byte-Fixtures und Implementierung sind
noch nicht begonnen.
