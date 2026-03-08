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
from steward.types import AgentEvent, AgentUsage, EventType

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


# ── Human-Readable Event Rendering ──────────────────────────────────


def _format_event(event: AgentEvent) -> None:
    """Render an AgentEvent to the terminal (human mode)."""
    if event.type == EventType.TEXT_DELTA:
        _console.print(str(event.content or ""), end="")
        return

    if event.type == EventType.TEXT:
        _console.print(f"\n{event.content}")

    elif event.type == EventType.TOOL_CALL and event.tool_use:
        tc = event.tool_use
        # Extract the most informative parameter for display
        display = _tool_display(tc.name, tc.parameters)
        _console.print(f"  [tool.name]{escape(tc.name)}[/] [tool.param]{escape(display)}[/]")

    elif event.type == EventType.TOOL_RESULT:
        if event.content and hasattr(event.content, "success"):
            if event.content.success:  # type: ignore[union-attr]
                output = getattr(event.content, "output", "")
                preview = str(output)[:120] if output else "ok"
                _console.print(f"  [tool.ok]>[/] [stats]{escape(preview)}[/]")
            else:
                err = getattr(event.content, "error", "failed")
                _console.print(f"  [tool.err]x {escape(str(err))}[/]")

    elif event.type == EventType.DONE and event.usage:
        _print_usage(event.usage)

    elif event.type == EventType.ERROR:
        _err_console.print(f"[error]Error: {escape(str(event.content))}[/]")


_TOOL_PARAM_KEY: dict[str, str] = {
    "read_file": "path",
    "write_file": "path",
    "edit_file": "path",
    "bash": "command",
    "glob": "pattern",
    "grep": "pattern",
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


def _format_event_json(event: AgentEvent) -> None:
    """Render an AgentEvent as JSON (machine mode)."""
    obj: dict[str, object] = {"type": str(event.type)}

    if event.type in (EventType.TEXT, EventType.TEXT_DELTA, EventType.ERROR):
        obj["content"] = str(event.content or "")
    elif event.type == EventType.TOOL_CALL and event.tool_use:
        obj["tool"] = event.tool_use.name
        obj["parameters"] = event.tool_use.parameters
        obj["call_id"] = event.tool_use.id
    elif event.type == EventType.TOOL_RESULT and event.content:
        obj["success"] = getattr(event.content, "success", None)
        obj["output"] = str(getattr(event.content, "output", ""))[:500]
        obj["error"] = getattr(event.content, "error", None)
    elif event.type == EventType.DONE and event.usage:
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

    print(json.dumps(obj), flush=True)


# ── Entry Points ─────────────────────────────────────────────────────


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

    args = parser.parse_args()

    # Telegram mode — delegate to telegram interface
    if args.telegram:
        from steward.interfaces.telegram import main as telegram_main

        telegram_main()
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
