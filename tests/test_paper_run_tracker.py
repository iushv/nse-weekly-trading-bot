from __future__ import annotations

import json
from pathlib import Path

from trading_bot.monitoring.paper_run_tracker import (
    compute_paper_run_status,
    load_promotion_records,
    load_weekly_audit_records,
)


def _write_weekly(path: Path, audit_end: str, ready: bool) -> None:
    payload = {
        "period": {"audit_start": "2026-01-01", "audit_end": audit_end, "weeks": 4},
        "metrics": {
            "closed_trades": 12,
            "sharpe_ratio": 0.9,
            "max_drawdown": -0.08,
            "win_rate": 0.56,
        },
        "ready_for_live": ready,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_promotion(bundle_dir: Path, audit_end: str, ready: bool, preflight: str = "ok") -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "ready_for_live": ready,
        "preflight_status": preflight,
        "weekly_audit_ready": ready,
    }
    weekly = {
        "period": {"audit_start": "2026-01-01", "audit_end": audit_end, "weeks": 4},
        "metrics": {
            "closed_trades": 12,
            "sharpe_ratio": 0.9,
            "max_drawdown": -0.08,
            "win_rate": 0.56,
        },
        "ready_for_live": ready,
    }
    (bundle_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (bundle_dir / "weekly_audit.json").write_text(json.dumps(weekly), encoding="utf-8")


def test_paper_run_ready_with_four_consecutive_promotion_weeks(tmp_path):
    promo = tmp_path / "promotion"
    _write_promotion(promo / "promotion_20260112_000001", "2026-01-12", True)
    _write_promotion(promo / "promotion_20260119_000001", "2026-01-19", True)
    _write_promotion(promo / "promotion_20260126_000001", "2026-01-26", True)
    _write_promotion(promo / "promotion_20260202_000001", "2026-02-02", True)

    weekly_records = []
    promotion_records = load_promotion_records(promo)

    result = compute_paper_run_status(
        weekly_records=weekly_records,
        promotion_records=promotion_records,
        required_weeks=4,
        require_promotion_bundle=True,
    )

    assert result["weekly_checkpoints"] == 4
    assert result["trailing_ready_streak"] == 4
    assert result["ready_for_live"] is True
    assert result["blocking_reasons"] == []


def test_paper_run_blocked_when_latest_week_not_ready(tmp_path):
    promo = tmp_path / "promotion"
    _write_promotion(promo / "promotion_20260112_000001", "2026-01-12", True)
    _write_promotion(promo / "promotion_20260119_000001", "2026-01-19", True)
    _write_promotion(promo / "promotion_20260126_000001", "2026-01-26", True)
    _write_promotion(promo / "promotion_20260202_000001", "2026-02-02", False)

    result = compute_paper_run_status(
        weekly_records=[],
        promotion_records=load_promotion_records(promo),
        required_weeks=4,
        require_promotion_bundle=True,
    )

    assert result["ready_for_live"] is False
    assert result["trailing_ready_streak"] == 0
    assert any("Trailing ready streak" in msg for msg in result["blocking_reasons"])


def test_paper_run_falls_back_to_weekly_audits_when_allowed(tmp_path):
    audits = tmp_path / "audits"
    audits.mkdir(parents=True)

    _write_weekly(audits / "weekly_audit_20260112_000001.json", "2026-01-12", True)
    _write_weekly(audits / "weekly_audit_20260119_000001.json", "2026-01-19", True)
    _write_weekly(audits / "weekly_audit_20260126_000001.json", "2026-01-26", True)
    _write_weekly(audits / "weekly_audit_20260202_000001.json", "2026-02-02", True)

    result = compute_paper_run_status(
        weekly_records=load_weekly_audit_records(audits),
        promotion_records=[],
        required_weeks=4,
        require_promotion_bundle=False,
    )

    assert result["ready_for_live"] is True
    assert result["trailing_ready_streak"] == 4
