from __future__ import annotations

from trading_bot.config.settings import Config
from trading_bot.monitoring.performance_audit import AuditThresholds


def resolve_go_live_profile(explicit_profile: str | None = None) -> str:
    raw = (explicit_profile if explicit_profile is not None else Config.GO_LIVE_PROFILE).strip().lower()
    if raw in {"baseline", "adaptive"}:
        return raw

    only_adaptive = (
        bool(Config.ENABLE_ADAPTIVE_TREND)
        and not bool(Config.ENABLE_MOMENTUM_BREAKOUT)
        and not bool(Config.ENABLE_MEAN_REVERSION)
        and not bool(Config.ENABLE_SECTOR_ROTATION)
        and not bool(Config.ENABLE_BEAR_REVERSAL)
        and not bool(Config.ENABLE_VOLATILITY_REVERSAL)
    )
    return "adaptive" if only_adaptive else "baseline"


def build_audit_thresholds(profile: str | None = None) -> AuditThresholds:
    active_profile = resolve_go_live_profile(profile)
    if active_profile == "adaptive":
        return AuditThresholds(
            min_sharpe=Config.ADAPTIVE_GO_LIVE_MIN_SHARPE,
            max_drawdown=Config.ADAPTIVE_GO_LIVE_MAX_DRAWDOWN,
            min_win_rate=Config.ADAPTIVE_GO_LIVE_MIN_WIN_RATE,
            min_profit_factor=Config.ADAPTIVE_GO_LIVE_MIN_PROFIT_FACTOR,
            min_closed_trades=Config.ADAPTIVE_GO_LIVE_MIN_CLOSED_TRADES,
            max_critical_errors=Config.ADAPTIVE_GO_LIVE_MAX_CRITICAL_ERRORS,
            critical_window_days=Config.ADAPTIVE_GO_LIVE_CRITICAL_WINDOW_DAYS,
        )
    return AuditThresholds(
        min_sharpe=Config.GO_LIVE_MIN_SHARPE,
        max_drawdown=Config.GO_LIVE_MAX_DRAWDOWN,
        min_win_rate=Config.GO_LIVE_MIN_WIN_RATE,
        min_profit_factor=Config.GO_LIVE_MIN_PROFIT_FACTOR,
        min_closed_trades=Config.GO_LIVE_MIN_CLOSED_TRADES,
        max_critical_errors=Config.GO_LIVE_MAX_CRITICAL_ERRORS,
        critical_window_days=Config.GO_LIVE_CRITICAL_WINDOW_DAYS,
    )


def required_paper_weeks(profile: str | None = None) -> int:
    active_profile = resolve_go_live_profile(profile)
    if active_profile == "adaptive":
        return int(Config.ADAPTIVE_PAPER_RUN_REQUIRED_WEEKS)
    return int(Config.PAPER_RUN_REQUIRED_WEEKS)
