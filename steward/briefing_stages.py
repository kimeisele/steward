"""
BriefingStages — composable pipeline for CLAUDE.md generation.

Same pattern as PhaseHookRegistry: register stages, dispatch by priority,
gate with should_run(). Each stage appends lines to the briefing output.

Priority bands:
  0-10:  Identity & Critical (must be first)
  11-30: Orientation & Status (context framing)
  31-60: Action & Knowledge (what to do, what we know)
  61-80: Environment & Insights (perception layer)
  81-100: Architecture & Sessions (reference footer)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger("STEWARD.BRIEFING_STAGES")


# ── BriefingStage Protocol ─────────────────────────────────────────


class BriefingStage(ABC):
    """Base class for composable briefing stages.

    Each stage is responsible for one section of the CLAUDE.md output.
    Stages are registered in a BriefingPipeline and executed in priority order.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this stage."""
        ...

    @property
    def priority(self) -> int:
        """Execution order (0=first, 100=last)."""
        return 50

    def should_run(self, ctx: dict, arch: dict) -> bool:
        """Gate — return False to skip this stage."""
        return True

    @abstractmethod
    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str) -> None:
        """Append lines to the briefing output."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} pri={self.priority}>"


# ── BriefingPipeline ───────────────────────────────────────────────


class BriefingPipeline:
    """Registry + dispatcher for briefing stages.

    Stages register at boot. generate() runs all stages in priority order,
    respecting gates. Output is a joined string of all stage contributions.
    """

    __slots__ = ("_stages",)

    def __init__(self) -> None:
        self._stages: list[BriefingStage] = []

    def register(self, stage: BriefingStage) -> None:
        """Register a stage. Deduplicates by name."""
        for existing in self._stages:
            if existing.name == stage.name:
                logger.debug("Stage %s already registered, skipping", stage.name)
                return
        self._stages.append(stage)
        self._stages.sort(key=lambda s: s.priority)

    def generate(self, ctx: dict, arch: dict, cwd: str) -> str:
        """Run all stages in priority order, return joined output."""
        parts: list[str] = []
        for stage in self._stages:
            try:
                if not stage.should_run(ctx, arch):
                    logger.debug("Stage %s skipped (gate)", stage.name)
                    continue
                stage.enrich(parts, ctx, arch, cwd)
            except Exception as e:
                logger.warning("Stage %s failed: %s", stage.name, e)
        return "\n".join(parts)

    def get_stages(self) -> list[BriefingStage]:
        """Get all stages sorted by priority."""
        return list(self._stages)

    def stage_count(self) -> int:
        return len(self._stages)


# ── Stages ─────────────────────────────────────────────────────────


class IdentityStage(BriefingStage):
    """Project name, north star, MahaMantra seed."""

    @property
    def name(self) -> str:
        return "identity"

    @property
    def priority(self) -> int:
        return 0

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str) -> None:
        project_name = ctx.get("project", {}).get("name", "") or Path(cwd).resolve().name
        ns = arch.get("north_star", "")
        parts.append(f"# {project_name}")
        if ns:
            parts.append(f"**{ns}**")

        seed_info = _get_seed_info()
        if seed_info:
            parts.append(seed_info)


class CriticalStage(BriefingStage):
    """Critical alerts — only shown when something is actually wrong."""

    @property
    def name(self) -> str:
        return "critical"

    @property
    def priority(self) -> int:
        return 5

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str) -> None:
        critical = _collect_critical(ctx)
        if critical:
            parts.append("\n## Critical")
            for c in critical:
                parts.append(f"- {c}")
        else:
            parts.append("\n*No critical issues.*")


class OrientationStage(BriefingStage):
    """Static mental model from .steward/conventions.md."""

    @property
    def name(self) -> str:
        return "orientation"

    @property
    def priority(self) -> int:
        return 10

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str) -> None:
        orientation = _load_orientation(cwd)
        if orientation:
            parts.append(f"\n{orientation}")

    def should_run(self, ctx: dict, arch: dict) -> bool:
        return True  # Always try — file check is in _load_orientation


class StatusStage(BriefingStage):
    """Compact health/immune/federation dashboard."""

    @property
    def name(self) -> str:
        return "status"

    @property
    def priority(self) -> int:
        return 20

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str) -> None:
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

        if status_lines:
            parts.append("\n## Status")
            for line in status_lines:
                parts.append(line)

    def should_run(self, ctx: dict, arch: dict) -> bool:
        return bool(ctx.get("health") or ctx.get("immune") or ctx.get("federation", {}).get("peers"))


class ActionStage(BriefingStage):
    """Action items — GitHub issues + gaps."""

    @property
    def name(self) -> str:
        return "action"

    @property
    def priority(self) -> int:
        return 30

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str) -> None:
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
    """Validated annotations from the knowledge pipeline."""

    @property
    def name(self) -> str:
        return "knowledge"

    @property
    def priority(self) -> int:
        return 40

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str) -> None:
        knowledge = _collect_annotations()
        if knowledge:
            parts.append("\n## Agent Knowledge")
            parts.append(knowledge)

    def should_run(self, ctx: dict, arch: dict) -> bool:
        return True  # Annotations check is in _collect_annotations


