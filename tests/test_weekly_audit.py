from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import text

from trading_bot.monitoring.performance_audit import (
    AuditThresholds,
    compute_portfolio_metrics,
    evaluate_go_live_gates,
    run_weekly_audit,
)


def test_compute_portfolio_metrics_contract():
    frame = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
            "total_value": [100000.0, 110000.0, 105000.0, 120000.0],
        }
    )
    metrics = compute_portfolio_metrics(frame)

    assert metrics["portfolio_points"] == 4
    assert round(float(metrics["total_return_pct"]), 2) == 20.00
    assert float(metrics["max_drawdown"]) < 0


def test_evaluate_go_live_gates():
    thresholds = AuditThresholds(
        min_sharpe=0.7,
        max_drawdown=0.15,
        min_win_rate=0.5,
        min_profit_factor=1.0,
        min_closed_trades=10,
        max_critical_errors=0,
        critical_window_days=14,
    )
    metrics = {
        "portfolio_points": 10,
        "sharpe_ratio": 0.9,
        "max_drawdown": -0.08,
        "win_rate": 0.6,
        "profit_factor": 1.4,
        "closed_trades": 12,
        "critical_error_count": 0,
    }
    gates, ready = evaluate_go_live_gates(metrics, thresholds)
    assert ready is True
    assert all(g["passed"] for g in gates.values())


def test_profit_factor_waiver_for_positive_sharpe_positive_return_trend_case():
    thresholds = AuditThresholds(
        min_sharpe=0.7,
        max_drawdown=0.15,
        min_win_rate=0.3,
        min_profit_factor=1.2,
        min_closed_trades=3,
        max_critical_errors=0,
        critical_window_days=14,
    )
    metrics = {
        "portfolio_points": 10,
        "sharpe_ratio": 1.1,
        "max_drawdown": -0.05,
        "total_return_pct": 1.8,
        "wins": 0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "closed_trades": 3,
        "critical_error_count": 0,
    }
    gates, ready = evaluate_go_live_gates(metrics, thresholds)
    assert gates["profit_factor"]["passed"] is True
    assert gates["profit_factor"]["waiver_applied"] is True
    assert gates["win_rate"]["passed"] is True
    assert gates["win_rate"]["waiver_applied"] is True
    assert ready is True


def test_run_weekly_audit_with_db_data(bot_with_test_db):
    _, test_db = bot_with_test_db
    now = datetime.utcnow().date()

    with test_db.engine.begin() as conn:
        # Portfolio growth over 14 days
        for i in range(14):
            d = now - timedelta(days=13 - i)
            conn.execute(
                text(
                    """
                    INSERT OR REPLACE INTO portfolio_snapshots
                    (date, total_value, cash, positions_value, num_positions, daily_pnl, daily_pnl_percent, total_pnl, total_pnl_percent)
                    VALUES
                    (:date, :total_value, :cash, :positions_value, :num_positions, :daily_pnl, :daily_pnl_percent, :total_pnl, :total_pnl_percent)
                    """
                ),
                {
                    "date": d.strftime("%Y-%m-%d"),
                    "total_value": 100000 + (i * 700),
                    "cash": 50000,
                    "positions_value": 50000 + (i * 700),
                    "num_positions": 5,
                    "daily_pnl": 700,
                    "daily_pnl_percent": 0.7,
                    "total_pnl": i * 700,
                    "total_pnl_percent": (i * 700 / 100000) * 100,
                },
            )

        # 12 closed trades with 9 wins, 3 losses
        for i in range(12):
            pnl = 120.0 if i < 9 else -70.0
            exit_dt = datetime.combine(now - timedelta(days=(11 - i)), datetime.min.time()).isoformat()
            conn.execute(
                text(
                    """
                    INSERT OR REPLACE INTO trades
                    (order_id, symbol, strategy, action, quantity, entry_price, entry_date, exit_price, exit_date, pnl, pnl_percent, status, notes)
                    VALUES
                    (:order_id, :symbol, :strategy, :action, :quantity, :entry_price, :entry_date, :exit_price, :exit_date, :pnl, :pnl_percent, :status, :notes)
                    """
                ),
                {
                    "order_id": f"AUDIT_{i}",
                    "symbol": "TEST",
                    "strategy": "AuditStrategy",
                    "action": "SELL",
                    "quantity": 1,
                    "entry_price": 100.0,
                    "entry_date": exit_dt,
                    "exit_price": 101.0,
                    "exit_date": exit_dt,
                    "pnl": pnl,
                    "pnl_percent": pnl / 100.0,
                    "status": "CLOSED",
                    "notes": "AUDIT",
                },
            )

    result = run_weekly_audit(
        test_db.engine,
        weeks=2,
        thresholds=AuditThresholds(
            min_sharpe=0.1,
            max_drawdown=0.2,
            min_win_rate=0.5,
            min_profit_factor=1.0,
            min_closed_trades=10,
            max_critical_errors=0,
            critical_window_days=14,
        ),
        anchor_date=now,
    )

    assert result["ready_for_live"] is True
    assert result["metrics"]["closed_trades"] == 12
    assert result["metrics"]["profit_factor"] > 1.0
    assert result["metrics"]["critical_error_count"] == 0


def test_run_weekly_audit_fails_on_critical_errors(bot_with_test_db):
    _, test_db = bot_with_test_db
    now = datetime.utcnow().date()

    with test_db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO portfolio_snapshots
                (date, total_value, cash, positions_value, num_positions, daily_pnl, daily_pnl_percent, total_pnl, total_pnl_percent)
                VALUES
                (:date, 100000, 100000, 0, 0, 0, 0, 0, 0)
                """
            ),
            {"date": now.strftime("%Y-%m-%d")},
        )
        conn.execute(
            text(
                """
                INSERT INTO system_logs (timestamp, level, module, message)
                VALUES (:timestamp, 'ERROR', 'audit_test', 'critical pipeline failure')
                """
            ),
            {"timestamp": datetime.utcnow().isoformat()},
        )

    result = run_weekly_audit(
        test_db.engine,
        weeks=1,
        thresholds=AuditThresholds(
            min_sharpe=-10.0,
            max_drawdown=1.0,
            min_win_rate=0.0,
            min_profit_factor=0.0,
            min_closed_trades=0,
            max_critical_errors=0,
            critical_window_days=14,
        ),
        anchor_date=now,
    )

    assert result["ready_for_live"] is False
    assert result["gates"]["critical_errors"]["passed"] is False
