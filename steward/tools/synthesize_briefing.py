"""
synthesize_briefing — LLM-enriched on-demand briefing synthesis.

This tool is an OPTIONAL, non-canonical preview path. It uses steward's
LLM to enrich deterministic context with prioritized insights and returns
the result to the caller without persisting it.

Input sources (all deterministic, zero LLM):
  - context.json: assembled from senses, vedana, gaps, sessions, etc.
  - Architecture metadata: SVC_ docstrings, kshetra, hooks, north star
  - Validated annotations from steward.annotations pipeline

The LLM then synthesizes these into a coherent briefing that:
  1. Leads with what matters most (health, urgencies, pain)
  2. Explains the architecture so the reader understands the system
  3. Shows what steward tried and what failed
  4. Tells the reader what needs attention
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from vibe_core.tools.tool_protocol import Tool, ToolResult

logger = logging.getLogger("STEWARD.TOOLS.SYNTHESIZE_BRIEFING")

# ── Synthesis Prompt ─────────────────────────────────────────────────
# This is NOT a hardcoded description of steward. It's an INSTRUCTION
# to steward's own LLM about HOW to write the briefing. The actual
# content comes from the architecture metadata and context data.

_SYNTHESIS_INSTRUCTION = """\
Write a COCKPIT BRIEFING PREVIEW, not a resume. The preview may be shown
to an external engineering agent, but it is not canonical instruction.

STRUCTURE (in this exact order):

## CRITICAL NOW
What is broken, failing, or needs immediate attention. Open issues.
CI status. Recent failures. Be brutally honest.

## RULES (non-negotiable)
- ruff format before every commit
- NEVER change NORTH_STAR_TEXT (it's a MahaCompression seed — breaks all alignment)
- Identity comes from data/federation/peer.json (nadi protocol)
- No hardcoded owner/org strings — use _get_federation_owner()
- CBR (OperationalQuota) on ALL external calls — API, LLM, subprocess
- Test suite baseline: ~3 minutes, ~1570 tests. Regression = your fault.
- except pass is Anti-Buddhi — log or propagate, never swallow silently

## ARCHITECTURE (compact)
Key services, MURALI phases, tools. Table format. No prose.

## FEDERATION
Which repos exist, who sends nadi messages, who receives, what's connected.
Include the relay pump in agent-internet.

## OPEN ISSUES
List from GitHub with 1-line context each.

Do NOT write "I am steward" or any first-person marketing.
Do NOT explain what MURALI means philosophically.
Do NOT add sections not listed above.
Use ONLY the data provided below. Be TERSE.
"""


class SynthesizeBriefingTool(Tool):
    """Return a non-canonical LLM briefing preview without filesystem writes."""

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self._cwd = cwd or str(Path.cwd())

    @property
    def name(self) -> str:
        return "synthesize_briefing"

    @property
    def description(self) -> str:
        return (
            "Return a non-canonical briefing preview from steward's architecture "
            "metadata and current state. This tool never writes files."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "output_path": {
                "type": "string",
                "required": False,
                "description": (
                    "Optional compatibility value. Only 'stdout' is accepted; all persisted output paths are rejected."
                ),
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        output_path = parameters.get("output_path")
        if output_path not in (None, "stdout"):
            raise ValueError("synthesize_briefing supports preview output only")

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        try:
            self.validate(parameters)
        except ValueError as e:
            return ToolResult(success=False, error=str(e))

        try:
            # 1. Collect raw material (deterministic, zero LLM)
            from steward.annotations import collect_validated
            from steward.context_bridge import assemble_context, collect_architecture_metadata

            context = assemble_context(self._cwd)
            architecture = collect_architecture_metadata()
            validated_annotations = collect_validated()

            # 2. Get steward's LLM provider
            from steward.services import SVC_PROVIDER
            from vibe_core.di import ServiceRegistry

            provider = ServiceRegistry.get(SVC_PROVIDER)
            if provider is None:
                return ToolResult(
                    success=False,
                    error="No LLM provider available — cannot synthesize briefing",
                )

            # 3. Build the synthesis prompt (includes annotations)
            prompt = self._build_prompt(architecture, context, validated_annotations)

            # 4. Call steward's own LLM
            response = provider.invoke(
                messages=[
                    {"role": "system", "content": _SYNTHESIS_INSTRUCTION},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=4000,
            )

            # Extract text from response
            briefing = self._extract_text(response)
            if not briefing:
                return ToolResult(
                    success=False,
                    error="LLM returned empty response for briefing synthesis",
                )

            return ToolResult(
                success=True,
                output=briefing,
                metadata={
                    "mode": "preview",
                    "canonical": False,
                    "tokens": len(briefing.split()),
                },
            )

        except Exception as e:
            logger.warning("Briefing synthesis failed: %s", e)
            return ToolResult(success=False, error=f"Synthesis failed: {e}")

    def _build_prompt(
        self, architecture: dict[str, Any], context: dict[str, Any], annotations: list | None = None
    ) -> str:
        """Build the data payload for the synthesis LLM call."""
        parts: list[str] = []

        parts.append("## ARCHITECTURE (from living code)\n")

        # North star
        ns = architecture.get("north_star")
        if ns:
            parts.append(f"**North Star**: {ns}\n")

        # Services
        services = architecture.get("services", {})
        if services:
            parts.append("### Services (SVC_ constants)\n")
            for svc_name, docstring in sorted(services.items()):
                parts.append(f"- `{svc_name}`: {docstring}")
            parts.append("")

        # Phases
        phases = architecture.get("phases", {})
        if phases:
            parts.append("### MURALI Phases\n")
            for phase, desc in phases.items():
                parts.append(f"- **{phase}**: {desc}")
            parts.append("")

        # Hooks
        hooks = architecture.get("hooks", {})
        if hooks:
            parts.append("### Registered Hooks\n")
            for phase, hook_list in hooks.items():
                parts.append(f"**{phase}**:")
                for h in hook_list:
                    doc = f" — {h['doc']}" if h.get("doc") else ""
                    parts.append(f"  - [{h['priority']}] {h['name']}{doc}")
            parts.append("")

        # Tools
        tools = architecture.get("tools", [])
        if tools:
            parts.append("### Available Tools\n")
            for t in tools:
                parts.append(f"- `{t['name']}`: {t.get('description', '')}")
            parts.append("")

        # Kshetra (compact)
        kshetra = architecture.get("kshetra", [])
        if kshetra:
            parts.append("### Kshetra (25-Tattva Architecture Map)\n")
            parts.append("| # | Element | Category | Role |")
            parts.append("|---|---------|----------|------|")
            for k in kshetra:
                parts.append(f"| {k['number']} | {k['element']} | {k['category']} | {k['role']} |")
            parts.append("")

        # Agent knowledge (validated annotations)
        if annotations:
            from steward.annotations import format_for_briefing

            annotation_text = format_for_briefing(annotations)
            if annotation_text:
                parts.append("\n## AGENT KNOWLEDGE (validated annotations)\n")
                parts.append(annotation_text)
                parts.append("")

        parts.append("\n## CONTEXT (current state)\n")
        # Compact JSON — the LLM can parse it
        parts.append(json.dumps(context, indent=2, default=str))

        return "\n".join(parts)

    @staticmethod
    def _extract_text(response: object) -> str:
        """Extract text content from an LLM response (provider-agnostic)."""
        # NormalizedResponse
        if hasattr(response, "content"):
            return response.content or ""
        # Dict response
        if isinstance(response, dict):
            return response.get("content", response.get("text", ""))
        return str(response)
