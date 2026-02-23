from __future__ import annotations

from pathlib import Path

import main as main_module
from trading_bot.config.settings import Config
from trading_bot.data.storage.database import Database


def test_trading_bot_passes_adaptive_runtime_knobs(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "test_runtime_wiring.db"
    monkeypatch.setattr(Config, "DATABASE_URL", f"sqlite:///{db_path}", raising=False)
    test_db = Database()
    test_db.init_db()
    monkeypatch.setattr(main_module, "db", test_db)

    monkeypatch.setattr(Config, "ENABLE_MOMENTUM_BREAKOUT", False, raising=False)
    monkeypatch.setattr(Config, "ENABLE_MEAN_REVERSION", False, raising=False)
    monkeypatch.setattr(Config, "ENABLE_SECTOR_ROTATION", False, raising=False)
    monkeypatch.setattr(Config, "ENABLE_BEAR_REVERSAL", False, raising=False)
    monkeypatch.setattr(Config, "ENABLE_VOLATILITY_REVERSAL", False, raising=False)
    monkeypatch.setattr(Config, "ENABLE_ADAPTIVE_TREND", True, raising=False)

    monkeypatch.setattr(Config, "ADAPTIVE_TREND_TRAIL_TIER2_GAIN", 0.061, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_TREND_TRAIL_TIER2_MULT", 1.07, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_TREND_TRAIL_TIER3_GAIN", 0.111, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_TREND_TRAIL_TIER3_MULT", 1.23, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_TREND_MAX_WEEKLY_ATR_PCT", 0.072, raising=False)
    monkeypatch.setattr(Config, "TOTAL_COST_PER_TRADE", 0.0042, raising=False)

    monkeypatch.setattr(main_module.MarketDataCollector, "get_nifty_500_list", lambda self: ["TEST.NS"])
    monkeypatch.setattr(main_module.MarketDataCollector, "filter_liquid_stocks", lambda self, symbols: symbols)
    monkeypatch.setattr(main_module.AlternativeDataScraper, "scrape_moneycontrol_trending", lambda self: [])
    monkeypatch.setattr(main_module.AlternativeDataScraper, "scrape_sector_performance", lambda self: [])
    monkeypatch.setattr(main_module.AlternativeDataScraper, "save_to_db", lambda self, rows: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_alert", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_trade_notification", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_morning_report", lambda *args, **kwargs: None)

    captured: dict[str, float] = {}

    class DummyAdaptiveTrend:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(main_module, "AdaptiveTrendFollowingStrategy", DummyAdaptiveTrend)

    bot = main_module.TradingBot(paper_mode=True)
    assert "adaptive_trend" in bot.strategies
    assert captured["trail_tier2_gain"] == 0.061
    assert captured["trail_tier2_mult"] == 1.07
    assert captured["trail_tier3_gain"] == 0.111
    assert captured["trail_tier3_mult"] == 1.23
    assert captured["max_weekly_atr_pct"] == 0.072
    assert captured["transaction_cost_pct"] == 0.0042
