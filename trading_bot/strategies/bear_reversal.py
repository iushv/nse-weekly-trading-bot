from __future__ import annotations

from datetime import datetime

import pandas as pd

from trading_bot.strategies.base_strategy import BaseStrategy, Signal


class BearReversalStrategy(BaseStrategy):
    """
    Counter-trend long strategy for bearish phases.

    The strategy looks for sharp short-term selloffs in symbols already below
    medium-term trend, then enters on early RSI recovery with tight risk/target.
    """

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_reentry: float = 35.0,
        trend_sma_period: int = 50,
        trend_below_sma_mult: float = 0.99,
        drop_lookback_days: int = 5,
        min_drop_pct: float = 0.04,
        min_volume_ratio: float = 0.8,
        stop_atr_mult: float = 1.2,
        rr_ratio: float = 1.0,
        max_hold_days: int = 4,
        log_signals: bool = True,
    ) -> None:
        super().__init__("Bear Reversal")
        self.rsi_period = int(rsi_period)
        self.rsi_oversold = float(rsi_oversold)
        self.rsi_reentry = float(rsi_reentry)
        self.trend_sma_period = int(trend_sma_period)
        self.trend_below_sma_mult = float(trend_below_sma_mult)
        self.drop_lookback_days = int(drop_lookback_days)
        self.min_drop_pct = float(min_drop_pct)
        self.min_volume_ratio = float(min_volume_ratio)
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

        out: list[Signal] = []
        min_rows = max(self.trend_sma_period + 5, self.drop_lookback_days + self.rsi_period + 5)
        for symbol in market_data["symbol"].dropna().unique():
            frame = market_data[market_data["symbol"] == symbol].copy().sort_values("date")
            if len(frame) < min_rows:
                continue

            frame = self._add_indicators(frame)
            latest = frame.iloc[-1]
            prev = frame.iloc[-2]
            prev2 = frame.iloc[-3]
            if not self._check_setup(latest, prev, prev2):
                continue

            price = float(latest["close"])
            atr = float(latest["ATR"]) if pd.notna(latest["ATR"]) else 0.0
            if atr <= 0:
                continue

            stop_loss = price - (self.stop_atr_mult * atr)
            target = self.calculate_target(price, stop_loss, rr=self.rr_ratio)
            if target <= price or stop_loss >= price:
                continue

            confidence = self._compute_confidence(
                rsi=float(latest["RSI"]),
                drop_pct=float(latest["DropPct"]),
                volume_ratio=float(latest["VolRatio"]),
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
                    "volume_ratio": float(latest["VolRatio"]),
                    "trend_gap_pct": float((latest["close"] / latest["TrendSMA"]) - 1.0),
                },
            )
            if self.log_signals_enabled:
                self.log_signal(signal)
            out.append(signal)

        return out

    def _add_indicators(self, frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        out["RSI"] = self._calculate_rsi(out["close"], self.rsi_period)
        out["TrendSMA"] = out["close"].rolling(self.trend_sma_period).mean()
        out["DropPct"] = -(out["close"].pct_change(self.drop_lookback_days))
        out["VolumeMA"] = out["volume"].rolling(20).mean()
        out["VolRatio"] = out["volume"] / out["VolumeMA"]

        high_low = out["high"] - out["low"]
        high_close = (out["high"] - out["close"].shift()).abs()
        low_close = (out["low"] - out["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        out["ATR"] = tr.rolling(14).mean()
        return out

    def _calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def _check_setup(self, latest: pd.Series, prev: pd.Series, prev2: pd.Series) -> bool:
        conditions = [
            # Only attempt reversal when symbol is structurally weak.
            latest["close"] < (latest["TrendSMA"] * self.trend_below_sma_mult),
            # Recent sharp decline.
            latest["DropPct"] >= self.min_drop_pct,
            # RSI recovery from oversold zone.
            min(prev["RSI"], prev2["RSI"]) <= self.rsi_oversold,
            latest["RSI"] >= self.rsi_reentry,
            latest["RSI"] > prev["RSI"],
            # Avoid dead symbols.
            latest["VolRatio"] >= self.min_volume_ratio,
        ]
        return all(bool(x) for x in conditions)

    def _compute_confidence(self, rsi: float, drop_pct: float, volume_ratio: float) -> float:
        rsi_score = min(max((rsi - self.rsi_reentry) / max(15.0, 70.0 - self.rsi_reentry), 0.0), 1.0)
        drop_score = min(max((drop_pct - self.min_drop_pct) / max(self.min_drop_pct, 1e-6), 0.0), 1.0)
        vol_score = min(max(volume_ratio / 2.0, 0.0), 1.0)
        confidence = 0.40 + (0.25 * rsi_score) + (0.20 * drop_score) + (0.15 * vol_score)
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
