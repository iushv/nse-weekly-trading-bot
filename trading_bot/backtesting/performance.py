from __future__ import annotations

import numpy as np
import pandas as pd


def summarize_performance(trades: list[dict], portfolio_history: list[dict]) -> dict:
    trades_df = pd.DataFrame(trades)
    portfolio_df = pd.DataFrame(portfolio_history)

    if trades_df.empty:
        return {"total_trades": 0, "win_rate": 0.0}

    wins = trades_df[trades_df["net_pnl"] > 0]
    losses = trades_df[trades_df["net_pnl"] < 0]

    if not portfolio_df.empty:
        portfolio_df["ret"] = portfolio_df["total_value"].pct_change().fillna(0)
        std = portfolio_df["ret"].std()
        sharpe = (portfolio_df["ret"].mean() / std) * np.sqrt(252) if std != 0 else 0.0
    else:
        sharpe = 0.0

    return {
        "total_trades": int(len(trades_df)),
        "win_rate": float(len(wins) / len(trades_df)),
        "avg_win": float(wins["net_pnl"].mean()) if not wins.empty else 0.0,
        "avg_loss": float(losses["net_pnl"].mean()) if not losses.empty else 0.0,
        "total_pnl": float(trades_df["net_pnl"].sum()),
        "sharpe_ratio": float(sharpe),
    }
