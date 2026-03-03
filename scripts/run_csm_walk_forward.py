from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import json
from datetime import datetime

import pandas as pd

from trading_bot.backtesting.walk_forward import WalkForwardAnalysis
from trading_bot.data.storage.database import db
from trading_bot.strategies.cross_sectional_momentum import CrossSectionalMomentumStrategy


def _load_universe(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8").splitlines()
    symbols = [line.strip() for line in raw if line.strip() and not line.strip().startswith("#")]
    return [s.replace(".NS", "").upper() for s in symbols]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CSM rolling OOS walk-forward over a universe file")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--universe-file", required=True)
    parser.add_argument("--train-months", type=int, default=3)
    parser.add_argument("--test-months", type=int, default=3)
    parser.add_argument("--capital", type=float, default=100000)
    parser.add_argument("--top-n", type=int, default=25)
    parser.add_argument("--lookback-months", type=int, default=6)
    parser.add_argument("--skip-recent-months", type=int, default=1)
    parser.add_argument("--trailing-stop-pct", type=float, default=0.15)
    parser.add_argument("--min-history-days", type=int, default=140)
    parser.add_argument("--warmup-days", type=int, default=400)
    parser.add_argument("--max-positions", type=int, default=30)
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
        min_history_days=int(args.min_history_days),
        initial_capital=float(args.capital),
        log_signals=False,
    )
    wfa = WalkForwardAnalysis(
        train_period_months=int(args.train_months),
        test_period_months=int(args.test_months),
    )
    results = wfa.run_walk_forward(
        strategy,
        market_data,
        args.start,
        args.end,
        engine_kwargs={
            "initial_capital": float(args.capital),
            "sizing_mode": "equal_weight",
            "max_positions": int(args.max_positions),
        },
        backtest_kwargs={
            "include_regime": False,
            "warmup_days": int(args.warmup_days),
        },
    )

    summary = results.get("summary", {})
    for key, value in list(summary.items()):
        if isinstance(value, float) and value != value:
            summary[key] = None

    windows = []
    for item in results.get("windows", []):
        windows.append(
            {
                "window": int(item["window"]),
                "test_start": str(pd.Timestamp(item["test_start"]).date()),
                "test_end": str(pd.Timestamp(item["test_end"]).date()),
                "return_pct": float(item["return"]),
                "sharpe": float(item["sharpe"]),
                "max_dd": float(item["max_dd"]),
                "trades": int(item["trades"]),
                "win_rate": float(item["win_rate"]),
            }
        )

    out = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "period": {"start": args.start, "end": args.end},
        "universe": {"file": str(uni_path), "symbols": len(universe)},
        "strategy_config": {
            "top_n": int(args.top_n),
            "lookback_months": int(args.lookback_months),
            "skip_recent_months": int(args.skip_recent_months),
            "trailing_stop_pct": float(args.trailing_stop_pct),
            "min_history_days": int(args.min_history_days),
        },
        "engine_config": {
            "capital": float(args.capital),
            "sizing_mode": "equal_weight",
            "max_positions": int(args.max_positions),
            "include_regime": False,
            "warmup_days": int(args.warmup_days),
        },
        "walk_forward_config": {
            "train_months": int(args.train_months),
            "test_months": int(args.test_months),
        },
        "summary": summary,
        "windows": windows,
    }

    if args.out:
        out_path = Path(args.out)
    else:
        out_dir = ROOT / "reports" / "backtests"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / (
            f"csm_walk_forward_{uni_path.stem}_{args.train_months}x{args.test_months}_"
            f"{args.start.replace('-', '')}_{args.end.replace('-', '')}_{stamp}.json"
        )

    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
