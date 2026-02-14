# CLAUDE.md

## Project Overview

Indian equity swing-trading bot targeting NSE stocks. Modular strategy system with backtesting, paper trading, and live execution (Groww broker). Currently running Adaptive Trend Following strategy on the Nifty Midcap 150 universe in paper mode.

## Quick Reference

```bash
# Activate environment
source .venv/bin/activate

# Run tests
pytest -q

# Lint & type check (mirrors CI)
ruff check .
mypy --config-file pyproject.toml --ignore-missing-imports trading_bot main.py paper_trading.py

# Paper trading (one cycle)
PYTHONPATH=. python main.py --mode paper --test

# Paper trading (continuous)
PYTHONPATH=. python main.py --mode paper

# Backtest on midcap universe
PYTHONPATH=. python scripts/run_universe_backtest.py --start 2025-08-01 --end 2026-02-12 --universe-file data/universe/nifty_midcap150.txt

# Walk-forward analysis
PYTHONPATH=. python scripts/run_universe_walk_forward.py --start 2024-01-01 --end 2026-02-11 --universe-file data/universe/nifty_midcap150.txt --train-months 3 --test-months 3

# Data backfill
PYTHONPATH=. python scripts/backfill_data.py --start-date 2023-01-01 --limit 60

# Weekly audit
PYTHONPATH=. python scripts/weekly_performance_audit.py --pretty --export-json

# Preflight check
PYTHONPATH=. python scripts/preflight_check.py --pretty
```

## Tech Stack

- **Python 3.11** (pyproject.toml target; local venv may be 3.9)
- **SQLite** via SQLAlchemy (default `trading_bot.db`; configurable via `DATABASE_URL`)
- **pandas** for all market data manipulation
- **loguru** for logging (not stdlib logging)
- **yfinance** + Groww API for market data
- **APScheduler** for scheduling routines
- **pytest** for testing (29 test files in `tests/`)

## Project Structure

```
main.py                          # Orchestrator (TradingBot class, entry point)
paper_trading.py                 # Deterministic historical replay simulator
trading_bot/
  config/settings.py             # Config class: all env vars with defaults
  strategies/
    base_strategy.py             # ABC: generate_signals(), check_exit_conditions()
    adaptive_trend.py            # Active strategy (weekly trend + daily entry)
    momentum_breakout.py         # Legacy strategies (disabled)
    mean_reversion.py
    sector_rotation.py
    bear_reversal.py
    volatility_reversal.py
  data/
    collectors/market_data.py    # MarketDataCollector (yfinance, Groww, NSE scraping)
    storage/database.py          # DB singleton, insert/query helpers
    storage/feature_store.py     # Trade feature persistence for ML
  execution/broker_interface.py  # Mock/Groww/HTTP broker abstraction
  risk/
    risk_manager.py              # Position limits, loss caps, portfolio heat
    position_sizer.py            # ATR-based sizing, adaptive half-Kelly
  backtesting/
    engine.py                    # BacktestEngine with trailing-stop support
    walk_forward.py              # Rolling OOS window analysis
  monitoring/
    performance_audit.py         # Sharpe, drawdown, win rate, profit factor
    paper_run_tracker.py         # 4-week promotion streak tracking
    gate_profiles.py             # Go-live gate thresholds per strategy
    run_context.py               # Universe-aware paper-run tagging
scripts/                         # CLI tools for backfill, tuning, auditing, ops
tests/                           # pytest test suite
data/universe/                   # Universe definition files (.txt, one symbol per line)
reports/                         # Generated backtests, audits, promotions (gitignored)
```

## Architecture

**Strategy pattern**: All strategies extend `BaseStrategy` (ABC) with `generate_signals()` returning `list[Signal]` and `check_exit_conditions()` returning `tuple[bool, str]`. The orchestrator in `main.py` calls these during market routines.

**Config system**: `trading_bot/config/settings.py` has a `Config` class with 100+ class-level attributes reading from env vars. All parameters have defaults. Strategy profiles (`STRATEGY_PROFILE` env var) override groups of parameters.

**Broker abstraction**: `execution/broker_interface.py` provides `MockGrowwClient` (paper), `HttpBrokerClient` (generic), and Groww integration. Selected via `BROKER_PROVIDER` env var.

**Safety model**: Live trading is fail-closed. Requires `LIVE_ORDER_EXECUTION_ENABLED=1` AND `LIVE_ORDER_FORCE_ACK` matching a safety phrase. Paper mode is the default.

