from trading_bot.config.settings import Config
from trading_bot.risk.position_sizer import size_position


def test_config_default_environment():
    assert Config.ENVIRONMENT in {"paper", "live"}


def test_position_sizer_returns_non_negative():
    qty = size_position(price=100.0, stop_loss=95.0, capital=100000.0, cash_available=50000.0)
    assert qty >= 0
