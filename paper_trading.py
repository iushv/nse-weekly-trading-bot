from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

from main import TradingBot


class PaperTradingSimulator:
    def __init__(self, start_date: str, end_date: str) -> None:
        self.bot = TradingBot(paper_mode=True, simulation_mode=True)
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date)

    def run_simulation(self) -> None:
        current = self.start_date
        while current <= self.end_date:
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue

            logger.info(f"Simulating trading day {current.date()}")
            try:
                # Freeze bot clock for deterministic replay and date-bound DB queries.
                self.bot.set_simulation_date(datetime.combine(current.date(), datetime.min.time()))
                self.bot.pre_market_routine()
                self.bot.market_open_routine()
                self.bot.intraday_monitoring()
                self.bot.market_close_routine()
            except Exception as exc:
                logger.error(f"Simulation error on {current.date()}: {exc}")

            current += timedelta(days=1)

        logger.info(f"Final Portfolio Value: ₹{self.bot.portfolio_value:,.2f}")


if __name__ == "__main__":
    sim = PaperTradingSimulator("2024-01-01", "2024-03-31")
    sim.run_simulation()
