from __future__ import annotations

from datetime import datetime

import pandas as pd

from trading_bot.strategies.adaptive_trend import AdaptiveTrendFollowingStrategy


def _build_market_data(symbols: list[str], periods: int = 180) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=periods, freq="B")
    rows: list[dict] = []
    for sym_idx, symbol in enumerate(symbols):
        base = 100.0 + (sym_idx * 15.0)
        for i, dt in enumerate(dates):
            close = base + (i * 0.35)
            rows.append(
                {
                    "symbol": symbol,
                    "date": dt,
                    "open": close * 0.997,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1_000_000 + (i * 1_000),
                }
            )
    return pd.DataFrame(rows)


def test_unfavorable_regime_does_not_hard_block_entries(monkeypatch):
    strategy = AdaptiveTrendFollowingStrategy(max_new_per_week=1)
    market_data = _build_market_data(["AAA"])
    monkeypatch.setattr(strategy, "_entry_conditions", lambda _daily, _weekly, **_kwargs: True)
    monkeypatch.setattr(strategy, "_estimate_expected_r_multiple", lambda _price, _weekly: 1.5)

    signals = strategy.generate_signals(
        market_data=market_data,
        market_regime={
            "is_favorable": False,
            "breadth_ratio": 0.25,
            "annualized_volatility": 0.35,
            "trend_up": False,
        },
    )
    assert len(signals) == 1
    assert strategy.last_scan_stats["reason"] == "scan_complete"
    assert strategy.last_scan_stats["blocked_by_regime"] is False


def test_generate_signals_respects_weekly_cap(monkeypatch):
    strategy = AdaptiveTrendFollowingStrategy(max_new_per_week=1)
    market_data = _build_market_data(["AAA", "BBB", "CCC"])

    monkeypatch.setattr(strategy, "_entry_conditions", lambda _daily, _weekly, **_kwargs: True)
    monkeypatch.setattr(strategy, "_estimate_expected_r_multiple", lambda _price, _weekly: 1.5)
    signals = strategy.generate_signals(
        market_data=market_data,
        market_regime={"breadth_ratio": 0.7, "annualized_volatility": 0.2, "trend_up": True},
    )
    assert len(signals) == 1
    assert signals[0].strategy == "Adaptive Trend"
    assert float(signals[0].metadata["weekly_atr"]) > 0


def test_generate_signals_selects_top_confidence_before_cap(monkeypatch):
    strategy = AdaptiveTrendFollowingStrategy(max_new_per_week=2)
    market_data = _build_market_data(["AAA", "BBB", "CCC"])

    confidence_values = iter([0.15, 0.95, 0.55])
    monkeypatch.setattr(strategy, "_entry_conditions", lambda _daily, _weekly, **_kwargs: True)
    monkeypatch.setattr(strategy, "_estimate_expected_r_multiple", lambda _price, _weekly: 1.5)
    monkeypatch.setattr(strategy, "_confidence", lambda _daily, _weekly: float(next(confidence_values)))

    signals = strategy.generate_signals(
        market_data=market_data,
        market_regime={"is_favorable": True},
    )

    assert [signal.symbol for signal in signals] == ["BBB", "CCC"]
    assert [signal.confidence for signal in signals] == [0.95, 0.55]


def test_generate_signals_filters_low_expected_r_multiple(monkeypatch):
    strategy = AdaptiveTrendFollowingStrategy(max_new_per_week=3, min_expected_r_mult=1.0)
    market_data = _build_market_data(["AAA", "BBB", "CCC"])

    expected_r_values = iter([0.7, 1.25, 0.95])
    monkeypatch.setattr(strategy, "_entry_conditions", lambda _daily, _weekly, **_kwargs: True)
    monkeypatch.setattr(strategy, "_estimate_expected_r_multiple", lambda _price, _weekly: float(next(expected_r_values)))
    monkeypatch.setattr(strategy, "_confidence", lambda _daily, _weekly: 0.8)

    signals = strategy.generate_signals(
        market_data=market_data,
        market_regime={"is_favorable": True, "confidence": 0.9, "breadth_ratio": 0.7, "annualized_volatility": 0.2},
    )
    assert [s.symbol for s in signals] == ["BBB"]
    assert signals[0].metadata["expected_r_multiple"] == 1.25
    assert signals[0].metadata["expected_r_floor"] == 1.0


