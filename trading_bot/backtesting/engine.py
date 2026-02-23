from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
    def __init__(self, initial_capital: float = 100000) -> None:
        self.initial_capital = initial_capital
        self.state = BacktestState(cash=initial_capital)
        # Per-side brokerage/tax cost for entry and exit legs.
        self.transaction_costs = Config.COST_PER_SIDE

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
        for current_date in sorted(data["date"].dt.date.unique()):
            if current_date < start_ts.date():
                continue
            daily = data[data["date"].dt.date == current_date]
            history = data[data["date"].dt.date <= current_date]
            self._process_exits(strategy, str(current_date), daily, history)

            regime = compute_market_regime(history) if include_regime else None
            if regime is not None:
                regime_snapshots.append(regime)
            signals = strategy.generate_signals(history, alternative_data, market_regime=regime)
            for signal in signals:
                self._execute_signal(signal, str(current_date), daily)

            self._record_snapshot(str(current_date), daily)

        final_date = str(max(test_dates))
        self._close_all_positions(final_date, data[data["date"].dt.date == pd.to_datetime(final_date).date()])
        return self._calculate_results(
            strategy.name,
            start_date,
            end_date,
            regime_snapshots=regime_snapshots,
            include_regime=include_regime,
        )

    def _execute_signal(self, signal: Signal, current_date: str, daily_data: pd.DataFrame) -> None:
        if signal.symbol in self.state.positions:
            return
        if len(self.state.positions) >= Config.MAX_POSITIONS:
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

        self.state.positions[signal.symbol] = Position(
            symbol=signal.symbol,
            strategy=signal.strategy,
            entry_date=current_date,
            entry_price=price,
            quantity=quantity,
            stop_loss=float(signal.stop_loss),
            target=float(signal.target),
            transaction_cost=tx_cost,
            highest_close=price,
            lowest_close=price,
            metadata={**dict(signal.metadata or {}), "last_mark_price": price},
        )
        self.state.cash -= total

    def _process_exits(
        self,
        strategy: BaseStrategy,
        current_date: str,
        daily_data: pd.DataFrame,
        history_data: pd.DataFrame,
    ) -> None:
        to_close: list[tuple[str, float, str]] = []
        ema_cache: dict[str, tuple[float, float]] = {}
        if hasattr(strategy, "weekly_ema_short") and hasattr(strategy, "weekly_ema_long"):
            ema_cache = self._compute_weekly_ema_cache(
                history_data=history_data,
                symbols=set(self.state.positions.keys()),
                ema_short=int(getattr(strategy, "weekly_ema_short")),
                ema_long=int(getattr(strategy, "weekly_ema_long")),
            )
        for symbol, position in self.state.positions.items():
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

        self.state.cash += (exit_price * position.quantity) - exit_cost

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
            }
        )

    def _close_all_positions(self, final_date: str, final_data: pd.DataFrame) -> None:
        for symbol in list(self.state.positions.keys()):
            row = final_data[final_data["symbol"] == symbol]
            if row.empty:
                continue
            self._close_position(symbol, final_date, float(row.iloc[0]["close"]), "BACKTEST_END")

    def _record_snapshot(self, date: str, daily_data: pd.DataFrame) -> None:
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
            }
        )

    def _calculate_position_size(self, signal: Signal) -> int:
        risk_amount = self.initial_capital * Config.RISK_PER_TRADE
        risk_per_share = signal.price - signal.stop_loss
        if risk_per_share <= 0:
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

    def _calculate_results(
        self,
        strategy_name: str,
        start_date: str,
        end_date: str,
        *,
        regime_snapshots: list[dict[str, Any]] | None = None,
        include_regime: bool = True,
    ) -> dict:
        regime_summary = self._summarize_regimes(regime_snapshots or [], include_regime)
        if not self.state.closed_trades:
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
        }


backtest_engine = BacktestEngine()
