from __future__ import annotations


class PortfolioManager:
    def __init__(self, starting_cash: float) -> None:
        self.cash = starting_cash
        self.positions: dict[str, dict] = {}

    def open_position(self, symbol: str, quantity: int, price: float, metadata: dict | None = None) -> None:
        self.positions[symbol] = {
            "symbol": symbol,
            "quantity": quantity,
            "entry_price": price,
            **(metadata or {}),
        }
        self.cash -= quantity * price

    def close_position(self, symbol: str, price: float) -> float:
        pos = self.positions.pop(symbol)
        pnl = (price - pos["entry_price"]) * pos["quantity"]
        self.cash += pos["quantity"] * price
        return pnl