def test_generate_signals_filters_on_low_trend_consistency(monkeypatch):
    strategy = AdaptiveTrendFollowingStrategy(max_new_per_week=3, min_trend_consistency=0.75)
    market_data = _build_market_data(["AAA", "BBB", "CCC"])
    monkeypatch.setattr(strategy, "_entry_conditions", lambda _daily, _weekly, **_kwargs: True)
    monkeypatch.setattr(strategy, "_estimate_expected_r_multiple", lambda _price, _weekly: 1.4)
    monkeypatch.setattr(strategy, "_trend_consistency_ratio", lambda _weekly: 0.5)

    signals = strategy.generate_signals(
        market_data=market_data,
        market_regime={"is_favorable": True},
    )
    assert signals == []


def test_trend_consistency_floor_tightens_in_weak_regime(monkeypatch):
    strategy = AdaptiveTrendFollowingStrategy(max_new_per_week=3, min_trend_consistency=0.50)
    market_data = _build_market_data(["AAA", "BBB", "CCC"])
    monkeypatch.setattr(strategy, "_entry_conditions", lambda _daily, _weekly, **_kwargs: True)
    monkeypatch.setattr(strategy, "_estimate_expected_r_multiple", lambda _price, _weekly: 1.5)
    monkeypatch.setattr(strategy, "_trend_consistency_ratio", lambda _weekly: 0.54)

    favorable = strategy.generate_signals(
        market_data=market_data,
        market_regime={"is_favorable": True, "confidence": 0.9, "breadth_ratio": 0.7, "annualized_volatility": 0.2},
    )
    weak = strategy.generate_signals(
        market_data=market_data,
        market_regime={"is_favorable": True, "confidence": 0.5, "breadth_ratio": 0.5, "annualized_volatility": 0.45},
    )
    assert len(favorable) == 3
    assert weak == []


def test_expected_r_floor_tightens_with_regime_steps(monkeypatch):
    strategy = AdaptiveTrendFollowingStrategy(max_new_per_week=3, min_expected_r_mult=1.0)
    market_data = _build_market_data(["AAA", "BBB", "CCC"])

    monkeypatch.setattr(strategy, "_entry_conditions", lambda _daily, _weekly, **_kwargs: True)
    monkeypatch.setattr(strategy, "_estimate_expected_r_multiple", lambda _price, _weekly: 1.2)
    monkeypatch.setattr(strategy, "_confidence", lambda _daily, _weekly: 0.8)

    favorable = strategy.generate_signals(
        market_data=market_data,
        market_regime={"is_favorable": True, "confidence": 0.9, "breadth_ratio": 0.7, "annualized_volatility": 0.2},
    )
    weak = strategy.generate_signals(
        market_data=market_data,
        market_regime={"is_favorable": True, "confidence": 0.4, "breadth_ratio": 0.45, "annualized_volatility": 0.65},
    )
    assert len(favorable) == 3
    assert weak == []


def test_entry_conditions_require_min_weekly_ema_spread():
    strategy = AdaptiveTrendFollowingStrategy(min_weekly_ema_spread_pct=0.005)
    daily = pd.Series({"close": 101.0, "SMA_20": 100.0, "RSI_14": 55.0})
    weekly = pd.Series(
        {
            "close": 100.0,
            "EMA_S": 100.2,
            "EMA_L": 100.0,
            "ROC_4": 0.05,
            "RSI": 55.0,
            "ATR": 2.0,
            "VOL_RATIO": 1.0,
        }
    )

    assert strategy._entry_conditions(daily, weekly) is False


def test_regime_conditional_thresholds_tighten_when_confidence_low():
    strategy = AdaptiveTrendFollowingStrategy(min_weekly_roc=0.03, min_weekly_ema_spread_pct=0.005)
    base = strategy._entry_thresholds_for_regime({"confidence": 0.9, "breadth_ratio": 0.7, "annualized_volatility": 0.2})
    tight = strategy._entry_thresholds_for_regime({"confidence": 0.5, "breadth_ratio": 0.5, "annualized_volatility": 0.45})

    assert tight[0] > base[0]
    assert tight[1] > base[1]
    assert tight[2] > base[2]


