from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from trading_bot.data.collectors.alternative_data import AlternativeDataScraper
from trading_bot.data.collectors.market_data import MarketDataCollector
from trading_bot.data.collectors import market_data as market_data_module


def test_collectors_disable_env_proxy_usage():
    assert MarketDataCollector().session.trust_env is False
    assert AlternativeDataScraper().session.trust_env is False


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


def test_update_daily_data_honors_required_latest_date(monkeypatch):
    collector = MarketDataCollector()
    required_date = date(2026, 2, 17)
    previous_day = date(2026, 2, 16)
    latest_map = {"RELIANCE.NS": previous_day}

    monkeypatch.setattr(collector, "_get_latest_price_date", lambda symbol: latest_map.get(symbol, previous_day))

    sample = pd.DataFrame(
        {
            "Date": pd.date_range("2026-02-17", periods=1, freq="D"),
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [1000],
            "Adj Close": [100.5],
        }
    )

    def fake_fetch(symbol, start_date, end_date=None):
        _ = start_date
        _ = end_date
        latest_map[symbol] = required_date
        return sample

    monkeypatch.setattr(collector, "fetch_historical_data", fake_fetch)
    monkeypatch.setattr(market_data_module.db, "insert_price_data", lambda df, symbol: len(df))

    summary = collector.update_daily_data(["RELIANCE.NS"], required_latest_date=required_date)

    assert int(summary["updated_symbols"]) == 1
    assert int(summary["failed_symbols"]) == 0
    assert summary["unresolved_symbols"] == []


def test_latest_trading_day_rolls_back_weekend():
    collector = MarketDataCollector()
    assert collector._latest_trading_day(date(2026, 2, 15)) == date(2026, 2, 13)


def test_get_nifty_midcap_150_list_parses_symbols(monkeypatch, tmp_path):
    collector = MarketDataCollector()
    collector.midcap_cache_path = tmp_path / "midcap.json"

    csv_text = "Symbol,Company Name\nABC,ABC LTD\nXYZ,XYZ LTD\n"

    class FakeResp:
        def __init__(self, text: str):
            self.text = text

    monkeypatch.setattr(collector, "_request_with_retries", lambda url: FakeResp(csv_text))

    symbols = collector.get_nifty_midcap_150_list()
    assert symbols == ["ABC.NS", "XYZ.NS"]


def test_get_nifty_midcap_150_list_falls_back_to_cache(monkeypatch, tmp_path):
    collector = MarketDataCollector()
    collector.midcap_cache_path = tmp_path / "midcap.json"
    collector.midcap_cache_path.write_text('{"updated_at":"now","symbols":["AAA.NS","BBB.NS"]}', encoding="utf-8")

    def fail_request(**_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(collector, "_request_with_retries", fail_request)

    symbols = collector.get_nifty_midcap_150_list()
    assert symbols == ["AAA.NS", "BBB.NS"]
