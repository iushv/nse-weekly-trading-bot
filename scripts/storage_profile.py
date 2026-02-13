from __future__ import annotations

import argparse
import json

from trading_bot.monitoring.audit_artifacts import write_json
from trading_bot.monitoring.storage_profile import profile_sources


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile artifact storage and suggest retention windows.")
    parser.add_argument(
        "--sources",
        nargs="+",
        default=["logs", "reports/audits", "reports/promotion", "reports/rollback", "reports/retention", "archive"],
        help="Directories to profile.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument("--export-json", action="store_true", help="Write profile artifact to reports/retention.")
    return parser


def _print_summary(result: dict) -> None:
    print("Storage Profile")
    print(
        "sources={count} files={files} bytes={bytes_} suggested_global_retention_days={ret}".format(
            count=len(result.get("profiles", [])),
            files=int(result.get("total_files", 0)),
            bytes_=int(result.get("total_bytes", 0)),
            ret=int(result.get("suggested_global_retention_days", 30)),
        )
    )


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    result = profile_sources(list(args.sources))
    _print_summary(result)

    if args.pretty:
        print("\nJSON:")
        print(json.dumps(result, indent=2, sort_keys=True, default=str))

    if args.export_json:
        stamp = result["generated_at_utc"].replace(":", "").replace("-", "").replace("T", "_")[:15]
        path = write_json(f"reports/retention/storage_profile_{stamp}.json", result)
        print(f"Artifact: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
