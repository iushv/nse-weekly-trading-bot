from __future__ import annotations

import argparse
import itertools
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.data.storage.database import db
from trading_bot.strategies.mean_reversion import MeanReversionStrategy
from trading_bot.strategies.momentum_breakout import MomentumBreakoutStrategy


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compact parameter tuning for core strategies.")
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default=str(datetime.utcnow().date()))
    parser.add_argument("--initial-capital", type=float, default=100000.0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-combos", type=int, default=0, help="Optional cap per strategy; 0 disables cap.")
    return parser.parse_args()


def _score_result(result: dict[str, Any]) -> float:
    trades = int(result.get("total_trades", 0))
    total_return_pct = float(result.get("total_return_pct", 0.0))
    sharpe = float(result.get("sharpe_ratio", 0.0))
    win_rate = float(result.get("win_rate", 0.0))
    max_drawdown = float(result.get("max_drawdown", 0.0))
    drawdown_abs = abs(min(0.0, max_drawdown))

    # Balance profitability and risk. Penalize very low trade counts.
    trade_bonus = min(trades, 30) * 0.05
    trade_penalty = 0.0 if trades >= 10 else (10 - trades) * 0.5
    return (
        total_return_pct
        + (12.0 * sharpe)
        + (20.0 * win_rate)
        - (30.0 * drawdown_abs)
        + trade_bonus
        - trade_penalty
    )


def _extract_metrics(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_return_pct": float(result.get("total_return_pct", 0.0)),
        "total_pnl": float(result.get("total_pnl", 0.0)),
        "total_trades": int(result.get("total_trades", 0)),
        "win_rate": float(result.get("win_rate", 0.0)),
        "sharpe_ratio": float(result.get("sharpe_ratio", 0.0)),
        "max_drawdown": float(result.get("max_drawdown", 0.0)),
    }


def _run_momentum_search(
    market_data: pd.DataFrame,
    start_date: str,
    end_date: str,
    initial_capital: float,
    max_combos: int,
) -> list[dict[str, Any]]:
    combos = list(
        itertools.product(
            [15, 20],  # lookback_period
            [1.0, 1.2],  # volume_multiplier
            [0.03, 0.05, 0.07],  # min_roc
            [0.04, 0.05],  # max_atr_pct
        )
    )
    if max_combos > 0:
        combos = combos[:max_combos]

    rows: list[dict[str, Any]] = []
    for idx, (lookback, vol_mult, min_roc, atr_cap) in enumerate(combos, start=1):
        strategy = MomentumBreakoutStrategy(
            lookback_period=lookback,
            volume_multiplier=vol_mult,
            min_roc=min_roc,
            max_atr_pct=atr_cap,
            log_signals=False,
        )
        engine = BacktestEngine(initial_capital=initial_capital)
        result = engine.run_backtest(
            strategy=strategy,
            market_data=market_data,
            start_date=start_date,
            end_date=end_date,
        )
        metrics = _extract_metrics(result)
        score = _score_result(metrics)
        rows.append(
            {
                "strategy": "momentum_breakout",
                "rank_hint": idx,
                "params": {
                    "lookback_period": lookback,
                    "volume_multiplier": vol_mult,
                    "min_roc": min_roc,
                    "max_atr_pct": atr_cap,
                },
                "score": score,
                "metrics": metrics,
            }
        )
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows


def _run_mean_reversion_search(
    market_data: pd.DataFrame,
    start_date: str,
    end_date: str,
    initial_capital: float,
    max_combos: int,
) -> list[dict[str, Any]]:
    combos = list(
        itertools.product(
            [3.0, 5.0, 7.0],  # oversold_buffer
            [0.93, 0.95],  # trend_tolerance
            [1.00, 1.01],  # bb_entry_mult
            [2.0, 2.5],  # volume_cap
        )
    )
    if max_combos > 0:
        combos = combos[:max_combos]

    rows: list[dict[str, Any]] = []
    for idx, (oversold_buf, trend_tol, bb_mult, vol_cap) in enumerate(combos, start=1):
        strategy = MeanReversionStrategy(
            oversold_buffer=oversold_buf,
            trend_tolerance=trend_tol,
            bb_entry_mult=bb_mult,
            volume_cap=vol_cap,
            log_signals=False,
        )
        engine = BacktestEngine(initial_capital=initial_capital)
        result = engine.run_backtest(
            strategy=strategy,
            market_data=market_data,
            start_date=start_date,
            end_date=end_date,
        )
        metrics = _extract_metrics(result)
        score = _score_result(metrics)
        rows.append(
            {
                "strategy": "mean_reversion",
                "rank_hint": idx,
                "params": {
                    "oversold_buffer": oversold_buf,
                    "trend_tolerance": trend_tol,
                    "bb_entry_mult": bb_mult,
                    "volume_cap": vol_cap,
                },
                "score": score,
                "metrics": metrics,
            }
        )
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows


def main() -> None:
    args = _parse_args()
    market_data = pd.read_sql(
        """
        SELECT symbol, date, open, high, low, close, volume
        FROM price_data
        ORDER BY symbol, date
        """,
        db.engine,
    )
    if market_data.empty:
        raise RuntimeError("No market data found in price_data table")

    momentum = _run_momentum_search(
        market_data=market_data,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        max_combos=args.max_combos,
    )
    mean_rev = _run_mean_reversion_search(
        market_data=market_data,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        max_combos=args.max_combos,
    )

    report: dict[str, Any] = {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "period": {"start_date": args.start_date, "end_date": args.end_date},
        "top_k": int(args.top_k),
        "momentum_breakout": {
            "best": momentum[0] if momentum else None,
            "top": momentum[: args.top_k],
            "combinations_tested": len(momentum),
        },
        "mean_reversion": {
            "best": mean_rev[0] if mean_rev else None,
            "top": mean_rev[: args.top_k],
            "combinations_tested": len(mean_rev),
        },
    }

    out_dir = Path("reports/backtests")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"strategy_tuning_{stamp}.json"
    latest_path = out_dir / "latest_tuning_summary.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Saved tuning report: {out_path}")
    print(f"Saved latest tuning summary: {latest_path}")
    print(
        json.dumps(
            {
                "momentum_best": report["momentum_breakout"]["best"],
                "mean_reversion_best": report["mean_reversion"]["best"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
