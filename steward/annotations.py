"""
Annotations — validated knowledge store using existing substrate primitives.

Agent-contributed knowledge goes through a neuro-symbolic validation pipeline
before it can influence CLAUDE.md generation.

Validation pipeline (submit):
  1. MahaCompression → deterministic seed (dedup + alignment)
  2. North Star XOR  → alignment score (reject misaligned)
  3. Seed similarity  → dedup (reject near-duplicates)

Lifecycle (via existing substrate):
  - SynapseStore: annotation weights stored as `ann:{id}` → `credibility`
  - HebbianSynaptic.decay(): temporal regression toward 0.5 in MOKSHA phase
  - HebbianSynaptic.trim(): prunes weakest entries when capacity exceeded
  - Reinforcement: Buddhi calls reinforce() when agent uses/ignores knowledge

Annotation metadata (text, category, file_ref) stored in PersistentMemory.
Annotation credibility (weight) stored in SynapseStore — same system
that tracks immune remedy confidence and tool success rates.

Categories:
  - invariant: things that must NEVER change
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

# SynapseStore key prefix for annotation weights
_SYNAPSE_PREFIX = "ann"
_SYNAPSE_ACTION = "credibility"


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
    created_at: float = field(default_factory=time.time)


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
      4. Store metadata in PersistentMemory, weight in SynapseStore
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

    # 4. Store metadata in PersistentMemory
    annotation = Annotation(
        id=annotation_id,
        text=text,
        category=category,
        source=source,
        file_ref=file_ref,
        seed=seed,
        alignment=alignment,
        created_at=time.time(),
    )
    _store_metadata(annotation, existing)

    # 5. Initialize weight in SynapseStore at 0.5
    _synapse_set(annotation_id, 0.5)

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


def collect_validated() -> list[Annotation]:
    """Collect annotations that pass alignment + confidence thresholds.

    Weight is read from SynapseStore (which applies HebbianSynaptic.decay()
    in MOKSHA phase). No custom decay logic here.
    """
    all_annotations = load_all()
    validated: list[Annotation] = []

    for ann in all_annotations:
        weight = _synapse_get(ann.id)
        if weight >= CONFIDENCE_THRESHOLD and ann.alignment >= ALIGNMENT_THRESHOLD:
            validated.append(ann)

    # Sort by weight (highest first)
    validated.sort(key=lambda a: _synapse_get(a.id), reverse=True)
    return validated


def reinforce(annotation_id: str, success: bool) -> None:
    """Update Hebbian weight via SynapseStore.

    Uses the same increment/decrement that immune.py uses for
    remedy confidence tracking.
    """
    store = _get_synapse_store()
    if store is None:
        return

    trigger = f"{_SYNAPSE_PREFIX}:{annotation_id}"
    if success:
        store.increment_weight(trigger, _SYNAPSE_ACTION, delta=0.05, max_weight=0.95)
    else:
        store.decrement_weight(trigger, _SYNAPSE_ACTION, delta=0.05, min_weight=0.1)

    logger.debug("Annotation %s reinforced: success=%s", annotation_id, success)


def decay_all() -> int:
    """Apply HebbianSynaptic temporal decay to all annotation weights.

    Called from MOKSHA phase hook. Uses the substrate's own decay()
    which regresses toward 0.5: w = w + factor * (0.5 - w)

    Returns number of weights decayed.
    """
    store = _get_synapse_store()
    if store is None:
        return 0

    # Access the underlying HebbianSynaptic if available
    synaptic = getattr(store, "_synaptic", None) or getattr(store, "synaptic", None)
    if synaptic is not None and hasattr(synaptic, "decay"):
        count = synaptic.decay(factor=0.01)
        if count > 0:
            logger.debug("Annotation decay: %d weights regressed", count)
        return count

    return 0


def trim(max_entries: int = 50) -> int:
    """Prune weakest annotation weights via HebbianSynaptic.trim().

    Called from MOKSHA phase hook. Removes weights closest to 0.5
    (least decisive) when capacity is exceeded.
    """
    store = _get_synapse_store()
    if store is None:
        return 0

    synaptic = getattr(store, "_synaptic", None) or getattr(store, "synaptic", None)
    if synaptic is not None and hasattr(synaptic, "trim"):
        count = synaptic.trim(max_entries=max_entries)
        if count > 0:
            logger.debug("Annotation trim: %d weakest entries pruned", count)
        return count

    return 0


def load_all() -> list[Annotation]:
    """Load all annotation metadata from PersistentMemory."""
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


def format_for_briefing(annotations: list[Annotation] | None = None) -> str:
    """Format validated annotations into a briefing-ready section.

    Groups by category, ordered by priority.
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


# ── SynapseStore Integration ─────────────────────────────────────────


def _get_synapse_store():
    """Get SynapseStore from ServiceRegistry."""
    try:
        from steward.services import SVC_SYNAPSE_STORE
        from vibe_core.di import ServiceRegistry

        return ServiceRegistry.get(SVC_SYNAPSE_STORE)
    except Exception:
        return None


def _synapse_get(annotation_id: str) -> float:
    """Get annotation weight from SynapseStore."""
    store = _get_synapse_store()
    if store is None:
        return 0.5  # neutral default

    trigger = f"{_SYNAPSE_PREFIX}:{annotation_id}"
    weight = store.get_weight(trigger, _SYNAPSE_ACTION)
    if weight is None:
        return 0.5
    return float(weight)


def _synapse_set(annotation_id: str, weight: float) -> None:
    """Set annotation weight in SynapseStore."""
    store = _get_synapse_store()
    if store is None:
        return

    trigger = f"{_SYNAPSE_PREFIX}:{annotation_id}"
    store.set_weight(trigger, _SYNAPSE_ACTION, weight, defer_save=True)


# ── Compression & Alignment ──────────────────────────────────────────


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

    return 0.5


def _seed_similarity(seed_a: int, seed_b: int) -> float:
    """Compute similarity between two seeds (1.0 = identical, 0.0 = maximally different)."""
    return 1.0 - min(bin(seed_a ^ seed_b).count("1") / 32.0, 1.0)


# ── Metadata Persistence ─────────────────────────────────────────────
# Annotation text/category/file_ref stored in PersistentMemory.
# Weight/credibility stored SEPARATELY in SynapseStore.


def _store_metadata(annotation: Annotation, existing: list[Annotation]) -> None:
    """Store annotation metadata in PersistentMemory."""
    all_annotations = existing + [annotation]
    _save_all_metadata(all_annotations)


def _save_all_metadata(annotations: list[Annotation]) -> None:
    """Save all annotation metadata to PersistentMemory."""
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
        created_at=d.get("created_at", 0.0),
    )
