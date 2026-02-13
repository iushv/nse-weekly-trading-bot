from __future__ import annotations

from trading_bot.monitoring.ops_controls import (
    build_notify_template,
    clear_kill_switch,
    create_incident_note,
    is_kill_switch_active,
    set_kill_switch,
)


def test_kill_switch_toggle(tmp_path):
    assert is_kill_switch_active(tmp_path) is False
    path = set_kill_switch(tmp_path, reason="test")
    assert path.exists()
    assert is_kill_switch_active(tmp_path) is True
    assert clear_kill_switch(tmp_path) is True
    assert is_kill_switch_active(tmp_path) is False


def test_create_incident_note(tmp_path):
    note = create_incident_note(
        title="Data feed outage",
        severity="high",
        details="Feed lag > 30 minutes.",
        actions="Paused entries.",
        output_dir=tmp_path,
    )
    assert note.exists()
    text = note.read_text(encoding="utf-8")
    assert "Data feed outage" in text
    assert "Paused entries." in text


def test_notify_template_contains_context():
    text = build_notify_template("broker_outage", context="Groww API timeouts observed")
    assert "Broker connectivity degraded" in text
    assert "Groww API timeouts observed" in text
