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


def test_regime_gate_blocks_unfavorable_market():
    strategy = AdaptiveTrendFollowingStrategy()
    market_data = _build_market_data(["AAA"])

    signals = strategy.generate_signals(
        market_data=market_data,
        market_regime={
            "breadth_ratio": 0.25,
            "annualized_volatility": 0.35,
            "trend_up": False,
        },
    )
    assert signals == []


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
    monkeypatch.setattr(strategy, "_trend_consistency_ratio", lambda _weekly: 0.55)

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
        market_regime={"is_favorable": True, "confidence": 0.5, "breadth_ratio": 0.5, "annualized_volatility": 0.45},
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
        {"confidence": 0.54, "breadth_ratio": 0.50, "annualized_volatility": 0.51}
    )
    assert strategy._entry_conditions(
        daily,
        weekly,
        min_weekly_roc=min_roc,
        min_ema_spread_pct=min_spread,
        min_volume_ratio=min_vol,
    ) is False


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
