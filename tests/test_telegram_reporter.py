from __future__ import annotations

import asyncio

from trading_bot.reporting.telegram_bot import TelegramReporter


def test_send_message_sync_falls_back_when_primary_loop_closed(monkeypatch):
    reporter = TelegramReporter()
    sent = {"count": 0}

    async def fake_send_message(message: str, parse_mode: str = "HTML") -> None:
        _ = message
        _ = parse_mode
        sent["count"] += 1

    def fake_asyncio_run(_coroutine):
        raise RuntimeError("Event loop is closed")

    monkeypatch.setattr(reporter, "send_message", fake_send_message)
    monkeypatch.setattr(asyncio, "run", fake_asyncio_run)

    reporter.send_message_sync("hello")

    assert sent["count"] == 1
