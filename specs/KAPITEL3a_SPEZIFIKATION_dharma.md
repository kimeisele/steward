# KAPITEL 3a — DETAILSPEZIFIKATION: Das Gewissen (Dharma)

> **Charakter:** Ausführbare Spezifikation für Claude Code. Baut auf Kap. 2 (Tag
> `v-earth-water-stable`) auf. Diese Version ist gegen den ECHTEN Substrat-Code
> verifiziert — die vier Fehler aus dem ersten Entwurf (TAMAS_BLOCK, Importpfade,
> Signatur, fehlende Permission-Brücke) sind behoben. Siehe Befund §18.
> **Ziel:** Dem Steward eine dharmische Identität geben und jede autonome Mission
> vor dem Dispatch durch `check_conscience` prüfen — Ahankara-Schutz.

---

## 0. ARCHITEKTUR-PRINZIP (verifiziert, nicht verhandelbar)

- **Ashrama = `Ashrama.GRIHASTHA`** (deklariert). Gewährt code_modify, git_*,
  pr_*, state_heal, genesis — NICHT admin/system_control. Dharmische Grenze:
  voller Erhalter, keine Governance-Hoheit. (Befund §17c)
- **Bhakti = `int(self.vedana.health * 100)`** (DYNAMISCH, aus gelebter Gesundheit
  — NICHT aus statischer VM-cell.integrity, siehe §18a). Schlechter Dienst →
  vedana.health sinkt → Bhakti sinkt → Rechte schwinden.
- **Der Riegel:** `check_conscience` gibt ein `ConscienceVerdict`-Objekt zurück.
  Prüfung: **`if not verdict.is_permitted:`** → Task auf `TaskStatus.BLOCKED`
  (Kap.-1-Mechanismus), kein stiller Tod.
- **Die Brücke (DAS FEHLENDE STÜCK, §18):** TaskIntents stehen NICHT in der
  `INTENT_PERMISSION_MAP`. Ohne Übersetzung würde das Gewissen ALLES durchwinken
  (Placebo). Wir brauchen ein explizites Mapping TaskIntent → Permission-Map-Key.
- **Fail-Closed (Gemini):** Ein NICHT gemappter Intent fällt auf `system_control`
  (admin-Recht, das GRIHASTHA NICHT hat) → wird blockiert. „Im Zweifel sperren",
  nie durchwinken. Verhindert, dass ein künftiger vergessener Intent das Tor
  umgeht.

---

## 1. PRE-FLIGHT — Claude Code verifiziert ZUERST (nur lesen, kein Code)

| # | Check | Erwartung | Wenn anders → |
|---|---|---|---|
| P1 | `git tag -l "v-earth-water-stable"` + `git branch --show-current` | Tag existiert, auf kap-2-Branch | erst Kap. 1+2 sichern |
| P2 | `python3 -c "from vibe_core.mahamantra.substrate.sankalpa.will import check_conscience; print('ok')"` | importierbar | Pfad anpassen, an uns berichten |
| P3 | `python3 -c "from vibe_core.mahamantra.protocols.sankalpa.types import Ashrama, ConscienceVerdict, GunaState; print('ok')"` | importierbar | Pfad anpassen |
| P4 | `python3 -c "from vibe_core.mahamantra.protocols.sankalpa.types import ConscienceVerdict; print(list(ConscienceVerdict.__dataclass_fields__))"` | enthält `is_permitted`, `guna`, `reason` (+ Extras ok) | Feldnamen an Realität anpassen |
| P5 | `grep -n "vedana_fn" steward/autonomy.py` | Engine hat `self.vedana_fn` (Callable) → `self.vedana_fn().health` | Bhakti-Quelle anpassen, an uns berichten |

> **VERIFIZIERT (Pre-Flight gelaufen):** P1-P3, P6 grün. P4: ConscienceVerdict hat
> ZUSÄTZLICH `ashrama, bhakti, required_permissions, missing_permissions` — alle
> erwarteten Felder da, Extras genutzt (missing_permissions → Log). P5: Engine hat
> KEIN `self.agent`, sondern `self.vedana_fn` (Callable) — Spec 2b/2c/2d entsprechend
> auf `vedana_fn()` + entkoppelte Ashrama-Übergabe korrigiert.
| P6 | Baseline grün (außer bekanntem test_briefing) | wie Kap. 1+2 | Baseline klären |

> **P2-P5 sind kritisch:** Sie verhindern genau die 4 Fehler aus §18. Erst wenn
> alle bestätigt, mit dem Eingriff beginnen. Bei Abweichung: ZUERST berichten.

---

## 2. DER EINGRIFF

