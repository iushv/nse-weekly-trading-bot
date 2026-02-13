from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from trading_bot.monitoring.audit_artifacts import ensure_dir, write_json


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_date(value: Any) -> str:
    if isinstance(value, str) and value:
        return value
    return ""


def load_weekly_audits(audit_dir: str | Path = "reports/audits") -> list[dict[str, Any]]:
    directory = Path(audit_dir)
    if not directory.exists():
        return []

    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("weekly_audit_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(payload, dict):
            continue

        period = payload.get("period", {}) if isinstance(payload.get("period"), dict) else {}
        metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {}
        gates = payload.get("gates", {}) if isinstance(payload.get("gates"), dict) else {}

        failed_gates = [
            name
            for name, gate in gates.items()
            if isinstance(gate, dict) and not bool(gate.get("passed"))
        ]
        pf_gate = gates.get("profit_factor", {}) if isinstance(gates.get("profit_factor"), dict) else {}
        win_gate = gates.get("win_rate", {}) if isinstance(gates.get("win_rate"), dict) else {}
        pf_waiver_applied = bool(pf_gate.get("waiver_applied", False))
        win_waiver_applied = bool(win_gate.get("waiver_applied", False))

        records.append(
            {
                "artifact": str(path),
                "audit_start": _safe_date(period.get("audit_start")),
                "audit_end": _safe_date(period.get("audit_end")),
                "weeks": _to_int(period.get("weeks")),
                "total_return_pct": _to_float(metrics.get("total_return_pct")),
                "sharpe_ratio": _to_float(metrics.get("sharpe_ratio")),
                "max_drawdown_abs": abs(_to_float(metrics.get("max_drawdown"))),
                "win_rate": _to_float(metrics.get("win_rate")),
                "closed_trades": _to_int(metrics.get("closed_trades")),
                "critical_error_count": _to_int(metrics.get("critical_error_count")),
                "ready_for_live": bool(payload.get("ready_for_live", False)),
                "failed_gates": failed_gates,
                "profit_factor_waiver_applied": pf_waiver_applied,
                "win_rate_waiver_applied": win_waiver_applied,
                "waiver_applied": pf_waiver_applied or win_waiver_applied,
            }
        )

    records.sort(key=lambda row: (row.get("audit_end", ""), row.get("artifact", "")))
    return records


def summarize_audit_trend(
    records: list[dict[str, Any]],
    *,
    lookback: int = 8,
    sharpe_drop_alert: float = 0.20,
    drawdown_increase_alert: float = 0.02,
    win_rate_drop_alert: float = 0.08,
) -> dict[str, Any]:
    if lookback <= 0:
        raise ValueError("lookback must be greater than 0")

    subset = records[-lookback:] if len(records) > lookback else list(records)
    if not subset:
        return {
            "generated_at_utc": datetime.utcnow().isoformat() + "Z",
            "records_considered": 0,
            "lookback": lookback,
            "latest": None,
            "trend": {},
            "drift_alerts": {},
            "needs_attention": False,
        }

    latest = subset[-1]
    previous = subset[:-1]

    ready_count = sum(1 for row in subset if bool(row.get("ready_for_live")))
    trend: dict[str, Any] = {
        "ready_ratio": (ready_count / len(subset)) if subset else 0.0,
        "avg_return_pct": mean(float(row.get("total_return_pct", 0.0)) for row in subset),
        "avg_sharpe": mean(float(row.get("sharpe_ratio", 0.0)) for row in subset),
        "avg_max_drawdown_abs": mean(float(row.get("max_drawdown_abs", 0.0)) for row in subset),
        "avg_win_rate": mean(float(row.get("win_rate", 0.0)) for row in subset),
        "avg_critical_errors": mean(float(row.get("critical_error_count", 0.0)) for row in subset),
        "waiver_fire_rate": mean(1.0 if bool(row.get("waiver_applied", False)) else 0.0 for row in subset),
        "profit_factor_waiver_fire_rate": mean(
            1.0 if bool(row.get("profit_factor_waiver_applied", False)) else 0.0 for row in subset
        ),
        "win_rate_waiver_fire_rate": mean(
            1.0 if bool(row.get("win_rate_waiver_applied", False)) else 0.0 for row in subset
        ),
        "waiver_fire_rate_last4": mean(
            1.0 if bool(row.get("waiver_applied", False)) else 0.0 for row in subset[-4:]
        ),
    }
    trend["waiver_timeline"] = [
        {
            "audit_end": row.get("audit_end", ""),
            "waiver_applied": bool(row.get("waiver_applied", False)),
            "profit_factor_waiver_applied": bool(row.get("profit_factor_waiver_applied", False)),
            "win_rate_waiver_applied": bool(row.get("win_rate_waiver_applied", False)),
        }
        for row in subset
    ]

    drift_alerts: dict[str, bool] = {
        "not_ready_latest": not bool(latest.get("ready_for_live")),
    }

    if previous:
        prev_sharpe_avg = mean(float(row.get("sharpe_ratio", 0.0)) for row in previous)
        prev_drawdown_avg = mean(float(row.get("max_drawdown_abs", 0.0)) for row in previous)
        prev_win_rate_avg = mean(float(row.get("win_rate", 0.0)) for row in previous)

        drift_alerts.update(
            {
                "sharpe_drop": float(latest.get("sharpe_ratio", 0.0)) < (prev_sharpe_avg - sharpe_drop_alert),
                "drawdown_worsened": float(latest.get("max_drawdown_abs", 0.0)) > (prev_drawdown_avg + drawdown_increase_alert),
                "win_rate_drop": float(latest.get("win_rate", 0.0)) < (prev_win_rate_avg - win_rate_drop_alert),
                "critical_errors_spike": _to_int(latest.get("critical_error_count", 0)) > _to_int(trend.get("avg_critical_errors", 0.0)) + 1,
            }
        )
    else:
        drift_alerts.update(
            {
                "sharpe_drop": False,
                "drawdown_worsened": False,
                "win_rate_drop": False,
                "critical_errors_spike": False,
            }
        )

    needs_attention = any(bool(flag) for flag in drift_alerts.values())

    return {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "records_considered": len(subset),
        "lookback": lookback,
        "latest": latest,
        "trend": trend,
        "drift_alerts": drift_alerts,
        "needs_attention": needs_attention,
    }


def write_trend_artifact(
    summary: dict[str, Any],
    *,
    output_dir: str | Path = "reports/audits/trends",
    prefix: str = "weekly_audit_trend",
) -> Path:
    directory = ensure_dir(output_dir)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return write_json(directory / f"{prefix}_{stamp}.json", summary)
