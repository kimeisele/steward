"""Tests for Telegram bot interface.

These tests mock the steward agent internals so they work
without vibe_core or LLM provider dependencies. We test
the Telegram bot's own logic: auth gates, command handlers,
chunking, error formatting, typing indicator, busy rejection.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Mock infrastructure ──────────────────────────────────────────
# We need to mock steward.agent and friends before importing
# the telegram module, since vibe_core may not be installed.


@dataclass
class FakeUser:
    id: int
    first_name: str = "Test"


@dataclass
class FakeChat:
    id: int = 1

    async def send_action(self, action: str) -> None:
        pass


@dataclass
class FakeMessage:
    text: str
    chat: FakeChat
    reply_text: AsyncMock

    @classmethod
    def create(cls, text: str) -> FakeMessage:
        return cls(text=text, chat=FakeChat(), reply_text=AsyncMock())


@dataclass
class FakeUpdate:
    effective_user: FakeUser
    message: FakeMessage


def _make_telegram_module():
    """Import telegram module with mocked steward dependencies."""
    # Create mock modules for steward internals
    mock_agent_mod = MagicMock()
    mock_provider_mod = MagicMock()
    mock_state_mod = MagicMock()
    mock_types_mod = MagicMock()

    # EventType needs real string values for comparisons
    class FakeEventType:
        TEXT_DELTA = "text_delta"
        TEXT = "text"
        TOOL_CALL = "tool_call"
        TOOL_RESULT = "tool_result"
        ERROR = "error"
        DONE = "done"

    mock_types_mod.EventType = FakeEventType

    # Patch modules before import
    patches = {
        "steward.agent": mock_agent_mod,
        "steward.provider": mock_provider_mod,
        "steward.state": mock_state_mod,
        "steward.types": mock_types_mod,
    }

    # Also mock vibe_core and its sub-modules to prevent import errors
    vibe_mocks = {}
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("vibe_core"):
            vibe_mocks[mod_name] = sys.modules[mod_name]

    with patch.dict(sys.modules, patches):
        # Force reimport
        if "steward.interfaces.telegram" in sys.modules:
            del sys.modules["steward.interfaces.telegram"]

        from steward.interfaces.telegram import TelegramBot, _format_error

        return TelegramBot, _format_error, mock_agent_mod, mock_state_mod, FakeEventType


# Import once for all tests
TelegramBot, _format_error, _mock_agent_mod, _mock_state_mod, _FakeEventType = _make_telegram_module()


# ── Auth Tests ────────────────────────────────────────────────────


class TestTelegramAuth:
    """Authentication gate — only owner gets agent access."""

    def test_non_owner_rejected(self):
        """Non-owner messages get rejected without LLM call."""
        bot = TelegramBot(token="fake", owner_id=12345)
        update = FakeUpdate(
            effective_user=FakeUser(id=99999),
            message=FakeMessage.create("hack the system"),
        )
        asyncio.run(bot.handle_message(update, None))
        update.message.reply_text.assert_called_once()
        args = update.message.reply_text.call_args
        assert "Read-only" in args[0][0]

    def test_start_shows_owner_status(self):
        """Start command shows correct access level."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create("/start"),
        )
        asyncio.run(bot.handle_start(update, None))
        args = update.message.reply_text.call_args
        assert "Owner access" in args[0][0]

    def test_start_shows_readonly_for_others(self):
        """Non-owners see read-only status."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=99),
            message=FakeMessage.create("/start"),
        )
        asyncio.run(bot.handle_start(update, None))
        args = update.message.reply_text.call_args
        assert "Read-only" in args[0][0]

    def test_reset_blocked_for_non_owner(self):
        """Non-owners can't reset the conversation."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=99),
            message=FakeMessage.create("/reset"),
        )
        asyncio.run(bot.handle_reset(update, None))
        args = update.message.reply_text.call_args
        assert "owner" in args[0][0].lower()

    def test_save_blocked_for_non_owner(self):
        """Non-owners can't save the session."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=99),
            message=FakeMessage.create("/save"),
        )
        asyncio.run(bot.handle_save(update, None))
        args = update.message.reply_text.call_args
        assert "owner" in args[0][0].lower()


# ── Bot Construction ──────────────────────────────────────────────


class TestTelegramBot:
    """Bot construction and configuration."""

    def test_bot_creates(self):
        """Bot can be created with token and owner_id."""
        bot = TelegramBot(token="test:token", owner_id=12345)
        assert bot._owner_id == 12345
        assert bot._token == "test:token"
        assert bot._agent is None  # lazy init
        assert bot._busy is False

    def test_bot_with_cwd(self):
        """Bot accepts custom working directory."""
        bot = TelegramBot(token="fake", owner_id=1, cwd="/tmp/test")
        assert bot._cwd == "/tmp/test"

    def test_empty_message_ignored(self):
        """Empty messages don't crash."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create(""),
        )
        update.message.text = ""
        asyncio.run(bot.handle_message(update, None))
        update.message.reply_text.assert_not_called()

    def test_none_text_ignored(self):
        """None text doesn't crash."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create("test"),
        )
        update.message.text = None
        asyncio.run(bot.handle_message(update, None))
        update.message.reply_text.assert_not_called()


# ── Chunking ──────────────────────────────────────────────────────


class TestChunkedSend:
    """Message chunking for Telegram's 4096 char limit."""

    def test_short_message_single_send(self):
        """Messages under 4096 chars sent in one chunk."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create("test"),
        )
        asyncio.run(bot._send_chunked(update, "Hello world"))
        assert update.message.reply_text.call_count == 1

    def test_long_message_chunked(self):
        """Long messages are chunked at 4096 chars."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create("test"),
        )
        long_text = "x" * 5000
        asyncio.run(bot._send_chunked(update, long_text))
        # Should be called twice (4096 + 904)
        assert update.message.reply_text.call_count == 2

    def test_exact_boundary_no_extra_chunk(self):
        """Message exactly at 4096 chars produces one chunk."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create("test"),
        )
        exact_text = "x" * 4096
        asyncio.run(bot._send_chunked(update, exact_text))
        assert update.message.reply_text.call_count == 1

    def test_html_fallback_on_parse_error(self):
        """Falls back to plain text when HTML parse fails."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create("test"),
        )
        # First call (HTML) raises, second (plain) succeeds
        update.message.reply_text.side_effect = [Exception("parse error"), None]
        asyncio.run(bot._send_chunked(update, "hello"))
        assert update.message.reply_text.call_count == 2
        # Second call should have no parse_mode
        second_call = update.message.reply_text.call_args_list[1]
        assert "parse_mode" not in second_call.kwargs


