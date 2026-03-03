from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, cast

import numpy as np
import pandas as pd
from loguru import logger

from trading_bot.config.settings import Config
from trading_bot.data.processors.regime import compute_market_regime
from trading_bot.strategies.base_strategy import BaseStrategy, Signal


@dataclass
class Position:
    symbol: str
    strategy: str
    entry_date: str
    entry_price: float
    quantity: int
    stop_loss: float
    target: float
    confidence: float = 0.0
    days_held: int = 0
    transaction_cost: float = 0.0
    highest_close: float = 0.0
    lowest_close: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BacktestState:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    closed_trades: list[dict] = field(default_factory=list)
    portfolio_history: list[dict] = field(default_factory=list)


class BacktestEngine:
    def __init__(
        self,
        initial_capital: float = 100000,
        *,
        sizing_mode: str = "atr",
        max_positions: int | None = None,
    ) -> None:
        self.initial_capital = initial_capital
        self.state = BacktestState(cash=initial_capital)
        # Per-side brokerage/tax cost for entry and exit legs.
        self.transaction_costs = Config.COST_PER_SIDE
        self.sizing_mode = str(sizing_mode or "atr").strip().lower()
        self.max_positions = int(max_positions) if max_positions is not None else None

    def run_backtest(
        self,
        strategy: BaseStrategy,
        market_data: pd.DataFrame,
        start_date: str,
        end_date: str,
        alternative_data: pd.DataFrame | None = None,
        warmup_days: int = 260,
        include_regime: bool = True,
    ) -> dict:
        data = market_data.copy()
        data["date"] = pd.to_datetime(data["date"])
        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)
        warmup_start = start_ts - pd.Timedelta(days=max(0, int(warmup_days)))
        data = data[(data["date"] >= warmup_start) & (data["date"] <= end_ts)]
        data = data.sort_values(["date", "symbol"])
        if data.empty:
            return {"error": "No market data for selected period"}

        test_dates = sorted(
            data[(data["date"] >= start_ts) & (data["date"] <= end_ts)]["date"].dt.date.unique()
        )
        if not test_dates:
            return {"error": "No market data for selected period"}

        regime_snapshots: list[dict[str, Any]] = []
        data_quality_warnings: list[dict[str, Any]] = []
        generate_params = inspect.signature(strategy.generate_signals).parameters
        has_positions_param = "current_positions" in generate_params
        prepare_rebalance_fn = getattr(strategy, "prepare_rebalance", None)
        has_prepare_rebalance = callable(prepare_rebalance_fn)
        prepare_accepts_positions = False
        if has_prepare_rebalance:
            try:
                prepare_accepts_positions = (
                    "current_positions"
                    in inspect.signature(cast(Callable[..., Any], prepare_rebalance_fn)).parameters
                )
            except (TypeError, ValueError):
                prepare_accepts_positions = False
        for current_date in sorted(data["date"].dt.date.unique()):
            if current_date < start_ts.date():
                continue
            daily = data[data["date"].dt.date == current_date]
            history = data[data["date"].dt.date <= current_date]
            daily_warnings = self._detect_overnight_jumps(
                current_date=str(current_date),
                daily_data=daily,
                history_data=history,
            )
            if daily_warnings:
                data_quality_warnings.extend(daily_warnings)
            blocked_symbols = {str(item["symbol"]) for item in daily_warnings}
            if blocked_symbols:
                logger.warning(
                    "Backtest data-quality guardrail: blocked symbols on {} due to overnight jumps: {}",
                    str(current_date),
                    sorted(blocked_symbols),
                )

            if has_prepare_rebalance:
                if prepare_accepts_positions:
                    cast(Callable[..., Any], prepare_rebalance_fn)(
                        history,
                        current_positions=self._position_snapshot(),
                    )
                else:
                    cast(Callable[..., Any], prepare_rebalance_fn)(history)

            self._process_exits(strategy, str(current_date), daily, history, blocked_symbols=blocked_symbols)

            regime = compute_market_regime(history) if include_regime else None
            regime_label = self._normalize_regime_label((regime or {}).get("regime_label", "unknown"))
            if regime is not None:
                regime_snapshots.append(regime)
            if has_positions_param:
                signals = cast(Any, strategy).generate_signals(
                    history,
                    alternative_data,
                    market_regime=regime,
                    current_positions=self._position_snapshot(),
                )
            else:
                signals = strategy.generate_signals(history, alternative_data, market_regime=regime)
            for signal in signals:
                if str(signal.symbol) in blocked_symbols:
                    continue
                self._execute_signal(
                    signal,
                    str(current_date),
                    daily,
                    regime_label=regime_label,
                    market_regime=regime,
                )

            self._record_snapshot(str(current_date), daily, regime_label=regime_label)

        final_date = str(max(test_dates))
        self._close_all_positions(final_date, data[data["date"].dt.date == pd.to_datetime(final_date).date()])
        return self._calculate_results(
            strategy.name,
            start_date,
            end_date,
            regime_snapshots=regime_snapshots,
            include_regime=include_regime,
            data_quality_warnings=data_quality_warnings,
        )

    @staticmethod
    def _normalize_regime_label(label: Any) -> str:
        value = str(label).strip().lower()
        if not value or value in {"none", "nan", "null"}:
            return "unknown"
        return value

    def _execute_signal(
        self,
        signal: Signal,
        current_date: str,
        daily_data: pd.DataFrame,
        *,
        regime_label: str = "unknown",
        market_regime: dict[str, Any] | None = None,
    ) -> None:
        if signal.symbol in self.state.positions:
            return
        max_positions = self.max_positions if self.max_positions is not None else int(Config.MAX_POSITIONS)
        if len(self.state.positions) >= max_positions:
            return

        row = daily_data[daily_data["symbol"] == signal.symbol]
        if row.empty:
            return

        price = float(row.iloc[0]["close"])
        signal.price = price

        quantity = self._calculate_position_size(signal)
        if quantity <= 0:
            return

        position_value = quantity * price
        tx_cost = position_value * self.transaction_costs
        total = position_value + tx_cost
        if total > self.state.cash:
            return

        metadata = {**dict(signal.metadata or {}), "last_mark_price": price}
        if market_regime:
            metadata["market_regime_label"] = self._normalize_regime_label(
                str(market_regime.get("regime_label", regime_label))
            )
            metadata["market_regime_confidence"] = float(
                market_regime.get("confidence", metadata.get("regime_confidence", 0.5))
            )
            metadata["market_breadth_ratio"] = float(
                market_regime.get("breadth_ratio", metadata.get("regime_breadth_ratio", 0.0))
            )
            metadata["market_annualized_volatility"] = float(
                market_regime.get("annualized_volatility", metadata.get("regime_annualized_volatility", 0.0))
            )
            metadata["market_regime_trend_up"] = bool(market_regime.get("trend_up", True))
            metadata["market_breadth_favorable"] = bool(market_regime.get("is_favorable", True))
        entry_regime_label = self._normalize_regime_label(metadata.get("regime_label", regime_label))
        metadata["entry_regime_label"] = entry_regime_label
        metadata["regime_label"] = entry_regime_label
        metadata["market_regime_label"] = self._normalize_regime_label(
            metadata.get("market_regime_label", entry_regime_label)
        )
        if "market_regime_confidence" not in metadata:
            metadata["market_regime_confidence"] = float(metadata.get("regime_confidence", 0.5))
        if "market_breadth_ratio" not in metadata:
            metadata["market_breadth_ratio"] = float(metadata.get("regime_breadth_ratio", 0.0))
        if "market_annualized_volatility" not in metadata:
            metadata["market_annualized_volatility"] = float(metadata.get("regime_annualized_volatility", 0.0))
        if "market_regime_trend_up" not in metadata:
            metadata["market_regime_trend_up"] = bool(metadata.get("regime_trend_up", True))

        self.state.positions[signal.symbol] = Position(
            symbol=signal.symbol,
            strategy=signal.strategy,
            entry_date=current_date,
            entry_price=price,
            quantity=quantity,
            stop_loss=float(signal.stop_loss),
            target=float(signal.target),
            confidence=float(signal.confidence),
            transaction_cost=tx_cost,
            highest_close=price,
            lowest_close=price,
            metadata=metadata,
        )
        self.state.cash -= total

    @staticmethod
    def _detect_overnight_jumps(
        *,
        current_date: str,
        daily_data: pd.DataFrame,
        history_data: pd.DataFrame,
        threshold_pct: float = 0.35,
    ) -> list[dict[str, Any]]:
        if daily_data.empty:
            return []

        symbols = [str(sym) for sym in daily_data["symbol"].dropna().unique()]
        if not symbols:
            return []

        hist = history_data[history_data["symbol"].isin(symbols)][["symbol", "date", "close", "volume"]].copy()
        if hist.empty:
            return []
        hist["date"] = pd.to_datetime(hist["date"], errors="coerce")
        hist = hist.dropna(subset=["symbol", "date", "close"]).sort_values(["symbol", "date"])
        if hist.empty:
            return []

        warnings: list[dict[str, Any]] = []
        for symbol, group in hist.groupby("symbol", sort=False):
            last_two = group.tail(2)
            if len(last_two) < 2:
                continue
            prev = last_two.iloc[-2]
            curr = last_two.iloc[-1]

            curr_date = pd.to_datetime(curr["date"]).date()
            if str(curr_date) != str(current_date):
                continue

            prev_close = float(prev["close"])
            curr_close = float(curr["close"])
            prev_volume = float(prev["volume"]) if pd.notna(prev["volume"]) else 0.0
            if prev_close <= 0 or prev_volume <= 0:
                continue

            pct_change = (curr_close - prev_close) / prev_close
            if abs(pct_change) > threshold_pct:
                warnings.append(
                    {
                        "symbol": str(symbol),
                        "date": str(current_date),
                        "prev_close": prev_close,
                        "current_close": curr_close,
                        "pct_change": float(pct_change),
                        "threshold_pct": float(threshold_pct),
                        "reason": "overnight_jump_suspect_corporate_action",
                    }
                )

        return warnings

    def _position_snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            symbol: {
                "symbol": symbol,
                "entry_price": float(position.entry_price),
                "quantity": int(position.quantity),
                "entry_date": str(position.entry_date),
                "days_held": int(position.days_held),
                "highest_close": float(position.highest_close),
                "lowest_close": float(position.lowest_close),
                "stop_loss": float(position.stop_loss),
                "target": float(position.target),
            }
            for symbol, position in self.state.positions.items()
        }

    def _process_exits(
        self,
        strategy: BaseStrategy,
        current_date: str,
        daily_data: pd.DataFrame,
        history_data: pd.DataFrame,
        *,
        blocked_symbols: set[str] | None = None,
    ) -> None:
        to_close: list[tuple[str, float, str]] = []
        blocked = blocked_symbols or set()
        ema_cache: dict[str, tuple[float, float]] = {}
        if hasattr(strategy, "weekly_ema_short") and hasattr(strategy, "weekly_ema_long"):
            ema_cache = self._compute_weekly_ema_cache(
                history_data=history_data,
                symbols=set(self.state.positions.keys()),
                ema_short=int(getattr(strategy, "weekly_ema_short")),
                ema_long=int(getattr(strategy, "weekly_ema_long")),
            )
        for symbol, position in self.state.positions.items():
            if symbol in blocked:
                continue
            row = daily_data[daily_data["symbol"] == symbol]
            if row.empty:
                continue
            current = row.iloc[0]
            position.days_held += 1
            current_close = float(current["close"])
            position.highest_close = max(position.highest_close, current_close)
            position.lowest_close = min(position.lowest_close, current_close)
            position.metadata["last_mark_price"] = current_close
            current_ema = ema_cache.get(symbol)
            should_exit, reason = strategy.check_exit_conditions(
                {
                    "symbol": symbol,
                    "entry_price": position.entry_price,
                    "stop_loss": position.stop_loss,
                    "target": position.target,
                    "days_held": position.days_held,
                    "highest_close": position.highest_close,
                    "lowest_close": position.lowest_close,
                    "metadata": position.metadata,
                    "weekly_atr": float(position.metadata.get("weekly_atr", 0.0)),
                    "current_weekly_ema_short": current_ema[0] if current_ema else None,
                    "current_weekly_ema_long": current_ema[1] if current_ema else None,
                },
                current,
            )
            if should_exit:
                to_close.append((symbol, float(current["close"]), reason or "EXIT"))

        for symbol, exit_price, reason in to_close:
            self._close_position(symbol, current_date, exit_price, reason)

    def _close_position(self, symbol: str, exit_date: str, exit_price: float, reason: str) -> None:
        position = self.state.positions.pop(symbol)
        gross_pnl = (exit_price - position.entry_price) * position.quantity
        exit_cost = exit_price * position.quantity * self.transaction_costs
        net_pnl = gross_pnl - position.transaction_cost - exit_cost
        entry_cost = position.entry_price * position.quantity + position.transaction_cost
        pnl_percent = (net_pnl / entry_cost) * 100 if entry_cost else 0.0
        mfe = (
            (position.highest_close - position.entry_price) / position.entry_price
            if position.entry_price > 0
            else 0.0
        )
        mae = (
            (position.entry_price - position.lowest_close) / position.entry_price
            if position.entry_price > 0
            else 0.0
        )
        metadata_snapshot = dict(position.metadata)

        self.state.cash += (exit_price * position.quantity) - exit_cost

        entry_regime_label = self._normalize_regime_label(
            position.metadata.get("entry_regime_label", position.metadata.get("regime_label", "unknown"))
        )
        self.state.closed_trades.append(
            {
                "symbol": symbol,
                "strategy": position.strategy,
                "entry_date": position.entry_date,
                "exit_date": exit_date,
                "entry_price": position.entry_price,
                "exit_price": exit_price,
                "quantity": position.quantity,
                "days_held": position.days_held,
                "net_pnl": net_pnl,
                "pnl_percent": pnl_percent,
                "exit_reason": reason,
                "entry_regime_label": entry_regime_label,
                "confidence": float(position.confidence),
                "stop_loss": float(position.stop_loss),
                "target": float(position.target),
                "mfe": float(mfe),
                "mae": float(mae),
                "metadata": metadata_snapshot,
            }
        )

    def _close_all_positions(self, final_date: str, final_data: pd.DataFrame) -> None:
        for symbol in list(self.state.positions.keys()):
            row = final_data[final_data["symbol"] == symbol]
            if row.empty:
                continue
            self._close_position(symbol, final_date, float(row.iloc[0]["close"]), "BACKTEST_END")

    def _record_snapshot(self, date: str, daily_data: pd.DataFrame, *, regime_label: str = "unknown") -> None:
        positions_value = 0.0
        for symbol, pos in self.state.positions.items():
            row = daily_data[daily_data["symbol"] == symbol]
            if row.empty:
                mark_price = float(pos.metadata.get("last_mark_price", pos.entry_price))
            else:
                mark_price = float(row.iloc[0]["close"])
                pos.metadata["last_mark_price"] = mark_price
            positions_value += pos.quantity * mark_price

        total = self.state.cash + positions_value
        self.state.portfolio_history.append(
            {
                "date": date,
                "total_value": total,
                "cash": self.state.cash,
                "positions_value": positions_value,
                "num_positions": len(self.state.positions),
                "regime_label": self._normalize_regime_label(regime_label),
            }
        )

    def _current_portfolio_equity(self) -> float:
        positions_value = 0.0
        for pos in self.state.positions.values():
            mark_price = float(pos.metadata.get("last_mark_price", pos.entry_price))
            positions_value += pos.quantity * mark_price
        return max(0.0, float(self.state.cash + positions_value))

    def _calculate_position_size(self, signal: Signal) -> int:
        if self.sizing_mode == "equal_weight":
            metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
            target_weight = float(metadata.get("target_weight", 0.0))
            target_alloc = float(metadata.get("target_allocation", 0.0))
            if target_alloc <= 0 and target_weight > 0:
                target_alloc = target_weight * self._current_portfolio_equity()
            if target_alloc <= 0 or signal.price <= 0:
                return 0
            shares = int(target_alloc / signal.price)
            required = shares * signal.price * (1 + self.transaction_costs)
            if required > self.state.cash:
                shares = int(self.state.cash / (signal.price * (1 + self.transaction_costs)))
            return max(shares, 0)

        risk_amount = self.initial_capital * Config.RISK_PER_TRADE
        risk_per_share = signal.price - signal.stop_loss
        if risk_per_share <= 0:
            return 0

        strategy_key = str(signal.strategy).strip().lower().replace(" ", "_")
        if strategy_key == "adaptive_trend":
            metadata = signal.metadata if isinstance(signal.metadata, dict) else {}
            risk_amount *= self._adaptive_regime_size_multiplier(metadata)
            if risk_amount <= 0:
                return 0

        shares = int(risk_amount / risk_per_share)
        max_value = self.initial_capital * Config.MAX_POSITION_SIZE
        max_shares = int(max_value / signal.price)
        shares = min(shares, max_shares)

        if Config.MAX_LOSS_PER_TRADE > 0:
            max_loss_shares = int(Config.MAX_LOSS_PER_TRADE * self.initial_capital / risk_per_share)
            shares = min(shares, max_loss_shares)

        required = shares * signal.price * (1 + self.transaction_costs)
        if required > self.state.cash:
            shares = int(self.state.cash / (signal.price * (1 + self.transaction_costs)))
        return max(shares, 0)

    @staticmethod
    def _adaptive_regime_size_multiplier(metadata: dict[str, Any]) -> float:
        if not Config.ADAPTIVE_REGIME_SIZE_SCALING_ENABLED:
            return 1.0

        label = str(
            metadata.get(
                "market_regime_label",
                metadata.get("regime_label", "unknown"),
            )
        ).strip().lower()
        if label == "favorable":
            return max(0.0, float(Config.ADAPTIVE_REGIME_SIZE_MULT_FAVORABLE))
        if label == "choppy":
            return max(0.0, float(Config.ADAPTIVE_REGIME_SIZE_MULT_CHOPPY))
        if label == "bearish":
            return max(0.0, float(Config.ADAPTIVE_REGIME_SIZE_MULT_BEARISH))
        if label == "defensive":
            return max(0.0, float(Config.ADAPTIVE_REGIME_SIZE_MULT_DEFENSIVE))

        favorable = bool(
            metadata.get(
                "market_breadth_favorable",
                metadata.get("regime_favorable", True),
            )
        )
        if favorable:
            return max(0.0, float(Config.ADAPTIVE_REGIME_SIZE_MULT_FAVORABLE))
        return max(0.0, float(Config.ADAPTIVE_REGIME_SIZE_MULT_CHOPPY))

    def _compute_weekly_ema_cache(
        self,
        *,
        history_data: pd.DataFrame,
        symbols: set[str],
        ema_short: int,
        ema_long: int,
    ) -> dict[str, tuple[float, float]]:
        if not symbols:
            return {}
        cache: dict[str, tuple[float, float]] = {}
        frame = history_data[history_data["symbol"].isin(symbols)].copy()
        if frame.empty:
            return cache
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date", "close"]).sort_values(["symbol", "date"])
        if frame.empty:
            return cache

        for symbol in symbols:
            sym = frame[frame["symbol"] == symbol]
            if sym.empty:
                continue
            weekly = (
                sym.set_index("date")
                .resample("W-FRI")
                .agg({"close": "last"})
                .dropna()
            )
            if len(weekly) < max(ema_short, ema_long):
                continue
            ema_s = weekly["close"].ewm(span=ema_short, adjust=False).mean().iloc[-1]
            ema_l = weekly["close"].ewm(span=ema_long, adjust=False).mean().iloc[-1]
            if pd.notna(ema_s) and pd.notna(ema_l):
                cache[symbol] = (float(ema_s), float(ema_l))
        return cache

    @staticmethod
    def _summarize_regimes(regime_snapshots: list[dict[str, Any]], include_regime: bool) -> dict[str, Any]:
        total_days = len(regime_snapshots)
        favorable_days = sum(1 for item in regime_snapshots if bool(item.get("is_favorable", False)))
        defensive_days = sum(1 for item in regime_snapshots if str(item.get("regime_label", "")) == "defensive")
        label_counts: dict[str, int] = {}
        for item in regime_snapshots:
            label = str(item.get("regime_label", "unknown"))
            label_counts[label] = label_counts.get(label, 0) + 1

        return {
            "include_regime": bool(include_regime),
            "favorable_days": favorable_days,
            "defensive_days": defensive_days,
            "total_days": total_days,
            "favorable_pct": (favorable_days / max(total_days, 1)),
            "label_counts": label_counts,
        }

    def _compute_regime_metrics(self, portfolio_df: pd.DataFrame, trades_df: pd.DataFrame) -> dict[str, Any]:
        regime_daily: dict[str, dict[str, float | int]] = {}
        if not portfolio_df.empty:
            day_frame = portfolio_df.copy()
            if "regime_label" not in day_frame:
                day_frame["regime_label"] = "unknown"
            day_frame["regime_label"] = day_frame["regime_label"].map(self._normalize_regime_label)
            day_frame["daily_pnl"] = day_frame["total_value"].diff().fillna(0.0)
            day_frame["daily_return"] = day_frame["total_value"].pct_change().fillna(0.0)

            for label, group in day_frame.groupby("regime_label"):
                std = float(group["daily_return"].std())
                sharpe = float((group["daily_return"].mean() / std) * np.sqrt(252)) if std > 0 else 0.0
                regime_daily[label] = {
                    "days": int(len(group)),
                    "total_pnl": float(group["daily_pnl"].sum()),
                    "avg_daily_return": float(group["daily_return"].mean()),
                    "std_daily_return": std,
                    "sharpe_ratio": sharpe,
                }

        trade_entry_regime: dict[str, dict[str, float | int]] = {}
        trade_frame = trades_df.copy()
        if "entry_regime_label" not in trade_frame:
            trade_frame["entry_regime_label"] = "unknown"
        trade_frame["entry_regime_label"] = trade_frame["entry_regime_label"].map(self._normalize_regime_label)

        for label, group in trade_frame.groupby("entry_regime_label"):
            wins = group[group["net_pnl"] > 0]
            losses = group[group["net_pnl"] < 0]
            win_sum = float(wins["net_pnl"].sum())
            loss_sum_abs = abs(float(losses["net_pnl"].sum()))
            trade_entry_regime[label] = {
                "trades": int(len(group)),
                "wins": int(len(wins)),
                "win_rate": float(len(wins) / len(group)) if len(group) else 0.0,
                "total_pnl": float(group["net_pnl"].sum()),
                "avg_pnl": float(group["net_pnl"].mean()) if len(group) else 0.0,
                "profit_factor": (win_sum / loss_sum_abs) if loss_sum_abs > 0 else 0.0,
            }

        stop_loss_trades = trade_frame[trade_frame["exit_reason"] == "STOP_LOSS"]
        worst_stop_loss = abs(float(stop_loss_trades["net_pnl"].min())) if not stop_loss_trades.empty else 0.0
        return {
            "daily_returns_by_regime": regime_daily,
            "entry_regime_trade_metrics": trade_entry_regime,
            "unknown_days": int(regime_daily.get("unknown", {}).get("days", 0)),
            "unknown_trades": int(trade_entry_regime.get("unknown", {}).get("trades", 0)),
            "single_stop_loss_max_abs": worst_stop_loss,
            "single_stop_loss_max_pct_capital": (worst_stop_loss / self.initial_capital) if self.initial_capital > 0 else 0.0,
        }

    def _calculate_results(
        self,
        strategy_name: str,
        start_date: str,
        end_date: str,
        *,
        regime_snapshots: list[dict[str, Any]] | None = None,
        include_regime: bool = True,
        data_quality_warnings: list[dict[str, Any]] | None = None,
    ) -> dict:
        regime_summary = self._summarize_regimes(regime_snapshots or [], include_regime)
        warnings = list(data_quality_warnings or [])
        quality_clean = len(warnings) == 0
        if not self.state.closed_trades:
            portfolio_df = pd.DataFrame(self.state.portfolio_history)
            empty_trades_df = pd.DataFrame(columns=["net_pnl", "exit_reason", "entry_regime_label"])
            regime_metrics = self._compute_regime_metrics(portfolio_df, empty_trades_df)
            return {
                "strategy": strategy_name,
                "period": f"{start_date} to {end_date}",
                "total_trades": 0,
                "total_return_pct": 0.0,
                "win_rate": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "trades": [],
                "portfolio_history": self.state.portfolio_history,
                "regime_summary": regime_summary,
                "regime_metrics": regime_metrics,
                "data_quality_clean": quality_clean,
                "data_quality_warnings": warnings,
            }

        trades_df = pd.DataFrame(self.state.closed_trades)
        portfolio_df = pd.DataFrame(self.state.portfolio_history)

        total_pnl = float(trades_df["net_pnl"].sum())
        total_return_pct = (total_pnl / self.initial_capital) * 100
        wins = trades_df[trades_df["net_pnl"] > 0]
        losses = trades_df[trades_df["net_pnl"] < 0]
        win_rate = len(wins) / len(trades_df)

        portfolio_df["peak"] = portfolio_df["total_value"].cummax()
        portfolio_df["drawdown"] = (portfolio_df["total_value"] - portfolio_df["peak"]) / portfolio_df["peak"]
        max_drawdown = float(portfolio_df["drawdown"].min()) if not portfolio_df.empty else 0.0

        portfolio_df["returns"] = portfolio_df["total_value"].pct_change().fillna(0.0)
        std = portfolio_df["returns"].std()
        sharpe = float((portfolio_df["returns"].mean() / std) * np.sqrt(252)) if std != 0 else 0.0
        regime_metrics = self._compute_regime_metrics(portfolio_df, trades_df)

        return {
            "strategy": strategy_name,
            "period": f"{start_date} to {end_date}",
            "initial_capital": self.initial_capital,
            "final_capital": self.state.cash,
            "total_pnl": total_pnl,
            "total_return_pct": total_return_pct,
            "total_trades": len(trades_df),
            "win_rate": win_rate,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe,
            "trades": self.state.closed_trades,
            "portfolio_history": self.state.portfolio_history,
            "regime_summary": regime_summary,
            "regime_metrics": regime_metrics,
            "data_quality_clean": quality_clean,
            "data_quality_warnings": warnings,
        }


backtest_engine = BacktestEngine()
