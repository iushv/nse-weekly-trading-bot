from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "bin" / "python"
REPORTS_DIR = ROOT / "reports" / "backtests"
MUTABLE_TABLES = ("trades", "portfolio_snapshots", "system_logs", "alternative_signals")


def _parse_csv_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def _parse_csv_ints(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Sweep structural runtime knobs on clean paper-trading gates.")
    p.add_argument("--base-db", default=str(ROOT / "trading_bot.db"))
    p.add_argument("--start-date", default="2026-01-16")
    p.add_argument("--end-date", default="2026-02-11")
    p.add_argument("--strategy-profile", default="tuned_momentum_v6")
    p.add_argument("--total-cost", type=float, default=0.00355)
    p.add_argument("--regime-options", default="0,1", help="CSV bool-as-int values (0/1)")
    p.add_argument("--edge-options", default="0,0.002,0.004,0.006", help="CSV floats")
    p.add_argument("--cap-options", default="3,5,10,30", help="CSV ints")
    p.add_argument("--max-combos", type=int, default=0, help="0 means all combinations")
    return p


def _reset_mutable_tables(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        for table in MUTABLE_TABLES:
            cur.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


def _run_subprocess(code: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PYTHON), "-c", code],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _simulate(env: dict[str, str], start_date: str, end_date: str) -> tuple[bool, str]:
    code = (
        "from paper_trading import PaperTradingSimulator\n"
        f"sim=PaperTradingSimulator('{start_date}','{end_date}')\n"
        "sim.run_simulation()\n"
    )
    proc = _run_subprocess(code, env)
    ok = proc.returncode == 0
    tail = "\n".join((proc.stdout + "\n" + proc.stderr).strip().splitlines()[-25:])
    return ok, tail


def _audit(env: dict[str, str]) -> tuple[bool, dict[str, Any], str]:
    code = (
        "import json\n"
        "from trading_bot.data.storage.database import db\n"
        "from trading_bot.monitoring.gate_profiles import build_audit_thresholds, resolve_go_live_profile\n"
        "from trading_bot.monitoring.performance_audit import run_weekly_audit\n"
        "profile = resolve_go_live_profile()\n"
        "thresholds = build_audit_thresholds(profile)\n"
        "res = run_weekly_audit(\n"
        "    db.engine,\n"
        "    weeks=4,\n"
        "    thresholds=thresholds,\n"
        ")\n"
        "res['gate_profile'] = profile\n"
        "print(json.dumps(res))\n"
    )
    proc = _run_subprocess(code, env)
    out = (proc.stdout or "").strip()
    tail = "\n".join((proc.stdout + "\n" + proc.stderr).strip().splitlines()[-25:])
    if proc.returncode != 0:
        return False, {}, tail
    try:
        return True, json.loads(out), tail
    except json.JSONDecodeError:
        return False, {}, tail


def _build_env(db_path: Path, strategy_profile: str, total_cost: float, regime: int, edge: float, cap: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "DATABASE_URL": f"sqlite:///{db_path}",
            "USE_LOCAL_UNIVERSE": "1",
            "MARKET_DATA_PROVIDER": "yfinance",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
            "BROKER_PROVIDER": "mock",
            "STRATEGY_PROFILE": strategy_profile,
            "TOTAL_COST_PER_TRADE": str(total_cost),
            "MOMENTUM_ENABLE_REGIME_FILTER": str(int(regime)),
            "MIN_EXPECTED_EDGE_PCT": str(edge),
            "MAX_SIGNALS_PER_DAY": str(cap),
        }
    )
    return env


def _score(item: dict[str, Any]) -> float:
    metrics = item.get("metrics", {})
    sharpe = float(metrics.get("sharpe_ratio", 0.0))
    win_rate = float(metrics.get("win_rate", 0.0))
    total_return = float(metrics.get("total_return_pct", 0.0))
    trades = int(metrics.get("closed_trades", 0))
    return (40.0 * sharpe) + (20.0 * win_rate) + total_return + min(trades, 25) * 0.2


