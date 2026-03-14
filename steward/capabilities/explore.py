"""
Explore Capability — MOLECULAR level codebase cognition.

Composes existing vibe_core infrastructure into a single deterministic
exploration circuit. Zero LLM tokens. Pure infrastructure cognition.

Pipeline:
  1. CodeScanner (AST) → populate KnowledgeGraph with target codebase
  2. KnowledgeResolver → query graph for focus-relevant nodes
  3. GunaClassifier → classify state quality of matched paths
  4. MahaCompression → compress each node to intent seed
  5. Output: ExploreMap (list of ExploreEntry with seed, guna, type, relations)

The agent receives a compressed intent-map, not raw text.
Navigation is O(1) via seed → MahaAttention lookup.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from vibe_core.knowledge.code_scanner import CodeScanner
from vibe_core.knowledge.graph import UnifiedKnowledgeGraph
from vibe_core.knowledge.schema import NodeType, RelationType
from vibe_core.mahamantra.adapters.compression import MahaCompression
from vibe_core.protocols.capability import CapabilityResult, CapabilityType
from vibe_core.state.guna_classifier import GunaClassifier, StateGuna

logger = logging.getLogger("STEWARD.CAPABILITY.EXPLORE")


# ── Output Types ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExploreEntry:
    """Single node in the explore map — compressed, navigable."""

    name: str  # Module/class/function name
    node_type: str  # module, class, function, interface
    file: str  # Relative path
    line: int  # Definition line
    seed: int  # MahaCompression 32-bit seed
    guna: str  # sattva/rajas/tamas
    relations: tuple[str, ...] = ()  # Connected node names (imports, inherits, calls)
    methods: tuple[str, ...] = ()  # For classes: method names


@dataclass
class ExploreMap:
    """Compressed intent-map of a codebase. The agent's radar."""

    target: str  # Directory explored
    focus: str  # What the agent was looking for
    entries: list[ExploreEntry] = field(default_factory=list)
    scan_time_ms: float = 0.0
    total_nodes: int = 0
    total_edges: int = 0

    def to_compact(self) -> str:
        """Compact string representation for the agent (minimal tokens)."""
        if not self.entries:
            return f"Explored {self.target}: no relevant symbols found for '{self.focus}'"

        lines = [f"=== {self.target} ({len(self.entries)} symbols, {self.focus}) ==="]
        for e in self.entries[:30]:  # Cap at 30 entries
            rels = f" → {','.join(e.relations[:5])}" if e.relations else ""
            methods = f" [{','.join(e.methods[:5])}]" if e.methods else ""
            lines.append(
                f"  {e.guna[0].upper()} {e.node_type:8s} {e.name}"
                f" ({e.file}:{e.line}){methods}{rels}"
            )
        return "\n".join(lines)


# ── Capability Implementation ────────────────────────────────────────


class ExploreCapability:
    """MOLECULAR Capability: compose CodeScanner + KnowledgeGraph + Compression.

    Implements the Capability protocol from vibe_core.
    Registered as a Tool in steward's ToolRegistry so the LLM can call it.
    """

    @property
    def capability_id(self) -> str:
        return "explore_codebase"

    @property
    def capability_type(self) -> CapabilityType:
        return CapabilityType.MOLECULAR

    @property
    def description(self) -> str:
        return (
            "Explore a codebase and return a compressed intent-map. "
            "Uses AST analysis, knowledge graph, and guna classification. "
            "Zero LLM tokens — pure deterministic cognition."
        )

    @property
    def parameters_schema(self) -> Dict[str, object]:
        return {
            "target": {
                "type": "string",
                "required": True,
                "description": "Directory to explore (absolute path)",
            },
            "focus": {
                "type": "string",
                "required": False,
                "description": "What to focus on (e.g. 'federation', 'authentication'). Empty = full scan.",
            },
        }

    def validate(self, parameters: Dict[str, object]) -> None:
        target = parameters.get("target")
        if not target or not isinstance(target, str):
            raise ValueError("target must be a non-empty string path")
        if not Path(target).is_dir():
            raise ValueError(f"target directory not found: {target}")

    def execute(self, parameters: Dict[str, object]) -> CapabilityResult:
        target = Path(str(parameters["target"]))
        focus = str(parameters.get("focus", ""))

        t0 = time.monotonic()

        try:
            explore_map = _explore(target, focus)
            duration_ms = (time.monotonic() - t0) * 1000
            explore_map.scan_time_ms = duration_ms

            return CapabilityResult(
                success=True,
                output=explore_map.to_compact(),
                metadata={
                    "entries": len(explore_map.entries),
                    "total_nodes": explore_map.total_nodes,
                    "total_edges": explore_map.total_edges,
                    "scan_time_ms": duration_ms,
                },
                capability_id=self.capability_id,
                capability_type=self.capability_type,
                execution_time_ms=duration_ms,
            )
        except Exception as e:
            logger.error("Explore failed for %s: %s", target, e)
            return CapabilityResult(
                success=False,
                error=str(e),
                capability_id=self.capability_id,
                capability_type=self.capability_type,
            )


