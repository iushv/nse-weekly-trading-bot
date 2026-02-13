from __future__ import annotations

from datetime import datetime

import pandas as pd

from trading_bot.strategies.base_strategy import BaseStrategy, Signal


class VolatilityReversalStrategy(BaseStrategy):
    """
    Volatility snapback long strategy.

    Looks for short-term panic selloffs (large drop + volatility expansion),
    then enters on initial RSI recovery for quick mean reversion.
    """

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_reentry: float = 35.0,
        drop_lookback_days: int = 3,
        min_drop_pct: float = 0.03,
        vol_spike_mult: float = 1.2,
        min_atr_pct: float = 0.025,
        trend_sma_period: int = 20,
        trend_below_sma_mult: float = 1.0,
        stop_atr_mult: float = 1.1,
        rr_ratio: float = 1.0,
        max_hold_days: int = 3,
        log_signals: bool = True,
    ) -> None:
        super().__init__("Volatility Reversal")
        self.rsi_period = int(rsi_period)
        self.rsi_reentry = float(rsi_reentry)
        self.drop_lookback_days = int(drop_lookback_days)
        self.min_drop_pct = float(min_drop_pct)
        self.vol_spike_mult = float(vol_spike_mult)
        self.min_atr_pct = float(min_atr_pct)
        self.trend_sma_period = int(trend_sma_period)
        self.trend_below_sma_mult = float(trend_below_sma_mult)
        self.stop_atr_mult = float(stop_atr_mult)
        self.rr_ratio = float(rr_ratio)
        self.max_hold_days = int(max_hold_days)
        self.log_signals_enabled = bool(log_signals)

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict | None = None,
    ) -> list[Signal]:
        if market_data.empty:
            return []

        min_rows = max(self.trend_sma_period + 5, self.rsi_period + self.drop_lookback_days + 5)
        signals: list[Signal] = []

        for symbol in market_data["symbol"].dropna().unique():
            frame = market_data[market_data["symbol"] == symbol].copy().sort_values("date")
            if len(frame) < min_rows:
                continue

            frame = self._add_indicators(frame)
            latest = frame.iloc[-1]
            prev = frame.iloc[-2]
            if not self._check_setup(latest, prev):
                continue

            price = float(latest["close"])
            atr = float(latest["ATR"]) if pd.notna(latest["ATR"]) else 0.0
            if atr <= 0:
                continue

            stop_loss = price - (self.stop_atr_mult * atr)
            target = self.calculate_target(price, stop_loss, rr=self.rr_ratio)
            if stop_loss >= price or target <= price:
                continue

            confidence = self._compute_confidence(
                rsi=float(latest["RSI"]),
                drop_pct=float(latest["DropPct"]),
                atr_pct=float(latest["ATR_Pct"]),
            )
            signal = Signal(
                symbol=symbol,
                action="BUY",
                price=price,
                quantity=0,
                stop_loss=float(stop_loss),
                target=float(target),
                strategy=self.name,
                confidence=confidence,
                timestamp=datetime.now(),
                metadata={
                    "rsi": float(latest["RSI"]),
                    "drop_pct": float(latest["DropPct"]),
                    "atr_pct": float(latest["ATR_Pct"]),
                    "atr_spike_ratio": float(latest["ATRSpikeRatio"]),
                },
            )
            if self.log_signals_enabled:
                self.log_signal(signal)
            signals.append(signal)

        return signals

    def _add_indicators(self, frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        out["RSI"] = self._calculate_rsi(out["close"], self.rsi_period)
        out["TrendSMA"] = out["close"].rolling(self.trend_sma_period).mean()
        out["DropPct"] = -(out["close"].pct_change(self.drop_lookback_days))

        high_low = out["high"] - out["low"]
        high_close = (out["high"] - out["close"].shift()).abs()
        low_close = (out["low"] - out["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        out["ATR"] = tr.rolling(14).mean()
        out["ATR_Pct"] = out["ATR"] / out["close"]
        out["ATR_MA"] = out["ATR"].rolling(20).mean()
        out["ATRSpikeRatio"] = out["ATR"] / out["ATR_MA"]
        return out

    def _calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def _check_setup(self, latest: pd.Series, prev: pd.Series) -> bool:
        conditions = [
            latest["close"] <= latest["TrendSMA"] * self.trend_below_sma_mult,
            latest["DropPct"] >= self.min_drop_pct,
            latest["ATR_Pct"] >= self.min_atr_pct,
            latest["ATRSpikeRatio"] >= self.vol_spike_mult,
            latest["RSI"] >= self.rsi_reentry,
            latest["RSI"] > prev["RSI"],
        ]
        return all(bool(x) for x in conditions)

    def _compute_confidence(self, rsi: float, drop_pct: float, atr_pct: float) -> float:
        rsi_score = min(max((rsi - self.rsi_reentry) / max(20.0, 70.0 - self.rsi_reentry), 0.0), 1.0)
        drop_score = min(max((drop_pct - self.min_drop_pct) / max(self.min_drop_pct, 1e-6), 0.0), 1.0)
        atr_score = min(max((atr_pct - self.min_atr_pct) / max(self.min_atr_pct, 1e-6), 0.0), 1.0)
        confidence = 0.35 + (0.25 * rsi_score) + (0.25 * drop_score) + (0.15 * atr_score)
        return float(min(max(confidence, 0.05), 0.99))

    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        price = float(current_data["close"])
        if price <= float(position["stop_loss"]):
            return True, "STOP_LOSS"
        if price >= float(position["target"]):
            return True, "TARGET_HIT"
        if int(position.get("days_held", 0)) >= self.max_hold_days:
            return True, "TIME_STOP"
        return False, None
