from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from loguru import logger

from trading_bot.config.constants import SECTORS
from trading_bot.strategies.base_strategy import BaseStrategy, Signal


class SectorRotationStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__("Sector Rotation")
        self.rebalance_day = 0
        self.top_sectors_count = 2
        self.stocks_per_sector = 3

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict | None = None,
    ) -> list[Signal]:
        if datetime.now().weekday() != self.rebalance_day:
            return []

        sector_scores = self._calculate_sector_momentum(market_data)
        if sector_scores.empty:
            logger.info("No eligible sectors this week")
            return []

        out: list[Signal] = []
        top_sectors = sector_scores.nlargest(self.top_sectors_count, "momentum_score")
        for _, row in top_sectors.iterrows():
            sector = row["sector"]
            sector_stocks = self._get_sector_stocks(sector, market_data)
            ranked = self._rank_stocks_in_sector(sector_stocks, market_data, alternative_data)
            for symbol in ranked.head(self.stocks_per_sector)["symbol"].tolist():
                signal = self._create_signal(symbol, market_data, sector)
                if signal:
                    self.log_signal(signal)
                    out.append(signal)
        return out

    def _calculate_sector_momentum(self, market_data: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for sector in SECTORS:
            sector_stocks = self._get_sector_stocks(sector, market_data)
            week, month = [], []
            for symbol in sector_stocks["symbol"].dropna().unique():
                df = market_data[market_data["symbol"] == symbol].sort_values("date")
                if len(df) < 25:
                    continue
                week.append((df.iloc[-1]["close"] - df.iloc[-5]["close"]) / df.iloc[-5]["close"])
                month.append((df.iloc[-1]["close"] - df.iloc[-20]["close"]) / df.iloc[-20]["close"])
            if not week:
                continue

            momentum_score = np.mean(week) * 0.6 + np.mean(month) * 0.4
            momentum_shift = np.mean(week) - (np.mean(month) / 4)
            if momentum_score > 0 and momentum_shift > 0:
                rows.append(
                    {
                        "sector": sector,
                        "momentum_score": float(momentum_score),
                        "momentum_shift": float(momentum_shift),
                    }
                )

        if not rows:
            return pd.DataFrame(columns=["sector", "momentum_score", "momentum_shift"])
        return pd.DataFrame(rows).sort_values("momentum_score", ascending=False)

    def _load_sector_mapping(self) -> dict[str, list[str]]:
        return {
            "BANKING": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"],
            "IT": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"],
            "AUTO": ["MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "EICHERMOT"],
            "PHARMA": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "AUROPHARMA"],
            "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR"],
            "METAL": ["TATASTEEL", "HINDALCO", "JSWSTEEL", "VEDL", "COALINDIA"],
            "ENERGY": ["RELIANCE", "ONGC", "BPCL", "IOC", "NTPC"],
        }

    def _get_sector_stocks(self, sector: str, market_data: pd.DataFrame) -> pd.DataFrame:
        sector_symbols = self._load_sector_mapping().get(sector, [])
        return market_data[market_data["symbol"].isin(sector_symbols)]

    def _rank_stocks_in_sector(
        self,
        sector_stocks: pd.DataFrame,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None,
    ) -> pd.DataFrame:
        ranks: list[dict] = []
        for symbol in sector_stocks["symbol"].dropna().unique():
            df = market_data[market_data["symbol"] == symbol].sort_values("date")
            if len(df) < 25:
                continue
            rs = self._calculate_relative_strength(df)
            news = self._check_news_sentiment(symbol, alternative_data)
            score = rs * 0.8 + news * 0.2
            ranks.append({"symbol": symbol, "score": score})

        if not ranks:
            return pd.DataFrame(columns=["symbol", "score"])
        return pd.DataFrame(ranks).sort_values("score", ascending=False)

    def _calculate_relative_strength(self, df: pd.DataFrame) -> float:
        roc20 = (df.iloc[-1]["close"] - df.iloc[-20]["close"]) / df.iloc[-20]["close"]
        return float(min(max(roc20 * 5, 0), 1))

    def _check_news_sentiment(self, symbol: str, alternative_data: pd.DataFrame | None) -> float:
        if alternative_data is None or alternative_data.empty:
            return 0.5
        try:
            recent = alternative_data[
                (alternative_data["symbol"] == symbol)
                & (alternative_data["signal_type"] == "news_mentions")
                & (pd.to_datetime(alternative_data["date"]).dt.date >= datetime.now().date() - timedelta(days=7))
            ]
            if recent.empty:
                return 0.3
            return float(min(recent["value"].sum() / 10, 1.0))
        except Exception:
            return 0.5

    def _create_signal(self, symbol: str, market_data: pd.DataFrame, sector: str) -> Signal | None:
        df = market_data[market_data["symbol"] == symbol].sort_values("date")
        if df.empty or len(df) < 20:
            return None

        latest = df.iloc[-1]
        price = float(latest["close"])
        atr = self._calculate_atr(df).iloc[-1]
        if pd.isna(atr) or atr <= 0:
            return None

        stop_loss = min(price * 0.94, price - (2 * atr))
        target = price + ((price - stop_loss) * 1.3)
        return Signal(
            symbol=symbol,
            action="BUY",
            price=price,
            quantity=0,
            stop_loss=float(stop_loss),
            target=float(target),
            strategy=self.name,
            confidence=0.70,
            timestamp=datetime.now(),
            metadata={"sector": sector, "hold_until": "Friday"},
        )

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def check_exit_conditions(self, position: dict, current_data: pd.Series) -> tuple[bool, str | None]:
        price = float(current_data["close"])
        if price <= float(position["stop_loss"]):
            return True, "STOP_LOSS"
        if price >= float(position["target"]):
            return True, "TARGET_HIT"
        if datetime.now().weekday() == 4:
            return True, "WEEKLY_REBALANCE"
        return False, None


sector_rotation_strategy = SectorRotationStrategy()
