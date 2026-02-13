from __future__ import annotations

import argparse
import json
from typing import Any

from trading_bot.config.settings import Config
from trading_bot.data.storage.database import db
from trading_bot.monitoring.audit_artifacts import write_weekly_audit_artifact
from trading_bot.monitoring.gate_profiles import build_audit_thresholds, resolve_go_live_profile
from trading_bot.monitoring.performance_audit import AuditThresholds, run_weekly_audit


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run weekly performance/go-live audit from local DB.")
    parser.add_argument("--weeks", type=int, default=4, help="Audit window in weeks (default: 4).")
    parser.add_argument(
        "--go-live-profile",
        default=Config.GO_LIVE_PROFILE,
        help="Gate profile: auto | baseline | adaptive",
    )
    parser.add_argument("--min-sharpe", type=float, default=None, help="Minimum Sharpe ratio threshold.")
    parser.add_argument("--max-drawdown", type=float, default=None, help="Maximum absolute drawdown threshold.")
    parser.add_argument("--min-win-rate", type=float, default=None, help="Minimum win-rate threshold (0-1).")
    parser.add_argument("--min-profit-factor", type=float, default=None, help="Minimum profit-factor threshold.")
    parser.add_argument("--min-closed-trades", type=int, default=None, help="Minimum closed trades in audit window.")
    parser.add_argument(
        "--max-critical-errors",
        type=int,
        default=None,
        help="Maximum ERROR/CRITICAL log entries in critical window.",
    )
    parser.add_argument(
        "--critical-window-days",
        type=int,
        default=None,
        help="Error-count lookback window (days).",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty print JSON output.")
    parser.add_argument(
        "--export-json",
        action="store_true",
        help="Write timestamped JSON artifact to output directory.",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/audits",
        help="Artifact output directory used with --export-json.",
    )
    parser.add_argument(
        "--allow-not-ready",
        action="store_true",
        help="Exit 0 even when go-live gates fail (useful for advisory reports).",
    )
    return parser


def _print_human_summary(result: dict[str, Any]) -> None:
    period = result["period"]
    metrics = result["metrics"]
    print("Weekly Performance Audit")
    print(f"Window: {period['audit_start']} -> {period['audit_end']} ({period['weeks']} weeks)")
    print(
        "Key Metrics: return={ret:.2f}% sharpe={sharpe:.2f} max_dd={dd:.2%} "
        "win_rate={wr:.2%} profit_factor={pf:.2f} closed_trades={ct} critical_errors={ce}".format(
            ret=float(metrics["total_return_pct"]),
            sharpe=float(metrics["sharpe_ratio"]),
            dd=abs(float(metrics["max_drawdown"])),
            wr=float(metrics["win_rate"]),
            pf=float(metrics.get("profit_factor", 0.0)),
            ct=int(metrics["closed_trades"]),
            ce=int(metrics["critical_error_count"]),
        )
    )
    print("Gate Results:")
    for gate_name, gate in result["gates"].items():
        flag = "PASS" if gate["passed"] else "FAIL"
        print(f"- {gate_name}: {flag} (value={gate['value']} required={gate['required']})")
    print(f"Ready For Live: {result['ready_for_live']}")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    profile = resolve_go_live_profile(args.go_live_profile)
    defaults = build_audit_thresholds(profile)
    thresholds = AuditThresholds(
        min_sharpe=float(args.min_sharpe if args.min_sharpe is not None else defaults.min_sharpe),
        max_drawdown=float(args.max_drawdown if args.max_drawdown is not None else defaults.max_drawdown),
        min_win_rate=float(args.min_win_rate if args.min_win_rate is not None else defaults.min_win_rate),
        min_profit_factor=float(
            args.min_profit_factor if args.min_profit_factor is not None else defaults.min_profit_factor
        ),
        min_closed_trades=int(
            args.min_closed_trades if args.min_closed_trades is not None else defaults.min_closed_trades
        ),
        max_critical_errors=int(
            args.max_critical_errors if args.max_critical_errors is not None else defaults.max_critical_errors
        ),
        critical_window_days=int(
            args.critical_window_days
            if args.critical_window_days is not None
            else defaults.critical_window_days
        ),
    )

    result = run_weekly_audit(
        db.engine,
        weeks=args.weeks,
        thresholds=thresholds,
    )

    _print_human_summary(result)
    print(f"Gate Profile: {profile}")
    if args.pretty:
        print("\nJSON:")
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if args.export_json:
        artifact = write_weekly_audit_artifact(result, output_dir=args.output_dir)
        print(f"Artifact: {artifact}")

    if result["ready_for_live"] or args.allow_not_ready:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
