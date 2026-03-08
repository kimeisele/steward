"""Tests for Telegram bot interface."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from steward.interfaces.telegram import TelegramBot


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


class TestTelegramAuth:
    """Authentication gate — only owner gets agent access."""

    def test_non_owner_rejected(self):
        """Non-owner messages get rejected without LLM call."""
        bot = TelegramBot(token="fake", owner_id=12345)
        update = FakeUpdate(
            effective_user=FakeUser(id=99999),  # not the owner
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


class TestTelegramBot:
    """Bot construction and configuration."""

    def test_bot_creates(self):
        """Bot can be created with token and owner_id."""
        bot = TelegramBot(token="test:token", owner_id=12345)
        assert bot._owner_id == 12345
        assert bot._token == "test:token"
        assert bot._agent is None  # lazy init

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

    def test_chunked_send(self):
        """Long messages are chunked at 4096 chars."""
        bot = TelegramBot(token="fake", owner_id=42)
        update = FakeUpdate(
            effective_user=FakeUser(id=42),
            message=FakeMessage.create("test"),
        )

        # Send a message longer than 4096 chars
        long_text = "x" * 5000
        asyncio.run(bot._send_chunked(update, long_text))

        # Should be called twice (4096 + 904)
        assert update.message.reply_text.call_count == 2
