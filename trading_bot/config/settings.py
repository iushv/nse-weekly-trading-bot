import os
from datetime import time
from typing import Any, cast

import pytz
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class Config:
    # Environment
    ENVIRONMENT = os.getenv("ENVIRONMENT", "paper").lower()
    STRATEGY_PROFILE = os.getenv("STRATEGY_PROFILE", "baseline").strip().lower()

    # API Credentials
    GROWW_API_KEY = os.getenv("GROWW_API_KEY")
    GROWW_API_SECRET = os.getenv("GROWW_API_SECRET")
    GROWW_TOKEN_MODE = os.getenv("GROWW_TOKEN_MODE", "approval")
    GROWW_ACCESS_TOKEN = os.getenv("GROWW_ACCESS_TOKEN")
    GROWW_TOTP = os.getenv("GROWW_TOTP")
    GROWW_APP_ID = os.getenv("GROWW_APP_ID", "").strip()
    BROKER_PROVIDER = os.getenv("BROKER_PROVIDER", "mock").lower()
    BROKER_BASE_URL = os.getenv("BROKER_BASE_URL", "").strip()
    LIVE_ORDER_ACK_PHRASE = "YES_I_UNDERSTAND_LIVE_ORDERS"
    LIVE_ORDER_EXECUTION_ENABLED = _env_bool("LIVE_ORDER_EXECUTION_ENABLED", False)
    LIVE_ORDER_FORCE_ACK = os.getenv("LIVE_ORDER_FORCE_ACK", "").strip()
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    RECONCILIATION_ENFORCE_CLOSE = _env_bool("RECONCILIATION_ENFORCE_CLOSE", False)
    RECONCILIATION_LOOKBACK_DAYS = _env_int("RECONCILIATION_LOOKBACK_DAYS", 30)
    GO_LIVE_MIN_SHARPE = _env_float("GO_LIVE_MIN_SHARPE", 0.7)
    GO_LIVE_MAX_DRAWDOWN = _env_float("GO_LIVE_MAX_DRAWDOWN", 0.15)
    GO_LIVE_MIN_WIN_RATE = _env_float("GO_LIVE_MIN_WIN_RATE", 0.5)
    GO_LIVE_MIN_PROFIT_FACTOR = _env_float("GO_LIVE_MIN_PROFIT_FACTOR", 0.0)
    GO_LIVE_MIN_CLOSED_TRADES = _env_int("GO_LIVE_MIN_CLOSED_TRADES", 10)
    GO_LIVE_MAX_CRITICAL_ERRORS = _env_int("GO_LIVE_MAX_CRITICAL_ERRORS", 0)
    GO_LIVE_CRITICAL_WINDOW_DAYS = _env_int("GO_LIVE_CRITICAL_WINDOW_DAYS", 14)
    GO_LIVE_PROFILE = os.getenv("GO_LIVE_PROFILE", "auto").strip().lower()
    ADAPTIVE_GO_LIVE_MIN_SHARPE = _env_float("ADAPTIVE_GO_LIVE_MIN_SHARPE", 0.7)
    ADAPTIVE_GO_LIVE_MAX_DRAWDOWN = _env_float("ADAPTIVE_GO_LIVE_MAX_DRAWDOWN", 0.15)
    ADAPTIVE_GO_LIVE_MIN_WIN_RATE = _env_float("ADAPTIVE_GO_LIVE_MIN_WIN_RATE", 0.30)
    ADAPTIVE_GO_LIVE_MIN_PROFIT_FACTOR = _env_float("ADAPTIVE_GO_LIVE_MIN_PROFIT_FACTOR", 1.20)
    ADAPTIVE_GO_LIVE_MIN_CLOSED_TRADES = _env_int("ADAPTIVE_GO_LIVE_MIN_CLOSED_TRADES", 3)
    ADAPTIVE_GO_LIVE_MAX_CRITICAL_ERRORS = _env_int("ADAPTIVE_GO_LIVE_MAX_CRITICAL_ERRORS", 0)
    ADAPTIVE_GO_LIVE_CRITICAL_WINDOW_DAYS = _env_int("ADAPTIVE_GO_LIVE_CRITICAL_WINDOW_DAYS", 14)
    AUDIT_TREND_LOOKBACK = _env_int("AUDIT_TREND_LOOKBACK", 8)
    RETENTION_DAYS = _env_int("RETENTION_DAYS", 30)
    RETENTION_ARCHIVE_ROOT = os.getenv("RETENTION_ARCHIVE_ROOT", "archive").strip()
    RETENTION_SOURCES = [
        item.strip()
        for item in os.getenv(
            "RETENTION_SOURCES",
            "logs,reports/audits,reports/promotion,reports/rollback,reports/incidents,reports/retention",
        ).split(",")
        if item.strip()
    ]
    PAPER_RUN_REQUIRED_WEEKS = _env_int("PAPER_RUN_REQUIRED_WEEKS", 4)
    ADAPTIVE_PAPER_RUN_REQUIRED_WEEKS = _env_int("ADAPTIVE_PAPER_RUN_REQUIRED_WEEKS", 6)
    PAPER_RUN_REQUIRE_PROMOTION_BUNDLE = _env_bool("PAPER_RUN_REQUIRE_PROMOTION_BUNDLE", True)
    # Runtime auto-resume for local/VPS restarts.
    AUTO_RESUME_ENABLED = _env_bool("AUTO_RESUME_ENABLED", True)
    AUTO_RESUME_INTERVAL_SECONDS = _env_int("AUTO_RESUME_INTERVAL_SECONDS", 60)
    AUTO_RESUME_PREMARKET_START = os.getenv("AUTO_RESUME_PREMARKET_START", "08:00").strip()
    AUTO_RESUME_PREMARKET_CUTOFF = os.getenv("AUTO_RESUME_PREMARKET_CUTOFF", "10:00").strip()
    AUTO_RESUME_MARKET_OPEN_START = os.getenv("AUTO_RESUME_MARKET_OPEN_START", "09:15").strip()
    AUTO_RESUME_MARKET_OPEN_CUTOFF = os.getenv("AUTO_RESUME_MARKET_OPEN_CUTOFF", "11:30").strip()
    AUTO_RESUME_MARKET_CLOSE_START = os.getenv("AUTO_RESUME_MARKET_CLOSE_START", "15:30").strip()
    AUTO_RESUME_MARKET_CLOSE_CUTOFF = os.getenv("AUTO_RESUME_MARKET_CLOSE_CUTOFF", "21:00").strip()

    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///trading_bot.db")

    # Capital
    STARTING_CAPITAL = _env_float("STARTING_CAPITAL", 100000.0)

    # Market Hours (IST)
    TIMEZONE = pytz.timezone("Asia/Kolkata")
    MARKET_OPEN = time(9, 15)
    MARKET_CLOSE = time(15, 30)

    # Risk Parameters
    _profile_risk_defaults = {
        "baseline": {"risk_per_trade": 0.02, "max_position_size": 0.15},
        "tuned_momentum_v2": {"risk_per_trade": 0.01, "max_position_size": 0.10},
        "tuned_momentum_v3": {"risk_per_trade": 0.01, "max_position_size": 0.12},
        "tuned_momentum_v4": {"risk_per_trade": 0.008, "max_position_size": 0.08},
        "tuned_momentum_v5": {"risk_per_trade": 0.008, "max_position_size": 0.10},
        "tuned_momentum_v6": {"risk_per_trade": 0.006, "max_position_size": 0.08},
    }
    _active_risk_defaults = _profile_risk_defaults.get(STRATEGY_PROFILE, _profile_risk_defaults["baseline"])
    MAX_PORTFOLIO_HEAT = _env_float("MAX_PORTFOLIO_HEAT", 0.12)
    MAX_POSITIONS = _env_int("MAX_POSITIONS", 10)
    MAX_POSITION_SIZE = _env_float(
        "MAX_POSITION_SIZE",
        float(_active_risk_defaults["max_position_size"]),
    )
    RISK_PER_TRADE = _env_float(
        "RISK_PER_TRADE",
        float(_active_risk_defaults["risk_per_trade"]),
    )
    DAILY_LOSS_LIMIT = _env_float("DAILY_LOSS_LIMIT", 0.03)
    WEEKLY_LOSS_LIMIT = _env_float("WEEKLY_LOSS_LIMIT", 0.05)
    MAX_DRAWDOWN = _env_float("MAX_DRAWDOWN", 0.15)

    # Transaction Costs (as decimals)
    BROKERAGE = 0.0003
    STT = 0.00025
    TRANSACTION_TAX = 0.00018
    GST = 0.000054
    SEBI_CHARGES = 0.000001
    STAMP_DUTY = 0.00015
    # Round-trip transaction cost estimate. Single-side cost is derived below.
    TOTAL_COST_PER_TRADE = _env_float("TOTAL_COST_PER_TRADE", 0.00355)
    COST_PER_SIDE = _env_float("COST_PER_SIDE", TOTAL_COST_PER_TRADE / 2.0)

    # Strategy Allocation / Runtime Toggles
    STRATEGY_ALLOCATION = {
        "momentum_breakout": 0.40,
        "mean_reversion": 0.35,
        "sector_rotation": 0.25,
    }
    _profile_strategy_defaults = {
        "baseline": {
            "enable_momentum_breakout": True,
            "enable_mean_reversion": True,
            "enable_sector_rotation": True,
            "momentum": {
                "lookback_period": 20,
                "min_history": 60,
                "volume_multiplier": 1.2,
                "min_roc": 0.05,
                "max_atr_pct": 0.05,
                "stop_atr_mult": 2.0,
                "rr_ratio": 2.0,
                "time_stop_days": 10,
                "time_stop_move_pct": 0.02,
            },
            "mean_reversion": {
                "oversold_buffer": 5.0,
                "trend_tolerance": 0.95,
                "bb_entry_mult": 1.01,
                "volume_cap": 2.5,
                "stop_bb_buffer": 0.98,
                "stop_sma_buffer": 0.98,
                "stop_atr_mult": 1.5,
                "target_gain_pct": 0.08,
                "time_stop_days": 7,
            },
        },
        "tuned_momentum_v2": {
            "enable_momentum_breakout": True,
            "enable_mean_reversion": False,
            "enable_sector_rotation": False,
            "momentum": {
                "lookback_period": 15,
                "min_history": 60,
                "volume_multiplier": 1.0,
                "min_roc": 0.07,
                "max_atr_pct": 0.04,
                "stop_atr_mult": 1.5,
                "rr_ratio": 2.0,
                "time_stop_days": 14,
                "time_stop_move_pct": 0.02,
            },
            "mean_reversion": {
                "oversold_buffer": 3.0,
                "trend_tolerance": 0.93,
                "bb_entry_mult": 1.0,
                "volume_cap": 2.0,
                "stop_bb_buffer": 0.97,
                "stop_sma_buffer": 0.97,
                "stop_atr_mult": 1.0,
                "target_gain_pct": 0.08,
                "time_stop_days": 7,
            },
        },
        "tuned_momentum_v3": {
            "enable_momentum_breakout": True,
            "enable_mean_reversion": False,
            "enable_sector_rotation": False,
            "momentum": {
                "lookback_period": 15,
                "min_history": 60,
                "volume_multiplier": 1.0,
                "min_roc": 0.02,
                "max_atr_pct": 0.04,
                "stop_atr_mult": 1.0,
                "rr_ratio": 1.0,
                "time_stop_days": 5,
                "time_stop_move_pct": 0.005,
            },
            "mean_reversion": {
                "oversold_buffer": 3.0,
                "trend_tolerance": 0.93,
                "bb_entry_mult": 1.0,
                "volume_cap": 2.0,
                "stop_bb_buffer": 0.97,
                "stop_sma_buffer": 0.97,
                "stop_atr_mult": 1.0,
                "target_gain_pct": 0.08,
                "time_stop_days": 7,
            },
        },
        "tuned_momentum_v4": {
            "enable_momentum_breakout": True,
            "enable_mean_reversion": False,
            "enable_sector_rotation": False,
            "momentum": {
                "lookback_period": 20,
                "min_history": 60,
                "volume_multiplier": 1.2,
                "min_roc": 0.05,
                "max_atr_pct": 0.03,
                "stop_atr_mult": 1.0,
                "rr_ratio": 0.9,
                "time_stop_days": 4,
                "time_stop_move_pct": 0.003,
            },
            "mean_reversion": {
                "oversold_buffer": 3.0,
                "trend_tolerance": 0.93,
                "bb_entry_mult": 1.0,
                "volume_cap": 2.0,
                "stop_bb_buffer": 0.97,
                "stop_sma_buffer": 0.97,
                "stop_atr_mult": 1.0,
                "target_gain_pct": 0.08,
                "time_stop_days": 7,
            },
        },
        "tuned_momentum_v5": {
            "enable_momentum_breakout": True,
            "enable_mean_reversion": False,
            "enable_sector_rotation": False,
            "momentum": {
                "lookback_period": 15,
                "min_history": 60,
                "volume_multiplier": 1.1,
                "min_roc": 0.03,
                "max_atr_pct": 0.035,
                "stop_atr_mult": 0.8,
                "rr_ratio": 0.8,
                "time_stop_days": 4,
                "time_stop_move_pct": 0.003,
            },
            "mean_reversion": {
                "oversold_buffer": 3.0,
                "trend_tolerance": 0.93,
                "bb_entry_mult": 1.0,
                "volume_cap": 2.0,
                "stop_bb_buffer": 0.97,
                "stop_sma_buffer": 0.97,
                "stop_atr_mult": 1.0,
                "target_gain_pct": 0.08,
                "time_stop_days": 7,
            },
        },
        "tuned_momentum_v6": {
            "enable_momentum_breakout": True,
            "enable_mean_reversion": False,
            "enable_sector_rotation": False,
            "momentum": {
                "lookback_period": 15,
                "min_history": 60,
                "volume_multiplier": 1.1,
                "min_roc": 0.03,
                "max_atr_pct": 0.035,
                "stop_atr_mult": 0.8,
                "rr_ratio": 1.0,
                "time_stop_days": 4,
                "time_stop_move_pct": 0.003,
            },
            "mean_reversion": {
                "oversold_buffer": 3.0,
                "trend_tolerance": 0.93,
                "bb_entry_mult": 1.0,
                "volume_cap": 2.0,
                "stop_bb_buffer": 0.97,
                "stop_sma_buffer": 0.97,
                "stop_atr_mult": 1.0,
                "target_gain_pct": 0.08,
                "time_stop_days": 7,
            },
        },
    }
    _active_strategy_defaults = cast(
        dict[str, Any],
        _profile_strategy_defaults.get(
            STRATEGY_PROFILE,
            _profile_strategy_defaults["baseline"],
        ),
    )
    ENABLE_MOMENTUM_BREAKOUT = _env_bool(
        "ENABLE_MOMENTUM_BREAKOUT",
        bool(_active_strategy_defaults["enable_momentum_breakout"]),
    )
    ENABLE_MEAN_REVERSION = _env_bool(
        "ENABLE_MEAN_REVERSION",
        bool(_active_strategy_defaults["enable_mean_reversion"]),
    )
    ENABLE_SECTOR_ROTATION = _env_bool(
        "ENABLE_SECTOR_ROTATION",
        bool(_active_strategy_defaults["enable_sector_rotation"]),
    )
    ENABLE_ADAPTIVE_TREND = _env_bool("ENABLE_ADAPTIVE_TREND", False)
    ENABLE_BEAR_REVERSAL = _env_bool("ENABLE_BEAR_REVERSAL", False)
    ENABLE_VOLATILITY_REVERSAL = _env_bool("ENABLE_VOLATILITY_REVERSAL", False)

    MOMENTUM_LOOKBACK_PERIOD = _env_int(
        "MOMENTUM_LOOKBACK_PERIOD",
        int(_active_strategy_defaults["momentum"]["lookback_period"]),
    )
    MOMENTUM_MIN_HISTORY = _env_int(
        "MOMENTUM_MIN_HISTORY",
        int(_active_strategy_defaults["momentum"]["min_history"]),
    )
    MOMENTUM_VOLUME_MULTIPLIER = _env_float(
        "MOMENTUM_VOLUME_MULTIPLIER",
        float(_active_strategy_defaults["momentum"]["volume_multiplier"]),
    )
    MOMENTUM_MIN_ROC = _env_float(
        "MOMENTUM_MIN_ROC",
        float(_active_strategy_defaults["momentum"]["min_roc"]),
    )
    MOMENTUM_MAX_ATR_PCT = _env_float(
        "MOMENTUM_MAX_ATR_PCT",
        float(_active_strategy_defaults["momentum"]["max_atr_pct"]),
    )
    MOMENTUM_STOP_ATR_MULT = _env_float(
        "MOMENTUM_STOP_ATR_MULT",
        float(_active_strategy_defaults["momentum"]["stop_atr_mult"]),
    )
    MOMENTUM_RR_RATIO = _env_float(
        "MOMENTUM_RR_RATIO",
        float(_active_strategy_defaults["momentum"]["rr_ratio"]),
    )
    MOMENTUM_TIME_STOP_DAYS = _env_int(
        "MOMENTUM_TIME_STOP_DAYS",
        int(_active_strategy_defaults["momentum"]["time_stop_days"]),
    )
    MOMENTUM_TIME_STOP_MOVE_PCT = _env_float(
        "MOMENTUM_TIME_STOP_MOVE_PCT",
        float(_active_strategy_defaults["momentum"]["time_stop_move_pct"]),
    )
    MOMENTUM_ENABLE_REGIME_FILTER = _env_bool("MOMENTUM_ENABLE_REGIME_FILTER", True)
    MOMENTUM_REGIME_SMA_PERIOD = _env_int("MOMENTUM_REGIME_SMA_PERIOD", 50)
    MOMENTUM_REGIME_VOL_WINDOW = _env_int("MOMENTUM_REGIME_VOL_WINDOW", 20)
    MOMENTUM_REGIME_MAX_ANNUAL_VOL = _env_float("MOMENTUM_REGIME_MAX_ANNUAL_VOL", 0.55)
    MAX_SIGNALS_PER_DAY = _env_int("MAX_SIGNALS_PER_DAY", 3)
    MIN_EXPECTED_EDGE_PCT = _env_float("MIN_EXPECTED_EDGE_PCT", 0.005)
    ADAPTIVE_DEFENSIVE_MODE_ENABLED = _env_bool("ADAPTIVE_DEFENSIVE_MODE_ENABLED", False)
    ADAPTIVE_DEFENSIVE_BREADTH_SMA_PERIOD = _env_int("ADAPTIVE_DEFENSIVE_BREADTH_SMA_PERIOD", 50)
    ADAPTIVE_DEFENSIVE_MIN_BREADTH = _env_float("ADAPTIVE_DEFENSIVE_MIN_BREADTH", 0.45)
    ADAPTIVE_DEFENSIVE_MIN_ELIGIBLE_SYMBOLS = _env_int("ADAPTIVE_DEFENSIVE_MIN_ELIGIBLE_SYMBOLS", 20)
    ADAPTIVE_DEFENSIVE_MAX_SIGNALS_PER_DAY = _env_int("ADAPTIVE_DEFENSIVE_MAX_SIGNALS_PER_DAY", 3)
    ADAPTIVE_DEFENSIVE_MIN_EXPECTED_EDGE_PCT = _env_float("ADAPTIVE_DEFENSIVE_MIN_EXPECTED_EDGE_PCT", 0.005)
    ADAPTIVE_DEFENSIVE_ALLOW_MOMENTUM = _env_bool("ADAPTIVE_DEFENSIVE_ALLOW_MOMENTUM", True)
    ADAPTIVE_DEFENSIVE_ALLOW_MEAN_REVERSION = _env_bool("ADAPTIVE_DEFENSIVE_ALLOW_MEAN_REVERSION", True)
    ADAPTIVE_DEFENSIVE_ALLOW_SECTOR_ROTATION = _env_bool("ADAPTIVE_DEFENSIVE_ALLOW_SECTOR_ROTATION", False)
    ADAPTIVE_DEFENSIVE_ALLOW_ADAPTIVE_TREND = _env_bool("ADAPTIVE_DEFENSIVE_ALLOW_ADAPTIVE_TREND", True)
    ADAPTIVE_DEFENSIVE_ALLOW_BEAR_REVERSAL = _env_bool("ADAPTIVE_DEFENSIVE_ALLOW_BEAR_REVERSAL", True)
    ADAPTIVE_DEFENSIVE_ALLOW_VOLATILITY_REVERSAL = _env_bool("ADAPTIVE_DEFENSIVE_ALLOW_VOLATILITY_REVERSAL", True)

    MEAN_REV_OVERSOLD_BUFFER = _env_float(
        "MEAN_REV_OVERSOLD_BUFFER",
        float(_active_strategy_defaults["mean_reversion"]["oversold_buffer"]),
    )
    MEAN_REV_TREND_TOLERANCE = _env_float(
        "MEAN_REV_TREND_TOLERANCE",
        float(_active_strategy_defaults["mean_reversion"]["trend_tolerance"]),
    )
    MEAN_REV_BB_ENTRY_MULT = _env_float(
        "MEAN_REV_BB_ENTRY_MULT",
        float(_active_strategy_defaults["mean_reversion"]["bb_entry_mult"]),
    )
    MEAN_REV_VOLUME_CAP = _env_float(
        "MEAN_REV_VOLUME_CAP",
        float(_active_strategy_defaults["mean_reversion"]["volume_cap"]),
    )
    MEAN_REV_STOP_BB_BUFFER = _env_float(
        "MEAN_REV_STOP_BB_BUFFER",
        float(_active_strategy_defaults["mean_reversion"]["stop_bb_buffer"]),
    )
    MEAN_REV_STOP_SMA_BUFFER = _env_float(
        "MEAN_REV_STOP_SMA_BUFFER",
        float(_active_strategy_defaults["mean_reversion"]["stop_sma_buffer"]),
    )
    MEAN_REV_STOP_ATR_MULT = _env_float(
        "MEAN_REV_STOP_ATR_MULT",
        float(_active_strategy_defaults["mean_reversion"]["stop_atr_mult"]),
    )
    MEAN_REV_TARGET_GAIN_PCT = _env_float(
        "MEAN_REV_TARGET_GAIN_PCT",
        float(_active_strategy_defaults["mean_reversion"]["target_gain_pct"]),
    )
    MEAN_REV_TIME_STOP_DAYS = _env_int(
        "MEAN_REV_TIME_STOP_DAYS",
        int(_active_strategy_defaults["mean_reversion"]["time_stop_days"]),
    )
    BEAR_REV_RSI_PERIOD = _env_int("BEAR_REV_RSI_PERIOD", 14)
    BEAR_REV_RSI_OVERSOLD = _env_float("BEAR_REV_RSI_OVERSOLD", 30.0)
    BEAR_REV_RSI_REENTRY = _env_float("BEAR_REV_RSI_REENTRY", 35.0)
    BEAR_REV_TREND_SMA_PERIOD = _env_int("BEAR_REV_TREND_SMA_PERIOD", 50)
    BEAR_REV_TREND_BELOW_SMA_MULT = _env_float("BEAR_REV_TREND_BELOW_SMA_MULT", 0.99)
    BEAR_REV_DROP_LOOKBACK_DAYS = _env_int("BEAR_REV_DROP_LOOKBACK_DAYS", 5)
    BEAR_REV_MIN_DROP_PCT = _env_float("BEAR_REV_MIN_DROP_PCT", 0.04)
    BEAR_REV_MIN_VOLUME_RATIO = _env_float("BEAR_REV_MIN_VOLUME_RATIO", 0.8)
    BEAR_REV_STOP_ATR_MULT = _env_float("BEAR_REV_STOP_ATR_MULT", 1.2)
    BEAR_REV_RR_RATIO = _env_float("BEAR_REV_RR_RATIO", 1.0)
    BEAR_REV_MAX_HOLD_DAYS = _env_int("BEAR_REV_MAX_HOLD_DAYS", 4)
    VOL_REV_RSI_PERIOD = _env_int("VOL_REV_RSI_PERIOD", 14)
    VOL_REV_RSI_REENTRY = _env_float("VOL_REV_RSI_REENTRY", 35.0)
    VOL_REV_DROP_LOOKBACK_DAYS = _env_int("VOL_REV_DROP_LOOKBACK_DAYS", 3)
    VOL_REV_MIN_DROP_PCT = _env_float("VOL_REV_MIN_DROP_PCT", 0.03)
    VOL_REV_VOL_SPIKE_MULT = _env_float("VOL_REV_VOL_SPIKE_MULT", 1.2)
    VOL_REV_MIN_ATR_PCT = _env_float("VOL_REV_MIN_ATR_PCT", 0.025)
    VOL_REV_TREND_SMA_PERIOD = _env_int("VOL_REV_TREND_SMA_PERIOD", 20)
    VOL_REV_TREND_BELOW_SMA_MULT = _env_float("VOL_REV_TREND_BELOW_SMA_MULT", 1.0)
    VOL_REV_STOP_ATR_MULT = _env_float("VOL_REV_STOP_ATR_MULT", 1.1)
    VOL_REV_RR_RATIO = _env_float("VOL_REV_RR_RATIO", 1.0)
    VOL_REV_MAX_HOLD_DAYS = _env_int("VOL_REV_MAX_HOLD_DAYS", 3)

    ADAPTIVE_TREND_WEEKLY_EMA_SHORT = _env_int("ADAPTIVE_TREND_WEEKLY_EMA_SHORT", 10)
    ADAPTIVE_TREND_WEEKLY_EMA_LONG = _env_int("ADAPTIVE_TREND_WEEKLY_EMA_LONG", 30)
    ADAPTIVE_TREND_WEEKLY_ATR_PERIOD = _env_int("ADAPTIVE_TREND_WEEKLY_ATR_PERIOD", 10)
    ADAPTIVE_TREND_WEEKLY_RSI_PERIOD = _env_int("ADAPTIVE_TREND_WEEKLY_RSI_PERIOD", 10)
    ADAPTIVE_TREND_MIN_WEEKLY_ROC = _env_float("ADAPTIVE_TREND_MIN_WEEKLY_ROC", 0.03)
    ADAPTIVE_TREND_MAX_WEEKLY_ROC = _env_float("ADAPTIVE_TREND_MAX_WEEKLY_ROC", 0.20)
    ADAPTIVE_TREND_MIN_WEEKLY_EMA_SPREAD_PCT = _env_float("ADAPTIVE_TREND_MIN_WEEKLY_EMA_SPREAD_PCT", 0.005)
    ADAPTIVE_TREND_MIN_TREND_CONSISTENCY = _env_float("ADAPTIVE_TREND_MIN_TREND_CONSISTENCY", 0.50)
    ADAPTIVE_TREND_MIN_EXPECTED_R_MULT = _env_float("ADAPTIVE_TREND_MIN_EXPECTED_R_MULT", 1.0)
    ADAPTIVE_TREND_STOP_ATR_MULT = _env_float("ADAPTIVE_TREND_STOP_ATR_MULT", 1.5)
    ADAPTIVE_TREND_MAX_POSITIONS = _env_int("ADAPTIVE_TREND_MAX_POSITIONS", 5)
    ADAPTIVE_TREND_MAX_NEW_PER_WEEK = _env_int("ADAPTIVE_TREND_MAX_NEW_PER_WEEK", 3)
    ADAPTIVE_TREND_MIN_HOLD_DAYS = _env_int("ADAPTIVE_TREND_MIN_HOLD_DAYS", 5)
    ADAPTIVE_TREND_TIME_STOP_DAYS = _env_int("ADAPTIVE_TREND_TIME_STOP_DAYS", 30)
    ADAPTIVE_TREND_PROFIT_PROTECT_PCT = _env_float("ADAPTIVE_TREND_PROFIT_PROTECT_PCT", 0.03)
    ADAPTIVE_TREND_PROFIT_TRAIL_ATR_MULT = _env_float("ADAPTIVE_TREND_PROFIT_TRAIL_ATR_MULT", 0.8)
    ADAPTIVE_TREND_BREAKEVEN_GAIN_PCT = _env_float("ADAPTIVE_TREND_BREAKEVEN_GAIN_PCT", 0.03)
    ADAPTIVE_TREND_BREAKEVEN_BUFFER_PCT = _env_float("ADAPTIVE_TREND_BREAKEVEN_BUFFER_PCT", 0.005)
    ADAPTIVE_TREND_REGIME_MIN_BREADTH = _env_float("ADAPTIVE_TREND_REGIME_MIN_BREADTH", 0.50)
    ADAPTIVE_TREND_REGIME_MAX_VOL = _env_float("ADAPTIVE_TREND_REGIME_MAX_VOL", 0.30)
    ADAPTIVE_TREND_ML_ENABLED = _env_bool("ADAPTIVE_TREND_ML_ENABLED", False)

    # Data Sources
    NIFTY_500_URL = "https://www1.nseindia.com/content/indices/ind_nifty500list.csv"
    MONEYCONTROL_BASE_URL = "https://www.moneycontrol.com"
    MARKET_DATA_PROVIDER = os.getenv("MARKET_DATA_PROVIDER", "auto").strip().lower()
    GROWW_HISTORICAL_EXCHANGE = os.getenv("GROWW_HISTORICAL_EXCHANGE", "NSE").strip().upper()
    GROWW_HISTORICAL_SEGMENT = os.getenv("GROWW_HISTORICAL_SEGMENT", "CASH").strip().upper()
    GROWW_HISTORICAL_INTERVAL = os.getenv("GROWW_HISTORICAL_INTERVAL", "1day").strip().lower()
    GROWW_HISTORICAL_CHUNK_DAYS = _env_int("GROWW_HISTORICAL_CHUNK_DAYS", 170)

    @classmethod
    def validate(cls) -> bool:
        """Validate required configs. Live mode requires broker keys."""
        missing = []
        if cls.MARKET_DATA_PROVIDER == "groww":
            if not cls.GROWW_API_KEY:
                missing.append("GROWW_API_KEY")
            if cls.GROWW_TOKEN_MODE == "approval" and not cls.GROWW_API_SECRET:
                missing.append("GROWW_API_SECRET")
            if cls.GROWW_TOKEN_MODE == "totp" and not cls.GROWW_TOTP:
                missing.append("GROWW_TOTP")
        if cls.ENVIRONMENT == "live":
            if cls.BROKER_PROVIDER == "http":
                if not cls.BROKER_BASE_URL:
                    missing.append("BROKER_BASE_URL")
                if not cls.GROWW_API_KEY:
                    missing.append("GROWW_API_KEY")
                if not cls.GROWW_API_SECRET:
                    missing.append("GROWW_API_SECRET")
            elif cls.BROKER_PROVIDER in {"groww", "groww_http"}:
                if not cls.GROWW_API_KEY:
                    missing.append("GROWW_API_KEY")
                if cls.GROWW_TOKEN_MODE == "approval" and not cls.GROWW_API_SECRET:
                    missing.append("GROWW_API_SECRET")
                if cls.GROWW_TOKEN_MODE == "totp" and not cls.GROWW_TOTP:
                    missing.append("GROWW_TOTP")

        if missing:
            raise ValueError(f"Missing required config: {', '.join(missing)}")
        if not (
            cls.ENABLE_MOMENTUM_BREAKOUT
            or cls.ENABLE_MEAN_REVERSION
            or cls.ENABLE_SECTOR_ROTATION
            or cls.ENABLE_ADAPTIVE_TREND
            or cls.ENABLE_BEAR_REVERSAL
            or cls.ENABLE_VOLATILITY_REVERSAL
        ):
            raise ValueError("At least one strategy must be enabled")
        return True
