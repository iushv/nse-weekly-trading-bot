from __future__ import annotations

import argparse
import json

from trading_bot.config.settings import Config
from trading_bot.data.storage.database import db
from trading_bot.monitoring.gate_profiles import build_audit_thresholds, resolve_go_live_profile
from trading_bot.monitoring.performance_audit import AuditThresholds
from trading_bot.monitoring.promotion_gate import run_promotion_gate


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run paper-to-live promotion gate checks and emit report bundle.")
    parser.add_argument("--weeks", type=int, default=4, help="Audit window in weeks.")
    parser.add_argument("--include-broker", action="store_true", help="Include broker read-only health check.")
    parser.add_argument(
        "--fail-on-broker",
        action="store_true",
        help="Mark preflight as degraded if broker read-only check fails.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON report.")
    parser.add_argument("--output-dir", default="reports/promotion", help="Promotion report bundle directory.")
    parser.add_argument(
        "--allow-not-ready",
        action="store_true",
        help="Return exit code 0 even when promotion gate fails.",
    )
    parser.add_argument(
        "--go-live-profile",
        default=Config.GO_LIVE_PROFILE,
        help="Gate profile: auto | baseline | adaptive",
    )
    parser.add_argument("--min-sharpe", type=float, default=None)
    parser.add_argument("--max-drawdown", type=float, default=None)
    parser.add_argument("--min-win-rate", type=float, default=None)
    parser.add_argument("--min-profit-factor", type=float, default=None)
    parser.add_argument("--min-closed-trades", type=int, default=None)
    parser.add_argument("--max-critical-errors", type=int, default=None)
    parser.add_argument("--critical-window-days", type=int, default=None)
    return parser


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

    report = run_promotion_gate(
        db.engine,
        weeks=args.weeks,
        thresholds=thresholds,
        include_broker=args.include_broker,
        fail_on_broker=args.fail_on_broker,
        write_bundle=True,
        output_dir=args.output_dir,
    )

    summary = report["summary"]
    print("Promotion Checklist")
    print(f"Gate Profile: {profile}")
    print(f"Preflight: {summary['preflight_status']}")
    print(f"Weekly Audit Ready: {summary['weekly_audit_ready']}")
    print(f"Ready For Live: {summary['ready_for_live']}")
    if summary.get("failed_gates"):
        print(f"Failed Gates: {', '.join(summary['failed_gates'])}")
    if summary.get("bundle_path"):
        print(f"Bundle: {summary['bundle_path']}")

    if args.pretty:
        print("\nJSON:")
        print(json.dumps(report, indent=2, sort_keys=True, default=str))

    if report["ready_for_live"] or args.allow_not_ready:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
