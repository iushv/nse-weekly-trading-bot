from __future__ import annotations

from datetime import timedelta

import pandas as pd

from trading_bot.data.collectors.market_data import MarketDataCollector
from trading_bot.data.collectors import market_data as market_data_module


def test_update_daily_data_skips_fresh_symbols(monkeypatch):
    collector = MarketDataCollector()
    today = pd.Timestamp.today().date()

    monkeypatch.setattr(collector, "_get_latest_price_date", lambda _symbol: today)

    fetch_calls = {"count": 0}

    def fake_fetch(_symbol, start_date, end_date=None):
        _ = start_date
        _ = end_date
        fetch_calls["count"] += 1
        return None

    monkeypatch.setattr(collector, "fetch_historical_data", fake_fetch)

    insert_calls = {"count": 0}

    def fake_insert(df, symbol):
        _ = df
        _ = symbol
        insert_calls["count"] += 1
        return 0

    monkeypatch.setattr(market_data_module.db, "insert_price_data", fake_insert)

    collector.update_daily_data(["RELIANCE.NS", "TCS.NS"])

    assert fetch_calls["count"] == 0
    assert insert_calls["count"] == 0


def test_update_daily_data_fetches_stale_symbols(monkeypatch):
    collector = MarketDataCollector()
    stale_date = pd.Timestamp.today().date() - timedelta(days=10)
    monkeypatch.setattr(collector, "_get_latest_price_date", lambda _symbol: stale_date)

    fetch_calls = {"count": 0}
    sample = pd.DataFrame(
        {
            "Date": pd.date_range("2026-02-01", periods=2, freq="D"),
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Volume": [1000, 1200],
            "Adj Close": [101.0, 102.0],
        }
    )

    def fake_fetch(_symbol, start_date, end_date=None):
        _ = start_date
        _ = end_date
        fetch_calls["count"] += 1
        return sample

    monkeypatch.setattr(collector, "fetch_historical_data", fake_fetch)

    inserted: list[str] = []

    def fake_insert(df, symbol):
        _ = df
        inserted.append(symbol)
        return len(sample)

    monkeypatch.setattr(market_data_module.db, "insert_price_data", fake_insert)

    collector.update_daily_data(["RELIANCE.NS"])

    assert fetch_calls["count"] == 1
    assert inserted == ["RELIANCE.NS"]
