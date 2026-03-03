from __future__ import annotations

from datetime import datetime

import pandas as pd

from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.walk_forward import WalkForwardAnalysis
from trading_bot.strategies.base_strategy import BaseStrategy, Signal
from trading_bot.strategies.cross_sectional_momentum import CrossSectionalMomentumStrategy


def _build_market_data(
    *,
    start: str = "2024-01-01",
    periods: int = 360,
    symbols: int = 12,
) -> pd.DataFrame:
    dates = pd.date_range(start, periods=periods, freq="B")
    rows: list[dict] = []
    for s_idx in range(symbols):
        symbol = f"S{s_idx:02d}"
        base = 100.0 + (s_idx * 8.0)
        slope = 0.15 + (s_idx * 0.01)
        for i, dt in enumerate(dates):
            close = base + (i * slope)
            rows.append(
                {
                    "symbol": symbol,
                    "date": dt,
                    "open": close * 0.998,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 500_000 + (s_idx * 10_000),
                }
            )
    return pd.DataFrame(rows)


def _build_high_vol_market_data(
    *,
    start: str = "2024-01-01",
    end: str = "2025-12-31",
    symbols: int = 20,
) -> pd.DataFrame:
    dates = pd.bdate_range(start=start, end=end)
    rows: list[dict] = []
    for s_idx in range(symbols):
        symbol = f"HV{s_idx:02d}"
        price = 100.0 + s_idx
        for i, dt in enumerate(dates):
            daily_ret = 0.06 if i % 2 == 0 else -0.055
            price = max(1.0, price * (1.0 + daily_ret))
            rows.append(
                {
                    "symbol": symbol,
                    "date": dt,
                    "open": price * 0.995,
                    "high": price * 1.02,
                    "low": price * 0.98,
                    "close": price,
                    "volume": 400_000 + (s_idx * 5_000),
                }
            )
    return pd.DataFrame(rows)


def test_check_exit_rebalance_on_rebalance_day() -> None:
    strategy = CrossSectionalMomentumStrategy(top_n=2, trailing_stop_pct=0.15, log_signals=False)
    strategy._current_top_n = {"AAA", "BBB"}
    strategy._rebalance_active_date = "2025-10-31"

    position = {"symbol": "CCC", "highest_close": 120.0, "entry_price": 100.0}
    current = pd.Series({"date": pd.Timestamp("2025-10-31"), "close": 115.0})
    should_exit, reason = strategy.check_exit_conditions(position, current)
    assert should_exit is True
    assert reason == "REBALANCE_EXIT"


def test_check_exit_no_rebalance_on_non_rebalance_day() -> None:
    strategy = CrossSectionalMomentumStrategy(top_n=2, trailing_stop_pct=0.15, log_signals=False)
    strategy._current_top_n = {"AAA", "BBB"}
    strategy._rebalance_active_date = "2025-10-31"

    position = {"symbol": "CCC", "highest_close": 120.0, "entry_price": 100.0}
    current = pd.Series({"date": pd.Timestamp("2025-10-30"), "close": 115.0})
    should_exit, reason = strategy.check_exit_conditions(position, current)
    assert should_exit is False
    assert reason is None


def test_check_exit_stop_loss() -> None:
    strategy = CrossSectionalMomentumStrategy(top_n=2, trailing_stop_pct=0.15, log_signals=False)
    position = {"symbol": "AAA", "highest_close": 120.0, "entry_price": 100.0}
    current = pd.Series({"date": pd.Timestamp("2025-10-31"), "close": 100.0})
    should_exit, reason = strategy.check_exit_conditions(position, current)
    assert should_exit is True
    assert reason == "STOP_LOSS"


def test_reset_state_clears_all() -> None:
    strategy = CrossSectionalMomentumStrategy(top_n=2, log_signals=False)
    strategy._current_top_n = {"AAA"}
    strategy._ordered_top_n = ["AAA"]
    strategy._score_lookup = {"AAA": {"score": 1.0}}
    strategy._rebalance_pending = True
    strategy._rebalance_active_date = "2025-10-31"

    strategy.reset_state()

    assert strategy._current_top_n == set()
    assert strategy._ordered_top_n == []
    assert strategy._score_lookup == {}
    assert strategy._rebalance_pending is False
    assert strategy._rebalance_active_date is None


def test_compute_scores_handles_zero_vol() -> None:
    dates = pd.date_range("2025-01-01", periods=200, freq="B")
    rows: list[dict] = []
    for dt in dates:
        rows.append(
            {
                "symbol": "FLAT",
                "date": dt,
                "close": 100.0,
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "volume": 100_000,
            }
        )
        rows.append(
            {
                "symbol": "TREND",
                "date": dt,
                "close": 100.0 + ((dt - dates[0]).days * 0.05),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "volume": 100_000,
            }
        )
    frame = pd.DataFrame(rows)

    strategy = CrossSectionalMomentumStrategy(
        top_n=2,
        lookback_months=4,
        skip_recent_months=1,
        min_history_days=60,
        log_signals=False,
    )
    score_frame = strategy._compute_scores(frame, pd.Timestamp(frame["date"].max()))
    assert not score_frame.empty
    assert bool(score_frame["score"].map(pd.notna).all())
    assert bool(score_frame["score"].map(lambda x: x == x and abs(x) != float("inf")).all())