## Active Strategy: Adaptive Trend Following

The only enabled strategy (`ENABLE_ADAPTIVE_TREND=1`). Key design:
- Weekly indicators (EMA-10/30, ATR-10, RSI-10, ROC-4) computed from daily OHLCV
- Hard regime gate blocks entries when market breadth < 50% or trend is down
- Entry: weekly uptrend + daily pullback timing + R-multiple filter + trend consistency check
- Exit cascade (strict priority): STOP_LOSS > BREAKEVEN_STOP > TREND_BREAK > TRAILING_STOP > TIME_STOP
- Progressive trailing: gain <3% = 1.5x ATR, >=3% = 1.2x, >=5% = 1.0x, >=8% = 0.8x ATR
- Position limits: max 3 new entries/week, max 5 total, holds 2-6 weeks
- Universe: Nifty Midcap 150 (140 symbols in `data/universe/nifty_midcap150.txt`)

## Coding Conventions

- **Style**: `snake_case` functions/variables, `PascalCase` classes, 120-char line length
- **Type hints**: Used on public functions; mypy config is lenient (`check_untyped_defs = false`)
- **Imports**: `from __future__ import annotations` in most files
- **Logging**: Use `loguru.logger`, not `logging`
- **Config access**: `Config.ATTRIBUTE_NAME` (class-level, reads env at import time)
- **Database**: Use `db.engine` for SQLAlchemy operations, `db.execute()` for raw queries
- **Env helpers**: `_env_bool()`, `_env_int()`, `_env_float()` in settings.py

## CI Pipeline

GitHub Actions (`.github/workflows/ci.yml`) runs on all pushes:
1. `ruff check .` — lint (rules: E9, F63, F7, F82)
2. `mypy` — type check on `trading_bot/`, `main.py`, `paper_trading.py`
3. `pytest -q` — full test suite

## Commit Style

Imperative present tense, scoped to one concern:
```
Fix backtest MTM for sparse daily data
Add Nifty Midcap 150 universe support
Track paper-run readiness per universe
Batch yfinance daily updates for large universes
```

## Key Environment Variables

Set in `.env` (see `.env.example` for full list):

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENVIRONMENT` | `paper` | `paper` or `live` |
| `UNIVERSE_FILE` | (empty) | Path to universe file, e.g. `data/universe/nifty_midcap150.txt` |
| `ENABLE_ADAPTIVE_TREND` | `1` | Enable adaptive trend strategy |
| `BROKER_PROVIDER` | `mock` | `mock`, `groww`, or `http` |
| `DATABASE_URL` | `sqlite:///trading_bot.db` | SQLAlchemy connection string |
| `STARTING_CAPITAL` | `100000` | Initial capital in INR |
| `MARKET_DATA_PROVIDER` | `auto` | `auto`, `yfinance`, or `groww` |
| `LIVE_ORDER_EXECUTION_ENABLED` | `0` | Must be `1` to arm live orders |

## Testing Notes

- Tests use temporary SQLite databases for isolation
- External services (broker, Telegram, market data) are mocked via monkeypatch in `conftest.py`
- Run a single test: `pytest tests/test_adaptive_trend_strategy.py::test_name -v`
- Some tests require `PYTHONPATH=.` if running outside the venv

## Current State

- **Active universe**: Nifty Midcap 150 (pivoted from Nifty 50 due to near-zero edge)
- **Backtest performance** (Midcap 150, Aug 2025-Feb 2026): +7.54% return, Sharpe 1.42, PF 1.94
- **Walk-forward** (3x3, Jan 2024-Feb 2026): 4/7 profitable windows, avg +0.90%
- **Paper-run status**: Restarted with midcap universe, streak counter at 0/4
- **ML layer** (Phase 9E-9F): Not yet implemented; collecting features only
- **Live trading**: Disabled; requires 4/4 weekly promotion gates + manual review

## Important Warnings

- **Never enable `LIVE_ORDER_EXECUTION_ENABLED=1`** without completing 4/4 paper-run promotion gates
- **Credential hygiene**: `.env` contains broker API keys and Telegram tokens. Never commit it.
- **Rate limits**: Backfilling 140 midcap symbols hits yfinance rate limits; the system falls back to Groww API automatically
- The Q1 2025 period (Jan-Apr) is a known weak regime for midcap trend-following; the regime gate does not fully block entries during broad selloffs
