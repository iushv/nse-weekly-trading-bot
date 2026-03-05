from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from trading_bot.config.settings import Config

Base = declarative_base()


class Database:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = str(database_url or Config.DATABASE_URL)
        engine_kwargs: dict[str, object] = {"echo": False}
        if "sqlite" in self.database_url:
            engine_kwargs["poolclass"] = StaticPool

        self.engine = create_engine(self.database_url, **engine_kwargs)
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
            self._ensure_corporate_actions_table(conn)
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

    @staticmethod
    def _ensure_corporate_actions_table(conn) -> None:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS corporate_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    action_date TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    prev_close_db REAL,
                    prev_close_exchange REAL,
                    adjustment_factor REAL NOT NULL,
                    face_val_before REAL,
                    face_val_after REAL,
                    applied INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, action_date)
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ca_symbol_date ON corporate_actions(symbol, action_date)"))

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

    @staticmethod
    def _prepare_price_records(df: pd.DataFrame, symbol: str) -> list[dict[str, Any]]:
        frame = df.copy()
        frame.columns = [c.lower().replace(" ", "_") for c in frame.columns]

        if "date" not in frame.columns:
            frame = frame.reset_index()
            frame.columns = [c.lower().replace(" ", "_") for c in frame.columns]

        frame = frame.rename(columns={"adjclose": "adj_close"})
        expected_cols = ["date", "open", "high", "low", "close", "volume", "adj_close"]
        for col in expected_cols:
            if col not in frame.columns:
                frame[col] = None

        frame["symbol"] = symbol.replace(".NS", "").upper().strip()
        frame["date"] = pd.to_datetime(frame["date"]).dt.date.astype(str)
        rows = frame[["symbol", "date", "open", "high", "low", "close", "volume", "adj_close"]]
        return rows.to_dict("records")

    def insert_price_data(self, df: pd.DataFrame, symbol: str) -> int:
        """Insert OHLCV rows with duplicate-safe behavior."""
        records = self._prepare_price_records(df=df, symbol=symbol)
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

    def upsert_price_data(self, df: pd.DataFrame, symbol: str) -> int:
        """Insert or update OHLCV rows (used for corporate-action adjustments)."""
        records = self._prepare_price_records(df=df, symbol=symbol)
        if not records:
            return 0

        upsert_sql = text(
            """
            INSERT INTO price_data (symbol, date, open, high, low, close, volume, adj_close)
            VALUES (:symbol, :date, :open, :high, :low, :close, :volume, :adj_close)
            ON CONFLICT(symbol, date) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                adj_close = excluded.adj_close
            """
        )

        with self.engine.begin() as conn:
            conn.execute(upsert_sql, records)

        logger.info(f"Upserted {len(records)} rows for {symbol}")
        return len(records)

    def upsert_corporate_actions(self, actions: Iterable[dict[str, Any]]) -> int:
        action_list = []
        for item in actions:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            normalized.setdefault("prev_close_db", None)
            normalized.setdefault("prev_close_exchange", None)
            normalized.setdefault("face_val_before", None)
            normalized.setdefault("face_val_after", None)
            normalized.setdefault("applied", 0)
            action_list.append(normalized)
        if not action_list:
            return 0

        sql = text(
            """
            INSERT INTO corporate_actions (
                symbol,
                action_date,
                action_type,
                prev_close_db,
                prev_close_exchange,
                adjustment_factor,
                face_val_before,
                face_val_after,
                applied
            )
            VALUES (
                :symbol,
                :action_date,
                :action_type,
                :prev_close_db,
                :prev_close_exchange,
                :adjustment_factor,
                :face_val_before,
                :face_val_after,
                :applied
            )
            ON CONFLICT(symbol, action_date) DO UPDATE SET
                action_type = excluded.action_type,
                prev_close_db = excluded.prev_close_db,
                prev_close_exchange = excluded.prev_close_exchange,
                adjustment_factor = excluded.adjustment_factor,
                face_val_before = excluded.face_val_before,
                face_val_after = excluded.face_val_after,
                applied = CASE
                    WHEN corporate_actions.applied = 1 THEN 1
                    ELSE excluded.applied
                END
            """
        )
        with self.engine.begin() as conn:
            conn.execute(sql, action_list)
        return len(action_list)

    def list_corporate_actions(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        symbols: list[str] | None = None,
        applied: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = ["1=1"]
        params: dict[str, Any] = {}

        if start_date:
            clauses.append("action_date >= :start_date")
            params["start_date"] = str(start_date)
        if end_date:
            clauses.append("action_date <= :end_date")
            params["end_date"] = str(end_date)
        if applied is not None:
            clauses.append("applied = :applied")
            params["applied"] = int(applied)
        if symbols:
            symbol_params: list[str] = []
            for idx, symbol in enumerate(symbols):
                key = f"sym_{idx}"
                symbol_params.append(f":{key}")
                params[key] = str(symbol).replace(".NS", "").upper().strip()
            clauses.append(f"symbol IN ({', '.join(symbol_params)})")

        query = text(
            f"""
            SELECT symbol, action_date, action_type, prev_close_db, prev_close_exchange,
                   adjustment_factor, face_val_before, face_val_after, applied, created_at
            FROM corporate_actions
            WHERE {' AND '.join(clauses)}
            ORDER BY action_date, symbol
            """
        )

        with self.engine.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row._mapping) for row in rows]

    def apply_backward_adjustment(self, *, symbol: str, action_date: str, adjustment_factor: float) -> int:
        factor = float(adjustment_factor)
        if factor <= 0:
            return 0
        sql = text(
            """
            UPDATE price_data
            SET open = open / :factor,
                high = high / :factor,
                low = low / :factor,
                close = close / :factor,
                adj_close = adj_close / :factor,
                volume = ROUND(volume * :factor)
            WHERE symbol = :symbol
              AND date < :action_date
            """
        )
        params = {
            "factor": factor,
            "symbol": str(symbol).replace(".NS", "").upper().strip(),
            "action_date": str(action_date),
        }
        with self.engine.begin() as conn:
            result = conn.execute(sql, params)
        return int(result.rowcount or 0)

    def mark_corporate_action_applied(self, *, symbol: str, action_date: str) -> int:
        sql = text(
            """
            UPDATE corporate_actions
            SET applied = 1
            WHERE symbol = :symbol AND action_date = :action_date
            """
        )
        params = {"symbol": str(symbol).replace(".NS", "").upper().strip(), "action_date": str(action_date)}
        with self.engine.begin() as conn:
            result = conn.execute(sql, params)
        return int(result.rowcount or 0)

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
