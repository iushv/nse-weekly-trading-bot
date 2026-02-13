from __future__ import annotations

from datetime import datetime

import pandas as pd


def test_save_trade_to_db_replaces_open_with_closed(bot_with_test_db):
    bot, test_db = bot_with_test_db

    open_trade = {
        "order_id": "PAPER_TEST_001",
        "symbol": "TEST",
        "strategy": "Momentum Breakout",
        "quantity": 10,
        "entry_price": 100.0,
        "entry_date": datetime(2024, 1, 1, 9, 15),
        "stop_loss": 95.0,
        "target": 110.0,
    }
    bot._save_trade_to_db(open_trade, status="OPEN")

    open_rows = pd.read_sql("SELECT * FROM trades WHERE order_id='PAPER_TEST_001'", test_db.engine)
    assert len(open_rows) == 1
    assert open_rows.iloc[0]["status"] == "OPEN"
    assert open_rows.iloc[0]["action"] == "BUY"

    closed_trade = {
        **open_trade,
        "exit_price": 106.0,
        "exit_date": datetime(2024, 1, 3, 15, 25),
        "pnl": 55.0,
        "pnl_percent": 5.5,
        "exit_reason": "TARGET_HIT",
        "action": "SELL",
    }
    bot._save_trade_to_db(closed_trade, status="CLOSED")

    final_rows = pd.read_sql("SELECT * FROM trades WHERE order_id='PAPER_TEST_001'", test_db.engine)
    assert len(final_rows) == 1
    row = final_rows.iloc[0]
    assert row["status"] == "CLOSED"
    assert row["action"] == "SELL"
    assert row["exit_price"] == 106.0
    assert row["pnl"] == 55.0
    assert row["notes"] == "TARGET_HIT"

