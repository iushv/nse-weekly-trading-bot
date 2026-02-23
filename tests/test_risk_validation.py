from __future__ import annotations

from datetime import datetime

from trading_bot.config.settings import Config
from trading_bot.risk.position_sizer import size_position, size_position_adaptive
from trading_bot.risk.risk_manager import RiskManager
from trading_bot.strategies.base_strategy import Signal


def _signal(symbol: str, qty: int, price: float, stop: float) -> Signal:
    return Signal(
        symbol=symbol,
        action="BUY",
        price=price,
        quantity=qty,
        stop_loss=stop,
        target=price * 1.05,
        strategy="Test",
        confidence=0.8,
        timestamp=datetime.now(),
    )


def test_validate_sized_signals_respects_cumulative_heat():
    risk = RiskManager(initial_capital=100000)
    # signal risk%: (10 * 50)/100000 = 0.005 each
    s1 = _signal("AAA", qty=50, price=100, stop=90)
    s2 = _signal("BBB", qty=50, price=100, stop=90)
    s3 = _signal("CCC", qty=1110, price=100, stop=90)  # 0.111 risk, should breach with first two

    accepted = risk.validate_sized_signals([s1, s2, s3], current_positions={})
    # first two fit, third breaches 0.12 heat (0.005 + 0.005 + 0.111 = 0.121)
    assert accepted[0].symbol == "AAA"
    assert accepted[1].symbol == "BBB"
    assert len(accepted) == 2


def test_validate_sized_signals_skips_duplicate_symbols():
    risk = RiskManager(initial_capital=100000)
    current_positions = {"AAA": {"entry_price": 100.0, "stop_loss": 95.0, "quantity": 10}}
    s1 = _signal("AAA", qty=10, price=100, stop=95)
    s2 = _signal("BBB", qty=10, price=100, stop=95)
    accepted = risk.validate_sized_signals([s1, s2], current_positions=current_positions)
    assert len(accepted) == 1
    assert accepted[0].symbol == "BBB"


def test_check_can_trade_resets_limits_when_clock_jumps_to_different_day():
    now = [datetime(2026, 2, 12, 9, 0, 0)]

    def clock() -> datetime:
        return now[0]

    risk = RiskManager(initial_capital=100000, clock=clock)
    risk.daily_pnl = -3500.0
    risk.weekly_pnl = -6000.0

    # Replay/simulation can move "backward" relative to init time.
    now[0] = datetime(2025, 9, 1, 9, 0, 0)
    assert risk.check_can_trade() is True
    assert risk.daily_pnl == 0.0
    assert risk.weekly_pnl == 0.0


def test_size_position_adaptive_returns_zero_for_invalid_risk():
    shares = size_position_adaptive(
        price=100.0,
        stop_loss=100.0,
        capital=100000.0,
        cash_available=50000.0,
        confidence=0.7,
        win_rate=0.55,
        avg_win_loss_ratio=1.2,
        current_drawdown=0.02,
        sector_exposure=0.05,
    )
    assert shares == 0


def test_size_position_adaptive_throttles_on_drawdown_and_sector_exposure():
    normal = size_position_adaptive(
        price=100.0,
        stop_loss=0.0,
        capital=100000.0,
        cash_available=100000.0,
        confidence=0.8,
        win_rate=0.6,
        avg_win_loss_ratio=1.4,
        current_drawdown=0.0,
        sector_exposure=0.0,
    )
    throttled = size_position_adaptive(
        price=100.0,
        stop_loss=0.0,
        capital=100000.0,
        cash_available=100000.0,
        confidence=0.8,
        win_rate=0.6,
        avg_win_loss_ratio=1.4,
        current_drawdown=0.15,
        sector_exposure=0.25,
    )
    assert normal > 0
    assert throttled > 0
    assert throttled < normal


def test_size_position_respects_max_loss_per_trade(monkeypatch):
    monkeypatch.setattr(Config, "RISK_PER_TRADE", 0.02)
    monkeypatch.setattr(Config, "MAX_POSITION_SIZE", 1.0)
    monkeypatch.setattr(Config, "MAX_LOSS_PER_TRADE", 0.01)
    monkeypatch.setattr(Config, "COST_PER_SIDE", 0.0)

    shares = size_position(
        price=100.0,
        stop_loss=90.0,
        capital=100000.0,
        cash_available=100000.0,
    )
    assert shares == 100


def test_size_position_adaptive_respects_max_loss_per_trade(monkeypatch):
    monkeypatch.setattr(Config, "RISK_PER_TRADE", 0.02)
    monkeypatch.setattr(Config, "MAX_POSITION_SIZE", 1.0)
    monkeypatch.setattr(Config, "MAX_LOSS_PER_TRADE", 0.01)
    monkeypatch.setattr(Config, "COST_PER_SIDE", 0.0)

    shares = size_position_adaptive(
        price=100.0,
        stop_loss=90.0,
        capital=100000.0,
        cash_available=100000.0,
        confidence=1.0,
        win_rate=0.65,
        avg_win_loss_ratio=1.5,
        current_drawdown=0.0,
        sector_exposure=0.0,
    )
    assert shares == 100
