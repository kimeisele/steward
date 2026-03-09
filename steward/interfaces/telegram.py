"""
Telegram Bot Interface — Access Steward via Telegram.

Same StewardAgent, different I/O channel. The agent doesn't
know it's talking through Telegram — clean separation.

Authentication:
    OWNER  (TELEGRAM_OWNER_ID) — full LLM access, all tools
    OTHERS — read-only status, no LLM calls (deterministic only)

Environment:
    TELEGRAM_BOT_TOKEN  — Bot API token from @BotFather
    TELEGRAM_OWNER_ID   — Your Telegram user ID (get from @userinfobot)
    STEWARD_CWD         — Working directory for the agent (default: cwd)

Usage:
    python -m steward.interfaces.telegram

Security:
    - Only the owner can execute tasks (LLM calls, tool use)
    - Narasimha killswitch still active (blocks dangerous commands)
    - Iron Dome still active (blocks blind writes)
    - Telegram message limit: 4096 chars (auto-chunked)
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import signal
import sys
import time

from steward.agent import StewardAgent
from steward.provider import build_chamber
from steward.state import load_conversation, save_conversation
from steward.types import EventType, ToolResult

logger = logging.getLogger("STEWARD.TELEGRAM")

# Telegram message limit
_MAX_MSG_LEN = 4096

# Typing indicator refresh interval (Telegram cancels after ~5s)
_TYPING_INTERVAL_S = 4.0


class TelegramBot:
    """Steward Telegram bot — owner-only agent access.

    Non-owners get a polite rejection. The owner gets full
    StewardAgent capabilities including tool use.
    """

    def __init__(self, token: str, owner_id: int, cwd: str | None = None) -> None:
        self._token = token
        self._owner_id = owner_id
        self._cwd = cwd
        self._agent: StewardAgent | None = None
        self._lock = asyncio.Lock()  # serialize agent access
        self._busy = False  # track whether agent is processing

    def _ensure_agent(self) -> StewardAgent:
        """Lazy-init the agent (provider chamber needs env vars at runtime)."""
        if self._agent is None:
            chamber = build_chamber()
            if len(chamber) == 0:
                raise RuntimeError("No LLM providers configured")
            self._agent = StewardAgent(
                provider=chamber,
                cwd=self._cwd,
            )
            # Resume previous session if available
            conv = load_conversation(cwd=self._cwd)
            if conv:
                self._agent.resume(conv)
                logger.info("Resumed session (%d messages)", len(conv.messages))
        return self._agent

    def _is_owner(self, user) -> bool:  # noqa: ANN001
        """Check if user is the owner."""
        return user.id == self._owner_id

    async def handle_start(self, update, context) -> None:  # noqa: ANN001
        """Handle /start command."""
        user = update.effective_user
        is_owner = self._is_owner(user)
        status = "Owner access" if is_owner else "Read-only access"
        await update.message.reply_text(
            f"Steward Superagent\n"
            f"Status: {status}\n"
            f"Your ID: {user.id}\n\n"
            f"Send any message to interact." + ("" if is_owner else "\n\nNote: Only the owner can execute tasks.")
        )

    async def handle_help(self, update, context) -> None:  # noqa: ANN001
        """Handle /help command — list available commands."""
        commands = (
            "<b>Steward Telegram Commands</b>\n\n"
            "/start  — Welcome message + access status\n"
            "/help   — This help message\n"
            "/status — Context window + phase diagnostics\n"
            "/reset  — Clear conversation (owner only)\n"
            "/save   — Save session to disk\n\n"
            "<b>Usage</b>\n"
            "Send any text to interact with the agent.\n"
            "The agent has full tool access (bash, file I/O, etc).\n"
            "All safety guards (Narasimha, Iron Dome) remain active."
        )
        await update.message.reply_text(commands, parse_mode="HTML")

    async def handle_reset(self, update, context) -> None:  # noqa: ANN001
        """Handle /reset command — clear conversation (owner only)."""
        if not self._is_owner(update.effective_user):
            await update.message.reply_text("Only the owner can reset.")
            return

        if self._agent:
            self._agent.reset()
            save_conversation(self._agent.conversation, cwd=self._cwd)
        await update.message.reply_text("Session reset.")

    async def handle_status(self, update, context) -> None:  # noqa: ANN001
        """Handle /status command — show agent diagnostics."""
        agent = self._ensure_agent()
        conv_len = len(agent.conversation.messages)
        tokens = agent.conversation.total_tokens
        max_tokens = agent.conversation.max_tokens
        pct = int(tokens / max_tokens * 100) if max_tokens else 0

        busy_indicator = " (processing...)" if self._busy else ""

        await update.message.reply_text(
            f"Context: {tokens}/{max_tokens} tokens ({pct}%)\n"
            f"Messages: {conv_len}\n"
            f"Phase: {agent._buddhi.phase}{busy_indicator}"
        )

    async def handle_save(self, update, context) -> None:  # noqa: ANN001
        """Handle /save command — explicitly save session."""
        if not self._is_owner(update.effective_user):
            await update.message.reply_text("Only the owner can save.")
            return

        if self._agent:
            save_conversation(self._agent.conversation, cwd=self._cwd)
            await update.message.reply_text("Session saved.")
        else:
            await update.message.reply_text("No active session to save.")

    async def _keep_typing(self, chat) -> None:  # noqa: ANN001
        """Send typing indicator periodically until cancelled."""
        try:
            while True:
                await chat.send_action("typing")
                await asyncio.sleep(_TYPING_INTERVAL_S)
        except asyncio.CancelledError:
            pass

    async def handle_message(self, update, context) -> None:  # noqa: ANN001
        """Handle incoming text messages."""
        user = update.effective_user
        text = update.message.text

        if not text:
            return

        # Auth gate: non-owners get rejected
        if not self._is_owner(user):
            await update.message.reply_text("Read-only mode. Only the owner can interact with the agent.")
            return

        # Reject if already processing (non-blocking feedback)
        if self._busy:
            await update.message.reply_text("Still processing previous request. Please wait.")
            return

        # Owner: run through StewardAgent
        async with self._lock:  # serialize — one task at a time
            self._busy = True
            typing_task: asyncio.Task | None = None
            try:
                agent = self._ensure_agent()

                # Keep typing indicator alive during processing
                typing_task = asyncio.create_task(self._keep_typing(update.message.chat))

                # Collect response
                response_parts: list[str] = []
                tool_log: list[str] = []
                t0 = time.monotonic()

                async for event in agent.run_stream(text):
                    if event.type == EventType.TEXT:
                        response_parts.append(str(event.content or ""))
                    elif event.type == EventType.TEXT_DELTA:
                        response_parts.append(str(event.content or ""))
                    elif event.type == EventType.TOOL_CALL and event.tool_use:
                        tc = event.tool_use
                        tool_log.append(f"  {tc.name}")
                    elif event.type == EventType.TOOL_RESULT:
                        if isinstance(event.content, ToolResult):
                            status = "ok" if event.content.success else "err"
                            tool_log.append(f"    -> {status}")
                    elif event.type == EventType.ERROR:
                        response_parts.append(f"Error: {event.content}")
                    elif event.type == EventType.DONE and event.usage:
                        u = event.usage
                        elapsed = time.monotonic() - t0
                        tool_log.append(
                            f"\n[{u.input_tokens}+{u.output_tokens} tok, "
                            f"{u.tool_calls} tools, {u.rounds} rounds, "
                            f"{elapsed:.1f}s]"
                        )

                # Save conversation after each turn
                save_conversation(agent.conversation, cwd=self._cwd)

                # Build final response
                response = "".join(response_parts).strip()
                if tool_log:
                    tools_summary = "\n".join(tool_log)
                    response = f"{response}\n\n<pre>{html.escape(tools_summary)}</pre>"

                if not response:
                    response = "(no response)"

                # Send response (chunked if > 4096)
                await self._send_chunked(update, response)

            except Exception as e:
                logger.exception("Error processing message")
                error_msg = _format_error(e)
                await update.message.reply_text(error_msg)

            finally:
                self._busy = False
                if typing_task:
                    typing_task.cancel()
                    try:
                        await typing_task
                    except asyncio.CancelledError:
                        pass

    async def _send_chunked(self, update, text: str) -> None:
        """Send a message, chunking if it exceeds Telegram's limit."""
        # Try HTML parse mode first (for tool log formatting)
        for i in range(0, len(text), _MAX_MSG_LEN):
            chunk = text[i : i + _MAX_MSG_LEN]
            try:
                await update.message.reply_text(chunk, parse_mode="HTML")
            except Exception:
                logger.debug("HTML parse failed for chunk, falling back to plain text")
                await update.message.reply_text(chunk)

    def run(self) -> None:
        """Start the bot (blocking — runs until interrupted)."""
        from telegram.ext import Application, CommandHandler, MessageHandler, filters

        app = Application.builder().token(self._token).build()

        # Commands
        app.add_handler(CommandHandler("start", self.handle_start))
        app.add_handler(CommandHandler("help", self.handle_help))
        app.add_handler(CommandHandler("reset", self.handle_reset))
        app.add_handler(CommandHandler("status", self.handle_status))
        app.add_handler(CommandHandler("save", self.handle_save))

        # Text messages
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        logger.info("Telegram bot starting (owner_id=%d)", self._owner_id)
        app.run_polling(drop_pending_updates=True)


