from __future__ import annotations

import argparse
import concurrent.futures
import itertools
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKTEST_SCRIPT = ROOT / "scripts" / "run_universe_backtest.py"
WALK_FORWARD_SCRIPT = ROOT / "scripts" / "run_universe_walk_forward.py"
REPORTS_DIR = ROOT / "reports" / "backtests"


def _parse_csv_floats(raw: str) -> list[float]:
    return [float(part.strip()) for part in raw.split(",") if part.strip()]


def _log(message: str) -> None:
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {message}", flush=True)


def _normalize_path_like(value: str) -> str:
    out = value.replace("\\", "/").strip().lower()
    if out.startswith("./"):
        out = out[2:]
    return out


def _same_path_like(left: str, right: str) -> bool:
    return _normalize_path_like(left) == _normalize_path_like(right)


def _format_overrides(env_overrides: dict[str, str]) -> str:
    if not env_overrides:
        return "default"
    return ", ".join(f"{k}={v}" for k, v in sorted(env_overrides.items()))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to read JSON: {path}") from exc


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _contexts_compatible(existing: dict[str, Any], current: dict[str, Any]) -> bool:
    optional_keys = {"max_workers"}
    normalized_existing = {k: v for k, v in existing.items() if k not in optional_keys}
    normalized_current = {k: v for k, v in current.items() if k not in optional_keys}
    return normalized_existing == normalized_current


def _run_python(
    cmd: list[str],
    env_overrides: dict[str, str] | None = None,
    *,
    task_label: str,
    heartbeat_sec: int,
    log_path: Path,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    if env_overrides:
        env.update(env_overrides)

    full_cmd = [sys.executable, *cmd]
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            full_cmd,
            cwd=str(ROOT),
            text=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )

        started = time.perf_counter()
        heartbeat_at = started + max(heartbeat_sec, 0)

        while proc.poll() is None:
            if heartbeat_sec > 0:
                now = time.perf_counter()
                if now >= heartbeat_at:
                    _log(f"{task_label}: still running ({int(now - started)}s elapsed)")
                    heartbeat_at = now + heartbeat_sec
            time.sleep(1)
        proc.wait()

    return subprocess.CompletedProcess(
        args=full_cmd,
        returncode=int(proc.returncode),
        stdout="",
        stderr="",
    )


def _tail_file(path: Path, lines: int = 40) -> str:
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return "\n".join(content.strip().splitlines()[-lines:])


def _validate_backtest_payload(
    payload: dict[str, Any],
    *,
    label: str,
    expected_start: str,
    expected_end: str,
    expected_universe_file: str,
    expected_include_regime: bool,
) -> None:
    period = payload.get("period", {}) if isinstance(payload.get("period"), dict) else {}
    actual_start = str(period.get("start", ""))
    actual_end = str(period.get("end", ""))
    if actual_start != expected_start or actual_end != expected_end:
        raise ValueError(
            f"Resume artifact mismatch for {label}: period {actual_start}..{actual_end} "
            f"!= expected {expected_start}..{expected_end}"
        )

    universe = payload.get("universe", {}) if isinstance(payload.get("universe"), dict) else {}
    actual_universe = str(universe.get("file", ""))
    if actual_universe and not _same_path_like(actual_universe, expected_universe_file):
        raise ValueError(
            f"Resume artifact mismatch for {label}: universe {actual_universe} != expected {expected_universe_file}"
        )

    settings = payload.get("settings", {}) if isinstance(payload.get("settings"), dict) else {}
    actual_include_regime = bool(settings.get("include_regime", True))
    if actual_include_regime != expected_include_regime:
        raise ValueError(
            f"Resume artifact mismatch for {label}: include_regime {actual_include_regime} "
            f"!= expected {expected_include_regime}"
        )


