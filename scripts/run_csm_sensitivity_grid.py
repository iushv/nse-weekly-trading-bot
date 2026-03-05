from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trading_bot.backtesting.walk_forward import WalkForwardAnalysis
from trading_bot.config.settings import Config
from trading_bot.data.storage.database import db
from trading_bot.strategies.cross_sectional_momentum import CrossSectionalMomentumStrategy


def _load_universe(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8").splitlines()
    symbols = [line.strip() for line in raw if line.strip() and not line.strip().startswith("#")]
    return [s.replace(".NS", "").upper() for s in symbols]


def _parse_csv_ints(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def _parse_csv_floats(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def _git_sha() -> str:
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return cp.stdout.strip()
    except Exception:
        return "unknown"


def _combo_key(combo: dict[str, Any]) -> str:
    return (
        f"top_n={combo['top_n']};lookback_months={combo['lookback_months']};"
        f"trailing_stop_pct={combo['trailing_stop_pct']:.4f};"
        f"crash_protection={int(bool(combo['crash_protection']))}"
    )


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _load_market_data(universe: list[str], end_date: str) -> pd.DataFrame:
    sorted_uni = sorted(set(universe))
    placeholders = ",".join([f":s{i}" for i in range(len(sorted_uni))])
    query = f"""
    SELECT symbol, date, open, high, low, close, volume
    FROM price_data
    WHERE date >= DATE(:min_date) AND date <= DATE(:max_date)
      AND symbol IN ({placeholders})
    ORDER BY date, symbol
    """
    bind: dict[str, Any] = {"min_date": "2023-01-01", "max_date": end_date}
    for i, sym in enumerate(sorted_uni):
        bind[f"s{i}"] = sym
    return pd.read_sql(query, db.engine, params=bind)


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_to_jsonable(payload), indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CSM walk-forward sensitivity grid")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--universe-file", required=True)
    parser.add_argument("--train-months", type=int, default=3)
    parser.add_argument("--test-months", type=int, default=3)
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument("--skip-recent-months", type=int, default=1)
    parser.add_argument(
        "--min-history-days",
        type=int,
        default=0,
        help="Set >0 to force a fixed minimum history; default 0 uses adaptive lookback+skip.",
    )
    parser.add_argument("--warmup-days", type=int, default=400)
    parser.add_argument("--target-vol", type=float, default=0.15)
    parser.add_argument("--min-exposure", type=float, default=0.25)
    parser.add_argument("--min-positions", type=int, default=5)
    parser.add_argument("--vol-lookback-days", type=int, default=126)
    parser.add_argument("--top-n-values", default="15,25,35")
    parser.add_argument("--lookback-values", default="3,6,9")
    parser.add_argument("--trailing-values", default="0.12,0.20")
    parser.add_argument("--crash-modes", choices=["both", "on", "off"], default="both")
    parser.add_argument("--out", default="")
    parser.add_argument("--checkpoint", default="")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    universe_file = Path(args.universe_file)
    universe = _load_universe(universe_file)
    if not universe:
        raise SystemExit(f"Universe file had no symbols: {universe_file}")

    top_n_values = _parse_csv_ints(args.top_n_values)
    lookback_values = _parse_csv_ints(args.lookback_values)
    trailing_values = _parse_csv_floats(args.trailing_values)
    if not top_n_values or not lookback_values or not trailing_values:
        raise SystemExit("Invalid grid values. Check --top-n-values/--lookback-values/--trailing-values.")

    if args.crash_modes == "both":
        crash_modes = [False, True]
    elif args.crash_modes == "on":
        crash_modes = [True]
    else:
        crash_modes = [False]

    combos: list[dict[str, Any]] = []
    for top_n, lookback, trailing, crash in product(
        top_n_values,
        lookback_values,
        trailing_values,
        crash_modes,
    ):
        combos.append(
            {
                "top_n": int(top_n),
                "lookback_months": int(lookback),
                "trailing_stop_pct": float(trailing),
                "crash_protection": bool(crash),
            }
        )

    out_dir = ROOT / "reports" / "backtests"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else out_dir / f"csm_sensitivity_grid_{stamp}.json"
    checkpoint_path = (
        Path(args.checkpoint)
        if args.checkpoint
        else out_path.with_name(f"{out_path.stem}.checkpoint.json")
    )

    completed_keys: set[str] = set()
    result_rows: list[dict[str, Any]] = []
    if checkpoint_path.exists() and not args.no_resume:
        existing = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        completed_keys = set(existing.get("completed_keys", []))
        result_rows = list(existing.get("results", []))
        print(f"Resuming from checkpoint: {checkpoint_path} ({len(completed_keys)} completed)")

    market_data = _load_market_data(universe, args.end)
    if market_data.empty:
        raise SystemExit("No market data available for the selected universe/date range.")

    total = len(combos)
    for idx, combo in enumerate(combos, start=1):
        key = _combo_key(combo)
        if key in completed_keys:
            print(f"[{idx}/{total}] skip {key} (checkpoint)")
            continue

        print(f"[{idx}/{total}] run {key}")
        lookback_months = int(combo["lookback_months"])
        adaptive_min_history = max(20, (lookback_months + int(args.skip_recent_months)) * 20)
        effective_min_history_days = (
            int(args.min_history_days) if int(args.min_history_days) > 0 else int(adaptive_min_history)
        )

        strategy = CrossSectionalMomentumStrategy(
            top_n=int(combo["top_n"]),
            lookback_months=lookback_months,
            skip_recent_months=int(args.skip_recent_months),
            trailing_stop_pct=float(combo["trailing_stop_pct"]),
            min_history_days=effective_min_history_days,
            initial_capital=float(args.capital),
            crash_protection=bool(combo["crash_protection"]),
            target_vol=float(args.target_vol),
            min_exposure=float(args.min_exposure),
            min_positions=int(args.min_positions),
            vol_lookback_days=int(args.vol_lookback_days),
            log_signals=False,
        )
        wfa = WalkForwardAnalysis(
            train_period_months=int(args.train_months),
            test_period_months=int(args.test_months),
        )

        try:
            wf = wfa.run_walk_forward(
                strategy=strategy,
                market_data=market_data,
                start_date=args.start,
                end_date=args.end,
                engine_kwargs={
                    "initial_capital": float(args.capital),
                    "sizing_mode": "equal_weight",
                    "max_positions": int(combo["top_n"]) + 5,
                },
                backtest_kwargs={
                    "include_regime": False,
                    "warmup_days": int(args.warmup_days),
                },
            )
        except Exception as exc:
            row = {
                "key": key,
                "params": combo,
                "status": "failed",
                "error": str(exc),
            }
        else:
            windows = list(wf.get("windows", []))
            summary = dict(wf.get("summary", {}))
            warning_count_total = int(sum(int(w.get("data_quality_warning_count", 0)) for w in windows))
            zero_trade_flags = [int(w.get("trades", 0)) == 0 for w in windows]
            zero_trade_consecutive = any(
                zero_trade_flags[i] and zero_trade_flags[i + 1] for i in range(max(0, len(zero_trade_flags) - 1))
            )
            row = {
                "key": key,
                "params": combo,
                "effective_min_history_days": int(effective_min_history_days),
                "status": "ok",
                "summary": {
                    "avg_return": float(summary.get("avg_return", 0.0)),
                    "avg_sharpe": float(summary.get("avg_sharpe", 0.0)),
                    "avg_max_dd": float(summary.get("avg_max_dd", 0.0)),
                    "consistency": float(summary.get("consistency", 0.0)),
                    "profitable_windows": int(summary.get("profitable_windows", 0)),
                    "total_windows": int(summary.get("total_windows", 0)),
                },
                "total_trade_count": int(sum(int(w.get("trades", 0)) for w in windows)),
                "data_quality_warning_count_total": warning_count_total,
                "zero_trade_consecutive": bool(zero_trade_consecutive),
                "windows": [
                    {
                        "window": int(w["window"]),
                        "test_start": str(pd.Timestamp(w["test_start"]).date()),
                        "test_end": str(pd.Timestamp(w["test_end"]).date()),
                        "return_pct": float(w.get("return", 0.0)),
                        "sharpe": float(w.get("sharpe", 0.0)),
                        "max_dd": float(w.get("max_dd", 0.0)),
                        "trades": int(w.get("trades", 0)),
                        "win_rate": float(w.get("win_rate", 0.0)),
                        "data_quality_warning_count": int(w.get("data_quality_warning_count", 0)),
                    }
                    for w in windows
                ],
            }

        result_rows.append(row)
        completed_keys.add(key)
        _save_json(
            checkpoint_path,
            {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "completed_keys": sorted(completed_keys),
                "results": result_rows,
            },
        )

    successful = [r for r in result_rows if r.get("status") == "ok"]
    viable = [r for r in successful if int(r.get("total_trade_count", 0)) > 0]
    ranked = sorted(
        viable,
        key=lambda r: (
            float(r["summary"]["avg_sharpe"]),
            float(r["summary"]["avg_return"]),
        ),
        reverse=True,
    )
    ranked_all = sorted(
        successful,
        key=lambda r: (
            float(r["summary"]["avg_sharpe"]),
            float(r["summary"]["avg_return"]),
        ),
        reverse=True,
    )
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank

    kill_all_below = bool(viable) and all(float(r["summary"]["avg_sharpe"]) < -0.5 for r in viable)
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "reproducibility": {
            "git_sha": _git_sha(),
            "database_url": str(Config.DATABASE_URL),
            "engine_url": str(db.engine.url),
            "python_version": sys.version,
        },
        "run_config": {
            "start": args.start,
            "end": args.end,
            "universe_file": str(universe_file),
            "universe_size": len(universe),
            "train_months": int(args.train_months),
            "test_months": int(args.test_months),
            "capital": float(args.capital),
            "skip_recent_months": int(args.skip_recent_months),
            "min_history_days": int(args.min_history_days),
            "adaptive_min_history_days": bool(int(args.min_history_days) <= 0),
            "warmup_days": int(args.warmup_days),
            "target_vol": float(args.target_vol),
            "min_exposure": float(args.min_exposure),
            "min_positions": int(args.min_positions),
            "vol_lookback_days": int(args.vol_lookback_days),
            "top_n_values": top_n_values,
            "lookback_values": lookback_values,
            "trailing_values": trailing_values,
            "crash_modes": [bool(v) for v in crash_modes],
        },
        "kill_criterion": {
            "all_avg_sharpe_below_neg_0_5": kill_all_below,
            "evaluated_configs": len(viable),
            "evaluated_configs_all_status_ok": len(successful),
            "zero_trade_configs": int(len(successful) - len(viable)),
            "total_configs": len(combos),
        },
        "results_ranked": ranked,
        "results_ranked_all": ranked_all,
        "results_all": result_rows,
    }
    _save_json(out_path, payload)
    if args.pretty:
        print(json.dumps(payload, indent=2))
    print(f"Saved grid results: {out_path}")
    print(f"Saved checkpoint: {checkpoint_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