def _format_error(exc: Exception) -> str:
    """Format an exception into a user-friendly Telegram message."""
    type_name = type(exc).__name__
    msg = str(exc)

    # Categorize common errors
    if "No LLM providers" in msg or "API" in type_name:
        return f"Provider error: {msg}"
    if "timeout" in msg.lower() or "Timeout" in type_name:
        return f"Timeout: {msg}"
    if "permission" in msg.lower() or "Narasimha" in msg:
        return f"Blocked: {msg}"

    return f"Internal error ({type_name}): {msg}"


def main() -> None:
    """Entry point for Telegram bot."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Set TELEGRAM_BOT_TOKEN environment variable")
        print("Get one from @BotFather on Telegram")
        sys.exit(1)

    owner_id_str = os.environ.get("TELEGRAM_OWNER_ID", "0")
    try:
        owner_id = int(owner_id_str)
    except ValueError:
        print(f"TELEGRAM_OWNER_ID must be an integer, got: {owner_id_str}")
        sys.exit(1)

    if owner_id == 0:
        print("Warning: TELEGRAM_OWNER_ID not set — no user will have access")
        print("Get your Telegram user ID from @userinfobot")

    cwd = os.environ.get("STEWARD_CWD", os.getcwd())

    bot = TelegramBot(token=token, owner_id=owner_id, cwd=cwd)
    bot.run()


if __name__ == "__main__":
    main()
