from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from trading_bot.backtesting.walk_forward import WalkForwardAnalysis
from trading_bot.data.storage.database import db
from trading_bot.strategies.adaptive_trend import AdaptiveTrendFollowingStrategy


def _load_universe(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8").splitlines()
    symbols = [line.strip() for line in raw if line.strip() and not line.strip().startswith("#")]
    return [s.replace(".NS", "").upper() for s in symbols]


def main() -> int:
    p = argparse.ArgumentParser(description="Walk-forward (rolling OOS windows) restricted to a universe file")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--universe-file", required=True)
    p.add_argument("--train-months", type=int, default=3)
    p.add_argument("--test-months", type=int, default=2)
    p.add_argument("--out", default="")
    args = p.parse_args()

    uni_path = Path(args.universe_file)
    universe = set(_load_universe(uni_path))
    if not universe:
        raise SystemExit(f"Universe file had no symbols: {uni_path}")

    sorted_uni = sorted(universe)
    placeholders = ",".join([f":s{i}" for i in range(len(sorted_uni))])
    q = f"""
    SELECT symbol, date, open, high, low, close, volume
    FROM price_data
    WHERE date >= DATE(:min_date) AND date <= DATE(:max_date)
      AND symbol IN ({placeholders})
    ORDER BY date, symbol
    """

    # Pull sufficient history for warmup in early windows.
    min_date = "2023-01-01"
    bind = {"min_date": min_date, "max_date": args.end}
    for i, sym in enumerate(sorted_uni):
        bind[f"s{i}"] = sym
    md = pd.read_sql(q, db.engine, params=bind)

    strategy = AdaptiveTrendFollowingStrategy(log_signals=False)
    wfa = WalkForwardAnalysis(train_period_months=int(args.train_months), test_period_months=int(args.test_months))
    results = wfa.run_walk_forward(strategy, md, args.start, args.end)

    summary = results.get("summary", {})
    # Replace NaN for JSON.
    for k, v in list(summary.items()):
        if isinstance(v, float) and v != v:
            summary[k] = None

    windows = []
    for w in results.get("windows", []):
        windows.append(
            {
                "window": int(w["window"]),
                "test_start": str(pd.Timestamp(w["test_start"]).date()),
                "test_end": str(pd.Timestamp(w["test_end"]).date()),
                "return_pct": float(w["return"]),
                "sharpe": float(w["sharpe"]),
                "max_dd": float(w["max_dd"]),
                "trades": int(w["trades"]),
                "win_rate": float(w["win_rate"]),
            }
        )

    out = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "period": {"start": args.start, "end": args.end},
        "universe": {"file": str(uni_path), "symbols": len(universe)},
        "config": {"train_months": int(args.train_months), "test_months": int(args.test_months)},
        "summary": summary,
        "windows": windows,
    }

    if args.out:
        out_path = Path(args.out)
    else:
        out_dir = Path("reports/backtests")
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / (
            f"universe_walk_forward_{uni_path.stem}_{args.train_months}x{args.test_months}_"
            f"{args.start.replace('-', '')}_{args.end.replace('-', '')}_{stamp}.json"
        )

    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