def test_entry_conditions_can_fail_with_regime_tightened_thresholds():
    strategy = AdaptiveTrendFollowingStrategy(min_weekly_roc=0.03, min_weekly_ema_spread_pct=0.005)
    daily = pd.Series({"close": 101.0, "SMA_20": 100.0, "RSI_14": 55.0})
    weekly = pd.Series(
        {
            "close": 101.0,
            "EMA_S": 100.55,
            "EMA_L": 100.0,
            "ROC_4": 0.033,
            "RSI": 55.0,
            "ATR": 2.0,
            "VOL_RATIO": 0.86,
        }
    )
    assert strategy._entry_conditions(daily, weekly) is True

    min_roc, min_spread, min_vol = strategy._entry_thresholds_for_regime(
        {"confidence": 0.45, "breadth_ratio": 0.50, "annualized_volatility": 0.51}
    )
    assert strategy._entry_conditions(
        daily,
        weekly,
        min_weekly_roc=min_roc,
        min_ema_spread_pct=min_spread,
        min_volume_ratio=min_vol,
    ) is False


def test_entry_conditions_use_configurable_daily_rsi_band():
    strategy = AdaptiveTrendFollowingStrategy(daily_rsi_min=40.0, daily_rsi_max=72.0)
    daily = pd.Series({"close": 101.0, "SMA_20": 100.0, "RSI_14": 42.0})
    weekly = pd.Series(
        {
            "close": 101.0,
            "EMA_S": 100.6,
            "EMA_L": 100.0,
            "ROC_4": 0.04,
            "RSI": 55.0,
            "ATR": 2.0,
            "VOL_RATIO": 1.0,
        }
    )
    assert strategy._entry_conditions(daily, weekly) is True

    stricter = AdaptiveTrendFollowingStrategy(daily_rsi_min=45.0, daily_rsi_max=70.0)
    assert stricter._entry_conditions(daily, weekly) is False


def test_scan_stats_capture_entry_reasons(monkeypatch):
    strategy = AdaptiveTrendFollowingStrategy(max_new_per_week=3)
    market_data = _build_market_data(["AAA"])

    monkeypatch.setattr(strategy, "_trend_consistency_ratio", lambda _weekly: 1.0)
    monkeypatch.setattr(strategy, "_estimate_expected_r_multiple", lambda _price, _weekly: 1.5)

    def _fail_entry(_daily, _weekly, **kwargs):
        failure_reasons = kwargs.get("failure_reasons")
        if isinstance(failure_reasons, list):
            failure_reasons.clear()
            failure_reasons.extend(["volume_ratio", "daily_rsi_band"])
        return False

    monkeypatch.setattr(strategy, "_entry_conditions", _fail_entry)

    signals = strategy.generate_signals(
        market_data=market_data,
        market_regime={"is_favorable": True},
    )

    assert signals == []
    assert strategy.last_scan_stats["reason"] == "scan_complete"
    assert strategy.last_scan_stats["entry_reasons"]["volume_ratio"] == 1
    assert strategy.last_scan_stats["entry_reasons"]["daily_rsi_band"] == 1


def test_trailing_stop_exit_when_profit_protected():
    strategy = AdaptiveTrendFollowingStrategy()
    should_exit, reason = strategy.check_exit_conditions(
        {
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "target": 130.0,
            "days_held": 8,
            "highest_close": 120.0,
            "weekly_atr": 5.0,
        },
        pd.Series({"close": 112.0}),
    )
    assert should_exit is True
    assert reason == "TRAILING_STOP"


def test_breakeven_stop_triggers():
    strategy = AdaptiveTrendFollowingStrategy()
    should_exit, reason = strategy.check_exit_conditions(
        {
            "entry_price": 100.0,
            "stop_loss": 92.0,
            "target": 130.0,
            "days_held": 7,
            "highest_close": 104.0,
            "weekly_atr": 2.0,
            "metadata": {"weekly_ema_short": 105.0, "weekly_ema_long": 100.0},
            "current_weekly_ema_short": 106.0,
            "current_weekly_ema_long": 101.0,
        },
        pd.Series({"close": 100.4}),
    )
    assert should_exit is True
    assert reason == "BREAKEVEN_STOP"


def test_progressive_trail_at_3pct_gain():
    strategy = AdaptiveTrendFollowingStrategy(breakeven_gain_pct=0.2)
    should_exit, reason = strategy.check_exit_conditions(
        {
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "target": 130.0,
            "days_held": 7,
            "highest_close": 103.0,
            "weekly_atr": 2.0,
            "metadata": {"weekly_ema_short": 105.0, "weekly_ema_long": 100.0},
            "current_weekly_ema_short": 106.0,
            "current_weekly_ema_long": 101.0,
        },
        pd.Series({"close": 100.5}),
    )
    assert should_exit is True
    assert reason == "TRAILING_STOP"


