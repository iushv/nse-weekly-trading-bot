from __future__ import annotations

from datetime import datetime

import pandas as pd

from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.walk_forward import WalkForwardAnalysis
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
