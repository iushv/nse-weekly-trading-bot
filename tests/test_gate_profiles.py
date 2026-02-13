from __future__ import annotations

from trading_bot.config.settings import Config
from trading_bot.monitoring.gate_profiles import (
    build_audit_thresholds,
    required_paper_weeks,
    resolve_go_live_profile,
)


def test_resolve_go_live_profile_auto_baseline_when_mixed(monkeypatch):
    monkeypatch.setattr(Config, "GO_LIVE_PROFILE", "auto", raising=False)
    monkeypatch.setattr(Config, "ENABLE_ADAPTIVE_TREND", True, raising=False)
    monkeypatch.setattr(Config, "ENABLE_MOMENTUM_BREAKOUT", True, raising=False)
    monkeypatch.setattr(Config, "ENABLE_MEAN_REVERSION", False, raising=False)
    monkeypatch.setattr(Config, "ENABLE_SECTOR_ROTATION", False, raising=False)
    monkeypatch.setattr(Config, "ENABLE_BEAR_REVERSAL", False, raising=False)
    monkeypatch.setattr(Config, "ENABLE_VOLATILITY_REVERSAL", False, raising=False)
    assert resolve_go_live_profile() == "baseline"


def test_resolve_go_live_profile_auto_adaptive_when_only_adaptive(monkeypatch):
    monkeypatch.setattr(Config, "GO_LIVE_PROFILE", "auto", raising=False)
    monkeypatch.setattr(Config, "ENABLE_ADAPTIVE_TREND", True, raising=False)
    monkeypatch.setattr(Config, "ENABLE_MOMENTUM_BREAKOUT", False, raising=False)
    monkeypatch.setattr(Config, "ENABLE_MEAN_REVERSION", False, raising=False)
    monkeypatch.setattr(Config, "ENABLE_SECTOR_ROTATION", False, raising=False)
    monkeypatch.setattr(Config, "ENABLE_BEAR_REVERSAL", False, raising=False)
    monkeypatch.setattr(Config, "ENABLE_VOLATILITY_REVERSAL", False, raising=False)
    assert resolve_go_live_profile() == "adaptive"


def test_build_audit_thresholds_uses_adaptive_values(monkeypatch):
    monkeypatch.setattr(Config, "ADAPTIVE_GO_LIVE_MIN_SHARPE", 0.7, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_GO_LIVE_MAX_DRAWDOWN", 0.15, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_GO_LIVE_MIN_WIN_RATE", 0.3, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_GO_LIVE_MIN_PROFIT_FACTOR", 1.2, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_GO_LIVE_MIN_CLOSED_TRADES", 3, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_GO_LIVE_MAX_CRITICAL_ERRORS", 0, raising=False)
    monkeypatch.setattr(Config, "ADAPTIVE_GO_LIVE_CRITICAL_WINDOW_DAYS", 14, raising=False)

    thresholds = build_audit_thresholds("adaptive")
    assert thresholds.min_sharpe == 0.7
    assert thresholds.max_drawdown == 0.15
    assert thresholds.min_win_rate == 0.3
    assert thresholds.min_profit_factor == 1.2
    assert thresholds.min_closed_trades == 3
    assert thresholds.max_critical_errors == 0
    assert thresholds.critical_window_days == 14


def test_required_paper_weeks_for_adaptive(monkeypatch):
    monkeypatch.setattr(Config, "ADAPTIVE_PAPER_RUN_REQUIRED_WEEKS", 6, raising=False)
    monkeypatch.setattr(Config, "PAPER_RUN_REQUIRED_WEEKS", 4, raising=False)
    assert required_paper_weeks("adaptive") == 6
    assert required_paper_weeks("baseline") == 4
