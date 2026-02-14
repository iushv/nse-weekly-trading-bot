from __future__ import annotations

import argparse
import json

from trading_bot.monitoring.audit_artifacts import write_json
from trading_bot.monitoring.paper_run_tracker import (
    compute_paper_run_status,
    load_promotion_records,
    load_weekly_audit_records,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track paper-run readiness from weekly audit artifacts.")
    parser.add_argument("--audit-dir", default="reports/audits", help="Directory with weekly_audit_*.json files.")
    parser.add_argument("--promotion-dir", default="reports/promotion", help="Directory with promotion bundle folders.")
    parser.add_argument("--required-weeks", type=int, default=4, help="Required consecutive ready weeks.")
    parser.add_argument("--universe-tag", default="", help="Only count checkpoints matching this universe tag (from artifacts).")
    parser.add_argument(
        "--require-promotion-bundle",
        action="store_true",
        help="Require weekly promotion bundles for readiness evaluation.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print full JSON output.")
    parser.add_argument("--export-json", action="store_true", help="Write status artifact to reports/promotion.")
    parser.add_argument("--allow-not-ready", action="store_true", help="Return 0 even when readiness is false.")
    return parser


def _print_summary(result: dict) -> None:
    print("Paper Run Readiness")
    print(
        "checkpoints={cp} trailing_streak={streak}/{required} ready={ready}".format(
            cp=int(result.get("weekly_checkpoints", 0)),
            streak=int(result.get("trailing_ready_streak", 0)),
            required=int(result.get("required_weeks", 0)),
            ready=bool(result.get("ready_for_live", False)),
        )
    )

    latest = result.get("latest_checkpoint")
    if isinstance(latest, dict):
        print(
            "latest_end={end} source={source} preflight={preflight} weekly_ready={weekly_ready}".format(
                end=latest.get("audit_end", ""),
                source=latest.get("source", ""),
                preflight=latest.get("preflight_status", "n/a"),
                weekly_ready=latest.get("weekly_audit_ready", "n/a"),
            )
        )

    reasons = result.get("blocking_reasons", [])
    if isinstance(reasons, list) and reasons:
        print("Blocking:")
        for reason in reasons:
            print(f"- {reason}")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    weekly_records = load_weekly_audit_records(args.audit_dir)
    promotion_records = load_promotion_records(args.promotion_dir)

    result = compute_paper_run_status(
        weekly_records=weekly_records,
        promotion_records=promotion_records,
        universe_tag=args.universe_tag.strip() or None,
        required_weeks=args.required_weeks,
        require_promotion_bundle=args.require_promotion_bundle,
    )

    _print_summary(result)

    if args.pretty:
        print("\nJSON:")
        print(json.dumps(result, indent=2, sort_keys=True, default=str))

    if args.export_json:
        stamp = result["generated_at_utc"].replace(":", "").replace("-", "").replace("T", "_")[:15]
        path = write_json(f"reports/promotion/paper_run_status_{stamp}.json", result)
        print(f"Artifact: {path}")

    if result["ready_for_live"] or args.allow_not_ready:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
