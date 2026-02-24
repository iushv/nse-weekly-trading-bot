from __future__ import annotations

from trading_bot.config.settings import Config


def size_position(price: float, stop_loss: float, capital: float, cash_available: float) -> int:
    risk_amount = capital * Config.RISK_PER_TRADE
    risk_per_share = price - stop_loss
    if risk_per_share <= 0:
        return 0

    shares = int(risk_amount / risk_per_share)
    max_value = capital * Config.MAX_POSITION_SIZE
    shares = min(shares, int(max_value / price))
    if Config.MAX_LOSS_PER_TRADE > 0:
        max_loss_shares = int((capital * Config.MAX_LOSS_PER_TRADE) / risk_per_share)
        shares = min(shares, max_loss_shares)

    needed = shares * price * (1 + Config.COST_PER_SIDE)
    if needed > cash_available:
        shares = int(cash_available / (price * (1 + Config.COST_PER_SIDE)))

    return max(shares, 0)


def size_position_adaptive(
    *,
    price: float,
    stop_loss: float,
    capital: float,
    cash_available: float,
    confidence: float,
    win_rate: float,
    avg_win_loss_ratio: float,
    current_drawdown: float,
    sector_exposure: float,
    regime_size_multiplier: float = 1.0,
) -> int:
    """
    Adaptive sizing for lower-frequency strategies.

    Uses half-Kelly with confidence, drawdown, and sector-exposure dampening.
    """
    risk_per_share = price - stop_loss
    if risk_per_share <= 0 or price <= 0 or capital <= 0 or cash_available <= 0:
        return 0

    w = max(0.0, min(1.0, win_rate))
    r = max(0.1, avg_win_loss_ratio)
    kelly = w - ((1.0 - w) / r)
    half_kelly = max(0.0, kelly / 2.0)
    kelly_cap = 0.06
    base_fraction = min(half_kelly, kelly_cap)

    # Keep a minimum allocation so the strategy can collect learning data.
    if base_fraction <= 0:
        base_fraction = min(Config.RISK_PER_TRADE, 0.01)

    conf_scale = 0.5 + max(0.0, min(1.0, confidence))

    # Linear drawdown throttling: 100% at 0 DD to 40% at 15% DD.
    dd = max(0.0, min(0.15, current_drawdown))
    drawdown_scale = 1.0 - (0.6 * (dd / 0.15))
    drawdown_scale = max(0.4, min(1.0, drawdown_scale))

    # Reduce new size in concentrated sectors.
    sector_scale = 0.6 if sector_exposure > 0.15 else 1.0
    regime_scale = max(0.0, float(regime_size_multiplier))

    risk_amount = capital * base_fraction * conf_scale * drawdown_scale * sector_scale * regime_scale
    shares = int(risk_amount / risk_per_share)

    max_value = capital * Config.MAX_POSITION_SIZE
    shares = min(shares, int(max_value / price))
    if Config.MAX_LOSS_PER_TRADE > 0:
        max_loss_shares = int((capital * Config.MAX_LOSS_PER_TRADE) / risk_per_share)
        shares = min(shares, max_loss_shares)

    needed = shares * price * (1 + Config.COST_PER_SIDE)
    if needed > cash_available:
        shares = int(cash_available / (price * (1 + Config.COST_PER_SIDE)))

    return max(shares, 0)
