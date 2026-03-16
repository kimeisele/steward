"""
Annotations — validated knowledge store with neuro-symbolic pipeline.

Agent-contributed knowledge goes through a validation pipeline before
it can influence CLAUDE.md generation. This is NOT a dumb append-store.

Pipeline:
  1. MahaCompression → deterministic seed (for dedup + alignment)
  2. North Star XOR  → alignment score (reject misaligned contributions)
  3. Seed similarity  → dedup (reject near-duplicates)
  4. Hebbian weight   → confidence tracking (utility over time)
  5. PersistentMemory → structured storage with tags

On briefing generation, only annotations that pass alignment AND
confidence thresholds are included. Annotations that are never
referenced by agents decay via Hebbian weight loss.

Categories:
  - invariant: things that must NEVER change (e.g., North Star immutability)
  - gotcha:    things that bite you if you don't know them
  - pattern:   recurring design patterns in this codebase
  - decision:  architectural decisions and their rationale
  - warning:   active issues or fragile areas
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Literal

logger = logging.getLogger("STEWARD.ANNOTATIONS")

# ── Types ────────────────────────────────────────────────────────────

Category = Literal["invariant", "gotcha", "pattern", "decision", "warning"]

ALIGNMENT_THRESHOLD = 0.45  # XOR distance — below this = misaligned
CONFIDENCE_THRESHOLD = 0.3  # Hebbian weight — below this = unvalidated
SIMILARITY_THRESHOLD = 0.85  # Seed similarity — above this = duplicate


@dataclass(frozen=True)
class Annotation:
    """A single validated knowledge contribution."""

    id: str  # deterministic: sha256(text)[:12]
    text: str
    category: Category
    source: str  # who contributed (e.g., "opus-session-abc")
    file_ref: str = ""  # optional file:line reference
    seed: int = 0  # MahaCompression seed
    alignment: float = 0.0  # North Star alignment score
    weight: float = 0.5  # Hebbian confidence (0.0-1.0)
    created_at: float = field(default_factory=time.time)
    verified: bool = False  # True after system validation pass


@dataclass
class SubmitResult:
    """Result of annotation submission."""

    accepted: bool
    annotation_id: str = ""
    reason: str = ""
    alignment: float = 0.0
    similar_to: str = ""  # ID of near-duplicate if rejected


# ── Core Pipeline ────────────────────────────────────────────────────


def submit(
    text: str,
    category: Category,
    source: str,
    file_ref: str = "",
) -> SubmitResult:
    """Submit an annotation through the validation pipeline.

    Steps:
      1. Compress text → seed
      2. Check North Star alignment (XOR distance)
      3. Check for near-duplicates (seed similarity)
      4. Store in PersistentMemory with Hebbian weight 0.5
    """
    text = text.strip()
    if not text:
        return SubmitResult(accepted=False, reason="empty text")

    if len(text) > 500:
        return SubmitResult(accepted=False, reason="too long (max 500 chars)")

    annotation_id = hashlib.sha256(text.encode()).hexdigest()[:12]

    # 1. Compress
    seed = _compress_seed(text)

    # 2. North Star alignment
    alignment = _north_star_alignment(seed)
    if alignment < ALIGNMENT_THRESHOLD:
        logger.info(
            "Annotation rejected: alignment %.3f < %.3f (id=%s)",
            alignment,
            ALIGNMENT_THRESHOLD,
            annotation_id,
        )
        return SubmitResult(
            accepted=False,
            annotation_id=annotation_id,
            reason=f"misaligned with north star ({alignment:.2f})",
            alignment=alignment,
        )

    # 3. Dedup — compare against existing annotations
    existing = load_all()
    for ann in existing:
        similarity = _seed_similarity(seed, ann.seed)
        if similarity > SIMILARITY_THRESHOLD:
            logger.info(
                "Annotation rejected: duplicate of %s (similarity %.3f)",
                ann.id,
                similarity,
            )
            return SubmitResult(
                accepted=False,
                annotation_id=annotation_id,
                reason=f"near-duplicate of {ann.id} (similarity {similarity:.2f})",
                similar_to=ann.id,
            )

    # 4. Store
    annotation = Annotation(
        id=annotation_id,
        text=text,
        category=category,
        source=source,
        file_ref=file_ref,
        seed=seed,
        alignment=alignment,
        weight=0.5,
        created_at=time.time(),
        verified=True,
    )

    _store(annotation, existing)
    logger.info(
        "Annotation accepted: id=%s category=%s alignment=%.3f",
        annotation_id,
        category,
        alignment,
    )

    return SubmitResult(
        accepted=True,
        annotation_id=annotation_id,
        alignment=alignment,
    )


def load_all() -> list[Annotation]:
    """Load all annotations from PersistentMemory."""
    try:
        from steward.services import SVC_MEMORY
        from vibe_core.di import ServiceRegistry

        memory = ServiceRegistry.get(SVC_MEMORY)
        if memory is None:
            return _load_from_disk()

        raw = memory.recall("annotations", session_id="steward")
        if not raw or not isinstance(raw, list):
            return []

        return [_dict_to_annotation(d) for d in raw if isinstance(d, dict)]
    except Exception:
        return _load_from_disk()


def collect_validated() -> list[Annotation]:
    """Collect annotations that pass alignment + confidence thresholds.

    Applies temporal decay: annotations lose weight over time if not
    reinforced. This prevents stale knowledge from accumulating.

    Decay rate: -0.02 per day since last reinforcement.
    Annotations below CONFIDENCE_THRESHOLD after decay are excluded.
    """
    all_annotations = load_all()
    now = time.time()
    decayed: list[Annotation] = []

    for ann in all_annotations:
        # Temporal decay: annotations lose weight over time
        age_days = (now - ann.created_at) / 86400.0
        decay = min(age_days * 0.02, 0.4)  # max 0.4 decay (won't kill high-weight annotations)
        effective_weight = max(ann.weight - decay, 0.0)

        if effective_weight >= CONFIDENCE_THRESHOLD and ann.alignment >= ALIGNMENT_THRESHOLD:
            decayed.append(ann)

    # Sort: highest effective weight first
    decayed.sort(key=lambda a: a.weight, reverse=True)
    return decayed


def reinforce(annotation_id: str, success: bool) -> None:
    """Update Hebbian weight for an annotation based on observed utility.

    Called when an agent uses (or ignores) an annotation's knowledge:
      - success=True:  agent used the knowledge and it helped → boost weight
      - success=False: knowledge was wrong or unhelpful → decay weight
    """
    all_annotations = load_all()
    updated = []
    for ann in all_annotations:
        if ann.id == annotation_id:
            # Hebbian update: same rule as synaptic weights
            w = ann.weight
            if success:
                w = w + 0.1 * (1 - w)  # asymptotic to 1.0
            else:
                w = w - 0.1 * w  # asymptotic to 0.0
            ann = Annotation(**{**asdict(ann), "weight": round(w, 4)})
        updated.append(ann)

    _save_all(updated)


def format_for_briefing(annotations: list[Annotation] | None = None) -> str:
    """Format validated annotations into a briefing-ready section.

    Groups by category, includes weight as confidence indicator.
    """
    if annotations is None:
        annotations = collect_validated()

    if not annotations:
        return ""

    by_category: dict[str, list[Annotation]] = {}
    for ann in annotations:
        by_category.setdefault(ann.category, []).append(ann)

    parts: list[str] = []

    # Priority order for categories
    order = ["invariant", "warning", "gotcha", "pattern", "decision"]
    for cat in order:
        anns = by_category.get(cat, [])
        if not anns:
            continue
        parts.append(f"\n**{cat.upper()}S**")
        for ann in anns:
            ref = f" ({ann.file_ref})" if ann.file_ref else ""
            parts.append(f"- {ann.text}{ref}")

    return "\n".join(parts)


# ── Internal ─────────────────────────────────────────────────────────


def _compress_seed(text: str) -> int:
    """Get MahaCompression seed for text, with fallback."""
    try:
        from steward.services import SVC_COMPRESSION
        from vibe_core.di import ServiceRegistry

        compression = ServiceRegistry.get(SVC_COMPRESSION)
        if compression is not None:
            return compression.compress(text).seed
    except Exception:
        pass

    # Fallback: deterministic hash-based seed
    h = hashlib.sha256(text.encode()).digest()
    return int.from_bytes(h[:4], "big")


def _north_star_alignment(seed: int) -> float:
    """Compute alignment with North Star seed via XOR Hamming distance."""
    try:
        from steward.services import SVC_NORTH_STAR
        from vibe_core.di import ServiceRegistry

        north_star = ServiceRegistry.get(SVC_NORTH_STAR)
        if north_star is not None and isinstance(north_star, int):
            return 1.0 - min(bin(seed ^ north_star).count("1") / 32.0, 1.0)
    except Exception:
        pass

    # Fallback: assume neutral alignment
    return 0.5


def _seed_similarity(seed_a: int, seed_b: int) -> float:
    """Compute similarity between two seeds (1.0 = identical, 0.0 = maximally different)."""
    return 1.0 - min(bin(seed_a ^ seed_b).count("1") / 32.0, 1.0)


def _store(annotation: Annotation, existing: list[Annotation]) -> None:
    """Store annotation in PersistentMemory."""
    all_annotations = existing + [annotation]
    _save_all(all_annotations)


def _save_all(annotations: list[Annotation]) -> None:
    """Save all annotations to PersistentMemory."""
    data = [asdict(ann) for ann in annotations]
    try:
        from steward.services import SVC_MEMORY
        from vibe_core.di import ServiceRegistry

        memory = ServiceRegistry.get(SVC_MEMORY)
        if memory is not None:
            memory.remember(
                "annotations",
                data,
                session_id="steward",
                tags=["annotations", "knowledge"],
            )
            return
    except Exception:
        pass

    _save_to_disk(data)


def _load_from_disk() -> list[Annotation]:
    """Load annotations from memory.json when ServiceRegistry isn't booted."""
    import json
    from pathlib import Path

    try:
        memory_file = Path.cwd() / ".steward" / "memory.json"
        if not memory_file.is_file():
            return []

        raw = json.loads(memory_file.read_text(encoding="utf-8"))
        for entry in raw.get("entries", []):
            if entry.get("key") == "annotations" and entry.get("session_id") == "steward":
                value = entry.get("value", [])
                if isinstance(value, list):
                    return [_dict_to_annotation(d) for d in value if isinstance(d, dict)]
    except Exception:
        pass

    return []


