from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

import main as main_module
from trading_bot.config.settings import Config
from trading_bot.data.storage.database import Database
from trading_bot.strategies.base_strategy import Signal


def _seed_price(test_db: Database, symbol: str = "TEST") -> None:
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-02-09", "2026-02-10", "2026-02-11"]),
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.0, 101.0, 102.0],
            "Volume": [1000, 1000, 1000],
            "Adj Close": [100.0, 101.0, 102.0],
        }
    )
    test_db.insert_price_data(frame, symbol)


def test_live_dry_run_blocks_broker_order_placement(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "test_live_dry_run.db"
    monkeypatch.setattr(Config, "DATABASE_URL", f"sqlite:///{db_path}", raising=False)
    test_db = Database()
    test_db.init_db()
    monkeypatch.setattr(main_module, "db", test_db)

    monkeypatch.setattr(main_module.MarketDataCollector, "get_nifty_500_list", lambda self: ["TEST.NS"])
    monkeypatch.setattr(main_module.MarketDataCollector, "filter_liquid_stocks", lambda self, symbols: symbols)
    monkeypatch.setattr(main_module.AlternativeDataScraper, "scrape_moneycontrol_trending", lambda self: [])
    monkeypatch.setattr(main_module.AlternativeDataScraper, "scrape_sector_performance", lambda self: [])
    monkeypatch.setattr(main_module.AlternativeDataScraper, "save_to_db", lambda self, rows: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_alert", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_trade_notification", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_morning_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_daily_pnl_report", lambda *args, **kwargs: None)

    class DummyBroker:
        def __init__(self):
            self.order_calls: list[tuple[str, int, str]] = []

        def connect(self) -> bool:
            return True

        def get_current_positions(self):
            return []

        def place_market_order(self, symbol: str, quantity: int, action: str):
            self.order_calls.append((symbol, quantity, action))
            return {"order_id": "LIVE_ORDER_SHOULD_NOT_HAPPEN"}

        def get_available_cash(self) -> float:
            return 100000.0

    dummy = DummyBroker()
    monkeypatch.setattr(main_module, "BrokerInterface", lambda: dummy)

    bot = main_module.TradingBot(
        paper_mode=False,
        dry_run_live=True,
        simulation_mode=True,
        simulation_date=datetime(2026, 2, 11),
    )
    _seed_price(test_db, "TEST")

    signal = Signal(
        symbol="TEST",
        action="BUY",
        price=100.0,
        quantity=10,
        stop_loss=95.0,
        target=110.0,
        strategy="Momentum Breakout",
        confidence=0.9,
        timestamp=datetime.now(),
        metadata={},
    )

    bot._execute_entry(signal)
    assert "TEST" in bot.positions
    assert dummy.order_calls == []

    bot._execute_exit("TEST", 101.0, "DRYRUN_EXIT")
    assert "TEST" not in bot.positions
    assert dummy.order_calls == []


def test_dry_run_requires_live_mode():
    with pytest.raises(ValueError, match="dry_run_live can only be used with live mode"):
        main_module.TradingBot(paper_mode=True, dry_run_live=True)


def test_live_mode_unarmed_forces_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "test_live_unarmed.db"
    monkeypatch.setattr(Config, "DATABASE_URL", f"sqlite:///{db_path}", raising=False)
    monkeypatch.setattr(Config, "LIVE_ORDER_EXECUTION_ENABLED", False, raising=False)
    monkeypatch.setattr(Config, "LIVE_ORDER_FORCE_ACK", "", raising=False)
    test_db = Database()
    test_db.init_db()
    monkeypatch.setattr(main_module, "db", test_db)

    monkeypatch.setattr(main_module.MarketDataCollector, "get_nifty_500_list", lambda self: ["TEST.NS"])
    monkeypatch.setattr(main_module.MarketDataCollector, "filter_liquid_stocks", lambda self, symbols: symbols)
    monkeypatch.setattr(main_module.AlternativeDataScraper, "scrape_moneycontrol_trending", lambda self: [])
    monkeypatch.setattr(main_module.AlternativeDataScraper, "scrape_sector_performance", lambda self: [])
    monkeypatch.setattr(main_module.AlternativeDataScraper, "save_to_db", lambda self, rows: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_alert", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_trade_notification", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_morning_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_daily_pnl_report", lambda *args, **kwargs: None)

    class DummyBroker:
        def __init__(self):
            self.order_calls: list[tuple[str, int, str]] = []

        def connect(self) -> bool:
            return True

        def get_current_positions(self):
            return []

        def place_market_order(self, symbol: str, quantity: int, action: str):
            self.order_calls.append((symbol, quantity, action))
            return {"order_id": "LIVE_ORDER_SHOULD_NOT_HAPPEN"}

        def get_available_cash(self) -> float:
            return 100000.0

    dummy = DummyBroker()
    monkeypatch.setattr(main_module, "BrokerInterface", lambda: dummy)

    bot = main_module.TradingBot(
        paper_mode=False,
        dry_run_live=False,
        simulation_mode=True,
        simulation_date=datetime(2026, 2, 11),
    )
    _seed_price(test_db, "TEST")
    assert bot.dry_run_live is True
    assert bot.live_orders_armed is False
    assert bot._should_place_live_orders() is False

    signal = Signal(
        symbol="TEST",
        action="BUY",
        price=100.0,
        quantity=10,
        stop_loss=95.0,
        target=110.0,
        strategy="Momentum Breakout",
        confidence=0.9,
        timestamp=datetime.now(),
        metadata={},
    )
    bot._execute_entry(signal)
    assert "TEST" in bot.positions
    assert dummy.order_calls == []


def test_live_mode_armed_allows_order_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "test_live_armed.db"
    monkeypatch.setattr(Config, "DATABASE_URL", f"sqlite:///{db_path}", raising=False)
    monkeypatch.setattr(Config, "LIVE_ORDER_EXECUTION_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "LIVE_ORDER_FORCE_ACK", Config.LIVE_ORDER_ACK_PHRASE, raising=False)
    test_db = Database()
    test_db.init_db()
    monkeypatch.setattr(main_module, "db", test_db)

    monkeypatch.setattr(main_module.MarketDataCollector, "get_nifty_500_list", lambda self: ["TEST.NS"])
    monkeypatch.setattr(main_module.MarketDataCollector, "filter_liquid_stocks", lambda self, symbols: symbols)
    monkeypatch.setattr(main_module.AlternativeDataScraper, "scrape_moneycontrol_trending", lambda self: [])
    monkeypatch.setattr(main_module.AlternativeDataScraper, "scrape_sector_performance", lambda self: [])
    monkeypatch.setattr(main_module.AlternativeDataScraper, "save_to_db", lambda self, rows: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_alert", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_trade_notification", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_morning_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_daily_pnl_report", lambda *args, **kwargs: None)

    class DummyBroker:
        def __init__(self):
            self.order_calls: list[tuple[str, int, str]] = []

        def connect(self) -> bool:
            return True

        def get_current_positions(self):
            return []

        def place_market_order(self, symbol: str, quantity: int, action: str):
            self.order_calls.append((symbol, quantity, action))
            return {"order_id": "LIVE_ORDER_OK"}

        def get_available_cash(self) -> float:
            return 100000.0

    dummy = DummyBroker()
    monkeypatch.setattr(main_module, "BrokerInterface", lambda: dummy)

    bot = main_module.TradingBot(
        paper_mode=False,
        dry_run_live=False,
        simulation_mode=True,
        simulation_date=datetime(2026, 2, 11),
    )
    _seed_price(test_db, "TEST")
    assert bot.dry_run_live is False
    assert bot.live_orders_armed is True
    assert bot._should_place_live_orders() is True

    signal = Signal(
        symbol="TEST",
        action="BUY",
        price=100.0,
        quantity=10,
        stop_loss=95.0,
        target=110.0,
        strategy="Momentum Breakout",
        confidence=0.9,
        timestamp=datetime.now(),
        metadata={},
    )
    bot._execute_entry(signal)
    assert "TEST" in bot.positions
    assert len(dummy.order_calls) == 1
