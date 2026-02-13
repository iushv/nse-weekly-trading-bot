from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from trading_bot.strategies.base_strategy import BaseStrategy, Signal


class MomentumBreakoutStrategy(BaseStrategy):
    def __init__(
        self,
        lookback_period: int = 20,
        min_history: int = 60,
        volume_multiplier: float = 1.2,
        min_roc: float = 0.05,
        max_atr_pct: float = 0.05,
        stop_atr_mult: float = 2.0,
        rr_ratio: float = 2.0,
        time_stop_days: int = 10,
        time_stop_move_pct: float = 0.02,
        enable_regime_filter: bool = True,
        regime_sma_period: int = 50,
        regime_vol_window: int = 20,
        regime_max_annual_vol: float = 0.35,
        log_signals: bool = True,
    ) -> None:
        super().__init__("Momentum Breakout")
        self.lookback_period = int(lookback_period)
        self.min_history = int(min_history)
        self.volume_multiplier = float(volume_multiplier)
        self.min_roc = float(min_roc)
        self.max_atr_pct = float(max_atr_pct)
        self.stop_atr_mult = float(stop_atr_mult)
        self.rr_ratio = float(rr_ratio)
        self.time_stop_days = int(time_stop_days)
        self.time_stop_move_pct = float(time_stop_move_pct)
        self.enable_regime_filter = bool(enable_regime_filter)
        self.regime_sma_period = int(regime_sma_period)
        self.regime_vol_window = int(regime_vol_window)
        self.regime_max_annual_vol = float(regime_max_annual_vol)
        self.log_signals_enabled = bool(log_signals)

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict[str, Any] | None = None,
    ) -> list[Signal]:
        signals: list[Signal] = []
        if market_data.empty:
            return signals

        regime = market_regime or self._compute_market_regime(market_data)
        if self.enable_regime_filter and not bool(regime.get("is_favorable", True)):
            return signals

        for symbol in market_data["symbol"].dropna().unique():
            df = market_data[market_data["symbol"] == symbol].copy().sort_values("date")
            if len(df) < self.min_history:
                continue

            df = self._add_indicators(df)
            latest = df.iloc[-1]
            if self._check_entry_conditions(latest):
                price = float(latest["close"])
                atr = float(latest["ATR"]) if pd.notna(latest["ATR"]) else 0.0
                if atr <= 0:
                    continue
                stop_loss = float(price - (self.stop_atr_mult * atr))
                target = self.calculate_target(price, stop_loss, rr=self.rr_ratio)
                risk = max(price - stop_loss, 1e-9)
                reward = max(target - price, 0.0)
                confidence = self._compute_confidence(
                    roc=float(latest["ROC_20"]),
                    volume_ratio=float(latest["volume"] / latest["Volume_MA"]),
                    atr_pct=float(latest["ATR_Pct"]),
                    reward_to_risk=reward / risk,
                )

                signal = Signal(
                    symbol=symbol,
                    action="BUY",
                    price=price,
                    quantity=0,
                    stop_loss=stop_loss,
                    target=target,
                    strategy=self.name,
                    confidence=confidence,
                    timestamp=datetime.now(),
                    metadata={
                        "roc_20": float(latest["ROC_20"]),
                        "volume_ratio": float(latest["volume"] / latest["Volume_MA"]),
                        "atr_pct": float(latest["ATR_Pct"]),
                        "regime_favorable": bool(regime.get("is_favorable", True)),
                        "regime_label": str(regime.get("regime_label", "favorable")),
                        "regime_confidence": float(regime.get("confidence", 0.5)),
                        "regime_trend_up": bool(regime.get("trend_up", True)),
                        "regime_annual_vol": float(regime.get("annualized_volatility", 0.0)),
                    },
                )
                if self.log_signals_enabled:
                    self.log_signal(signal)
                signals.append(signal)

        return signals

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["SMA_50"] = out["close"].rolling(50).mean()
        out["ROC_20"] = out["close"].pct_change(self.lookback_period)
        # Breakout reference must exclude current candle to avoid look-ahead bias.
        out["Prev_High_20"] = out["high"].rolling(self.lookback_period).max().shift(1)
        out["Volume_MA"] = out["volume"].rolling(self.lookback_period).mean()

        high_low = out["high"] - out["low"]
        high_close = (out["high"] - out["close"].shift()).abs()
        low_close = (out["low"] - out["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        out["ATR"] = tr.rolling(14).mean()
        out["ATR_Pct"] = out["ATR"] / out["close"]
        return out

    def _check_entry_conditions(self, latest: pd.Series) -> bool:
        checks = [
            latest.get("close", 0) > latest.get("SMA_50", float("inf")),
            latest.get("ROC_20", 0) > self.min_roc,
            latest.get("close", 0) > latest.get("Prev_High_20", float("inf")),
            latest.get("volume", 0) > latest.get("Volume_MA", float("inf")) * self.volume_multiplier,
            latest.get("ATR_Pct", 1) < self.max_atr_pct,
        ]
        return all(checks)

    def _compute_market_regime(self, market_data: pd.DataFrame) -> dict[str, Any]:
        frame = market_data.copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date", "close"])
        if frame.empty:
            return {"is_favorable": True, "trend_up": True, "annualized_volatility": 0.0}

        # Build an equal-weight market proxy from daily symbol returns.
        close_pivot = frame.pivot_table(index="date", columns="symbol", values="close", aggfunc="last").sort_index()
        symbol_returns = close_pivot.pct_change(fill_method=None)
        proxy_returns = symbol_returns.mean(axis=1, skipna=True).fillna(0.0)
        proxy = (1.0 + proxy_returns).cumprod() * 100.0
        min_points = max(self.regime_sma_period, self.regime_vol_window) + 5
        if len(proxy) < min_points:
            # Avoid blocking during warmup/sparse history windows.
            return {"is_favorable": True, "trend_up": True, "annualized_volatility": 0.0}

        sma = proxy.rolling(self.regime_sma_period).mean()
        ann_vol = proxy_returns.rolling(self.regime_vol_window).std() * (252**0.5)

        latest_close = float(proxy.iloc[-1])
        latest_sma = float(sma.iloc[-1]) if pd.notna(sma.iloc[-1]) else latest_close
        latest_vol = float(ann_vol.iloc[-1]) if pd.notna(ann_vol.iloc[-1]) else 0.0
        trend_up = latest_close >= (latest_sma * 0.99)
        low_vol = latest_vol <= self.regime_max_annual_vol
        return {
            "is_favorable": bool(trend_up and low_vol),
            "trend_up": bool(trend_up),
            "annualized_volatility": latest_vol,
            "close": latest_close,
            "sma": latest_sma,
        }

    def _compute_confidence(self, roc: float, volume_ratio: float, atr_pct: float, reward_to_risk: float) -> float:
        roc_score = min(max(roc / max(self.min_roc, 1e-6), 0.0), 2.0) / 2.0
        vol_score = min(max(volume_ratio / max(self.volume_multiplier, 1e-6), 0.0), 2.0) / 2.0
        atr_score = min(max((self.max_atr_pct - atr_pct) / max(self.max_atr_pct, 1e-6), 0.0), 1.0)
        rr_score = min(max(reward_to_risk / 2.0, 0.0), 1.0)
        confidence = 0.30 + (0.30 * roc_score) + (0.20 * vol_score) + (0.10 * atr_score) + (0.10 * rr_score)
        return float(min(max(confidence, 0.05), 0.99))

    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        current_price = float(current_data["close"])
        entry_price = float(position["entry_price"])
        days_held = int(position.get("days_held", 0))

        if current_price <= float(position["stop_loss"]):
            return True, "STOP_LOSS"
        if current_price >= float(position["target"]):
            return True, "TARGET_HIT"
        if days_held >= self.time_stop_days and abs((current_price - entry_price) / entry_price) < self.time_stop_move_pct:
            return True, "TIME_STOP"
        return False, None


momentum_strategy = MomentumBreakoutStrategy()
