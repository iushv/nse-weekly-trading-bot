# Indian Stock Trading Bot - Swing Trading System

Automated swing-trading framework for Indian equities with modular strategies, risk controls, paper trading, backtesting, and Telegram reporting.

## Quick Start

```bash
cd new-trading-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -c "from trading_bot.data.storage.database import db; db.init_db()"
python main.py --mode paper --test
```

Key `.env` options:
- `ENVIRONMENT=paper|live`
- `BROKER_PROVIDER=mock|groww|http`
- `GROWW_TOKEN_MODE=approval|totp|access_token`
- `BROKER_BASE_URL=https://api.groww.in` (default for `groww`; required for `http`)
- `MARKET_DATA_PROVIDER=auto|yfinance|groww` (historical OHLCV source selection)
- `GROWW_HISTORICAL_EXCHANGE`, `GROWW_HISTORICAL_SEGMENT`, `GROWW_HISTORICAL_INTERVAL`, `GROWW_HISTORICAL_CHUNK_DAYS`
- `RECONCILIATION_ENFORCE_CLOSE=0|1` (auto-close local OPEN trades missing at broker)
- `RECONCILIATION_LOOKBACK_DAYS=30` (lookback for open-trade reconciliation)
- `AUDIT_TREND_LOOKBACK=8` (number of weekly audit artifacts used for drift checks)
- `RETENTION_DAYS=30` and `RETENTION_SOURCES=...` (scheduled artifact rotation scope)
- `PAPER_RUN_REQUIRED_WEEKS=4` and `PAPER_RUN_REQUIRE_PROMOTION_BUNDLE=1` (paper-run gate behavior)
- `AUTO_RESUME_ENABLED=1` and `AUTO_RESUME_*` windows (restart recovery for missed routines)
- `STRATEGY_PROFILE=baseline|tuned_momentum_v2|tuned_momentum_v3|tuned_momentum_v4|tuned_momentum_v5|tuned_momentum_v6` (runtime strategy/risk preset)
- `ENABLE_MOMENTUM_BREAKOUT`, `ENABLE_MEAN_REVERSION`, `ENABLE_SECTOR_ROTATION` (toggle strategies)
- `RISK_PER_TRADE`, `MAX_POSITION_SIZE`, `TOTAL_COST_PER_TRADE`, `COST_PER_SIDE`, `MAX_SIGNALS_PER_DAY`, `MIN_EXPECTED_EDGE_PCT` and `MOMENTUM_*`, `MEAN_REV_*` (parameter overrides without code edits)
- `MOMENTUM_ENABLE_REGIME_FILTER`, `MOMENTUM_REGIME_SMA_PERIOD`, `MOMENTUM_REGIME_VOL_WINDOW`, `MOMENTUM_REGIME_MAX_ANNUAL_VOL` (market-regime gate for momentum entries)

## Core Features

- Momentum breakout, mean reversion, and sector rotation strategies
- Historical backtesting and walk-forward evaluation
- Risk controls: position sizing, heat limits, daily/weekly loss caps
- Paper mode by default, with pluggable broker interface for live mode
- Telegram alerts for startup, entries, exits, and morning summary

## Project Layout

```text
trading_bot/
  config/
  data/
    collectors/
    processors/
    storage/
  strategies/
  backtesting/
  execution/
  risk/
  reporting/
  monitoring/
main.py
paper_trading.py
scripts/backfill_data.py
```

## Development Commands

