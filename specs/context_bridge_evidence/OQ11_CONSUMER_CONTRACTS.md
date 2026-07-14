# OQ-11 — CLAUDE-/CODEX-CONSUMER-VERTRÄGE

> **Status:** EVIDENCE COMPLETE — Entscheidung für Master-Spec DRAFT 0.3
> **Untersuchungsdatum:** 2026-07-14
> **Steward-Head:** `c437eed490da500626d1c48168dd6282ca08594e`
> **Steward-Tree:** `13f522ce0dd26110b00b5b8e2e4c709b8b6cfb34`
> **Scope:** Nur Discovery, Hierarchie, Priorität, Scope, Includes und Größenlimits von
> `AGENTS.md` und `CLAUDE.md`. Keine Governance-, Publisher- oder Workflow-Entscheidung.

---

## 1. Untersuchte Quellen

### OpenAI / Codex

- Offizielle Dokumentation:
  `https://developers.openai.com/codex/guides/agents-md`
- Lokal beobachtete Version: `codex-cli 0.144.3`
- Lokale Codex-Konfiguration: keine expliziten Werte für
  `project_doc_fallback_filenames` oder `project_doc_max_bytes`.

### Anthropic / Claude Code

- Offizielle Dokumentation:
  `https://code.claude.com/docs/en/memory`
- Ein lokaler Claude-Versionsprozess wurde nicht als Beweis verwendet, weil der
  Versionsaufruf im Recon nicht zuverlässig terminierte.

### Steward

Am gepinnten Head:

- `CLAUDE.md`: Blob `516d909f1b2445eee9e9ec8a366bdb9b12ab9688`, 4.046 Bytes,
  lokal 68 Zeilen.
- `AGENTS.md`: nicht vorhanden.

---

## 2. Positive Beweise — Codex

Die offizielle Codex-Dokumentation belegt:

1. Codex baut die Instruction-Chain einmal pro Run beziehungsweise TUI-Session.
2. Global wird `AGENTS.override.md` bevorzugt, sonst `AGENTS.md`; nur die erste
   nichtleere Datei dieser Ebene wird verwendet.
3. Im Projekt läuft Discovery vom Projekt-Root bis zum aktuellen Arbeitsverzeichnis.
4. Pro Verzeichnis wird höchstens eine Datei gewählt, in der Reihenfolge:
   `AGENTS.override.md`, `AGENTS.md`, konfigurierte Fallback-Namen.
5. Dateien werden Root-zu-CWD zusammengefügt; nähere Regeln stehen später und können
   frühere widersprechende Regeln übersteuern.
6. Der Standardwert für die kombinierte Guidance beträgt 32 KiB.
7. Codex dokumentiert konfigurierbare Fallback-Namen, aber keinen nativen `@file`-Import
   innerhalb von `AGENTS.md`.
8. Änderungen werden durch Neustart beziehungsweise einen neuen Run sicher neu entdeckt.

---

## 3. Positive Beweise — Claude Code

Die offizielle Claude-Code-Dokumentation belegt:

1. Claude Code liest `CLAUDE.md`, nicht automatisch `AGENTS.md`.
2. `CLAUDE.md` kann auf Root-, `.claude/`-, User-, Local- und Managed-Ebene liegen.
3. Gefundene Dateien werden additiv in den Context aufgenommen, nicht dateiweise ersetzt.
4. Dateien über dem Arbeitsverzeichnis laden beim Start; Unterverzeichnis-Dateien laden
   beim Zugriff auf Dateien in deren Scope.
5. `@path`-Imports werden unterstützt; relative Imports beziehen sich auf die
   importierende Datei.
6. Die Dokumentation empfiehlt für bestehende `AGENTS.md`-Repos ausdrücklich ein
   `CLAUDE.md`, das `@AGENTS.md` importiert und optional Claude-spezifische Regeln ergänzt.
7. `CLAUDE.md` wird vollständig geladen; empfohlen sind trotzdem weniger als 200 Zeilen.
8. Root-`CLAUDE.md` wird nach `/compact` erneut von Disk geladen.
9. HTML-Blockkommentare werden vor der Context-Injektion entfernt.
10. `CLAUDE.md` ist Verhaltenskontext, keine hart erzwungene Security Policy.

---

## 4. Vergleich

