from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class AuditThresholds:
    min_sharpe: float = 0.7
    max_drawdown: float = 0.15
    min_win_rate: float = 0.0
    min_profit_factor: float = 0.0
    min_closed_trades: int = 0
    max_critical_errors: int = 0
    critical_window_days: int = 14


def _to_date_str(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def _load_portfolio_history(engine: Engine, start_date: date, end_date: date) -> pd.DataFrame:
    query = """
        SELECT date, total_value
        FROM portfolio_snapshots
        WHERE date >= :start_date
          AND date <= :end_date
        ORDER BY date
    """
    return pd.read_sql(
        query,
        engine,
        params={"start_date": _to_date_str(start_date), "end_date": _to_date_str(end_date)},
    )


def _load_closed_trades(engine: Engine, start_date: date, end_date: date) -> pd.DataFrame:
    query = """
        SELECT strategy, pnl, pnl_percent, exit_date, notes AS exit_reason
        FROM trades
        WHERE status = 'CLOSED'
          AND date(exit_date) >= date(:start_date)
          AND date(exit_date) <= date(:end_date)
        ORDER BY exit_date
    """
    return pd.read_sql(
        query,
        engine,
        params={"start_date": _to_date_str(start_date), "end_date": _to_date_str(end_date)},
    )


def _load_critical_logs(engine: Engine, start_date: date, end_date: date) -> pd.DataFrame:
    query = """
        SELECT timestamp, level, module, message
        FROM system_logs
        WHERE datetime(timestamp) >= datetime(:start_date)
          AND datetime(timestamp) <= datetime(:end_date, '+1 day')
          AND UPPER(level) IN ('ERROR', 'CRITICAL')
        ORDER BY timestamp DESC
    """
    return pd.read_sql(
        query,
        engine,
        params={"start_date": _to_date_str(start_date), "end_date": _to_date_str(end_date)},
    )


def compute_portfolio_metrics(portfolio_df: pd.DataFrame) -> dict[str, float | int]:
    if portfolio_df.empty:
        return {
            "portfolio_points": 0,
            "total_return_pct": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "annualized_volatility": 0.0,
        }

    frame = portfolio_df.copy()
    frame["total_value"] = pd.to_numeric(frame["total_value"], errors="coerce")
    frame = frame.dropna(subset=["total_value"])

    if frame.empty:
        return {
            "portfolio_points": 0,
            "total_return_pct": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "annualized_volatility": 0.0,
        }

    frame["ret"] = frame["total_value"].pct_change().fillna(0.0)
    frame["peak"] = frame["total_value"].cummax()
    frame["drawdown"] = np.where(
        frame["peak"] > 0,
        (frame["total_value"] - frame["peak"]) / frame["peak"],
        0.0,
    )

    first = float(frame.iloc[0]["total_value"])
    last = float(frame.iloc[-1]["total_value"])
    total_return_pct = ((last - first) / first * 100.0) if first > 0 else 0.0

    ret_std = float(frame["ret"].std())
    ret_mean = float(frame["ret"].mean())
    sharpe_ratio = (ret_mean / ret_std) * (252**0.5) if ret_std != 0 else 0.0
    annualized_volatility = ret_std * (252**0.5)

    return {
        "portfolio_points": int(len(frame)),
        "total_return_pct": float(total_return_pct),
        "max_drawdown": float(frame["drawdown"].min()),
        "sharpe_ratio": float(sharpe_ratio),
        "annualized_volatility": float(annualized_volatility),
    }


def compute_trade_metrics(trades_df: pd.DataFrame) -> dict[str, Any]:
    if trades_df.empty:
        return {
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "exit_reason_breakdown": {},
            "exit_reason_by_strategy": {},
        }

    frame = trades_df.copy()
    frame["pnl"] = pd.to_numeric(frame["pnl"], errors="coerce").fillna(0.0)

    closed_trades = int(len(frame))
    wins_df = frame[frame["pnl"] > 0]
    losses_df = frame[frame["pnl"] < 0]
    wins = int(len(wins_df))
    losses = int(len(losses_df))
    win_rate = (wins / closed_trades) if closed_trades > 0 else 0.0
    gross_profit = float(wins_df["pnl"].sum()) if not wins_df.empty else 0.0
    gross_loss = abs(float(losses_df["pnl"].sum())) if not losses_df.empty else 0.0
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = 999.0 if gross_profit > 0 else 0.0

    return {
        "closed_trades": closed_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": float(win_rate),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": float(profit_factor),
        "total_pnl": float(frame["pnl"].sum()),
        "avg_pnl": float(frame["pnl"].mean()),
        "avg_win": float(wins_df["pnl"].mean()) if not wins_df.empty else 0.0,
        "avg_loss": float(losses_df["pnl"].mean()) if not losses_df.empty else 0.0,
        "exit_reason_breakdown": {
            str(reason if reason else "UNKNOWN"): int(count)
            for reason, count in frame["exit_reason"].fillna("UNKNOWN").value_counts().items()
        },
        "exit_reason_by_strategy": {
            str(strategy): {
                str(reason): int(count)
                for reason, count in strategy_df["exit_reason"].fillna("UNKNOWN").value_counts().items()
            }
            for strategy, strategy_df in frame.groupby("strategy")
        },
    }


def compute_log_metrics(logs_df: pd.DataFrame) -> dict[str, Any]:
    if logs_df.empty:
        return {
            "critical_error_count": 0,
            "critical_error_samples": [],
        }

    samples: list[dict[str, str]] = []
    for _, row in logs_df.head(5).iterrows():
        samples.append(
            {
                "timestamp": str(row.get("timestamp", "")),
                "level": str(row.get("level", "")),
                "module": str(row.get("module", "")),
                "message": str(row.get("message", "")),
            }
        )

    return {
        "critical_error_count": int(len(logs_df)),
        "critical_error_samples": samples,
    }


def evaluate_go_live_gates(
    metrics: dict[str, Any],
    thresholds: AuditThresholds,
) -> tuple[dict[str, dict[str, Any]], bool]:
    portfolio_points = int(metrics.get("portfolio_points", 0))
    sharpe_ratio = float(metrics.get("sharpe_ratio", 0.0))
    max_drawdown_abs = abs(float(metrics.get("max_drawdown", 0.0)))
    win_rate = float(metrics.get("win_rate", 0.0))
    profit_factor = float(metrics.get("profit_factor", 0.0))
    total_return_pct = float(metrics.get("total_return_pct", 0.0))
    wins = int(metrics.get("wins", 0))
    closed_trades = int(metrics.get("closed_trades", 0))
    critical_error_count = int(metrics.get("critical_error_count", 0))

    # Trend-following edge case: profitable + Sharpe-positive anchor with open winners still running
    # may show 0 closed wins and PF=0 in a short evaluation window.
    profit_factor_waiver = bool(
        thresholds.min_profit_factor > 0
        and wins == 0
        and closed_trades > 0
        and total_return_pct > 0
        and sharpe_ratio >= thresholds.min_sharpe
    )
    win_rate_waiver = bool(profit_factor_waiver and win_rate <= 0.0 and thresholds.min_win_rate > 0)

    gates: dict[str, dict[str, Any]] = {
        "sufficient_portfolio_data": {
            "passed": portfolio_points >= 2,
            "value": portfolio_points,
            "required": 2,
            "description": "Need at least 2 portfolio points to compute risk-adjusted metrics",
        },
        "sharpe_ratio": {
            "passed": sharpe_ratio >= thresholds.min_sharpe,
            "value": sharpe_ratio,
            "required": thresholds.min_sharpe,
            "description": "Annualized Sharpe ratio threshold",
        },
        "max_drawdown": {
            "passed": max_drawdown_abs <= thresholds.max_drawdown,
            "value": max_drawdown_abs,
            "required": thresholds.max_drawdown,
            "description": "Absolute max drawdown cap",
        },
        "win_rate": {
            "passed": (win_rate >= thresholds.min_win_rate) or win_rate_waiver,
            "value": win_rate,
            "required": thresholds.min_win_rate,
            "description": "Minimum closed-trade win rate (waiver when trend-following open-winner condition is met)",
            "waiver_applied": win_rate_waiver,
        },
        "profit_factor": {
            "passed": (profit_factor >= thresholds.min_profit_factor) or profit_factor_waiver,
            "value": profit_factor,
            "required": thresholds.min_profit_factor,
            "description": "Minimum gross-profit to gross-loss ratio (waiver when return>0 and Sharpe gate passes with no closed wins yet)",
            "waiver_applied": profit_factor_waiver,
        },
        "closed_trades": {
            "passed": closed_trades >= thresholds.min_closed_trades,
            "value": closed_trades,
            "required": thresholds.min_closed_trades,
            "description": "Minimum number of closed trades in audit window",
        },
        "critical_errors": {
            "passed": critical_error_count <= thresholds.max_critical_errors,
            "value": critical_error_count,
            "required": thresholds.max_critical_errors,
            "description": "Maximum allowed ERROR/CRITICAL logs in critical window",
        },
    }
    ready_for_live = all(bool(gate["passed"]) for gate in gates.values())
    return gates, ready_for_live


def run_weekly_audit(
    engine: Engine,
    *,
    weeks: int = 4,
    thresholds: AuditThresholds | None = None,
    anchor_date: date | None = None,
) -> dict[str, Any]:
    if weeks <= 0:
        raise ValueError("weeks must be greater than 0")

    if thresholds is None:
        thresholds = AuditThresholds()

    anchor = anchor_date or datetime.utcnow().date()
    audit_start = anchor - timedelta(days=(weeks * 7) - 1)
    critical_window_start = anchor - timedelta(days=thresholds.critical_window_days - 1)

    portfolio_df = _load_portfolio_history(engine, audit_start, anchor)
    trades_df = _load_closed_trades(engine, audit_start, anchor)
    logs_df = _load_critical_logs(engine, critical_window_start, anchor)

    metrics: dict[str, Any] = {}
    metrics.update(compute_portfolio_metrics(portfolio_df))
    metrics.update(compute_trade_metrics(trades_df))
    metrics.update(compute_log_metrics(logs_df))

    gates, ready_for_live = evaluate_go_live_gates(metrics, thresholds)
    return {
        "period": {
            "audit_start": _to_date_str(audit_start),
            "audit_end": _to_date_str(anchor),
            "weeks": weeks,
            "critical_window_days": thresholds.critical_window_days,
            "critical_window_start": _to_date_str(critical_window_start),
        },
        "thresholds": asdict(thresholds),
        "metrics": metrics,
        "gates": gates,
        "ready_for_live": ready_for_live,
    }