- `python main.py --mode paper --test`: run one-cycle dry run
- `STRATEGY_PROFILE=tuned_momentum_v2 python main.py --mode paper --test`: run paper dry run with tuned momentum profile
- `STRATEGY_PROFILE=tuned_momentum_v3 python main.py --mode paper --test`: run paper dry run with higher-turnover tuned profile
- `STRATEGY_PROFILE=tuned_momentum_v4 python main.py --mode paper --test`: run paper dry run with quality-focused momentum profile
- `STRATEGY_PROFILE=tuned_momentum_v5 python main.py --mode paper --test`: run paper dry run with gate-focused momentum profile (improved win-rate / reduced drawdown in latest sweep)
- `STRATEGY_PROFILE=tuned_momentum_v6 python main.py --mode paper --test`: run paper dry run with lower-risk, higher-expectancy momentum profile
- `python main.py --mode live --dry-run-live --test`: exercise live dependencies without placing broker orders
- `python scripts/backfill_data.py --start-date 2022-01-01 --limit 30`: load historical data
- `python scripts/backfill_data.py --provider groww --use-fallback-universe --start-date 2025-01-01 --limit 60`: backfill using Groww historical API
- `python scripts/preflight_check.py --pretty`: run env + database health checks
- `python scripts/preflight_check.py --include-broker --fail-on-broker --pretty`: include broker read-only check
- `python scripts/weekly_performance_audit.py --pretty --export-json`: run go-live audit and export JSON artifact
- `python scripts/promotion_checklist.py --include-broker --fail-on-broker --pretty --allow-not-ready`: run full promotion gate and bundle reports
- `python scripts/paper_run_tracker.py --required-weeks 4 --require-promotion-bundle --pretty`: verify continuous paper-run readiness
- `python scripts/weekly_audit_trend.py --lookback 8 --pretty --export-json`: summarize multi-week audit drift and export trend artifact
- `python scripts/retention_rotate.py --retention-days 30 --pretty --export-json`: archive old logs/report artifacts
- `python scripts/storage_profile.py --pretty --export-json`: profile artifact growth and suggest retention tuning
- `python scripts/tune_strategies.py --start-date 2025-01-01 --end-date 2026-02-11 --top-k 10`: tune entry parameters
- `python scripts/tune_exit_risk.py --start-date 2025-01-01 --end-date 2026-02-11 --top-k 10 --max-combos 120`: tune exits + risk sizing
- `python scripts/validate_tuned_momentum.py --start-date 2025-01-01 --end-date 2026-02-11 --holdout-start 2025-10-01`: compare default vs tuned momentum on holdout windows
- `python scripts/groww_live_smoke.py`: read-only Groww auth/funds/positions smoke test
- `python scripts/groww_live_smoke.py --place-order --force YES_PLACE_LIVE_ORDER --simulate-funds 50000`: simulate funded order path
- `python scripts/groww_live_smoke.py --place-order --simulate-roundtrip --persist-db --force YES_PLACE_LIVE_ORDER --simulate-funds 50000`: simulate and persist one closed roundtrip
- `python scripts/rollback_live.py --enable-kill-switch --cancel-open-orders --force YES_ROLLBACK --dry-run --pretty`: guarded rollback helper for live incidents
- `python scripts/ops_controls.py kill-switch on --reason "manual emergency"`: enable kill switch
- `python scripts/ops_controls.py incident-note --title "Broker outage" --details "Order API failing"`: create incident record
- `python paper_trading.py`: deterministic date-by-date replay simulation
- `pytest -q`: run tests
- `python -m trading_bot.backtesting.walk_forward`: add your own test harness for WFA

Windows long-running PC:
- `powershell -ExecutionPolicy Bypass -File .\scripts\windows\bootstrap_windows.ps1 -TaskName TradingBotPaper`: one-click Windows setup + safe paper autorun install
- `powershell -ExecutionPolicy Bypass -File .\scripts\windows\install_startup_task.ps1 -TaskName TradingBotPaper`: install auto-start task
- `powershell -ExecutionPolicy Bypass -File .\scripts\windows\manage_startup_task.ps1 -Action status -TaskName TradingBotPaper`: task status
- `powershell -ExecutionPolicy Bypass -File .\scripts\windows\run_paper_bot.ps1`: run resilient paper runner manually

## Notes

- `BrokerInterface` supports `mock`, `groww`, and generic `http` providers.
- Groww integration uses the documented token flow (`/v1/token/api/access`) and trading endpoints (`/v1/order/*`, `/v1/positions/user`, `/v1/margins/detail/user`).
- Groww historical candles automatically fall back from `/v1/historical/candles` to `/v1/historical/candle/range` when the primary endpoint is unavailable for the account.
- In live mode, reconciliation runs on schedule (`10:05`, `12:05`, `14:05`, `16:05`) to compare broker positions vs local OPEN trades.
- Backtests now use a warmup lookback window before `start_date` so short-horizon tuning has valid indicator history.
- Simulation mode bootstraps universe from local `price_data` first, avoiding external symbol-list dependency during replay runs.
- Risk limits in simulation now reset on replay day/week boundaries (supports backward/forward time jumps during historical replays).
- Weekly automation includes audit export (`18:10` Sunday), trend analysis (`18:20` Sunday), paper-run status (`18:25` Sunday), and retention rotation (`18:30` Sunday).
- SQLite is used by default for easy local setup.
- Keep `ENVIRONMENT=paper` until risk validation criteria are met.

## Operations Docs

- `docs/LIVE_ROLLOUT_RUNBOOK.md`: staged go-live, rollback, and incident workflow.
- `docs/PAPER_RUN_ACCEPTANCE.md`: 4-week paper-run acceptance criteria and sign-off checklist.
- `docs/WINDOWS_AUTORUN.md`: Windows Task Scheduler setup for long-running paper mode.
- `docs/WINDOWS_MIGRATION_SETUP.md`: move project to Windows PC (Git/zip), preserve paper-run state, and bring up safe paper autorun.

## Disclaimer

Educational project. Trading involves risk. Validate strategy behavior extensively in paper mode before live deployment.