def _safe_rate(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return float(num / den)


def _collect_funnel_analytics(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT metadata
            FROM system_logs
            WHERE module = 'signal_funnel'
              AND message = 'pre_market_signal_funnel'
            ORDER BY timestamp
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "entries": 0,
            "counts_total": {},
            "counts_avg": {},
            "rates_avg": {},
            "risk_valid_by_strategy_total": {},
        }

    totals = {
        "raw_signals": 0,
        "candidate_signals": 0,
        "edge_passed": 0,
        "ranked_selected": 0,
        "sized_candidates": 0,
        "risk_valid": 0,
    }
    rates = {
        "candidate_from_raw": 0.0,
        "edge_from_candidates": 0.0,
        "ranked_from_edge": 0.0,
        "sized_from_ranked": 0.0,
        "risk_valid_from_sized": 0.0,
    }
    strategy_totals: dict[str, int] = {}

    for row in rows:
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        counts = metadata.get("counts", {}) if isinstance(metadata.get("counts"), dict) else {}
        for key in totals:
            totals[key] += int(counts.get(key, 0))

        rates["candidate_from_raw"] += _safe_rate(float(counts.get("candidate_signals", 0)), float(counts.get("raw_signals", 0)))
        rates["edge_from_candidates"] += _safe_rate(float(counts.get("edge_passed", 0)), float(counts.get("candidate_signals", 0)))
        rates["ranked_from_edge"] += _safe_rate(float(counts.get("ranked_selected", 0)), float(counts.get("edge_passed", 0)))
        rates["sized_from_ranked"] += _safe_rate(float(counts.get("sized_candidates", 0)), float(counts.get("ranked_selected", 0)))
        rates["risk_valid_from_sized"] += _safe_rate(float(counts.get("risk_valid", 0)), float(counts.get("sized_candidates", 0)))

        by_strategy = metadata.get("by_strategy", {}) if isinstance(metadata.get("by_strategy"), dict) else {}
        risk_valid_by_strategy = (
            by_strategy.get("risk_valid", {}) if isinstance(by_strategy.get("risk_valid"), dict) else {}
        )
        for strategy, count in risk_valid_by_strategy.items():
            strategy_key = str(strategy)
            strategy_totals[strategy_key] = strategy_totals.get(strategy_key, 0) + int(count)

    entries = len(rows)
    return {
        "entries": entries,
        "counts_total": totals,
        "counts_avg": {k: float(v) / entries for k, v in totals.items()},
        "rates_avg": {k: float(v) / entries for k, v in rates.items()},
        "risk_valid_by_strategy_total": strategy_totals,
    }


def main() -> int:
    args = _build_parser().parse_args()
    base_db = Path(args.base_db).resolve()
    if not base_db.exists():
        raise FileNotFoundError(f"Base DB not found: {base_db}")
    if not PYTHON.exists():
        raise FileNotFoundError(f"Python not found: {PYTHON}")

    regime_opts = _parse_csv_ints(args.regime_options)
    edge_opts = _parse_csv_floats(args.edge_options)
    cap_opts = _parse_csv_ints(args.cap_options)

    combos: list[tuple[int, float, int]] = []
    for regime in regime_opts:
        for edge in edge_opts:
            for cap in cap_opts:
                combos.append((regime, edge, cap))
    if args.max_combos > 0:
        combos = combos[: args.max_combos]

    rows: list[dict[str, Any]] = []
    for idx, (regime, edge, cap) in enumerate(combos, start=1):
        temp_db = Path(f"/tmp/trading_bot_structural_sweep_{idx}.db")
        if temp_db.exists():
            temp_db.unlink()
        shutil.copy2(base_db, temp_db)
        _reset_mutable_tables(temp_db)

        env = _build_env(
            db_path=temp_db,
            strategy_profile=args.strategy_profile,
            total_cost=args.total_cost,
            regime=regime,
            edge=edge,
            cap=cap,
        )

        sim_ok, sim_tail = _simulate(env, args.start_date, args.end_date)
        audit_ok, audit_payload, audit_tail = _audit(env)

        row: dict[str, Any] = {
            "combo": {
                "regime_filter": bool(regime),
                "min_expected_edge_pct": edge,
                "max_signals_per_day": cap,
            },
            "simulate_ok": sim_ok,
            "audit_ok": audit_ok,
            "metrics": {},
            "gates": {},
            "ready_for_live": False,
            "gate_profile": "baseline",
            "score": -1e9,
        }
        if sim_ok and audit_ok:
            metrics = audit_payload.get("metrics", {})
            gates = audit_payload.get("gates", {})
            row["metrics"] = metrics
            row["gates"] = gates
            row["ready_for_live"] = bool(audit_payload.get("ready_for_live", False))
            row["gate_profile"] = str(audit_payload.get("gate_profile", "baseline"))
            row["exit_analysis"] = {
                "exit_reason_breakdown": metrics.get("exit_reason_breakdown", {}),
                "exit_reason_by_strategy": metrics.get("exit_reason_by_strategy", {}),
            }
            row["funnel_analysis"] = _collect_funnel_analytics(temp_db)
            row["score"] = _score(row)
        else:
            row["logs_tail"] = {"simulate": sim_tail, "audit": audit_tail}

        rows.append(row)
        status = "ok" if sim_ok and audit_ok else "fail"
        ready = row["ready_for_live"]
        sharpe = float(row.get("metrics", {}).get("sharpe_ratio", 0.0))
        win = float(row.get("metrics", {}).get("win_rate", 0.0))
        trades = int(row.get("metrics", {}).get("closed_trades", 0))
        print(
            f"[{idx}/{len(combos)}] status={status} ready={ready} regime={bool(regime)} edge={edge} "
            f"cap={cap} sharpe={sharpe:.4f} win={win:.4f} trades={trades}"
        )

    rows.sort(key=_score, reverse=True)
    payload = {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "base_db": str(base_db),
        "period": {"start_date": args.start_date, "end_date": args.end_date},
        "strategy_profile": args.strategy_profile,
        "total_cost_per_trade": args.total_cost,
        "num_combos": len(combos),
        "results": rows,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = REPORTS_DIR / f"structural_gate_sweep_{stamp}.json"
    latest_path = REPORTS_DIR / "latest_structural_gate_sweep.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Saved: {out_path}")
    print(f"Saved: {latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
