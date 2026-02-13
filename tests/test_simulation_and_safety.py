from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import text

from trading_bot.strategies.base_strategy import Signal


def test_get_current_price_respects_simulation_date(bot_with_test_db):
    bot, test_db = bot_with_test_db

    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "Open": [100.0, 110.0, 120.0],
            "High": [101.0, 111.0, 121.0],
            "Low": [99.0, 109.0, 119.0],
            "Close": [100.0, 110.0, 120.0],
            "Volume": [1000, 1000, 1000],
            "Adj Close": [100.0, 110.0, 120.0],
        }
    )
    test_db.insert_price_data(frame, "TEST")

    bot.set_simulation_date(datetime(2024, 1, 2))
    row = bot._get_current_price("TEST")
    assert row is not None
    assert float(row["close"]) == 110.0


def test_kill_switch_blocks_pre_market(bot_with_test_db):
    bot, _ = bot_with_test_db

    bot.kill_switch_path.write_text("STOP", encoding="utf-8")
    bot.pre_market_routine()
    assert bot.pending_signals == []


def test_entry_intent_idempotency(bot_with_test_db):
    bot, test_db = bot_with_test_db

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
    )

    bot._execute_entry(signal)
    bot._execute_entry(signal)

    trades_df = pd.read_sql("SELECT * FROM trades", test_db.engine)
    assert len(trades_df) == 1
    assert trades_df.iloc[0]["status"] == "OPEN"


def test_market_close_persists_snapshot_and_closed_trades(bot_with_test_db):
    bot, test_db = bot_with_test_db
    bot.set_simulation_date(datetime(2024, 1, 3))

    # Seed one closed trade row to exercise close-report queries.
    with test_db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT OR REPLACE INTO trades (
                    order_id, symbol, strategy, action, quantity, entry_price, entry_date,
                    exit_price, exit_date, stop_loss, target, pnl, pnl_percent, status, notes
                ) VALUES (
                    :order_id, :symbol, :strategy, :action, :quantity, :entry_price, :entry_date,
                    :exit_price, :exit_date, :stop_loss, :target, :pnl, :pnl_percent, :status, :notes
                )
                """
            ),
            {
                "order_id": "PAPER_CLOSED_1",
                "symbol": "TEST",
                "strategy": "Momentum Breakout",
                "action": "SELL",
                "quantity": 10,
                "entry_price": 100.0,
                "entry_date": "2024-01-02 09:15:00",
                "exit_price": 102.0,
                "exit_date": "2024-01-03 15:20:00",
                "stop_loss": 95.0,
                "target": 110.0,
                "pnl": 20.0,
                "pnl_percent": 2.0,
                "status": "CLOSED",
                "notes": "TARGET_HIT",
            },
        )

    bot.market_close_routine()
    snaps = pd.read_sql("SELECT * FROM portfolio_snapshots", test_db.engine)
    assert len(snaps) == 1
