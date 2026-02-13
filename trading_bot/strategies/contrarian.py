from __future__ import annotations

import pandas as pd

from trading_bot.strategies.base_strategy import BaseStrategy, Signal


class ContrarianStrategy(BaseStrategy):
    """Experimental placeholder strategy."""

    def __init__(self) -> None:
        super().__init__("Contrarian")

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict | None = None,
    ) -> list[Signal]:
        return []

    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        return False, None