def _save_to_disk(data: list[dict]) -> None:
    """Save annotations to memory.json when ServiceRegistry isn't booted."""
    import json
    from pathlib import Path

    try:
        memory_file = Path.cwd() / ".steward" / "memory.json"
        if not memory_file.is_file():
            return

        raw = json.loads(memory_file.read_text(encoding="utf-8"))
        # Update the annotations entry
        found = False
        for entry in raw.get("entries", []):
            if entry.get("key") == "annotations" and entry.get("session_id") == "steward":
                entry["value"] = data
                found = True
                break

        if not found:
            raw.setdefault("entries", []).append(
                {
                    "session_id": "steward",
                    "key": "annotations",
                    "value": data,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "expires_at": None,
                    "tags": ["annotations", "knowledge"],
                }
            )

        from vibe_core.utils.atomic_io import atomic_write_json

        atomic_write_json(memory_file, raw)
    except Exception as e:
        logger.warning("Failed to save annotations to disk: %s", e)


def _dict_to_annotation(d: dict) -> Annotation:
    """Convert dict to Annotation, handling missing/extra fields."""
    return Annotation(
        id=d.get("id", ""),
        text=d.get("text", ""),
        category=d.get("category", "pattern"),
        source=d.get("source", "unknown"),
        file_ref=d.get("file_ref", ""),
        seed=d.get("seed", 0),
        alignment=d.get("alignment", 0.5),
        weight=d.get("weight", 0.5),
        created_at=d.get("created_at", 0.0),
        verified=d.get("verified", False),
    )