def _validate_walk_forward_payload(
    payload: dict[str, Any],
    *,
    label: str,
    expected_start: str,
    expected_end: str,
    expected_universe_file: str,
    expected_train_months: int,
    expected_test_months: int,
) -> None:
    period = payload.get("period", {}) if isinstance(payload.get("period"), dict) else {}
    actual_start = str(period.get("start", ""))
    actual_end = str(period.get("end", ""))
    if actual_start != expected_start or actual_end != expected_end:
        raise ValueError(
            f"Resume artifact mismatch for {label}: period {actual_start}..{actual_end} "
            f"!= expected {expected_start}..{expected_end}"
        )

    universe = payload.get("universe", {}) if isinstance(payload.get("universe"), dict) else {}
    actual_universe = str(universe.get("file", ""))
    if actual_universe and not _same_path_like(actual_universe, expected_universe_file):
        raise ValueError(
            f"Resume artifact mismatch for {label}: universe {actual_universe} != expected {expected_universe_file}"
        )

    config = payload.get("config", {}) if isinstance(payload.get("config"), dict) else {}
    actual_train = int(config.get("train_months", 0) or 0)
    actual_test = int(config.get("test_months", 0) or 0)
    if actual_train != expected_train_months or actual_test != expected_test_months:
        raise ValueError(
            f"Resume artifact mismatch for {label}: train/test {actual_train}/{actual_test} "
            f"!= expected {expected_train_months}/{expected_test_months}"
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
    heartbeat_sec: int,
) -> dict[str, Any]:
    out_path = run_dir / f"{label}.json"
    log_path = run_dir / f"{label}.log"
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
    started = time.perf_counter()
    proc = _run_python(
        cmd,
        env_overrides=env_overrides,
        task_label=label,
        heartbeat_sec=heartbeat_sec,
        log_path=log_path,
    )
    elapsed = time.perf_counter() - started
    if proc.returncode != 0:
        tail = _tail_file(log_path, lines=40)
        raise RuntimeError(f"Backtest failed for {label}\n{tail}")
    payload = _read_json(out_path)
    _validate_backtest_payload(
        payload,
        label=label,
        expected_start=start,
        expected_end=end,
        expected_universe_file=universe_file,
        expected_include_regime=not no_regime,
    )
    return {
        "label": label,
        "start": start,
        "end": end,
        "artifact": str(out_path.relative_to(ROOT)),
        "env_overrides": dict(env_overrides),
        "metrics": _extract_metrics(payload),
        "elapsed_sec": float(elapsed),
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
    heartbeat_sec: int,
) -> dict[str, Any]:
    out_path = run_dir / f"{label}_walk_forward.json"
    log_path = run_dir / f"{label}_walk_forward.log"
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
    started = time.perf_counter()
    proc = _run_python(
        cmd,
        env_overrides=env_overrides,
        task_label=label,
        heartbeat_sec=heartbeat_sec,
        log_path=log_path,
    )
    elapsed = time.perf_counter() - started
    if proc.returncode != 0:
        tail = _tail_file(log_path, lines=40)
        raise RuntimeError(f"Walk-forward failed for {label}\n{tail}")
    payload = _read_json(out_path)
    _validate_walk_forward_payload(
        payload,
        label=label,
        expected_start=start,
        expected_end=end,
        expected_universe_file=universe_file,
        expected_train_months=train_months,
        expected_test_months=test_months,
    )
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
        "elapsed_sec": float(elapsed),
    }


def _run_or_resume_universe_backtest(
    *,
    step_index: int,
    total_steps: int,
    label: str,
    start: str,
    end: str,
    universe_file: str,
    capital: float,
    no_regime: bool,
    env_overrides: dict[str, str],
    run_dir: Path,
    heartbeat_sec: int,
) -> dict[str, Any]:
    out_path = run_dir / f"{label}.json"
    meta_path = run_dir / f"{label}.meta.json"
    step_tag = f"[{step_index:02d}/{total_steps:02d}] {label}"
    expected_meta = {
        "label": label,
        "start": start,
        "end": end,
        "universe_file": universe_file,
        "include_regime": bool(not no_regime),
        "env_overrides": dict(env_overrides),
    }

    if out_path.exists():
        if meta_path.exists():
            existing_meta = _read_json(meta_path)
            if existing_meta != expected_meta:
                raise ValueError(
                    f"Resume metadata mismatch for {label} in {meta_path}. "
                    "Start a fresh run or use matching parameters."
                )
        payload = _read_json(out_path)
        _validate_backtest_payload(
            payload,
            label=label,
            expected_start=start,
            expected_end=end,
            expected_universe_file=universe_file,
            expected_include_regime=not no_regime,
        )
        run = {
            "label": label,
            "start": start,
            "end": end,
            "artifact": str(out_path.relative_to(ROOT)),
            "env_overrides": dict(env_overrides),
            "metrics": _extract_metrics(payload),
            "elapsed_sec": 0.0,
            "resumed": True,
        }
        _log(
            f"{step_tag}: resumed existing artifact "
            f"(sharpe={run['metrics']['sharpe']:.4f}, pf={run['metrics']['pf']:.4f}, "
            f"trades={int(run['metrics']['trades'])})"
        )
        return run

    _log(
        f"{step_tag}: running backtest {start}..{end} | "
        f"overrides={_format_overrides(env_overrides)}"
    )
    run = _run_universe_backtest(
        label=label,
        start=start,
        end=end,
        universe_file=universe_file,
        capital=capital,
        no_regime=no_regime,
        env_overrides=env_overrides,
        run_dir=run_dir,
        heartbeat_sec=heartbeat_sec,
    )
    _write_json(meta_path, expected_meta)
    run["resumed"] = False
    _log(
        f"{step_tag}: completed in {run['elapsed_sec']:.1f}s "
        f"(sharpe={run['metrics']['sharpe']:.4f}, pf={run['metrics']['pf']:.4f}, "
        f"trades={int(run['metrics']['trades'])})"
    )
    return run


