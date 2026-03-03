from __future__ import annotations

from trading_bot.config.settings import Config
from trading_bot.strategies.cross_sectional_momentum import CrossSectionalMomentumStrategy


def build_csm_strategy(
    *,
    log_signals: bool = True,
    initial_capital: float = 100000.0,
) -> CrossSectionalMomentumStrategy:
    return CrossSectionalMomentumStrategy(
        top_n=Config.CSM_TOP_N,
        lookback_months=Config.CSM_LOOKBACK_MONTHS,
        skip_recent_months=Config.CSM_SKIP_RECENT_MONTHS,
        trailing_stop_pct=Config.CSM_TRAILING_STOP_PCT,
        min_history_days=Config.CSM_MIN_HISTORY_DAYS,
        initial_capital=initial_capital,
        log_signals=log_signals,
    )
