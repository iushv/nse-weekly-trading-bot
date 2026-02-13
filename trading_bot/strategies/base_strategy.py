from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
from loguru import logger


@dataclass
class Signal:
    symbol: str
    action: str
    price: float
    quantity: int
    stop_loss: float
    target: float
    strategy: str
    confidence: float
    timestamp: datetime
    metadata: dict[str, Any] | None = None


class BaseStrategy(ABC):
    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict[str, Any] | None = None,
    ) -> list[Signal]:
        pass

    @abstractmethod
    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        pass

    def calculate_stop_loss(self, entry_price: float, atr: float, direction: str = "LONG") -> float:
        mult = 2.0
        if direction == "LONG":
            return float(entry_price - (mult * atr))
        return float(entry_price + (mult * atr))

    def calculate_target(self, entry_price: float, stop_loss: float, rr: float = 2.0) -> float:
        risk = abs(entry_price - stop_loss)
        return float(entry_price + (risk * rr))

    def log_signal(self, signal: Signal) -> None:
        logger.info(
            f"[{self.name}] {signal.action} {signal.symbol} @ {signal.price:.2f} "
            f"SL {signal.stop_loss:.2f} TGT {signal.target:.2f}"
        )