# ── Help Command ──────────────────────────────────────────────────


class TestHelpCommand:
    """The /help command."""

    def test_help_lists_commands(self):
        """/help shows available commands."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create("/help"),
        )
        asyncio.run(bot.handle_help(update, None))
        args = update.message.reply_text.call_args
        text = args[0][0]
        assert "/start" in text
        assert "/help" in text
        assert "/status" in text
        assert "/reset" in text
        assert "/save" in text

    def test_help_accessible_by_non_owner(self):
        """/help is available to everyone."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=99),
            message=FakeMessage.create("/help"),
        )
        asyncio.run(bot.handle_help(update, None))
        # Should succeed without auth rejection
        args = update.message.reply_text.call_args
        assert "/start" in args[0][0]


# ── Save Command ──────────────────────────────────────────────────


class TestSaveCommand:
    """The /save command."""

    def test_save_no_active_session(self):
        """Save without active agent returns appropriate message."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create("/save"),
        )
        asyncio.run(bot.handle_save(update, None))
        args = update.message.reply_text.call_args
        assert "No active session" in args[0][0]

    def test_save_with_active_agent(self):
        """Save with active agent calls save_conversation."""
        bot = TelegramBot(token="fake", owner_id=42)
        bot._agent = MagicMock()
        bot._agent.conversation = MagicMock()
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create("/save"),
        )
        asyncio.run(bot.handle_save(update, None))
        args = update.message.reply_text.call_args
        assert "saved" in args[0][0].lower()


# ── Busy Rejection ────────────────────────────────────────────────


class TestBusyRejection:
    """Concurrent request handling."""

    def test_busy_rejects_second_request(self):
        """Second message while processing gets rejected."""
        bot = TelegramBot(token="fake", owner_id=42)
        bot._busy = True
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create("do something"),
        )
        asyncio.run(bot.handle_message(update, None))
        args = update.message.reply_text.call_args
        assert "processing" in args[0][0].lower() or "wait" in args[0][0].lower()


# ── Error Formatting ──────────────────────────────────────────────


class TestErrorFormatting:
    """User-friendly error messages."""

    def test_provider_error(self):
        """Provider/API errors get categorized."""
        msg = _format_error(RuntimeError("No LLM providers configured"))
        assert "Provider error" in msg

    def test_timeout_error(self):
        """Timeout errors get categorized."""
        msg = _format_error(TimeoutError("connection timeout"))
        assert "Timeout" in msg

    def test_permission_error(self):
        """Narasimha/permission blocks get categorized."""
        msg = _format_error(RuntimeError("Narasimha blocked rm -rf"))
        assert "Blocked" in msg

    def test_generic_error(self):
        """Unknown errors include type name."""
        msg = _format_error(ValueError("something broke"))
        assert "ValueError" in msg
        assert "something broke" in msg


# ── Is Owner Helper ───────────────────────────────────────────────


class TestIsOwner:
    """Owner check helper method."""

    def test_owner_returns_true(self):
        bot = TelegramBot(token="fake", owner_id=42)
        assert bot._is_owner(FakeUser(id=42)) is True

    def test_non_owner_returns_false(self):
        bot = TelegramBot(token="fake", owner_id=42)
        assert bot._is_owner(FakeUser(id=99)) is False


# ── Reset Command ─────────────────────────────────────────────────


class TestResetCommand:
    """The /reset command."""

    def test_reset_with_active_agent(self):
        """Reset clears the agent and saves."""
        bot = TelegramBot(token="fake", owner_id=42)
        bot._agent = MagicMock()
        bot._agent.conversation = MagicMock()
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create("/reset"),
        )
        asyncio.run(bot.handle_reset(update, None))
        bot._agent.reset.assert_called_once()
        args = update.message.reply_text.call_args
        assert "reset" in args[0][0].lower()

    def test_reset_without_agent(self):
        """Reset without agent doesn't crash."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create("/reset"),
        )
        asyncio.run(bot.handle_reset(update, None))
        args = update.message.reply_text.call_args
        assert "reset" in args[0][0].lower()