def _run_or_resume_walk_forward(
    *,
    step_index: int,
    total_steps: int,
    label: str,
    start: str,
    end: str,
    universe_file: str,
    train_months: int,
    test_months: int,
    env_overrides: dict[str, str],
    run_dir: Path,
    heartbeat_sec: int,
) -> dict[str, Any]:
    out_path = run_dir / f"{label}_walk_forward.json"
    meta_path = run_dir / f"{label}_walk_forward.meta.json"
    step_tag = f"[{step_index:02d}/{total_steps:02d}] {label}_walk_forward"
    expected_meta = {
        "label": f"{label}_walk_forward",
        "start": start,
        "end": end,
        "universe_file": universe_file,
        "train_months": int(train_months),
        "test_months": int(test_months),
        "env_overrides": dict(env_overrides),
    }

    if out_path.exists():
        if meta_path.exists():
            existing_meta = _read_json(meta_path)
            if existing_meta != expected_meta:
                raise ValueError(
                    f"Resume metadata mismatch for {label}_walk_forward in {meta_path}. "
                    "Start a fresh run or use matching parameters."
                )
        payload = _read_json(out_path)
        _validate_walk_forward_payload(
            payload,
            label=f"{label}_walk_forward",
            expected_start=start,
            expected_end=end,
            expected_universe_file=universe_file,
            expected_train_months=train_months,
            expected_test_months=test_months,
        )
        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        run = {
            "artifact": str(out_path.relative_to(ROOT)),
            "summary": {
                "avg_return": float(summary.get("avg_return", 0.0) or 0.0),
                "avg_sharpe": float(summary.get("avg_sharpe", 0.0) or 0.0),
                "avg_max_dd": float(summary.get("avg_max_dd", 0.0) or 0.0),
                "consistency": float(summary.get("consistency", 0.0) or 0.0),
                "total_windows": int(summary.get("total_windows", 0) or 0),
            },
            "elapsed_sec": 0.0,
            "resumed": True,
        }
        _log(
            f"{step_tag}: resumed existing artifact "
            f"(avg_sharpe={run['summary']['avg_sharpe']:.4f}, windows={run['summary']['total_windows']})"
        )
        return run

    _log(
        f"{step_tag}: running walk-forward {start}..{end} "
        f"(train={train_months}m, test={test_months}m) | overrides={_format_overrides(env_overrides)}"
    )
    run = _run_walk_forward(
        label=label,
        start=start,
        end=end,
        universe_file=universe_file,
        train_months=train_months,
        test_months=test_months,
        env_overrides=env_overrides,
        run_dir=run_dir,
        heartbeat_sec=heartbeat_sec,
    )
    _write_json(meta_path, expected_meta)
    run["resumed"] = False
    _log(
        f"{step_tag}: completed in {run['elapsed_sec']:.1f}s "
        f"(avg_sharpe={run['summary']['avg_sharpe']:.4f}, windows={run['summary']['total_windows']})"
    )
    return run


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
    p.add_argument(
        "--max-workers",
        type=int,
        default=max(1, min(8, int(os.cpu_count() or 1))),
        help="Parallel workers for factorial runs (run02-run09).",
    )
    p.add_argument("--resume-dir", default="", help="Resume an existing run directory (e.g. reports/backtests/step9_factorial_YYYYMMDD_HHMMSS)")
    p.add_argument(
        "--assume-legacy-context",
        action="store_true",
        help="Allow adopting a resume directory that has run artifacts but no run_context.json (use only when args exactly match the original run)",
    )
    p.add_argument("--heartbeat-sec", type=int, default=60, help="Print per-step heartbeat every N seconds while child scripts run (0 disables)")
    p.add_argument("--out", default="")
    return p


