from __future__ import annotations

from datetime import datetime

import pandas as pd

from trading_bot.strategies.base_strategy import Signal


class AlwaysExitStrategy:
    name = "Momentum Breakout"

    def generate_signals(
        self,
        market_data: pd.DataFrame,
        alternative_data: pd.DataFrame | None = None,
        market_regime: dict | None = None,
    ):
        latest = market_data[market_data["symbol"] == "TEST"].sort_values("date").iloc[-1]
        price = float(latest["close"])
        return [
            Signal(
                symbol="TEST",
                action="BUY",
                price=price,
                quantity=0,
                stop_loss=price * 0.95,
                target=price * 1.01,
                strategy=self.name,
                confidence=0.9,
                timestamp=datetime.now(),
                metadata={},
            )
        ]

    def check_exit_conditions(self, position: dict, current_data: pd.Series):
        return True, "TEST_EXIT"


def test_end_to_end_paper_trading_cycle_persists_results(bot_with_test_db, seed_test_symbol_prices):
    bot, test_db = bot_with_test_db
    seed_test_symbol_prices(test_db, symbol="TEST")

    bot.strategies = {"momentum_breakout": AlwaysExitStrategy()}

    bot.pre_market_routine()
    assert len(bot.pending_signals) == 1

    bot.market_open_routine()
    assert "TEST" in bot.positions

    bot.intraday_monitoring()
    assert "TEST" not in bot.positions

    bot.market_close_routine()

    trades_df = pd.read_sql("SELECT * FROM trades", test_db.engine)
    assert len(trades_df) == 1
    assert trades_df.iloc[0]["status"] == "CLOSED"
    assert trades_df.iloc[0]["pnl"] is not None
    assert trades_df.iloc[0]["notes"] == "TEST_EXIT"

    snapshots_df = pd.read_sql("SELECT * FROM portfolio_snapshots", test_db.engine)
    assert len(snapshots_df) == 1
    assert snapshots_df.iloc[0]["num_positions"] == 0
