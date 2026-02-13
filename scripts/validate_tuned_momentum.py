from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.config.settings import Config
from trading_bot.data.storage.database import db
from trading_bot.strategies.momentum_breakout import MomentumBreakoutStrategy


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate tuned momentum configurations on full/holdout/rolling windows."
    )
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default=str(datetime.utcnow().date()))
    parser.add_argument("--holdout-start", default="2025-10-01")
    parser.add_argument("--initial-capital", type=float, default=100000.0)
    parser.add_argument(
        "--tuning-summary",
        default="reports/backtests/latest_exit_risk_tuning.json",
        help="Path to latest exit/risk tuning summary.",
    )
    return parser.parse_args()


def _load_market_data() -> pd.DataFrame:
    frame = pd.read_sql(
        """
        SELECT symbol, date, open, high, low, close, volume
        FROM price_data
        ORDER BY symbol, date
        """,
        db.engine,
    )
    if frame.empty:
        raise RuntimeError("No market data found in price_data table")
    return frame


def _load_tuning_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _pick_sharpe_candidate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    ranked = sorted(
        rows,
        key=lambda x: (
            float(x.get("metrics", {}).get("sharpe_ratio", 0.0)),
            float(x.get("metrics", {}).get("total_return_pct", 0.0)),
            int(x.get("metrics", {}).get("total_trades", 0)),
        ),
        reverse=True,
    )
    return ranked[0]


def _candidate_from_row(row: dict[str, Any]) -> dict[str, Any]:
    entry = row.get("entry_params", {})
    exit_risk = row.get("exit_risk_params", {})
    return {
        "lookback_period": int(entry.get("lookback_period", 15)),
        "volume_multiplier": float(entry.get("volume_multiplier", 1.0)),
        "min_roc": float(entry.get("min_roc", 0.07)),
        "max_atr_pct": float(entry.get("max_atr_pct", 0.04)),
        "stop_atr_mult": float(exit_risk.get("stop_atr_mult", 1.5)),
        "rr_ratio": float(exit_risk.get("rr_ratio", 2.0)),
        "time_stop_days": int(exit_risk.get("time_stop_days", 14)),
        "time_stop_move_pct": float(exit_risk.get("time_stop_move_pct", 0.02)),
        "risk_per_trade": float(exit_risk.get("risk_per_trade", 0.01)),
        "max_position_size": float(exit_risk.get("max_position_size", 0.10)),
    }