def test_progressive_trail_at_5pct_gain():
    strategy = AdaptiveTrendFollowingStrategy(breakeven_gain_pct=0.2)
    should_exit, reason = strategy.check_exit_conditions(
        {
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "target": 130.0,
            "days_held": 7,
            "highest_close": 105.0,
            "weekly_atr": 2.0,
            "metadata": {"weekly_ema_short": 105.0, "weekly_ema_long": 100.0},
            "current_weekly_ema_short": 106.0,
            "current_weekly_ema_long": 101.0,
        },
        pd.Series({"close": 102.9}),
    )
    assert should_exit is True
    assert reason == "TRAILING_STOP"


def test_progressive_trail_uses_configurable_tiers():
    strategy = AdaptiveTrendFollowingStrategy(
        profit_trail_atr_mult=0.7,
        profit_protect_pct=0.04,
        trail_tier2_gain=0.06,
        trail_tier2_mult=1.1,
        trail_tier3_gain=0.10,
        trail_tier3_mult=1.3,
    )
    assert strategy._progressive_trail_mult(0.11) == 0.7
    assert strategy._progressive_trail_mult(0.07) == 1.1
    assert strategy._progressive_trail_mult(0.05) == 1.3
    assert strategy._progressive_trail_mult(0.02) == strategy.stop_atr_mult


def test_trend_break_exit():
    strategy = AdaptiveTrendFollowingStrategy()
    should_exit, reason = strategy.check_exit_conditions(
        {
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "target": 130.0,
            "days_held": 8,
            "highest_close": 106.0,
            "weekly_atr": 2.0,
            "metadata": {"weekly_ema_short": 105.0, "weekly_ema_long": 100.0},
            "current_weekly_ema_short": 99.0,
            "current_weekly_ema_long": 101.0,
        },
        pd.Series({"close": 104.0}),
    )
    assert should_exit is True
    assert reason == "TREND_BREAK"


def test_time_stop_for_low_progress_trade():
    strategy = AdaptiveTrendFollowingStrategy(time_stop_days=30)
    should_exit, reason = strategy.check_exit_conditions(
        {
            "entry_price": 100.0,
            "stop_loss": 90.0,
            "target": 130.0,
            "days_held": 31,
            "highest_close": 102.0,
            "weekly_atr": 2.0,
        },
        pd.Series({"close": 101.0}),
    )
    assert should_exit is True
    assert reason == "TIME_STOP"


def test_stop_loss_exit_takes_priority():
    strategy = AdaptiveTrendFollowingStrategy()
    should_exit, reason = strategy.check_exit_conditions(
        {
            "entry_price": 100.0,
            "stop_loss": 97.0,
            "target": 130.0,
            "days_held": 1,
            "highest_close": 101.0,
            "weekly_atr": 1.5,
        },
        pd.Series({"close": 96.0}),
    )
    assert should_exit is True
    assert reason == "STOP_LOSS"



def test_signal_timestamp_is_recent(monkeypatch):
    strategy = AdaptiveTrendFollowingStrategy(max_new_per_week=1)
    market_data = _build_market_data(["AAA"])
    monkeypatch.setattr(strategy, "_entry_conditions", lambda _daily, _weekly, **_kwargs: True)
    monkeypatch.setattr(strategy, "_estimate_expected_r_multiple", lambda _price, _weekly: 1.5)
    signal = strategy.generate_signals(
        market_data=market_data,
        market_regime={"breadth_ratio": 0.8, "annualized_volatility": 0.15, "trend_up": True},
    )[0]
    assert abs((datetime.now() - signal.timestamp).total_seconds()) < 5


def test_high_atr_pct_entry_rejected(monkeypatch):
    """ATR-cap filter rejects entries where weekly_atr / price > max_weekly_atr_pct."""
    strategy = AdaptiveTrendFollowingStrategy(max_new_per_week=3, max_weekly_atr_pct=0.05)
    market_data = _build_market_data(["AAA"])
    monkeypatch.setattr(strategy, "_entry_conditions", lambda _daily, _weekly, **_kwargs: True)
    monkeypatch.setattr(strategy, "_estimate_expected_r_multiple", lambda _price, _weekly: 1.5)

    # Patch _build_weekly_indicators to return data with ATR/close > 0.05
    original_build_weekly = strategy._build_weekly_indicators

    def _high_atr_weekly(frame):
        weekly = original_build_weekly(frame)
        if not weekly.empty:
            weekly["ATR"] = weekly["close"] * 0.08  # 8% ATR - above the 5% cap
        return weekly

    monkeypatch.setattr(strategy, "_build_weekly_indicators", _high_atr_weekly)

    signals = strategy.generate_signals(
        market_data=market_data,
        market_regime={"is_favorable": True},
    )
    assert signals == []
    assert strategy.last_scan_stats["high_atr_pct"] == 1


