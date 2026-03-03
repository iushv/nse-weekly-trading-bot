from __future__ import annotations

from datetime import datetime

import pandas as pd

from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.walk_forward import WalkForwardAnalysis
from trading_bot.config.settings import Config
from trading_bot.data.processors.regime import compute_market_regime
from trading_bot.risk.position_sizer import size_position
from trading_bot.strategies.base_strategy import BaseStrategy, Signal


class DeterministicTrendStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__("Deterministic Trend")

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict | None = None,
    ) -> list[Signal]:
        signals: list[Signal] = []
        if market_data.empty:
            return signals

        for symbol in market_data["symbol"].dropna().unique():
            df = market_data[market_data["symbol"] == symbol].sort_values("date")
            if len(df) < 6:
                continue
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            if float(latest["close"]) > float(prev["close"]):
                price = float(latest["close"])
                signals.append(
                    Signal(
                        symbol=symbol,
                        action="BUY",
                        price=price,
                        quantity=0,
                        stop_loss=price * 0.98,
                        target=price * 1.02,
                        strategy=self.name,
                        confidence=0.8,
                        timestamp=datetime.now(),
                    )
                )
        return signals

    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        current_price = float(current_data["close"])
        if current_price <= float(position["stop_loss"]):
            return True, "STOP_LOSS"
        if current_price >= float(position["target"]):
            return True, "TARGET_HIT"
        if int(position.get("days_held", 0)) >= 3:
            return True, "TIME_STOP"
        return False, None


def _build_market_data(periods: int = 280) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=periods, freq="B")
    rows: list[dict] = []
    symbols = ["AAA", "BBB"]

    for sym_idx, symbol in enumerate(symbols):
        base = 100 + sym_idx * 15
        for i, dt in enumerate(dates):
            close = base + (i * 0.25) + (0.05 if i % 2 == 0 else -0.03)
            rows.append(
                {
                    "symbol": symbol,
                    "date": dt,
                    "open": close * 0.997,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1_000_000 + (i * 1000),
                }
            )
    return pd.DataFrame(rows)


def _build_bearish_market_data(periods: int = 140, symbols: int = 25) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=periods, freq="B")
    rows: list[dict] = []
    tickers = [f"S{i:02d}" for i in range(symbols)]

    for sym_idx, symbol in enumerate(tickers):
        base = 300.0 + (sym_idx * 8.0)
        for i, dt in enumerate(dates):
            close = base - (i * (0.35 + (sym_idx * 0.002)))
            close = max(close, 5.0)
            rows.append(
                {
                    "symbol": symbol,
                    "date": dt,
                    "open": close * 1.001,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 900_000 + (sym_idx * 1_000),
                }
            )
    return pd.DataFrame(rows)


class RegimeSensitiveStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__("Regime Sensitive")

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict | None = None,
    ) -> list[Signal]:
        if market_data.empty:
            return []
        if market_regime is not None and not bool(market_regime.get("is_favorable", True)):
            return []

        symbols = sorted(str(x) for x in market_data["symbol"].dropna().unique())
        if not symbols:
            return []
        df = market_data[market_data["symbol"] == symbols[0]].sort_values("date")
        if len(df) < 2:
            return []
        price = float(df.iloc[-1]["close"])
        return [
            Signal(
                symbol=symbols[0],
                action="BUY",
                price=price,
                quantity=0,
                stop_loss=price * 0.99,
                target=price * 1.01,
                strategy=self.name,
                confidence=0.8,
                timestamp=datetime.now(),
            )
        ]

    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        if int(position.get("days_held", 0)) >= 1:
            return True, "TIME_STOP"
        return False, None


class OneShotEntryStopStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__("One Shot Entry Stop")

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
                stop_loss=price * 0.90,
                target=price * 1.05,
                strategy=self.name,
                confidence=0.9,
                timestamp=datetime.now(),
            )
        ]

    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        if float(current_data["close"]) <= float(position["stop_loss"]):
            return True, "STOP_LOSS"
        return False, None


class JumpDayEntryStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__("Jump Day Entry")

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict | None = None,
    ) -> list[Signal]:
        if market_data.empty:
            return []
        df = market_data[market_data["symbol"] == "AAA"].sort_values("date")
        if len(df) != 2:
            return []
        price = float(df.iloc[-1]["close"])
        return [
            Signal(
                symbol="AAA",
                action="BUY",
                price=price,
                quantity=0,
                stop_loss=price * 0.95,
                target=price * 1.05,
                strategy=self.name,
                confidence=0.8,
                timestamp=datetime.now(),
            )
        ]

    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        return False, None