# ── Core Pipeline ────────────────────────────────────────────────────


def _explore(target: Path, focus: str) -> ExploreMap:
    """Run the explore pipeline. Pure deterministic, 0 LLM tokens.

    1. CodeScanner scans target → populates a fresh KnowledgeGraph
    2. Query graph nodes (filtered by focus if provided)
    3. Classify each file's guna (sattva/rajas/tamas)
    4. Compress each node name to a seed
    5. Collect relations (imports, inherits, calls)
    """
    # Step 1: Scan target into a fresh graph
    graph = UnifiedKnowledgeGraph()
    scanner = CodeScanner(graph)
    stats = scanner.scan_directory(target)

    total_nodes = len(graph.nodes)
    total_edges = sum(len(edges) for edges in graph.edges.values())

    # Step 2: Get relevant nodes
    if focus:
        nodes = _query_by_focus(graph, focus)
    else:
        nodes = list(graph.nodes.values())

    # Step 3: Classify guna for each file
    guna_classifier = GunaClassifier(workspace=target)
    file_gunas: dict[str, str] = {}

    # Step 4: Compress + build entries
    compressor = MahaCompression()
    entries: list[ExploreEntry] = []

    for node in nodes:
        # Get file path from node metadata
        file_path = node.properties.get("file", "") if hasattr(node, "metadata") and node.properties else ""
        line = node.properties.get("line", 0) if hasattr(node, "metadata") and node.properties else 0

        # Guna classification (cached per file)
        guna = "sattva"  # default
        if file_path and file_path not in file_gunas:
            full_path = target / file_path
            if full_path.exists():
                try:
                    classification = guna_classifier.classify(full_path)
                    file_gunas[file_path] = classification.guna.value
                except Exception:
                    file_gunas[file_path] = "sattva"
            else:
                file_gunas[file_path] = "sattva"
        guna = file_gunas.get(file_path, "sattva")

        # Compression seed
        seed = compressor.compress(node.name).seed

        # Relations (edges FROM this node)
        relations: list[str] = []
        for edge in graph.edges.get(node.id, []):
            target_node = graph.nodes.get(edge.target)
            if target_node:
                relations.append(target_node.name)

        # Methods (for classes)
        methods: list[str] = []
        if node.type == NodeType.CLASS:
            for edge in graph.edges.get(node.id, []):
                if edge.relation == RelationType.DEFINES:
                    child = graph.nodes.get(edge.target)
                    if child and child.node_type == NodeType.FUNCTION:
                        methods.append(child.name)

        entries.append(ExploreEntry(
            name=node.name,
            node_type=node.type.value if hasattr(node.type, "value") else str(node.type),
            file=file_path,
            line=line,
            seed=seed,
            guna=guna,
            relations=tuple(relations[:10]),
            methods=tuple(methods[:15]),
        ))

    # Sort: tamas first (problems), then rajas (active), then sattva (clean)
    guna_order = {"tamas": 0, "rajas": 1, "sattva": 2}
    entries.sort(key=lambda e: (guna_order.get(e.guna, 9), e.file, e.name))

    return ExploreMap(
        target=str(target),
        focus=focus,
        entries=entries[:50],  # Cap at 50 entries
        total_nodes=total_nodes,
        total_edges=total_edges,
    )


def _query_by_focus(graph: UnifiedKnowledgeGraph, focus: str) -> list:
    """Query graph nodes matching focus term. Case-insensitive substring match."""
    focus_lower = focus.lower()
    terms = focus_lower.split()

    matched = []
    for node in graph.nodes.values():
        name_lower = node.name.lower()
        desc_lower = (node.description or "").lower() if hasattr(node, "description") else ""

        if any(t in name_lower or t in desc_lower for t in terms):
            matched.append(node)

    # If no direct match, return all nodes (let the agent decide)
    return matched if matched else list(graph.nodes.values())[:50]
