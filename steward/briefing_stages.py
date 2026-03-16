"""
BriefingStages — foveated rendering pipeline for CLAUDE.md generation.

Same pattern as PhaseHookRegistry: register stages, dispatch by priority,
gate with should_run(). Each stage renders at VARIABLE DETAIL LEVEL
driven by a focus signal from the substrate.

Foveated rendering (like VR eye-tracking):
  - The "gaze" is determined by system state: pain, dominant sense, gaps
  - High-focus stages render at full detail (1.0)
  - Low-focus stages compress to essence (0.1)
  - No information is "cut" — it's compressed proportionally

Focus signals (from substrate, zero LLM):
  - total_pain → urgency (high pain = expand everything)
  - per-sense pain → which area needs attention
  - context_pressure → how much space do we have
  - active gaps → what capabilities are missing
  - health guna → overall system state

Token budget is the hard-ceiling safety net (CBR limiter),
but focus weights are the primary compression driver.

Priority bands:
  0-10:  Identity & Critical (always full detail)
  11-30: Orientation & Status (context framing)
  31-60: Action & Knowledge (what to do, what we know)
  61-80: Environment & Insights (perception layer)
  81-100: Architecture & Sessions (reference footer)
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("STEWARD.BRIEFING_STAGES")

# ── Token Budget Constants ─────────────────────────────────────────
# Hard ceiling — safety net after focus-weighted compression.

BUDGET_COMPACT = 800
BUDGET_STANDARD = 2000  # Sweet spot: 800-2000 tokens optimal for AI agents
BUDGET_FULL = 4000  # Max before Claude shows accuracy degradation (~5500)
BUDGET_UNLIMITED = 0

_VERSION = "3.0.0"  # Foveated rendering pipeline


def _estimate_tokens(text: str) -> int:
    """Estimate token count. chars/4 approximation (safe overestimate)."""
    return max(1, len(text) // 4)


# ── Focus Signal ───────────────────────────────────────────────────


@dataclass(frozen=True)
class BriefingFocus:
    """Per-stage focus weights derived from substrate signals.

    Each weight is 0.0 (fully compressed) to 1.0 (full detail).
    Computed from system state — no LLM, deterministic.
    """

    orientation: float = 0.8  # Irreplaceable mental model — high default
    status: float = 0.7  # Health dashboard
    action: float = 1.0  # Drives agent behavior — always full
    knowledge: float = 0.7  # Validated learnings
    environment: float = 0.8  # Current perception
    gap_awareness: float = 0.6  # Known blind spots
    federation_insight: float = 0.4  # May be empty
    toolbox: float = 0.4  # Names sufficient
    architecture: float = 0.8  # Service map — essential for coding
    sessions: float = 0.3  # Footer stats

    # Diagnostic: what drove the focus computation
    driver: str = "default"


def compute_focus(ctx: dict) -> BriefingFocus:
    """Derive focus weights from substrate signals.

    Reads: total_pain, per-sense pain, context_pressure, gaps, health.
    All available at cold-start (from context.json or fresh senses).

    Strategy:
      1. Base weights from overall health (sattva=relaxed, tamas=urgent)
      2. Per-sense pain boosts the corresponding stage
      3. Context pressure compresses everything proportionally
      4. Active gaps boost gap_awareness stage
    """
    senses = ctx.get("senses", {})
    health = ctx.get("health", {})
    gaps = ctx.get("gaps", {})

    total_pain = senses.get("total_pain", 0.0)
    if not isinstance(total_pain, (int, float)):
        total_pain = 0.0

    context_pressure = health.get("context_pressure", 0.0)
    if not isinstance(context_pressure, (int, float)):
        context_pressure = 0.0

    guna = health.get("guna", "rajas")
    active_gap_count = len(gaps.get("active", []))
    driver_parts: list[str] = []

    # ── 1. Base weights from guna (overall system mood) ──
    if guna == "tamas" or total_pain > 0.5:
        # System in pain → expand everything, agent needs full context
        base = 0.9
        driver_parts.append(f"pain={total_pain:.1f}")
    elif guna == "sattva" and total_pain < 0.2:
        # System healthy → compress to essentials
        base = 0.5
        driver_parts.append("sattva")
    else:
        # Rajas (active) → balanced
        base = 0.7
        driver_parts.append("rajas")

    # Start from base. Essential sections stay high — only noise sections compress.
    # Orientation, Architecture, Action, Environment = SIGNAL (never below 0.7)
    # Toolbox, Sessions, FederationInsight = NOISE (can compress freely)
    weights = {
        "orientation": max(0.7, base),  # Irreplaceable mental model
        "status": max(0.5, base * 0.9),  # Health dashboard
        "action": 1.0,  # Always full — drives agent behavior
        "knowledge": max(0.5, base * 0.8),  # Validated learnings
        "environment": max(0.7, base),  # Current perception = essential
        "gap_awareness": max(0.5, base * 0.7),  # Known blind spots
        "federation_insight": base * 0.6,  # May be empty — compress ok
        "toolbox": base * 0.5,  # Can show just names
        "architecture": max(0.7, base),  # Service map = essential for coding
        "sessions": base * 0.4,  # Footer stats — compress ok
    }

    # ── 2. Per-sense pain → boost corresponding stages ──
    sense_detail = senses.get("detail", {})
    if isinstance(sense_detail, dict):
        for sense_name, info in sense_detail.items():
            if not isinstance(info, dict):
                continue
            sense_pain = info.get("pain", 0.0)
            if not isinstance(sense_pain, (int, float)) or sense_pain < 0.3:
                continue

            # Map sense → stage boost
            boost = min(0.4, sense_pain * 0.5)
            if sense_name in ("srotra", "git"):
                weights["environment"] = min(1.0, weights["environment"] + boost)
                driver_parts.append(f"git_pain={sense_pain:.1f}")
            elif sense_name in ("jihva", "testing"):
                weights["environment"] = min(1.0, weights["environment"] + boost)
                weights["status"] = min(1.0, weights["status"] + boost)
                driver_parts.append(f"test_pain={sense_pain:.1f}")
            elif sense_name in ("caksu", "code"):
                weights["architecture"] = min(1.0, weights["architecture"] + boost)
                weights["knowledge"] = min(1.0, weights["knowledge"] + boost)
                driver_parts.append(f"code_pain={sense_pain:.1f}")
            elif sense_name in ("ghrana", "health"):
                weights["status"] = min(1.0, weights["status"] + boost)
                driver_parts.append(f"health_pain={sense_pain:.1f}")

    # ── 3. Context pressure → compress proportionally ──
    if context_pressure > 0.5:
        compression = 1.0 - (context_pressure - 0.5)  # 0.5→1.0, 1.0→0.5
        for key in weights:
            weights[key] *= compression
        driver_parts.append(f"ctx_pressure={context_pressure:.1f}")

    # ── 4. Active gaps → boost gap awareness ──
    if active_gap_count > 0:
        gap_boost = min(0.4, active_gap_count * 0.1)
        weights["gap_awareness"] = min(1.0, weights["gap_awareness"] + gap_boost)
        weights["action"] = min(1.0, weights["action"] + gap_boost * 0.5)
        driver_parts.append(f"gaps={active_gap_count}")

    # Clamp all weights to [0.1, 1.0] — never fully suppress
    for key in weights:
        weights[key] = max(0.1, min(1.0, weights[key]))

    return BriefingFocus(
        **weights,
        driver=", ".join(driver_parts) if driver_parts else "default",
    )


# ── BriefingStage Protocol ─────────────────────────────────────────


class BriefingStage(ABC):
    """Base class for composable briefing stages with foveated rendering.

    Each stage renders at a variable detail level based on its focus weight:
      - focus=1.0: full detail (every line)
      - focus=0.5: compressed (headers + key lines only)
      - focus=0.1: minimal (one-liner summary)

    Stages that are NOT compressible (Identity, Critical) ignore focus.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    def priority(self) -> int:
        return 50

    @property
    def compressible(self) -> bool:
        """Whether this stage responds to focus weight."""
        return True

    def should_run(self, ctx: dict, arch: dict) -> bool:
        return True

    @abstractmethod
    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str, focus: float) -> None:
        """Append lines at the given focus level (0.0-1.0)."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} pri={self.priority}>"


# ── BriefingPipeline ───────────────────────────────────────────────


class BriefingPipeline:
    """Foveated rendering pipeline for CLAUDE.md.

    Three-pass generation:
      1. Compute focus signal from substrate (deterministic, zero LLM)
      2. Run all stages with per-stage focus weights
      3. Hard-ceiling safety net (CBR limiter) — truncate if still over budget

    The focus signal is the PRIMARY compression driver.
    The token budget is the SAFETY NET (should rarely trigger).
    """

    __slots__ = ("_stages", "_token_budget")

    def __init__(self, token_budget: int = BUDGET_STANDARD) -> None:
        self._stages: list[BriefingStage] = []
        self._token_budget = token_budget

    @property
    def token_budget(self) -> int:
        return self._token_budget

    @token_budget.setter
    def token_budget(self, value: int) -> None:
        self._token_budget = max(0, value)

    def register(self, stage: BriefingStage) -> None:
        """Register a stage. Deduplicates by name."""
        for existing in self._stages:
            if existing.name == stage.name:
                logger.debug("Stage %s already registered, skipping", stage.name)
                return
        self._stages.append(stage)
        self._stages.sort(key=lambda s: s.priority)

    def generate(self, ctx: dict, arch: dict, cwd: str) -> str:
        """Foveated rendering: focus-weighted stages, iterative compression.

        Never cuts or truncates. If over budget, re-renders ALL stages
        with progressively lower focus until it fits. Every stage always
        appears — just at lower resolution.
        """
        # Pass 1: compute focus from substrate signals
        focus = compute_focus(ctx)

        # Pass 2: render with focus, then iteratively compress if over budget
        result_text = self._render_all(ctx, arch, cwd, focus)

        if self._token_budget > 0:
            # Iterative compression: reduce focus by 20% per round, max 4 rounds
            compression_factor = 1.0
            for _ in range(4):
                if _estimate_tokens(result_text) <= self._token_budget:
                    break
                compression_factor *= 0.8
                compressed_focus = self._scale_focus(focus, compression_factor)
                result_text = self._render_all(ctx, arch, cwd, compressed_focus)

        result = result_text

        # Metadata footer
        token_count = _estimate_tokens(result)
        budget_label = self._budget_label()
        metadata = (
            f"\n<!-- briefing v{_VERSION}"
            f" | {token_count} tokens"
            f" | budget: {budget_label} ({self._token_budget})"
            f" | focus: {focus.driver}"
            f" | {time.strftime('%Y-%m-%dT%H:%M:%S')} -->"
        )
        return result + metadata

    def _render_all(self, ctx: dict, arch: dict, cwd: str, focus: BriefingFocus) -> str:
        """Render all stages with given focus weights. Nothing is ever cut."""
        stage_outputs: list[str] = []
        for stage in self._stages:
            try:
                if not stage.should_run(ctx, arch):
                    continue

                if stage.compressible:
                    stage_focus = getattr(focus, stage.name, 0.5)
                else:
                    stage_focus = 1.0

                parts: list[str] = []
                stage.enrich(parts, ctx, arch, cwd, stage_focus)
                output = "\n".join(parts)
                if output.strip():
                    stage_outputs.append(output)
            except Exception as e:
                logger.warning("Stage %s failed: %s", stage.name, e)
        return "\n".join(stage_outputs)

    @staticmethod
    def _scale_focus(focus: BriefingFocus, factor: float) -> BriefingFocus:
        """Scale all compressible focus weights down by factor. Floor at 0.1."""
        return BriefingFocus(
            orientation=max(0.1, focus.orientation * factor),
            status=max(0.1, focus.status * factor),
            action=focus.action,  # Never compress action
            knowledge=max(0.1, focus.knowledge * factor),
            environment=max(0.1, focus.environment * factor),
            gap_awareness=max(0.1, focus.gap_awareness * factor),
            federation_insight=max(0.1, focus.federation_insight * factor),
            toolbox=max(0.1, focus.toolbox * factor),
            architecture=max(0.1, focus.architecture * factor),
            sessions=max(0.1, focus.sessions * factor),
            driver=f"{focus.driver}, compressed={factor:.2f}",
        )

    def _budget_label(self) -> str:
        if self._token_budget == 0:
            return "unlimited"
        if self._token_budget <= BUDGET_COMPACT:
            return "compact"
        if self._token_budget <= BUDGET_STANDARD:
            return "standard"
        if self._token_budget <= BUDGET_FULL:
            return "full"
        return "custom"

    def get_stages(self) -> list[BriefingStage]:
        return list(self._stages)

    def stage_count(self) -> int:
        return len(self._stages)


# ── Stages ─────────────────────────────────────────────────────────
# Each stage renders at variable detail based on focus weight.
# focus=1.0 → full detail | focus=0.5 → compressed | focus=0.1 → minimal


class IdentityStage(BriefingStage):
    """Project name, north star, MahaMantra seed. Always full detail."""

    @property
    def name(self) -> str:
        return "identity"

    @property
    def priority(self) -> int:
        return 0

    @property
    def compressible(self) -> bool:
        return False

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str, focus: float) -> None:
        project_name = ctx.get("project", {}).get("name", "") or Path(cwd).resolve().name
        ns = arch.get("north_star", "")
        parts.append(f"# {project_name}")
        if ns:
            parts.append(f"**{ns}**")
        seed_info = _get_seed_info()
        if seed_info:
            parts.append(seed_info)


class CriticalStage(BriefingStage):
    """Critical alerts. Always full detail — never compress warnings."""

    @property
    def name(self) -> str:
        return "critical"

    @property
    def priority(self) -> int:
        return 5

    @property
    def compressible(self) -> bool:
        return False

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str, focus: float) -> None:
        critical = _collect_critical(ctx)
        if critical:
            parts.append("\n## Critical")
            for c in critical:
                parts.append(f"- {c}")
        else:
            parts.append("\n*No critical issues.*")


class OrientationStage(BriefingStage):
    """Static mental model from .steward/conventions.md.

    Focus levels:
      1.0: Full conventions.md verbatim
      0.5: Only section headers + first line per section
      0.1: Skip entirely (agent already knows the system)
    """

    @property
    def name(self) -> str:
        return "orientation"

    @property
    def priority(self) -> int:
        return 10

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str, focus: float) -> None:
        orientation = _load_orientation(cwd)
        if not orientation:
            return

        if focus >= 0.7:
            # Full detail — verbatim
            parts.append(f"\n{orientation}")
        elif focus >= 0.3:
            # Compressed — section headers + first content line
            parts.append("")
            for line in orientation.splitlines():
                stripped = line.strip()
                if stripped.startswith("## ") or stripped.startswith("| "):
                    parts.append(line)
                elif stripped.startswith("```"):
                    parts.append(line)
                elif stripped.startswith("- **"):
                    parts.append(line)
        else:
            # Minimal — just section headers
            parts.append("")
            for line in orientation.splitlines():
                if line.strip().startswith("## "):
                    parts.append(line)


class StatusStage(BriefingStage):
    """Health/immune/federation dashboard.

    Focus levels:
      1.0: Full dashboard with all subsystems
      0.5: One-liner summary
      0.1: Skip (only if healthy)
    """

    @property
    def name(self) -> str:
        return "status"

    @property
    def priority(self) -> int:
        return 20

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str, focus: float) -> None:
        status_lines: list[str] = []

        health = ctx.get("health", {})
        if health:
            h_val = health.get("value", "?")
            guna = health.get("guna", "?")
            status_lines.append(f"Health: {h_val} ({guna})")

        immune = ctx.get("immune", {})
        if immune:
            breaker = "TRIPPED" if immune.get("breaker", {}).get("tripped") else "OK"
            attempted = immune.get("heals_attempted", 0)
            succeeded = immune.get("heals_succeeded", 0)
            status_lines.append(f"Immune: {succeeded}/{attempted} heals, breaker {breaker}")

        fed = ctx.get("federation", {})
        peers = fed.get("peers", [])
        if peers:
            alive = sum(1 for p in peers if p.get("status") == "alive")
            suspect = sum(1 for p in peers if p.get("status") == "suspect")
            dead = sum(1 for p in peers if p.get("status") in ("dead", "evicted"))
            status_lines.append(
                f"Federation: {len(peers)} peers ({alive} alive, {suspect} suspect, {dead} dead)"
            )

        if not status_lines:
            return

        if focus >= 0.5:
            parts.append("\n## Status")
            for line in status_lines:
                parts.append(line)
        else:
            # Compressed: single line
            parts.append(f"\n## Status\n{' · '.join(status_lines)}")

    def should_run(self, ctx: dict, arch: dict) -> bool:
        return bool(ctx.get("health") or ctx.get("immune") or ctx.get("federation", {}).get("peers"))


class ActionStage(BriefingStage):
    """Action items — GitHub issues + gaps. Never compressed."""

    @property
    def name(self) -> str:
        return "action"

    @property
    def priority(self) -> int:
        return 30

    @property
    def compressible(self) -> bool:
        return False

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str, focus: float) -> None:
        issues = ctx.get("issues", [])
        gaps = ctx.get("gaps", {})
        active_gaps = gaps.get("active", [])

        if not issues and not active_gaps:
            return

        parts.append("\n## Action")

        if issues:
            for i in issues:
                num = i.get("number", "?")
                title = i.get("title", "?")
                labels = i.get("labels", [])
                label_str = ""
                if labels:
                    label_str = " " + " ".join(f"[{lb}]" for lb in labels[:3])
                parts.append(f"- #{num}: {title}{label_str}")

        if active_gaps:
            parts.append("")
            parts.append("Gaps:")
            for g in active_gaps[:5]:
                parts.append(f"- [{g.get('category', '?')}] {g.get('description', '?')}")

    def should_run(self, ctx: dict, arch: dict) -> bool:
        return bool(ctx.get("issues") or ctx.get("gaps", {}).get("active"))


class KnowledgeStage(BriefingStage):
    """Validated annotations.

    Focus levels:
      1.0: All annotations with details
      0.3: Only invariants and warnings
      0.1: Skip
    """

    @property
    def name(self) -> str:
        return "knowledge"

    @property
    def priority(self) -> int:
        return 40

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str, focus: float) -> None:
        if focus < 0.2:
            return  # Skip at very low focus — agent already knows

        knowledge = _collect_annotations(high_priority_only=(focus < 0.5))
        if knowledge:
            parts.append("\n## Agent Knowledge")
            parts.append(knowledge)


class EnvironmentStage(BriefingStage):
    """Senses perception + federation peer table.

    Focus levels:
      1.0: Full prompt_summary + peer table
      0.5: prompt_summary only (no peer table)
      0.1: One-liner summary
    """

    @property
    def name(self) -> str:
        return "environment"

    @property
    def priority(self) -> int:
        return 50

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str, focus: float) -> None:
        senses = ctx.get("senses", {})
        prompt = senses.get("prompt_summary", "")

        if focus >= 0.5:
            if prompt:
                parts.append(f"\n{prompt.strip()}")
            else:
                parts.append("\n## Environment Perception")

            # Peer table only at high focus
            if focus >= 0.8:
                fed = ctx.get("federation", {})
                peers = fed.get("peers", [])
                if peers:
                    parts.append(f"\nFederation peers: {len(peers)}")
                    parts.append("| Peer | Status | Trust | Capabilities |")
                    parts.append("|------|--------|-------|--------------|")
                    for p in peers:
                        caps = ", ".join(p.get("capabilities", [])[:3]) or "—"
                        parts.append(
                            f"| {p.get('agent_id', '?')} | {p.get('status', '?')} | {p.get('trust', '?')} | {caps} |"
                        )
        else:
            # Compressed: one-liner from prompt
            if prompt:
                first_lines = [ln for ln in prompt.strip().splitlines() if ln.strip() and not ln.startswith("#")]
                parts.append(f"\n## Environment Perception\n{first_lines[0] if first_lines else ''}")
            else:
                parts.append("\n## Environment Perception")


class GapAwarenessStage(BriefingStage):
    """Capability gaps — detailed view.

    Focus levels:
      1.0: All gaps with context
      0.5: Gaps without context
      0.1: Count only
    """

    @property
    def name(self) -> str:
        return "gap_awareness"

    @property
    def priority(self) -> int:
        return 55

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str, focus: float) -> None:
        gaps = ctx.get("gaps", {})
        active = gaps.get("active", [])
        stats = gaps.get("stats", {})

        if not active:
            return

        parts.append("\n## Gap Awareness")

        if focus < 0.3:
            # Minimal: just count
            parts.append(f"{len(active)} active gaps")
            return

        if stats and focus >= 0.5:
            total = stats.get("total_tracked", 0)
            resolved = stats.get("resolved", 0)
            parts.append(f"Tracked: {total} total, {resolved} resolved")

        max_gaps = max(1, int(10 * focus))
        for g in active[:max_gaps]:
            cat = g.get("category", "?")
            desc = g.get("description", "?")
            line = f"- **[{cat}]** {desc}"
            if focus >= 0.7:
                ctx_str = g.get("context", "")
                if ctx_str:
                    line += f" — _{ctx_str}_"
            parts.append(line)

    def should_run(self, ctx: dict, arch: dict) -> bool:
        return bool(ctx.get("gaps", {}).get("active"))


class FederationInsightStage(BriefingStage):
    """Research results from federation peers.

    Focus levels:
      1.0: All insights with peer attribution
      0.3: Latest insight only
      0.1: Skip
    """

    @property
    def name(self) -> str:
        return "federation_insight"

    @property
    def priority(self) -> int:
        return 60

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str, focus: float) -> None:
        if focus < 0.2:
            return

        insights = self._collect_insights(cwd)
        if not insights:
            return

        parts.append("\n## Federation Insights")
        max_insights = max(1, int(5 * focus))
        for insight in insights[:max_insights]:
            parts.append(f"- From **{insight['peer']}**: {insight['summary']}")

    def _collect_insights(self, cwd: str) -> list[dict]:
        import json

        inbox_path = Path(cwd) / "data" / "federation" / "nadi_inbox.json"
        if not inbox_path.is_file():
            return []

        try:
            data = json.loads(inbox_path.read_text())
            messages = data if isinstance(data, list) else data.get("messages", [])
            insights = []
            for msg in messages:
                op = msg.get("operation", "")
                if op in ("research_result", "task_completed", "insight"):
                    payload = msg.get("payload", {})
                    insights.append({
                        "peer": msg.get("agent_id", msg.get("from", "unknown")),
                        "summary": payload.get("summary", payload.get("title", str(payload)[:100])),
                    })
            return insights
        except (json.JSONDecodeError, OSError):
            return []


class ToolboxStage(BriefingStage):
    """Available tools.

    Focus levels:
      1.0: Full tool list with descriptions
      0.5: Tool names only (no descriptions)
      0.1: Count only
    """

    @property
    def name(self) -> str:
        return "toolbox"

    @property
    def priority(self) -> int:
        return 70

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str, focus: float) -> None:
        tools = arch.get("tools", [])
        if not tools:
            return

        parts.append("\n## Toolbox")

        if focus < 0.3:
            parts.append(f"{len(tools)} tools available")
            return

        for t in tools:
            name = t.get("name", "?")
            desc = t.get("description", "")
            if desc and focus >= 0.6:
                first_sentence = desc.split(".")[0].strip()
                parts.append(f"- `{name}` — {first_sentence}")
            else:
                parts.append(f"- `{name}`")

    def should_run(self, ctx: dict, arch: dict) -> bool:
        return bool(arch.get("tools"))


class ArchitectureStage(BriefingStage):
    """Services, phases, substrate reference.

    Focus levels:
      1.0: Full grouped services + MURALI phases
      0.5: Service count + MURALI one-liner
      0.1: Service count only
    """

    @property
    def name(self) -> str:
        return "architecture"

    @property
    def priority(self) -> int:
        return 80

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str, focus: float) -> None:
        services = arch.get("services", {})
        kshetra = arch.get("kshetra", [])
        phases = arch.get("phases", {})
        hooks = arch.get("hooks", {})

        parts.append("\n## Architecture")

        if services:
            parts.append(f"{len(services)} services · {len(kshetra)} tattvas")

        if focus >= 0.5 and services:
            # Grouped service listing
            groups = _group_services(sorted(services.keys()))
            if focus >= 0.7:
                # Full: all services per group
                for group_name, svc_list in groups.items():
                    parts.append(f"{group_name}: {', '.join(f'`{s}`' for s in svc_list)}")
            else:
                # Compressed: group names + counts
                group_summary = ", ".join(f"{k}({len(v)})" for k, v in groups.items())
                parts.append(f"Services: {group_summary}")

        if phases:
            phase_parts = []
            for p, desc in phases.items():
                hook_info = hooks.get(p, {})
                if isinstance(hook_info, dict):
                    count = hook_info.get("count", 0)
                else:
                    count = len(hook_info) if isinstance(hook_info, list) else 0
                phase_parts.append(f"**{p}**({count})")
            parts.append(f"MURALI: {' → '.join(phase_parts)}")


class SessionsStage(BriefingStage):
    """Session stats footer.

    Focus levels:
      1.0: Stats + recent session summaries
      0.3: Stats one-liner
      0.1: Skip
    """

    @property
    def name(self) -> str:
        return "sessions"

    @property
    def priority(self) -> int:
        return 90

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str, focus: float) -> None:
        if focus < 0.2:
            return

        sessions = ctx.get("sessions", {})
        stats = sessions.get("stats", {})
        if stats and stats.get("total", 0) > 0:
            parts.append(
                f"\nSessions: {stats.get('total', 0)} total, success rate {stats.get('success_rate', 0):.0%}"
            )

    def should_run(self, ctx: dict, arch: dict) -> bool:
        return bool(ctx.get("sessions", {}).get("stats", {}).get("total", 0))


# ── Shared Helpers ─────────────────────────────────────────────────


def _get_seed_info() -> str:
    try:
        from vibe_core.mahamantra import mahamantra

        vm = mahamantra("steward")
        seed = vm.get("seed", "")
        position = vm.get("position", "")
        compression = vm.get("compression_ratio", "")
        info_parts = []
        if seed:
            info_parts.append(f"Seed `{seed}`")
        if position:
            info_parts.append(f"position {position}")
        if compression:
            info_parts.append(f"{compression}x compression")
        return " · ".join(info_parts) if info_parts else ""
    except Exception:
        return ""


def _load_orientation(cwd: str) -> str:
    """Load the static orientation block from .steward/conventions.md."""
    path = Path(cwd) / ".steward" / "conventions.md"
    if not path.is_file():
        return ""
    try:
        content = path.read_text(encoding="utf-8").strip()
        lines = content.splitlines()
        start = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                start = i
                if i > 0 and lines[i - 1].strip().startswith("# "):
                    start = i - 1
                break
            if stripped.startswith("## "):
                start = i
                break
        return "\n".join(lines[start:]).strip()
    except OSError:
        return ""


def _collect_annotations(high_priority_only: bool = False) -> str:
    """Collect validated annotations from the knowledge pipeline."""
    try:
        from steward.annotations import format_for_briefing

        return format_for_briefing()
    except Exception:
        return ""


def _collect_critical(ctx: dict) -> list[str]:
    critical: list[str] = []

    health = ctx.get("health", {})
    h_val = health.get("value", 1.0)
    if isinstance(h_val, (int, float)) and h_val < 0.5:
        critical.append(f"Health CRITICAL: {h_val} ({health.get('guna', '?')})")

    immune = ctx.get("immune", {})
    if immune.get("breaker", {}).get("tripped"):
        critical.append("Immune breaker TRIPPED — healing suspended")
    if immune.get("heals_rolled_back", 0) > 0:
        critical.append(f"{immune['heals_rolled_back']} heals rolled back")

    fed = ctx.get("federation", {})
    dead = fed.get("dead", 0) if isinstance(fed.get("dead"), int) else len(fed.get("dead_ids", []))
    if dead:
        critical.append(f"{dead} DEAD peers in federation")

    senses = ctx.get("senses", {})
    pain = senses.get("total_pain", 0)
    if isinstance(pain, (int, float)) and pain > 0.7:
        critical.append(f"High pain: {pain:.2f}")

    return critical


def _group_services(svc_names: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {
        "Cognitive": [],
        "Memory": [],
        "Safety": [],
        "Federation": [],
        "Healing": [],
        "Other": [],
    }

    cognitive = {"SVC_ATTENTION", "SVC_MAHA_LLM", "SVC_COMPRESSION", "SVC_ANTARANGA", "SVC_VENU", "SVC_SIKSASTAKAM"}
    memory = {"SVC_MEMORY", "SVC_SYNAPSE_STORE", "SVC_CACHE", "SVC_KNOWLEDGE_GRAPH", "SVC_TASK_MANAGER"}
    safety = {"SVC_SAFETY_GUARD", "SVC_NARASIMHA", "SVC_INTEGRITY", "SVC_DIAMOND"}
    federation = {
        "SVC_FEDERATION",
        "SVC_FEDERATION_TRANSPORT",
        "SVC_FEDERATION_RELAY",
        "SVC_GIT_NADI_SYNC",
        "SVC_REAPER",
        "SVC_MARKETPLACE",
    }
    healing = {"SVC_IMMUNE", "SVC_FEEDBACK", "SVC_OUROBOROS"}

    for svc_name in svc_names:
        if svc_name in cognitive:
            groups["Cognitive"].append(svc_name)
        elif svc_name in memory:
            groups["Memory"].append(svc_name)
        elif svc_name in safety:
            groups["Safety"].append(svc_name)
        elif svc_name in federation:
            groups["Federation"].append(svc_name)
        elif svc_name in healing:
            groups["Healing"].append(svc_name)
        else:
            groups["Other"].append(svc_name)

    return {k: v for k, v in groups.items() if v}


# ── Pipeline Factory ───────────────────────────────────────────────


def default_pipeline(token_budget: int = BUDGET_STANDARD) -> BriefingPipeline:
    """Create the default briefing pipeline with all stages registered.

    Args:
        token_budget: Hard ceiling safety net. Focus weights are the primary
            compression driver; budget is the brick-wall limiter.
    """
    pipeline = BriefingPipeline(token_budget=token_budget)
    pipeline.register(IdentityStage())
    pipeline.register(CriticalStage())
    pipeline.register(OrientationStage())
    pipeline.register(StatusStage())
    pipeline.register(ActionStage())
    pipeline.register(KnowledgeStage())
    pipeline.register(EnvironmentStage())
    pipeline.register(GapAwarenessStage())
    pipeline.register(FederationInsightStage())
    pipeline.register(ToolboxStage())
    pipeline.register(ArchitectureStage())
    pipeline.register(SessionsStage())
    return pipeline