### 2a. Intent→Permission-Brücke (REALITY: steward/intents.py oder eigene Datei)
Das fehlende Stück. Explizites Mapping von TaskIntent auf den Action-String, den
`check_conscience` über INTENT_PERMISSION_MAP versteht. Lesende Detektoren → `""`
(keine Rechte nötig = legitim erlaubt). Schreibende → echter Permission-Key.

```python
# Mapping TaskIntent → check_conscience intent_type-string.
# Lesende/detektierende Intents: "" (review_todos-artig, keine Schreibrechte).
# Schreibende Intents: ein Key aus INTENT_PERMISSION_MAP (types.py).
INTENT_TO_CONSCIENCE: dict[TaskIntent, str] = {
    # Lesend/detektierend — keine besonderen Rechte
    TaskIntent.HEALTH_CHECK: "review_todos",
    TaskIntent.SENSE_SCAN: "review_todos",
    TaskIntent.CI_CHECK: "review_todos",
    TaskIntent.FEDERATION_HEALTH: "review_todos",
    TaskIntent.CROSS_REPO_DIAGNOSTIC: "review_todos",
    TaskIntent.FEDERATION_GAP_SCAN: "review_todos",
    TaskIntent.SYNTHESIZE_BRIEFING: "doc_update",        # schreibt Doku
    # Schreibend — brauchen echte Rechte
    TaskIntent.HEAL_REPO: "contract_import_fix",          # code_modify
    TaskIntent.BOTTLENECK_ESCALATION: "contract_import_fix",  # code_modify
    TaskIntent.GOVERNANCE_BOUNTY: "contract_import_fix",  # code_modify
    TaskIntent.POST_MERGE: "commit_and_push",             # git
    TaskIntent.UPDATE_DEPS: "create_pr",                  # git_push + pr_create
    TaskIntent.REMOVE_DEAD_CODE: "create_pr",             # git_push + pr_create
}
```
> **DESIGN-ENTSCHEIDUNG (Kim/Opus vorzulegen):** Diese Zuordnung legt fest, WAS
> der Steward darf. Vorschlag oben: lesen=frei, schreiben=code_modify, git=git-Rechte.
> Alle gewählten Keys sind durch GRIHASTHA-Rechte gedeckt (§17c) → Steward arbeitet
> normal, aber ein hypothetischer `delete_file`/`shutdown`-Intent (admin) würde
> korrekt blockiert. Vor Implementierung bestätigen.

### 2b. Dharmische Identität (REALITY: steward/agent.py + Übergabe an Engine)
Die Identität gehört zum Agenten, aber die Prüfung passiert in der AutonomyEngine,
die den Agenten NICHT kennt (Entkopplung via Callables — wie `vedana_fn`). Daher:
```python
from vibe_core.mahamantra.protocols.sankalpa.types import Ashrama
# agent.py __init__ (~Z. 222, bei Persona):
self._ashrama = Ashrama.GRIHASTHA
# Bei der AutonomyEngine-Konstruktion: Ashrama ebenso entkoppelt übergeben,
# KONSISTENT zum vedana_fn-Muster (NICHT self.agent reinreichen — das bräche
# die bewusste Entkopplung der Engine):
#   AutonomyEngine(..., ashrama=self._ashrama)   bzw.   ashrama_fn=lambda: self._ashrama
```
> **Architektur-Begründung:** Die Engine bekommt `vedana_fn` bewusst als Callable
> (DI), damit sie den Agenten nicht kennen muss. Die Ashrama wird GENAUSO
> übergeben. `self.agent` in die Engine zu injizieren wäre die ENGERE, fragilere
> Kopplung — „vollständiger" aussehend, aber architektonisch schlechter. Richtig
> machen = die vorhandene Entkopplung respektieren, nicht den größeren Eingriff.

### 2c. Bhakti dynamisch (REALITY: steward/autonomy.py)
```python
def _current_bhakti(self) -> int:
    """Dynamische Hingabe aus gelebter Gesundheit, 0-100. Quelle: vedana_fn
    (die Engine kennt den Agenten NICHT — sie nutzt das injizierte Callable,
    konsistent zur bestehenden Architektur). NICHT statische VM-cell.integrity (§18a).
    """
    try:
        health = self.vedana_fn().health  # vedana_fn ist bereits in __init__ vorhanden
    except Exception:
        health = 0.99  # konservativer Fallback nur bei Nichtverfügbarkeit
    return int(max(0.0, min(1.0, health)) * 100)
```

