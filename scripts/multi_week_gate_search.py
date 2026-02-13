from __future__ import annotations

import argparse
import itertools
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "bin" / "python"
REPORTS_DIR = ROOT / "reports" / "backtests"
MUTABLE_TABLES = ("trades", "portfolio_snapshots", "system_logs", "alternative_signals")


def _parse_csv(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def _parse_dates(raw: str) -> list[date]:
    return [date.fromisoformat(x.strip()) for x in raw.split(",") if x.strip()]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Search configs that pass gate checks across consecutive weekly anchors.")
    p.add_argument("--base-db", default=str(ROOT / "trading_bot.db"))
    p.add_argument("--anchors", default="2026-01-22,2026-01-29,2026-02-05,2026-02-12")
    p.add_argument("--lookback-days", type=int, default=None)
    p.add_argument("--profiles", default="tuned_momentum_v4,tuned_momentum_v5,tuned_momentum_v6")
    p.add_argument("--regime-options", default="0,1")
    p.add_argument("--cap-options", default="3,5,10")
    p.add_argument("--edge-options", default="0,0.002,0.005")
    p.add_argument("--max-combos", type=int, default=0, help="0 means all combinations.")
    return p


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_adaptive_only_run() -> bool:
    return (
        _env_bool("ENABLE_ADAPTIVE_TREND", False)
        and not _env_bool("ENABLE_MOMENTUM_BREAKOUT", True)
        and not _env_bool("ENABLE_MEAN_REVERSION", True)
        and not _env_bool("ENABLE_SECTOR_ROTATION", True)
        and not _env_bool("ENABLE_BEAR_REVERSAL", False)
        and not _env_bool("ENABLE_VOLATILITY_REVERSAL", False)
    )


def _reset_mutable_tables(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        for table in MUTABLE_TABLES:
            cur.execute(f"DELETE FROM {table}")
        conn.commit()
    finally:
        conn.close()


def _run_python(code: str, env: dict[str, str], *, capture_output: bool = True) -> subprocess.CompletedProcess[str]:
    if capture_output:
        return subprocess.run(
            [str(PYTHON), "-c", code],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    return subprocess.run(
        [str(PYTHON), "-c", code],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )


def _simulate_period(env: dict[str, str], start_date: date, end_date: date) -> tuple[bool, str]:
    code = (
        "from paper_trading import PaperTradingSimulator\n"
        f"PaperTradingSimulator('{start_date.isoformat()}','{end_date.isoformat()}').run_simulation()\n"
    )
    # Simulations can emit a lot of logs; discard output to avoid subprocess buffer overhead.
    proc = _run_python(code, env, capture_output=False)
    ok = proc.returncode == 0
    tail = "" if ok else "simulation failed"
    return ok, tail


def _run_audit(env: dict[str, str], anchor: date) -> tuple[bool, dict[str, Any], str]:
    code = (
        "import json\n"
        "from datetime import date\n"
        "from trading_bot.data.storage.database import db\n"
        "from trading_bot.monitoring.gate_profiles import build_audit_thresholds, resolve_go_live_profile\n"
        "from trading_bot.monitoring.performance_audit import run_weekly_audit\n"
        f"anchor = date.fromisoformat('{anchor.isoformat()}')\n"
        "profile = resolve_go_live_profile()\n"
        "thresholds = build_audit_thresholds(profile)\n"
        "res = run_weekly_audit(\n"
        "    db.engine,\n"
        "    weeks=4,\n"
        "    thresholds=thresholds,\n"
        "    anchor_date=anchor,\n"
        ")\n"
        "res['gate_profile'] = profile\n"
        "print(json.dumps(res))\n"
    )
    proc = _run_python(code, env)
    tail = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[-20:])
    if proc.returncode != 0:
        return False, {}, tail
    raw = (proc.stdout or "").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False, {}, tail
    return True, payload, tail


def _build_env(db_path: Path, profile: str, regime: int, cap: int, edge: float) -> dict[str, str]:
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
            "TOTAL_COST_PER_TRADE": "0.00355",
            "STRATEGY_PROFILE": profile,
            "MOMENTUM_ENABLE_REGIME_FILTER": str(int(regime)),
            "MAX_SIGNALS_PER_DAY": str(int(cap)),
            "MIN_EXPECTED_EDGE_PCT": str(float(edge)),
        }
    )
    return env