def _build_jump_market_data() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=3, freq="B")
    closes = [100.0, 55.0, 100.0]  # -45% overnight jump on day 2
    rows: list[dict] = []
    for dt, close in zip(dates, closes):
        rows.append(
            {
                "symbol": "AAA",
                "date": dt,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1_000_000,
            }
        )
    return pd.DataFrame(rows)


def test_backtest_engine_returns_contract_fields():
    market_data = _build_market_data(periods=140)
    strategy = DeterministicTrendStrategy()
    engine = BacktestEngine(initial_capital=100000)

    results = engine.run_backtest(
        strategy=strategy,
        market_data=market_data,
        start_date="2024-02-01",
        end_date="2024-06-30",
    )

    expected_keys = {
        "strategy",
        "period",
        "initial_capital",
        "final_capital",
        "total_pnl",
        "total_return_pct",
        "total_trades",
        "win_rate",
        "max_drawdown",
        "sharpe_ratio",
        "trades",
        "portfolio_history",
    }
    assert expected_keys.issubset(results.keys())
    assert isinstance(results["portfolio_history"], list)
    assert len(results["portfolio_history"]) > 0
    assert results["total_trades"] > 0
    assert "regime_summary" in results


def test_walk_forward_analysis_returns_windows_and_summary_contract():
    market_data = _build_market_data(periods=320)
    strategy = DeterministicTrendStrategy()
    wfa = WalkForwardAnalysis(train_period_months=2, test_period_months=1)

    results = wfa.run_walk_forward(
        strategy=strategy,
        market_data=market_data,
        start_date="2024-01-01",
        end_date="2025-02-28",
    )

    assert "windows" in results
    assert "summary" in results
    assert len(results["windows"]) > 0

    summary_keys = {
        "avg_return",
        "std_return",
        "avg_sharpe",
        "avg_max_dd",
        "profitable_windows",
        "total_windows",
        "consistency",
    }
    assert summary_keys.issubset(results["summary"].keys())
    assert results["summary"]["total_windows"] == len(results["windows"])

class SparseMarkingStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__("Sparse Marking")

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict | None = None,
    ) -> list[Signal]:
        if market_data.empty:
            return []
        aaa = market_data[market_data["symbol"] == "AAA"].sort_values("date")
        if aaa.empty:
            return []
        price = float(aaa.iloc[-1]["close"])
        return [
            Signal(
                symbol="AAA",
                action="BUY",
                price=price,
                quantity=0,
                stop_loss=price * 0.9,
                target=price * 1.5,
                strategy=self.name,
                confidence=0.9,
                timestamp=datetime.now(),
            )
        ]

    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        return False, None


def test_backtest_marks_open_positions_when_symbol_missing_for_day():
    dates = pd.date_range("2024-01-01", periods=5, freq="B")
    rows: list[dict] = []

    aaa_close = {
        dates[0]: 100.0,
        dates[1]: 102.0,
        dates[3]: 101.0,
        dates[4]: 103.0,
    }
    for dt, close in aaa_close.items():
        rows.append(
            {
                "symbol": "AAA",
                "date": dt,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1_000_000,
            }
        )

    for dt in dates:
        close = 50.0
        rows.append(
            {
                "symbol": "BBB",
                "date": dt,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1_000_000,
            }
        )

    market_data = pd.DataFrame(rows)
    strategy = SparseMarkingStrategy()
    engine = BacktestEngine(initial_capital=100000)

    results = engine.run_backtest(
        strategy=strategy,
        market_data=market_data,
        start_date="2024-01-01",
        end_date="2024-01-05",
    )

    day_with_missing_aaa = next(
        row for row in results["portfolio_history"] if row["date"] == str(dates[2].date())
    )
    assert day_with_missing_aaa["num_positions"] >= 1
    assert day_with_missing_aaa["positions_value"] > 0


def test_compute_market_regime_returns_expected_keys():
    market_data = _build_market_data(periods=80)
    regime = compute_market_regime(market_data)

    assert "is_favorable" in regime
    assert "breadth_ratio" in regime
    assert "confidence" in regime
    assert "regime_label" in regime
    assert 0.0 <= float(regime["confidence"]) <= 1.0


