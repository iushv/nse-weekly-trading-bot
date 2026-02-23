from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from sqlalchemy import text

import main as main_module
from trading_bot.config.settings import Config
from trading_bot.risk.risk_manager import RiskManager


def test_restart_reconstructs_cash_and_position_metadata(bot_with_test_db, seed_test_symbol_prices):
    bot, test_db = bot_with_test_db
    seed_test_symbol_prices(test_db, symbol="TEST")
    today = bot._today_str()

    with test_db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR REPLACE INTO trades (
                    order_id, symbol, strategy, action, quantity, entry_price, entry_date,
                    stop_loss, target, highest_close, lowest_close, weekly_atr, status
                ) VALUES (
                    :order_id, :symbol, :strategy, :action, :quantity, :entry_price, :entry_date,
                    :stop_loss, :target, :highest_close, :lowest_close, :weekly_atr, :status
                )
                """
            ),
            {
                "order_id": "PAPER_TEST_RESTORE_001",
                "symbol": "TEST",
                "strategy": "Adaptive Trend",
                "action": "BUY",
                "quantity": 10,
                "entry_price": 120.0,
                "entry_date": f"{today} 09:20:00",
                "stop_loss": 110.0,
                "target": 150.0,
                "highest_close": 132.5,
                "lowest_close": 118.2,
                "weekly_atr": 6.4,
                "status": "OPEN",
            },
        )
        # Simulate stale/inflated snapshot values that were saved before restart.
        conn.execute(
            text(
                """
                INSERT OR REPLACE INTO portfolio_snapshots (
                    date, total_value, cash, positions_value, num_positions, daily_pnl, daily_pnl_percent, total_pnl, total_pnl_percent
                ) VALUES (
                    :date, :total_value, :cash, :positions_value, :num_positions, 0, 0, :total_pnl, :total_pnl_percent
                )
                """
            ),
            {
                "date": today,
                "total_value": 101200.0,
                "cash": 100000.0,
                "positions_value": 1200.0,
                "num_positions": 1,
                "total_pnl": 1200.0,
                "total_pnl_percent": 1.2,
            },
        )

    restarted = main_module.TradingBot(paper_mode=True)

    expected_cash = Config.STARTING_CAPITAL - (120.0 * 10.0 * (1 + Config.COST_PER_SIDE))
    assert abs(restarted.cash - expected_cash) < 1e-6
    assert "TEST" in restarted.positions
    pos = restarted.positions["TEST"]
    assert float(pos["highest_close"]) == 132.5
    assert float(pos["lowest_close"]) == 118.2
    assert float(pos["weekly_atr"]) == 6.4


def test_load_market_data_scopes_to_universe(bot_with_test_db):
    bot, test_db = bot_with_test_db
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=3, freq="D")

    test_frame = pd.DataFrame(
        {
            "Date": dates,
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1000, 1100, 1200],
            "Adj Close": [100.5, 101.5, 102.5],
        }
    )
    extra_frame = test_frame.copy()
    extra_frame["Close"] = [200.5, 201.5, 202.5]

    test_db.insert_price_data(test_frame, "TEST")
    test_db.insert_price_data(extra_frame, "EXTRA")

    bot.universe = ["TEST"]
    market = bot._load_market_data()
    assert not market.empty
    assert set(market["symbol"].astype(str).unique()) == {"TEST"}


def test_risk_manager_reconstructs_daily_and_weekly_pnl(bot_with_test_db):
    _bot, test_db = bot_with_test_db
    with test_db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR REPLACE INTO trades (
                    order_id, symbol, strategy, action, quantity, entry_price, entry_date,
                    exit_price, exit_date, pnl, status
                ) VALUES
                    ('CLOSE_1', 'TEST', 'Adaptive Trend', 'SELL', 1, 100, '2026-02-18 09:20:00', 110, '2026-02-20 10:00:00', 10, 'CLOSED'),
                    ('CLOSE_2', 'TEST', 'Adaptive Trend', 'SELL', 1, 100, '2026-02-17 09:20:00', 105, '2026-02-19 10:00:00', 5, 'CLOSED'),
                    ('CLOSE_3', 'TEST', 'Adaptive Trend', 'SELL', 1, 100, '2026-02-10 09:20:00', 95, '2026-02-13 10:00:00', -5, 'CLOSED')
                """
            )
        )

    clock = lambda: datetime(2026, 2, 20, 12, 0, 0)
    risk = RiskManager(initial_capital=100000.0, clock=clock)
    risk.reconstruct_realized_pnl(test_db.engine, date(2026, 2, 20))

    assert risk.daily_pnl == 10.0
    assert risk.weekly_pnl == 15.0
