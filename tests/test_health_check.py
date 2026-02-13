from __future__ import annotations

from trading_bot.monitoring import health_check


def test_health_status_ok_without_broker(monkeypatch):
    monkeypatch.setattr(health_check, "check_environment", lambda: {"ok": True, "message": "env ok"})
    monkeypatch.setattr(health_check, "check_database", lambda: {"ok": True, "message": "db ok"})

    result = health_check.health_status(include_broker=False)
    assert result["status"] == "ok"
    assert result["checks"]["environment"]["ok"] is True
    assert result["checks"]["database"]["ok"] is True
    assert "broker" not in result["checks"]


def test_health_status_degraded_when_core_check_fails(monkeypatch):
    monkeypatch.setattr(health_check, "check_environment", lambda: {"ok": False, "message": "env bad"})
    monkeypatch.setattr(health_check, "check_database", lambda: {"ok": True, "message": "db ok"})

    result = health_check.health_status(include_broker=False)
    assert result["status"] == "degraded"


def test_health_status_broker_optional(monkeypatch):
    monkeypatch.setattr(health_check, "check_environment", lambda: {"ok": True, "message": "env ok"})
    monkeypatch.setattr(health_check, "check_database", lambda: {"ok": True, "message": "db ok"})
    monkeypatch.setattr(health_check, "check_broker_read_only", lambda: {"ok": False, "message": "broker bad"})

    result = health_check.health_status(include_broker=True, fail_on_broker=False)
    assert result["status"] == "ok"
    assert result["checks"]["broker"]["ok"] is False


def test_health_status_broker_required(monkeypatch):
    monkeypatch.setattr(health_check, "check_environment", lambda: {"ok": True, "message": "env ok"})
    monkeypatch.setattr(health_check, "check_database", lambda: {"ok": True, "message": "db ok"})
    monkeypatch.setattr(health_check, "check_broker_read_only", lambda: {"ok": False, "message": "broker bad"})

    result = health_check.health_status(include_broker=True, fail_on_broker=True)
    assert result["status"] == "degraded"
