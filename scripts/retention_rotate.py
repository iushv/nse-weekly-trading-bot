from __future__ import annotations

import argparse
import json

from trading_bot.monitoring.audit_artifacts import write_json
from trading_bot.monitoring.retention import rotate_many


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rotate/archival old logs and report artifacts.")
    parser.add_argument(
        "--sources",
        nargs="+",
        default=["logs", "reports/audits", "reports/promotion", "reports/rollback"],
        help="Source directories to rotate.",
    )
    parser.add_argument("--archive-root", default="archive", help="Archive destination root.")
    parser.add_argument("--retention-days", type=int, default=30, help="Retain files newer than this many days.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would rotate without moving files.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON summary.")
    parser.add_argument("--export-json", action="store_true", help="Write rotation summary artifact to reports/retention.")
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Return exit code 1 if any file failed during rotation.",
    )
    return parser


def _print_summary(result: dict) -> None:
    print("Retention Rotation")
    print(f"Sources: {', '.join(result['sources'])}")
    print(
        "examined={examined} rotated={rotated} failed={failed} bytes={bytes_} dry_run={dry_run}".format(
            examined=int(result.get("files_examined", 0)),
            rotated=int(result.get("files_rotated", 0)),
            failed=int(result.get("files_failed", 0)),
            bytes_=int(result.get("bytes_rotated", 0)),
            dry_run=bool(result.get("dry_run", False)),
        )
    )


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    result = rotate_many(
        list(args.sources),
        archive_root=args.archive_root,
        retention_days=args.retention_days,
        dry_run=args.dry_run,
    )

    _print_summary(result)

    if args.pretty:
        print("\nJSON:")
        print(json.dumps(result, indent=2, sort_keys=True, default=str))

    if args.export_json:
        stamp = result["generated_at_utc"].replace(":", "").replace("-", "").replace("T", "_")[:15]
        path = write_json(f"reports/retention/retention_{stamp}.json", result)
        print(f"Artifact: {path}")

    if args.fail_on_error and int(result.get("files_failed", 0)) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
