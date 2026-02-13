from __future__ import annotations

import argparse
import json

from trading_bot.monitoring.audit_trend import load_weekly_audits, summarize_audit_trend, write_trend_artifact


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize weekly audit trend and drift alerts.")
    parser.add_argument("--audit-dir", default="reports/audits", help="Directory containing weekly_audit_*.json artifacts.")
    parser.add_argument("--lookback", type=int, default=8, help="How many most-recent audit artifacts to summarize.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print full JSON summary.")
    parser.add_argument("--export-json", action="store_true", help="Write trend summary artifact to disk.")
    parser.add_argument("--output-dir", default="reports/audits/trends", help="Output directory for trend artifacts.")
    parser.add_argument("--allow-empty", action="store_true", help="Return exit code 0 when no audit artifacts exist.")
    parser.add_argument("--fail-on-alert", action="store_true", help="Return exit code 1 if drift alerts indicate attention is needed.")
    return parser


def _print_summary(result: dict) -> None:
    print("Weekly Audit Trend")
    print(f"Records considered: {result['records_considered']} (lookback={result['lookback']})")

    latest = result.get("latest")
    if not latest:
        print("No audit artifacts found")
        return

    print(
        "Latest: end={end} sharpe={sharpe:.2f} drawdown={dd:.2%} win_rate={wr:.2%} "
        "critical_errors={ce} ready={ready}".format(
            end=latest.get("audit_end", ""),
            sharpe=float(latest.get("sharpe_ratio", 0.0)),
            dd=float(latest.get("max_drawdown_abs", 0.0)),
            wr=float(latest.get("win_rate", 0.0)),
            ce=int(latest.get("critical_error_count", 0)),
            ready=bool(latest.get("ready_for_live", False)),
        )
    )
    trend = result.get("trend", {})
    if isinstance(trend, dict):
        print(
            "Waiver Fire Rate: overall={overall:.1%} pf={pf:.1%} win_rate={wr:.1%} last4={last4:.1%}".format(
                overall=float(trend.get("waiver_fire_rate", 0.0)),
                pf=float(trend.get("profit_factor_waiver_fire_rate", 0.0)),
                wr=float(trend.get("win_rate_waiver_fire_rate", 0.0)),
                last4=float(trend.get("waiver_fire_rate_last4", 0.0)),
            )
        )

    alerts = result.get("drift_alerts", {})
    if isinstance(alerts, dict) and alerts:
        active = [name for name, flag in alerts.items() if bool(flag)]
        print(f"Active alerts: {', '.join(active) if active else 'none'}")

    print(f"Needs attention: {bool(result.get('needs_attention', False))}")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    records = load_weekly_audits(args.audit_dir)
    summary = summarize_audit_trend(records, lookback=args.lookback)

    _print_summary(summary)

    if args.pretty:
        print("\nJSON:")
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))

    if args.export_json:
        path = write_trend_artifact(summary, output_dir=args.output_dir)
        print(f"Artifact: {path}")

    if summary["records_considered"] == 0 and not args.allow_empty:
        return 1
    if args.fail_on_alert and bool(summary.get("needs_attention", False)):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