def _combo_score(anchor_rows: list[dict[str, Any]]) -> float:
    if not anchor_rows:
        return -1e9
    sharpe_sum = sum(float(r["metrics"].get("sharpe_ratio", 0.0)) for r in anchor_rows)
    win_sum = sum(float(r["metrics"].get("win_rate", 0.0)) for r in anchor_rows)
    pf_sum = sum(float(r["metrics"].get("profit_factor", 0.0)) for r in anchor_rows)
    ret_sum = sum(float(r["metrics"].get("total_return_pct", 0.0)) for r in anchor_rows)
    pass_count = sum(1 for r in anchor_rows if bool(r.get("ready_for_live", False)))
    return (30.0 * sharpe_sum) + (10.0 * win_sum) + (5.0 * pf_sum) + ret_sum + (pass_count * 50.0)


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
        raise FileNotFoundError(f"Base DB missing: {base_db}")
    if args.lookback_days is not None:
        lookback_days = max(1, int(args.lookback_days))
    else:
        lookback_days = 42 if _is_adaptive_only_run() else 28

    profiles = _parse_csv(args.profiles)
    anchors = _parse_dates(args.anchors)
    regimes = [int(x) for x in _parse_csv(args.regime_options)]
    caps = [int(x) for x in _parse_csv(args.cap_options)]
    edges = [float(x) for x in _parse_csv(args.edge_options)]

    combos = list(itertools.product(profiles, regimes, caps, edges))
    if args.max_combos > 0:
        combos = combos[: args.max_combos]

    results: list[dict[str, Any]] = []
    for idx, (profile, regime, cap, edge) in enumerate(combos, start=1):
        anchor_rows: list[dict[str, Any]] = []
        all_ok = True
        for anchor in anchors:
            period_end = anchor - timedelta(days=1)
            period_start = anchor - timedelta(days=lookback_days)

            run_db = Path(f"/tmp/trading_bot_multi_week_{idx}_{anchor.isoformat()}.db")
            if run_db.exists():
                run_db.unlink()
            shutil.copy2(base_db, run_db)
            _reset_mutable_tables(run_db)

            env = _build_env(
                db_path=run_db,
                profile=profile,
                regime=regime,
                cap=cap,
                edge=edge,
            )
            sim_ok, sim_tail = _simulate_period(env, period_start, period_end)
            if not sim_ok:
                all_ok = False
                anchor_rows.append(
                    {
                        "anchor": anchor.isoformat(),
                        "ready_for_live": False,
                        "gate_profile": "baseline",
                        "simulate_ok": False,
                        "audit_ok": False,
                        "metrics": {},
                        "exit_analysis": {},
                        "funnel_analysis": _collect_funnel_analytics(run_db),
                        "errors": {"simulate_tail": sim_tail},
                    }
                )
                break

            audit_ok, audit_payload, audit_tail = _run_audit(env, anchor)
            if not audit_ok:
                all_ok = False
                anchor_rows.append(
                    {
                        "anchor": anchor.isoformat(),
                        "ready_for_live": False,
                        "gate_profile": "baseline",
                        "simulate_ok": True,
                        "audit_ok": False,
                        "metrics": {},
                        "exit_analysis": {},
                        "funnel_analysis": _collect_funnel_analytics(run_db),
                        "errors": {"audit_tail": audit_tail},
                    }
                )
                break

            ready = bool(audit_payload.get("ready_for_live", False))
            metrics = audit_payload.get("metrics", {}) if isinstance(audit_payload.get("metrics"), dict) else {}
            funnel_analysis = _collect_funnel_analytics(run_db)
            anchor_rows.append(
                {
                    "anchor": anchor.isoformat(),
                    "ready_for_live": ready,
                    "gate_profile": str(audit_payload.get("gate_profile", "baseline")),
                    "simulate_ok": True,
                    "audit_ok": True,
                    "metrics": {
                        "sharpe_ratio": float(metrics.get("sharpe_ratio", 0.0)),
                        "win_rate": float(metrics.get("win_rate", 0.0)),
                        "profit_factor": float(metrics.get("profit_factor", 0.0)),
                        "closed_trades": int(metrics.get("closed_trades", 0)),
                        "max_drawdown": float(metrics.get("max_drawdown", 0.0)),
                        "total_return_pct": float(metrics.get("total_return_pct", 0.0)),
                    },
                    "exit_analysis": {
                        "exit_reason_breakdown": metrics.get("exit_reason_breakdown", {}),
                        "exit_reason_by_strategy": metrics.get("exit_reason_by_strategy", {}),
                    },
                    "funnel_analysis": funnel_analysis,
                }
            )
            if not ready:
                all_ok = False

        pass_count = sum(1 for r in anchor_rows if bool(r.get("ready_for_live", False)))
        row = {
            "combo": {
                "strategy_profile": profile,
                "regime_filter": bool(regime),
                "max_signals_per_day": cap,
                "min_expected_edge_pct": edge,
            },
            "anchors": anchor_rows,
            "anchors_passed": pass_count,
            "all_anchors_passed": bool(all_ok and pass_count == len(anchors)),
        }
        row["score"] = _combo_score(anchor_rows)
        results.append(row)
        print(
            f"[{idx}/{len(combos)}] pass={row['all_anchors_passed']} pass_count={pass_count}/{len(anchors)} "
            f"strategy_profile={profile} regime={bool(regime)} cap={cap} edge={edge}"
        )

    results.sort(key=lambda x: float(x.get("score", -1e9)), reverse=True)
    payload = {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "base_db": str(base_db),
        "anchors": [d.isoformat() for d in anchors],
        "lookback_days": int(lookback_days),
        "num_combos": len(combos),
        "results": results,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = REPORTS_DIR / f"multi_week_gate_search_{stamp}.json"
    latest_path = REPORTS_DIR / "latest_multi_week_gate_search.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Saved: {out_path}")
    print(f"Saved: {latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
