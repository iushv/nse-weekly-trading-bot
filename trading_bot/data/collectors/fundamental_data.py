from __future__ import annotations

import yfinance as yf
from loguru import logger


class FundamentalDataCollector:
    """Lightweight fundamentals collector using yfinance."""

    def fetch_fundamentals(self, symbol: str) -> dict:
        try:
            info = yf.Ticker(symbol).info
            return {
                "symbol": symbol,
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "pb_ratio": info.get("priceToBook"),
                "roe": info.get("returnOnEquity"),
                "debt_to_equity": info.get("debtToEquity"),
            }
        except Exception as exc:
            logger.error(f"Fundamental fetch failed for {symbol}: {exc}")
            return {"symbol": symbol}


fundamental_collector = FundamentalDataCollector()
