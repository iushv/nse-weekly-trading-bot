from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from loguru import logger
from sqlalchemy import Engine, text


class FeatureStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save_entry_features(
        self,
        *,
        order_id: str,
        symbol: str,
        strategy: str,
        entry_date: datetime,
        entry_price: float,
        stop_loss: float,
        target: float,
        quantity: int,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        md = metadata or {}
        payload = {
            "order_id": order_id,
            "symbol": symbol.replace(".NS", ""),
            "strategy": strategy,
            "entry_date": entry_date.isoformat(),
            "entry_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "target": float(target),
            "quantity": int(quantity),
            "confidence": float(confidence),
            "ml_score": self._float(md.get("ml_score")),
            "market_regime_label": self._str(md.get("market_regime_label", md.get("regime_label"))),
            "market_regime_confidence": self._float(md.get("market_regime_confidence", md.get("regime_confidence"))),
            "market_breadth_ratio": self._float(md.get("market_breadth_ratio")),
            "market_trend_up": self._int_bool(md.get("market_regime_trend_up")),
            "market_annualized_volatility": self._float(md.get("market_regime_annualized_volatility")),
            "weekly_ema_short": self._float(md.get("weekly_ema_short")),
            "weekly_ema_long": self._float(md.get("weekly_ema_long")),
            "weekly_atr": self._float(md.get("weekly_atr")),
            "weekly_rsi": self._float(md.get("weekly_rsi")),
            "weekly_roc": self._float(md.get("weekly_roc")),
            "daily_sma20": self._float(md.get("daily_sma20")),
            "daily_rsi": self._float(md.get("daily_rsi")),
            "volume_ratio": self._float(md.get("volume_ratio")),
            "sector": self._str(md.get("sector")),
            "liquidity_score": self._float(md.get("liquidity_score")),
            "metadata_json": str(md),
        }

        query = text(
            """
            INSERT OR REPLACE INTO trade_features (
                order_id, symbol, strategy, entry_date, entry_price, stop_loss, target, quantity,
                confidence, ml_score, market_regime_label, market_regime_confidence, market_breadth_ratio,
                market_trend_up, market_annualized_volatility, weekly_ema_short, weekly_ema_long, weekly_atr,
                weekly_rsi, weekly_roc, daily_sma20, daily_rsi, volume_ratio, sector, liquidity_score,
                metadata_json, updated_at
            ) VALUES (
                :order_id, :symbol, :strategy, :entry_date, :entry_price, :stop_loss, :target, :quantity,
                :confidence, :ml_score, :market_regime_label, :market_regime_confidence, :market_breadth_ratio,
                :market_trend_up, :market_annualized_volatility, :weekly_ema_short, :weekly_ema_long, :weekly_atr,
                :weekly_rsi, :weekly_roc, :daily_sma20, :daily_rsi, :volume_ratio, :sector, :liquidity_score,
                :metadata_json, CURRENT_TIMESTAMP
            )
            """
        )
        with self.engine.begin() as conn:
            conn.execute(query, payload)

    def update_trade_outcome(
        self,
        *,
        order_id: str,
        exit_date: datetime,
        exit_price: float,
        pnl: float,
        pnl_percent: float,
        days_held: int,
        exit_reason: str,
        mfe: float | None = None,
        mae: float | None = None,
    ) -> None:
        outcome_label = 1 if pnl > 0 else 0
        query = text(
            """
            UPDATE trade_features
            SET exit_date = :exit_date,
                exit_price = :exit_price,
                pnl = :pnl,
                pnl_percent = :pnl_percent,
                days_held = :days_held,
                exit_reason = :exit_reason,
                mfe = :mfe,
                mae = :mae,
                outcome_label = :outcome_label,
                updated_at = CURRENT_TIMESTAMP
            WHERE order_id = :order_id
            """
        )
        with self.engine.begin() as conn:
            result = conn.execute(
                query,
                {
                    "order_id": order_id,
                    "exit_date": exit_date.isoformat(),
                    "exit_price": float(exit_price),
                    "pnl": float(pnl),
                    "pnl_percent": float(pnl_percent),
                    "days_held": int(days_held),
                    "exit_reason": exit_reason,
                    "mfe": mfe,
                    "mae": mae,
                    "outcome_label": outcome_label,
                },
            )
        if result.rowcount == 0:
            logger.warning("No trade_features row found for order_id={}", order_id)

    def get_training_data(self, min_rows: int = 0) -> pd.DataFrame:
        query = """
            SELECT * FROM trade_features
            WHERE outcome_label IS NOT NULL
            ORDER BY entry_date
        """
        df = pd.read_sql(query, self.engine)
        if len(df) < int(min_rows):
            return pd.DataFrame()
        return df

    @staticmethod
    def _float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _str(value: Any) -> str | None:
        if value is None:
            return None
        text_value = str(value).strip()
        return text_value if text_value else None

    @staticmethod
    def _int_bool(value: Any) -> int | None:
        if value is None:
            return None
        return int(bool(value))
