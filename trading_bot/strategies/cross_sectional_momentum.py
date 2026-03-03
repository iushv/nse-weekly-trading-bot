from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from trading_bot.strategies.base_strategy import BaseStrategy, Signal


class CrossSectionalMomentumStrategy(BaseStrategy):
    def __init__(
        self,
        *,
        top_n: int = 25,
        lookback_months: int = 6,
        skip_recent_months: int = 1,
        trailing_stop_pct: float = 0.15,
        min_history_days: int = 140,
        initial_capital: float = 100000.0,
        overnight_jump_threshold: float = 0.35,
        log_signals: bool = True,
    ) -> None:
        super().__init__("Cross Sectional Momentum")
        self.top_n = max(1, int(top_n))
        self.lookback_months = max(1, int(lookback_months))
        self.skip_recent_months = max(0, int(skip_recent_months))
        self.trailing_stop_pct = max(0.01, float(trailing_stop_pct))
        self.min_history_days = max(20, int(min_history_days))
        self.initial_capital = float(initial_capital)
        self.overnight_jump_threshold = max(0.05, float(overnight_jump_threshold))
        self.log_signals_enabled = bool(log_signals)

        self._current_top_n: set[str] = set()
        self._ordered_top_n: list[str] = []
        self._score_lookup: dict[str, dict[str, float]] = {}
        self._rebalance_pending = False
        self._rebalance_active_date: str | None = None

    def reset_state(self) -> None:
        self._current_top_n = set()
        self._ordered_top_n = []
        self._score_lookup = {}
        self._rebalance_pending = False
        self._rebalance_active_date = None

    def prepare_rebalance(
        self,
        market_data: pd.DataFrame,
        current_positions: dict[str, Any] | None = None,
    ) -> None:
        if market_data.empty:
            return

        frame = market_data.copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date", "symbol", "close"]).sort_values(["date", "symbol"])
        if frame.empty:
            return

        current_ts = pd.Timestamp(frame["date"].max())
        current_date = self._date_str(current_ts)
        if self._rebalance_active_date and current_date != self._rebalance_active_date:
            self._rebalance_active_date = None
            self._rebalance_pending = False

        if not self._is_rebalance_day(current_ts):
            return

        score_frame = self._compute_scores(frame, current_ts)
        if score_frame.empty:
            self._current_top_n = set()
            self._ordered_top_n = []
            self._score_lookup = {}
            self._rebalance_pending = True
            self._rebalance_active_date = current_date
            return

        top = score_frame.head(self.top_n).copy()
        self._ordered_top_n = [str(sym) for sym in top["symbol"].tolist()]
        self._current_top_n = set(self._ordered_top_n)
        self._score_lookup = {
            str(row["symbol"]): {
                "score": float(row["score"]),
                "raw_return": float(row["raw_return"]),
                "annualized_volatility": float(row["annualized_volatility"]),
            }
            for _, row in top.iterrows()
        }
        self._rebalance_pending = True
        self._rebalance_active_date = current_date

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict[str, Any] | None = None,
        current_positions: dict[str, Any] | None = None,
    ) -> list[Signal]:
        if not self._rebalance_pending or not self._rebalance_active_date:
            return []
        if market_data.empty or not self._ordered_top_n:
            self._rebalance_pending = False
            self._rebalance_active_date = None
            return []

        frame = market_data.copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date", "symbol", "close"]).sort_values(["date", "symbol"])
        if frame.empty:
            self._rebalance_pending = False
            self._rebalance_active_date = None
            return []

        today = self._date_str(pd.Timestamp(frame["date"].max()))
        if today != self._rebalance_active_date:
            self._rebalance_pending = False
            self._rebalance_active_date = None
            return []

        held_symbols = set((current_positions or {}).keys())
        target_weight = 1.0 / float(max(1, self.top_n))
        signals: list[Signal] = []
        for symbol in self._ordered_top_n:
            if symbol in held_symbols:
                continue
            sym = frame[frame["symbol"] == symbol]
            if sym.empty:
                continue
            latest = sym.iloc[-1]
            price = float(latest["close"])
            if price <= 0:
                continue
            stop_loss = float(price * (1.0 - self.trailing_stop_pct))
            target = float(price * 1.3)  # Placeholder; CSM exits are rebalance/trailing driven.
            score_meta = self._score_lookup.get(symbol, {})
            confidence = self._score_to_confidence(float(score_meta.get("score", 0.0)))

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
                    "target_weight": target_weight,
                    "rebalance_date": self._rebalance_active_date,
                    "momentum_score": float(score_meta.get("score", 0.0)),
                    "raw_return": float(score_meta.get("raw_return", 0.0)),
                    "annualized_volatility": float(score_meta.get("annualized_volatility", 0.0)),
                    "lookback_months": int(self.lookback_months),
                    "skip_recent_months": int(self.skip_recent_months),
                },
            )
            if self.log_signals_enabled:
                self.log_signal(signal)
            signals.append(signal)

        self._rebalance_pending = False
        self._rebalance_active_date = None
        return signals

    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        current_price = float(current_data.get("close", 0.0))
        if current_price <= 0:
            return False, None

        highest_close = float(position.get("highest_close", current_price))
        if current_price <= highest_close * (1.0 - self.trailing_stop_pct):
            return True, "STOP_LOSS"

        if self._rebalance_active_date:
            current_date = self._date_str(current_data.get("date"))
            symbol = str(position.get("symbol", "")).strip().upper()
            if current_date == self._rebalance_active_date and symbol and symbol not in self._current_top_n:
                return True, "REBALANCE_EXIT"

        return False, None

    @staticmethod
    def _date_str(value: Any) -> str:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return str(value)
        return str(pd.Timestamp(ts).date())

    @staticmethod
    def _score_to_confidence(score: float) -> float:
        # Keep confidence bounded and monotonic in score.
        return float(np.clip(0.5 + 0.4 * np.tanh(score / 4.0), 0.05, 0.99))

    @staticmethod
    def _is_rebalance_day(current_ts: pd.Timestamp) -> bool:
        # Use business month-end calendar; this handles weekends consistently.
        month_end = (current_ts + pd.offsets.BMonthEnd(0)).date()
        return current_ts.date() == month_end

    def _compute_scores(self, market_data: pd.DataFrame, current_ts: pd.Timestamp) -> pd.DataFrame:
        skip_end = current_ts - pd.DateOffset(months=self.skip_recent_months)
        lookback_start = skip_end - pd.DateOffset(months=self.lookback_months)

        rows: list[dict[str, float | str]] = []
        for symbol in sorted(market_data["symbol"].dropna().unique()):
            sym = market_data[market_data["symbol"] == symbol][["date", "close"]].copy()
            sym = sym.dropna(subset=["date", "close"]).sort_values("date")
            if sym.empty:
                continue

            full_window = sym[(sym["date"] > lookback_start) & (sym["date"] <= current_ts)].copy()
            if len(full_window) < self.min_history_days:
                continue
            window = full_window[full_window["date"] <= skip_end].copy()
            if len(window) < 20:
                continue

            pct = window["close"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
            if not pct.empty and bool((pct.abs() > self.overnight_jump_threshold).any()):
                continue

            start_price = float(window.iloc[0]["close"])
            end_price = float(window.iloc[-1]["close"])
            if start_price <= 0 or end_price <= 0:
                continue
            raw_return = (end_price / start_price) - 1.0

            vol = float(pct.std() * np.sqrt(252))
            vol = max(vol, 1e-6)
            score = raw_return / vol
            if not np.isfinite(score):
                continue

            rows.append(
                {
                    "symbol": str(symbol).upper(),
                    "score": float(score),
                    "raw_return": float(raw_return),
                    "annualized_volatility": float(vol),
                }
            )

        if not rows:
            return pd.DataFrame(columns=["symbol", "score", "raw_return", "annualized_volatility"])

        score_frame = pd.DataFrame(rows)
        score_frame["score"] = (
            pd.to_numeric(score_frame["score"], errors="coerce").replace([np.inf, -np.inf], np.nan)
        )
        score_frame = score_frame.dropna(subset=["score", "raw_return", "annualized_volatility"])
        if score_frame.empty:
            return score_frame

        if len(score_frame) >= 10:
            lower = float(score_frame["score"].quantile(0.01))
            upper = float(score_frame["score"].quantile(0.99))
            score_frame["score"] = score_frame["score"].clip(lower=lower, upper=upper)

        return score_frame.sort_values("score", ascending=False).reset_index(drop=True)
