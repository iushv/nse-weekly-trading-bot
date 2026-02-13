from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from trading_bot.strategies.base_strategy import BaseStrategy, Signal


class AdaptiveTrendFollowingStrategy(BaseStrategy):
    """
    Weekly trend + daily timing strategy.

    Designed to reduce trade frequency and let winners run with ATR-based trailing exits.
    """

    def __init__(
        self,
        weekly_ema_short: int = 10,
        weekly_ema_long: int = 30,
        weekly_atr_period: int = 10,
        weekly_rsi_period: int = 10,
        min_weekly_roc: float = 0.03,
        max_weekly_roc: float = 0.20,
        min_weekly_ema_spread_pct: float = 0.005,
        min_trend_consistency: float = 0.50,
        min_expected_r_mult: float = 1.0,
        stop_atr_mult: float = 1.5,
        profit_protect_pct: float = 0.03,
        profit_trail_atr_mult: float = 0.8,
        breakeven_gain_pct: float = 0.03,
        breakeven_buffer_pct: float = 0.005,
        max_positions: int = 5,
        max_new_per_week: int = 3,
        min_hold_days: int = 5,
        time_stop_days: int = 30,
        regime_min_breadth: float = 0.50,
        regime_max_vol: float = 0.30,
        log_signals: bool = True,
    ) -> None:
        super().__init__("Adaptive Trend")
        self.weekly_ema_short = int(weekly_ema_short)
        self.weekly_ema_long = int(weekly_ema_long)
        self.weekly_atr_period = int(weekly_atr_period)
        self.weekly_rsi_period = int(weekly_rsi_period)
        self.min_weekly_roc = float(min_weekly_roc)
        self.max_weekly_roc = float(max_weekly_roc)
        self.min_weekly_ema_spread_pct = float(min_weekly_ema_spread_pct)
        self.min_trend_consistency = float(min_trend_consistency)
        self.min_expected_r_mult = float(min_expected_r_mult)
        self.stop_atr_mult = float(stop_atr_mult)
        self.profit_protect_pct = float(profit_protect_pct)
        self.profit_trail_atr_mult = float(profit_trail_atr_mult)
        self.breakeven_gain_pct = float(breakeven_gain_pct)
        self.breakeven_buffer_pct = float(breakeven_buffer_pct)
        self.max_positions = int(max_positions)
        self.max_new_per_week = int(max_new_per_week)
        self.min_hold_days = int(min_hold_days)
        self.time_stop_days = int(time_stop_days)
        self.regime_min_breadth = float(regime_min_breadth)
        self.regime_max_vol = float(regime_max_vol)
        self.log_signals_enabled = bool(log_signals)

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict[str, Any] | None = None,
    ) -> list[Signal]:
        if market_data.empty:
            return []
        if not self._regime_allows_entry(market_regime):
            return []
        tighten_steps = self._regime_tighten_steps(market_regime)
        entry_min_weekly_roc, entry_min_ema_spread_pct, entry_min_volume_ratio = self._entry_thresholds_for_regime(
            market_regime,
            tighten_steps=tighten_steps,
        )

        candidates: list[Signal] = []
        for symbol in market_data["symbol"].dropna().unique():
            frame = market_data[market_data["symbol"] == symbol].copy()
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            frame = frame.dropna(subset=["date", "close", "high", "low", "volume"]).sort_values("date")
            if len(frame) < 120:
                continue

            daily = self._add_daily_indicators(frame)
            weekly = self._build_weekly_indicators(frame)
            if daily.empty or weekly.empty:
                continue

            d = daily.iloc[-1]
            w = weekly.iloc[-1]
            trend_consistency = self._trend_consistency_ratio(weekly)
            trend_consistency_floor = min(1.0, self.min_trend_consistency + (0.10 * tighten_steps))
            if trend_consistency < trend_consistency_floor:
                continue
            if not self._entry_conditions(
                d,
                w,
                min_weekly_roc=entry_min_weekly_roc,
                min_ema_spread_pct=entry_min_ema_spread_pct,
                min_volume_ratio=entry_min_volume_ratio,
            ):
                continue

            price = float(d["close"])
            weekly_atr = float(w["ATR"])
            if weekly_atr <= 0:
                continue

            expected_r = self._estimate_expected_r_multiple(price, w)
            expected_r_floor = min(self.min_expected_r_mult + (0.15 * tighten_steps), 1.6)
            if expected_r < expected_r_floor:
                continue

            stop_loss = price - (self.stop_atr_mult * weekly_atr)
            # Signal API expects a numeric target; exits are trailing/time based.
            target = price + (self.stop_atr_mult * weekly_atr * 4.0)
            confidence = self._confidence(d, w)
            signal = Signal(
                symbol=str(symbol),
                action="BUY",
                price=price,
                quantity=0,
                stop_loss=float(stop_loss),
                target=float(target),
                strategy=self.name,
                confidence=confidence,
                timestamp=datetime.now(),
                metadata={
                    "weekly_ema_short": float(w["EMA_S"]),
                    "weekly_ema_long": float(w["EMA_L"]),
                    "weekly_atr": weekly_atr,
                    "weekly_rsi": float(w["RSI"]),
                    "weekly_roc": float(w["ROC_4"]),
                    "daily_sma20": float(d["SMA_20"]),
                    "daily_rsi": float(d["RSI_14"]),
                    "volume_ratio": float(w["VOL_RATIO"]),
                    "regime_label": str((market_regime or {}).get("regime_label", "unknown")),
                    "regime_confidence": float((market_regime or {}).get("confidence", 0.5)),
                    "regime_breadth_ratio": float((market_regime or {}).get("breadth_ratio", 0.0)),
                    "regime_annualized_volatility": float((market_regime or {}).get("annualized_volatility", 0.0)),
                    "expected_r_multiple": expected_r,
                    "expected_r_floor": expected_r_floor,
                    "trend_consistency_ratio": trend_consistency,
                    "trend_consistency_floor": trend_consistency_floor,
                },
            )
            if self.log_signals_enabled:
                self.log_signal(signal)
            candidates.append(signal)

        candidates.sort(key=lambda s: float(s.confidence), reverse=True)
        return candidates[: self.max_new_per_week]

    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        current_price = float(current_data["close"])
        entry_price = float(position["entry_price"])
        days_held = int(position.get("days_held", 0))
        if current_price <= float(position["stop_loss"]):
            return True, "STOP_LOSS"

        highest_close = float(position.get("highest_close", max(entry_price, current_price)))
        weekly_atr = float(position.get("weekly_atr", 0.0))
        gain_pct = (highest_close - entry_price) / entry_price if entry_price > 0 else 0.0

        if days_held >= self.min_hold_days and gain_pct >= self.breakeven_gain_pct:
            breakeven_floor = entry_price * (1.0 + self.breakeven_buffer_pct)
            if current_price <= breakeven_floor:
                return True, "BREAKEVEN_STOP"

        metadata = position.get("metadata", {}) if isinstance(position.get("metadata"), dict) else {}
        entry_ema_short = metadata.get("weekly_ema_short")
        entry_ema_long = metadata.get("weekly_ema_long")
        current_ema_short = position.get("current_weekly_ema_short")
        current_ema_long = position.get("current_weekly_ema_long")
        if (
            days_held >= self.min_hold_days
            and entry_ema_short is not None
            and entry_ema_long is not None
            and current_ema_short is not None
            and current_ema_long is not None
        ):
            if float(entry_ema_short) > float(entry_ema_long) and float(current_ema_short) < float(current_ema_long):
                return True, "TREND_BREAK"

        if weekly_atr > 0 and days_held >= self.min_hold_days:
            trail_mult = self._progressive_trail_mult(gain_pct)
            trailing_stop = highest_close - (trail_mult * weekly_atr)
            if current_price <= trailing_stop:
                return True, "TRAILING_STOP"

        if days_held >= self.time_stop_days:
            pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0.0
            if pnl_pct < 0.03:
                return True, "TIME_STOP"
        return False, None

    def _progressive_trail_mult(self, gain_pct: float) -> float:
        if gain_pct >= 0.08:
            return self.profit_trail_atr_mult
        if gain_pct >= 0.05:
            return 1.0
        if gain_pct >= self.profit_protect_pct:
            return 1.2
        return self.stop_atr_mult

    def _regime_allows_entry(self, market_regime: dict[str, Any] | None) -> bool:
        if not market_regime:
            return True
        # Single source of truth: orchestrator-computed regime contract.
        if "is_favorable" in market_regime:
            return bool(market_regime.get("is_favorable", True))
        # Backward-compatible fallback for legacy callers that don't pass the canonical key.
        breadth = float(market_regime.get("breadth_ratio", 1.0))
        trend_up = bool(market_regime.get("trend_up", True))
        return bool(breadth >= self.regime_min_breadth and trend_up)

    def _add_daily_indicators(self, frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        out["SMA_20"] = out["close"].rolling(20).mean()
        out["RSI_14"] = self._rsi(out["close"], 14)
        return out

    def _build_weekly_indicators(self, frame: pd.DataFrame) -> pd.DataFrame:
        weekly = (
            frame.set_index("date")
            .resample("W-FRI")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna()
            .copy()
        )
        if len(weekly) < max(self.weekly_ema_long + 2, self.weekly_atr_period + 5):
            return pd.DataFrame()

        weekly["EMA_S"] = weekly["close"].ewm(span=self.weekly_ema_short, adjust=False).mean()
        weekly["EMA_L"] = weekly["close"].ewm(span=self.weekly_ema_long, adjust=False).mean()
        weekly["ROC_4"] = weekly["close"].pct_change(4)
        weekly["RSI"] = self._rsi(weekly["close"], self.weekly_rsi_period)

        high_low = weekly["high"] - weekly["low"]
        high_close = (weekly["high"] - weekly["close"].shift()).abs()
        low_close = (weekly["low"] - weekly["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        weekly["ATR"] = tr.rolling(self.weekly_atr_period).mean()
        weekly["VOL_MA"] = weekly["volume"].rolling(10).mean()
        weekly["VOL_RATIO"] = weekly["volume"] / weekly["VOL_MA"]
        return weekly.dropna()

    def _regime_tighten_steps(self, market_regime: dict[str, Any] | None) -> int:
        if not market_regime:
            return 0
        steps = 0
        if "confidence" in market_regime:
            confidence = float(market_regime.get("confidence", 0.5))
            steps += int(confidence < 0.55)
        if "breadth_ratio" in market_regime:
            breadth = float(market_regime.get("breadth_ratio", 1.0))
            steps += int(breadth < 0.52)
        if "annualized_volatility" in market_regime:
            annual_vol = float(market_regime.get("annualized_volatility", 0.0))
            steps += int(annual_vol > 0.50)
        return steps

    def _entry_thresholds_for_regime(
        self,
        market_regime: dict[str, Any] | None,
        *,
        tighten_steps: int | None = None,
    ) -> tuple[float, float, float]:
        min_weekly_roc = self.min_weekly_roc
        min_ema_spread_pct = self.min_weekly_ema_spread_pct
        min_volume_ratio = 0.8
        if not market_regime:
            return min_weekly_roc, min_ema_spread_pct, min_volume_ratio

        steps = self._regime_tighten_steps(market_regime) if tighten_steps is None else max(0, int(tighten_steps))
        tighten_steps = steps
        if tighten_steps <= 0:
            return min_weekly_roc, min_ema_spread_pct, min_volume_ratio

        min_weekly_roc += 0.005 * tighten_steps
        min_ema_spread_pct += 0.0015 * tighten_steps
        min_volume_ratio += 0.05 * tighten_steps

        min_weekly_roc = min(min_weekly_roc, max(self.max_weekly_roc - 0.01, self.min_weekly_roc))
        min_ema_spread_pct = min(min_ema_spread_pct, 0.02)
        min_volume_ratio = min(min_volume_ratio, 1.0)
        return min_weekly_roc, min_ema_spread_pct, min_volume_ratio

    def _estimate_expected_r_multiple(self, entry_price: float, weekly: pd.Series) -> float:
        if entry_price <= 0:
            return 0.0
        weekly_close = float(weekly["close"])
        weekly_ema_s = float(weekly["EMA_S"])
        weekly_ema_l = float(weekly["EMA_L"])
        weekly_roc = max(float(weekly["ROC_4"]), 0.0)
        weekly_atr = float(weekly["ATR"])
        if weekly_atr <= 0:
            return 0.0

        ema_spread_pct = (weekly_ema_s - weekly_ema_l) / weekly_close if weekly_close > 0 else 0.0
        trend_proxy_pct = max(weekly_roc, max(ema_spread_pct, 0.0) * 4.0)
        risk_pct = (self.stop_atr_mult * weekly_atr) / entry_price
        if risk_pct <= 0:
            return 0.0
        return float(max(trend_proxy_pct / risk_pct, 0.0))

    def _entry_conditions(
        self,
        daily: pd.Series,
        weekly: pd.Series,
        *,
        min_weekly_roc: float | None = None,
        min_ema_spread_pct: float | None = None,
        min_volume_ratio: float = 0.8,
    ) -> bool:
        weekly_roc_floor = self.min_weekly_roc if min_weekly_roc is None else float(min_weekly_roc)
        ema_spread_floor = self.min_weekly_ema_spread_pct if min_ema_spread_pct is None else float(min_ema_spread_pct)
        weekly_close = float(weekly["close"])
        weekly_ema_s = float(weekly["EMA_S"])
        weekly_ema_l = float(weekly["EMA_L"])
        weekly_roc = float(weekly["ROC_4"])
        weekly_rsi = float(weekly["RSI"])
        weekly_atr = float(weekly["ATR"])
        vol_ratio = float(weekly["VOL_RATIO"])
        ema_spread_pct = (weekly_ema_s - weekly_ema_l) / weekly_close if weekly_close > 0 else 0.0

        daily_close = float(daily["close"])
        sma20 = float(daily["SMA_20"])
        daily_rsi = float(daily["RSI_14"])
        atr_distance = abs(daily_close - weekly_ema_s)

        checks = [
            weekly_ema_s > weekly_ema_l,
            ema_spread_pct >= ema_spread_floor,
            weekly_close > weekly_ema_s,
            weekly_roc_floor <= weekly_roc <= self.max_weekly_roc,
            40.0 <= weekly_rsi <= 75.0,
            daily_close > sma20,
            45.0 <= daily_rsi <= 70.0,
            weekly_atr > 0,
            atr_distance <= (1.5 * weekly_atr),
            vol_ratio >= min_volume_ratio,
        ]
        return all(checks)

    def _trend_consistency_ratio(self, weekly: pd.DataFrame, weeks: int = 4) -> float:
        if weekly.empty:
            return 0.0
        recent = weekly.tail(max(1, int(weeks)))
        if recent.empty:
            return 0.0
        consistent = (recent["close"] > recent["EMA_S"]).sum()
        return float(consistent / len(recent))

    def _confidence(self, daily: pd.Series, weekly: pd.Series) -> float:
        weekly_roc = float(weekly["ROC_4"])
        weekly_rsi = float(weekly["RSI"])
        vol_ratio = float(weekly["VOL_RATIO"])
        daily_rsi = float(daily["RSI_14"])

        roc_score = min(max((weekly_roc - self.min_weekly_roc) / max(self.max_weekly_roc, 1e-6), 0.0), 1.0)
        weekly_rsi_score = min(max((weekly_rsi - 40.0) / 35.0, 0.0), 1.0)
        daily_rsi_score = min(max((daily_rsi - 45.0) / 25.0, 0.0), 1.0)
        vol_score = min(max(vol_ratio / 2.0, 0.0), 1.0)
        confidence = 0.35 + (0.25 * roc_score) + (0.20 * weekly_rsi_score) + (0.10 * daily_rsi_score) + (0.10 * vol_score)
        return float(min(max(confidence, 0.05), 0.99))

    def _rsi(self, series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
        rs = gain / loss
        return 100.0 - (100.0 / (1.0 + rs))
