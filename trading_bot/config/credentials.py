from __future__ import annotations

from dataclasses import dataclass

from trading_bot.config.settings import Config


@dataclass(frozen=True)
class Credentials:
    groww_api_key: str | None
    groww_api_secret: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None


credentials = Credentials(
    groww_api_key=Config.GROWW_API_KEY,
    groww_api_secret=Config.GROWW_API_SECRET,
    telegram_bot_token=Config.TELEGRAM_BOT_TOKEN,
    telegram_chat_id=Config.TELEGRAM_CHAT_ID,
)