| Eigenschaft | Codex | Claude Code | Konsequenz |
|---|---|---|---|
| primärer Root-Name | `AGENTS.md` | `CLAUDE.md` | beide Dateinamen werden benötigt |
| Discovery-Zeit | einmal pro Run/Session | Start; Root erneut nach Compaction | kein Versprechen, laufende Sessions sofort zu aktualisieren |
| Hierarchie | höchstens eine Datei je Ebene | mehrere Dateien additiv | Konfliktsemantik ist nicht identisch |
| Override-Datei | `AGENTS.override.md` | `CLAUDE.local.md` additiv | nicht gemeinsam modellierbar |
| Include | kein nativer Include-Vertrag belegt | `@path` bis dokumentierte Tiefe | Import-Hülle möglich, aber nicht erforderlich |
| Größenverhalten | 32 KiB kombiniert per Default | vollständig geladen; <200 Zeilen empfohlen | gemeinsamer Kern muss beide Grenzen respektieren |
| Unterverzeichnis | Discovery bis Start-CWD | on-demand beim Dateizugriff | path-spezifische Regeln brauchen Consumer-Vertrag |
| HTML-Kommentare | nicht belegt | bei Injection entfernt | Provenance nicht nur in Kommentare schreiben |

---

## 5. Nicht belegbare oder bewusst offene Annahmen

- Die öffentlichen Consumer-Dokumente beweisen nicht, dass beide Produkte Markdown in
  jeder Form identisch gewichten.
- Der dokumentierte Claude-Import belegt eine unterstützte Interoperabilitätsoption, aber
  keinen Zwang zu einer Import-Hülle.
- Der Recon beweist keine Notwendigkeit für tool-spezifischen Root-Inhalt.
- Die Autorenschaft und Governance des gemeinsamen Kerns gehören zu OQ-18/OQ-07.
- Automatische Schreib- und Delivery-Rechte gehören nicht zu OQ-11.
- Pfadspezifische Unterverzeichnisregeln sind nicht Teil des gemeinsamen Root-Vertrags.

---

## 6. Sicherheitsauswirkung

- Ein fehlendes `AGENTS.md` lässt Codex ohne portable repo-eigene Root-Guidance starten.
- Unterschiedliche Discovery-Namen erzwingen zwei Dateien, aber nicht zwei Inhalte.
- Automatische Änderungen werden nicht sicher in bereits laufende Codex-Sessions geladen.
- Claude kann Root-Guidance nach Compaction erneut lesen; ein während einer Session
  wechselnder Root-Vertrag kann daher consumerabhängig zu unterschiedlichen Zeitpunkten
  sichtbar werden.
- Ein Root-Vertrag nahe oder über 32 KiB kann bei Codex abgeschnitten werden; lange
  Claude-Dateien reduzieren laut Anthropic die Befolgungsqualität.
- HTML-Kommentar-Provenance wäre für Claude unsichtbar.

---

## 7. Entscheidung

1. Steward benötigt portable Root-Artefakte unter beiden Namen.
2. Solange kein konkreter technischer Zwang zur Abweichung belegt ist, sind
   `CLAUDE.md` und `AGENTS.md` **vollständig byte-identische Publikationen exakt derselben
   kanonischen Payload**.
3. Es gibt keine vorsorglichen Claude- oder Codex-Hüllen.
4. Die von Anthropic dokumentierte `@AGENTS.md`-Hülle bleibt eine zulässige spätere
   Alternative, ist durch OQ-11 aber nicht erforderlich.
5. Jede Abweichung von Byteidentität benötigt:
   - einen dokumentierten Consumer-Zwang,
   - eine eigene Reviewentscheidung,
   - einen Contract-Test für beide Consumer,
   - eine minimale, klar abgegrenzte Differenz.
6. Der gemeinsame Root-Output bleibt unter beiden Grenzen: deutlich unter 32 KiB und als
   Zielwert unter 200 Zeilen.
7. Path-spezifische Regeln werden nicht durch blind identische Unterverzeichnisdateien
   gelöst; sie erfordern bei Bedarf eigene Consumer-Specs.
8. Die Bridge behauptet niemals, eine bereits laufende Session sei durch einen neuen
   Heartbeat-Publish aktualisiert worden.

**OQ-11 ist geschlossen.** Diese Entscheidung schließt OQ-07/OQ-18 ausdrücklich nicht.
