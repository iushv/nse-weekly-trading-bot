from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import json
from collections import Counter
from datetime import datetime
from typing import Any

import pandas as pd

from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.data.storage.database import db
from trading_bot.strategies.cross_sectional_momentum import CrossSectionalMomentumStrategy


def _load_universe(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8").splitlines()
    symbols = [line.strip() for line in raw if line.strip() and not line.strip().startswith("#")]
    return [s.replace(".NS", "").upper() for s in symbols]


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CSM backtest restricted to a universe file")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--universe-file", required=True)
    parser.add_argument("--capital", type=float, default=100000)
    parser.add_argument("--top-n", type=int, default=25)
    parser.add_argument("--lookback-months", type=int, default=6)
    parser.add_argument("--skip-recent-months", type=int, default=1)
    parser.add_argument("--trailing-stop-pct", type=float, default=0.15)
    parser.add_argument("--crash-protection", action="store_true")
    parser.add_argument("--target-vol", type=float, default=0.15)
    parser.add_argument("--min-exposure", type=float, default=0.25)
    parser.add_argument("--min-positions", type=int, default=5)
    parser.add_argument("--vol-lookback-days", type=int, default=126)
    parser.add_argument("--min-history-days", type=int, default=140)
    parser.add_argument("--warmup-days", type=int, default=400)
    parser.add_argument("--max-positions", type=int, default=30)
    parser.add_argument("--include-trades", action="store_true", help="Include per-trade rows in output JSON.")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    uni_path = Path(args.universe_file)
    universe = set(_load_universe(uni_path))
    if not universe:
        raise SystemExit(f"Universe file had no symbols: {uni_path}")

    sorted_uni = sorted(universe)
    placeholders = ",".join([f":s{i}" for i in range(len(sorted_uni))])
    query = f"""
    SELECT symbol, date, open, high, low, close, volume
    FROM price_data
    WHERE date >= DATE(:min_date) AND date <= DATE(:max_date)
      AND symbol IN ({placeholders})
    ORDER BY date, symbol
    """

    bind = {"min_date": "2023-01-01", "max_date": args.end}
    for i, sym in enumerate(sorted_uni):
        bind[f"s{i}"] = sym
    market_data = pd.read_sql(query, db.engine, params=bind)

    strategy = CrossSectionalMomentumStrategy(
        top_n=int(args.top_n),
        lookback_months=int(args.lookback_months),
        skip_recent_months=int(args.skip_recent_months),
        trailing_stop_pct=float(args.trailing_stop_pct),
        crash_protection=bool(args.crash_protection),
        target_vol=float(args.target_vol),
        min_exposure=float(args.min_exposure),
        min_positions=int(args.min_positions),
        vol_lookback_days=int(args.vol_lookback_days),
        min_history_days=int(args.min_history_days),
        initial_capital=float(args.capital),
        log_signals=False,
    )
    engine = BacktestEngine(
        initial_capital=float(args.capital),
        sizing_mode="equal_weight",
        max_positions=int(args.max_positions),
    )
    result = engine.run_backtest(
        strategy,
        market_data,
        args.start,
        args.end,
        warmup_days=int(args.warmup_days),
        include_regime=False,
    )

    trades = result.get("trades", [])
    wins = [t for t in trades if float(t.get("net_pnl", 0.0)) > 0]
    losses = [t for t in trades if float(t.get("net_pnl", 0.0)) < 0]
    win_sum = float(sum(float(t.get("net_pnl", 0.0)) for t in wins))
    loss_sum_abs = abs(float(sum(float(t.get("net_pnl", 0.0)) for t in losses)))
    pf = (win_sum / loss_sum_abs) if loss_sum_abs > 0 else 0.0
    avg_hold = (
        float(sum(float(t.get("days_held", 0)) for t in trades) / len(trades))
        if trades
        else 0.0
    )
    exit_counts = Counter(str(t.get("exit_reason", "UNKNOWN")) for t in trades)
    exit_breakdown: dict[str, dict[str, float | int]] = {}
    for reason in sorted(exit_counts):
        reason_trades = [t for t in trades if str(t.get("exit_reason", "UNKNOWN")) == reason]
        reason_count = len(reason_trades)
        reason_total_pnl = float(sum(float(t.get("net_pnl", 0.0)) for t in reason_trades))
        reason_wins = sum(1 for t in reason_trades if float(t.get("net_pnl", 0.0)) > 0)
        exit_breakdown[reason] = {
            "count": reason_count,
            "total_pnl": reason_total_pnl,
            "avg_pnl": (reason_total_pnl / reason_count) if reason_count else 0.0,
            "win_rate": (reason_wins / reason_count) if reason_count else 0.0,
        }

    out: dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "period": {"start": args.start, "end": args.end},
        "universe": {"file": str(uni_path), "symbols": len(universe)},
        "strategy_config": {
            "top_n": int(args.top_n),
            "lookback_months": int(args.lookback_months),
            "skip_recent_months": int(args.skip_recent_months),
            "trailing_stop_pct": float(args.trailing_stop_pct),
            "crash_protection": bool(args.crash_protection),
            "target_vol": float(args.target_vol),
            "min_exposure": float(args.min_exposure),
            "min_positions": int(args.min_positions),
            "vol_lookback_days": int(args.vol_lookback_days),
            "min_history_days": int(args.min_history_days),
        },
        "engine_config": {
            "capital": float(args.capital),
            "sizing_mode": "equal_weight",
            "max_positions": int(args.max_positions),
            "warmup_days": int(args.warmup_days),
            "include_regime": False,
        },
        "metrics": {
            "total_return_pct": float(result.get("total_return_pct", 0.0)),
            "total_pnl": float(result.get("total_pnl", 0.0)),
            "sharpe_ratio": float(result.get("sharpe_ratio", 0.0)),
            "max_drawdown": float(result.get("max_drawdown", 0.0)),
            "total_trades": int(result.get("total_trades", 0)),
            "win_rate": float(result.get("win_rate", 0.0)),
            "profit_factor_closed": float(pf),
            "avg_days_held": float(avg_hold),
        },
        "regime_summary": result.get("regime_summary", {}),
        "data_quality_clean": bool(result.get("data_quality_clean", True)),
        "data_quality_warnings": result.get("data_quality_warnings", []),
        "exit_breakdown": exit_breakdown,
    }

    if args.include_trades:
        out["trades"] = [
            {
                "symbol": str(t.get("symbol", "")),
                "entry_date": str(t.get("entry_date", "")),
                "exit_date": str(t.get("exit_date", "")),
                "entry_price": float(t.get("entry_price", 0.0)),
                "exit_price": float(t.get("exit_price", 0.0)),
                "quantity": int(t.get("quantity", 0)),
                "days_held": int(t.get("days_held", 0)),
                "net_pnl": float(t.get("net_pnl", 0.0)),
                "pnl_percent": float(t.get("pnl_percent", 0.0)),
                "exit_reason": str(t.get("exit_reason", "UNKNOWN")),
                "metadata": _json_safe(t.get("metadata", {})),
            }
            for t in trades
        ]

    if args.out:
        out_path = Path(args.out)
    else:
        out_dir = ROOT / "reports" / "backtests"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / (
            f"csm_backtest_{uni_path.stem}_{args.start.replace('-', '')}_{args.end.replace('-', '')}_{stamp}.json"
        )
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