def _build_candidates(tuning_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    momentum_block = tuning_payload.get("momentum_breakout", {})
    top_rows = momentum_block.get("top", []) if isinstance(momentum_block, dict) else []
    best_row = momentum_block.get("best") if isinstance(momentum_block, dict) else None

    baseline = {
        "lookback_period": 20,
        "volume_multiplier": 1.2,
        "min_roc": 0.05,
        "max_atr_pct": 0.05,
        "stop_atr_mult": 2.0,
        "rr_ratio": 2.0,
        "time_stop_days": 10,
        "time_stop_move_pct": 0.02,
        "risk_per_trade": 0.02,
        "max_position_size": 0.15,
    }

    out = {"default_momentum": baseline}
    if isinstance(best_row, dict):
        out["tuned_score_best"] = _candidate_from_row(best_row)
    sharpe_row = _pick_sharpe_candidate(top_rows if isinstance(top_rows, list) else [])
    if isinstance(sharpe_row, dict):
        out["tuned_sharpe_candidate"] = _candidate_from_row(sharpe_row)
    return out


def _run_backtest(
    cfg: dict[str, Any],
    market_data: pd.DataFrame,
    start: str,
    end: str,
    initial_capital: float,
) -> dict[str, Any]:
    orig_risk = Config.RISK_PER_TRADE
    orig_max_position_size = Config.MAX_POSITION_SIZE
    try:
        Config.RISK_PER_TRADE = float(cfg["risk_per_trade"])  # type: ignore[misc]
        Config.MAX_POSITION_SIZE = float(cfg["max_position_size"])  # type: ignore[misc]
        strategy = MomentumBreakoutStrategy(
            lookback_period=int(cfg["lookback_period"]),
            volume_multiplier=float(cfg["volume_multiplier"]),
            min_roc=float(cfg["min_roc"]),
            max_atr_pct=float(cfg["max_atr_pct"]),
            stop_atr_mult=float(cfg["stop_atr_mult"]),
            rr_ratio=float(cfg["rr_ratio"]),
            time_stop_days=int(cfg["time_stop_days"]),
            time_stop_move_pct=float(cfg["time_stop_move_pct"]),
            log_signals=False,
        )
        engine = BacktestEngine(initial_capital=initial_capital)
        result = engine.run_backtest(strategy, market_data, start, end)
        return {
            "total_return_pct": float(result.get("total_return_pct", 0.0)),
            "total_pnl": float(result.get("total_pnl", 0.0)),
            "total_trades": int(result.get("total_trades", 0)),
            "win_rate": float(result.get("win_rate", 0.0)),
            "sharpe_ratio": float(result.get("sharpe_ratio", 0.0)),
            "max_drawdown": float(result.get("max_drawdown", 0.0)),
        }
    finally:
        Config.RISK_PER_TRADE = orig_risk  # type: ignore[misc]
        Config.MAX_POSITION_SIZE = orig_max_position_size  # type: ignore[misc]


def _rolling_windows(start_date: str, end_date: str, months: int = 3) -> list[tuple[str, str]]:
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    windows: list[tuple[str, str]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + pd.DateOffset(months=months) - pd.Timedelta(days=1), end)
        windows.append((str(cursor.date()), str(window_end.date())))
        cursor = cursor + pd.DateOffset(months=months)
    return windows


def main() -> None:
    args = _parse_args()
    market_data = _load_market_data()
    tuning_payload = _load_tuning_payload(Path(args.tuning_summary))
    candidates = _build_candidates(tuning_payload)

    full_start = args.start_date
    full_end = args.end_date
    holdout_start = args.holdout_start
    pre_holdout_end = str((pd.to_datetime(holdout_start) - pd.Timedelta(days=1)).date())

    periods = {
        "full": (full_start, full_end),
        "pre_holdout": (full_start, pre_holdout_end),
        "holdout": (holdout_start, full_end),
    }
    windows = _rolling_windows(full_start, full_end, months=3)

    report: dict[str, Any] = {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "period": {"start_date": full_start, "end_date": full_end, "holdout_start": holdout_start},
        "symbol_coverage": int(market_data["symbol"].nunique()),
        "candidates": candidates,
        "results": {},
    }

    for name, cfg in candidates.items():
        item: dict[str, Any] = {"periods": {}, "rolling_windows": []}
        for label, (start, end) in periods.items():
            item["periods"][label] = _run_backtest(
                cfg=cfg,
                market_data=market_data,
                start=start,
                end=end,
                initial_capital=float(args.initial_capital),
            )
        for idx, (start, end) in enumerate(windows, start=1):
            item["rolling_windows"].append(
                {
                    "window": idx,
                    "start": start,
                    "end": end,
                    "metrics": _run_backtest(
                        cfg=cfg,
                        market_data=market_data,
                        start=start,
                        end=end,
                        initial_capital=float(args.initial_capital),
                    ),
                }
            )
        report["results"][name] = item

    ranking = sorted(
        (
            {
                "candidate": name,
                "holdout_sharpe": float(row["periods"]["holdout"]["sharpe_ratio"]),
                "holdout_return_pct": float(row["periods"]["holdout"]["total_return_pct"]),
                "holdout_win_rate": float(row["periods"]["holdout"]["win_rate"]),
                "holdout_trades": int(row["periods"]["holdout"]["total_trades"]),
                "holdout_max_drawdown": float(row["periods"]["holdout"]["max_drawdown"]),
            }
            for name, row in report["results"].items()
        ),
        key=lambda x: (x["holdout_sharpe"], x["holdout_return_pct"]),
        reverse=True,
    )
    report["holdout_ranking"] = ranking

    out_dir = Path("reports/backtests")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"tuned_validation_{stamp}.json"
    latest_path = out_dir / "latest_tuned_validation.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Saved validation report: {out_path}")
    print(json.dumps(ranking, indent=2))


if __name__ == "__main__":
    main()
