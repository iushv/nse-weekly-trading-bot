from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import text

from trading_bot.config.settings import Config
from trading_bot.data.storage.database import db
from trading_bot.execution.broker_interface import BrokerInterface


def _build_check(ok: bool, message: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": ok, "message": message}
    if extra:
        payload.update(extra)
    return payload


def check_environment() -> dict[str, Any]:
    try:
        Config.validate()
        return _build_check(True, "Configuration is valid")
    except Exception as exc:
        return _build_check(False, f"Configuration validation failed: {exc}")


def check_database() -> dict[str, Any]:
    try:
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return _build_check(True, "Database connection is healthy")
    except Exception as exc:
        return _build_check(False, f"Database check failed: {exc}")


def check_broker_read_only() -> dict[str, Any]:
    try:
        broker = BrokerInterface()
        if not broker.connect():
            return _build_check(False, "Broker connect() returned False")
        cash = broker.get_available_cash()
        positions = broker.get_current_positions()
        return _build_check(
            True,
            "Broker read-only checks succeeded",
            {
                "provider": broker.provider,
                "cash": float(cash),
                "positions_count": len(positions),
            },
        )
    except Exception as exc:
        logger.warning(f"Broker health check failed: {exc}")
        return _build_check(False, f"Broker check failed: {exc}")


def health_status(*, include_broker: bool = False, fail_on_broker: bool = False) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {
        "environment": check_environment(),
        "database": check_database(),
    }
    overall_ok = checks["environment"]["ok"] and checks["database"]["ok"]

    if include_broker:
        checks["broker"] = check_broker_read_only()
        if fail_on_broker:
            overall_ok = overall_ok and checks["broker"]["ok"]

    status = "ok" if overall_ok else "degraded"
    return {
        "status": status,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "checks": checks,
    }
