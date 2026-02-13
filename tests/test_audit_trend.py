from __future__ import annotations

import json
from pathlib import Path

from trading_bot.monitoring.audit_trend import load_weekly_audits, summarize_audit_trend, write_trend_artifact


def _write_audit(
    path: Path,
    *,
    audit_start: str,
    audit_end: str,
    sharpe: float,
    drawdown: float,
    win_rate: float,
    closed_trades: int,
    critical_errors: int,
    ready: bool,
    pf_waiver: bool = False,
    win_waiver: bool = False,
) -> None:
    payload = {
        "period": {"audit_start": audit_start, "audit_end": audit_end, "weeks": 4},
        "metrics": {
            "total_return_pct": 4.2,
            "sharpe_ratio": sharpe,
            "max_drawdown": drawdown,
            "win_rate": win_rate,
            "closed_trades": closed_trades,
            "critical_error_count": critical_errors,
        },
        "gates": {
            "sharpe_ratio": {"passed": sharpe >= 0.7},
            "max_drawdown": {"passed": abs(drawdown) <= 0.15},
            "profit_factor": {"passed": True, "waiver_applied": pf_waiver},
            "win_rate": {"passed": True, "waiver_applied": win_waiver},
        },
        "ready_for_live": ready,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_audit_trend_load_and_summary(tmp_path):
    audits_dir = tmp_path / "audits"
    audits_dir.mkdir(parents=True)

    _write_audit(
        audits_dir / "weekly_audit_20260101_000001.json",
        audit_start="2025-12-01",
        audit_end="2026-01-01",
        sharpe=0.95,
        drawdown=-0.08,
        win_rate=0.58,
        closed_trades=18,
        critical_errors=0,
        ready=True,
    )
    _write_audit(
        audits_dir / "weekly_audit_20260108_000001.json",
        audit_start="2025-12-08",
        audit_end="2026-01-08",
        sharpe=1.02,
        drawdown=-0.09,
        win_rate=0.56,
        closed_trades=20,
        critical_errors=0,
        ready=True,
    )
    _write_audit(
        audits_dir / "weekly_audit_20260115_000001.json",
        audit_start="2025-12-15",
        audit_end="2026-01-15",
        sharpe=1.00,
        drawdown=-0.10,
        win_rate=0.57,
        closed_trades=22,
        critical_errors=0,
        ready=True,
    )

    records = load_weekly_audits(audits_dir)
    assert len(records) == 3
    assert records[-1]["audit_end"] == "2026-01-15"

    summary = summarize_audit_trend(records, lookback=3)
    assert summary["records_considered"] == 3
    assert summary["latest"]["ready_for_live"] is True
    assert summary["needs_attention"] is False
    assert summary["trend"]["waiver_fire_rate"] == 0.0



def test_audit_trend_flags_drift_alerts(tmp_path):
    audits_dir = tmp_path / "audits"
    audits_dir.mkdir(parents=True)

    _write_audit(
        audits_dir / "weekly_audit_20260101_000001.json",
        audit_start="2025-12-01",
        audit_end="2026-01-01",
        sharpe=1.10,
        drawdown=-0.06,
        win_rate=0.62,
        closed_trades=15,
        critical_errors=0,
        ready=True,
    )
    _write_audit(
        audits_dir / "weekly_audit_20260108_000001.json",
        audit_start="2025-12-08",
        audit_end="2026-01-08",
        sharpe=1.05,
        drawdown=-0.07,
        win_rate=0.60,
        closed_trades=17,
        critical_errors=0,
        ready=True,
    )
    _write_audit(
        audits_dir / "weekly_audit_20260115_000001.json",
        audit_start="2025-12-15",
        audit_end="2026-01-15",
        sharpe=0.40,
        drawdown=-0.20,
        win_rate=0.40,
        closed_trades=12,
        critical_errors=4,
        ready=False,
    )

    records = load_weekly_audits(audits_dir)
    summary = summarize_audit_trend(records, lookback=3)

    alerts = summary["drift_alerts"]
    assert alerts["not_ready_latest"] is True
    assert alerts["sharpe_drop"] is True
    assert alerts["drawdown_worsened"] is True
    assert alerts["win_rate_drop"] is True
    assert summary["needs_attention"] is True

    artifact = write_trend_artifact(summary, output_dir=tmp_path / "trend")
    assert artifact.exists()
    written = json.loads(artifact.read_text(encoding="utf-8"))
    assert written["latest"]["audit_end"] == "2026-01-15"


def test_audit_trend_tracks_waiver_fire_rate(tmp_path):
    audits_dir = tmp_path / "audits"
    audits_dir.mkdir(parents=True)

    _write_audit(
        audits_dir / "weekly_audit_20260101_000001.json",
        audit_start="2025-12-01",
        audit_end="2026-01-01",
        sharpe=0.95,
        drawdown=-0.08,
        win_rate=0.58,
        closed_trades=18,
        critical_errors=0,
        ready=True,
        pf_waiver=True,
        win_waiver=True,
    )
    _write_audit(
        audits_dir / "weekly_audit_20260108_000001.json",
        audit_start="2025-12-08",
        audit_end="2026-01-08",
        sharpe=1.02,
        drawdown=-0.09,
        win_rate=0.56,
        closed_trades=20,
        critical_errors=0,
        ready=True,
        pf_waiver=False,
        win_waiver=False,
    )

    records = load_weekly_audits(audits_dir)
    summary = summarize_audit_trend(records, lookback=8)
    assert summary["trend"]["waiver_fire_rate"] == 0.5
    assert summary["trend"]["profit_factor_waiver_fire_rate"] == 0.5
    assert summary["trend"]["win_rate_waiver_fire_rate"] == 0.5
    timeline = summary["trend"]["waiver_timeline"]
    assert len(timeline) == 2
    assert timeline[0]["waiver_applied"] is True
