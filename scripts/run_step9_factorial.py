from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKTEST_SCRIPT = ROOT / "scripts" / "run_universe_backtest.py"
WALK_FORWARD_SCRIPT = ROOT / "scripts" / "run_universe_walk_forward.py"
REPORTS_DIR = ROOT / "reports" / "backtests"


def _parse_csv_floats(raw: str) -> list[float]:
    return [float(part.strip()) for part in raw.split(",") if part.strip()]


def _run_python(cmd: list[str], env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, *cmd],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _extract_metrics(payload: dict[str, Any]) -> dict[str, float]:
    metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {}
    exit_breakdown = payload.get("exit_breakdown", {}) if isinstance(payload.get("exit_breakdown"), dict) else {}
    stop_loss = exit_breakdown.get("STOP_LOSS", {}) if isinstance(exit_breakdown.get("STOP_LOSS"), dict) else {}
    return {
        "sharpe": float(metrics.get("sharpe_ratio", 0.0)),
        "pf": float(metrics.get("profit_factor_closed", 0.0)),
        "trades": float(metrics.get("total_trades", 0.0)),
        "max_dd": float(metrics.get("max_drawdown", 0.0)),
        "total_pnl": float(metrics.get("total_pnl", 0.0)),
        "stop_loss_total_pnl": float(stop_loss.get("total_pnl", 0.0)),
    }


def _gate_failures(candidate: dict[str, float], baseline_stop_loss: float) -> list[str]:
    failures: list[str] = []
    if candidate["pf"] < 0.85:
        failures.append("pf_below_0.85")
    if candidate["sharpe"] < -0.30:
        failures.append("sharpe_below_-0.30")
    if candidate["trades"] < 40 or candidate["trades"] > 70:
        failures.append("trades_outside_40_70")
    if baseline_stop_loss < 0:
        worst_allowed = baseline_stop_loss * 1.2
        if candidate["stop_loss_total_pnl"] < worst_allowed:
            failures.append("stop_loss_pnl_worse_than_20pct_vs_baseline")
    return failures


def _rank_key(run: dict[str, Any]) -> tuple[float, float, float, float]:
    m = run["metrics"]
    return (
        -float(m["pf"]),
        -float(m["sharpe"]),
        abs(float(m["max_dd"])),
        -float(m["total_pnl"]),
    )


def _run_universe_backtest(
    *,
    label: str,
    start: str,
    end: str,
    universe_file: str,
    capital: float,
    no_regime: bool,
    env_overrides: dict[str, str],
    run_dir: Path,
) -> dict[str, Any]:
    out_path = run_dir / f"{label}.json"
    cmd = [
        str(BACKTEST_SCRIPT),
        "--start",
        start,
        "--end",
        end,
        "--universe-file",
        universe_file,
        "--capital",
        str(capital),
        "--out",
        str(out_path),
    ]
    if no_regime:
        cmd.append("--no-regime")
    proc = _run_python(cmd, env_overrides=env_overrides)
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + "\n" + proc.stderr).strip().splitlines()[-40:])
        raise RuntimeError(f"Backtest failed for {label}\n{tail}")
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    return {
        "label": label,
        "start": start,
        "end": end,
        "artifact": str(out_path.relative_to(ROOT)),
        "env_overrides": dict(env_overrides),
        "metrics": _extract_metrics(payload),
    }


