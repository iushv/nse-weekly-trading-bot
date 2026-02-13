from __future__ import annotations

import argparse
import itertools
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.config.settings import Config
from trading_bot.data.storage.database import db
from trading_bot.strategies.mean_reversion import MeanReversionStrategy
from trading_bot.strategies.momentum_breakout import MomentumBreakoutStrategy


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tune exit logic and risk sizing for core strategies.")
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default=str(datetime.utcnow().date()))
    parser.add_argument("--initial-capital", type=float, default=100000.0)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--max-combos",
        type=int,
        default=120,
        help="Max parameter combinations per strategy (0 means all combinations).",
    )
    return parser.parse_args()


def _load_entry_presets(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        out: dict[str, dict[str, Any]] = {}
        momentum = payload.get("momentum_breakout", {})
        mean_rev = payload.get("mean_reversion", {})
        if isinstance(momentum, dict):
            best = momentum.get("best")
            if isinstance(best, dict):
                params = best.get("params", {})
                if isinstance(params, dict):
                    out["momentum_breakout"] = params
        if isinstance(mean_rev, dict):
            best = mean_rev.get("best")
            if isinstance(best, dict):
                params = best.get("params", {})
                if isinstance(params, dict):
                    out["mean_reversion"] = params
        return out
    except Exception:
        return {}


def _score(metrics: dict[str, Any]) -> float:
    trades = int(metrics.get("total_trades", 0))
    total_return_pct = float(metrics.get("total_return_pct", 0.0))
    sharpe = float(metrics.get("sharpe_ratio", 0.0))
    win_rate = float(metrics.get("win_rate", 0.0))
    max_drawdown = float(metrics.get("max_drawdown", 0.0))
    drawdown_abs = abs(min(0.0, max_drawdown))

    trade_bonus = min(trades, 40) * 0.04
    trade_penalty = 0.0 if trades >= 12 else (12 - trades) * 0.5
    return (
        total_return_pct
        + (15.0 * sharpe)
        + (20.0 * win_rate)
        - (35.0 * drawdown_abs)
        + trade_bonus
        - trade_penalty
    )


def _metrics(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_return_pct": float(result.get("total_return_pct", 0.0)),
        "total_pnl": float(result.get("total_pnl", 0.0)),
        "total_trades": int(result.get("total_trades", 0)),
        "win_rate": float(result.get("win_rate", 0.0)),
        "sharpe_ratio": float(result.get("sharpe_ratio", 0.0)),
        "max_drawdown": float(result.get("max_drawdown", 0.0)),
    }


def _iter_limited(items: Iterable[tuple[Any, ...]], limit: int) -> list[tuple[Any, ...]]:
    data = list(items)
    if limit > 0:
        return data[:limit]
    return data


def _run_with_risk(
    strategy: Any,
    market_data: pd.DataFrame,
    start_date: str,
    end_date: str,
    initial_capital: float,
    risk_per_trade: float,
    max_position_size: float,
) -> dict[str, Any]:
    orig_risk = Config.RISK_PER_TRADE
    orig_max_pos = Config.MAX_POSITION_SIZE
    try:
        Config.RISK_PER_TRADE = float(risk_per_trade)  # type: ignore[misc]
        Config.MAX_POSITION_SIZE = float(max_position_size)  # type: ignore[misc]
        engine = BacktestEngine(initial_capital=initial_capital)
        return engine.run_backtest(
            strategy=strategy,
            market_data=market_data,
            start_date=start_date,
            end_date=end_date,
        )
    finally:
        Config.RISK_PER_TRADE = orig_risk  # type: ignore[misc]
        Config.MAX_POSITION_SIZE = orig_max_pos  # type: ignore[misc]


def _tune_momentum(
    market_data: pd.DataFrame,
    start_date: str,
    end_date: str,
    initial_capital: float,
    entry_params: dict[str, Any],
    max_combos: int,
) -> list[dict[str, Any]]:
    combos = _iter_limited(
        itertools.product(
            [1.5, 2.0, 2.5],  # stop_atr_mult
            [1.2, 1.6, 2.0],  # rr_ratio
            [7, 10, 14],  # time_stop_days
            [0.01, 0.02],  # time_stop_move_pct
            [0.01, 0.015, 0.02],  # risk_per_trade
            [0.10, 0.12],  # max_position_size
        ),
        max_combos,
    )

    rows: list[dict[str, Any]] = []
    for idx, (stop_mult, rr_ratio, time_days, move_pct, risk_pct, max_pos) in enumerate(combos, start=1):
        strategy = MomentumBreakoutStrategy(
            lookback_period=int(entry_params.get("lookback_period", 15)),
            volume_multiplier=float(entry_params.get("volume_multiplier", 1.0)),
            min_roc=float(entry_params.get("min_roc", 0.07)),
            max_atr_pct=float(entry_params.get("max_atr_pct", 0.04)),
            stop_atr_mult=float(stop_mult),
            rr_ratio=float(rr_ratio),
            time_stop_days=int(time_days),
            time_stop_move_pct=float(move_pct),
            log_signals=False,
        )
        result = _run_with_risk(
            strategy=strategy,
            market_data=market_data,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            risk_per_trade=float(risk_pct),
            max_position_size=float(max_pos),
        )
        m = _metrics(result)
        rows.append(
            {
                "strategy": "momentum_breakout",
                "rank_hint": idx,
                "entry_params": {
                    "lookback_period": int(entry_params.get("lookback_period", 15)),
                    "volume_multiplier": float(entry_params.get("volume_multiplier", 1.0)),
                    "min_roc": float(entry_params.get("min_roc", 0.07)),
                    "max_atr_pct": float(entry_params.get("max_atr_pct", 0.04)),
                },
                "exit_risk_params": {
                    "stop_atr_mult": float(stop_mult),
                    "rr_ratio": float(rr_ratio),
                    "time_stop_days": int(time_days),
                    "time_stop_move_pct": float(move_pct),
                    "risk_per_trade": float(risk_pct),
                    "max_position_size": float(max_pos),
                },
                "score": _score(m),
                "metrics": m,
            }
        )
    rows.sort(key=lambda x: float(x.get("score", -1e9)), reverse=True)
    return rows


def _tune_mean_reversion(
    market_data: pd.DataFrame,
    start_date: str,
    end_date: str,
    initial_capital: float,
    entry_params: dict[str, Any],
    max_combos: int,
) -> list[dict[str, Any]]:
    combos = _iter_limited(
        itertools.product(
            [1.0, 1.5],  # stop_atr_mult
            [0.05, 0.08],  # target_gain_pct
            [5, 7, 10],  # time_stop_days
            [0.97, 0.98],  # stop_bb_buffer
            [0.97, 0.98],  # stop_sma_buffer
            [0.01, 0.015, 0.02],  # risk_per_trade
            [0.10, 0.12],  # max_position_size
        ),
        max_combos,
    )

    rows: list[dict[str, Any]] = []
    for idx, (stop_mult, target_gain, time_days, bb_buf, sma_buf, risk_pct, max_pos) in enumerate(combos, start=1):
        strategy = MeanReversionStrategy(
            oversold_buffer=float(entry_params.get("oversold_buffer", 3.0)),
            trend_tolerance=float(entry_params.get("trend_tolerance", 0.93)),
            bb_entry_mult=float(entry_params.get("bb_entry_mult", 1.0)),
            volume_cap=float(entry_params.get("volume_cap", 2.0)),
            stop_atr_mult=float(stop_mult),
            target_gain_pct=float(target_gain),
            time_stop_days=int(time_days),
            stop_bb_buffer=float(bb_buf),
            stop_sma_buffer=float(sma_buf),
            log_signals=False,
        )
        result = _run_with_risk(
            strategy=strategy,
            market_data=market_data,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            risk_per_trade=float(risk_pct),
            max_position_size=float(max_pos),
        )
        m = _metrics(result)
        rows.append(
            {
                "strategy": "mean_reversion",
                "rank_hint": idx,
                "entry_params": {
                    "oversold_buffer": float(entry_params.get("oversold_buffer", 3.0)),
                    "trend_tolerance": float(entry_params.get("trend_tolerance", 0.93)),
                    "bb_entry_mult": float(entry_params.get("bb_entry_mult", 1.0)),
                    "volume_cap": float(entry_params.get("volume_cap", 2.0)),
                },
                "exit_risk_params": {
                    "stop_atr_mult": float(stop_mult),
                    "target_gain_pct": float(target_gain),
                    "time_stop_days": int(time_days),
                    "stop_bb_buffer": float(bb_buf),
                    "stop_sma_buffer": float(sma_buf),
                    "risk_per_trade": float(risk_pct),
                    "max_position_size": float(max_pos),
                },
                "score": _score(m),
                "metrics": m,
            }
        )
    rows.sort(key=lambda x: float(x.get("score", -1e9)), reverse=True)
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

    presets = _load_entry_presets(Path("reports/backtests/latest_tuning_summary.json"))
    momentum_entry = presets.get(
        "momentum_breakout",
        {
            "lookback_period": 15,
            "volume_multiplier": 1.0,
            "min_roc": 0.07,
            "max_atr_pct": 0.04,
        },
    )
    mean_entry = presets.get(
        "mean_reversion",
        {
            "oversold_buffer": 3.0,
            "trend_tolerance": 0.93,
            "bb_entry_mult": 1.0,
            "volume_cap": 2.0,
        },
    )

    momentum_rows = _tune_momentum(
        market_data=market_data,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        entry_params=momentum_entry,
        max_combos=args.max_combos,
    )
    mean_rows = _tune_mean_reversion(
        market_data=market_data,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        entry_params=mean_entry,
        max_combos=args.max_combos,
    )

    report: dict[str, Any] = {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "period": {"start_date": args.start_date, "end_date": args.end_date},
        "top_k": int(args.top_k),
        "max_combos": int(args.max_combos),
        "momentum_breakout": {
            "entry_preset": momentum_entry,
            "combinations_tested": len(momentum_rows),
            "best": momentum_rows[0] if momentum_rows else None,
            "top": momentum_rows[: args.top_k],
        },
        "mean_reversion": {
            "entry_preset": mean_entry,
            "combinations_tested": len(mean_rows),
            "best": mean_rows[0] if mean_rows else None,
            "top": mean_rows[: args.top_k],
        },
    }

    out_dir = Path("reports/backtests")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"exit_risk_tuning_{stamp}.json"
    latest_path = out_dir / "latest_exit_risk_tuning.json"
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
