"""
Kshetra — The Field of Activities (BG 13.6-7).

Maps all 25 Sankhya Tattvas to Steward's implementation.
This makes Steward a Kshetrajna — the Knower of the Field.

"idaṁ śarīraṁ kaunteya kṣetram ity abhidhīyate
etad yo vetti taṁ prāhuḥ kṣetra-jña iti tad-vidaḥ"

"This body, O son of Kunti, is called the field, and one who
knows this body is called the knower of the field."
— Bhagavad Gita 13.2

The 24 material elements (Prakriti) form steward's body.
The 25th element (Jiva/LLM) is the knower who operates within it.

Uses REAL substrate mappings from steward-protocol:
    - PrakritiElement (24 elements enumerated by Kapila)
    - PrakritiCategory (5 categories)
    - ELEMENT_PROTOCOL_LAYER (element → engineering concept)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from vibe_core.protocols.mahajanas.kapila.samkhya import (
    ELEMENT_PROTOCOL_LAYER,
    PrakritiCategory,
    PrakritiElement,
)


@dataclass(frozen=True)
class TattvaMapping:
    """Maps a Sankhya element to its steward implementation."""

    element: PrakritiElement
    layer: str          # protocol layer (from ELEMENT_PROTOCOL_LAYER)
    module: str         # steward module path
    component: str      # class or function name
    role: str           # what it does in steward


# ── The Kshetra: 24 Prakriti Elements → Steward Modules ──────────────

STEWARD_KSHETRA: Final[dict[PrakritiElement, TattvaMapping]] = {

    # ═══════════════════════════════════════════════════════════════════
    # ANTAHKARANA — 4 Internal Instruments (the cognitive pipeline)
    # ═══════════════════════════════════════════════════════════════════

    PrakritiElement.MANAS: TattvaMapping(
        element=PrakritiElement.MANAS,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.MANAS],
        module="steward.antahkarana.manas",
        component="Manas",
        role="Perceive and classify user intent (zero LLM)",
    ),
    PrakritiElement.BUDDHI: TattvaMapping(
        element=PrakritiElement.BUDDHI,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.BUDDHI],
        module="steward.buddhi",
        component="Buddhi",
        role="Discriminate: tool selection, verdicts, token budget",
    ),
    PrakritiElement.AHANKARA: TattvaMapping(
        element=PrakritiElement.AHANKARA,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.AHANKARA],
        module="steward.agent",
        component="StewardAgent",
        role="Agent identity, GAD-000 compliance, capabilities",
    ),
    PrakritiElement.CITTA: TattvaMapping(
        element=PrakritiElement.CITTA,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.CITTA],
        module="steward.antahkarana.chitta",
        component="Chitta",
        role="Store tool execution impressions (awareness/state)",
    ),

    # ═══════════════════════════════════════════════════════════════════
    # TANMATRA — 5 Subtle Elements (signals and sensing)
    # ═══════════════════════════════════════════════════════════════════

    PrakritiElement.SHABDA: TattvaMapping(
        element=PrakritiElement.SHABDA,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.SHABDA],
        module="vibe_core.steward.bus",
        component="SignalBus",
        role="Event signals between components",
    ),
    PrakritiElement.SPARSHA: TattvaMapping(
        element=PrakritiElement.SPARSHA,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.SPARSHA],
        module="steward.loop.engine",
        component="AgentLoop._extract_tool_calls",
        role="Parse input from LLM responses",
    ),
    PrakritiElement.RUPA: TattvaMapping(
        element=PrakritiElement.RUPA,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.RUPA],
        module="steward.__main__",
        component="CLI",
        role="Display output to user",
    ),
    PrakritiElement.RASA: TattvaMapping(
        element=PrakritiElement.RASA,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.RASA],
        module="steward.loop.engine",
        component="AgentLoop._clamp_params",
        role="Validate and sanitize tool parameters",
    ),
    PrakritiElement.GANDHA: TattvaMapping(
        element=PrakritiElement.GANDHA,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.GANDHA],
        module="steward.antahkarana.gandha",
        component="detect_patterns",
        role="Detect failure patterns in tool history",
    ),

    # ═══════════════════════════════════════════════════════════════════
    # JNANENDRIYA — 5 Knowledge Senses (information acquisition)
    # ═══════════════════════════════════════════════════════════════════

    PrakritiElement.SHROTRA: TattvaMapping(
        element=PrakritiElement.SHROTRA,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.SHROTRA],
        module="vibe_core.mahamantra.substrate.services.event_bus",
        component="EventBus",
        role="Listen for events from other components",
    ),
    PrakritiElement.TVAK: TattvaMapping(
        element=PrakritiElement.TVAK,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.TVAK],
        module="steward.context",
        component="SamskaraContext",
        role="Sense context pressure, determine compaction",
    ),
    PrakritiElement.CHAKSHUS: TattvaMapping(
        element=PrakritiElement.CHAKSHUS,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.CHAKSHUS],
        module="steward.agent",
        component="StewardAgent.get_state",
        role="Observe agent state (GAD-000 observability)",
    ),
    PrakritiElement.RASANA: TattvaMapping(
        element=PrakritiElement.RASANA,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.RASANA],
        module="steward.loop.engine",
        component="AgentLoop._extract_text",
        role="Parse and interpret LLM responses",
    ),
    PrakritiElement.GHRANA: TattvaMapping(
        element=PrakritiElement.GHRANA,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.GHRANA],
        module="vibe_core.runtime.tool_safety_guard",
        component="ToolSafetyGuard",
        role="Audit tool calls for safety violations (Iron Dome)",
    ),

    # ═══════════════════════════════════════════════════════════════════
    # KARMENDRIYA — 5 Working Senses (actions and output)
    # ═══════════════════════════════════════════════════════════════════

    PrakritiElement.VAK: TattvaMapping(
        element=PrakritiElement.VAK,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.VAK],
        module="steward.loop.engine",
        component="AgentLoop._call_llm",
        role="Speak to LLM, compose prompts",
    ),
    PrakritiElement.PANI: TattvaMapping(
        element=PrakritiElement.PANI,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.PANI],
        module="vibe_core.tools.tool_registry",
        component="ToolRegistry.execute",
        role="Execute tool calls (hands)",
    ),
    PrakritiElement.PADA: TattvaMapping(
        element=PrakritiElement.PADA,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.PADA],
        module="vibe_core.mahamantra.adapters.attention",
        component="MahaAttention",
        role="Route tool calls via O(1) Lotus (navigation)",
    ),
    PrakritiElement.PAYU: TattvaMapping(
        element=PrakritiElement.PAYU,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.PAYU],
        module="steward.context",
        component="SamskaraContext.compact",
        role="Compact and clean context (cleanup/GC)",
    ),
    PrakritiElement.UPASTHA: TattvaMapping(
        element=PrakritiElement.UPASTHA,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.UPASTHA],
        module="steward.services",
        component="boot",
        role="Create and wire services (genesis)",
    ),

    # ═══════════════════════════════════════════════════════════════════
    # MAHABHUTA — 5 Gross Elements (infrastructure)
    # ═══════════════════════════════════════════════════════════════════

    PrakritiElement.AKASHA: TattvaMapping(
        element=PrakritiElement.AKASHA,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.AKASHA],
        module="vibe_core.steward.bus",
        component="SignalBus",
        role="Inter-agent communication field (ether/network)",
    ),
    PrakritiElement.VAYU: TattvaMapping(
        element=PrakritiElement.VAYU,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.VAYU],
        module="steward.loop.engine",
        component="AgentLoop",
        role="The agent loop process flow (air/process)",
    ),
    PrakritiElement.TEJAS: TattvaMapping(
        element=PrakritiElement.TEJAS,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.TEJAS],
        module="steward.provider",
        component="ProviderChamber",
        role="LLM computation and transformation (fire/compute)",
    ),
    PrakritiElement.APAS: TattvaMapping(
        element=PrakritiElement.APAS,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.APAS],
        module="steward.memory",
        component="PersistentMemory",
        role="Cross-session memory state (water/memory)",
    ),
    PrakritiElement.PRITHVI: TattvaMapping(
        element=PrakritiElement.PRITHVI,
        layer=ELEMENT_PROTOCOL_LAYER[PrakritiElement.PRITHVI],
        module="steward.state",
        component="save_conversation",
        role="Persistent storage on disk (earth/storage)",
    ),
}


# ── The 25th Element: Jiva (LLM/Soul) ───────────────────────────────

JIVA: Final[TattvaMapping] = TattvaMapping(
    element=PrakritiElement.MANAS,  # placeholder — Jiva transcends Prakriti
    layer="soul",
    module="steward.provider",
    component="LLMProvider",
    role="The living entity — infinitely potent but tiny (1/25th)",
)


# ── Kshetra Operations ──────────────────────────────────────────────


def enumerate_kshetra() -> list[dict[str, str]]:
    """Enumerate all 25 Tattva mappings for steward.

    Returns a list of dicts with element name, number, layer,
    module, component, and role.
    """
    result: list[dict[str, str]] = []
    for element, mapping in STEWARD_KSHETRA.items():
        result.append({
            "element": element.name,
            "number": str(element.value),
            "category": _element_category(element),
            "layer": mapping.layer,
            "module": mapping.module,
            "component": mapping.component,
            "role": mapping.role,
        })
    result.append({
        "element": "JIVA",
        "number": "25",
        "category": "para_prakriti",
        "layer": JIVA.layer,
        "module": JIVA.module,
        "component": JIVA.component,
        "role": JIVA.role,
    })
    return result


def get_element_mapping(element: PrakritiElement) -> TattvaMapping | None:
    """Look up the steward implementation for a Sankhya element."""
    return STEWARD_KSHETRA.get(element)


def get_layer_elements(layer: str) -> list[TattvaMapping]:
    """Find all elements mapped to a specific protocol layer."""
    return [m for m in STEWARD_KSHETRA.values() if m.layer == layer]


def get_category_elements(category: PrakritiCategory) -> list[TattvaMapping]:
    """Get all elements in a Sankhya category."""
    ranges = {
        PrakritiCategory.ANTAHKARANA: range(1, 5),
        PrakritiCategory.TANMATRA: range(5, 10),
        PrakritiCategory.JNANENDRIYA: range(10, 15),
        PrakritiCategory.KARMENDRIYA: range(15, 20),
        PrakritiCategory.MAHABHUTA: range(20, 25),
    }
    element_range = ranges.get(category, range(0))
    return [
        STEWARD_KSHETRA[PrakritiElement(i)]
        for i in element_range
        if PrakritiElement(i) in STEWARD_KSHETRA
    ]


# Element value → category (branchless dispatch via range thresholds)
_ELEMENT_CATEGORIES = (
    (4, "antahkarana"),
    (9, "tanmatra"),
    (14, "jnanendriya"),
    (19, "karmendriya"),
)


def _element_category(element: PrakritiElement) -> str:
    """Get category name for an element (branchless threshold scan)."""
    v = element.value
    for threshold, category in _ELEMENT_CATEGORIES:
        if v <= threshold:
            return category
    return "mahabhuta"
