from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

import main as main_module
from trading_bot.config.settings import Config
from trading_bot.data.storage.database import Database


def _build_live_dry_run_bot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "test_reconcile.db"
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
            self.positions = []

        def connect(self) -> bool:
            return True

        def get_current_positions(self):
            return self.positions

        def place_market_order(self, symbol: str, quantity: int, action: str):
            _ = (symbol, quantity, action)
            return {"order_id": "NOOP"}

    dummy = DummyBroker()
    monkeypatch.setattr(main_module, "BrokerInterface", lambda: dummy)

    bot = main_module.TradingBot(
        paper_mode=False,
        dry_run_live=True,
        simulation_mode=True,
        simulation_date=datetime(2026, 2, 11),
    )
    return bot, test_db, dummy


def test_reconciliation_logs_mismatches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    bot, test_db, dummy = _build_live_dry_run_bot(monkeypatch, tmp_path)
    dummy.positions = []

    with test_db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR REPLACE INTO trades
                (order_id, symbol, strategy, action, quantity, entry_price, entry_date, status)
                VALUES
                ('OPEN_TEST_1', 'TEST', 'Momentum Breakout', 'BUY', 5, 100.0, '2026-02-10T09:15:00', 'OPEN')
                """
            )
        )

    summary = bot.reconciliation_routine()
    assert summary["mismatched_open_trades"] == 1
    assert summary["auto_closed_trades"] == 0

    logs_df = pd.read_sql(
        "SELECT * FROM system_logs WHERE module='reconciliation' AND level='WARNING'",
        test_db.engine,
    )
    assert len(logs_df) >= 1


def test_reconciliation_can_auto_close(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(Config, "RECONCILIATION_ENFORCE_CLOSE", True, raising=False)
    bot, test_db, dummy = _build_live_dry_run_bot(monkeypatch, tmp_path)
    dummy.positions = []

    with test_db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR REPLACE INTO trades
                (order_id, symbol, strategy, action, quantity, entry_price, entry_date, status)
                VALUES
                ('OPEN_TEST_2', 'TEST', 'Momentum Breakout', 'BUY', 3, 100.0, '2026-02-10T09:15:00', 'OPEN')
                """
            )
        )

    summary = bot.reconciliation_routine()
    assert summary["auto_closed_trades"] == 1

    closed_df = pd.read_sql("SELECT * FROM trades WHERE order_id='OPEN_TEST_2'", test_db.engine)
    assert len(closed_df) == 1
    assert closed_df.iloc[0]["status"] == "CLOSED"
    assert closed_df.iloc[0]["notes"] == "RECONCILE_AUTO_CLOSE_MISSING_AT_BROKER"
