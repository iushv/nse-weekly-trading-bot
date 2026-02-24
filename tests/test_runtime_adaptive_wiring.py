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
    monkeypatch.setattr(Config, "ADAPTIVE_TREND_DYNAMIC_STOP_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_TREND_DYNAMIC_STOP_HIGH_ATR_PCT", 0.081, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_TREND_DYNAMIC_STOP_LOW_ATR_PCT", 0.039, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_TREND_DYNAMIC_STOP_HIGH_VOL_SCALE", 0.83, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_TREND_DYNAMIC_STOP_LOW_VOL_SCALE", 1.14, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_TREND_DYNAMIC_STOP_MIN_MULT", 1.05, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_TREND_DYNAMIC_STOP_MAX_MULT", 1.95, raising=False)
    monkeypatch.setattr(Config, "TOTAL_COST_PER_TRADE", 0.0042, raising=False)

    monkeypatch.setattr(main_module.MarketDataCollector, "get_nifty_500_list", lambda self: ["TEST.NS"])
    monkeypatch.setattr(main_module.MarketDataCollector, "filter_liquid_stocks", lambda self, symbols: symbols)
    monkeypatch.setattr(main_module.AlternativeDataScraper, "scrape_moneycontrol_trending", lambda self: [])
    monkeypatch.setattr(main_module.AlternativeDataScraper, "scrape_sector_performance", lambda self: [])
    monkeypatch.setattr(main_module.AlternativeDataScraper, "save_to_db", lambda self, rows: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_alert", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_trade_notification", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.TelegramReporter, "send_morning_report", lambda *args, **kwargs: None)

    bot = main_module.TradingBot(paper_mode=True)
    assert "adaptive_trend" in bot.strategies
    strategy = bot.strategies["adaptive_trend"]
    assert float(getattr(strategy, "trail_tier2_gain", 0.0)) == 0.061
    assert float(getattr(strategy, "trail_tier2_mult", 0.0)) == 1.07
    assert float(getattr(strategy, "trail_tier3_gain", 0.0)) == 0.111
    assert float(getattr(strategy, "trail_tier3_mult", 0.0)) == 1.23
    assert float(getattr(strategy, "max_weekly_atr_pct", 0.0)) == 0.072
    assert bool(getattr(strategy, "dynamic_stop_enabled", False)) is True
    assert float(getattr(strategy, "dynamic_stop_high_atr_pct", 0.0)) == 0.081
    assert float(getattr(strategy, "dynamic_stop_low_atr_pct", 0.0)) == 0.039
    assert float(getattr(strategy, "dynamic_stop_high_vol_scale", 0.0)) == 0.83
    assert float(getattr(strategy, "dynamic_stop_low_vol_scale", 0.0)) == 1.14
    assert float(getattr(strategy, "dynamic_stop_min_mult", 0.0)) == 1.05
    assert float(getattr(strategy, "dynamic_stop_max_mult", 0.0)) == 1.95
    assert float(getattr(strategy, "transaction_cost_pct", 0.0)) == 0.0042