def test_backtest_with_regime_differs_from_without(monkeypatch):
    monkeypatch.setattr(Config, "ADAPTIVE_DEFENSIVE_BREADTH_SMA_PERIOD", 5)
    monkeypatch.setattr(Config, "MOMENTUM_REGIME_SMA_PERIOD", 5)
    monkeypatch.setattr(Config, "MOMENTUM_REGIME_VOL_WINDOW", 5)
    monkeypatch.setattr(Config, "ADAPTIVE_DEFENSIVE_MIN_BREADTH", 0.50)
    monkeypatch.setattr(Config, "ADAPTIVE_DEFENSIVE_MIN_ELIGIBLE_SYMBOLS", 1)

    market_data = _build_bearish_market_data()
    strategy = RegimeSensitiveStrategy()

    with_regime_engine = BacktestEngine(initial_capital=100000)
    with_regime = with_regime_engine.run_backtest(
        strategy=strategy,
        market_data=market_data,
        start_date="2024-02-01",
        end_date="2024-07-31",
        include_regime=True,
    )

    without_regime_engine = BacktestEngine(initial_capital=100000)
    without_regime = without_regime_engine.run_backtest(
        strategy=strategy,
        market_data=market_data,
        start_date="2024-02-01",
        end_date="2024-07-31",
        include_regime=False,
    )

    assert with_regime["total_trades"] != without_regime["total_trades"]
    assert with_regime["total_trades"] < without_regime["total_trades"]
    assert with_regime["regime_summary"]["total_days"] > 0
    assert without_regime["regime_summary"]["total_days"] == 0


def test_backtest_exposes_regime_metrics_and_entry_labels():
    market_data = _build_market_data(periods=140)
    strategy = DeterministicTrendStrategy()
    engine = BacktestEngine(initial_capital=100000)

    results = engine.run_backtest(
        strategy=strategy,
        market_data=market_data,
        start_date="2024-02-01",
        end_date="2024-06-30",
        include_regime=True,
    )

    assert "regime_metrics" in results
    regime_metrics = results["regime_metrics"]
    assert "daily_returns_by_regime" in regime_metrics
    assert "entry_regime_trade_metrics" in regime_metrics
    assert isinstance(regime_metrics["daily_returns_by_regime"], dict)
    assert isinstance(regime_metrics["entry_regime_trade_metrics"], dict)

    trades = results["trades"]
    assert trades
    assert all("entry_regime_label" in trade for trade in trades)


def test_backtest_without_regime_labels_all_days_unknown():
    market_data = _build_market_data(periods=140)
    strategy = DeterministicTrendStrategy()
    engine = BacktestEngine(initial_capital=100000)

    results = engine.run_backtest(
        strategy=strategy,
        market_data=market_data,
        start_date="2024-02-01",
        end_date="2024-06-30",
        include_regime=False,
    )

    regime_metrics = results["regime_metrics"]
    unknown_days = int(regime_metrics.get("unknown_days", 0))
    assert unknown_days == len(results["portfolio_history"])
    assert "unknown" in regime_metrics.get("daily_returns_by_regime", {})


def test_overnight_jump_guardrail_flags_and_skips_false_stop_loss():
    market_data = _build_jump_market_data()
    strategy = OneShotEntryStopStrategy()
    engine = BacktestEngine(initial_capital=100000)

    results = engine.run_backtest(
        strategy=strategy,
        market_data=market_data,
        start_date="2024-01-01",
        end_date="2024-01-03",
        include_regime=False,
        warmup_days=0,
    )

    assert results["data_quality_clean"] is False
    warnings = results.get("data_quality_warnings", [])
    assert len(warnings) >= 1
    assert any(item["symbol"] == "AAA" and abs(float(item["pct_change"])) > 0.35 for item in warnings)
    assert any(item["date"] == "2024-01-02" for item in warnings)

    exit_reasons = {trade["exit_reason"] for trade in results["trades"]}
    assert "STOP_LOSS" not in exit_reasons


def test_overnight_jump_guardrail_blocks_entries_on_flagged_day():
    market_data = _build_jump_market_data()
    strategy = JumpDayEntryStrategy()
    engine = BacktestEngine(initial_capital=100000)

    results = engine.run_backtest(
        strategy=strategy,
        market_data=market_data,
        start_date="2024-01-01",
        end_date="2024-01-03",
        include_regime=False,
        warmup_days=0,
    )

    assert results["data_quality_clean"] is False
    assert len(results.get("data_quality_warnings", [])) >= 1
    assert int(results["total_trades"]) == 0


def test_max_loss_per_trade_caps_position_size(monkeypatch):
    """MAX_LOSS_PER_TRADE limits position size so worst-case loss is bounded."""
    monkeypatch.setattr(Config, "RISK_PER_TRADE", 0.02)
    monkeypatch.setattr(Config, "MAX_POSITION_SIZE", 0.15)
    monkeypatch.setattr(Config, "MAX_LOSS_PER_TRADE", 0.01)

    engine = BacktestEngine(initial_capital=100000)
    signal = Signal(
        symbol="TEST",
        action="BUY",
        price=100.0,
        quantity=0,
        stop_loss=90.0,  # risk_per_share = 10
        target=120.0,
        strategy="test",
        confidence=0.8,
        timestamp=datetime.now(),
    )

    # Without cap: risk_amount = 0.02 * 100000 = 2000, shares = 2000/10 = 200
    # With cap:    max_loss   = 0.01 * 100000 = 1000, shares = 1000/10 = 100
    size = engine._calculate_position_size(signal)
    assert size <= 100
    assert size > 0