def test_breakeven_floor_includes_transaction_cost():
    """Breakeven floor includes transaction cost so near-breakeven trades aren't net-negative."""
    strategy = AdaptiveTrendFollowingStrategy(
        breakeven_gain_pct=0.03,
        breakeven_buffer_pct=0.005,
        transaction_cost_pct=0.004,
    )
    position = {
        "entry_price": 100.0,
        "stop_loss": 92.0,
        "target": 130.0,
        "days_held": 7,
        "highest_close": 104.0,  # gain_pct = 4% > 3% breakeven_gain_pct
        "weekly_atr": 0.5,
        "metadata": {"weekly_ema_short": 105.0, "weekly_ema_long": 100.0},
        "current_weekly_ema_short": 106.0,
        "current_weekly_ema_long": 101.0,
    }

    # close=100.85 is above old floor (100.50) but below new floor (100.90)
    # Should trigger breakeven because 100.85 <= 100 * (1 + 0.005 + 0.004) = 100.90
    should_exit, reason = strategy.check_exit_conditions(position, pd.Series({"close": 100.85}))
    assert should_exit is True
    assert reason == "BREAKEVEN_STOP"

    # With weekly_atr=0.5:
    # gain_pct = 0.04 >= profit_protect_pct (0.03) -> trail_mult = 1.2
    # trailing_stop = 104 - (1.2 * 0.5) = 104 - 0.6 = 103.4
    # Wait, 103.4 is still > 100.95. I need a much smaller ATR or different trail config.
    # If trail_mult = 1.5 (gain < 3%): TS = 104 - 1.5*0.5 = 103.25.
    # Let's set weekly_atr to 10.0 so trailing_stop is 104 - 1.2*10 = 92.0.
    # Then 100.95 > 92.0 - no trailing stop.
    position["weekly_atr"] = 10.0

    # close=100.95 is above the new breakeven floor (100.90) - should NOT trigger
    should_exit2, reason2 = strategy.check_exit_conditions(position, pd.Series({"close": 100.95}))
    assert should_exit2 is False
    assert reason2 is None


def test_dynamic_entry_stop_mult_scales_with_atr_pct():
    strategy = AdaptiveTrendFollowingStrategy(
        stop_atr_mult=1.5,
        dynamic_stop_enabled=True,
        dynamic_stop_low_atr_pct=0.04,
        dynamic_stop_high_atr_pct=0.08,
        dynamic_stop_low_vol_scale=1.10,
        dynamic_stop_high_vol_scale=0.80,
        dynamic_stop_min_mult=1.0,
        dynamic_stop_max_mult=2.0,
    )

    low_vol_mult = strategy._entry_stop_atr_mult(entry_price=100.0, weekly_atr=3.0)
    mid_vol_mult = strategy._entry_stop_atr_mult(entry_price=100.0, weekly_atr=6.0)
    high_vol_mult = strategy._entry_stop_atr_mult(entry_price=100.0, weekly_atr=10.0)

    assert low_vol_mult > mid_vol_mult > high_vol_mult
    assert high_vol_mult >= 1.0
    assert low_vol_mult <= 2.0


def test_generate_signals_includes_dynamic_stop_metadata(monkeypatch):
    strategy = AdaptiveTrendFollowingStrategy(
        max_new_per_week=1,
        dynamic_stop_enabled=True,
        stop_atr_mult=1.5,
    )
    market_data = _build_market_data(["AAA"])
    monkeypatch.setattr(strategy, "_entry_conditions", lambda _daily, _weekly, **_kwargs: True)
    monkeypatch.setattr(strategy, "_estimate_expected_r_multiple", lambda _price, _weekly, **_kwargs: 1.5)

    signals = strategy.generate_signals(
        market_data=market_data,
        market_regime={"is_favorable": True},
    )
    assert len(signals) == 1
    metadata = signals[0].metadata
    assert "stop_atr_mult_used" in metadata
    assert "weekly_atr_pct" in metadata
    assert float(metadata["stop_atr_mult_used"]) > 0
    assert float(metadata["weekly_atr_pct"]) > 0

