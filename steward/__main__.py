"""
CLI entry point — python -m steward 'task' or python -m steward for interactive.

Usage:
    python -m steward "Fix the bug in main.py"     # single task
    python -m steward                               # interactive REPL
    python -m steward --resume "Follow up"          # resume session
    python -m steward --version                     # print version
    python -m steward --output json "task"          # JSON output (machine)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from rich.console import Console
from rich.markup import escape
from rich.theme import Theme

from steward import __version__
from steward.agent import StewardAgent
from steward.provider import build_chamber
from steward.state import clear_state, load_conversation, save_conversation
from steward.types import AgentEvent, AgentUsage, EventType, ToolResult

# ── Console Setup ────────────────────────────────────────────────────

_THEME = Theme(
    {
        "tool.name": "bold cyan",
        "tool.param": "dim",
        "tool.ok": "green",
        "tool.err": "red",
        "stats": "dim",
        "prompt": "bold cyan",
        "heading": "bold",
        "error": "red bold",
    }
)

_console = Console(theme=_THEME, highlight=False)
_err_console = Console(theme=_THEME, stderr=True, highlight=False)


# ── Human-Readable Event Rendering (O(1) dispatch) ────────────────


def _fmt_text_delta(event: AgentEvent) -> None:
    _console.print(str(event.content or ""), end="")


def _fmt_text(event: AgentEvent) -> None:
    _console.print(f"\n{event.content}")


def _fmt_tool_call(event: AgentEvent) -> None:
    if not event.tool_use:
        return
    tc = event.tool_use
    display = _tool_display(tc.name, tc.parameters)
    _console.print(f"  [tool.name]{escape(tc.name)}[/] [tool.param]{escape(display)}[/]")


def _fmt_tool_result(event: AgentEvent) -> None:
    if not isinstance(event.content, ToolResult):
        return
    if event.content.success:
        preview = str(event.content.output)[:120] if event.content.output else "ok"
        _console.print(f"  [tool.ok]>[/] [stats]{escape(preview)}[/]")
    else:
        _console.print(f"  [tool.err]x {escape(event.content.error or 'failed')}[/]")


def _fmt_done(event: AgentEvent) -> None:
    if event.usage:
        _print_usage(event.usage)


def _fmt_error(event: AgentEvent) -> None:
    _err_console.print(f"[error]Error: {escape(str(event.content))}[/]")


_FORMAT_DISPATCH: dict[EventType, object] = {
    EventType.TEXT_DELTA: _fmt_text_delta,
    EventType.TEXT: _fmt_text,
    EventType.TOOL_CALL: _fmt_tool_call,
    EventType.TOOL_RESULT: _fmt_tool_result,
    EventType.DONE: _fmt_done,
    EventType.ERROR: _fmt_error,
}


def _format_event(event: AgentEvent) -> None:
    """Render an AgentEvent to the terminal — O(1) dispatch."""
    handler = _FORMAT_DISPATCH.get(event.type)
    if handler is not None:
        handler(event)


_TOOL_PARAM_KEY: dict[str, str] = {
    "read_file": "path",
    "write_file": "path",
    "edit_file": "path",
    "bash": "command",
    "glob": "pattern",
    "grep": "pattern",
    "http": "url",
    "agent_internet": "action",
    "sub_agent": "task",
}


def _tool_display(name: str, params: dict) -> str:
    """Extract the most informative param for compact tool display."""
    key = _TOOL_PARAM_KEY.get(name)
    if key:
        val = str(params.get(key, ""))
        return val[:80] + ("..." if len(val) > 80 else "")
    # Fallback: show all params compactly
    return " ".join(f"{k}={v!r}" for k, v in params.items())[:100]


def _print_usage(u: AgentUsage) -> None:
    """Print turn statistics."""
    buddhi = ""
    if u.buddhi_action:
        phase = f"/{u.buddhi_phase}" if u.buddhi_phase else ""
        buddhi = f" | {u.buddhi_action}/{u.buddhi_guna}{phase}"
        if u.buddhi_reflections:
            buddhi += f" {u.buddhi_reflections}r"
    _console.print(
        f"\n[stats][{u.input_tokens}+{u.output_tokens} tokens, "
        f"{u.llm_calls} calls, {u.tool_calls} tools, "
        f"{u.rounds} rounds{buddhi}][/]"
    )


# ── JSON Event Rendering ────────────────────────────────────────────


def _json_content(event: AgentEvent, obj: dict) -> None:
    obj["content"] = str(event.content or "")


def _json_tool_call(event: AgentEvent, obj: dict) -> None:
    if event.tool_use:
        obj["tool"] = event.tool_use.name
        obj["parameters"] = event.tool_use.parameters
        obj["call_id"] = event.tool_use.id


def _json_tool_result(event: AgentEvent, obj: dict) -> None:
    if event.content:
        obj["success"] = getattr(event.content, "success", None)
        obj["output"] = str(getattr(event.content, "output", ""))[:500]
        obj["error"] = getattr(event.content, "error", None)


def _json_done(event: AgentEvent, obj: dict) -> None:
    if event.usage:
        u = event.usage
        obj["usage"] = {
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "llm_calls": u.llm_calls,
            "tool_calls": u.tool_calls,
            "rounds": u.rounds,
            "buddhi_action": u.buddhi_action,
            "buddhi_guna": u.buddhi_guna,
            "buddhi_phase": u.buddhi_phase,
        }


_JSON_DISPATCH: dict[EventType, object] = {
    EventType.TEXT: _json_content,
    EventType.TEXT_DELTA: _json_content,
    EventType.ERROR: _json_content,
    EventType.TOOL_CALL: _json_tool_call,
    EventType.TOOL_RESULT: _json_tool_result,
    EventType.DONE: _json_done,
}


def _format_event_json(event: AgentEvent) -> None:
    """Render an AgentEvent as JSON — O(1) dispatch."""
    obj: dict[str, object] = {"type": str(event.type)}
    handler = _JSON_DISPATCH.get(event.type)
    if handler is not None:
        handler(event, obj)
    print(json.dumps(obj), flush=True)


# ── Entry Points ─────────────────────────────────────────────────────


def _run_autonomous(cwd: str | None = None) -> None:
    """Run as persistent daemon — boot once, Cetana heartbeat drives work.

    NOT cron-based. Agent stays alive in memory. Import overhead: 0 after boot.
    Cetana 4-phase heartbeat (GENESIS→DHARMA→KARMA→MOKSHA) drives all work.
    Kill with SIGTERM/SIGINT for graceful shutdown.
    """
    # Try to build provider — optional for deterministic-only runs
    try:
        chamber = build_chamber()
        provider = chamber if len(chamber) > 0 else None
    except Exception:
        provider = None

    if provider is None:

        class _NoProvider:
            def invoke(self, **kwargs):
                raise RuntimeError("No LLM provider configured — cannot execute LLM tasks")

            def invoke_stream(self, **kwargs):
                raise RuntimeError("No LLM provider configured — cannot execute LLM tasks")

        provider = _NoProvider()
        _err_console.print("[stats]No LLM provider — running deterministic checks only[/]")

    agent = StewardAgent(provider=provider, cwd=cwd)

    try:
        agent.run_daemon()  # Blocks until SIGTERM/SIGINT
    finally:
        agent.close()


async def _run_task(
    agent: StewardAgent,
    task: str,
    output_json: bool = False,
) -> None:
    formatter = _format_event_json if output_json else _format_event
    async for event in agent.run_stream(task):
        formatter(event)


async def _interactive(agent: StewardAgent, cwd: str | None = None) -> None:
    _console.print(f"[heading]Steward v{__version__}[/] — autonomous agent")
    _console.print("[stats]Type 'exit' to quit, 'reset' to clear conversation[/]\n")

    while True:
        try:
            user_input = _console.input("[prompt]steward>[/] ")
        except (EOFError, KeyboardInterrupt):
            _console.print()
            break

        text = user_input.strip()
        if not text:
            continue
        if text in ("exit", "quit"):
            break
        if text == "reset":
            agent.reset()
            clear_state(cwd=cwd)
            _console.print("[stats]Conversation reset[/]")
            continue

        async for event in agent.run_stream(text):
            _format_event(event)

        save_conversation(agent.conversation, cwd=cwd)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="steward",
        description="Steward — Autonomous Superagent Engine",
    )
    parser.add_argument("task", nargs="?", help="Task to execute (omit for interactive mode)")
    parser.add_argument("--version", action="version", version=f"steward {__version__}")
    parser.add_argument("--resume", action="store_true", help="Resume previous session")
    parser.add_argument("--cwd", help="Working directory (default: current)")
    parser.add_argument("--max-tokens", type=int, default=4096, help="Max output tokens per response")
    parser.add_argument(
        "--output",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human)",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Run as Telegram bot (requires TELEGRAM_BOT_TOKEN)",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Run as HTTP API server (requires pip install steward-agent[api])",
    )
    parser.add_argument(
        "--autonomous",
        action="store_true",
        help="Run as persistent daemon: boot once, Cetana heartbeat drives work. Kill with SIGTERM.",
    )
    parser.add_argument(
        "--briefing",
        action="store_true",
        help="Output dynamic context briefing (senses + gaps + sessions) to stdout. No LLM needed.",
    )

    args = parser.parse_args()

    # Briefing mode — show committed CLAUDE.md if fresh, regenerate if stale
    if args.briefing:
        import time
        from pathlib import Path

        cwd = args.cwd or "."
        committed = Path(cwd) / "CLAUDE.md"
        if committed.exists():
            age_s = time.time() - committed.stat().st_mtime
            if age_s < 3600:  # < 1 hour old → use committed version
                print(committed.read_text())
                return

        # Stale or missing → regenerate (cold-start, partial data)
        from steward.briefing import generate_briefing

        print(generate_briefing(cwd=cwd))
        return

    # Telegram mode — delegate to telegram interface
    if args.telegram:
        from steward.interfaces.telegram import main as telegram_main

        telegram_main()
        return

    # API mode — delegate to API server
    if args.api:
        from steward.interfaces.api import main as api_main

        api_main()
        return

    # Autonomous mode — persistent daemon, Cetana heartbeat drives work
    if args.autonomous:
        _run_autonomous(cwd=args.cwd)
        return

    # Build provider chamber from environment
    chamber = build_chamber()
    if len(chamber) == 0:
        _err_console.print(
            "[error]No LLM providers configured.[/]\n"
            "Set at least one: GOOGLE_API_KEY, MISTRAL_API_KEY, OPENROUTER_API_KEY"
        )
        sys.exit(1)

    agent = StewardAgent(
        provider=chamber,
        cwd=args.cwd,
        max_output_tokens=args.max_tokens,
    )

    # Resume previous session if requested
    if args.resume:
        conv = load_conversation(cwd=args.cwd)
        if conv:
            agent.resume(conv)
            _console.print(f"[stats]Resumed session ({len(conv.messages)} messages)[/]")
        else:
            _console.print("[stats]No previous session found[/]")

    output_json = args.output == "json"

    if args.task:
        asyncio.run(_run_task(agent, args.task, output_json=output_json))
        save_conversation(agent.conversation, cwd=args.cwd)
    else:
        asyncio.run(_interactive(agent, cwd=args.cwd))


if __name__ == "__main__":
    main()
