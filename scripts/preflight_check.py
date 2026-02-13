from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from trading_bot.monitoring.health_check import health_status


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run preflight environment checks.")
    parser.add_argument("--include-broker", action="store_true", help="Include read-only broker health checks.")
    parser.add_argument(
        "--fail-on-broker",
        action="store_true",
        help="Mark health as failed if broker check fails (requires --include-broker).",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser


def _emit(result: dict[str, Any], pretty: bool) -> None:
    if pretty:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(json.dumps(result, sort_keys=True))


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    result = health_status(include_broker=args.include_broker, fail_on_broker=args.fail_on_broker)
    _emit(result, args.pretty)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
