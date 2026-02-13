from __future__ import annotations

import json
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    for parser in (date.fromisoformat, datetime.fromisoformat):
        try:
            parsed = parser(raw)
            if isinstance(parsed, datetime):
                return parsed.date()
            return parsed
        except ValueError:
            continue
    return None


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def load_weekly_audit_records(audit_dir: str | Path = "reports/audits") -> list[dict[str, Any]]:
    directory = Path(audit_dir)
    if not directory.exists():
        return []

    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("weekly_audit_*.json")):
        payload = _load_json(path)
        if payload is None:
            continue

        period = payload.get("period", {}) if isinstance(payload.get("period"), dict) else {}
        metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics"), dict) else {}

        audit_end = _parse_date(period.get("audit_end"))
        if audit_end is None:
            continue

        records.append(
            {
                "source": "weekly_audit",
                "artifact": str(path),
                "audit_end": audit_end.isoformat(),
                "ready_for_live": bool(payload.get("ready_for_live", False)),
                "preflight_status": None,
                "weekly_audit_ready": bool(payload.get("ready_for_live", False)),
                "closed_trades": int(metrics.get("closed_trades", 0) or 0),
                "sharpe_ratio": float(metrics.get("sharpe_ratio", 0.0) or 0.0),
                "max_drawdown": float(metrics.get("max_drawdown", 0.0) or 0.0),
                "win_rate": float(metrics.get("win_rate", 0.0) or 0.0),
            }
        )

    records.sort(key=lambda r: (r["audit_end"], r["artifact"]))
    return records


def load_promotion_records(promotion_dir: str | Path = "reports/promotion") -> list[dict[str, Any]]:
    root = Path(promotion_dir)
    if not root.exists():
        return []

    records: list[dict[str, Any]] = []
    for bundle in sorted(p for p in root.glob("promotion_*") if p.is_dir()):
        summary = _load_json(bundle / "summary.json")
        weekly = _load_json(bundle / "weekly_audit.json")
        if summary is None or weekly is None:
            continue

        period = weekly.get("period", {}) if isinstance(weekly.get("period"), dict) else {}
        metrics = weekly.get("metrics", {}) if isinstance(weekly.get("metrics"), dict) else {}
        audit_end = _parse_date(period.get("audit_end"))
        if audit_end is None:
            continue

        records.append(
            {
                "source": "promotion_bundle",
                "artifact": str(bundle),
                "audit_end": audit_end.isoformat(),
                "ready_for_live": bool(summary.get("ready_for_live", False)),
                "preflight_status": summary.get("preflight_status"),
                "weekly_audit_ready": bool(summary.get("weekly_audit_ready", False)),
                "closed_trades": int(metrics.get("closed_trades", 0) or 0),
                "sharpe_ratio": float(metrics.get("sharpe_ratio", 0.0) or 0.0),
                "max_drawdown": float(metrics.get("max_drawdown", 0.0) or 0.0),
                "win_rate": float(metrics.get("win_rate", 0.0) or 0.0),
            }
        )

    records.sort(key=lambda r: (r["audit_end"], r["artifact"]))
    return records


def _group_latest_by_week(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    week_map: "OrderedDict[tuple[int, int], dict[str, Any]]" = OrderedDict()

    for record in sorted(records, key=lambda r: (r["audit_end"], r["artifact"])):
        day = _parse_date(record.get("audit_end"))
        if day is None:
            continue
        iso_year, iso_week, _ = day.isocalendar()
        week_map[(iso_year, iso_week)] = record

    return list(week_map.values())


def _calculate_trailing_ready_streak(weekly_records: list[dict[str, Any]]) -> int:
    if not weekly_records:
        return 0

    streak = 0
    for row in reversed(weekly_records):
        if bool(row.get("ready_for_live", False)):
            streak += 1
            continue
        break
    return streak


def compute_paper_run_status(
    *,
    weekly_records: list[dict[str, Any]],
    promotion_records: list[dict[str, Any]],
    required_weeks: int = 4,
    require_promotion_bundle: bool = True,
) -> dict[str, Any]:
    if required_weeks <= 0:
        raise ValueError("required_weeks must be greater than 0")

    source_records = promotion_records if require_promotion_bundle else (promotion_records or weekly_records)
    grouped = _group_latest_by_week(source_records)
    streak = _calculate_trailing_ready_streak(grouped)

    latest = grouped[-1] if grouped else None
    ready_for_live = bool(streak >= required_weeks)

    reasons: list[str] = []
    if require_promotion_bundle and not promotion_records:
        reasons.append("No promotion bundles found")
    if len(grouped) < required_weeks:
        reasons.append(f"Only {len(grouped)} weekly checkpoints available, requires {required_weeks}")
    if streak < required_weeks:
        reasons.append(f"Trailing ready streak is {streak}, requires {required_weeks}")

    return {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "required_weeks": required_weeks,
        "require_promotion_bundle": bool(require_promotion_bundle),
        "weekly_audit_records": len(weekly_records),
        "promotion_records": len(promotion_records),
        "weekly_checkpoints": len(grouped),
        "trailing_ready_streak": streak,
        "latest_checkpoint": latest,
        "ready_for_live": ready_for_live,
        "blocking_reasons": reasons,
        "checkpoints": grouped,
    }
