from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def ensure_dir(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(path)
    ensure_dir(target.parent)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return target


def timestamp_slug(dt: datetime | None = None) -> str:
    now = dt or datetime.utcnow()
    return now.strftime("%Y%m%d_%H%M%S")


def write_weekly_audit_artifact(
    result: dict[str, Any],
    *,
    output_dir: str | Path = "reports/audits",
    prefix: str = "weekly_audit",
) -> Path:
    directory = ensure_dir(output_dir)
    name = f"{prefix}_{timestamp_slug()}.json"
    return write_json(directory / name, result)


def write_promotion_bundle(
    *,
    preflight: dict[str, Any],
    weekly_audit: dict[str, Any],
    summary: dict[str, Any],
    output_dir: str | Path = "reports/promotion",
) -> Path:
    base = ensure_dir(output_dir) / f"promotion_{timestamp_slug()}"
    ensure_dir(base)
    write_json(base / "preflight.json", preflight)
    write_json(base / "weekly_audit.json", weekly_audit)
    write_json(base / "summary.json", summary)
    return base
