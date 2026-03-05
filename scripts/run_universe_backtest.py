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
from pathlib import Path
from typing import Any

import pandas as pd

from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.data.storage.database import db
from trading_bot.strategies.adaptive_trend_factory import build_adaptive_trend_strategy


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
    p = argparse.ArgumentParser(description="Run a continuous backtest restricted to a universe file")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--universe-file", required=True)
    p.add_argument("--capital", type=float, default=100000)
    p.add_argument(
        "--include-trades",
        action="store_true",
        help="Include per-trade details in output JSON.",
    )
    p.add_argument(
        "--no-regime",
        action="store_true",
        help="Disable market-regime computation in the backtest loop.",
    )
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

    # We need warmup history for EMAs, so pull from DB min(date) up to end.
    min_date = "2023-01-01"
    bind = {"min_date": min_date, "max_date": args.end}
    for i, sym in enumerate(sorted_uni):
        bind[f"s{i}"] = sym
    md = pd.read_sql(q, db.engine, params=bind)

    engine = BacktestEngine(initial_capital=float(args.capital))
    strategy = build_adaptive_trend_strategy(log_signals=False)
    res = engine.run_backtest(strategy, md, args.start, args.end, include_regime=(not args.no_regime))

    trades = res.get("trades", [])
    wins = [t for t in trades if float(t.get("net_pnl", 0)) > 0]
    losses = [t for t in trades if float(t.get("net_pnl", 0)) < 0]
    win_sum = sum(float(t["net_pnl"]) for t in wins)
    loss_sum_abs = abs(sum(float(t["net_pnl"]) for t in losses))
    pf = (win_sum / loss_sum_abs) if loss_sum_abs > 0 else 0.0
    avg_hold = sum(float(t.get("days_held", 0)) for t in trades) / len(trades) if trades else 0.0
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

    out = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "period": {"start": args.start, "end": args.end},
        "universe": {"file": str(uni_path), "symbols": len(universe)},
        "settings": {"include_regime": bool(not args.no_regime)},
        "metrics": {
            "total_return_pct": float(res.get("total_return_pct", 0.0)),
            "total_pnl": float(res.get("total_pnl", 0.0)),
            "sharpe_ratio": float(res.get("sharpe_ratio", 0.0)),
            "max_drawdown": float(res.get("max_drawdown", 0.0)),
            "total_trades": int(res.get("total_trades", 0)),
            "win_rate": float(res.get("win_rate", 0.0)),
            "profit_factor_closed": float(pf),
            "avg_days_held": float(avg_hold),
        },
        "regime_summary": res.get("regime_summary", {}),
        "regime_metrics": res.get("regime_metrics", {}),
        "data_quality_clean": bool(res.get("data_quality_clean", True)),
        "data_quality_warnings": res.get("data_quality_warnings", []),
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
                "entry_regime_label": str(t.get("entry_regime_label", "unknown")),
                "confidence": float(t.get("confidence", 0.0)),
                "stop_loss": float(t.get("stop_loss", 0.0)),
                "target": float(t.get("target", 0.0)),
                "mfe": float(t.get("mfe", 0.0)),
                "mae": float(t.get("mae", 0.0)),
                "metadata": _json_safe(t.get("metadata", {})),
            }
            for t in trades
        ]

    if args.out:
        out_path = Path(args.out)
    else:
        out_dir = Path("reports/backtests")
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"universe_backtest_{uni_path.stem}_{args.start.replace('-', '')}_{args.end.replace('-', '')}_{stamp}.json"

    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
