from __future__ import annotations

from typing import Any

import pandas as pd

from trading_bot.config.settings import Config


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return float(max(lower, min(upper, value)))


def compute_market_regime(market_data: pd.DataFrame) -> dict[str, Any]:
    if market_data.empty:
        return {
            "is_favorable": True,
            "regime_label": "unknown",
            "trend_up": True,
            "annualized_volatility": 0.0,
            "volatility_threshold": float(Config.MOMENTUM_REGIME_MAX_ANNUAL_VOL),
            "breadth_ratio": 1.0,
            "breadth_threshold": Config.ADAPTIVE_DEFENSIVE_MIN_BREADTH,
            "confidence": 0.5,
            "eligible_symbols": 0,
            "reason": "empty_market_data",
        }

    vol_window = max(5, int(Config.MOMENTUM_REGIME_VOL_WINDOW))
    proxy_sma_period = max(5, int(Config.MOMENTUM_REGIME_SMA_PERIOD))
    period = max(2, int(Config.ADAPTIVE_DEFENSIVE_BREADTH_SMA_PERIOD))
    frame = market_data[["symbol", "date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["symbol", "date", "close"])
    if frame.empty:
        return {
            "is_favorable": True,
            "regime_label": "unknown",
            "trend_up": True,
            "annualized_volatility": 0.0,
            "volatility_threshold": float(Config.MOMENTUM_REGIME_MAX_ANNUAL_VOL),
            "breadth_ratio": 1.0,
            "breadth_threshold": Config.ADAPTIVE_DEFENSIVE_MIN_BREADTH,
            "confidence": 0.5,
            "eligible_symbols": 0,
            "reason": "no_valid_points",
        }

    frame = frame.sort_values(["symbol", "date"])
    frame["sma"] = frame.groupby("symbol")["close"].transform(lambda series: series.rolling(period).mean())
    latest = frame.dropna(subset=["sma"]).groupby("symbol", as_index=False).tail(1)
    eligible = int(len(latest))
    min_eligible = max(1, int(Config.ADAPTIVE_DEFENSIVE_MIN_ELIGIBLE_SYMBOLS))
    if eligible < min_eligible:
        return {
            "is_favorable": True,
            "regime_label": "warmup",
            "trend_up": True,
            "annualized_volatility": 0.0,
            "volatility_threshold": float(Config.MOMENTUM_REGIME_MAX_ANNUAL_VOL),
            "breadth_ratio": 1.0,
            "breadth_threshold": Config.ADAPTIVE_DEFENSIVE_MIN_BREADTH,
            "confidence": 0.5,
            "eligible_symbols": eligible,
            "reason": "insufficient_symbols",
        }

    breadth_ratio = float((latest["close"] > latest["sma"]).mean())
    threshold = float(Config.ADAPTIVE_DEFENSIVE_MIN_BREADTH)
    close_pivot = frame.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
    proxy_returns = close_pivot.pct_change(fill_method=None).mean(axis=1, skipna=True).fillna(0.0)
    proxy = (1.0 + proxy_returns).cumprod() * 100.0

    min_proxy_points = max(proxy_sma_period, vol_window) + 5
    if len(proxy) < min_proxy_points:
        trend_up = True
        latest_vol = 0.0
        low_vol = True
        reason = "proxy_warmup"
    else:
        proxy_sma = proxy.rolling(proxy_sma_period).mean()
        ann_vol = proxy_returns.rolling(vol_window).std() * (252**0.5)
        latest_close = float(proxy.iloc[-1])
        latest_sma = float(proxy_sma.iloc[-1]) if pd.notna(proxy_sma.iloc[-1]) else latest_close
        latest_vol = float(ann_vol.iloc[-1]) if pd.notna(ann_vol.iloc[-1]) else 0.0
        trend_up = latest_close >= (latest_sma * 0.99)
        low_vol = latest_vol <= float(Config.MOMENTUM_REGIME_MAX_ANNUAL_VOL)
        reason = "computed"

    is_favorable = bool((breadth_ratio >= threshold) and trend_up and low_vol)
    if is_favorable:
        regime_label = "favorable"
    elif (not trend_up) and (breadth_ratio < (threshold * 0.9)):
        regime_label = "bearish"
    elif low_vol and breadth_ratio >= (threshold * 0.8):
        regime_label = "choppy"
    else:
        regime_label = "defensive"

    vol_limit = max(float(Config.MOMENTUM_REGIME_MAX_ANNUAL_VOL), 1e-6)
    if latest_vol <= vol_limit:
        vol_score = 1.0
    else:
        vol_score = max(0.0, 1.0 - ((latest_vol - vol_limit) / vol_limit))
    confidence = _clamp((0.40 * breadth_ratio) + (0.35 * (1.0 if trend_up else 0.0)) + (0.25 * vol_score))

    return {
        "is_favorable": is_favorable,
        "regime_label": regime_label,
        "trend_up": bool(trend_up),
        "annualized_volatility": float(latest_vol),
        "volatility_threshold": float(Config.MOMENTUM_REGIME_MAX_ANNUAL_VOL),
        "breadth_ratio": breadth_ratio,
        "breadth_threshold": threshold,
        "confidence": confidence,
        "eligible_symbols": eligible,
        "reason": reason,
    }