def _run_walk_forward(
    *,
    label: str,
    start: str,
    end: str,
    universe_file: str,
    train_months: int,
    test_months: int,
    env_overrides: dict[str, str],
    run_dir: Path,
) -> dict[str, Any]:
    out_path = run_dir / f"{label}_walk_forward.json"
    cmd = [
        str(WALK_FORWARD_SCRIPT),
        "--start",
        start,
        "--end",
        end,
        "--universe-file",
        universe_file,
        "--train-months",
        str(train_months),
        "--test-months",
        str(test_months),
        "--out",
        str(out_path),
    ]
    proc = _run_python(cmd, env_overrides=env_overrides)
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + "\n" + proc.stderr).strip().splitlines()[-40:])
        raise RuntimeError(f"Walk-forward failed for {label}\n{tail}")
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    return {
        "artifact": str(out_path.relative_to(ROOT)),
        "summary": {
            "avg_return": float(summary.get("avg_return", 0.0) or 0.0),
            "avg_sharpe": float(summary.get("avg_sharpe", 0.0) or 0.0),
            "avg_max_dd": float(summary.get("avg_max_dd", 0.0) or 0.0),
            "consistency": float(summary.get("consistency", 0.0) or 0.0),
            "total_windows": int(summary.get("total_windows", 0) or 0),
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run Step-9 constrained factorial optimization (PF-first, 12-run budget).")
    p.add_argument("--start", default="2025-08-01")
    p.add_argument("--end", default="2026-02-20")
    p.add_argument("--holdout-start", default="2025-04-01")
    p.add_argument("--holdout-end", default="2025-07-31")
    p.add_argument("--wf-start", default="2024-01-01")
    p.add_argument("--wf-end", default="2026-02-20")
    p.add_argument("--universe-file", default="data/universe/nifty_midcap150.txt")
    p.add_argument("--capital", type=float, default=100000.0)
    p.add_argument("--train-months", type=int, default=3)
    p.add_argument("--test-months", type=int, default=3)
    p.add_argument("--no-regime", action="store_true")
    p.add_argument("--max-weekly-atr-pct-values", default="0.06,0.08")
    p.add_argument("--max-loss-per-trade-values", default="0.0,0.008")
    p.add_argument("--stop-atr-mult-values", default="1.3,1.5")
    p.add_argument("--out", default="")
    return p


def main() -> int:
    args = _build_parser().parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = REPORTS_DIR / f"step9_factorial_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    max_atr_values = _parse_csv_floats(args.max_weekly_atr_pct_values)
    max_loss_values = _parse_csv_floats(args.max_loss_per_trade_values)
    stop_mult_values = _parse_csv_floats(args.stop_atr_mult_values)
    combos = list(itertools.product(max_atr_values, max_loss_values, stop_mult_values))
    if len(combos) != 8:
        raise ValueError("Expected exactly 8 factorial combinations (2x2x2).")

    runs: list[dict[str, Any]] = []
    baseline = _run_universe_backtest(
        label="run01_baseline",
        start=args.start,
        end=args.end,
        universe_file=args.universe_file,
        capital=args.capital,
        no_regime=args.no_regime,
        env_overrides={},
        run_dir=run_dir,
    )
    runs.append(baseline)
    baseline_stop_loss = baseline["metrics"]["stop_loss_total_pnl"]

    candidates: list[dict[str, Any]] = []
    for idx, (max_atr_pct, max_loss, stop_mult) in enumerate(combos, start=2):
        overrides = {
            "ADAPTIVE_TREND_MAX_WEEKLY_ATR_PCT": str(max_atr_pct),
            "MAX_LOSS_PER_TRADE": str(max_loss),
            "ADAPTIVE_TREND_STOP_ATR_MULT": str(stop_mult),
        }
        run = _run_universe_backtest(
            label=f"run{idx:02d}_factorial",
            start=args.start,
            end=args.end,
            universe_file=args.universe_file,
            capital=args.capital,
            no_regime=args.no_regime,
            env_overrides=overrides,
            run_dir=run_dir,
        )
        gate_failures = _gate_failures(run["metrics"], baseline_stop_loss)
        run["gate_failures"] = gate_failures
        run["passed_gates"] = not gate_failures
        runs.append(run)
        candidates.append(run)

    passing = [r for r in candidates if r.get("passed_gates")]
    ranked_pool = passing if passing else candidates
    ranked = sorted(ranked_pool, key=_rank_key)
    best = ranked[0]

    retest = _run_universe_backtest(
        label="run10_retest_best",
        start=args.start,
        end=args.end,
        universe_file=args.universe_file,
        capital=args.capital,
        no_regime=args.no_regime,
        env_overrides=best["env_overrides"],
        run_dir=run_dir,
    )
    runs.append(retest)

    holdout = _run_universe_backtest(
        label="run11_holdout_best",
        start=args.holdout_start,
        end=args.holdout_end,
        universe_file=args.universe_file,
        capital=args.capital,
        no_regime=args.no_regime,
        env_overrides=best["env_overrides"],
        run_dir=run_dir,
    )
    runs.append(holdout)

    walk = _run_walk_forward(
        label="run12_best",
        start=args.wf_start,
        end=args.wf_end,
        universe_file=args.universe_file,
        train_months=args.train_months,
        test_months=args.test_months,
        env_overrides=best["env_overrides"],
        run_dir=run_dir,
    )

    decision_checks = {
        "in_sample_pf_ge_1": float(best["metrics"]["pf"]) >= 1.0,
        "in_sample_sharpe_gt_0": float(best["metrics"]["sharpe"]) > 0.0,
        "in_sample_max_dd_not_worse_1p5pp": float(best["metrics"]["max_dd"]) >= (float(baseline["metrics"]["max_dd"]) - 0.015),
        "holdout_pf_ge_0_95": float(holdout["metrics"]["pf"]) >= 0.95,
        "walk_forward_avg_sharpe_gt_0": float(walk["summary"]["avg_sharpe"]) > 0.0,
    }
    accepted = all(bool(v) for v in decision_checks.values())

    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "objective": "pf_first",
        "run_budget": 12,
        "config": {
            "start": args.start,
            "end": args.end,
            "holdout_start": args.holdout_start,
            "holdout_end": args.holdout_end,
            "wf_start": args.wf_start,
            "wf_end": args.wf_end,
            "universe_file": args.universe_file,
            "capital": args.capital,
            "no_regime": bool(args.no_regime),
            "factor_values": {
                "ADAPTIVE_TREND_MAX_WEEKLY_ATR_PCT": max_atr_values,
                "MAX_LOSS_PER_TRADE": max_loss_values,
                "ADAPTIVE_TREND_STOP_ATR_MULT": stop_mult_values,
            },
        },
        "baseline": baseline,
        "ranked_candidates": ranked,
        "selected_best": best,
        "retest_best": retest,
        "holdout_best": holdout,
        "walk_forward_best": walk,
        "decision_checks": decision_checks,
        "accepted": accepted,
        "runs": runs,
    }

    if args.out:
        out_path = Path(args.out)
    else:
        out_path = run_dir / "summary.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