def test_compute_scores_winsorize_skipped_small_sample() -> None:
    frame = _build_market_data(periods=260, symbols=6)
    strategy = CrossSectionalMomentumStrategy(
        top_n=3,
        lookback_months=4,
        skip_recent_months=1,
        min_history_days=80,
        log_signals=False,
    )
    score_frame = strategy._compute_scores(frame, pd.Timestamp(frame["date"].max()))
    assert len(score_frame) <= 6
    # With small sample (<10), no winsorization clipping should alter the top score ordering.
    assert score_frame.iloc[0]["score"] >= score_frame.iloc[-1]["score"]


def test_crash_protection_reduces_top_n_in_high_vol() -> None:
    frame = _build_high_vol_market_data(symbols=20)
    strategy = CrossSectionalMomentumStrategy(
        top_n=15,
        lookback_months=6,
        skip_recent_months=1,
        min_history_days=140,
        crash_protection=True,
        target_vol=0.15,
        min_exposure=0.25,
        min_positions=5,
        vol_lookback_days=126,
        log_signals=False,
    )
    current_ts = pd.Timestamp(frame["date"].max())
    score_frame = strategy._compute_scores(frame, current_ts)
    selected = strategy._resolve_selected_count(score_frame, frame, current_ts)
    assert selected < strategy.top_n
    assert selected >= 5
    assert strategy._last_crash_scale < 1.0


def test_crash_protection_maintains_minimum_positions() -> None:
    frame = _build_high_vol_market_data(symbols=12)
    strategy = CrossSectionalMomentumStrategy(
        top_n=12,
        lookback_months=6,
        skip_recent_months=1,
        min_history_days=140,
        crash_protection=True,
        target_vol=0.10,
        min_exposure=0.10,
        min_positions=6,
        vol_lookback_days=126,
        log_signals=False,
    )
    current_ts = pd.Timestamp(frame["date"].max())
    score_frame = strategy._compute_scores(frame, current_ts)
    selected = strategy._resolve_selected_count(score_frame, frame, current_ts)
    assert selected >= 6
    assert selected <= strategy.top_n


def test_crash_protection_no_effect_in_low_vol() -> None:
    frame = _build_market_data(start="2024-01-01", periods=520, symbols=20)
    strategy = CrossSectionalMomentumStrategy(
        top_n=10,
        lookback_months=6,
        skip_recent_months=1,
        min_history_days=140,
        crash_protection=True,
        target_vol=0.15,
        min_exposure=0.25,
        min_positions=5,
        vol_lookback_days=126,
        log_signals=False,
    )
    current_ts = pd.Timestamp(frame["date"].max())
    score_frame = strategy._compute_scores(frame, current_ts)
    selected = strategy._resolve_selected_count(score_frame, frame, current_ts)
    assert selected == strategy.top_n
    assert abs(strategy._last_crash_scale - 1.0) < 1e-9


def test_crash_protection_off_by_default() -> None:
    frame = _build_market_data(start="2024-01-01", periods=520, symbols=20)
    strategy = CrossSectionalMomentumStrategy(
        top_n=10,
        lookback_months=6,
        skip_recent_months=1,
        min_history_days=140,
        log_signals=False,
    )
    current_ts = pd.Timestamp(frame["date"].max())
    score_frame = strategy._compute_scores(frame, current_ts)
    selected = strategy._resolve_selected_count(score_frame, frame, current_ts)
    assert selected == strategy.top_n
    assert abs(strategy._last_crash_scale - 1.0) < 1e-9


def test_portfolio_vol_computation_matches_expected() -> None:
    dates = pd.bdate_range("2025-01-01", periods=30)
    rows: list[dict] = []
    for symbol in ("AAA", "BBB"):
        price = 100.0
        for i, dt in enumerate(dates):
            daily_ret = 0.01 if i % 2 == 0 else -0.01
            price *= 1.0 + daily_ret
            rows.append(
                {
                    "symbol": symbol,
                    "date": dt,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 100_000,
                }
            )
    frame = pd.DataFrame(rows)
    strategy = CrossSectionalMomentumStrategy(
        top_n=2,
        crash_protection=True,
        vol_lookback_days=126,
        log_signals=False,
    )
    strategy._current_top_n = {"AAA", "BBB"}
    current_ts = pd.Timestamp(frame["date"].max())
    actual = strategy._compute_portfolio_vol(frame, current_ts)

    pivot = frame.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
    ew_returns = pivot.pct_change().mean(axis=1, skipna=True).dropna()
    expected = float(ew_returns.std(ddof=0) * (252.0 ** 0.5))
    assert abs(actual - expected) < 1e-9


