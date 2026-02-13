from __future__ import annotations

from datetime import datetime

from trading_bot.data.storage.feature_store import FeatureStore


def test_feature_store_entry_and_outcome_roundtrip(bot_with_test_db):
    _, test_db = bot_with_test_db
    feature_store = FeatureStore(test_db.engine)

    feature_store.save_entry_features(
        order_id="PAPER_ADAPT_1",
        symbol="TEST",
        strategy="Adaptive Trend",
        entry_date=datetime(2026, 2, 12, 9, 15),
        entry_price=100.0,
        stop_loss=95.0,
        target=120.0,
        quantity=10,
        confidence=0.78,
        metadata={
            "weekly_ema_short": 105.0,
            "weekly_ema_long": 100.0,
            "weekly_atr": 3.0,
            "weekly_rsi": 58.0,
            "weekly_roc": 0.08,
            "market_regime_label": "favorable",
            "market_breadth_ratio": 0.66,
            "market_regime_confidence": 0.72,
            "market_regime_trend_up": True,
        },
    )
    row = test_db.execute_query("SELECT * FROM trade_features WHERE order_id='PAPER_ADAPT_1'")
    assert len(row) == 1

    feature_store.update_trade_outcome(
        order_id="PAPER_ADAPT_1",
        exit_date=datetime(2026, 2, 19, 15, 20),
        exit_price=110.0,
        pnl=95.0,
        pnl_percent=9.5,
        days_held=7,
        exit_reason="TRAILING_STOP",
    )
    row = test_db.execute_query(
        "SELECT outcome_label, exit_reason, pnl FROM trade_features WHERE order_id='PAPER_ADAPT_1'"
    )
    assert len(row) == 1
    assert row[0][0] == 1
    assert row[0][1] == "TRAILING_STOP"
    assert float(row[0][2]) == 95.0

    training_df = feature_store.get_training_data(min_rows=1)
    assert len(training_df) == 1
