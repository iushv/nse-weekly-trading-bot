from __future__ import annotations

from typing import Any

import pandas as pd
from loguru import logger

from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.strategies.base_strategy import BaseStrategy


class WalkForwardAnalysis:
    def __init__(self, train_period_months: int = 24, test_period_months: int = 6) -> None:
        self.train_period_months = train_period_months
        self.test_period_months = test_period_months

    def run_walk_forward(
        self,
        strategy: BaseStrategy,
        market_data: pd.DataFrame,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        windows = self._create_windows(start, end)
        out: list[dict] = []

        for idx, (_, _, test_start, test_end) in enumerate(windows, start=1):
            logger.info(f"Running window {idx}/{len(windows)}: {test_start.date()} to {test_end.date()}")
            engine = BacktestEngine(initial_capital=100000)
            result = engine.run_backtest(
                strategy=strategy,
                market_data=market_data,
                start_date=str(test_start.date()),
                end_date=str(test_end.date()),
            )
            out.append(
                {
                    "window": idx,
                    "test_start": test_start,
                    "test_end": test_end,
                    "return": result.get("total_return_pct", 0.0),
                    "sharpe": result.get("sharpe_ratio", 0.0),
                    "max_dd": result.get("max_drawdown", 0.0),
                    "trades": result.get("total_trades", 0),
                    "win_rate": result.get("win_rate", 0.0),
                }
            )

        summary = self._calculate_summary(out)
        return {"windows": out, "summary": summary}

    def _create_windows(self, start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, ...]]:
        windows: list[tuple[pd.Timestamp, ...]] = []
        current = start
        while current < end:
            train_start = current
            train_end = current + pd.DateOffset(months=self.train_period_months)
            test_start = train_end
            test_end = test_start + pd.DateOffset(months=self.test_period_months)
            if test_end > end:
                break
            windows.append((train_start, train_end, test_start, test_end))
            current = test_start
        return windows

    def _calculate_summary(self, rows: list[dict]) -> dict:
        df = pd.DataFrame(rows)
        if df.empty:
            return {
                "avg_return": 0.0,
                "consistency": 0.0,
                "total_windows": 0,
            }

        profitable = len(df[df["return"] > 0])
        return {
            "avg_return": float(df["return"].mean()),
            "std_return": float(df["return"].std()),
            "avg_sharpe": float(df["sharpe"].mean()),
            "avg_max_dd": float(df["max_dd"].mean()),
            "profitable_windows": int(profitable),
            "total_windows": int(len(df)),
            "consistency": float(profitable / len(df)),
        }

    def plot_results(self, results: dict, save_path: str | None = None) -> None:
        import matplotlib.pyplot as plt
        df = pd.DataFrame(results.get("windows", []))
        if df.empty:
            return

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        axes[0, 0].bar(df["window"], df["return"])
        axes[0, 0].set_title("Returns by Window")

        axes[0, 1].bar(df["window"], df["sharpe"])
        axes[0, 1].set_title("Sharpe by Window")

        axes[1, 0].bar(df["window"], df["max_dd"] * 100)
        axes[1, 0].set_title("Max Drawdown by Window")

        axes[1, 1].bar(df["window"], df["win_rate"] * 100)
        axes[1, 1].set_title("Win Rate by Window")

        plt.tight_layout()
        if save_path:
            plt.savefig(save_path, dpi=140, bbox_inches="tight")
        else:
            plt.close(fig)


walk_forward = WalkForwardAnalysis()
