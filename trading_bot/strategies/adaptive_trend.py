from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from loguru import logger

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
        daily_rsi_min: float = 40.0,
        daily_rsi_max: float = 72.0,
        min_weekly_ema_spread_pct: float = 0.005,
        min_volume_ratio: float = 0.80,
        min_trend_consistency: float = 0.50,
        min_expected_r_mult: float = 1.0,
        stop_atr_mult: float = 1.5,
        profit_protect_pct: float = 0.03,
        profit_trail_atr_mult: float = 0.8,
        trail_tier2_gain: float = 0.05,
        trail_tier2_mult: float = 1.0,
        trail_tier3_gain: float = 0.08,
        trail_tier3_mult: float = 1.2,
        breakeven_gain_pct: float = 0.03,
        breakeven_buffer_pct: float = 0.005,
        max_weekly_atr_pct: float = 0.08,
        dynamic_stop_enabled: bool = False,
        dynamic_stop_high_atr_pct: float = 0.08,
        dynamic_stop_low_atr_pct: float = 0.04,
        dynamic_stop_high_vol_scale: float = 0.85,
        dynamic_stop_low_vol_scale: float = 1.10,
        dynamic_stop_min_mult: float = 1.0,
        dynamic_stop_max_mult: float = 2.0,
        transaction_cost_pct: float = 0.00355,
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
        self.daily_rsi_min = float(daily_rsi_min)
        self.daily_rsi_max = float(daily_rsi_max)
        self.min_weekly_ema_spread_pct = float(min_weekly_ema_spread_pct)
        self.min_volume_ratio = float(min_volume_ratio)
        self.min_trend_consistency = float(min_trend_consistency)
        self.min_expected_r_mult = float(min_expected_r_mult)
        self.stop_atr_mult = float(stop_atr_mult)
        self.profit_protect_pct = float(profit_protect_pct)
        self.profit_trail_atr_mult = float(profit_trail_atr_mult)
        self.trail_tier2_gain = float(trail_tier2_gain)
        self.trail_tier2_mult = float(trail_tier2_mult)
        self.trail_tier3_gain = float(trail_tier3_gain)
        self.trail_tier3_mult = float(trail_tier3_mult)
        self.breakeven_gain_pct = float(breakeven_gain_pct)
        self.breakeven_buffer_pct = float(breakeven_buffer_pct)
        self.max_weekly_atr_pct = float(max_weekly_atr_pct)
        self.dynamic_stop_enabled = bool(dynamic_stop_enabled)
        self.dynamic_stop_high_atr_pct = float(dynamic_stop_high_atr_pct)
        self.dynamic_stop_low_atr_pct = float(dynamic_stop_low_atr_pct)
        self.dynamic_stop_high_vol_scale = float(dynamic_stop_high_vol_scale)
        self.dynamic_stop_low_vol_scale = float(dynamic_stop_low_vol_scale)
        self.dynamic_stop_min_mult = float(dynamic_stop_min_mult)
        self.dynamic_stop_max_mult = float(dynamic_stop_max_mult)
        self.transaction_cost_pct = float(transaction_cost_pct)
        self.max_positions = int(max_positions)
        self.max_new_per_week = int(max_new_per_week)
        self.min_hold_days = int(min_hold_days)
        self.time_stop_days = int(time_stop_days)
        self.regime_min_breadth = float(regime_min_breadth)
        self.regime_max_vol = float(regime_max_vol)
        self.log_signals_enabled = bool(log_signals)
        self.last_scan_stats: dict[str, Any] = {
            "symbols": 0,
            "insufficient_data": 0,
            "indicator_warmup": 0,
            "trend_consistency": 0,
            "entry_conditions": 0,
            "weekly_atr_invalid": 0,
            "low_expected_r": 0,
            "high_atr_pct": 0,
            "passed": 0,
            "entry_reasons": {},
            "tighten_steps": 0,
            "blocked_by_regime": False,
            "reason": "uninitialized",
        }

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict[str, Any] | None = None,
    ) -> list[Signal]:
        if market_data.empty:
            self.last_scan_stats = {
                "symbols": 0,
                "insufficient_data": 0,
                "indicator_warmup": 0,
                "trend_consistency": 0,
                "entry_conditions": 0,
                "weekly_atr_invalid": 0,
                "low_expected_r": 0,
                "high_atr_pct": 0,
                "passed": 0,
                "entry_reasons": {},
                "tighten_steps": 0,
                "blocked_by_regime": False,
                "reason": "empty_market_data",
            }
            return []
        symbols = list(market_data["symbol"].dropna().unique())
        if not self._regime_allows_entry(market_regime):
            self.last_scan_stats = {
                "symbols": len(symbols),
                "insufficient_data": 0,
                "indicator_warmup": 0,
                "trend_consistency": 0,
                "entry_conditions": 0,
                "weekly_atr_invalid": 0,
                "low_expected_r": 0,
                "passed": 0,
                "entry_reasons": {},
                "tighten_steps": 0,
                "blocked_by_regime": True,
                "reason": "regime_blocked",
            }
            return []
        tighten_steps = self._regime_tighten_steps(market_regime)
        entry_min_weekly_roc, entry_min_ema_spread_pct, entry_min_volume_ratio = self._entry_thresholds_for_regime(
            market_regime,
            tighten_steps=tighten_steps,
        )

        candidates: list[Signal] = []
        scan_stats: dict[str, int] = {
            "symbols": len(symbols),
            "insufficient_data": 0,
            "indicator_warmup": 0,
            "trend_consistency": 0,
            "entry_conditions": 0,
            "weekly_atr_invalid": 0,
            "high_atr_pct": 0,
            "low_expected_r": 0,
            "passed": 0,
        }
        entry_reasons: dict[str, int] = {}
        for symbol in symbols:
            frame = market_data[market_data["symbol"] == symbol].copy()
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            frame = frame.dropna(subset=["date", "close", "high", "low", "volume"]).sort_values("date")
            if len(frame) < 120:
                scan_stats["insufficient_data"] += 1
                continue

            daily = self._add_daily_indicators(frame)
            weekly = self._build_weekly_indicators(frame)
            if daily.empty or weekly.empty:
                scan_stats["indicator_warmup"] += 1
                continue

            d = daily.iloc[-1]
            w = weekly.iloc[-1]
            trend_consistency = self._trend_consistency_ratio(weekly)
            trend_consistency_floor = min(1.0, self.min_trend_consistency + (0.05 * tighten_steps))
            if trend_consistency < trend_consistency_floor:
                scan_stats["trend_consistency"] += 1
                continue
            failed_reasons: list[str] = []
            entry_ok = self._entry_conditions(
                d,
                w,
                min_weekly_roc=entry_min_weekly_roc,
                min_ema_spread_pct=entry_min_ema_spread_pct,
                min_volume_ratio=entry_min_volume_ratio,
                failure_reasons=failed_reasons,
            )
            if not entry_ok:
                scan_stats["entry_conditions"] += 1
                for reason in failed_reasons:
                    entry_reasons[reason] = int(entry_reasons.get(reason, 0)) + 1
                continue

            price = float(d["close"])
            weekly_atr = float(w["ATR"])
            if weekly_atr <= 0:
                scan_stats["weekly_atr_invalid"] += 1
                continue

            atr_pct = weekly_atr / price
            if atr_pct > self.max_weekly_atr_pct:
                scan_stats["high_atr_pct"] += 1
                continue

            stop_atr_mult_used = self._entry_stop_atr_mult(price, weekly_atr)
            if self.dynamic_stop_enabled:
                expected_r = self._estimate_expected_r_multiple(price, w, stop_atr_mult=stop_atr_mult_used)
            else:
                expected_r = self._estimate_expected_r_multiple(price, w)
            expected_r_floor = min(self.min_expected_r_mult + (0.08 * tighten_steps), 1.4)
            if expected_r < expected_r_floor:
                scan_stats["low_expected_r"] += 1
                continue

            stop_loss = price - (stop_atr_mult_used * weekly_atr)
            # Signal API expects a numeric target; exits are trailing/time based.
            target = price + (stop_atr_mult_used * weekly_atr * 4.0)
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
                    "weekly_atr_pct": atr_pct,
                    "stop_atr_mult_used": stop_atr_mult_used,
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
            scan_stats["passed"] += 1

        candidates.sort(key=lambda s: float(s.confidence), reverse=True)
        logger.info(
            "Adaptive trend scan: symbols={} rejected_data={} rejected_warmup={} rejected_trend={} "
            "rejected_entry={} rejected_low_r={} passed={} entry_reasons={}",
            scan_stats["symbols"],
            scan_stats["insufficient_data"],
            scan_stats["indicator_warmup"],
            scan_stats["trend_consistency"],
            scan_stats["entry_conditions"],
            scan_stats["low_expected_r"],
            scan_stats["passed"],
            entry_reasons,
        )
        self.last_scan_stats = {
            **scan_stats,
            "entry_reasons": dict(entry_reasons),
            "tighten_steps": int(tighten_steps),
            "blocked_by_regime": False,
            "reason": "scan_complete",
            "thresholds": {
                "min_weekly_roc": float(entry_min_weekly_roc),
                "min_weekly_ema_spread_pct": float(entry_min_ema_spread_pct),
                "min_volume_ratio": float(entry_min_volume_ratio),
                "expected_r_floor_base": float(self.min_expected_r_mult),
                "expected_r_floor_effective": float(min(self.min_expected_r_mult + (0.08 * tighten_steps), 1.4)),
                "trend_consistency_floor_effective": float(min(1.0, self.min_trend_consistency + (0.05 * tighten_steps))),
            },
        }
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
            breakeven_floor = entry_price * (1.0 + self.breakeven_buffer_pct + self.transaction_cost_pct)
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
            entry_stop_mult = float(metadata.get("stop_atr_mult_used", self.stop_atr_mult))
            trail_mult = self._progressive_trail_mult(gain_pct, base_stop_atr_mult=entry_stop_mult)
            trailing_stop = highest_close - (trail_mult * weekly_atr)
            if current_price <= trailing_stop:
                return True, "TRAILING_STOP"

        if days_held >= self.time_stop_days:
            pnl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0.0
            if pnl_pct < 0.03:
                return True, "TIME_STOP"
        return False, None

    def _progressive_trail_mult(self, gain_pct: float, base_stop_atr_mult: float | None = None) -> float:
        base_mult = self.stop_atr_mult if base_stop_atr_mult is None else float(base_stop_atr_mult)
        if gain_pct >= self.trail_tier3_gain:
            return self.profit_trail_atr_mult
        if gain_pct >= self.trail_tier2_gain:
            return self.trail_tier2_mult
        if gain_pct >= self.profit_protect_pct:
            return self.trail_tier3_mult
        return base_mult

    def _regime_allows_entry(self, market_regime: dict[str, Any] | None) -> bool:
        # Binary regime gating is disabled; regime should influence thresholds, not block all entries.
        _ = market_regime
        return True

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
        score = 0.0
        if "confidence" in market_regime:
            confidence = float(market_regime.get("confidence", 0.5))
            score += max(0.0, min(1.0, (0.55 - confidence) / 0.10))
        if "breadth_ratio" in market_regime:
            breadth = float(market_regime.get("breadth_ratio", 1.0))
            score += max(0.0, min(1.0, (0.52 - breadth) / 0.07))
        if "annualized_volatility" in market_regime:
            annual_vol = float(market_regime.get("annualized_volatility", 0.0))
            score += max(0.0, min(1.0, (annual_vol - 0.50) / 0.15))
        return int(round(score))

    def _entry_thresholds_for_regime(
        self,
        market_regime: dict[str, Any] | None,
        *,
        tighten_steps: int | None = None,
    ) -> tuple[float, float, float]:
        min_weekly_roc = self.min_weekly_roc
        min_ema_spread_pct = self.min_weekly_ema_spread_pct
        min_volume_ratio = self.min_volume_ratio
        if not market_regime:
            return min_weekly_roc, min_ema_spread_pct, min_volume_ratio

        steps = self._regime_tighten_steps(market_regime) if tighten_steps is None else max(0, int(tighten_steps))
        tighten_steps = steps
        if tighten_steps <= 0:
            return min_weekly_roc, min_ema_spread_pct, min_volume_ratio

        min_weekly_roc += 0.0025 * tighten_steps
        min_ema_spread_pct += 0.00075 * tighten_steps
        min_volume_ratio += 0.025 * tighten_steps

        min_weekly_roc = min(min_weekly_roc, max(self.max_weekly_roc - 0.01, self.min_weekly_roc))
        min_ema_spread_pct = min(min_ema_spread_pct, 0.02)
        min_volume_ratio = min(min_volume_ratio, 1.0)
        return min_weekly_roc, min_ema_spread_pct, min_volume_ratio

    def _estimate_expected_r_multiple(self, entry_price: float, weekly: pd.Series, *, stop_atr_mult: float | None = None) -> float:
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
        effective_stop_mult = self.stop_atr_mult if stop_atr_mult is None else float(stop_atr_mult)
        risk_pct = (effective_stop_mult * weekly_atr) / entry_price
        if risk_pct <= 0:
            return 0.0
        return float(max(trend_proxy_pct / risk_pct, 0.0))

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return float(max(lower, min(upper, value)))

    def _entry_stop_atr_mult(self, entry_price: float, weekly_atr: float) -> float:
        if not self.dynamic_stop_enabled:
            return self.stop_atr_mult
        if entry_price <= 0 or weekly_atr <= 0:
            return self.stop_atr_mult

        atr_pct = weekly_atr / entry_price
        low_atr = max(1e-6, self.dynamic_stop_low_atr_pct)
        high_atr = max(low_atr + 1e-6, self.dynamic_stop_high_atr_pct)

        if atr_pct <= low_atr:
            scale = self.dynamic_stop_low_vol_scale
        elif atr_pct >= high_atr:
            scale = self.dynamic_stop_high_vol_scale
        else:
            ratio = (atr_pct - low_atr) / (high_atr - low_atr)
            scale = self.dynamic_stop_low_vol_scale + (
                ratio * (self.dynamic_stop_high_vol_scale - self.dynamic_stop_low_vol_scale)
            )

        stop_mult = self.stop_atr_mult * scale
        lower = min(self.dynamic_stop_min_mult, self.dynamic_stop_max_mult)
        upper = max(self.dynamic_stop_min_mult, self.dynamic_stop_max_mult)
        return self._clamp(stop_mult, lower, upper)

    def _entry_conditions(
        self,
        daily: pd.Series,
        weekly: pd.Series,
        *,
        min_weekly_roc: float | None = None,
        min_ema_spread_pct: float | None = None,
        min_volume_ratio: float | None = None,
        failure_reasons: list[str] | None = None,
    ) -> bool:
        passed, failed = self._entry_conditions_with_reasons(
            daily,
            weekly,
            min_weekly_roc=min_weekly_roc,
            min_ema_spread_pct=min_ema_spread_pct,
            min_volume_ratio=min_volume_ratio,
        )
        if failure_reasons is not None:
            failure_reasons.clear()
            failure_reasons.extend(failed)
        return passed

    def _entry_conditions_with_reasons(
        self,
        daily: pd.Series,
        weekly: pd.Series,
        *,
        min_weekly_roc: float | None = None,
        min_ema_spread_pct: float | None = None,
        min_volume_ratio: float | None = None,
    ) -> tuple[bool, list[str]]:
        weekly_roc_floor = self.min_weekly_roc if min_weekly_roc is None else float(min_weekly_roc)
        ema_spread_floor = self.min_weekly_ema_spread_pct if min_ema_spread_pct is None else float(min_ema_spread_pct)
        volume_ratio_floor = self.min_volume_ratio if min_volume_ratio is None else float(min_volume_ratio)
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
            ("ema_trend", weekly_ema_s > weekly_ema_l),
            ("ema_spread", ema_spread_pct >= ema_spread_floor),
            ("weekly_price_above_ema", weekly_close > weekly_ema_s),
            ("weekly_roc_band", weekly_roc_floor <= weekly_roc <= self.max_weekly_roc),
            ("weekly_rsi_band", 40.0 <= weekly_rsi <= 75.0),
            ("daily_above_sma20", daily_close > sma20),
            ("daily_rsi_band", self.daily_rsi_min <= daily_rsi <= self.daily_rsi_max),
            ("weekly_atr_positive", weekly_atr > 0),
            ("atr_distance", atr_distance <= (1.5 * weekly_atr)),
            ("volume_ratio", vol_ratio >= volume_ratio_floor),
        ]
        failed = [name for name, passed in checks if not passed]
        return len(failed) == 0, failed

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
        daily_rsi_range = max(self.daily_rsi_max - self.daily_rsi_min, 1e-6)
        daily_rsi_score = min(max((daily_rsi - self.daily_rsi_min) / daily_rsi_range, 0.0), 1.0)
        vol_score = min(max(vol_ratio / 2.0, 0.0), 1.0)
        confidence = 0.35 + (0.25 * roc_score) + (0.20 * weekly_rsi_score) + (0.10 * daily_rsi_score) + (0.10 * vol_score)
        return float(min(max(confidence, 0.05), 0.99))

    def _rsi(self, series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
        rs = gain / loss
        return 100.0 - (100.0 / (1.0 + rs))
