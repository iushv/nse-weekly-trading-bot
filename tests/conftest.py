from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

# Ensure repository root is importable in CI and local runs.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main as main_module
from trading_bot.config.settings import Config
from trading_bot.data.storage.database import Database


@pytest.fixture
def bot_with_test_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Create a TradingBot instance with isolated sqlite DB and no external calls."""
    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "test_bot.db"
    monkeypatch.setattr(Config, "DATABASE_URL", f"sqlite:///{db_path}", raising=False)
    test_db = Database()
    test_db.init_db()

    monkeypatch.setattr(main_module, "db", test_db)

    # Avoid network access during init and routines.
    monkeypatch.setattr(main_module.MarketDataCollector, "get_nifty_500_list", lambda self: ["TEST.NS"])
    monkeypatch.setattr(main_module.MarketDataCollector, "filter_liquid_stocks", lambda self, symbols: symbols)
    monkeypatch.setattr(main_module.AlternativeDataScraper, "scrape_moneycontrol_trending", lambda self: [])
    monkeypatch.setattr(main_module.AlternativeDataScraper, "scrape_sector_performance", lambda self: [])
    monkeypatch.setattr(main_module.AlternativeDataScraper, "save_to_db", lambda self, data_list: None)

    # Avoid external Telegram calls.
    monkeypatch.setattr(main_module.TelegramReporter, "send_alert", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_trade_notification", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_morning_report", lambda *args, **kwargs: None)

    bot = main_module.TradingBot(paper_mode=True)
    monkeypatch.setattr(bot.data_collector, "update_daily_data", lambda symbols: None)
    return bot, test_db


@pytest.fixture
def seed_test_symbol_prices():
    def _seed(test_db: Database, symbol: str = "TEST") -> pd.DataFrame:
        end_date = pd.Timestamp.today().normalize()
        dates = pd.date_range(end=end_date, periods=40, freq="D")
        close = pd.Series(range(100, 140), dtype=float)
        frame = pd.DataFrame(
            {
                "Date": dates,
                "Open": close - 1,
                "High": close + 1,
                "Low": close - 2,
                "Close": close,
                "Volume": 1_000_000,
                "Adj Close": close,
            }
        )
        test_db.insert_price_data(frame, symbol)
        return frame

    return _seed
