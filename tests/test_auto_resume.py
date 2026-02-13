from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import pytest

from trading_bot.config.settings import Config
from trading_bot.strategies.base_strategy import Signal


class RecoverySignalStrategy:
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
                target=price * 1.05,
                strategy=self.name,
                confidence=0.9,
                timestamp=datetime.now(),
                metadata={"source": "test"},
            )
        ]

    def check_exit_conditions(self, position: dict, current_data: pd.Series):
        return False, None


def test_pending_signals_persist_and_restore_on_market_open(bot_with_test_db, seed_test_symbol_prices):
    bot, test_db = bot_with_test_db
    seed_test_symbol_prices(test_db, symbol="TEST")
    bot.strategies = {"momentum_breakout": RecoverySignalStrategy()}

    bot.pre_market_routine()
    assert len(bot.pending_signals) == 1

    state = json.loads(bot.runtime_state_path.read_text(encoding="utf-8"))
    pending = state.get("pending_signals", {})
    assert pending.get("date") == bot._today_str()
    assert pending.get("consumed") is False
    assert len(pending.get("signals", [])) == 1

    # Simulate restart: in-memory queue lost, but runtime state file remains.
    bot.pending_signals = []
    bot.market_open_routine()

    assert "TEST" in bot.positions
    state_after = json.loads(bot.runtime_state_path.read_text(encoding="utf-8"))
    assert state_after["pending_signals"].get("consumed") is True


def test_recovery_cycle_runs_missed_pre_market_and_open(bot_with_test_db, monkeypatch: pytest.MonkeyPatch):
    bot, _ = bot_with_test_db
    calls: list[str] = []

    def fake_pre_market() -> None:
        calls.append("pre_market")
        bot._mark_routine_completed("pre_market")

    def fake_market_open() -> None:
        calls.append("market_open")
        bot._mark_routine_completed("market_open")

    monkeypatch.setattr(bot, "pre_market_routine", fake_pre_market)
    monkeypatch.setattr(bot, "market_open_routine", fake_market_open)
    monkeypatch.setattr(Config, "AUTO_RESUME_ENABLED", True, raising=False)

    bot.set_simulation_date(datetime(2024, 1, 3, 10, 0))
    recovered = bot._run_recovery_cycle(force=True)

    assert recovered == ["pre_market", "market_open"]
    assert calls == ["pre_market", "market_open"]


def test_recovery_cycle_runs_missed_market_close(bot_with_test_db, monkeypatch: pytest.MonkeyPatch):
    bot, _ = bot_with_test_db
    calls: list[str] = []

    def fake_market_close() -> None:
        calls.append("market_close")
        bot._mark_routine_completed("market_close")

    monkeypatch.setattr(bot, "market_close_routine", fake_market_close)
    monkeypatch.setattr(Config, "AUTO_RESUME_ENABLED", True, raising=False)

    bot.set_simulation_date(datetime(2024, 1, 3, 16, 0))
    recovered = bot._run_recovery_cycle(force=True)

    assert recovered == ["market_close"]
    assert calls == ["market_close"]
