"""
CLI entry point — python -m steward 'task' or python -m steward for interactive.

Usage:
    python -m steward "Fix the bug in main.py"     # single task
    python -m steward                               # interactive REPL
    python -m steward --resume "Follow up"          # resume session
    python -m steward --version                     # print version
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from steward import __version__
from steward.agent import StewardAgent
from steward.provider import build_chamber
from steward.state import clear_state, load_conversation, save_conversation
from steward.types import AgentEvent

# ANSI escape codes (no external dependencies)
_DIM = "\033[2m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_RESET = "\033[0m"
_BOLD = "\033[1m"


def _format_event(event: AgentEvent) -> None:
    """Print an AgentEvent to the terminal."""
    if event.type == "text":
        print(f"\n{event.content}")
    elif event.type == "tool_call" and event.tool_use:
        params = " ".join(f"{k}={v!r}" for k, v in event.tool_use.parameters.items())
        print(f"  {_DIM}[{event.tool_use.name}] {params}{_RESET}")
    elif event.type == "tool_result":
        if event.content and hasattr(event.content, "success"):
            if event.content.success:  # type: ignore[union-attr]
                output = getattr(event.content, "output", "")
                preview = str(output)[:120] if output else "ok"
                print(f"  {_GREEN}>{_RESET} {_DIM}{preview}{_RESET}")
            else:
                err = getattr(event.content, "error", "failed")
                print(f"  {_RED}x {err}{_RESET}")
    elif event.type == "done" and event.usage:
        u = event.usage
        print(
            f"\n{_DIM}[{u.input_tokens}+{u.output_tokens} tokens, "
            f"{u.llm_calls} calls, {u.tool_calls} tools, "
            f"{u.rounds} rounds]{_RESET}"
        )
    elif event.type == "error":
        print(f"{_RED}Error: {event.content}{_RESET}", file=sys.stderr)


async def _run_task(agent: StewardAgent, task: str) -> None:
    async for event in agent.run_stream(task):
        _format_event(event)


async def _interactive(agent: StewardAgent, cwd: str | None = None) -> None:
    print(f"{_BOLD}Steward v{__version__}{_RESET} — autonomous agent")
    print(f"{_DIM}Type 'exit' to quit, 'reset' to clear conversation{_RESET}\n")

    while True:
        try:
            user_input = input(f"{_CYAN}steward>{_RESET} ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        text = user_input.strip()
        if not text:
            continue
        if text in ("exit", "quit"):
            break
        if text == "reset":
            agent.reset()
            clear_state(cwd=cwd)
            print(f"{_DIM}Conversation reset{_RESET}")
            continue

        async for event in agent.run_stream(text):
            _format_event(event)

        save_conversation(agent.conversation, cwd=cwd)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="steward",
        description="Steward — Autonomous Agent Engine",
    )
    parser.add_argument("task", nargs="?", help="Task to execute (omit for interactive mode)")
    parser.add_argument("--version", action="version", version=f"steward {__version__}")
    parser.add_argument("--resume", action="store_true", help="Resume previous session")
    parser.add_argument("--cwd", help="Working directory (default: current)")
    parser.add_argument("--max-tokens", type=int, default=4096, help="Max output tokens per response")

    args = parser.parse_args()

    # Build provider chamber from environment
    chamber = build_chamber()
    if len(chamber) == 0:
        print(
            f"{_RED}No LLM providers configured.{_RESET}\n"
            "Set at least one: GOOGLE_API_KEY, MISTRAL_API_KEY, OPENROUTER_API_KEY",
            file=sys.stderr,
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
            agent._conversation = conv  # noqa: SLF001
            print(f"{_DIM}Resumed session ({len(conv.messages)} messages){_RESET}")
        else:
            print(f"{_DIM}No previous session found{_RESET}")

    if args.task:
        asyncio.run(_run_task(agent, args.task))
        save_conversation(agent.conversation, cwd=args.cwd)
    else:
        asyncio.run(_interactive(agent, cwd=args.cwd))


if __name__ == "__main__":
    main()