def test_crash_protection_keeps_base_target_weight() -> None:
    frame = _build_high_vol_market_data(symbols=20)
    strategy = CrossSectionalMomentumStrategy(
        top_n=15,
        lookback_months=6,
        skip_recent_months=1,
        min_history_days=140,
        crash_protection=True,
        target_vol=0.10,
        min_exposure=0.25,
        min_positions=5,
        log_signals=False,
    )
    strategy.prepare_rebalance(frame, current_positions={})
    assert strategy._rebalance_active_date is not None
    assert strategy._last_selected_n < strategy.top_n

    signals = strategy.generate_signals(frame, current_positions={})
    assert signals
    assert len(signals) <= strategy._last_selected_n
    for signal in signals:
        assert signal.metadata is not None
        assert abs(float(signal.metadata["target_weight"]) - (1.0 / strategy.top_n)) < 1e-9


def test_generate_signals_rebalance_day_new_buys_and_target_weight() -> None:
    frame = _build_market_data(start="2025-01-01", periods=280, symbols=12)
    strategy = CrossSectionalMomentumStrategy(
        top_n=5,
        lookback_months=4,
        skip_recent_months=1,
        min_history_days=80,
        initial_capital=100000.0,
        log_signals=False,
    )
    latest_date = pd.Timestamp(frame["date"].max())
    # Ensure rebalance state is prepared for the same day as generate_signals call.
    strategy.prepare_rebalance(frame, current_positions={"S00": {"symbol": "S00"}})
    strategy._rebalance_active_date = str(latest_date.date())
    strategy._rebalance_pending = True
    strategy._ordered_top_n = ["S00", "S01", "S02", "S03", "S04"]
    strategy._current_top_n = set(strategy._ordered_top_n)

    signals = strategy.generate_signals(frame, current_positions={"S00": {"symbol": "S00"}})
    assert signals
    for signal in signals:
        assert signal.symbol != "S00"
        assert signal.metadata is not None
        assert abs(float(signal.metadata["target_weight"]) - 0.2) < 1e-9


class _ResetTrackingCSM(CrossSectionalMomentumStrategy):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.reset_calls = 0

    def reset_state(self) -> None:
        self.reset_calls += 1
        super().reset_state()


def test_walk_forward_no_state_leakage() -> None:
    frame = _build_market_data(start="2024-01-01", periods=360, symbols=10)
    strategy = _ResetTrackingCSM(
        top_n=4,
        lookback_months=3,
        skip_recent_months=1,
        min_history_days=60,
        log_signals=False,
    )
    wfa = WalkForwardAnalysis(train_period_months=2, test_period_months=2)
    results = wfa.run_walk_forward(
        strategy,
        frame,
        "2024-01-01",
        "2025-06-30",
        engine_kwargs={"sizing_mode": "equal_weight", "max_positions": 6},
        backtest_kwargs={"include_regime": False, "warmup_days": 200},
    )
    assert len(results["windows"]) > 0
    assert strategy.reset_calls == len(results["windows"])


class _EqualWeightSignalStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__("Equal Weight Test")

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict | None = None,
    ) -> list[Signal]:
        if market_data.empty:
            return []
        df = market_data[market_data["symbol"] == "AAA"].sort_values("date")
        if len(df) != 1:
            return []
        price = float(df.iloc[-1]["close"])
        return [
            Signal(
                symbol="AAA",
                action="BUY",
                price=price,
                quantity=0,
                stop_loss=price * 0.9,
                target=price * 1.2,
                strategy=self.name,
                confidence=0.7,
                timestamp=datetime.now(),
                metadata={"target_weight": 0.25},
            )
        ]

    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        return False, None


def test_equal_weight_position_sizing_uses_target_weight() -> None:
    dates = pd.date_range("2025-01-01", periods=2, freq="B")
    frame = pd.DataFrame(
        [
            {"symbol": "AAA", "date": dates[0], "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 100_000},
            {"symbol": "AAA", "date": dates[1], "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 100_000},
        ]
    )
    engine = BacktestEngine(initial_capital=100000, sizing_mode="equal_weight", max_positions=5)
    strategy = _EqualWeightSignalStrategy()
    result = engine.run_backtest(
        strategy,
        frame,
        "2025-01-01",
        "2025-01-02",
        include_regime=False,
        warmup_days=0,
    )
    trades = result.get("trades", [])
    assert trades
    # 25% target on 100k at price 100 -> ~250 shares before costs.
    assert int(trades[0]["quantity"]) >= 240
