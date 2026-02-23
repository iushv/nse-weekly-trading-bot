from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable

from loguru import logger

from trading_bot.config.settings import Config
from trading_bot.strategies.base_strategy import Signal


class RiskManager:
    def __init__(self, initial_capital: float, clock: Callable[[], datetime] | None = None) -> None:
        self.capital = initial_capital
        self._clock = clock or datetime.now
        self.daily_pnl = 0.0
        self.weekly_pnl = 0.0
        self.trading_day_start = self._clock().date()
        self.week_start = self._get_week_start()

    def _get_week_start(self) -> datetime:
        now = self._clock()
        return now - timedelta(days=now.weekday())

    def check_can_trade(self) -> bool:
        now = self._clock()
        current_day = now.date()
        if current_day != self.trading_day_start:
            self.daily_pnl = 0.0
            self.trading_day_start = current_day

        current_week_start = self._get_week_start()
        if current_week_start != self.week_start:
            self.weekly_pnl = 0.0
            self.week_start = current_week_start

        daily_loss_pct = abs(self.daily_pnl / self.capital)
        if daily_loss_pct >= Config.DAILY_LOSS_LIMIT:
            logger.warning(f"Daily loss limit hit: {daily_loss_pct:.2%}")
            return False

        weekly_loss_pct = abs(self.weekly_pnl / self.capital)
        if weekly_loss_pct >= Config.WEEKLY_LOSS_LIMIT:
            logger.warning(f"Weekly loss limit hit: {weekly_loss_pct:.2%}")
            return False

        return True

    def validate_signals(self, signals: list[Signal], current_positions: dict) -> list[Signal]:
        """
        Backward-compatible validation.
        Prefer `validate_sized_signals` after quantity is computed.
        """
        if not self.check_can_trade():
            return []

        valid: list[Signal] = []
        for signal in signals:
            if signal.symbol in current_positions:
                continue
            if len(current_positions) + len(valid) >= Config.MAX_POSITIONS:
                break
            if self._check_portfolio_heat(signal, current_positions):
                valid.append(signal)
        return valid

    def validate_sized_signals(self, signals: list[Signal], current_positions: dict) -> list[Signal]:
        """
        Validate already-sized signals against max positions and cumulative heat.
        """
        if not self.check_can_trade():
            return []

        accepted: list[Signal] = []
        seen_symbols = set(current_positions.keys())
        running_heat = self.calculate_portfolio_heat(current_positions)

        for signal in signals:
            if signal.quantity <= 0:
                continue
            if signal.symbol in seen_symbols:
                continue
            if len(current_positions) + len(accepted) >= Config.MAX_POSITIONS:
                break

            next_heat = running_heat + self._signal_risk(signal)
            if next_heat > Config.MAX_PORTFOLIO_HEAT:
                logger.debug(f"Skipping {signal.symbol}: heat {next_heat:.4f} > {Config.MAX_PORTFOLIO_HEAT:.4f}")
                continue

            accepted.append(signal)
            seen_symbols.add(signal.symbol)
            running_heat = next_heat

        return accepted

    def calculate_portfolio_heat(self, current_positions: dict) -> float:
        current_heat_value = 0.0
        for pos in current_positions.values():
            risk_per_share = max(float(pos["entry_price"]) - float(pos["stop_loss"]), 0.0)
            current_heat_value += risk_per_share * float(pos["quantity"])
        return current_heat_value / self.capital if self.capital else 0.0

    def _signal_risk(self, signal: Signal) -> float:
        risk_per_share = max(float(signal.price) - float(signal.stop_loss), 0.0)
        return (risk_per_share * float(signal.quantity)) / self.capital if self.capital else 0.0

    def _check_portfolio_heat(self, signal: Signal, current_positions: dict) -> bool:
        current_heat = self.calculate_portfolio_heat(current_positions)
        proposed_risk = self._signal_risk(signal)
        total_heat = current_heat + proposed_risk
        return total_heat <= Config.MAX_PORTFOLIO_HEAT

    def update_pnl(self, pnl: float) -> None:
        self.daily_pnl += pnl
        self.weekly_pnl += pnl

    def reconstruct_realized_pnl(self, engine: Any, today: date) -> None:
        """Restore daily/weekly realized PnL after process restart."""
        week_start = today - timedelta(days=today.weekday())
        query = """
            SELECT
                COALESCE(SUM(CASE WHEN date(exit_date) = :today THEN COALESCE(pnl, 0) ELSE 0 END), 0) AS daily_total,
                COALESCE(SUM(CASE WHEN date(exit_date) >= :week_start AND date(exit_date) <= :today THEN COALESCE(pnl, 0) ELSE 0 END), 0) AS weekly_total
            FROM trades
            WHERE status = 'CLOSED'
        """
        try:
            import pandas as pd

            df = pd.read_sql(
                query,
                engine,
                params={"today": today.isoformat(), "week_start": week_start.isoformat()},
            )
            if not df.empty:
                self.daily_pnl = float(df.iloc[0].get("daily_total", 0.0) or 0.0)
                self.weekly_pnl = float(df.iloc[0].get("weekly_total", 0.0) or 0.0)
        except Exception as exc:
            logger.warning(f"RiskManager PnL reconstruction skipped: {exc}")

    def check_emergency_stop(self, portfolio_value: float) -> bool:
        drawdown = (portfolio_value - self.capital) / self.capital
        if drawdown <= -Config.MAX_DRAWDOWN:
            logger.error(f"Emergency stop triggered at drawdown {drawdown:.2%}")
            return True
        return False

    def get_risk_report(self) -> dict:
        return {
            "can_trade": self.check_can_trade(),
            "daily_pnl": self.daily_pnl,
            "weekly_pnl": self.weekly_pnl,
            "daily_limit_pct": Config.DAILY_LOSS_LIMIT * 100,
            "weekly_limit_pct": Config.WEEKLY_LOSS_LIMIT * 100,
        }