### 2d. Gewissenstor vorschalten (REALITY: steward/autonomy.py, vor Z. 229)
```python
from vibe_core.mahamantra.substrate.sankalpa.will import check_conscience
from steward.intents import INTENT_TO_CONSCIENCE
# ... in _dispatch_next_task, VOR result = self.dispatch_intent(intent, task):

intent_str = INTENT_TO_CONSCIENCE.get(intent, "system_control")  # fail-CLOSED: unbekannt → admin-Recht → blockiert
verdict = check_conscience(intent_str, self._ashrama, self._current_bhakti())
if not verdict.is_permitted:
    logger.warning(
        "CONSCIENCE: intent %s NOT permitted (guna=%s, bhakti=%d, missing=%s): %s",
        intent.name, verdict.guna, self._current_bhakti(),
        verdict.missing_permissions, verdict.reason,  # missing_permissions = Diagnose-Gold (P4)
    )
    task_mgr.update_task(task.id, status=TaskStatus.BLOCKED)
    self._ledger.record_autonomous(intent.name, False)
    return None
# permitted → normaler Dispatch (Kap.-1/2-Logik unverändert):
result = self.dispatch_intent(intent, task)
```
> `self._ashrama` ist der in 2b an die Engine übergebene Wert (entkoppelt), NICHT
> `self.agent._ashrama`. `verdict.missing_permissions` (P4-Fund) ins Log → bei
> Blockade sieht man GENAU, welches Recht fehlte.
> **WICHTIG (Reihenfolge gegenüber Kap. 1):** Das Gewissen kommt VOR dem Dispatch.
> NO_HANDLER/BLOCKED-Logik aus Kap. 1+2 bleibt darunter unverändert. Ein
> unautorisierter Intent → BLOCKED durch das Gewissen; ein autorisierter, aber
> handler-loser → BLOCKED durch Kap. 1. Beide Wege sichtbar, kein stiller Tod.

---

## 3. DUALE VERIFIKATIONSTABELLE

| Eingriff | LAW | REALITY (steward) | Tests |
|---|---|---|---|
| 2a Brücke | — | steward/intents.py | Mapping deckt alle 13 Intents |
| 2b Ashrama | — | steward/agent.py | `agent._ashrama == GRIHASTHA` |
| 2c Bhakti | — | steward/autonomy.py | skaliert mit vedana.health |
| 2d Tor | — | steward/autonomy.py | unerlaubt → BLOCKED, erlaubt → dispatch |

---

## 4. NEUE TESTS (echte Objekte, KEIN MagicMock — Hausstil)

1. `test_steward_has_grihastha_identity`: `agent._ashrama == Ashrama.GRIHASTHA`.
2. `test_bhakti_scales_with_vedana`: vedana.health 1.0/0.5/0.0 → bhakti 100/50/0.
3. `test_conscience_allows_authorized_intent`: HEAL_REPO (→contract_import_fix,
   code_modify) bei GRIHASTHA+hohem Bhakti → `verdict.is_permitted is True`,
   Dispatch läuft normal.
4. `test_conscience_blocks_unauthorized`: ein Intent gemappt auf einen
   admin-Key (z.B. testweise `delete_file`) → `is_permitted False` → Task BLOCKED,
   kein dispatch.
5. `test_low_bhakti_revokes_borderline`: vedana.health < 0.5 (bhakti<50) → ein
   Intent, der nur per Bhakti-Override (≥50) erlaubt wäre, wird jetzt BLOCKED.
6. `test_kap1_kap2_regression`: unbekannter Intent → weiterhin NO_HANDLER/BLOCKED;
   Membran-Intent mit Payload → weiterhin Problem-String (Gewissen lässt durch).
7. `test_unmapped_intent_fails_closed`: ein nicht in INTENT_TO_CONSCIENCE gemappter
   Intent → fällt auf `system_control` → `is_permitted False` → BLOCKED (nie erlaubt).

---

## 5. WAS DIESER EINGRIFF BEWUSST NICHT TUT

- Keine neue autonome Trigger-Schleife (das ist Kap. 3b — is_stuck→Mission).
  Hier wird nur das Schutzgitter aktiviert, das Kap. 3b dann vorfindet.
- Kein statisches Bhakti (nutzt lebendige vedana.health).
- Keine Änderung an cell.integrity / VM (das ist die geborene, statische Natur).
- Keine admin/system_control-Rechte für den Steward (dharmische Grenze).

---

## 6. ERWARTETE WIRKUNG

- Jede autonome Mission wird vor Ausführung dharmisch geprüft. Unautorisierte
  Intents landen sichtbar als BLOCKED (Gewissen + Kap.-1-Immunsystem greifen
  zusammen).
- Bhakti lebt: sinkt der Dienst in Qualität (vedana.health fällt), schwinden die
  Rechte automatisch. Steigt er, kehren sie zurück. Hingabe im gelebten Dienst.
- Das Fundament für Kap. 3b (Feuer / is_stuck→Mission) steht: autonome Trigger
  treffen ab dann auf ein aktives Gewissen.

---

*Ende Kap-3a-Spezifikation. Vor Übergabe: Pre-Flight P2-P5 (verhindern die §18-
Fehler) + Bestätigung der Intent→Permission-Zuordnung (§2a, Wesensentscheidung).*
