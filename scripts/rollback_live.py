from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from trading_bot.execution.broker_interface import BrokerInterface
from trading_bot.monitoring.ops_controls import set_kill_switch


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guarded live rollback helper: enable kill switch and cancel open broker orders.",
    )
    parser.add_argument("--segment", default="CASH", help="Broker segment for open-order listing/cancel.")
    parser.add_argument(
        "--enable-kill-switch",
        action="store_true",
        help="Enable kill switch before cancellation operations.",
    )
    parser.add_argument("--kill-switch-reason", default="rollback_manual")
    parser.add_argument(
        "--cancel-open-orders",
        action="store_true",
        help="Cancel all currently open orders from broker.",
    )
    parser.add_argument("--max-orders", type=int, default=200, help="Safety cap for maximum cancellation attempts.")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without sending cancellation requests.")
    parser.add_argument(
        "--force",
        default="",
        help="Required when --cancel-open-orders is used: YES_ROLLBACK",
    )
    parser.add_argument("--output-dir", default="reports/rollback")
    parser.add_argument("--pretty", action="store_true")
    return parser


def _write_report(payload: dict[str, Any], output_dir: str) -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = directory / f"rollback_{ts}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def main() -> int:
    load_dotenv()
    parser = _build_parser()
    args = parser.parse_args()

    if args.cancel_open_orders and args.force != "YES_ROLLBACK":
        parser.error("--cancel-open-orders requires --force YES_ROLLBACK")

    broker = BrokerInterface()
    if not broker.connect():
        print("Rollback failed: broker connection failed")
        return 1

    report: dict[str, Any] = {
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "provider": broker.provider,
        "segment": args.segment,
        "dry_run": bool(args.dry_run),
        "kill_switch_enabled": False,
        "open_orders_count": 0,
        "cancellation_attempted": 0,
        "cancellation_success": 0,
        "cancellation_failed": 0,
        "orders": [],
    }

    if args.enable_kill_switch:
        ks_path = set_kill_switch(reason=args.kill_switch_reason)
        report["kill_switch_enabled"] = True
        report["kill_switch_path"] = str(ks_path)

    open_orders = broker.get_open_orders(segment=args.segment)
    report["open_orders_count"] = len(open_orders)

    if args.cancel_open_orders:
        targets = open_orders[: max(0, int(args.max_orders))]
        report["cancellation_attempted"] = len(targets)
        for order in targets:
            order_id = str(order.get("groww_order_id") or order.get("order_id") or "")
            if not order_id:
                report["cancellation_failed"] += 1
                report["orders"].append(
                    {
                        "order_id": None,
                        "status": "FAILED",
                        "reason": "missing_order_id",
                        "raw": order,
                    }
                )
                continue

            if args.dry_run:
                report["orders"].append(
                    {
                        "order_id": order_id,
                        "status": "DRY_RUN_SKIP",
                    }
                )
                continue

            result = broker.cancel_order(order_id, segment=args.segment)
            status = str((result or {}).get("status", "UNKNOWN")).upper()
            is_ok = status in {"CANCELLED", "COMPLETE", "SUCCESS", "OK"}
            if is_ok:
                report["cancellation_success"] += 1
            else:
                report["cancellation_failed"] += 1
            report["orders"].append(
                {
                    "order_id": order_id,
                    "status": status,
                    "response": result,
                }
            )

    artifact = _write_report(report, args.output_dir)
    print(f"Rollback report: {artifact}")
    if args.pretty:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print(
            "summary provider={provider} open_orders={open_orders} attempted={attempted} "
            "success={success} failed={failed} dry_run={dry_run}".format(
                provider=report["provider"],
                open_orders=report["open_orders_count"],
                attempted=report["cancellation_attempted"],
                success=report["cancellation_success"],
                failed=report["cancellation_failed"],
                dry_run=report["dry_run"],
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
