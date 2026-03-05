from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from trading_bot.data.collectors.market_data import MarketDataCollector
from trading_bot.data.storage.database import Database


def _day_frame(
    trading_date: date,
    *,
    symbol: str = "ABC",
    close: float = 100.0,
    prev_close: float = 100.0,
    face_val: float = 10.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Symbol": [symbol],
            "Date": [pd.Timestamp(trading_date)],
            "Open": [close],
            "High": [close],
            "Low": [close],
            "Close": [close],
            "Volume": [1000],
            "PrevClose": [prev_close],
            "FaceVal": [face_val],
        }
    )


def _make_db(tmp_path: Path) -> Database:
    db_path = tmp_path / "corp_actions_test.db"
    database = Database(f"sqlite:///{db_path}")
    database.init_db()
    return database


def _insert_prices(database: Database, symbol: str, closes: list[float], start: str = "2025-01-01") -> None:
    dates = pd.date_range(start=start, periods=len(closes), freq="D")
    frame = pd.DataFrame(
        {
            "Date": dates,
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1000] * len(closes),
            "Adj Close": closes,
        }
    )
    database.upsert_price_data(frame, symbol)


def _read_symbol_rows(database: Database, symbol: str) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT date, open, high, low, close, volume, adj_close FROM price_data WHERE symbol=:s ORDER BY date",
        database.engine,
        params={"s": symbol},
    )


def test_detect_split_from_prev_close(monkeypatch):
    collector = MarketDataCollector()
    trade_day = date(2026, 1, 9)
    prev_day = date(2026, 1, 8)

    day_map = {
        trade_day: _day_frame(trade_day, close=52.0, prev_close=50.0, face_val=5.0),
        prev_day: _day_frame(prev_day, close=100.0, prev_close=100.0, face_val=10.0),
    }

    monkeypatch.setattr(collector, "_fetch_bhavcopy_day", lambda d: day_map.get(d))
    monkeypatch.setattr(collector, "_get_db_previous_close", lambda symbol, trading_date: 100.0)

    actions = collector.detect_corporate_actions_for_day(trade_day, symbols={"ABC"})

    assert len(actions) == 1
    assert actions[0]["action_type"] == "split"
    assert actions[0]["adjustment_factor"] == 2.0
    assert actions[0]["face_val_before"] == 10.0
    assert actions[0]["face_val_after"] == 5.0


def test_detect_bonus_from_prev_close(monkeypatch):
    collector = MarketDataCollector()
    trade_day = date(2026, 1, 9)
    prev_day = date(2026, 1, 8)
    day_map = {
        trade_day: _day_frame(trade_day, close=103.0, prev_close=100.0, face_val=10.0),
        prev_day: _day_frame(prev_day, close=200.0, prev_close=200.0, face_val=10.0),
    }

    monkeypatch.setattr(collector, "_fetch_bhavcopy_day", lambda d: day_map.get(d))
    monkeypatch.setattr(collector, "_get_db_previous_close", lambda symbol, trading_date: 200.0)

    actions = collector.detect_corporate_actions_for_day(trade_day, symbols={"ABC"})

    assert len(actions) == 1
    assert actions[0]["action_type"] == "bonus"
    assert actions[0]["adjustment_factor"] == 2.0


def test_no_false_positive_normal_day(monkeypatch):
    collector = MarketDataCollector()
    trade_day = date(2026, 1, 9)
    prev_day = date(2026, 1, 8)
    day_map = {
        trade_day: _day_frame(trade_day, close=100.2, prev_close=100.3, face_val=10.0),
        prev_day: _day_frame(prev_day, close=100.0, prev_close=100.0, face_val=10.0),
    }

    monkeypatch.setattr(collector, "_fetch_bhavcopy_day", lambda d: day_map.get(d))
    monkeypatch.setattr(collector, "_get_db_previous_close", lambda symbol, trading_date: 100.0)

    actions = collector.detect_corporate_actions_for_day(trade_day, symbols={"ABC"})
    assert actions == []


def test_backward_adjustment_applied(tmp_path):
    database = _make_db(tmp_path)
    collector = MarketDataCollector(database=database)
    _insert_prices(database, "ABC", [100.0, 120.0, 130.0])

    action = {
        "symbol": "ABC",
        "action_date": "2025-01-03",
        "action_type": "split",
        "adjustment_factor": 2.0,
        "face_val_before": 10.0,
        "face_val_after": 5.0,
    }
    summary = collector.apply_corporate_actions([action], dry_run=False)
    rows = _read_symbol_rows(database, "ABC")

    assert summary["applied"] == 1
    assert summary["rows_updated"] == 2
    assert list(rows["close"].round(2)) == [50.0, 60.0, 130.0]
    assert list(rows["volume"].astype(int)) == [2000, 2000, 1000]


def test_idempotency(tmp_path):
    database = _make_db(tmp_path)
    collector = MarketDataCollector(database=database)
    _insert_prices(database, "ABC", [100.0, 120.0, 130.0])

    action = {
        "symbol": "ABC",
        "action_date": "2025-01-03",
        "action_type": "split",
        "adjustment_factor": 2.0,
        "face_val_before": 10.0,
        "face_val_after": 5.0,
        "applied": 0,
    }
    database.upsert_corporate_actions([action])
    pending_once = database.list_corporate_actions(start_date="2025-01-01", end_date="2025-01-03", symbols=["ABC"], applied=0)
    summary_once = collector.apply_corporate_actions(pending_once, dry_run=False)
    pending_twice = database.list_corporate_actions(start_date="2025-01-01", end_date="2025-01-03", symbols=["ABC"], applied=0)
    summary_twice = collector.apply_corporate_actions(pending_twice, dry_run=False)
    rows = _read_symbol_rows(database, "ABC")

    assert summary_once["applied"] == 1
    assert summary_twice["applied"] == 0
    assert list(rows["close"].round(2)) == [50.0, 60.0, 130.0]


def test_cumulative_actions(tmp_path):
    database = _make_db(tmp_path)
    collector = MarketDataCollector(database=database)
    _insert_prices(database, "ABC", [300.0, 330.0, 360.0, 390.0])

    actions = [
        {
            "symbol": "ABC",
            "action_date": "2025-01-03",
            "action_type": "split",
            "adjustment_factor": 2.0,
            "face_val_before": 10.0,
            "face_val_after": 5.0,
        },
        {
            "symbol": "ABC",
            "action_date": "2025-01-04",
            "action_type": "bonus",
            "adjustment_factor": 1.5,
            "face_val_before": 5.0,
            "face_val_after": 5.0,
        },
    ]
    summary = collector.apply_corporate_actions(actions, dry_run=False)
    rows = _read_symbol_rows(database, "ABC")

    assert summary["applied"] == 2
    assert list(rows["close"].round(2)) == [100.0, 110.0, 240.0, 390.0]


def test_verify_no_overnight_jumps(tmp_path):
    database = _make_db(tmp_path)
    collector = MarketDataCollector(database=database)
    _insert_prices(database, "ABC", [100.0, 102.0, 101.5, 103.0], start="2025-02-01")

    warnings = collector.scan_overnight_jumps(
        start_date=date(2025, 2, 1),
        end_date=date(2025, 2, 4),
        symbols=["ABC"],
        threshold_pct=0.10,
    )
    assert warnings == []
