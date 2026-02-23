from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading_bot.config.settings import Config


@dataclass
class SnapshotRepairRow:
    snapshot_id: int
    snapshot_date: str
    old_cash: float
    new_cash: float
    old_total: float
    new_total: float
    positions_value: float
    new_total_pnl: float
    new_total_pnl_percent: float


def _to_date(value: object) -> date | None:
    try:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.date()
    except Exception:
        return None


def _load_trades(engine) -> pd.DataFrame:
    trades = pd.read_sql(
        """
        SELECT entry_date, exit_date, entry_price, exit_price, quantity, status
        FROM trades
        """,
        engine,
    )
    if trades.empty:
        return trades
    trades["entry_price"] = pd.to_numeric(trades["entry_price"], errors="coerce").fillna(0.0)
    trades["exit_price"] = pd.to_numeric(trades["exit_price"], errors="coerce").fillna(0.0)
    trades["quantity"] = pd.to_numeric(trades["quantity"], errors="coerce").fillna(0.0)
    trades["status"] = trades["status"].astype(str).str.upper().str.strip()
    trades["entry_day"] = trades["entry_date"].apply(_to_date)
    trades["exit_day"] = trades["exit_date"].apply(_to_date)
    return trades


def _load_snapshots(engine) -> pd.DataFrame:
    return pd.read_sql(
        """
        SELECT id, date, cash, total_value, positions_value, total_pnl, total_pnl_percent
        FROM portfolio_snapshots
        ORDER BY date ASC
        """,
        engine,
    )


def _build_repairs(trades: pd.DataFrame, snapshots: pd.DataFrame) -> list[SnapshotRepairRow]:
    starting = float(Config.STARTING_CAPITAL)
    rows: list[SnapshotRepairRow] = []
    for _, snap in snapshots.iterrows():
        snap_day = _to_date(snap.get("date"))
        if snap_day is None:
            continue

        if trades.empty:
            entry_costs = 0.0
            exit_proceeds = 0.0
        else:
            entry_mask = trades["entry_day"].apply(lambda d: d is not None and d <= snap_day)
            entry_costs = float(
                (
                    trades.loc[entry_mask, "entry_price"]
                    * trades.loc[entry_mask, "quantity"]
                    * (1 + Config.COST_PER_SIDE)
                ).sum()
            )

            exit_mask = trades["status"].eq("CLOSED") & trades["exit_day"].apply(
                lambda d: d is not None and d <= snap_day
            )
            exit_proceeds = float(
                (
                    trades.loc[exit_mask, "exit_price"]
                    * trades.loc[exit_mask, "quantity"]
                    * (1 - Config.COST_PER_SIDE)
                ).sum()
            )

        old_cash = float(snap.get("cash", 0.0) or 0.0)
        old_total = float(snap.get("total_value", 0.0) or 0.0)
        positions_value_raw = snap.get("positions_value")
        if pd.notna(positions_value_raw):
            positions_value = float(positions_value_raw)
        else:
            positions_value = old_total - old_cash

        new_cash = starting - entry_costs + exit_proceeds
        new_total = new_cash + positions_value
        new_total_pnl = new_total - starting
        new_total_pnl_percent = (new_total_pnl / starting) * 100 if starting else 0.0

        rows.append(
            SnapshotRepairRow(
                snapshot_id=int(snap["id"]),
                snapshot_date=str(snap["date"]),
                old_cash=old_cash,
                new_cash=new_cash,
                old_total=old_total,
                new_total=new_total,
                positions_value=positions_value,
                new_total_pnl=new_total_pnl,
                new_total_pnl_percent=new_total_pnl_percent,
            )
        )
    return rows


def _apply_repairs(engine, repairs: list[SnapshotRepairRow]) -> int:
    if not repairs:
        return 0
    query = text(
        """
        UPDATE portfolio_snapshots
        SET
            cash = :cash,
            positions_value = :positions_value,
            total_value = :total_value,
            total_pnl = :total_pnl,
            total_pnl_percent = :total_pnl_percent
        WHERE id = :snapshot_id
        """
    )
    payload = [
        {
            "snapshot_id": item.snapshot_id,
            "cash": item.new_cash,
            "positions_value": item.positions_value,
            "total_value": item.new_total,
            "total_pnl": item.new_total_pnl,
            "total_pnl_percent": item.new_total_pnl_percent,
        }
        for item in repairs
    ]
    with engine.begin() as conn:
        conn.execute(query, payload)
    return len(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair inflated portfolio snapshots from restart cash bug.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes in-place. Without this flag the script runs in dry-run mode.",
    )
    parser.add_argument(
        "--show",
        type=int,
        default=10,
        help="Number of changed rows to print.",
    )
    args = parser.parse_args()

    engine = create_engine(Config.DATABASE_URL)
    snapshots = _load_snapshots(engine)
    trades = _load_trades(engine)
    repairs = _build_repairs(trades, snapshots)

    changed = [
        row
        for row in repairs
        if abs(row.new_cash - row.old_cash) > 0.01 or abs(row.new_total - row.old_total) > 0.01
    ]

    print(f"Snapshots scanned: {len(repairs)}")
    print(f"Rows requiring correction: {len(changed)}")
    for item in changed[: max(0, int(args.show))]:
        print(
            f"{item.snapshot_date}: cash {item.old_cash:.2f} -> {item.new_cash:.2f} | "
            f"total {item.old_total:.2f} -> {item.new_total:.2f}"
        )

    if not args.apply:
        print("Dry-run complete. Re-run with --apply to write updates.")
        return

    updated = _apply_repairs(engine, changed)
    print(f"Updated rows: {updated}")


if __name__ == "__main__":
    main()
