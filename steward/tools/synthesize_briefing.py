"""
synthesize_briefing — Steward writes its own documentation via LLM.

This tool lets steward use its own intelligence to synthesize a CLAUDE.md
briefing for external consumers (Claude Code, Opus sessions). Instead of
hardcoded templates, steward reads its own state and architecture from
living code and asks its LLM to produce a prioritized briefing.

Input sources (all deterministic, zero LLM):
  - context.json: assembled from senses, vedana, gaps, sessions, etc.
  - Architecture metadata: SVC_ docstrings, kshetra, hooks, north star

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
You are steward, an autonomous superagent. You are writing a briefing
about YOURSELF for an external consumer (another LLM session, Claude Code,
or a developer). Write in first person where natural.

Below you receive two data sources:
1. ARCHITECTURE — your own service docstrings, module mappings, phase hooks,
   and tools. This is WHO you are, read from your own source code.
2. CONTEXT — your current state: health, environmental perception, recent
   sessions, capability gaps, pending tasks, federation peers, immune status.

Synthesize a CLAUDE.md that:
- Leads with system status (health, guna, urgencies) — what matters NOW
- Explains your architecture concisely — services, phases, senses, tools
- Highlights what needs attention — gaps, failed sessions, immune issues
- Notes conventions that matter — Sanskrit naming is load-bearing, DI via
  ServiceRegistry, hooks for extensibility, pytest for tests
- Is concise but complete — an experienced developer or LLM should understand
  the system after reading this

Format as clean markdown. Use headers, tables, bullet points.
Do NOT invent information. Only use what's in the data below.
Do NOT add motivational text or philosophy. Be technical and precise.
"""


class SynthesizeBriefingTool(Tool):
    """Synthesize CLAUDE.md from steward's living state + architecture metadata."""

    def __init__(self, cwd: str | None = None) -> None:
        super().__init__()
        self._cwd = cwd or str(Path.cwd())

    @property
    def name(self) -> str:
        return "synthesize_briefing"

    @property
    def description(self) -> str:
        return (
            "Synthesize .steward/CLAUDE.md from steward's own architecture "
            "metadata and current state. Uses steward's LLM to create a "
            "prioritized briefing for external consumers."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "output_path": {
                "type": "string",
                "required": False,
                "description": (
                    "Path to write the briefing (default: .steward/CLAUDE.md). "
                    "Use 'stdout' to return content without writing."
                ),
            },
        }

    def validate(self, parameters: dict[str, Any]) -> None:
        pass  # No required params

    def execute(self, parameters: dict[str, Any]) -> ToolResult:
        output_path = parameters.get("output_path")
        stdout_mode = output_path == "stdout"

        try:
            # 1. Collect raw material (deterministic, zero LLM)
            from steward.context_bridge import assemble_context, collect_architecture_metadata

            context = assemble_context(self._cwd)
            architecture = collect_architecture_metadata()

            # 2. Get steward's LLM provider
            from steward.services import SVC_PROVIDER
            from vibe_core.di import ServiceRegistry

            provider = ServiceRegistry.get(SVC_PROVIDER)
            if provider is None:
                return ToolResult(
                    success=False,
                    error="No LLM provider available — cannot synthesize briefing",
                )

            # 3. Build the synthesis prompt
            prompt = self._build_prompt(architecture, context)

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

            # 5. Write the result
            if stdout_mode:
                return ToolResult(
                    success=True,
                    output=briefing,
                    metadata={"mode": "stdout", "tokens": len(briefing.split())},
                )

            # Default path: .steward/CLAUDE.md
            if output_path:
                dest = Path(output_path)
            else:
                dest = Path(self._cwd) / "CLAUDE.md"

            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(briefing, encoding="utf-8")

            return ToolResult(
                success=True,
                output=f"Briefing synthesized → {dest} ({len(briefing)} bytes)",
                metadata={"path": str(dest), "bytes": len(briefing)},
            )

        except Exception as e:
            logger.warning("Briefing synthesis failed: %s", e)
            return ToolResult(success=False, error=f"Synthesis failed: {e}")

    def _build_prompt(self, architecture: dict[str, Any], context: dict[str, Any]) -> str:
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
