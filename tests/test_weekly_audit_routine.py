from __future__ import annotations

from pathlib import Path

import pandas as pd

import main as main_module


def test_weekly_audit_routine_writes_artifact_and_log(bot_with_test_db, monkeypatch):
    bot, test_db = bot_with_test_db

    fake_result = {
        "ready_for_live": False,
        "gates": {
            "sharpe_ratio": {"passed": False},
            "max_drawdown": {"passed": True},
        },
    }
    fake_artifact = Path("reports/audits/weekly_audit_test.json")

    monkeypatch.setattr(main_module, "run_weekly_audit", lambda *args, **kwargs: fake_result)
    monkeypatch.setattr(main_module, "write_weekly_audit_artifact", lambda *args, **kwargs: fake_artifact)

    sent_alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(bot.telegram, "send_alert", lambda level, msg: sent_alerts.append((level, msg)))

    result = bot.weekly_audit_routine()
    assert result["ready_for_live"] is False
    assert sent_alerts
    assert sent_alerts[-1][0] == "WARNING"

    logs_df = pd.read_sql("SELECT * FROM system_logs WHERE module='weekly_audit'", test_db.engine)
    assert len(logs_df) >= 1
    assert "ready_for_live=False" in str(logs_df.iloc[-1]["message"])

    hb = bot.heartbeat_path.read_text(encoding="utf-8")
    assert "weekly_audit_complete" in hb