def main() -> int:
    args = _build_parser().parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    max_atr_values = _parse_csv_floats(args.max_weekly_atr_pct_values)
    max_loss_values = _parse_csv_floats(args.max_loss_per_trade_values)
    stop_mult_values = _parse_csv_floats(args.stop_atr_mult_values)
    combos = list(itertools.product(max_atr_values, max_loss_values, stop_mult_values))
    if len(combos) != 8:
        raise ValueError("Expected exactly 8 factorial combinations (2x2x2).")

    if args.resume_dir:
        run_dir = Path(args.resume_dir)
        if not run_dir.is_absolute():
            run_dir = ROOT / run_dir
        run_dir = run_dir.resolve()
        if not run_dir.exists():
            raise FileNotFoundError(f"--resume-dir does not exist: {run_dir}")
        _log(f"Resuming Step 9 run directory: {run_dir}")
    else:
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        run_dir = REPORTS_DIR / f"step9_factorial_{stamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        _log(f"Created Step 9 run directory: {run_dir}")

    run_dir.mkdir(parents=True, exist_ok=True)

    run_context = {
        "start": args.start,
        "end": args.end,
        "holdout_start": args.holdout_start,
        "holdout_end": args.holdout_end,
        "wf_start": args.wf_start,
        "wf_end": args.wf_end,
        "universe_file": args.universe_file,
        "capital": float(args.capital),
        "train_months": int(args.train_months),
        "test_months": int(args.test_months),
        "no_regime": bool(args.no_regime),
        "factor_values": {
            "ADAPTIVE_TREND_MAX_WEEKLY_ATR_PCT": max_atr_values,
            "MAX_LOSS_PER_TRADE": max_loss_values,
            "ADAPTIVE_TREND_STOP_ATR_MULT": stop_mult_values,
        },
        "max_workers": max(1, int(args.max_workers)),
    }
    run_context_path = run_dir / "run_context.json"
    if run_context_path.exists():
        existing_context = _read_json(run_context_path)
        if not _contexts_compatible(existing_context, run_context):
            raise ValueError(
                "run_context.json mismatch for resume-dir. Use matching arguments or start a fresh run.\n"
                f"run_dir={run_dir}"
            )
    else:
        existing_run_files = list(run_dir.glob("run*.json"))
        if args.resume_dir and existing_run_files and not args.assume_legacy_context:
            raise ValueError(
                "resume-dir contains run artifacts but no run_context.json. "
                "To avoid mismatched resume parameters, rerun with --assume-legacy-context "
                "only if your arguments exactly match the original run."
            )
        _write_json(run_context_path, run_context)
        if args.resume_dir and existing_run_files and args.assume_legacy_context:
            _log(
                "Adopted legacy resume directory without run_context.json; "
                "wrote run_context.json from current arguments."
            )
        else:
            _log(f"Wrote run context: {run_context_path.relative_to(ROOT)}")

    total_steps = 12
    _log(
        f"Step 9 cycle started (budget={total_steps}, no_regime={bool(args.no_regime)}, "
        f"factors={len(max_atr_values)}x{len(max_loss_values)}x{len(stop_mult_values)}, "
        f"max_workers={max(1, int(args.max_workers))})"
    )

    runs: list[dict[str, Any]] = []
    resumed_steps = 0

    baseline = _run_or_resume_universe_backtest(
        step_index=1,
        total_steps=total_steps,
        label="run01_baseline",
        start=args.start,
        end=args.end,
        universe_file=args.universe_file,
        capital=args.capital,
        no_regime=args.no_regime,
        env_overrides={},
        run_dir=run_dir,
        heartbeat_sec=args.heartbeat_sec,
    )
    runs.append(baseline)
    resumed_steps += int(bool(baseline.get("resumed")))
    baseline_stop_loss = baseline["metrics"]["stop_loss_total_pnl"]

    candidates: list[dict[str, Any]] = []
    workers = max(1, int(args.max_workers))
    factorial_specs: list[tuple[int, dict[str, str]]] = []
    for idx, (max_atr_pct, max_loss, stop_mult) in enumerate(combos, start=2):
        overrides = {
            "ADAPTIVE_TREND_MAX_WEEKLY_ATR_PCT": str(max_atr_pct),
            "MAX_LOSS_PER_TRADE": str(max_loss),
            "ADAPTIVE_TREND_STOP_ATR_MULT": str(stop_mult),
        }
        factorial_specs.append((idx, overrides))

    _log(f"Launching factorial runs in parallel: workers={workers}, tasks={len(factorial_specs)}")
    factorial_results: dict[int, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_idx = {
            executor.submit(
                _run_or_resume_universe_backtest,
                step_index=idx,
                total_steps=total_steps,
                label=f"run{idx:02d}_factorial",
                start=args.start,
                end=args.end,
                universe_file=args.universe_file,
                capital=args.capital,
                no_regime=args.no_regime,
                env_overrides=overrides,
                run_dir=run_dir,
                heartbeat_sec=args.heartbeat_sec,
            ): idx
            for idx, overrides in factorial_specs
        }
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            factorial_results[idx] = future.result()

    for idx, _overrides in sorted(factorial_specs, key=lambda item: item[0]):
        run = factorial_results[idx]
        gate_failures = _gate_failures(run["metrics"], baseline_stop_loss)
        run["gate_failures"] = gate_failures
        run["passed_gates"] = not gate_failures
        runs.append(run)
        resumed_steps += int(bool(run.get("resumed")))
        candidates.append(run)

    passing = [r for r in candidates if r.get("passed_gates")]
    ranked_pool = passing if passing else candidates
    ranked = sorted(ranked_pool, key=_rank_key)
    best = ranked[0]
    _log(
        "Selected best candidate: "
        f"{best['label']} | sharpe={best['metrics']['sharpe']:.4f}, "
        f"pf={best['metrics']['pf']:.4f}, trades={int(best['metrics']['trades'])}, "
        f"overrides={_format_overrides(best['env_overrides'])}"
    )

    retest = _run_or_resume_universe_backtest(
        step_index=10,
        total_steps=total_steps,
        label="run10_retest_best",
        start=args.start,
        end=args.end,
        universe_file=args.universe_file,
        capital=args.capital,
        no_regime=args.no_regime,
        env_overrides=best["env_overrides"],
        run_dir=run_dir,
        heartbeat_sec=args.heartbeat_sec,
    )
    runs.append(retest)
    resumed_steps += int(bool(retest.get("resumed")))

    holdout = _run_or_resume_universe_backtest(
        step_index=11,
        total_steps=total_steps,
        label="run11_holdout_best",
        start=args.holdout_start,
        end=args.holdout_end,
        universe_file=args.universe_file,
        capital=args.capital,
        no_regime=args.no_regime,
        env_overrides=best["env_overrides"],
        run_dir=run_dir,
        heartbeat_sec=args.heartbeat_sec,
    )
    runs.append(holdout)
    resumed_steps += int(bool(holdout.get("resumed")))

    walk = _run_or_resume_walk_forward(
        step_index=12,
        total_steps=total_steps,
        label="run12_best",
        start=args.wf_start,
        end=args.wf_end,
        universe_file=args.universe_file,
        train_months=args.train_months,
        test_months=args.test_months,
        env_overrides=best["env_overrides"],
        run_dir=run_dir,
        heartbeat_sec=args.heartbeat_sec,
    )
    resumed_steps += int(bool(walk.get("resumed")))

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
        "run_dir": str(run_dir.relative_to(ROOT)),
        "resumed_steps": int(resumed_steps),
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
            "max_workers": workers,
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

    _log(
        "Decision checks: "
        + ", ".join(f"{k}={'PASS' if bool(v) else 'FAIL'}" for k, v in decision_checks.items())
        + f" | accepted={bool(accepted)}"
    )

    if args.out:
        out_path = Path(args.out)
    else:
        out_path = run_dir / "summary.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))
    _log(f"Saved summary: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
