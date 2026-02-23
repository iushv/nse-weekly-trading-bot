from __future__ import annotations

from trading_bot.config.settings import Config
from trading_bot.strategies.adaptive_trend import AdaptiveTrendFollowingStrategy


def build_adaptive_trend_strategy(*, log_signals: bool = True) -> AdaptiveTrendFollowingStrategy:
    return AdaptiveTrendFollowingStrategy(
        weekly_ema_short=Config.ADAPTIVE_TREND_WEEKLY_EMA_SHORT,
        weekly_ema_long=Config.ADAPTIVE_TREND_WEEKLY_EMA_LONG,
        weekly_atr_period=Config.ADAPTIVE_TREND_WEEKLY_ATR_PERIOD,
        weekly_rsi_period=Config.ADAPTIVE_TREND_WEEKLY_RSI_PERIOD,
        min_weekly_roc=Config.ADAPTIVE_TREND_MIN_WEEKLY_ROC,
        max_weekly_roc=Config.ADAPTIVE_TREND_MAX_WEEKLY_ROC,
        daily_rsi_min=Config.ADAPTIVE_DAILY_RSI_MIN,
        daily_rsi_max=Config.ADAPTIVE_DAILY_RSI_MAX,
        min_volume_ratio=Config.ADAPTIVE_MIN_VOLUME_RATIO,
        min_weekly_ema_spread_pct=Config.ADAPTIVE_TREND_MIN_WEEKLY_EMA_SPREAD_PCT,
        min_trend_consistency=Config.ADAPTIVE_TREND_MIN_TREND_CONSISTENCY,
        min_expected_r_mult=Config.ADAPTIVE_TREND_MIN_EXPECTED_R_MULT,
        stop_atr_mult=Config.ADAPTIVE_TREND_STOP_ATR_MULT,
        profit_protect_pct=Config.ADAPTIVE_TREND_PROFIT_PROTECT_PCT,
        profit_trail_atr_mult=Config.ADAPTIVE_TREND_PROFIT_TRAIL_ATR_MULT,
        trail_tier2_gain=Config.ADAPTIVE_TREND_TRAIL_TIER2_GAIN,
        trail_tier2_mult=Config.ADAPTIVE_TREND_TRAIL_TIER2_MULT,
        trail_tier3_gain=Config.ADAPTIVE_TREND_TRAIL_TIER3_GAIN,
        trail_tier3_mult=Config.ADAPTIVE_TREND_TRAIL_TIER3_MULT,
        breakeven_gain_pct=Config.ADAPTIVE_TREND_BREAKEVEN_GAIN_PCT,
        breakeven_buffer_pct=Config.ADAPTIVE_TREND_BREAKEVEN_BUFFER_PCT,
        max_weekly_atr_pct=Config.ADAPTIVE_TREND_MAX_WEEKLY_ATR_PCT,
        transaction_cost_pct=Config.TOTAL_COST_PER_TRADE,
        max_positions=Config.ADAPTIVE_TREND_MAX_POSITIONS,
        max_new_per_week=Config.ADAPTIVE_TREND_MAX_NEW_PER_WEEK,
        min_hold_days=Config.ADAPTIVE_TREND_MIN_HOLD_DAYS,
        time_stop_days=Config.ADAPTIVE_TREND_TIME_STOP_DAYS,
        regime_min_breadth=Config.ADAPTIVE_TREND_REGIME_MIN_BREADTH,
        regime_max_vol=Config.ADAPTIVE_TREND_REGIME_MAX_VOL,
        log_signals=log_signals,
    )
