from __future__ import annotations

from datetime import datetime

import pandas as pd

from trading_bot.config.constants import INDICATORS
from trading_bot.strategies.base_strategy import BaseStrategy, Signal


class MeanReversionStrategy(BaseStrategy):
    def __init__(
        self,
        rsi_oversold: float | None = None,
        rsi_overbought: float | None = None,
        oversold_buffer: float = 5.0,
        trend_tolerance: float = 0.95,
        bb_entry_mult: float = 1.01,
        volume_cap: float = 2.5,
        rsi_recovery_delta: float = 0.0,
        stop_bb_buffer: float = 0.98,
        stop_sma_buffer: float = 0.98,
        stop_atr_mult: float = 1.5,
        target_gain_pct: float = 0.08,
        time_stop_days: int = 7,
        log_signals: bool = True,
    ) -> None:
        super().__init__("Mean Reversion")
        self.rsi_period = INDICATORS["RSI_PERIOD"]
        self.rsi_oversold = float(
            INDICATORS["RSI_OVERSOLD"] if rsi_oversold is None else rsi_oversold
        )
        self.rsi_overbought = float(
            INDICATORS["RSI_OVERBOUGHT"] if rsi_overbought is None else rsi_overbought
        )
        self.oversold_buffer = float(oversold_buffer)
        self.trend_tolerance = float(trend_tolerance)
        self.bb_entry_mult = float(bb_entry_mult)
        self.volume_cap = float(volume_cap)
        self.rsi_recovery_delta = float(rsi_recovery_delta)
        self.stop_bb_buffer = float(stop_bb_buffer)
        self.stop_sma_buffer = float(stop_sma_buffer)
        self.stop_atr_mult = float(stop_atr_mult)
        self.target_gain_pct = float(target_gain_pct)
        self.time_stop_days = int(time_stop_days)
        self.log_signals_enabled = bool(log_signals)

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict | None = None,
    ) -> list[Signal]:
        signals: list[Signal] = []
        if market_data.empty:
            return signals

        for symbol in market_data["symbol"].dropna().unique():
            df = market_data[market_data["symbol"] == symbol].copy().sort_values("date")
            if len(df) < 210:
                continue

            df = self._add_indicators(df)
            if self._check_setup(df):
                latest = df.iloc[-1]
                atr = float(latest["ATR"]) if pd.notna(latest["ATR"]) else 0.0
                if atr <= 0:
                    continue

                price = float(latest["close"])
                # Use tighter protective stop among structural levels.
                stop_loss = max(
                    float(latest["BB_Lower"] * self.stop_bb_buffer),
                    float(latest["SMA_200"] * self.stop_sma_buffer),
                    float(price - (self.stop_atr_mult * atr)),
                )
                # Target must be at or above entry for long positions.
                target = max(float(price * (1 + self.target_gain_pct)), float(latest["BB_Middle"]))

                signal = Signal(
                    symbol=symbol,
                    action="BUY",
                    price=price,
                    quantity=0,
                    stop_loss=stop_loss,
                    target=target,
                    strategy=self.name,
                    confidence=0.65,
                    timestamp=datetime.now(),
                    metadata={"rsi": float(latest["RSI"])},
                )
                if self.log_signals_enabled:
                    self.log_signal(signal)
                signals.append(signal)

        return signals

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["RSI"] = self._calculate_rsi(out["close"], self.rsi_period)
        out["SMA_200"] = out["close"].rolling(200).mean()
        out["BB_Middle"] = out["close"].rolling(20).mean()
        out["BB_Std"] = out["close"].rolling(20).std()
        out["BB_Upper"] = out["BB_Middle"] + 2 * out["BB_Std"]
        out["BB_Lower"] = out["BB_Middle"] - 2 * out["BB_Std"]
        out["Volume_MA"] = out["volume"].rolling(20).mean()

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

    def _check_setup(self, df: pd.DataFrame) -> bool:
        latest, prev, prev2 = df.iloc[-1], df.iloc[-2], df.iloc[-3]
        conditions = [
            # Soft confirmation of prior oversold, then momentum turn-up.
            min(prev["RSI"], prev2["RSI"]) < (self.rsi_oversold + self.oversold_buffer),
            latest["RSI"] > self.rsi_oversold,
            latest["RSI"] > (prev["RSI"] + self.rsi_recovery_delta),
            # Allow near-trend pullbacks (not only strict > 200SMA).
            latest["close"] > latest["SMA_200"] * self.trend_tolerance,
            # Entry near lower half of Bollinger envelope.
            latest["close"] <= latest["BB_Middle"] * self.bb_entry_mult,
            latest["volume"] < latest["Volume_MA"] * self.volume_cap,
        ]
        return all(bool(x) for x in conditions)

    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        price = float(current_data["close"])
        if price <= float(position["stop_loss"]):
            return True, "STOP_LOSS"
        if price >= float(position["target"]):
            return True, "TARGET_HIT"
        if float(current_data.get("RSI", 0)) > self.rsi_overbought:
            return True, "RSI_OVERBOUGHT"
        if int(position.get("days_held", 0)) >= self.time_stop_days:
            return True, "TIME_STOP"
        return False, None


mean_reversion_strategy = MeanReversionStrategy()
