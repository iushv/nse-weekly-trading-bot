from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Engine

from trading_bot.monitoring.audit_artifacts import write_promotion_bundle
from trading_bot.monitoring.health_check import health_status
from trading_bot.monitoring.performance_audit import AuditThresholds, run_weekly_audit


def evaluate_promotion_ready(preflight: dict[str, Any], weekly_audit: dict[str, Any]) -> bool:
    return bool(preflight.get("status") == "ok" and weekly_audit.get("ready_for_live") is True)


def run_promotion_gate(
    engine: Engine,
    *,
    weeks: int,
    thresholds: AuditThresholds,
    include_broker: bool = True,
    fail_on_broker: bool = True,
    write_bundle: bool = True,
    output_dir: str = "reports/promotion",
) -> dict[str, Any]:
    preflight = health_status(include_broker=include_broker, fail_on_broker=fail_on_broker)
    weekly = run_weekly_audit(engine, weeks=weeks, thresholds=thresholds)
    ready = evaluate_promotion_ready(preflight, weekly)

    summary: dict[str, Any] = {
        "ready_for_live": ready,
        "preflight_status": preflight.get("status"),
        "weekly_audit_ready": weekly.get("ready_for_live"),
        "failed_gates": [
            name
            for name, gate in weekly.get("gates", {}).items()
            if isinstance(gate, dict) and not bool(gate.get("passed"))
        ],
    }

    bundle_path = None
    if write_bundle:
        bundle_path = write_promotion_bundle(
            preflight=preflight,
            weekly_audit=weekly,
            summary=summary,
            output_dir=output_dir,
        )
        summary["bundle_path"] = str(bundle_path)

    return {
        "ready_for_live": ready,
        "preflight": preflight,
        "weekly_audit": weekly,
        "summary": summary,
        "bundle_path": str(bundle_path) if bundle_path else None,
    }