class EnvironmentStage(BriefingStage):
    """Senses perception + federation peer table."""

    @property
    def name(self) -> str:
        return "environment"

    @property
    def priority(self) -> int:
        return 50

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str) -> None:
        senses = ctx.get("senses", {})
        prompt = senses.get("prompt_summary", "")

        if prompt:
            parts.append(f"\n{prompt.strip()}")
        else:
            parts.append("\n## Environment Perception")

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


class GapAwarenessStage(BriefingStage):
    """Proactive gap surfacing — detailed view of capability gaps."""

    @property
    def name(self) -> str:
        return "gap_awareness"

    @property
    def priority(self) -> int:
        return 55

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str) -> None:
        gaps = ctx.get("gaps", {})
        active = gaps.get("active", [])
        stats = gaps.get("stats", {})

        if not active:
            return

        parts.append("\n## Gap Awareness")
        if stats:
            total = stats.get("total_tracked", 0)
            resolved = stats.get("resolved", 0)
            parts.append(f"Tracked: {total} total, {resolved} resolved")

        for g in active[:10]:
            cat = g.get("category", "?")
            desc = g.get("description", "?")
            ctx_str = g.get("context", "")
            line = f"- **[{cat}]** {desc}"
            if ctx_str:
                line += f" — _{ctx_str}_"
            parts.append(line)

    def should_run(self, ctx: dict, arch: dict) -> bool:
        return bool(ctx.get("gaps", {}).get("active"))


class FederationInsightStage(BriefingStage):
    """Research results and insights from federation peers."""

    @property
    def name(self) -> str:
        return "federation_insight"

    @property
    def priority(self) -> int:
        return 60

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str) -> None:
        insights = self._collect_insights(cwd)
        if not insights:
            return

        parts.append("\n## Federation Insights")
        for insight in insights[:5]:
            parts.append(f"- From **{insight['peer']}**: {insight['summary']}")

    def should_run(self, ctx: dict, arch: dict) -> bool:
        return True  # File check is in _collect_insights

    def _collect_insights(self, cwd: str) -> list[dict]:
        """Read research results from federation inbox."""
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
    """Available tools with descriptions."""

    @property
    def name(self) -> str:
        return "toolbox"

    @property
    def priority(self) -> int:
        return 70

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str) -> None:
        tools = arch.get("tools", [])
        if not tools:
            return

        parts.append("\n## Toolbox")
        for t in tools:
            name = t.get("name", "?")
            desc = t.get("description", "")
            if desc:
                first_sentence = desc.split(".")[0].strip()
                parts.append(f"- `{name}` — {first_sentence}")
            else:
                parts.append(f"- `{name}`")

    def should_run(self, ctx: dict, arch: dict) -> bool:
        return bool(arch.get("tools"))


class ArchitectureStage(BriefingStage):
    """Services grouped, phases, substrate reference."""

    @property
    def name(self) -> str:
        return "architecture"

    @property
    def priority(self) -> int:
        return 80

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str) -> None:
        parts.append("\n## Architecture")

        services = arch.get("services", {})
        kshetra = arch.get("kshetra", [])
        if services:
            parts.append(f"{len(services)} services · {len(kshetra)} tattvas")

            groups = _group_services(sorted(services.keys()))
            for group_name, svc_list in groups.items():
                parts.append(f"{group_name}: {', '.join(f'`{s}`' for s in svc_list)}")

        phases = arch.get("phases", {})
        hooks = arch.get("hooks", {})
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
    """Compact session stats footer."""

    @property
    def name(self) -> str:
        return "sessions"

    @property
    def priority(self) -> int:
        return 90

    def enrich(self, parts: list[str], ctx: dict, arch: dict, cwd: str) -> None:
        sessions = ctx.get("sessions", {})
        stats = sessions.get("stats", {})
        if stats and stats.get("total", 0) > 0:
            parts.append(
                f"\nSessions: {stats.get('total', 0)} total, success rate {stats.get('success_rate', 0):.0%}"
            )

    def should_run(self, ctx: dict, arch: dict) -> bool:
        return bool(ctx.get("sessions", {}).get("stats", {}).get("total", 0))


# ── Shared Helpers ─────────────────────────────────────────────────
# These are extracted from briefing.py and shared across stages.


def _get_seed_info() -> str:
    """Get MahaMantra seed + position for identity line."""
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


def _collect_annotations() -> str:
    """Collect validated annotations from the knowledge pipeline."""
    try:
        from steward.annotations import format_for_briefing

        return format_for_briefing()
    except Exception:
        return ""


def _collect_critical(ctx: dict) -> list[str]:
    """Collect critical alerts from system state."""
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
    """Group services by functional area for compact display."""
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


def default_pipeline() -> BriefingPipeline:
    """Create the default briefing pipeline with all stages registered."""
    pipeline = BriefingPipeline()
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