def test_runtime_sizer_matches_backtest_with_max_loss_cap(monkeypatch):
    monkeypatch.setattr(Config, "RISK_PER_TRADE", 0.02)
    monkeypatch.setattr(Config, "MAX_POSITION_SIZE", 1.0)
    monkeypatch.setattr(Config, "MAX_LOSS_PER_TRADE", 0.01)
    monkeypatch.setattr(Config, "COST_PER_SIDE", 0.0)

    signal = Signal(
        symbol="TEST",
        action="BUY",
        price=100.0,
        quantity=0,
        stop_loss=90.0,
        target=120.0,
        strategy="test",
        confidence=0.8,
        timestamp=datetime.now(),
    )
    backtest_engine = BacktestEngine(initial_capital=100000)
    backtest_size = backtest_engine._calculate_position_size(signal)
    runtime_size = size_position(
        price=signal.price,
        stop_loss=signal.stop_loss,
        capital=100000.0,
        cash_available=100000.0,
    )

    assert backtest_size == runtime_size


def test_backtest_adaptive_regime_size_multiplier_scales_position(monkeypatch):
    monkeypatch.setattr(Config, "RISK_PER_TRADE", 0.02)
    monkeypatch.setattr(Config, "MAX_POSITION_SIZE", 1.0)
    monkeypatch.setattr(Config, "MAX_LOSS_PER_TRADE", 0.0)
    monkeypatch.setattr(Config, "ADAPTIVE_REGIME_SIZE_SCALING_ENABLED", True)
    monkeypatch.setattr(Config, "ADAPTIVE_REGIME_SIZE_MULT_FAVORABLE", 1.0)
    monkeypatch.setattr(Config, "ADAPTIVE_REGIME_SIZE_MULT_CHOPPY", 0.5)
    monkeypatch.setattr(Config, "ADAPTIVE_REGIME_SIZE_MULT_BEARISH", 0.25)
    monkeypatch.setattr(Config, "ADAPTIVE_REGIME_SIZE_MULT_DEFENSIVE", 0.25)

    engine = BacktestEngine(initial_capital=100000)
    favorable_signal = Signal(
        symbol="TEST",
        action="BUY",
        price=100.0,
        quantity=0,
        stop_loss=90.0,
        target=120.0,
        strategy="Adaptive Trend",
        confidence=0.8,
        timestamp=datetime.now(),
        metadata={"market_regime_label": "favorable"},
    )
    choppy_signal = Signal(
        symbol="TEST",
        action="BUY",
        price=100.0,
        quantity=0,
        stop_loss=90.0,
        target=120.0,
        strategy="Adaptive Trend",
        confidence=0.8,
        timestamp=datetime.now(),
        metadata={"market_regime_label": "choppy"},
    )

    favorable_size = engine._calculate_position_size(favorable_signal)
    choppy_size = engine._calculate_position_size(choppy_signal)

    assert favorable_size > 0
    assert choppy_size > 0
    assert choppy_size < favorable_size


def test_closed_trade_contains_enriched_fields_for_ml() -> None:
    market_data = _build_market_data(periods=140)
    strategy = DeterministicTrendStrategy()
    engine = BacktestEngine(initial_capital=100000)

    results = engine.run_backtest(
        strategy=strategy,
        market_data=market_data,
        start_date="2024-02-01",
        end_date="2024-06-30",
        include_regime=True,
    )

    trades = results["trades"]
    assert trades
    trade = trades[0]
    assert "metadata" in trade and isinstance(trade["metadata"], dict)
    assert "confidence" in trade
    assert "stop_loss" in trade
    assert "target" in trade
    assert "mfe" in trade
    assert "mae" in trade
    assert float(trade["mfe"]) >= 0.0
    assert float(trade["mae"]) >= 0.0


def test_existing_strategy_unaffected_with_default_engine_mode() -> None:
    market_data = _build_market_data(periods=140)
    strategy = DeterministicTrendStrategy()

    default_engine = BacktestEngine(initial_capital=100000)
    explicit_engine = BacktestEngine(initial_capital=100000, sizing_mode="atr")

    default_result = default_engine.run_backtest(
        strategy=strategy,
        market_data=market_data,
        start_date="2024-02-01",
        end_date="2024-06-30",
        include_regime=False,
    )
    explicit_result = explicit_engine.run_backtest(
        strategy=strategy,
        market_data=market_data,
        start_date="2024-02-01",
        end_date="2024-06-30",
        include_regime=False,
    )

    assert int(default_result.get("total_trades", 0)) == int(explicit_result.get("total_trades", 0))
    assert float(default_result.get("total_pnl", 0.0)) == float(explicit_result.get("total_pnl", 0.0))
