from __future__ import annotations

from pathlib import Path

import pandas as pd

import main as main_module


def test_weekly_audit_trend_routine_writes_log_and_warning(bot_with_test_db, monkeypatch):
    bot, test_db = bot_with_test_db

    fake_summary = {
        "records_considered": 4,
        "needs_attention": True,
        "drift_alerts": {"sharpe_drop": True},
        "latest": {"audit_end": "2026-02-10"},
    }

    monkeypatch.setattr(main_module, "load_weekly_audits", lambda *args, **kwargs: [{"audit_end": "2026-02-10"}])
    monkeypatch.setattr(main_module, "summarize_audit_trend", lambda *args, **kwargs: fake_summary)
    monkeypatch.setattr(main_module, "write_trend_artifact", lambda *args, **kwargs: Path("reports/audits/trends/test.json"))

    sent_alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(bot.telegram, "send_alert", lambda level, msg: sent_alerts.append((level, msg)))

    result = bot.weekly_audit_trend_routine()
    assert result["needs_attention"] is True
    assert sent_alerts
    assert sent_alerts[-1][0] == "WARNING"

    logs_df = pd.read_sql("SELECT * FROM system_logs WHERE module='weekly_audit_trend'", test_db.engine)
    assert len(logs_df) >= 1
    assert "needs_attention=True" in str(logs_df.iloc[-1]["message"])


def test_retention_rotation_routine_logs_and_alerts_on_failures(bot_with_test_db, monkeypatch):
    bot, test_db = bot_with_test_db

    fake_result = {
        "files_rotated": 2,
        "files_failed": 1,
    }

    monkeypatch.setattr(main_module, "rotate_many", lambda *args, **kwargs: fake_result)
    monkeypatch.setattr(main_module, "write_json", lambda *args, **kwargs: Path("reports/retention/test.json"))

    sent_alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(bot.telegram, "send_alert", lambda level, msg: sent_alerts.append((level, msg)))

    result = bot.retention_rotation_routine()
    assert result["files_failed"] == 1
    assert sent_alerts
    assert sent_alerts[-1][0] == "WARNING"

    logs_df = pd.read_sql("SELECT * FROM system_logs WHERE module='retention_rotation'", test_db.engine)
    assert len(logs_df) >= 1
    assert "failed=1" in str(logs_df.iloc[-1]["message"])


def test_paper_run_status_routine_writes_status_and_info_alert(bot_with_test_db, monkeypatch):
    bot, test_db = bot_with_test_db

    fake_result = {
        "ready_for_live": False,
        "required_weeks": 4,
        "trailing_ready_streak": 1,
        "blocking_reasons": ["Only 1 weekly checkpoints available, requires 4"],
    }

    monkeypatch.setattr(main_module, "load_weekly_audit_records", lambda *args, **kwargs: [])
    monkeypatch.setattr(main_module, "load_promotion_records", lambda *args, **kwargs: [])
    monkeypatch.setattr(main_module, "compute_paper_run_status", lambda *args, **kwargs: fake_result)
    monkeypatch.setattr(main_module, "write_json", lambda *args, **kwargs: Path("reports/promotion/paper_run_status_test.json"))

    sent_alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(bot.telegram, "send_alert", lambda level, msg: sent_alerts.append((level, msg)))

    result = bot.paper_run_status_routine()
    assert result["ready_for_live"] is False
    assert sent_alerts
    assert sent_alerts[-1][0] == "INFO"

    logs_df = pd.read_sql("SELECT * FROM system_logs WHERE module='paper_run_status'", test_db.engine)
    assert len(logs_df) >= 1
    assert "streak=1/4" in str(logs_df.iloc[-1]["message"])
