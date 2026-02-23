from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

import pandas as pd
from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from trading_bot.config.settings import Config

Base = declarative_base()


class Database:
    def __init__(self) -> None:
        engine_kwargs: dict[str, object] = {"echo": False}
        if "sqlite" in Config.DATABASE_URL:
            engine_kwargs["poolclass"] = StaticPool

        self.engine = create_engine(Config.DATABASE_URL, **engine_kwargs)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def init_db(self) -> None:
        """Initialize database schema from SQL file."""
        schema_path = Path(__file__).with_name("schemas.sql")
        schema = schema_path.read_text(encoding="utf-8")

        with self.engine.connect() as conn:
            for statement in schema.split(";"):
                if statement.strip():
                    conn.execute(text(statement))
            self._ensure_trades_columns(conn)
            conn.commit()

        logger.info("Database initialized successfully")

    @staticmethod
    def _ensure_trades_columns(conn) -> None:
        required_columns = {
            "highest_close": "REAL",
            "lowest_close": "REAL",
            "weekly_atr": "REAL",
        }
        existing_rows = conn.execute(text("PRAGMA table_info(trades)")).fetchall()
        existing = {str(row[1]).lower() for row in existing_rows}
        for column, sql_type in required_columns.items():
            if column.lower() in existing:
                continue
            conn.execute(text(f"ALTER TABLE trades ADD COLUMN {column} {sql_type}"))

    @contextmanager
    def get_session(self):
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def execute_query(self, query: str, params: dict | None = None) -> list:
        with self.get_session() as session:
            result = session.execute(text(query), params or {})
            return result.fetchall()

    def insert_price_data(self, df: pd.DataFrame, symbol: str) -> int:
        """Insert OHLCV rows with duplicate-safe behavior."""
        frame = df.copy()
        frame.columns = [c.lower().replace(" ", "_") for c in frame.columns]

        if "date" not in frame.columns:
            frame = frame.reset_index()
            frame.columns = [c.lower().replace(" ", "_") for c in frame.columns]

        rename_map = {
            "adj_close": "adj_close",
            "adjclose": "adj_close",
        }
        frame = frame.rename(columns=rename_map)

        expected_cols = ["date", "open", "high", "low", "close", "volume", "adj_close"]
        for col in expected_cols:
            if col not in frame.columns:
                frame[col] = None

        frame["symbol"] = symbol.replace(".NS", "")
        frame["date"] = pd.to_datetime(frame["date"]).dt.date.astype(str)

        rows = frame[["symbol", "date", "open", "high", "low", "close", "volume", "adj_close"]]
        records = rows.to_dict("records")

        if not records:
            return 0

        insert_sql = text(
            """
            INSERT OR IGNORE INTO price_data
            (symbol, date, open, high, low, close, volume, adj_close)
            VALUES
            (:symbol, :date, :open, :high, :low, :close, :volume, :adj_close)
            """
        )

        with self.engine.begin() as conn:
            conn.execute(insert_sql, records)

        logger.info(f"Inserted/updated {len(records)} rows for {symbol}")
        return len(records)

    def insert_alternative_signals(self, rows: Iterable[dict]) -> int:
        frame = pd.DataFrame(rows)
        if frame.empty:
            return 0

        if "metadata" in frame.columns:
            frame["metadata"] = frame["metadata"].astype(str)

        frame.to_sql("alternative_signals", self.engine, if_exists="append", index=False)
        return len(frame)


# Singleton

db = Database()
