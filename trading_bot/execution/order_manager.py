from __future__ import annotations

from loguru import logger

from trading_bot.execution.broker_interface import BrokerInterface


class OrderManager:
    def __init__(self, broker: BrokerInterface) -> None:
        self.broker = broker

    def place_entry(self, symbol: str, quantity: int) -> dict | None:
        order = self.broker.place_market_order(symbol, quantity, "BUY")
        if order:
            logger.info(f"Entry order submitted: {symbol} x {quantity}")
        return order

    def place_exit(self, symbol: str, quantity: int) -> dict | None:
        order = self.broker.place_market_order(symbol, quantity, "SELL")
        if order:
            logger.info(f"Exit order submitted: {symbol} x {quantity}")
        return order

    def place_limit_entry(self, symbol: str, quantity: int, price: float) -> dict | None:
        order = self.broker.place_limit_order(symbol, quantity, "BUY", price)
        if order:
            logger.info(f"Limit entry submitted: {symbol} x {quantity} @ {price}")
        return order

    def place_stop_loss(self, symbol: str, quantity: int, stop_price: float) -> dict | None:
        order = self.broker.place_stop_loss_order(symbol, quantity, stop_price)
        if order:
            logger.info(f"Stop loss submitted: {symbol} x {quantity} @ {stop_price}")
        return order
