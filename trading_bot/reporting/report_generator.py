from __future__ import annotations

import os
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd
from loguru import logger

from trading_bot.data.storage.database import db


class ReportGenerator:
    def __init__(self, output_dir: str = "reports") -> None:
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_portfolio_chart(self, portfolio_history: list[dict], save_path: str | None = None) -> str:
        df = pd.DataFrame(portfolio_history)
        if df.empty:
            raise ValueError("No portfolio history to plot")

        df["date"] = pd.to_datetime(df["date"])
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(df["date"], df["total_value"], linewidth=2)
        ax.set_title("Portfolio Value")
        ax.set_ylabel("INR")
        ax.grid(alpha=0.3)
        plt.tight_layout()

        if save_path is None:
            save_path = os.path.join(self.output_dir, f"portfolio_{datetime.now().strftime('%Y%m%d')}.png")
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

        logger.info(f"Saved chart to {save_path}")
        return save_path

    def generate_trade_distribution(self, trades: list[dict], save_path: str | None = None) -> str:
        df = pd.DataFrame(trades)
        if df.empty:
            raise ValueError("No trades provided")

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        pnl_col = "pnl_percent" if "pnl_percent" in df.columns else "net_pnl"
        axes[0].hist(df[pnl_col].dropna(), bins=25, alpha=0.75, edgecolor="black")
        axes[0].axvline(x=0, color="red", linestyle="--", linewidth=1.5)
        axes[0].set_title("Trade P&L Distribution")
        axes[0].set_xlabel(pnl_col)
        axes[0].set_ylabel("Frequency")
        axes[0].grid(alpha=0.3)

        if "strategy" in df.columns:
            strategy_pnl = df.groupby("strategy")[["pnl", "net_pnl"]].sum(numeric_only=True)
            chosen_col = "pnl" if "pnl" in strategy_pnl.columns and strategy_pnl["pnl"].abs().sum() > 0 else "net_pnl"
            vals = strategy_pnl[chosen_col].sort_values()
            colors = ["green" if x > 0 else "red" for x in vals.values]
            vals.plot(kind="barh", ax=axes[1], color=colors, alpha=0.75)
            axes[1].set_title("P&L by Strategy")
            axes[1].set_xlabel("P&L")
            axes[1].grid(alpha=0.3, axis="x")
        else:
            axes[1].axis("off")
            axes[1].set_title("No strategy breakdown")

        plt.tight_layout()

        if save_path is None:
            save_path = os.path.join(self.output_dir, f"trades_{datetime.now().strftime('%Y%m%d')}.png")
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info(f"Saved trade distribution chart to {save_path}")
        return save_path

    def generate_monthly_report(self, year: int, month: int) -> dict:
        start_date = f"{year}-{month:02d}-01"
        end_date = f"{year + 1}-01-01" if month == 12 else f"{year}-{month + 1:02d}-01"

        trades = pd.read_sql(
            """
            SELECT * FROM trades
            WHERE entry_date >= :start_date
              AND entry_date < :end_date
              AND status = 'CLOSED'
            """,
            db.engine,
            params={"start_date": start_date, "end_date": end_date},
        )
        portfolio = pd.read_sql(
            """
            SELECT * FROM portfolio_snapshots
            WHERE date >= :start_date
              AND date < :end_date
            ORDER BY date
            """,
            db.engine,
            params={"start_date": start_date, "end_date": end_date},
        )

        if trades.empty or portfolio.empty:
            return {"error": "No data for this month"}

        pnl_col = "pnl" if "pnl" in trades.columns else "net_pnl"
        wins = trades[trades[pnl_col] > 0]
        losses = trades[trades[pnl_col] < 0]
        win_rate = len(wins) / len(trades) if len(trades) > 0 else 0.0

        start_value = float(portfolio.iloc[0]["total_value"])
        end_value = float(portfolio.iloc[-1]["total_value"])
        monthly_return = ((end_value - start_value) / start_value) * 100 if start_value else 0.0

        portfolio["peak"] = portfolio["total_value"].cummax()
        portfolio["drawdown"] = ((portfolio["total_value"] - portfolio["peak"]) / portfolio["peak"]) * 100

        return {
            "month": f"{year}-{month:02d}",
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate * 100,
            "total_pnl": float(trades[pnl_col].sum()),
            "avg_win": float(wins[pnl_col].mean()) if len(wins) > 0 else 0.0,
            "avg_loss": float(losses[pnl_col].mean()) if len(losses) > 0 else 0.0,
            "best_trade": float(trades[pnl_col].max()) if len(trades) > 0 else 0.0,
            "worst_trade": float(trades[pnl_col].min()) if len(trades) > 0 else 0.0,
            "monthly_return": monthly_return,
            "max_drawdown": float(portfolio["drawdown"].min()) if not portfolio.empty else 0.0,
            "start_value": start_value,
            "end_value": end_value,
        }

    def export_trades_csv(self, start_date: str, end_date: str, filename: str | None = None) -> str:
        trades = pd.read_sql(
            """
            SELECT * FROM trades
            WHERE entry_date >= :start_date
              AND entry_date <= :end_date
            ORDER BY entry_date DESC
            """,
            db.engine,
            params={"start_date": start_date, "end_date": end_date},
        )
        if filename is None:
            filename = os.path.join(self.output_dir, f"trades_{start_date}_to_{end_date}.csv")
        trades.to_csv(filename, index=False)
        logger.info(f"Exported trades to {filename}")
        return filename


report_generator = ReportGenerator()
